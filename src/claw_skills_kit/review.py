"""The reconciler's review artifact: a text diff of what a run changes on the host.

Skill files (SKILL.md, the template, interview.md, lineage.md, scripts) get an ordinary unified diff. A client's
client-config.md holds their answers, and reports never contain answer values, so it is summarised by keys only:
which questions and standards appear, disappear or change their wording. Same input, same text: it is the artifact
a reviewer reads.
"""
from __future__ import annotations

import difflib

from claw_skills_kit.reconciler.host import Host
from claw_skills_kit.reconciler.layout import ANSWERS_FILE
from claw_skills_kit.template_format import TemplateFormatError, parse_template


def _text(data: bytes | None) -> str:
    return "" if data is None else data.decode("utf-8", errors="replace")


def _config_summary(path: str, before: bytes | None, after: bytes | None) -> list[str]:
    lines = [f"~ {path} (answer values not shown)"]
    try:
        old = parse_template(_text(before)) if before is not None else None
        new = parse_template(_text(after)) if after is not None else None
    except TemplateFormatError:
        return lines + ["  (the file could not be read as settings; its content is not shown)"]
    old_std = old.standards if old else {}
    new_std = new.standards if new else {}
    for key in sorted(set(old_std) | set(new_std)):
        if key not in old_std:
            lines.append(f"  + standard {key}")
        elif key not in new_std:
            lines.append(f"  - standard {key}")
        elif old_std[key] != new_std[key]:
            lines.append(f"  ~ standard {key} (wording changed)")
    old_q = {f.key: f for f in (old.fields if old else ())}
    new_q = {f.key: f for f in (new.fields if new else ())}
    for key in [*[k for k in new_q if k not in old_q], *[k for k in old_q if k not in new_q]]:
        lines.append(f"  {'+' if key in new_q else '-'} question {key}")
    for key in (k for k in new_q if k in old_q):
        a, b = old_q[key], new_q[key]
        if (a.comes_from, a.suggested) != (b.comes_from, b.suggested):
            lines.append(f"  ~ question {key} (wording changed)")
        if a.answer != b.answer:
            lines.append(f"  ~ question {key} (answer changed)")
    return lines


def review_diff(plan, target: Host) -> str:
    """Text diff for a reconcile plan (a Report with `changes` and `desired`)."""
    out: list[str] = []
    for change in plan.changes:
        before = target.read(change.path)
        after = plan.desired.get(change.path)
        if change.path.endswith("/" + ANSWERS_FILE) or change.path == ANSWERS_FILE:
            out += _config_summary(change.path, before, after)
            continue
        out += difflib.unified_diff(
            _text(before).splitlines(), _text(after).splitlines(),
            fromfile=f"a/{change.path}" if before is not None else "/dev/null",
            tofile=f"b/{change.path}" if after is not None else "/dev/null",
            lineterm="",
        )
    return "\n".join(out) + ("\n" if out else "")
