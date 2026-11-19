"""Enable or disable a skill's integration in one gateway's config (skills.entries.<skill>).

A skill declares what it needs in its SKILL.md frontmatter (metadata.openclaw.requires.env, primaryEnv) and OpenClaw
does not load it until those variables are provided. This module only orchestrates OpenClaw's own commands
(`config file`, `config set --batch-json`, `config unset`, `config validate`, `skills check --json`); it never edits
openclaw.json itself and never edits the skill.

Rules:
- Only variables the skill declares in requires.env can be set.
- The skill's primaryEnv (its API key) is never given a value: only a SecretRef to an environment variable that a
  person fills on the host ({source: env, provider: default, id: VAR}).
- A value that looks like a secret is refused.
- Snapshots come from the config FILE: `config get` redacts SecretRef ids, so restoring from it would write a wrong
  reference.
- Reports carry variable names only, never values.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_SECRET_LIKE = (
    re.compile(r"^(sk|pk|rk|xox[abpr]|ghp|gho|github_pat|glpat|AKIA|AIza)[-_A-Za-z0-9]{8,}"),
    re.compile(r"^[A-Za-z0-9+/_\-=]{32,}$"),  # long unbroken token
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)
_MAX_VALUE = 200


class IntegrationError(Exception):
    """A refusal before anything is written, or a failed apply. `status` is a stable machine-readable code."""

    def __init__(self, status: str, message: str, unrestored: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.status = status
        self.unrestored = tuple(unrestored)


@dataclass(frozen=True)
class Requirements:
    env: tuple[str, ...] = ()
    primary_env: str | None = None


@dataclass(frozen=True)
class Plan:
    skill: str
    action: str  # enable | disable
    entry_before: dict | None  # skills.entries.<skill> as it is in the config file now
    entry_after: dict | None  # what it will be (None = removed)
    env_names: tuple[str, ...] = ()  # names only, for the report
    api_key_ref: bool = False

    @property
    def changed(self) -> bool:
        return self.entry_before != self.entry_after


# --- reading the skill ---------------------------------------------------------------------------

def _frontmatter(skill_md: str) -> list[str]:
    lines = skill_md.splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return lines[1:i]
    return []


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def read_requirements(skill_md: str) -> Requirements:
    """requires.env and primaryEnv from `metadata.openclaw` (block YAML, inline or dash lists).

    Only the YAML subset of the operator template is understood; an `openclaw` block written as a JSON5 object on
    one line is refused rather than misread.
    """
    lines = _frontmatter(skill_md)
    env: list[str] = []
    primary: str | None = None
    path: list[tuple[int, str]] = []  # (indent, key) of the open YAML mappings
    pending_list: str | None = None
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        ind, text = _indent(line), line.strip()
        if text.startswith("- ") and pending_list == "env":
            env.append(text[2:].strip().strip("'\""))
            continue
        pending_list = None
        while path and path[-1][0] >= ind:
            path.pop()
        key, _, value = text.partition(":")
        key, value = key.strip(), value.strip()
        keys = [k for _, k in path]
        if keys == ["metadata"] and key == "openclaw" and value:
            raise IntegrationError("invalid_skill", "metadata.openclaw must be written as a YAML block.")
        if keys == ["metadata", "openclaw", "requires"] and key == "env":
            if value.startswith("[") and value.endswith("]"):
                env.extend(v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip())
            elif not value:
                pending_list = "env"
            else:
                raise IntegrationError("invalid_skill", "requires.env must be a list.")
        elif keys == ["metadata", "openclaw"] and key == "primaryEnv":
            primary = value.strip("'\"") or None
        if not value:
            path.append((ind, key))
    for name in [*env, *([primary] if primary else [])]:
        if not _ENV_NAME.match(name):
            raise IntegrationError("invalid_skill", f"Invalid variable name in the skill: {name!r}.")
    return Requirements(tuple(env), primary)


# --- planning --------------------------------------------------------------------------------------

def _looks_like_secret(value: str) -> bool:
    return any(p.search(value) for p in _SECRET_LIKE)


def plan_enable(
    skill: str,
    requirements: Requirements,
    entry_before: dict | None,
    env: Mapping[str, str],
    api_key_env: str | None = None,
) -> Plan:
    if not env and api_key_env is None:
        raise IntegrationError("invalid_integration", "Nothing to enable: give --env and/or --api-key-env.")
    for name, value in env.items():
        if name == requirements.primary_env:
            raise IntegrationError(
                "secret_value_refused",
                f"{name} is this skill's key: it takes a reference (--api-key-env), never a value.",
            )
        if name not in requirements.env:
            raise IntegrationError("not_required", f"The skill does not declare {name} in requires.env.")
        if not value.strip() or "\n" in value or len(value) > _MAX_VALUE:
            raise IntegrationError("invalid_integration", f"The value for {name} must be one short line.")
        if _looks_like_secret(value.strip()):
            raise IntegrationError(
                "looks_like_secret", f"The value for {name} looks like a secret; secrets are never written here."
            )
    after = json.loads(json.dumps(entry_before)) if entry_before else {}
    if after.get("enabled") is False:
        # Observed on 2026.11.3: OpenClaw writes `enabled: false` for a skill it found with missing requirements.
        # Enabling the integration is the client's explicit choice, so the skill is switched back on.
        after["enabled"] = True
    if env:
        after.setdefault("env", {}).update({k: v.strip() for k, v in env.items()})
    if api_key_env is not None:
        if requirements.primary_env is None:
            raise IntegrationError("no_primary_env", "The skill declares no primaryEnv, so it takes no API key.")
        if not _ENV_NAME.match(api_key_env):
            raise IntegrationError("invalid_integration", f"Invalid environment variable name: {api_key_env!r}.")
        after["apiKey"] = {"source": "env", "provider": "default", "id": api_key_env}
    return Plan(skill, "enable", entry_before, after, tuple(sorted(env)), api_key_env is not None)


def plan_disable(skill: str, requirements: Requirements, entry_before: dict | None) -> Plan:
    """Remove what enable sets (the declared env vars and apiKey); anything else in the entry stays."""
    if entry_before is None:
        return Plan(skill, "disable", None, None)
    after = json.loads(json.dumps(entry_before))
    env = after.get("env") or {}
    removed = tuple(sorted(k for k in env if k in requirements.env))
    for name in removed:
        del env[name]
    if not env:
        after.pop("env", None)
    had_key = after.pop("apiKey", None) is not None
    return Plan(skill, "disable", entry_before, after or None, removed, had_key)


# --- OpenClaw CLI ----------------------------------------------------------------------------------

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


def _default_runner(argv: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=120, check=False)


class OpenClaw:
    """The few OpenClaw commands this module needs. Output is parsed, never copied into reports."""

    def __init__(self, command: Sequence[str] | None = None, runner: Runner | None = None) -> None:
        self.command = list(command or shlex.split(os.environ.get("CSK_OPENCLAW", "openclaw")))
        self.run = runner or _default_runner

    def _call(self, *args: str) -> subprocess.CompletedProcess:
        try:
            return self.run([*self.command, *args])
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise IntegrationError("openclaw_failed", f"openclaw could not run: {type(exc).__name__}") from None

    def config_file(self) -> Path:
        done = self._call("config", "file")
        lines = [ln.strip() for ln in done.stdout.splitlines() if ln.strip()]
        if done.returncode != 0 or not lines:
            raise IntegrationError("openclaw_failed", "openclaw config file failed.")
        return Path(os.path.expanduser(lines[-1]))

    def set_entry(self, skill: str, entry: dict | None) -> None:
        path = f"skills.entries.{skill}"
        if entry is None:
            done = self._call("config", "unset", path)
        else:
            done = self._call("config", "set", "--batch-json", json.dumps([{"path": path, "value": entry}]))
        if done.returncode != 0:
            raise IntegrationError("openclaw_failed", f"openclaw config {'unset' if entry is None else 'set'} failed.")

    def validate(self) -> bool:
        return self._call("config", "validate").returncode == 0

    def _skills_check(self) -> dict:
        done = self._call("skills", "check", "--json")
        try:
            data = json.loads(done.stdout)
        except json.JSONDecodeError:
            raise IntegrationError("openclaw_failed", "openclaw skills check did not return JSON.") from None
        if not isinstance(data, dict):
            raise IntegrationError("openclaw_failed", "openclaw skills check returned an unexpected shape.")
        return data

    @staticmethod
    def _names(items: object) -> set[str]:
        if not isinstance(items, list):
            return set()
        return {x if isinstance(x, str) else x.get("name") for x in items if isinstance(x, (str, dict))} - {None}

    def skill_ready(self, skill: str) -> bool:
        return skill in self._names(self._skills_check().get("eligible"))

    def rescan_skills(self, config_file: Path) -> None:
        """Make the Gateway rediscover skills now, then put `skills.load.watch` back as it was.

        Observed on 2026.11.3: skill files changed on disk show up in `skills check` only after the watcher's next
        pass (up to about a minute), and a config write that changes nothing ("No change") does not rescan. A real
        change to a skills setting does. So the watch flag is flipped and restored: two real changes, one rescan,
        and the config ends as it started (an absent key is removed again).
        """
        try:
            data = json.loads(config_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise IntegrationError("config_unreadable", f"Cannot read the gateway config: {type(exc).__name__}") from None
        load = ((data.get("skills") or {}).get("load") or {})
        original = load.get("watch")
        path = "skills.load.watch"
        steps = [self._call("config", "set", "--batch-json", json.dumps([{"path": path, "value": original is False}]))]
        if original is None:
            steps.append(self._call("config", "unset", path))
        else:
            steps.append(self._call("config", "set", "--batch-json", json.dumps([{"path": path, "value": original}])))
        if any(done.returncode != 0 for done in steps):
            raise IntegrationError("openclaw_failed", "openclaw could not refresh the skill list.")

    def skill_inventory(self) -> set[str]:
        """Every skill OpenClaw discovered, whatever its state (each list in `skills check --json`)."""
        names: set[str] = set()
        for value in self._skills_check().values():
            names |= self._names(value)
        return names


def read_entry(config_file: Path, skill: str) -> dict | None:
    try:
        data = json.loads(config_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegrationError("config_unreadable", f"Cannot read the gateway config: {type(exc).__name__}") from None
    entry = ((data.get("skills") or {}).get("entries") or {}).get(skill)
    return entry if isinstance(entry, dict) else None


def apply_plan(openclaw: OpenClaw, config_file: Path, plan: Plan) -> bool:
    """Write the plan, then check config validity and whether the skill loads as expected.

    Returns the skill's readiness after the change. On any failure the entry is put back and verified by
    reading the config file: status `rolled_back`, or `rollback_failed` with the entry path in `unrestored`.
    """
    if not plan.changed:
        return openclaw.skill_ready(plan.skill)
    error = "apply failed"
    try:
        openclaw.set_entry(plan.skill, plan.entry_after)
        if not openclaw.validate():
            error = "the gateway config is not valid after the change"
        else:
            ready = openclaw.skill_ready(plan.skill)
            expected = plan.action == "disable" or ready
            if expected:
                return ready
            error = "the skill still does not load after the change"
    except IntegrationError as exc:
        error = str(exc)
    try:
        openclaw.set_entry(plan.skill, plan.entry_before)
    except IntegrationError:
        pass
    path = f"skills.entries.{plan.skill}"
    try:
        restored = read_entry(config_file, plan.skill) == plan.entry_before
    except IntegrationError:
        restored = False
    if not restored:
        raise IntegrationError("rollback_failed", f"{error}; restore failed", unrestored=[path])
    raise IntegrationError("rolled_back", f"{error}; the config was put back")


@dataclass(frozen=True)
class Status:
    skill: str
    required_env: tuple[str, ...]
    primary_env: str | None
    configured_env: tuple[str, ...]
    api_key_ref: bool
    ready: bool
    missing_env: tuple[str, ...] = field(default=())


def status_of(skill: str, requirements: Requirements, entry: dict | None, ready: bool) -> Status:
    configured = tuple(sorted((entry or {}).get("env") or {}))
    has_key = isinstance((entry or {}).get("apiKey"), dict)
    missing = tuple(
        n for n in requirements.env
        if n not in configured and not (n == requirements.primary_env and has_key) and n not in os.environ
    )
    return Status(skill, requirements.env, requirements.primary_env, configured, has_key, ready, missing)
