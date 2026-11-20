import json
from pathlib import Path

import pytest

from claw_skills_kit.cli import main
from claw_skills_kit.layer1 import find_client_specifics, lint_skill

ROOT = Path(__file__).parents[1]
GOOD = sorted((ROOT / "library/releases").glob("*/skills/*"))


@pytest.mark.parametrize(
    "line, kind",
    [
        ("Send the report to joao@acme.com.", "email"),
        ("Call +55 91 98765-4321 if it fails.", "phone"),
        ("Or (91) 3201-7000 at the office.", "phone"),
        ("Post it in #team-acme.", "chat_channel"),
        ("Slack channel C0123ABCD9.", "chat_id"),
        ("Discord channel 123456789012345678.", "chat_id"),
        ("Telegram group -1001234567890.", "chat_id"),
        ("The sheet is at https://docs.google.com/spreadsheets/d/x.", "drive_link"),
        ("Use key sk-live-0123456789abcdefgh.", "secret"),
        ("token=ghp_abcdefghij0123456789", "secret"),
        ("-----BEGIN RSA PRIVATE KEY-----", "secret"),
        ("Fetch https://user:pass@example.org/feed", "url_credentials"),
    ],
)
def test_finds_client_specifics(line, kind):
    assert kind in {f.kind for f in find_client_specifics(line)}


@pytest.mark.parametrize(
    "line",
    [
        "## Procedure",
        "Release 2026.11.18, version 0.2.0, on 2026-11-18.",
        "The channel is the one named in `TEAM_DIGEST_CHANNEL`.",
        "Run `{baseDir}/scripts/precheck.py --json`.",
        "Failures go to #<agent>-ops.",
        "CONSTRAINTS and RULES apply.",
    ],
)
def test_leaves_generic_text_alone(line):
    assert find_client_specifics(line) == []


def test_findings_carry_kind_and_line_never_the_text():
    found = find_client_specifics("ok\nmail joao@acme.com\n", "SKILL.md")
    assert [f.to_dict() for f in found] == [{"file": "SKILL.md", "line": 2, "kind": "email"}]
    assert "joao" not in json.dumps([f.to_dict() for f in found])


@pytest.mark.parametrize("folder", GOOD, ids=lambda p: f"{p.parents[1].name}/{p.name}")
def test_the_library_passes_the_lint(folder):
    assert lint_skill(folder, library=True) == []


def test_lint_catches_the_rollback_demo_release():
    folder = ROOT / "library/demo-releases/2026.11.25/skills/meeting-notes"
    assert [f.kind for f in lint_skill(folder, library=True)] == ["no_description"]


def test_lint_reports_missing_files_and_leaks(tmp_path):
    folder = tmp_path / "leaky"
    (folder / "scripts").mkdir(parents=True)
    (folder / "SKILL.md").write_text("---\nname: leaky\ndescription: d\n---\nPost to #team-acme\n")
    (folder / "scripts/send.py").write_text("TO = 'joao@acme.com'\n")
    kinds = {(f.file, f.kind) for f in lint_skill(folder, library=True)}
    assert {("interview.md", "missing_file"), ("SKILL.md", "chat_channel"), ("scripts/send.py", "email")} <= kinds


def run(capsys, *argv):
    code = main(list(argv))
    return code, json.loads(capsys.readouterr().out)


def test_cli_lint(capsys, tmp_path):
    code, out = run(capsys, "lint", "--library", *map(str, GOOD[:3]))
    assert (code, out["status"]) == (0, "ok")
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "SKILL.md").write_text("---\nname: bad\ndescription: d\n---\nemail joao@acme.com\n")
    code, out = run(capsys, "lint", str(bad))
    assert (code, out["status"], out["skills"]["bad"]) == (
        11, "lint_failed", [{"file": "SKILL.md", "line": 5, "kind": "email"}]
    )


def test_skill_create_refuses_client_data_and_writes_nothing(capsys, tmp_path):
    skills = tmp_path / "skills"
    skills.mkdir()
    code, out = run(capsys, "skill", "create", str(skills), "--name", "weekly-report", "--description", "d",
                    "--instructions", "Every Friday email the report to joao@acme.com.", "--apply")
    assert (code, out["status"]) == (11, "client_data_in_skill")
    assert out["findings"][0]["kind"] == "email" and "joao" not in json.dumps(out)
    assert not (skills / "weekly-report").exists()


def test_the_client_data_goes_in_a_question_instead(capsys, tmp_path):
    skills = tmp_path / "skills"
    skills.mkdir()
    code, out = run(capsys, "skill", "create", str(skills), "--name", "weekly-report", "--description", "d",
                    "--instructions", "Every Friday email the report to the recipient in client-config.md.",
                    "--question", "report.recipient", "Who receives the report", "joao@acme.com", "--apply")
    assert (code, out["status"]) == (0, "applied")
    assert "joao@acme.com" in (skills / "weekly-report/client-config.md").read_text()
    assert "joao" not in (skills / "weekly-report/SKILL.md").read_text()
