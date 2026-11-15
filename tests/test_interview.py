import pytest

from claw_skills_kit.interview import (
    InterviewError,
    apply_answers,
    load_answers,
    missing_required,
)
from claw_skills_kit.models import Field, Template


def make_template() -> Template:
    return Template(
        standards={"retry_limit": "3"},
        fields=(
            Field("target_channel", "Where should the summary be posted?", "", True),
            Field("timezone", "Which timezone should schedules use?", "America/Sao_Paulo", False),
            Field("owner", "Who owns this skill for the client?", "", False),
        ),
    )


# --- load_answers: reading the JSON answers file --------------------------------

def test_load_answers_reads_a_flat_json_object():
    assert load_answers('{"target_channel": "#sales"}') == {"target_channel": "#sales"}


def test_load_answers_accepts_an_empty_object():
    assert load_answers("{}") == {}


def test_load_answers_rejects_invalid_json_and_names_the_position():
    with pytest.raises(InterviewError, match=r"line 1"):
        load_answers('{"target_channel": ')


def test_load_answers_rejects_a_top_level_that_is_not_an_object():
    with pytest.raises(InterviewError):
        load_answers('["target_channel"]')


def test_load_answers_rejects_non_string_values_and_names_the_key():
    with pytest.raises(InterviewError, match=r"'retries'"):
        load_answers('{"retries": 3}')


def test_load_answers_rejects_duplicate_keys_and_names_the_key():
    with pytest.raises(InterviewError, match=r"'timezone'"):
        load_answers('{"timezone": "UTC", "timezone": "CET"}')


# --- apply_answers: merging answers into the template ---------------------------

def test_apply_answers_fills_a_blank_answer():
    result = apply_answers(make_template(), {"target_channel": "#sales"})
    assert result.fields[0].answer == "#sales"


def test_apply_answers_keeps_the_template_answer_when_none_is_given():
    result = apply_answers(make_template(), {"target_channel": "#sales"})
    assert result.fields[1].answer == "America/Sao_Paulo"


def test_apply_answers_lets_the_given_answer_override_the_template_answer():
    result = apply_answers(make_template(), {"timezone": "UTC"})
    assert result.fields[1].answer == "UTC"


def test_apply_answers_treats_a_blank_value_as_not_provided():
    result = apply_answers(make_template(), {"timezone": "   ", "target_channel": ""})
    assert result.fields[1].answer == "America/Sao_Paulo"
    assert result.fields[0].answer == ""


def test_apply_answers_strips_surrounding_whitespace():
    result = apply_answers(make_template(), {"target_channel": "  #sales "})
    assert result.fields[0].answer == "#sales"


def test_apply_answers_rejects_unknown_keys_and_lists_all_of_them():
    with pytest.raises(InterviewError, match=r"nope.*typo|typo.*nope"):
        apply_answers(make_template(), {"nope": "x", "typo": "y"})


def test_apply_answers_rejects_a_key_that_is_a_company_standard():
    with pytest.raises(InterviewError, match=r"retry_limit"):
        apply_answers(make_template(), {"retry_limit": "9"})


def test_apply_answers_keeps_order_questions_flags_and_standards():
    original = make_template()
    result = apply_answers(original, {"owner": "Ana"})
    assert [f.key for f in result.fields] == ["target_channel", "timezone", "owner"]
    assert [f.question for f in result.fields] == [f.question for f in original.fields]
    assert [f.required for f in result.fields] == [f.required for f in original.fields]
    assert result.standards == original.standards


def test_apply_answers_does_not_change_the_template_it_receives():
    original = make_template()
    apply_answers(original, {"target_channel": "#sales"})
    assert original == make_template()


def test_apply_answers_is_idempotent():
    answers = {"target_channel": "#sales", "timezone": "UTC"}
    once = apply_answers(make_template(), answers)
    twice = apply_answers(once, answers)
    assert twice == once


# --- missing_required: which required answers are still blank -------------------

def test_missing_required_lists_blank_required_fields_in_template_order():
    missing = missing_required(make_template())
    assert [f.key for f in missing] == ["target_channel"]


def test_missing_required_ignores_blank_optional_fields():
    assert "owner" not in [f.key for f in missing_required(make_template())]


def test_missing_required_is_empty_once_every_required_answer_is_given():
    filled = apply_answers(make_template(), {"target_channel": "#sales"})
    assert missing_required(filled) == ()