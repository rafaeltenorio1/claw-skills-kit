import json

import pytest

from claw_skills_kit.cli import main


@pytest.fixture
def host(tmp_path):
    path = tmp_path / "host.json"
    path.write_text(json.dumps({
        "host_id": "csk-demo", "skills_dir": "/x", "clients": ["acme"], "skills": ["inbox-triage"],
    }))
    return path


def run(capsys, *argv):
    code = main(["host", *argv])
    return code, json.loads(capsys.readouterr().out)


def test_show(capsys, host):
    code, out = run(capsys, "show", "--host", str(host))
    assert (code, out["client"], out["skills"]) == (0, "acme", ["inbox-triage"])


@pytest.mark.parametrize("name", ["acme", "ACME", " acme "])
def test_the_same_client_is_fine(capsys, host, name):
    code, out = run(capsys, "check-client", "--host", str(host), "--name", name)
    assert (code, out["status"]) == (0, "same_client")


def test_another_client_is_refused_with_the_reconcilers_tenant_code(capsys, host):
    before = host.read_text()
    code, out = run(capsys, "check-client", "--host", str(host), "--name", "beta-corp")
    assert (code, out["ok"], out["status"], out["client"]) == (8, False, "tenant_conflict", "acme")
    assert host.read_text() == before  # read-only


def test_a_host_that_already_has_two_clients_is_refused(capsys, tmp_path):
    path = tmp_path / "host.json"
    path.write_text(json.dumps({"host_id": "h", "skills_dir": "/x", "clients": ["a", "b"], "skills": []}))
    code, out = run(capsys, "show", "--host", str(path))
    assert (code, out["status"]) == (8, "tenant_conflict")


@pytest.mark.parametrize("argv, code", [(["--name", ""], 10), (["--name", "x"], 10)])
def test_bad_input(capsys, tmp_path, host, argv, code):
    target = host if argv[1] == "" else tmp_path / "missing.json"
    got, out = run(capsys, "check-client", "--host", str(target), *argv)
    assert (got, out["ok"]) == (code, False)


# --- verify-skills: the smoke check that OpenClaw finds every operator skill ----------------------------

import shlex  # noqa: E402
import shutil  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).parents[1]
RELEASE = ROOT / "library/releases/2026.11.18/skills"


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    state = tmp_path / "state"
    (state / "skills").mkdir(parents=True)
    for skill in ("inbox-triage", "meeting-notes"):
        shutil.copytree(RELEASE / skill, state / "skills" / skill)
    (state / "openclaw.json").write_text("{}")
    host = tmp_path / "host.json"
    host.write_text(json.dumps({"host_id": "h", "skills_dir": str(state / "skills"), "clients": ["acme"],
                                "skills": ["inbox-triage", "meeting-notes"]}))
    fake = [sys.executable, str(ROOT / "tests/fake_openclaw.py"), str(state)]
    monkeypatch.setenv("CSK_OPENCLAW", shlex.join(fake))
    return state, host


def test_verify_skills_passes_when_openclaw_finds_them_all(capsys, gateway):
    state, host = gateway
    code, out = run(capsys, "verify-skills", "--host", str(host))
    assert (code, out["status"]) == (0, "ok")


def test_verify_skills_names_a_skill_with_a_broken_frontmatter(capsys, gateway):
    state, host = gateway
    md = state / "skills/meeting-notes/SKILL.md"
    md.write_text(md.read_text().replace("description: Turn", "description: [Turn", 1))
    code, out = run(capsys, "verify-skills", "--host", str(host))
    assert (code, out["status"], out["missing"]) == (11, "skills_not_loaded", ["meeting-notes"])


def test_verify_skills_names_a_missing_folder(capsys, gateway):
    state, host = gateway
    shutil.rmtree(state / "skills/inbox-triage")
    code, out = run(capsys, "verify-skills", "--host", str(host))
    assert (code, out["missing"]) == (11, ["inbox-triage"])


