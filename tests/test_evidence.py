import json
import shutil
from pathlib import Path

import pytest

from claw_skills_kit.cli import main
from claw_skills_kit.evidence import history, record_approval

ROOT = Path(__file__).parents[1]
NOTES = ROOT / "library/releases/2026.11.18/skills/meeting-notes"


@pytest.fixture
def skill(tmp_path):
    folder = tmp_path / "skills/meeting-notes"
    shutil.copytree(NOTES, folder)
    shutil.copy(folder / "client-config.template.md", folder / "client-config.md")
    return folder


@pytest.fixture
def log(tmp_path, monkeypatch):
    path = tmp_path / "csk/evidence.jsonl"
    monkeypatch.setenv("CSK_EVIDENCE", str(path))
    return path


def run(capsys, *argv):
    code = main(list(argv))
    return code, json.loads(capsys.readouterr().out)


def answer(skill, *extra):
    return ["question", "change", str(skill), "--key", "summary_style", "--answer", "Bullets", *extra]


def test_without_evidence_nothing_is_required_or_written(capsys, skill, tmp_path, monkeypatch):
    monkeypatch.delenv("CSK_EVIDENCE", raising=False)
    code, out = run(capsys, *answer(skill, "--apply"))
    assert (code, out["status"]) == (0, "applied")
    assert not any(tmp_path.rglob("evidence.jsonl"))


def test_an_apply_without_approval_is_refused_and_changes_nothing(capsys, skill, log):
    before = (skill / "client-config.md").read_text()
    code, out = run(capsys, *answer(skill, "--apply"))
    assert (code, out["status"]) == (10, "approval_required")
    assert (skill / "client-config.md").read_text() == before
    assert not log.exists()


def test_a_dry_run_needs_no_approval_and_records_nothing(capsys, skill, log):
    code, out = run(capsys, *answer(skill))
    assert (code, out["status"]) == (0, "planned")
    assert not log.exists()


def test_an_approval_with_client_data_is_refused(capsys, skill, log):
    code, out = run(capsys, *answer(skill, "--apply", "--approval", "Send summaries to joao@acme.com?"))
    assert (code, out["status"]) == (10, "approval_has_client_data")
    assert not log.exists()


def test_approval_is_recorded_before_and_the_result_after(capsys, skill, log):
    code, out = run(capsys, *answer(skill, "--apply", "--approval", "Save your summary style?"))
    assert code == 0
    lines = [json.loads(line) for line in log.read_text().splitlines()]
    assert [r["phase"] for r in lines] == ["approved", "result"]
    assert lines[0]["id"] == lines[1]["id"]
    assert lines[0]["approval"] == "Save your summary style?"
    assert lines[1]["status"] == "applied" and lines[1]["key"] == "summary_style"
    assert "Bullets" not in log.read_text()  # keys only, never answer values


def test_a_refused_apply_is_recorded_with_its_status(capsys, tmp_path, log):
    skills = tmp_path / "skills"
    shutil.copytree(NOTES, skills / "meeting-notes")
    code, out = run(capsys, "skill", "remove", str(skills), "--name", "meeting-notes", "--apply",
                    "--approval", "Remove the meeting notes skill?")
    assert code == 11
    (entry,) = history(log)
    assert (entry["status"], entry["exit_code"], entry["command"]) == ("library_skill", 11, "skill")


def test_history_is_newest_first_and_tolerates_a_torn_line(capsys, skill, log):
    run(capsys, *answer(skill, "--apply", "--approval", "first?"))
    run(capsys, "question", "change", str(skill), "--key", "summary_language", "--answer", "English",
        "--apply", "--approval", "second?")
    with open(log, "a") as f:
        f.write('{"id": "torn", "pha')  # a crash in the middle of a write
    code, out = run(capsys, "history", "--limit", "5")
    assert code == 0
    assert [c["approval"] for c in out["changes"]] == ["second?", "first?"]
    assert all(c["status"] == "applied" for c in out["changes"])


def test_an_approval_without_a_result_shows_as_interrupted(log):
    record_approval(log, "reconcile", None, "/lib", "Install the update?")
    (entry,) = history(log)
    assert entry["status"] == "interrupted"


def test_history_without_an_evidence_file_is_refused(capsys, monkeypatch):
    monkeypatch.delenv("CSK_EVIDENCE", raising=False)
    code, out = run(capsys, "history")
    assert (code, out["status"]) == (10, "invalid_input")


def test_an_approval_that_repeats_the_answer_is_refused(capsys, skill, log):
    code, out = run(capsys, *answer(skill, "--apply", "--approval", "Save your summary style as bullets?"))
    assert (code, out["status"]) == (10, "approval_has_answer_value")
    assert not log.exists()


def test_an_approval_that_repeats_a_question_answer_on_create_is_refused(capsys, tmp_path, log):
    skills = tmp_path / "skills"
    skills.mkdir()
    code, out = run(capsys, "skill", "create", str(skills), "--name", "r", "--description", "d",
                    "--instructions", "Send it to the recipient in client-config.md.",
                    "--question", "when", "When to send", "Friday at 11:00",
                    "--apply", "--approval", "Create the report skill for Friday at 11:00?")
    assert (code, out["status"]) == (10, "approval_has_answer_value")
    assert not (skills / "r").exists()
