"""Find client specifics in Layer 1 text (SKILL.md, scripts, references).

The library validator fails the build on any secret, email address, chat or drive identifier, phone number, or
missing required file in Layer 1. This module finds the first five; `lint_skill` adds the file checks.

Findings carry a kind and a line number only, never the matched text: the point is to keep client data out of
shared files, so the report must not copy it either. The patterns are heuristics and can miss or over-match; they
are listed here so a reviewer can see exactly what is checked.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from claw_skills_kit.integrations import _SECRET_LIKE  # one list of secret shapes for the whole kit

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")),
    ("drive_link", re.compile(r"(?:docs|drive|sheets)\.google\.com/|dropbox\.com/s/|sharepoint\.com/|onedrive\.live\.com/")),
    ("chat_channel", re.compile(r"(?<![\w&/#<])#[a-z][a-z0-9_-]{1,79}\b")),
    ("chat_id", re.compile(r"\b[CGDUW](?=[A-Z0-9]*\d)[A-Z0-9]{8,11}\b|(?<![\w-])-100\d{10}\b|\b\d{17,20}\b")),
    ("url_credentials", re.compile(r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@")),
)
_PHONE = re.compile(r"(?<![\w.])\+?\(?\d[\d\s().-]{7,}\d(?![\w.])")

LAYER1_FILES = ("SKILL.md",)
LAYER1_DIRS = ("scripts", "references", "assets")
LIBRARY_FILES = ("SKILL.md", "client-config.template.md", "interview.md", "lineage.md")
_TEXT_SUFFIXES = {".md", ".txt", ".py", ".sh", ".js", ".ts", ".json", ".yaml", ".yml", ".toml", ".csv", ""}


@dataclass(frozen=True)
class Finding:
    kind: str
    line: int
    file: str = ""

    def to_dict(self) -> dict[str, object]:
        return {"file": self.file, "line": self.line, "kind": self.kind}


def _phone_like(text: str) -> bool:
    digits = re.sub(r"\D", "", text)
    if not 10 <= len(digits) <= 15:
        return False
    return not re.fullmatch(r"\d{4}[-.]\d{2}[-.]\d{2}(?:[-.]\d+)*", text.strip())  # dates and version strings


def find_client_specifics(text: str, file: str = "") -> list[Finding]:
    findings: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        kinds: set[str] = set()
        for kind, pattern in _PATTERNS:
            if pattern.search(line):
                kinds.add(kind)
        if any(_phone_like(m.group(0)) for m in _PHONE.finditer(line)):
            kinds.add("phone")
        # the secret shapes are anchored at the start of a value, so try each word of the line on its own
        words = [w.strip("`'\"()[]{}<>,;") for w in re.split(r"[\s=:]+", line)]
        if any(any(p.search(w) for p in _SECRET_LIKE) for w in words if w) or "PRIVATE KEY-----" in line:
            kinds.add("secret")
        findings.extend(Finding(kind, number, file) for kind in sorted(kinds))
    return findings


def _frontmatter_fields(text: str) -> dict[str, str] | None:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    try:
        end = lines.index("---", 1)
    except ValueError:
        return None
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        if line and not line.startswith((" ", "\t")) and ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields


def lint_skill(folder: Path, *, library: bool) -> list[Finding]:
    """Layer 1 must hold no client specifics; a library skill also needs its Layer 2 files."""
    findings: list[Finding] = []
    required = LIBRARY_FILES if library else LAYER1_FILES
    for name in required:
        if not (folder / name).is_file():
            findings.append(Finding("missing_file", 0, name))
    skill_md = folder / "SKILL.md"
    if skill_md.is_file():
        text = skill_md.read_text(encoding="utf-8", errors="replace")
        fields = _frontmatter_fields(text)
        if fields is None:
            findings.append(Finding("no_frontmatter", 1, "SKILL.md"))
        else:
            if fields.get("name") != folder.name:
                findings.append(Finding("name_mismatch", 0, "SKILL.md"))
            description = fields.get("description", "").strip("\"'")
            if not description:
                findings.append(Finding("no_description", 0, "SKILL.md"))
            elif len(description) >= 160:
                findings.append(Finding("description_too_long", 0, "SKILL.md"))
    layer1 = [folder / n for n in LAYER1_FILES if (folder / n).is_file()]
    for sub in LAYER1_DIRS:
        if (folder / sub).is_dir():
            layer1 += sorted(p for p in (folder / sub).rglob("*") if p.is_file() and p.suffix in _TEXT_SUFFIXES)
    for path in layer1:
        rel = str(path.relative_to(folder))
        findings += find_client_specifics(path.read_text(encoding="utf-8", errors="replace"), rel)
    interview = folder / "interview.md"
    if library and interview.is_file():
        questions = [ln for ln in interview.read_text(encoding="utf-8").splitlines() if re.match(r"\| Q\d+ \|", ln)]
        if not 1 <= len(questions) <= 3:
            findings.append(Finding("interview_size", 0, "interview.md"))
    return findings
