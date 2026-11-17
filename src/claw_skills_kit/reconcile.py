from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from claw_skills_kit.interview import InterviewError, apply_answers, missing_required
from claw_skills_kit.reconciler.descriptor import (
    DescriptorError,
    HostDescriptor,
    TenantConflictError,
    check_single_tenant,
)
from claw_skills_kit.reconciler.hashing import revision_of, sha256_hex
from claw_skills_kit.reconciler.host import Host
from claw_skills_kit.reconciler.layout import ANSWERS_FILE, SKILL_FILE, TEMPLATE_FILE
from claw_skills_kit.reconciler.smoke import Check, IntegrityCheck, SmokeResult, run_checks
from claw_skills_kit.template_format import FillError, TemplateFormatError, fill_answers, parse_template


class ReconcileError(Exception):
    """A refusal before anything is written. `status` is a stable machine-readable code."""

    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Change:
    path: str
    action: str
    before: str | None 
    after: str | None  


@dataclass(frozen=True)
class Report:
    status: str  
    host_id: str
    changes: tuple[Change, ...] = ()
    revisions: Mapping[str, str] = field(default_factory=dict)
    pending_answers: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    removed_answers: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    smoke: SmokeResult | None = None
    error: str | None = None
    unrestored: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """JSON-ready. Contains paths, hashes and answer KEYS only, never answer values."""
        return {
            "status": self.status,
            "host_id": self.host_id,
            "changes": [
                {"path": c.path, "action": c.action, "before": c.before, "after": c.after}
                for c in self.changes
            ],
            "revisions": dict(self.revisions),
            "pending_answers": {k: list(v) for k, v in self.pending_answers.items()},
            "removed_answers": {k: list(v) for k, v in self.removed_answers.items()},
            "smoke": None
            if self.smoke is None
            else {
                "ok": self.smoke.ok,
                "checks": [{"name": o.name, "ok": o.ok, "detail": o.detail} for o in self.smoke.outcomes],
            },
            "error": self.error,
            "unrestored": list(self.unrestored),
        }


# --- reading the library -----------------------------------------------------------

def _check_skill_name(skill: str) -> None:
    if "/" in skill or "\\" in skill or skill.startswith("."):
        raise ReconcileError("invalid_skill", f"Invalid skill name: {skill!r}.")


def _library_files(library: Host, skill: str) -> dict[str, bytes]:
    """The skill's files, keyed by path relative to the skill directory."""
    _check_skill_name(skill)
    files: dict[str, bytes] = {}
    for path in library.files(skill):
        rel = path[len(skill) + 1 :]
        if rel == ANSWERS_FILE:  
            continue
        data = library.read(path)
        if data is not None:
            files[rel] = data
    if not files:
        raise ReconcileError("skill_not_in_library", f"Skill '{skill}' is not in the library.")
    if SKILL_FILE not in files:
        raise ReconcileError("invalid_skill", f"Skill '{skill}' has no {SKILL_FILE}.")
    return files


def compute_revisions(library: Host, skills: Sequence[str]) -> dict[str, str]:
    """Revision (content hash) of each skill as it is in the library right now."""
    return {skill: revision_of(_library_files(library, skill)) for skill in skills}


# --- answers: keep what the client already said ------------------------------------

def _merge_answers(skill: str, template_text: str, existing: bytes | None) -> tuple[bytes, list[str], list[str]]:
    """Returns (rendered client-config.md, pending keys, removed keys)."""
    try:
        new = parse_template(template_text)
    except TemplateFormatError as exc:
        raise ReconcileError("invalid_template", f"Skill '{skill}': {exc}") from exc

    carried: dict[str, str] = {}
    removed: list[str] = []
    if existing is not None:
        try:
            old = parse_template(existing.decode("utf-8"))
        except (UnicodeDecodeError, TemplateFormatError) as exc:
            raise ReconcileError(
                "invalid_existing_config",
                f"Skill '{skill}': the client-config.md on the host cannot be read; nothing was changed.",
            ) from exc
        known = {f.key for f in new.fields}
        for f in old.fields:
            if not f.answer.strip():
                continue
            if f.key in known:
                carried[f.key] = f.answer
            else:
                removed.append(f.key)  

    try:
        merged = apply_answers(new, carried)
        rendered = fill_answers(template_text, merged)
    except (InterviewError, FillError) as exc:
        raise ReconcileError("invalid_existing_config", f"Skill '{skill}': {exc}") from exc
    pending = [f.key for f in missing_required(merged)]
    return rendered.encode("utf-8"), pending, removed


