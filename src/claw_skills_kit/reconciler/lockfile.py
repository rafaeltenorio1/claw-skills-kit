from __future__ import annotations

import json
import re
from collections.abc import Mapping

_HEX64 = re.compile(r"[0-9a-f]{64}")
_VERSION = re.compile(r"[0-9][0-9A-Za-z.+-]{0,63}")
RUNTIME_KEYS = ("openclaw", "node")  # runtime pinned besides skill revisions


class LockfileError(ValueError):
    """The pins file is malformed."""


def load_pins(text: str) -> dict[str, str]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LockfileError(f"Pins file is not valid JSON (line {exc.lineno}): {exc.msg}.") from exc
    skills = data.get("skills") if isinstance(data, dict) else None
    if not isinstance(skills, dict):
        raise LockfileError("Pins file must be an object with a 'skills' object.")
    for name, revision in skills.items():
        if not isinstance(revision, str) or not _HEX64.fullmatch(revision):
            raise LockfileError(f"Pin for '{name}' must be a 64-character lowercase sha256 hex string.")
    return dict(skills)


def load_runtime_pins(text: str) -> dict[str, str]:
    """The optional "runtime" block: the OpenClaw and Node versions the host must run. Empty when absent."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LockfileError(f"Pins file is not valid JSON (line {exc.lineno}): {exc.msg}.") from exc
    runtime = data.get("runtime", {}) if isinstance(data, dict) else {}
    if not isinstance(runtime, dict) or set(runtime) - set(RUNTIME_KEYS):
        raise LockfileError(f"'runtime' must be an object with only {', '.join(RUNTIME_KEYS)}.")
    for key, version in runtime.items():
        if not isinstance(version, str) or not _VERSION.fullmatch(version):
            raise LockfileError(f"runtime.{key} must be a version such as 2026.11.3.")
    return dict(runtime)


def dump_pins(revisions: Mapping[str, str], runtime: Mapping[str, str] | None = None) -> str:
    data: dict[str, object] = {"skills": dict(sorted(revisions.items()))}
    if runtime:
        data["runtime"] = {k: runtime[k] for k in RUNTIME_KEYS if k in runtime}
    return json.dumps(data, indent=2) + "\n"
