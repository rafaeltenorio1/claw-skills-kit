"""Evidence of every change made to a host: the approval before it, the outcome after it.

The spec: "approvals come from a human in chat, recorded, before any mutating step" and "every phase leaves its
evidence on disk". When CSK_EVIDENCE names a file, each applying command appends two JSON lines with one id:

  {"id", "phase": "approved", "ts", "command", "action", "target", "approval"}   before anything is written
  {"id", "phase": "result",   "ts", "status", ...what changed}                   after it

"What changed" is copied from the command's own JSON report, which by contract holds paths, hashes, keys and
variable names, never answer values or secrets. Lines are appended and fsync'ed, so an approval is on disk even if
the change is interrupted. Without CSK_EVIDENCE nothing is recorded.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

ENV = "CSK_EVIDENCE"
_RESULT_KEYS = (
    "status", "action", "skill", "key", "files", "changes", "env", "api_key_ref", "ready", "discarded_answer",
    "discarded_answers", "revisions", "pending_answers", "removed_answers", "unrestored", "error", "findings",
    "backup", "backed_up",
)


def evidence_path() -> Path | None:
    value = os.environ.get(ENV, "").strip()
    return Path(value) if value else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _append(path: Path, record: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


def record_approval(path: Path, command: str, action: str | None, target: str, approval: str) -> str:
    record_id = uuid.uuid4().hex[:12]
    _append(path, {
        "id": record_id, "phase": "approved", "ts": _now(), "command": command, "action": action,
        "target": target, "approval": approval,
    })
    return record_id


def record_result(path: Path, record_id: str, payload: dict[str, object] | None, exit_code: int) -> None:
    payload = payload or {}
    result = {k: payload[k] for k in _RESULT_KEYS if k in payload}
    result.setdefault("status", "unknown")
    _append(path, {"id": record_id, "phase": "result", "ts": _now(), "exit_code": exit_code, **result})


def history(path: Path, limit: int = 20) -> list[dict[str, object]]:
    """One entry per change, newest first: the approval merged with its result."""
    if not path.is_file():
        return []
    entries: dict[str, dict[str, object]] = {}
    order: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue  # a torn last line after a crash; the rest stays readable
        record_id = record.get("id")
        if not isinstance(record_id, str):
            continue
        if record.get("phase") == "approved":
            entries[record_id] = {k: v for k, v in record.items() if k != "phase"}
            entries[record_id]["status"] = "interrupted"  # until a result says otherwise
            order.append(record_id)
        elif record.get("phase") == "result" and record_id in entries:
            done = {k: v for k, v in record.items() if k not in ("id", "phase")}
            done["finished"] = done.pop("ts", None)
            entries[record_id].update(done)
    return [entries[i] for i in reversed(order)][:limit]
