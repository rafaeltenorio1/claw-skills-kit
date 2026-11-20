from pathlib import Path

import pytest

from claw_skills_kit.template_format import TemplateFormatError, parse_template

FIXTURE = Path(__file__).parent / "fixtures/skills/demo-skill/client-config.template.md"

STANDARDS = "## Standards\n| Setting | Standard |\n|---|---|\n| schedule | Every hour |\n"
HEADER = "| Setting | Comes from | Suggested answer | Value |"


def doc(rows: str, header: str = HEADER) -> str:
    """A valid document whose 'Client answers' table is built from `rows`."""
    return STANDARDS + "\n## Client answers\n" + header + "\n|---|---|---|---|\n" + rows


# --- what a real template looks like ---------------------------------------------

def test_parses_the_standards_of_the_template():
    t = parse_template(FIXTURE.read_text(encoding="utf-8"))
    assert t.standards == {
        "schedule": "Every hour during working hours",
        "filing_mode": "First run: preview only. Never delete.",
        "quiet_runs": "A run with nothing new posts nothing. Failures go to #<agent>-ops.",
    }


def test_parses_the_client_answers_in_order_with_question_ids_and_suggestions():
    t = parse_template(FIXTURE.read_text(encoding="utf-8"))
    assert [f.key for f in t.fields] == [
        "extra urgent_rules",
        "sender_rules / suppression_rules",
        "critical_senders",
    ]
    assert [f.comes_from for f in t.fields] == ["Q1", "Q2", "Q3"]
    assert t.fields[0].suggested == "Anything with a deadline or a payment problem"
    assert all(f.answer == "" for f in t.fields)


def test_every_client_answer_is_required_for_now():
    t = parse_template(FIXTURE.read_text(encoding="utf-8"))
    assert all(f.required for f in t.fields)


def test_reads_values_that_are_already_filled():
    t = parse_template(doc("| k | Q1 | Suggested | Acme Corp, Dana at Smith & Co |\n"))
    assert t.fields[0].answer == "Acme Corp, Dana at Smith & Co"


# --- sections and headers --------------------------------------------------------

def test_rejects_a_text_without_the_client_answers_section():
    with pytest.raises(TemplateFormatError, match="Client answers"):
        parse_template(STANDARDS)


def test_rejects_a_text_without_the_standards_section():
    text = "## Client answers\n" + HEADER + "\n|---|---|---|---|\n| k | Q1 | s | |\n"
    with pytest.raises(TemplateFormatError, match="## Standards"):
        parse_template(text)


def test_rejects_a_duplicated_section():
    with pytest.raises(TemplateFormatError, match=r"line \d+"):
        parse_template(doc("| k | Q1 | s | |\n") + "\n## Client answers\n")


def test_rejects_an_unexpected_standards_header():
    text = doc("| k | Q1 | s | |\n").replace("| Setting | Standard |", "| Name | Standard |")
    with pytest.raises(TemplateFormatError, match=r"line \d+"):
        parse_template(text)


def test_rejects_an_unexpected_answers_header():
    with pytest.raises(TemplateFormatError, match=r"line \d+"):
        parse_template(doc("| k | Q1 | s | |\n", header="| Setting | Origin | Suggested answer | Value |"))


def test_ignores_unknown_sections_and_their_tables():
    text = doc("| k | Q1 | s | |\n") + "\n## Notes\n| a | b |\n|---|---|\n| 1 |\n"
    assert [f.key for f in parse_template(text).fields] == ["k"]


def test_allows_html_comments_inside_a_known_section():
    t = parse_template(doc("<!-- note -->\n| k | Q1 | s | |\n"))
    assert [f.key for f in t.fields] == ["k"]


def test_rejects_stray_text_inside_a_known_section():
    with pytest.raises(TemplateFormatError, match=r"line \d+"):
        parse_template(doc("| k | Q1 | s | |\nk2 | Q2 | s | |\n"))


# --- rows ------------------------------------------------------------------------

def test_rejects_a_row_with_the_wrong_number_of_cells_and_names_the_line():
    with pytest.raises(TemplateFormatError, match=r"line \d+"):
        parse_template(doc("| k | Q1 | s |\n"))


def test_rejects_duplicate_settings():
    with pytest.raises(TemplateFormatError, match=r"line \d+"):
        parse_template(doc("| k | Q1 | s | |\n| k | Q2 | s | |\n"))


def test_a_client_setting_cannot_reuse_the_name_of_a_standard():
    with pytest.raises(TemplateFormatError, match="schedule"):
        parse_template(doc("| schedule | Q1 | s | |\n"))


def test_rejects_an_empty_setting_name():
    with pytest.raises(TemplateFormatError, match=r"line \d+"):
        parse_template(doc("|  | Q1 | s | |\n"))


def test_rejects_an_empty_standard():
    text = doc("| k | Q1 | s | |\n").replace("| schedule | Every hour |", "| schedule |  |")
    with pytest.raises(TemplateFormatError, match="schedule"):
        parse_template(text)

# --- instance-only questions -------------------------------------------------------

from claw_skills_kit.models import Field  # noqa: E402
from claw_skills_kit.template_format import FillError, append_fields, is_instance_field  # noqa: E402


def instance(key="interval_days", suggested="Every 7 days", answer=""):
    return Field(key=key, comes_from="Instance", suggested=suggested, answer=answer)


def test_a_question_marked_instance_is_recognised_in_any_case():
    assert is_instance_field(instance())
    assert is_instance_field(Field("k", " instance ", "", ""))
    assert not is_instance_field(Field("k", "Q1", "", ""))


def test_append_adds_a_row_at_the_end_of_the_answers_table_and_keeps_every_other_byte():
    text = FIXTURE.read_text()
    out = append_fields(text, [instance(answer="7")])
    sep = "\n" if not text.endswith("\n") else ""
    assert out == text + sep + "| interval_days | Instance | Every 7 days | 7 |" + ("\n" if not sep else "")
    assert parse_template(out).fields[-1] == instance(answer="7")


def test_append_keeps_text_after_the_table():
    text = doc("| q1 | Q1 | s | |\n") + "\n## Notes\nkeep me\n"
    out = append_fields(text, [instance()])
    assert out == doc("| q1 | Q1 | s | |\n| interval_days | Instance | Every 7 days | |\n") + "\n## Notes\nkeep me\n"


def test_append_keeps_windows_line_endings_and_a_missing_final_newline():
    crlf = doc("| q1 | Q1 | s | |").replace("\n", "\r\n")
    out = append_fields(crlf, [instance()])
    assert out == crlf + "\r\n| interval_days | Instance | Every 7 days | |"


def test_append_to_an_empty_table_goes_right_after_the_separator():
    out = append_fields(doc(""), [instance()])
    assert out == doc("| interval_days | Instance | Every 7 days | |\n")


@pytest.mark.parametrize("key", ["q1", "schedule"])
def test_append_refuses_a_key_that_already_exists_as_a_question_or_a_standard(key):
    with pytest.raises((FillError, TemplateFormatError)):
        append_fields(doc("| q1 | Q1 | s | |\n"), [instance(key=key)])


@pytest.mark.parametrize("bad", ["a|b", "a\nb", ""])
def test_append_refuses_cells_that_break_the_table(bad):
    field = instance(key=bad) if bad == "" else instance(suggested=bad)
    with pytest.raises(FillError):
        append_fields(doc(""), [field])