# --- planning ---------------------------------------------------------------------

def reconcile(
    descriptor: HostDescriptor,
    library: Host,
    target: Host,
    pins: Mapping[str, str],
    *,
    apply: bool = False,
    extra_checks: Callable[[], Sequence[Check]] | None = None,
) -> Report:
    """Plan the change, and with apply=True carry it out with snapshot and rollback."""
    try:
        check_single_tenant(descriptor)
    except DescriptorError as exc:
        status = "tenant_conflict" if isinstance(exc, TenantConflictError) else "invalid_descriptor"
        raise ReconcileError(status, str(exc)) from exc

    desired: dict[str, bytes] = {}
    revisions: dict[str, str] = {}
    pending: dict[str, tuple[str, ...]] = {}
    removed: dict[str, tuple[str, ...]] = {}

    for skill in descriptor.skills:
        files = _library_files(library, skill)
        revision = revision_of(files)
        if skill not in pins:
            raise ReconcileError("unpinned_skill", f"Skill '{skill}' has no pinned revision.")
        if pins[skill] != revision:
            raise ReconcileError(
                "library_revision_mismatch",
                f"Skill '{skill}': library is at {revision[:12]}, pin says {pins[skill][:12]}.",
            )
        revisions[skill] = revision
        for rel, data in files.items():
            desired[f"{skill}/{rel}"] = data
        if TEMPLATE_FILE in files:
            rendered, p, r = _merge_answers(
                skill, files[TEMPLATE_FILE].decode("utf-8"), target.read(f"{skill}/{ANSWERS_FILE}")
            )
            desired[f"{skill}/{ANSWERS_FILE}"] = rendered
            if p:
                pending[skill] = tuple(p)
            if r:
                removed[skill] = tuple(r)

    changes = _diff(target, descriptor.skills, desired)
    base = dict(
        host_id=descriptor.host_id,
        changes=changes,
        revisions=revisions,
        pending_answers=pending,
        removed_answers=removed,
    )
    if not changes:
        return Report(status="unchanged", **base)
    if not apply:
        return Report(status="planned", **base)
    return _apply(descriptor, target, desired, changes, extra_checks, base)


def _diff(target: Host, skills: Sequence[str], desired: Mapping[str, bytes]) -> tuple[Change, ...]:
    changes = []
    for path, data in desired.items():
        current = target.read(path)
        if current is None:
            changes.append(Change(path, "create", None, sha256_hex(data)))
        elif current != data:
            changes.append(Change(path, "update", sha256_hex(current), sha256_hex(data)))
    for skill in skills:  # only inside managed skills; other skills on the host are left alone
        for path in target.files(skill):
            if path not in desired:
                current = target.read(path) or b""
                changes.append(Change(path, "delete", sha256_hex(current), None))
    return tuple(sorted(changes, key=lambda c: c.path))


# --- applying, with rollback -----------------------------------------------------

_UNREADABLE = object()


def _restore(target: Host, snapshot: Mapping[str, bytes | None]) -> tuple[str, ...]:
    """Put every touched path back as it was. Returns the paths that could NOT be restored."""
    for path, before in snapshot.items():
        try:
            if before is None:
                target.delete(path)
            else:
                target.write(path, before)
        except Exception:  
            pass
    bad = []
    for path, before in snapshot.items():
        try:
            now: object = target.read(path)
        except Exception: 
            now = _UNREADABLE
        if now != before:
            bad.append(path)
    return tuple(sorted(bad))


def _apply(
    descriptor: HostDescriptor,
    target: Host,
    desired: Mapping[str, bytes],
    changes: tuple[Change, ...],
    extra_checks: Callable[[], Sequence[Check]] | None,
    base: dict[str, object],
) -> Report:
    snapshot = {c.path: target.read(c.path) for c in changes}
    smoke: SmokeResult | None = None
    error: str | None = None
    try:
        for change in changes:
            if change.action == "delete":
                target.delete(change.path)
            else:
                target.write(change.path, desired[change.path])
        checks = [IntegrityCheck(target, desired, descriptor.skills), *(extra_checks() if extra_checks else ())]
        smoke = run_checks(checks)
        if smoke.ok:
            return Report(status="applied", smoke=smoke, **base)
    except Exception as exc:  
        error = f"apply failed: {type(exc).__name__}" 

    unrestored = _restore(target, snapshot)
    status = "rollback_failed" if unrestored else "rolled_back"
    return Report(status=status, smoke=smoke, error=error, unrestored=unrestored, **base)
