"""Create or remove a skill on one client's instance.

A skill created here is marked in its SKILL.md frontmatter with `metadata.csk_origin: instance`. OpenClaw ignores
unknown metadata keys (verified on OpenClaw 2026.11.3 for `layer` and `version`), so the mark does not change how the
skill loads. Only marked skills can be removed here: library skills belong to the reconciler.
"""
from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass

from claw_skills_kit.layer1 import find_client_specifics
from claw_skills_kit.questions import add_question
from claw_skills_kit.reconciler.host import Host
from claw_skills_kit.reconciler.layout import ANSWERS_FILE, SKILL_FILE
from claw_skills_kit.template_format import TemplateFormatError, new_client_config, parse_template

ORIGIN_KEY = "csk_origin"
INSTANCE_ORIGIN = "instance"

# Assumption: lowercase letters, digits and hyphens, like the library skills. OpenClaw's own rule is not verified.
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_ORIGIN_LINE = re.compile(rf"^\s+{ORIGIN_KEY}:\s*{INSTANCE_ORIGIN}\s*$")


class SkillError(Exception):
    """A refusal before anything is written. `status` is a stable machine-readable code."""

    def __init__(self, status: str, message: str, findings: Sequence[dict] = ()) -> None:
        super().__init__(message)
        self.status = status
        self.findings = tuple(findings)


@dataclass(frozen=True)
class SkillPlan:
    name: str
    action: str  # create | remove
    files: dict[str, bytes | None]  # path -> new content (create) or None (remove)
    had_answers: bool = False
    questions: tuple[str, ...] = ()  # create only: keys of the questions written with the skill


@dataclass(frozen=True)
class NewQuestion:
    key: str
    suggested: str
    answer: str = ""


def _check_name(name: str) -> str:
    if not _NAME.match(name):
        raise SkillError(
            "invalid_skill", f"Invalid skill name {name!r}: use lowercase letters, digits and hyphens."
        )
    return name


def render_skill_md(name: str, description: str, instructions: str) -> str:
    description = description.strip()
    if not description or "\n" in description:
        raise SkillError("invalid_skill", "The description must be one non-empty line.")
    body = instructions.strip()
    if not body:
        raise SkillError("invalid_skill", "The skill needs instructions.")
    if body.startswith("---"):
        raise SkillError("invalid_skill", "Instructions cannot start with '---' (that is the frontmatter marker).")
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {json.dumps(description, ensure_ascii=False)}\n"
        "user-invocable: true\n"
        "metadata:\n"
        f"  {ORIGIN_KEY}: {INSTANCE_ORIGIN}\n"
        "---\n"
        "\n"
        f"{body}\n"
    )


def is_instance_skill(skill_md: str) -> bool:
    """True if the SKILL.md frontmatter carries the instance mark."""
    lines = skill_md.splitlines()
    if not lines or lines[0].strip() != "---":
        return False
    for line in lines[1:]:
        if line.strip() == "---":
            return False
        if _ORIGIN_LINE.match(line):
            return True
    return False


def plan_create(
    skills: Host,
    name: str,
    description: str,
    instructions: str,
    questions: Sequence[NewQuestion] = (),
) -> SkillPlan:
    """Plan the skill and its questions together, so one dry run checks everything and one apply writes it all.

    Each question goes through the same rules as `question add` (QuestionError on refusal, nothing planned).
    """
    _check_name(name)
    if skills.files(name):
        raise SkillError("skill_exists", f"A skill called {name!r} already exists on this instance.")
    skill_md = render_skill_md(name, description, instructions)
    leaks = find_client_specifics(skill_md, SKILL_FILE)
    if leaks:
        raise SkillError(
            "client_data_in_skill",
            "The skill text holds client specifics (contact, channel, ID or secret). Keep the skill generic and "
            "put them in its settings: one --question each.",
            [f.to_dict() for f in leaks],
        )
    config = new_client_config(name)
    for q in questions:
        config = add_question(config, q.key, q.suggested, q.answer).text
    files: dict[str, bytes | None] = {
        f"{name}/{SKILL_FILE}": skill_md.encode("utf-8"),
        f"{name}/{ANSWERS_FILE}": config.encode("utf-8"),
    }
    return SkillPlan(name, "create", files, questions=tuple(q.key for q in questions))


def plan_remove(skills: Host, name: str, *, discard_answers: bool = False) -> SkillPlan:
    _check_name(name)
    paths = skills.files(name)
    if not paths:
        raise SkillError("skill_not_found", f"There is no skill called {name!r} on this instance.")
    skill_md = skills.read(f"{name}/{SKILL_FILE}")
    if skill_md is None or not is_instance_skill(skill_md.decode("utf-8", errors="replace")):
        raise SkillError(
            "library_skill", f"{name!r} was not created on this instance; it cannot be removed from here."
        )
    had_answers = False
    config = skills.read(f"{name}/{ANSWERS_FILE}")
    if config is not None:
        try:
            had_answers = any(f.answer.strip() for f in parse_template(config.decode("utf-8")).fields)
        except (UnicodeDecodeError, TemplateFormatError):
            had_answers = True  # cannot tell: treat as holding answers
    if had_answers and not discard_answers:
        raise SkillError(
            "answer_would_be_lost",
            f"{name!r} has client answers; confirm with the client, then pass --discard-answers.",
        )
    return SkillPlan(name, "remove", {p: None for p in paths}, had_answers)


def apply_plan(skills: Host, plan: SkillPlan) -> None:
    """Write the plan. On any failure put every path back and verify it by read-back."""
    from claw_skills_kit.reconcile import _restore  # same verified restore the reconciler uses

    snapshot = {path: skills.read(path) for path in plan.files}
    try:
        for path, data in plan.files.items():
            if data is None:
                skills.delete(path)
            else:
                skills.write(path, data)
    except Exception as exc:
        unrestored = _restore(skills, snapshot)
        if unrestored:
            raise SkillError("rollback_failed", "Restore failed for: " + ", ".join(unrestored)) from exc
        raise SkillError("rolled_back", f"Write failed ({type(exc).__name__}); nothing was changed.") from exc