def test_a_disabled_skill_waiting_for_its_integration_still_counts(capsys, gateway):
    state, host = gateway
    (state / "openclaw.json").write_text(json.dumps({"skills": {"entries": {"meeting-notes": {"enabled": False}}}}))
    code, out = run(capsys, "verify-skills", "--host", str(host))
    assert (code, out["status"]) == (0, "ok")


@pytest.mark.parametrize("watch", [None, True, False])
def test_verify_skills_leaves_the_watch_setting_as_it_was(capsys, gateway, watch):
    state, host = gateway
    config = {} if watch is None else {"skills": {"load": {"watch": watch}}}
    (state / "openclaw.json").write_text(json.dumps(config))
    code, _ = run(capsys, "verify-skills", "--host", str(host))
    after = json.loads((state / "openclaw.json").read_text())
    assert code == 0
    assert ((after.get("skills") or {}).get("load") or {}).get("watch") == watch


# --- releases: where this host is, and the next release ----------------------------------------------

from claw_skills_kit.reconcile import reconcile as _reconcile  # noqa: E402
from claw_skills_kit.reconciler.descriptor import load_descriptor as _load  # noqa: E402
from claw_skills_kit.reconciler.host import LocalHost as _Local  # noqa: E402
from claw_skills_kit.reconciler.lockfile import load_pins as _pins  # noqa: E402

RELEASES = ROOT / "library/releases"


@pytest.fixture
def installed(tmp_path):
    skills = tmp_path / "skills"
    skills.mkdir()
    host = tmp_path / "host.json"
    host.write_text(json.dumps({"host_id": "h", "skills_dir": str(skills), "clients": ["acme"],
                                "skills": ["inbox-triage", "meeting-notes", "team-digest"]}))

    def install(release):
        rel = RELEASES / release
        pins = _pins((rel / "skills.lock.json").read_text())
        report = _reconcile(_load(host.read_text()), _Local(rel / "skills"), _Local(skills), pins, apply=True)
        assert report.status in ("applied", "unchanged")

    return host, skills, install


def test_releases_reports_current_and_the_next_one(capsys, installed, tmp_path):
    host, skills, install = installed
    install("2026.11.10")
    code, out = run(capsys, "releases", "--host", str(host), "--releases", str(RELEASES))
    assert (code, out["current"], out["next"]) == (0, "2026.11.10", "2026.11.18")
    install("2026.11.18")
    code, out = run(capsys, "releases", "--host", str(host), "--releases", str(RELEASES))
    assert (out["current"], out["next"], out["newer"]) == ("2026.11.18", None, [])
    # with the rollback demo on, the broken release is the next one (as the image does with CSK_DEMO_ROLLBACK=1)
    both = tmp_path / "with-demo"
    shutil.copytree(RELEASES, both)
    shutil.copytree(ROOT / "library/demo-releases/2026.11.25", both / "2026.11.25")
    code, out = run(capsys, "releases", "--host", str(host), "--releases", str(both))
    assert (out["current"], out["next"]) == ("2026.11.18", "2026.11.25")


def test_answers_do_not_make_a_host_look_out_of_date(capsys, installed):
    host, skills, install = installed
    install("2026.11.10")
    cfg = skills / "meeting-notes/client-config.md"
    cfg.write_text(cfg.read_text().replace("| Five short bullet points | |", "| Five short bullet points | Bullets |"))
    code, out = run(capsys, "releases", "--host", str(host), "--releases", str(RELEASES))
    assert out["current"] == "2026.11.10"


def test_a_hand_edited_host_is_reported_as_drift(capsys, installed):
    host, skills, install = installed
    install("2026.11.10")
    (skills / "inbox-triage/SKILL.md").write_text("edited by hand\n")
    code, out = run(capsys, "releases", "--host", str(host), "--releases", str(RELEASES))
    assert (code, out["status"], out["current"], out["next"]) == (0, "drift", None, None)
