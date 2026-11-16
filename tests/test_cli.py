import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from claw_skills_kit.cli import main

TEMPLATE = """# demo-skill: settings (Layer 2)

<!-- test fixture -->

## Standards
| Setting | Standard |
|---|---|
| schedule | Every hour |

## Client answers
| Setting | Comes from | Suggested answer | Value |
|---|---|---|---|
| extra urgent_rules | Q1 | Anything with a deadline | |
| critical_senders | Q2 | Our clients | Our clients |
"""

TEMPLATE_NAME = "client-config.template.md"
KEY = "extra urgent_rules"


@pytest.fixture
def skill_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "golden-skills" / "demo-skill"
    folder.mkdir(parents=True)
    (folder / TEMPLATE_NAME).write_bytes(TEMPLATE.encode("utf-8"))
    return folder


@pytest.fixture
def out(tmp_path: Path) -> Path:
    return tmp_path / "client-a" / "skills" / "demo-skill" / "client-config.md"


def write_answers(tmp_path: Path, content) -> Path:
    path = tmp_path / "answers.json"
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
    return path


def run(capsys, skill_dir: Path, answers: Path, out: Path):
    code = main(["fill", str(skill_dir), "--answers", str(answers), "--out", str(out)])
    return code, json.loads(capsys.readouterr().out)


# --- the happy path --------------------------------------------------------------

def test_fills_the_config_and_reports_ok(skill_dir, tmp_path, out, capsys):
    answers = write_answers(tmp_path, {KEY: "Deadlines and payments"})
    code, report = run(capsys, skill_dir, answers, out)
    assert code == 0
    assert report == {"ok": True, "status": "ok", "out": str(out), "changed": True}
    assert "| Deadlines and payments |" in out.read_text(encoding="utf-8")


def test_a_second_run_changes_nothing(skill_dir, tmp_path, out, capsys):
    answers = write_answers(tmp_path, {KEY: "Deadlines"})
    run(capsys, skill_dir, answers, out)
    first = out.read_bytes()
    code, report = run(capsys, skill_dir, answers, out)
    assert code == 0
    assert report["changed"] is False
    assert out.read_bytes() == first


def test_never_modifies_the_template(skill_dir, tmp_path, out, capsys):
    before = (skill_dir / TEMPLATE_NAME).read_bytes()
    run(capsys, skill_dir, write_answers(tmp_path, {KEY: "Deadlines"}), out)
    assert (skill_dir / TEMPLATE_NAME).read_bytes() == before


def test_keeps_the_templates_line_endings(skill_dir, tmp_path, out, capsys):
    (skill_dir / TEMPLATE_NAME).write_bytes(TEMPLATE.replace("\n", "\r\n").encode("utf-8"))
    run(capsys, skill_dir, write_answers(tmp_path, {KEY: "Deadlines"}), out)
    data = out.read_bytes()
    assert b"\r\n" in data
    assert data.replace(b"\r\n", b"").count(b"\n") == 0


def test_does_not_echo_answer_values_in_its_output(skill_dir, tmp_path, out, capsys):
    main(["fill", str(skill_dir), "--answers", str(write_answers(tmp_path, {KEY: "Deadlines and payments"})),
          "--out", str(out)])
    assert "Deadlines and payments" not in capsys.readouterr().out


# --- refusing: missing required answers (exit 5) --------------------------------

def test_refuses_when_a_required_answer_is_missing_and_writes_nothing(skill_dir, tmp_path, out, capsys):
    code, report = run(capsys, skill_dir, write_answers(tmp_path, {}), out)
    assert code == 5
    assert report["ok"] is False
    assert report["status"] == "missing_required"
    assert report["missing"] == [
        {"key": KEY, "comes_from": "Q1", "suggested": "Anything with a deadline"}
    ]
    assert not out.exists()


def test_a_refused_run_leaves_an_existing_output_as_it_was(skill_dir, tmp_path, out, capsys):
    out.parent.mkdir(parents=True)
    out.write_text("previous content", encoding="utf-8")
    code, _ = run(capsys, skill_dir, write_answers(tmp_path, {}), out)
    assert code == 5
    assert out.read_text(encoding="utf-8") == "previous content"


