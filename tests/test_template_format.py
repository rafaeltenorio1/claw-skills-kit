from pathlib import Path
import pytest
from claw_skills_kit.template_format import parse_template, TemplateFormatError

FIXTURE = Path(__file__).parent / "fixtures/skills/hello-channel/client-config.md"


def test_parses_standards():
    t = parse_template(FIXTURE.read_text())
    assert t.standards == {"max_items_per_run": "20", "retry_limit": "3"}


def test_parses_fields_in_order_with_required_flag():
    t = parse_template(FIXTURE.read_text())
    assert [f.key for f in t.fields] == ["target_channel", "timezone"]
    assert t.fields[0].required is True
    assert t.fields[0].answer == ""
    assert t.fields[1].required is False
    assert t.fields[1].answer == "America/Sao_Paulo"


def test_rejects_template_without_client_answers_section():
    with pytest.raises(TemplateFormatError):
        parse_template("# Client config\n\n## Standards\n| Key | Value |\n|---|---|\n")


STANDARDS = "## Standards\n| Key | Value |\n|---|---|\n| retry_limit | 3 |\n"
HEADER = "| Key | Question | Answer | Required |"


def doc(rows: str, header: str = HEADER) -> str:
    return STANDARDS + "\n## Client answers\n" + header + "\n|---|---|---|---|\n" + rows


@pytest.mark.parametrize("raw,expected", [
    ("yes", True), ("Yes", True), ("YES", True), ("no", False), ("No", False),
])
def test_required_accepts_yes_no_in_any_case(raw, expected):
    t = parse_template(doc(f"| k | Q? | | {raw} |\n"))
    assert t.fields[0].required is expected


@pytest.mark.parametrize("raw", ["maybe", "", "true"])
def test_required_rejects_anything_else(raw):
    with pytest.raises(TemplateFormatError):
        parse_template(doc(f"| k | Q? | | {raw} |\n"))


def test_ignores_unknown_sections_and_their_tables():
    text = doc("| k | Q? | | yes |\n") + "\n## Notes\n| a | b |\n|---|---|\n| 1 |\n"
    assert [f.key for f in parse_template(text).fields] == ["k"]


def test_rejects_row_with_wrong_number_of_cells_and_names_the_line():
    with pytest.raises(TemplateFormatError, match=r"line \d+"):
        parse_template(doc("| k | Q? | yes |\n"))


def test_rejects_unexpected_header():
    with pytest.raises(TemplateFormatError):
        parse_template(doc("| k | Q? | | yes |\n",
                           header="| Name | Question | Answer | Required |"))


def test_rejects_duplicate_keys():
    with pytest.raises(TemplateFormatError):
        parse_template(doc("| k | Q1? | | yes |\n| k | Q2? | | no |\n"))


def test_rejects_missing_standards_section():
    text = "## Client answers\n" + HEADER + "\n|---|---|---|---|\n| k | Q? | | yes |\n"
    with pytest.raises(TemplateFormatError):
        parse_template(text)