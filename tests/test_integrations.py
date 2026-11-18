import json
import shlex
import shutil
import sys
from pathlib import Path

import pytest

from claw_skills_kit.cli import main
from claw_skills_kit.integrations import IntegrationError, Requirements, plan_disable, plan_enable, read_requirements

ROOT = Path(__file__).parents[1]
FAKE = ROOT / "tests/fake_openclaw.py"
TEAM_DIGEST = ROOT / "library/releases/2026.11.18/skills/team-digest"
KEYED = """---
name: keyed
description: needs a key
metadata:
  openclaw:
    requires:
      env:
        - KEYED_TOKEN
        - KEYED_REGION
    primaryEnv: KEYED_TOKEN
---
body
"""


# --- reading what a skill needs --------------------------------------------------------------------

def test_reads_the_library_skill_that_needs_a_channel():
    req = read_requirements((TEAM_DIGEST / "SKILL.md").read_text(encoding="utf-8"))
    assert req == Requirements(("TEAM_DIGEST_CHANNEL",), None)


def test_reads_dash_lists_and_primary_env():
    assert read_requirements(KEYED) == Requirements(("KEYED_TOKEN", "KEYED_REGION"), "KEYED_TOKEN")


def test_a_skill_without_an_openclaw_block_needs_nothing():
    assert read_requirements("---\nname: x\nmetadata:\n  layer: 1\n---\nbody\n") == Requirements()


def test_a_one_line_json5_openclaw_block_is_refused_not_misread():
    text = '---\nname: x\nmetadata:\n  openclaw: { "requires": { "env": ["A"] } }\n---\n'
    with pytest.raises(IntegrationError) as exc:
        read_requirements(text)
    assert exc.value.status == "invalid_skill"


# --- planning: refuse before writing ---------------------------------------------------------------

REQ = Requirements(("TEAM_DIGEST_CHANNEL", "KEYED_TOKEN"), "KEYED_TOKEN")


@pytest.mark.parametrize(
    "env, api_key_env, status",
    [
        ({"OTHER": "x"}, None, "not_required"),
        ({"KEYED_TOKEN": "abc"}, None, "secret_value_refused"),
        ({"TEAM_DIGEST_CHANNEL": "sk-live-0123456789abcdef"}, None, "looks_like_secret"),
        ({"TEAM_DIGEST_CHANNEL": "A" * 40}, None, "looks_like_secret"),
        ({"TEAM_DIGEST_CHANNEL": "two\nlines"}, None, "invalid_integration"),
        ({"TEAM_DIGEST_CHANNEL": "  "}, None, "invalid_integration"),
        ({}, "not-a-name", "invalid_integration"),
        ({}, None, "invalid_integration"),
    ],
)
def test_enable_refusals(env, api_key_env, status):
    with pytest.raises(IntegrationError) as exc:
        plan_enable("s", REQ, None, env, api_key_env)
    assert exc.value.status == status


def test_api_key_needs_a_primary_env():
    with pytest.raises(IntegrationError) as exc:
        plan_enable("s", Requirements(("A",)), None, {}, "SOME_KEY")
    assert exc.value.status == "no_primary_env"


def test_disable_keeps_what_enable_did_not_set():
    before = {"enabled": True, "env": {"TEAM_DIGEST_CHANNEL": "#team", "EXTRA": "1"}, "apiKey": {"id": "K"}}
    plan = plan_disable("s", REQ, before)
    assert plan.entry_after == {"enabled": True, "env": {"EXTRA": "1"}}
    assert plan.env_names == ("TEAM_DIGEST_CHANNEL",) and plan.api_key_ref


# --- the command, against a fake openclaw ----------------------------------------------------------