# --- refusing: invalid answers (exit 4) -----------------------------------------

def test_rejects_unknown_answer_keys(skill_dir, tmp_path, out, capsys):
    code, report = run(capsys, skill_dir, write_answers(tmp_path, {"extra urgent_rulez": "x"}), out)
    assert code == 4
    assert report["status"] == "invalid_answers"
    assert "extra urgent_rulez" in report["error"]


def test_rejects_answers_that_override_a_standard(skill_dir, tmp_path, out, capsys):
    code, report = run(capsys, skill_dir, write_answers(tmp_path, {"schedule": "every minute"}), out)
    assert code == 4
    assert "standard" in report["error"]


def test_rejects_an_answers_file_that_is_not_valid_json(skill_dir, tmp_path, out, capsys):
    code, report = run(capsys, skill_dir, write_answers(tmp_path, '{"extra urgent_rules": '), out)
    assert code == 4
    assert report["status"] == "invalid_answers"


def test_reports_a_missing_answers_file(skill_dir, tmp_path, out, capsys):
    code, report = run(capsys, skill_dir, tmp_path / "does-not-exist.json", out)
    assert code == 4
    assert report["status"] == "invalid_answers"


def test_rejects_an_answer_that_cannot_be_written_to_the_table(skill_dir, tmp_path, out, capsys):
    code, report = run(capsys, skill_dir, write_answers(tmp_path, {KEY: "a|b"}), out)
    assert code == 4
    assert KEY in report["error"]
    assert not out.exists()


# --- refusing: invalid template (exit 3) ----------------------------------------

def test_reports_an_invalid_template(skill_dir, tmp_path, out, capsys):
    (skill_dir / TEMPLATE_NAME).write_text("# nothing useful here\n", encoding="utf-8")
    code, report = run(capsys, skill_dir, write_answers(tmp_path, {}), out)
    assert code == 3
    assert report["status"] == "invalid_template"


def test_reports_a_missing_template(skill_dir, tmp_path, out, capsys):
    (skill_dir / TEMPLATE_NAME).unlink()
    code, report = run(capsys, skill_dir, write_answers(tmp_path, {}), out)
    assert code == 3
    assert report["status"] == "invalid_template"


# --- usage errors (exit 2, from argparse) ---------------------------------------

def test_usage_errors_exit_with_code_2():
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_refuses_to_overwrite_the_template(skill_dir, tmp_path):
    answers = write_answers(tmp_path, {KEY: "Deadlines"})
    with pytest.raises(SystemExit) as exc:
        main(["fill", str(skill_dir), "--answers", str(answers), "--out", str(skill_dir / TEMPLATE_NAME)])
    assert exc.value.code == 2


# --- bugs and failed writes ------------------------------------------------------

def test_an_unexpected_error_is_reported_as_json_and_logged_to_stderr(skill_dir, tmp_path, capsys):
    answers = write_answers(tmp_path, {KEY: "Deadlines"})
    blocked = tmp_path / "a-directory"
    blocked.mkdir()  # --out points to a directory: writing to it must fail
    code = main(["fill", str(skill_dir), "--answers", str(answers), "--out", str(blocked)])
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert code == 1
    assert report["ok"] is False
    assert report["status"] == "unexpected_error"
    assert "Traceback" in captured.err


def test_a_failed_write_leaves_no_temporary_file(skill_dir, tmp_path, out, capsys, monkeypatch):
    def boom(self, target):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", boom)
    code, report = run(capsys, skill_dir, write_answers(tmp_path, {KEY: "Deadlines"}), out)
    assert code == 1
    assert report["status"] == "unexpected_error"
    assert not list(out.parent.glob("*.tmp"))
    assert not out.exists()


# --- the real command line -------------------------------------------------------

def test_the_command_line_propagates_exit_codes(skill_dir, tmp_path, out):
    answers = write_answers(tmp_path, {})
    result = subprocess.run(
        [sys.executable, "-m", "claw_skills_kit", "fill", str(skill_dir),
         "--answers", str(answers), "--out", str(out)],
        capture_output=True, text=True, env={**os.environ},
    )
    assert result.returncode == 5
    assert json.loads(result.stdout)["status"] == "missing_required"