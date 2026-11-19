import json
from pathlib import Path

import pytest

from claw_skills_kit.cli import main

ROOT = Path(__file__).parents[1]
RELEASES = ROOT / "library/releases"
SKILLS = ["inbox-triage", "meeting-notes", "team-digest"]


@pytest.fixture
def host(tmp_path):
    skills = tmp_path / "skills"
    skills.mkdir()
    descriptor = tmp_path / "host.json"
    descriptor.write_text(json.dumps({"host_id": "h", "skills_dir": str(skills), "clients": ["acme"],
                                      "skills": SKILLS}))
    return descriptor, skills


def reconcile(capsys, host, release, *extra):
    descriptor, skills = host
    rel = RELEASES / release
    code = main(["reconcile", "--host", str(descriptor), "--library", str(rel / "skills"), "--target", str(skills),
                 "--pins", str(rel / "skills.lock.json"), *extra])
    return code, json.loads(capsys.readouterr().out)


def answered(host):
    cfg = host[1] / "meeting-notes/client-config.md"
    cfg.write_text(cfg.read_text().replace("| Five short bullet points | |", "| Five short bullet points | MY-ANSWER |"))


def test_the_diff_shows_skill_changes_and_summarises_settings_by_key(capsys, host):
    reconcile(capsys, host, "2026.11.10", "--apply")
    answered(host)
    code, out = reconcile(capsys, host, "2026.11.18", "--diff")
    assert (code, out["status"]) == (0, "planned")
    diff = out["diff"]
    assert "+5. Group the messages by sender" in diff
    assert "~ meeting-notes/client-config.md (answer values not shown)\n  + question summary_language" in diff
    assert "~ inbox-triage/client-config.md (answer values not shown)\n  + standard grouping" in diff
    assert "MY-ANSWER" not in json.dumps(out)


def test_the_diff_is_the_same_for_the_same_input(capsys, host):
    reconcile(capsys, host, "2026.11.10", "--apply")
    first = reconcile(capsys, host, "2026.11.18", "--diff")[1]["diff"]
    second = reconcile(capsys, host, "2026.11.18", "--diff")[1]["diff"]
    assert first == second


def test_with_apply_the_diff_describes_what_was_written(capsys, host):
    reconcile(capsys, host, "2026.11.10", "--apply")
    code, out = reconcile(capsys, host, "2026.11.18", "--diff", "--apply")
    assert (code, out["status"]) == (0, "applied")
    assert "-  version: 0.1.0\n+  version: 0.2.0" in out["diff"]
    assert reconcile(capsys, host, "2026.11.18", "--diff")[1]["diff"] == ""


def test_a_first_install_diffs_from_nothing(capsys, host):
    code, out = reconcile(capsys, host, "2026.11.10", "--diff")
    assert "--- /dev/null\n+++ b/inbox-triage/SKILL.md" in out["diff"]
    block = out["diff"].split("~ team-digest/client-config.md (answer values not shown)\n", 1)[1]
    assert "  + standard schedule\n" in block and "  + question digest_sections\n" in block


def test_without_the_flag_there_is_no_diff(capsys, host):
    code, out = reconcile(capsys, host, "2026.11.10")
    assert "diff" not in out