@pytest.fixture
def host(tmp_path, monkeypatch):
    state = tmp_path / "state"
    (state / "skills").mkdir(parents=True)
    shutil.copytree(TEAM_DIGEST, state / "skills/team-digest")
    (state / "skills/keyed").mkdir()
    (state / "skills/keyed/SKILL.md").write_text(KEYED)
    (state / "openclaw.json").write_text(json.dumps({"skills": {"entries": {"other": {"enabled": False}}}}))
    for name in ("TEAM_DIGEST_CHANNEL", "KEYED_TOKEN", "KEYED_REGION"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CSK_OPENCLAW", shlex.join([sys.executable, str(FAKE), str(state)]))
    return state


def run(capsys, *argv):
    code = main(["integration", *argv])
    return code, json.loads(capsys.readouterr().out)


def entry(state, skill):
    return json.loads((state / "openclaw.json").read_text())["skills"]["entries"].get(skill)


def test_status_says_what_is_missing(capsys, host):
    code, out = run(capsys, "status", str(host / "skills"), "--name", "team-digest")
    assert code == 0
    assert (out["status"], out["missing_env"]) == ("not_ready", ["TEAM_DIGEST_CHANNEL"])


def test_enable_dry_run_then_apply_then_again(capsys, host):
    args = ["enable", str(host / "skills"), "--name", "team-digest", "--env", "TEAM_DIGEST_CHANNEL=#acme-team"]
    code, out = run(capsys, *args)
    assert (code, out["status"], out["ready"]) == (0, "planned", None)
    assert entry(host, "team-digest") is None  # dry run wrote nothing

    code, out = run(capsys, *args, "--apply")
    assert (code, out["status"], out["ready"], out["env"]) == (0, "applied", True, ["TEAM_DIGEST_CHANNEL"])
    assert "#acme-team" not in json.dumps(out)  # names only, never values
    assert entry(host, "team-digest") == {"env": {"TEAM_DIGEST_CHANNEL": "#acme-team"}}
    assert entry(host, "other") == {"enabled": False}  # other skills untouched

    code, out = run(capsys, *args, "--apply")
    assert (code, out["status"]) == (0, "unchanged")
    assert (host / "skills/team-digest/SKILL.md").read_bytes() == (TEAM_DIGEST / "SKILL.md").read_bytes()


def test_enable_switches_on_a_skill_openclaw_marked_disabled(capsys, host):
    # seen on the real gateway: a skill installed with missing requirements gets `enabled: false`
    config = json.loads((host / "openclaw.json").read_text())
    config["skills"]["entries"]["team-digest"] = {"enabled": False}
    (host / "openclaw.json").write_text(json.dumps(config))
    code, out = run(capsys, "enable", str(host / "skills"), "--name", "team-digest",
                    "--env", "TEAM_DIGEST_CHANNEL=#t", "--apply")
    assert (code, out["status"], out["ready"]) == (0, "applied", True)
    assert entry(host, "team-digest") == {"enabled": True, "env": {"TEAM_DIGEST_CHANNEL": "#t"}}


def test_disable_removes_it_and_the_skill_stops_loading(capsys, host):
    run(capsys, "enable", str(host / "skills"), "--name", "team-digest", "--env", "TEAM_DIGEST_CHANNEL=#t", "--apply")
    code, out = run(capsys, "disable", str(host / "skills"), "--name", "team-digest", "--apply")
    assert (code, out["status"], out["ready"]) == (0, "applied", False)
    assert entry(host, "team-digest") is None


def test_api_key_is_stored_as_a_reference(capsys, host):
    code, out = run(capsys, "enable", str(host / "skills"), "--name", "keyed",
                    "--env", "KEYED_REGION=eu", "--api-key-env", "KEYED_API_KEY", "--apply")
    assert (code, out["status"], out["ready"], out["api_key_ref"]) == (0, "applied", True, True)
    assert entry(host, "keyed")["apiKey"] == {"source": "env", "provider": "default", "id": "KEYED_API_KEY"}


@pytest.mark.parametrize("switch", ["invalid", "never_ready"])
def test_a_failed_check_puts_the_config_back(capsys, host, switch):
    before = (host / "openclaw.json").read_text()
    (host / switch).touch()
    code, out = run(capsys, "enable", str(host / "skills"), "--name", "team-digest",
                    "--env", "TEAM_DIGEST_CHANNEL=#t", "--apply")
    assert (code, out["status"]) == (6, "rolled_back")
    assert json.loads((host / "openclaw.json").read_text()) == json.loads(before)


@pytest.mark.parametrize(
    "argv, code, status",
    [
        (["enable", "{d}", "--name", "nope", "--env", "A=b"], 11, "skill_not_found"),
        (["enable", "{d}", "--name", "team-digest", "--env", "OTHER=x"], 15, "not_required"),
        (["enable", "{d}", "--name", "keyed", "--env", "KEYED_TOKEN=abc"], 15, "secret_value_refused"),
        (["enable", "{d}", "--name", "team-digest", "--env", "no-equals"], 15, "invalid_integration"),
    ],
)
def test_cli_refusals_write_nothing(capsys, host, argv, code, status):
    before = (host / "openclaw.json").read_text()
    got, out = run(capsys, *[a.format(d=host / "skills") for a in argv], "--apply")
    assert (got, out["ok"], out["status"]) == (code, False, status)
    assert (host / "openclaw.json").read_text() == before
