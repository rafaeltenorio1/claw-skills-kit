import json
from pathlib import Path

import pytest

from claw_skills_kit.cli import main
from claw_skills_kit.questions import QuestionError, add_question, change_question, remove_question
from claw_skills_kit.template_format import parse_template, remove_field, update_field

CONFIG = """# demo-skill: settings (Layer 2)

## Standards
| Setting | Standard |
|---|---|
| schedule | Every hour |

## Client answers
| Setting | Comes from | Suggested answer | Value |
|---|---|---|---|
| run_time | Q1 | 08:00 | 07:30 |
| interval_days | Instance | Every 7 days | 7 |
| channel | Instance | #ops | |

## Notes
keep me
"""


def keys(text):
    return [f.key for f in parse_template(text).fields]


# --- template_format: row edits keep every other byte --------------------------------

def test_update_field_changes_only_the_named_cells():
    out = update_field(CONFIG, "interval_days", suggested="Every 14 days", answer="14")
    assert out == CONFIG.replace("| interval_days | Instance | Every 7 days | 7 |",
                                 "| interval_days | Instance | Every 14 days | 14 |")


def test_update_field_with_a_blank_answer_leaves_a_tidy_empty_cell():
    out = update_field(CONFIG, "run_time", answer="")
    assert "| run_time | Q1 | 08:00 | |" in out


def test_remove_field_removes_exactly_one_line():
    out = remove_field(CONFIG, "channel")
    assert out == CONFIG.replace("| channel | Instance | #ops | |\n", "")


def test_remove_the_last_row_of_a_file_without_final_newline():
    text = CONFIG.split("\n## Notes")[0].rstrip("\n")
    assert remove_field(text, "channel") == text.rsplit("\n", 1)[0]


# --- questions: the rules ----------------------------------------------------------

def test_add_creates_an_instance_row():
    edit = add_question(CONFIG, "weekday", "Monday")
    assert keys(edit.text)[-1] == "weekday"
    assert "| weekday | Instance | Monday | |" in edit.text
    assert edit.text.endswith("## Notes\nkeep me\n")


@pytest.mark.parametrize("key", ["run_time", "channel", "schedule"])
def test_add_refuses_an_existing_question_or_standard(key):
    with pytest.raises(QuestionError) as exc:
        add_question(CONFIG, key, "x")
    assert exc.value.status == "question_exists"


def test_add_refuses_text_that_breaks_the_table():
    with pytest.raises(QuestionError) as exc:
        add_question(CONFIG, "weekday", "a | b")
    assert exc.value.status == "invalid_question"


def test_change_an_instance_question():
    edit = change_question(CONFIG, "interval_days", suggested="Every 14 days")
    assert "| interval_days | Instance | Every 14 days | 7 |" in edit.text


def test_a_golden_question_can_get_a_new_answer():
    edit = change_question(CONFIG, "run_time", answer="09:00")
    assert "| run_time | Q1 | 08:00 | 09:00 |" in edit.text


def test_a_golden_question_text_cannot_change_per_instance():
    with pytest.raises(QuestionError) as exc:
        change_question(CONFIG, "run_time", suggested="10:00")
    assert exc.value.status == "golden_question"


def test_a_golden_question_cannot_be_removed_per_instance():
    with pytest.raises(QuestionError) as exc:
        remove_question(CONFIG, "run_time", discard_answer=True)
    assert exc.value.status == "golden_question"


def test_removing_an_answered_question_needs_explicit_consent():
    with pytest.raises(QuestionError) as exc:
        remove_question(CONFIG, "interval_days")
    assert exc.value.status == "answer_would_be_lost"
    edit = remove_question(CONFIG, "interval_days", discard_answer=True)
    assert "interval_days" not in keys(edit.text) and edit.had_answer


def test_removing_a_blank_question_needs_no_consent():
    edit = remove_question(CONFIG, "channel")
    assert "channel" not in keys(edit.text) and not edit.had_answer


def test_unknown_question():
    with pytest.raises(QuestionError) as exc:
        change_question(CONFIG, "nope", answer="x")
    assert exc.value.status == "question_not_found"


# --- CLI ------------------------------------------------------------------------------

@pytest.fixture
def host_skill(tmp_path: Path) -> Path:
    d = tmp_path / "skills" / "demo-skill"
    d.mkdir(parents=True)
    (d / "client-config.md").write_text(CONFIG)
    return d


def run(capsys, *argv):
    code = main(["question", *argv])
    return code, json.loads(capsys.readouterr().out)


def test_cli_dry_run_touches_nothing(capsys, host_skill):
    code, out = run(capsys, "add", str(host_skill), "--key", "weekday", "--suggested", "Monday")
    assert (code, out["status"], out["changed"]) == (0, "planned", False)
    assert (host_skill / "client-config.md").read_text() == CONFIG


def test_cli_apply_writes(capsys, host_skill):
    code, out = run(capsys, "add", str(host_skill), "--key", "weekday", "--suggested", "Monday", "--apply")
    assert (code, out["status"], out["changed"]) == (0, "applied", True)
    assert "weekday" in keys((host_skill / "client-config.md").read_text())


def test_cli_report_never_contains_answer_values(capsys, host_skill):
    _, out = run(capsys, "change", str(host_skill), "--key", "run_time", "--answer", "SECRET-09:00", "--apply")
    assert "SECRET" not in json.dumps(out)


@pytest.mark.parametrize(
    "argv, code, status",
    [
        (["remove", "{d}", "--key", "interval_days", "--apply"], 14, "answer_would_be_lost"),
        (["remove", "{d}", "--key", "run_time", "--apply"], 13, "golden_question"),
        (["add", "{d}", "--key", "run_time", "--suggested", "x"], 13, "question_exists"),
        (["change", "{d}", "--key", "nope", "--answer", "x"], 13, "question_not_found"),
    ],
)
def test_cli_refusals_have_stable_codes_and_write_nothing(capsys, host_skill, argv, code, status):
    got, out = run(capsys, *[a.format(d=host_skill) for a in argv])
    assert (got, out["ok"], out["status"]) == (code, False, status)
    assert (host_skill / "client-config.md").read_text() == CONFIG


def test_cli_without_client_config(capsys, tmp_path):
    code, out = run(capsys, "add", str(tmp_path), "--key", "k", "--suggested", "s")
    assert (code, out["status"]) == (10, "invalid_input")
