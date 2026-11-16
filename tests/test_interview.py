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
        standards={"schedule": "Every hour"},
        fields=(
            Field("extra urgent_rules", "Q1", "Anything with a deadline", "", True),
            Field("sender_rules / suppression_rules", "Q2", "Promotions stay out", "Keep as suggested", True),
            Field("notes_for_team", "Q4", "", "", False),
        ),
    )


# --- load_answers: reading the JSON answers file --------------------------------

def test_load_answers_reads_a_flat_json_object():
    assert load_answers('{"extra urgent_rules": "deadlines"}') == {"extra urgent_rules": "deadlines"}


def test_load_answers_accepts_an_empty_object():
    assert load_answers("{}") == {}


def test_load_answers_rejects_invalid_json_and_names_the_position():
    with pytest.raises(InterviewError, match=r"line 1"):
        load_answers('{"extra urgent_rules": ')


def test_load_answers_rejects_a_top_level_that_is_not_an_object():
    with pytest.raises(InterviewError):
        load_answers('["extra urgent_rules"]')


def test_load_answers_rejects_non_string_values_and_names_the_key():
    with pytest.raises(InterviewError, match=r"'retries'"):
        load_answers('{"retries": 3}')


def test_load_answers_rejects_duplicate_keys_and_names_the_key():
    with pytest.raises(InterviewError, match=r"'critical_senders'"):
        load_answers('{"critical_senders": "a", "critical_senders": "b"}')


# --- apply_answers: merging answers into the template ---------------------------

def test_apply_answers_fills_a_blank_answer():
    result = apply_answers(make_template(), {"extra urgent_rules": "deadlines"})
    assert result.fields[0].answer == "deadlines"


def test_apply_answers_keeps_the_existing_answer_when_none_is_given():
    result = apply_answers(make_template(), {"extra urgent_rules": "deadlines"})
    assert result.fields[1].answer == "Keep as suggested"


def test_apply_answers_lets_the_given_answer_override_the_existing_one():
    result = apply_answers(make_template(), {"sender_rules / suppression_rules": "show receipts"})
    assert result.fields[1].answer == "show receipts"


def test_apply_answers_treats_a_blank_value_as_not_provided():
    result = apply_answers(
        make_template(), {"sender_rules / suppression_rules": "   ", "extra urgent_rules": ""}
    )
    assert result.fields[1].answer == "Keep as suggested"
    assert result.fields[0].answer == ""


def test_apply_answers_strips_surrounding_whitespace():
    result = apply_answers(make_template(), {"extra urgent_rules": "  deadlines "})
    assert result.fields[0].answer == "deadlines"


def test_apply_answers_rejects_unknown_keys_and_lists_all_of_them():
    with pytest.raises(InterviewError, match=r"nope.*typo|typo.*nope"):
        apply_answers(make_template(), {"nope": "x", "typo": "y"})


def test_apply_answers_rejects_a_key_that_is_a_standard():
    with pytest.raises(InterviewError, match=r"standard.*schedule"):
        apply_answers(make_template(), {"schedule": "every minute"})


def test_apply_answers_keeps_order_ids_suggestions_flags_and_standards():
    original = make_template()
    result = apply_answers(original, {"notes_for_team": "hello"})
    assert [f.key for f in result.fields] == [f.key for f in original.fields]
    assert [f.comes_from for f in result.fields] == [f.comes_from for f in original.fields]
    assert [f.suggested for f in result.fields] == [f.suggested for f in original.fields]
    assert [f.required for f in result.fields] == [f.required for f in original.fields]
    assert result.standards == original.standards


def test_apply_answers_does_not_change_the_template_it_receives():
    original = make_template()
    apply_answers(original, {"extra urgent_rules": "deadlines"})
    assert original == make_template()


def test_apply_answers_is_idempotent():
    answers = {"extra urgent_rules": "deadlines", "sender_rules / suppression_rules": "show receipts"}
    once = apply_answers(make_template(), answers)
    assert apply_answers(once, answers) == once


# --- missing_required: which required answers are still blank -------------------

def test_missing_required_lists_blank_required_fields_in_template_order():
    assert [f.key for f in missing_required(make_template())] == ["extra urgent_rules"]


def test_missing_required_ignores_blank_optional_fields():
    assert "notes_for_team" not in [f.key for f in missing_required(make_template())]


def test_missing_required_is_empty_once_every_required_answer_is_given():
    filled = apply_answers(make_template(), {"extra urgent_rules": "deadlines"})
    assert missing_required(filled) == ()