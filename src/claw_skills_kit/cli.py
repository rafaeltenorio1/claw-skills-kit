import argparse
import json
import sys
import traceback
from pathlib import Path

from claw_skills_kit.interview import InterviewError, apply_answers, load_answers, missing_required
from claw_skills_kit.reconcile import ReconcileError, compute_revisions, reconcile
from claw_skills_kit.reconciler.descriptor import DescriptorError, load_descriptor
from claw_skills_kit.reconciler.host import LocalHost
from claw_skills_kit.reconciler.lockfile import LockfileError, dump_pins, load_pins
from claw_skills_kit.reconciler.smoke import CommandCheck
from claw_skills_kit.template_format import FillError, TemplateFormatError, fill_answers, parse_template

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_INVALID_TEMPLATE = 3
EXIT_INVALID_ANSWERS = 4
EXIT_MISSING_ANSWERS = 5
EXIT_ROLLED_BACK = 6
EXIT_ROLLBACK_FAILED = 7
EXIT_TENANT_CONFLICT = 8
EXIT_PIN = 9
EXIT_INVALID_INPUT = 10
EXIT_SKILL = 11
EXIT_EXISTING_CONFIG = 12

# ReconcileError.status -> exit code. A status not listed here is treated as a bug (exit 1).
_REFUSAL_CODES = {
    "tenant_conflict": EXIT_TENANT_CONFLICT,
    "invalid_descriptor": EXIT_INVALID_INPUT,
    "library_revision_mismatch": EXIT_PIN,
    "unpinned_skill": EXIT_PIN,
    "skill_not_in_library": EXIT_SKILL,
    "invalid_skill": EXIT_SKILL,
    "invalid_template": EXIT_INVALID_TEMPLATE,
    "invalid_existing_config": EXIT_EXISTING_CONFIG,
}

TEMPLATE_FILE = "client-config.template.md"


class _Refusal(Exception):
    """A run that must stop with a reportable status (a refusal, not a bug)."""

    def __init__(self, status: str, code: int, **details: object) -> None:
        super().__init__(status)
        self.status = status
        self.code = code
        self.details = details


