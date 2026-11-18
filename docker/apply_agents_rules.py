"""Put the operator rules block at the top of a workspace AGENTS.md (idempotent).

Usage: python apply_agents_rules.py BLOCK_FILE AGENTS_MD

- A block already between the csk-rules markers is replaced, so a re-run never duplicates it.
- Otherwise the block goes before the first "## " section (OpenClaw's default file starts with "## Red Lines"),
  or at the end if the file has no section.
- Prints one JSON line: {"ok": true, "changed": bool}. Exit 1 if a file cannot be read.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

START = "<!-- csk-rules:start -->"
END = "<!-- csk-rules:end -->"
_EXISTING = re.compile(re.escape(START) + r".*?" + re.escape(END) + r"\n*", re.S)
_FIRST_SECTION = re.compile(r"^## ", re.M)


def apply_rules(block: str, text: str) -> str:
    block = block.strip("\n") + "\n\n"
    if START not in block or END not in block:
        raise ValueError("the block must be wrapped in csk-rules markers")
    text = _EXISTING.sub("", text, count=1)
    match = _FIRST_SECTION.search(text)
    if match is None:
        return text.rstrip("\n") + "\n\n" + block
    return text[: match.start()] + block + text[match.start():]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(json.dumps({"ok": False, "error": "usage: apply_agents_rules.py BLOCK_FILE AGENTS_MD"}))
        return 1
    block_path, target = Path(argv[0]), Path(argv[1])
    try:
        block = block_path.read_text(encoding="utf-8")
        before = target.read_text(encoding="utf-8")
        after = apply_rules(block, before)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    if after != before:
        target.write_text(after, encoding="utf-8")
    print(json.dumps({"ok": True, "changed": after != before}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
