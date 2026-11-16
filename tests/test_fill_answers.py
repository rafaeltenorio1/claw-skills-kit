
import pytest
 
from claw_skills_kit.interview import apply_answers
from claw_skills_kit.models import Field, Template
from claw_skills_kit.template_format import FillError, fill_answers, parse_template
 
TEXT = """# Client config: hello-channel
 
<!-- ASSUMED FORMAT: see docs/assumptions.md -->
 
## Standards
| Key | Value |
|---|---|
| retry_limit | 3 |
 
## Client answers
| Key | Question | Answer | Required |
|---|---|---|---|
| target_channel | Where should the summary be posted? | | yes |
| timezone | Which timezone should schedules use? | America/Sao_Paulo | no |
 
## Notes
Free text that must survive untouched.
"""
 
ROW = "| target_channel | Where should the summary be posted? | | yes |"
 
 
def fill(text: str, answers: dict[str, str]) -> str:
    template = apply_answers(parse_template(text), answers)
    return fill_answers(text, template)
 
 
def changed_line_numbers(before: str, after: str) -> list[int]:
    a, b = before.splitlines(), after.splitlines()
    assert len(a) == len(b)
    return [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
 
 
def test_writes_the_answer_into_its_row():
    out = fill(TEXT, {"target_channel": "#sales"})
    assert "| target_channel | Where should the summary be posted? | #sales | yes |" in out
 
 
def test_changes_only_the_rows_that_received_a_new_answer():
    out = fill(TEXT, {"target_channel": "#sales"})
    row = next(i for i, line in enumerate(TEXT.splitlines()) if line.startswith("| target_channel"))
    assert changed_line_numbers(TEXT, out) == [row]
 
 
def test_keeps_title_comment_standards_and_notes_untouched():
    out = fill(TEXT, {"target_channel": "#sales"})
    assert out.startswith(TEXT.split("## Client answers")[0])
    assert out.endswith("## Notes\nFree text that must survive untouched.\n")
 
 
def test_returns_the_text_unchanged_when_there_is_nothing_new():
    assert fill(TEXT, {}) == TEXT
 
 
def test_is_idempotent():
    answers = {"target_channel": "#sales", "timezone": "UTC"}
    once = fill(TEXT, answers)
    assert fill(once, answers) == once
 
 
def test_the_filled_text_parses_back_to_the_filled_template():
    template = apply_answers(parse_template(TEXT), {"target_channel": "#sales"})
    assert parse_template(fill_answers(TEXT, template)) == template
 
 
def test_keeps_the_original_spacing_of_the_other_cells():
    spaced = "|   target_channel   |   Where should the summary be posted?   |   |   yes   |"
    out = fill(TEXT.replace(ROW, spaced), {"target_channel": "#sales"})
    assert "|   target_channel   |   Where should the summary be posted?   | #sales |   yes   |" in out
 
 
def test_keeps_windows_line_endings():
    out = fill(TEXT.replace("\n", "\r\n"), {"target_channel": "#sales"})
    assert out == fill(TEXT, {"target_channel": "#sales"}).replace("\n", "\r\n")
 
 
def test_keeps_a_missing_final_newline():
    out = fill(TEXT.rstrip("\n"), {"target_channel": "#sales"})
    assert not out.endswith("\n")
 
 
@pytest.mark.parametrize("answer", ["a|b", "line one\nline two"])
def test_rejects_an_answer_that_cannot_live_in_a_table_cell(answer):
    with pytest.raises(FillError, match="target_channel"):
        fill(TEXT, {"target_channel": answer})
 
 
def test_rejects_a_template_with_a_key_that_is_not_in_the_text():
    ghost = Template(standards={}, fields=(Field("ghost", "Q?", "x", True),))
    with pytest.raises(FillError, match="ghost"):
        fill_answers(TEXT, ghost)
 
 
def test_rejects_a_text_row_that_is_not_in_the_template():
    partial = Template(standards={}, fields=(Field("target_channel", "Q?", "#sales", True),))
    with pytest.raises(FillError, match="timezone"):
        fill_answers(TEXT, partial)
 