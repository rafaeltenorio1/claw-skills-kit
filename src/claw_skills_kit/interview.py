from __future__ import annotations

from dataclasses import replace
import json
from typing import Any

from claw_skills_kit.models import Field, Template


class InterviewError(ValueError):
    """The client answers file is invalid or does not match the skill template."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InterviewError(f"Duplicate key in answers file: {key!r}.")
        result[key] = value
    return result


def load_answers(text: str) -> dict[str, str]:
    """Parse the JSON answers file into {key: answer}."""
    try:
        data = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise InterviewError(
            f"Invalid JSON (line {exc.lineno}, column {exc.colno}): {exc.msg}."
        ) from None
    
    if not isinstance(data, dict):
        raise InterviewError(
            f"Answers file must be a JSON object, got {type(data).__name__}."
        )

    for key, value in data.items():
        if not isinstance(value, str):
            raise InterviewError(
                f"Invalid value for {key!r}: expected str, got {type(value).__name__}."
            )

    return data


def apply_answers(template: Template, answers: dict[str, str]) -> Template:
    """Return a new Template with the given answers filled in."""
    known_keys = {field.key for field in template.fields}
    unknown_keys = set(answers) - known_keys
    if unknown_keys:
        raise InterviewError(
            f"Unknown keys in answers: {', '.join(sorted(unknown_keys))}."
        )

    updated_fields = tuple(
        replace(
            field,
            answer=(answers[field.key].strip() or field.answer)
            if field.key in answers
            else field.answer,
        )
        for field in template.fields
    )

    return replace(template, fields=updated_fields)


def missing_required(template: Template) -> tuple[Field, ...]:
    """Required fields whose answer is still blank, in template order."""
    return tuple(
        field
        for field in template.fields
        if field.required and not field.answer.strip()
    )