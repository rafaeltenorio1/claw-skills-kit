import pytest

from claw_skills_kit.interview import apply_answers
from claw_skills_kit.models import Field, Template
from claw_skills_kit.template_format import (
    FillError,
    TemplateFormatError,
    fill_answers,
    parse_template,
)

TEXT = """# demo-skill: settings (Layer 2)

See context/layer2-standards.md. Standards apply without asking.

## Standards
| Setting | Standard |
|---|---|
| schedule | Every hour |

## Client answers
| Setting | Comes from | Suggested answer | Value |
|---|---|---|---|
| extra urgent_rules | Q1 | Anything with a deadline | |
| sender_rules / suppression_rules | Q2 | Promotions stay out | Keep as suggested |

## Notes
Free text that must survive untouched.
"""

ROW = "| extra urgent_rules | Q1 | Anything with a deadline | |"
KEY = "extra urgent_rules"


def fill(text: str, answers: dict[str, str]) -> str:
    template = apply_answers(parse_template(text), answers)
    return fill_answers(text, template)


def changed_line_numbers(before: str, after: str) -> list[int]:
    a, b = before.splitlines(), after.splitlines()
    assert len(a) == len(b)
    return [i for i, (x, y) in enumerate(zip(a, b)) if x != y]


def test_writes_the_value_into_its_row():
    out = fill(TEXT, {KEY: "Deadlines and payments"})
    assert "| extra urgent_rules | Q1 | Anything with a deadline | Deadlines and payments |" in out


def test_changes_only_the_rows_that_received_a_new_answer():
    out = fill(TEXT, {KEY: "Deadlines"})
    row = next(i for i, line in enumerate(TEXT.splitlines()) if line.startswith("| extra urgent_rules"))
    assert changed_line_numbers(TEXT, out) == [row]


def test_keeps_title_intro_standards_and_notes_untouched():
    out = fill(TEXT, {KEY: "Deadlines"})
    assert out.startswith(TEXT.split("## Client answers")[0])
    assert out.endswith("## Notes\nFree text that must survive untouched.\n")


def test_returns_the_text_unchanged_when_there_is_nothing_new():
    assert fill(TEXT, {}) == TEXT


def test_is_idempotent():
    answers = {KEY: "Deadlines", "sender_rules / suppression_rules": "Show receipts"}
    once = fill(TEXT, answers)
    assert fill(once, answers) == once


def test_the_filled_text_parses_back_to_the_filled_template():
    template = apply_answers(parse_template(TEXT), {KEY: "Deadlines"})
    assert parse_template(fill_answers(TEXT, template)) == template


def test_keeps_the_original_spacing_of_the_other_cells():
    spaced = "|   extra urgent_rules   |   Q1   |   Anything with a deadline   |   |"
    out = fill(TEXT.replace(ROW, spaced), {KEY: "Deadlines"})
    assert "|   extra urgent_rules   |   Q1   |   Anything with a deadline   | Deadlines |" in out


def test_keeps_windows_line_endings():
    out = fill(TEXT.replace("\n", "\r\n"), {KEY: "Deadlines"})
    assert out == fill(TEXT, {KEY: "Deadlines"}).replace("\n", "\r\n")


def test_keeps_a_missing_final_newline():
    out = fill(TEXT.rstrip("\n"), {KEY: "Deadlines"})
    assert not out.endswith("\n")


@pytest.mark.parametrize("answer", ["a|b", "line one\nline two"])
def test_rejects_an_answer_that_cannot_live_in_a_table_cell(answer):
    with pytest.raises(FillError, match="extra urgent_rules"):
        fill(TEXT, {KEY: answer})


@pytest.mark.parametrize("answer", ["abc\n", "abc\x0b", "a\u2028b"])
def test_rejects_any_kind_of_line_break_even_at_the_end_of_an_answer(answer):
    template = Template(
        standards={},
        fields=(
            Field(KEY, "Q1", "Anything with a deadline", answer, True),
            Field("sender_rules / suppression_rules", "Q2", "Promotions stay out", "Keep as suggested", True),
        ),
    )
    with pytest.raises(FillError, match="extra urgent_rules"):
        fill_answers(TEXT, template)


def test_a_blank_answer_leaves_a_tidy_empty_cell():
    template = parse_template(TEXT)
    blanked = Template(
        standards=template.standards,
        fields=(template.fields[0], Field(template.fields[1].key, "Q2", "Promotions stay out", "", True)),
    )
    out = fill_answers(TEXT, blanked)
    assert "| Promotions stay out | |" in out
    assert parse_template(out).fields[1].answer == ""


def test_rejects_a_template_with_a_key_that_is_not_in_the_text():
    ghost = Template(standards={}, fields=(Field("ghost", "Q9", "s", "x", True),))
    with pytest.raises(FillError, match="ghost"):
        fill_answers(TEXT, ghost)


def test_rejects_a_text_row_that_is_not_in_the_template():
    partial = Template(standards={}, fields=(Field(KEY, "Q1", "s", "x", True),))
    with pytest.raises(FillError, match="sender_rules"):
        fill_answers(TEXT, partial)


def test_a_text_without_the_answers_section_is_a_template_error_not_a_fill_error():
    with pytest.raises(TemplateFormatError):
        fill_answers("# nothing useful here\n", Template(standards={}, fields=()))


def test_a_text_with_duplicate_settings_is_a_template_error():
    duplicated = TEXT.replace(
        "| sender_rules / suppression_rules | Q2 | Promotions stay out | Keep as suggested |",
        "| extra urgent_rules | Q2 | Again | |",
    )
    template = Template(standards={}, fields=(Field(KEY, "Q1", "s", "x", True),))
    with pytest.raises(TemplateFormatError, match=r"line \d+"):
        fill_answers(duplicated, template)