def _build_parser() -> argparse.ArgumentParser:
    """`fill` subcommand: skill_dir (positional), --answers and --out (both required)."""
    parser = argparse.ArgumentParser(prog="claw-skills-kit")
    subparsers = parser.add_subparsers(dest="command", required=True)

    fill_parser = subparsers.add_parser(
        "fill",
        help="Fill a skill's client-config.template.md with answers from a JSON file.",
    )
    fill_parser.add_argument(
        "skill_dir",
        type=Path,
        help="Path to the skill directory containing client-config.template.md.",
    )
    fill_parser.add_argument(
        "--answers",
        type=Path,
        required=True,
        help="Path to the client answers JSON file.",
    )
    fill_parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Destination path for the filled client-config.md.",
    )

    lock_parser = subparsers.add_parser(
        "lock", help="Write the pins file: the current revision of each named library skill."
    )
    lock_parser.add_argument("library", type=Path, help="Folder holding the skills.")
    lock_parser.add_argument("--skills", nargs="+", required=True, help="Skill names to pin.")
    lock_parser.add_argument("--out", type=Path, required=True, help="Where to write the pins file.")

    rec_parser = subparsers.add_parser(
        "reconcile",
        help="Bring a host's skills to the pinned library revision (dry run unless --apply).",
    )
    rec_parser.add_argument("--host", type=Path, required=True, help="Host descriptor JSON.")
    rec_parser.add_argument("--library", type=Path, required=True, help="Folder holding the skills.")
    rec_parser.add_argument("--target", type=Path, required=True, help="The host's skills folder.")
    rec_parser.add_argument("--pins", type=Path, required=True, help="Pins file (skills.lock.json).")
    rec_parser.add_argument(
        "--apply", action="store_true", help="Write the changes. Without it nothing is touched."
    )
    return parser


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    """Run the command and return the exit code. Never calls sys.exit itself."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "fill":
            return _run_fill(parser, args.skill_dir, args.answers, args.out)
        if args.command == "lock":
            return _run_lock(args.library, args.skills, args.out)
        if args.command == "reconcile":
            return _run_reconcile(args.host, args.library, args.target, args.pins, args.apply)
        parser.error(f"Unknown command: {args.command}")
    except _Refusal as refusal:
        _emit({"ok": False, "status": refusal.status, **refusal.details})
        return refusal.code
    except Exception as exc:  # noqa: BLE001 - a bug must still produce JSON for the caller
        traceback.print_exc(file=sys.stderr)  # details for the developer, off stdout
        _emit({"ok": False, "status": "unexpected_error", "error": str(exc)})
        return EXIT_UNEXPECTED


def _read_utf8(path: Path, status: str, code: int, what: str) -> str:
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise _Refusal(status, code, error=f"Cannot read {what}: {exc}") from None


def _write_if_changed(path: Path, data: bytes) -> bool:
    """Atomic write; returns False (and touches nothing) when the file is already right."""
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_bytes(data)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)  # no-op after a successful replace
    return True


def _run_fill(
    parser: argparse.ArgumentParser,
    skill_dir: Path,
    answers_path: Path,
    out_path: Path,
) -> int:
    template_path = skill_dir / TEMPLATE_FILE
    if out_path.resolve() == template_path.resolve():
        parser.error(f"--out must not point to the skill's own {TEMPLATE_FILE}.")

    # 1. Read and parse the template
    template_text = _read_utf8(template_path, "invalid_template", EXIT_INVALID_TEMPLATE, "template")
    try:
        template = parse_template(template_text)
    except TemplateFormatError as exc:
        raise _Refusal("invalid_template", EXIT_INVALID_TEMPLATE, error=str(exc)) from None

    # 2. Read, load and apply the answers
    answers_text = _read_utf8(answers_path, "invalid_answers", EXIT_INVALID_ANSWERS, "answers file")
    try:
        filled = apply_answers(template, load_answers(answers_text))
    except InterviewError as exc:
        raise _Refusal("invalid_answers", EXIT_INVALID_ANSWERS, error=str(exc)) from None

    # 3. Required answers must be complete before anything is written
    missing = missing_required(filled)
    if missing:
        raise _Refusal(
            "missing_required",
            EXIT_MISSING_ANSWERS,
            missing=[
                {"key": f.key, "comes_from": f.comes_from, "suggested": f.suggested}
                for f in missing
            ],
            error="Missing required answers: " + ", ".join(f.key for f in missing) + ".",
        )

    # 4. Fill the original text (only the Answer cells change)
    try:
        new_bytes = fill_answers(template_text, filled).encode("utf-8")
    except FillError as exc:
        raise _Refusal("invalid_answers", EXIT_INVALID_ANSWERS, error=str(exc)) from None

    # 5. Write (atomic, and only if the content actually changed)
    changed = _write_if_changed(out_path, new_bytes)

    # 6. Report
    _emit({"ok": True, "status": "ok", "changed": changed, "out": str(out_path)})
    return EXIT_OK


def _require_dir(path: Path, label: str) -> None:
    if not path.is_dir():
        raise _Refusal("invalid_input", EXIT_INVALID_INPUT, error=f"{label} is not a folder: {path}")


def _refuse(exc: ReconcileError) -> _Refusal:
    return _Refusal(exc.status, _REFUSAL_CODES.get(exc.status, EXIT_UNEXPECTED), error=str(exc))


def _run_lock(library: Path, skills: list[str], out_path: Path) -> int:
    _require_dir(library, "library")
    try:
        revisions = compute_revisions(LocalHost(library), skills)
    except ReconcileError as exc:
        raise _refuse(exc) from None
    changed = _write_if_changed(out_path, dump_pins(revisions).encode("utf-8"))
    _emit({"ok": True, "status": "ok", "changed": changed, "out": str(out_path), "skills": revisions})
    return EXIT_OK


def _run_reconcile(host_path: Path, library: Path, target: Path, pins_path: Path, apply: bool) -> int:
    descriptor_text = _read_utf8(host_path, "invalid_descriptor", EXIT_INVALID_INPUT, "host descriptor")
    try:
        descriptor = load_descriptor(descriptor_text)
    except DescriptorError as exc:
        raise _Refusal("invalid_descriptor", EXIT_INVALID_INPUT, error=str(exc)) from None

    pins_text = _read_utf8(pins_path, "invalid_pins", EXIT_INVALID_INPUT, "pins file")
    try:
        pins = load_pins(pins_text)
    except LockfileError as exc:
        raise _Refusal("invalid_pins", EXIT_INVALID_INPUT, error=str(exc)) from None

    _require_dir(library, "library")
    _require_dir(target, "target")  # a typo must not silently create a new folder

    def smoke_commands():
        return [
            CommandCheck(argv, timeout=descriptor.smoke.timeout_seconds)
            for argv in descriptor.smoke.commands
        ]

    try:
        report = reconcile(
            descriptor, LocalHost(library), LocalHost(target), pins, apply=apply, extra_checks=smoke_commands
        )
    except ReconcileError as exc:
        raise _refuse(exc) from None

    code = {"rolled_back": EXIT_ROLLED_BACK, "rollback_failed": EXIT_ROLLBACK_FAILED}.get(report.status, EXIT_OK)
    _emit({"ok": code == EXIT_OK, **report.to_dict()})
    return code
