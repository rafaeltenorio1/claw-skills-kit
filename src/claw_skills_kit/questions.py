"""Per-instance question edits on a host's client-config.md (Phase 2).

Rules (decided by Rafael):
- New questions are instance-only rows (`Comes from` = Instance); the golden template never changes here.
- A golden question can only get a new answer here. Changing or removing it per instance would be undone by the
  next reconcile, so it is refused.
- Removing a question that holds an answer is refused unless the caller says the answer may be discarded.
"""
from __future__ import annotations

from dataclasses import dataclass

from claw_skills_kit.models import Field
from claw_skills_kit.template_format import (
    INSTANCE_SOURCE,
    FillError,
    TemplateFormatError,
    append_fields,
    is_instance_field,
    parse_template,
    remove_field,
    update_field,
)


class QuestionError(Exception):
    """A refusal before anything is written. `status` is a stable machine-readable code."""

    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Edit:
    text: str  # the new client-config.md text
    key: str
    action: str  # add | change | remove
    had_answer: bool = False  # remove only: an answer was (or would be) discarded


def _parse(text: str):
    try:
        return parse_template(text)
    except TemplateFormatError as exc:
        raise QuestionError("invalid_existing_config", str(exc)) from None


def _field(text: str, key: str) -> Field:
    for field in _parse(text).fields:
        if field.key == key:
            return field
    raise QuestionError("question_not_found", f"There is no question {key!r}.")


def _checked(text: str) -> str:
    _parse(text)  # never hand back a document that does not parse
    return text


def add_question(text: str, key: str, suggested: str, answer: str = "") -> Edit:
    template = _parse(text)
    key = key.strip()
    if key in template.standards or any(f.key == key for f in template.fields):
        raise QuestionError("question_exists", f"A setting called {key!r} already exists.")
    try:
        new = append_fields(text, [Field(key, INSTANCE_SOURCE, suggested.strip(), answer.strip())])
    except (FillError, TemplateFormatError) as exc:
        raise QuestionError("invalid_question", str(exc)) from None
    return Edit(_checked(new), key, "add")


def change_question(text: str, key: str, *, suggested: str | None = None, answer: str | None = None) -> Edit:
    if suggested is None and answer is None:
        raise QuestionError("invalid_question", "Nothing to change: give a new suggestion and/or answer.")
    field = _field(text, key)
    if suggested is not None and not is_instance_field(field):
        raise QuestionError(
            "golden_question",
            f"{key!r} comes from the golden skill; only its answer can change for one client.",
        )
    try:
        new = update_field(text, key, suggested=suggested, answer=answer)
    except FillError as exc:
        raise QuestionError("invalid_question", str(exc)) from None
    return Edit(_checked(new), key, "change")


def remove_question(text: str, key: str, *, discard_answer: bool = False) -> Edit:
    field = _field(text, key)
    if not is_instance_field(field):
        raise QuestionError(
            "golden_question",
            f"{key!r} comes from the golden skill; it cannot be removed for one client.",
        )
    had_answer = bool(field.answer.strip())
    if had_answer and not discard_answer:
        raise QuestionError(
            "answer_would_be_lost",
            f"{key!r} has an answer; confirm with the client, then pass --discard-answer.",
        )
    return Edit(_checked(remove_field(text, key)), key, "remove", had_answer)
