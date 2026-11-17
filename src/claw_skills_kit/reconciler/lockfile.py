from __future__ import annotations

import json
import re
from collections.abc import Mapping

_HEX64 = re.compile(r"[0-9a-f]{64}")


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


def dump_pins(revisions: Mapping[str, str]) -> str:
    return json.dumps({"skills": dict(sorted(revisions.items()))}, indent=2) + "\n"
