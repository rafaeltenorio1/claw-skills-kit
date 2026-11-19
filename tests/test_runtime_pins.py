"""Pins can also fix the OpenClaw and Node versions a host must run; reconcile refuses another version."""
import json
import shlex
import sys
from pathlib import Path

import pytest

from claw_skills_kit.cli import main
from claw_skills_kit.reconciler.lockfile import LockfileError, dump_pins, load_pins, load_runtime_pins

ROOT = Path(__file__).parents[1]
RELEASE = ROOT / "library/releases/2026.11.10"


def test_runtime_block_round_trips_and_is_optional():
    text = dump_pins({"a": "0" * 64}, {"openclaw": "2026.11.3", "node": "24.22.1"})
    assert load_runtime_pins(text) == {"openclaw": "2026.11.3", "node": "24.22.1"}
    assert load_pins(text) == {"a": "0" * 64}
    assert load_runtime_pins(dump_pins({"a": "0" * 64})) == {}


@pytest.mark.parametrize("runtime", [{"python": "3.14"}, {"node": ""}, {"node": "latest"}, []])
def test_bad_runtime_blocks_are_refused(runtime):
    with pytest.raises(LockfileError):
        load_runtime_pins(json.dumps({"skills": {}, "runtime": runtime}))


@pytest.fixture
def host(tmp_path, monkeypatch):
    skills = tmp_path / "skills"
    skills.mkdir()
    descriptor = tmp_path / "host.json"
    descriptor.write_text(json.dumps({"host_id": "h", "skills_dir": str(skills), "clients": ["acme"],
                                      "skills": ["inbox-triage", "meeting-notes", "team-digest"]}))
    fake = [sys.executable, str(ROOT / "tests/fake_openclaw.py"), str(tmp_path)]
    monkeypatch.setenv("CSK_OPENCLAW", shlex.join(fake))
    monkeypatch.setenv("CSK_NODE", shlex.join([sys.executable, "-c", "print('v24.22.1')"]))
    return descriptor, skills, tmp_path


def pins_with(tmp_path, runtime):
    lock = json.loads((RELEASE / "skills.lock.json").read_text())
    path = tmp_path / "pins.json"
    path.write_text(dump_pins(lock["skills"], runtime))
    return path


def reconcile(capsys, descriptor, skills, pins, *extra):
    code = main(["reconcile", "--host", str(descriptor), "--library", str(RELEASE / "skills"),
                 "--target", str(skills), "--pins", str(pins), *extra])
    return code, json.loads(capsys.readouterr().out)


def test_matching_versions_apply(capsys, host):
    descriptor, skills, tmp = host
    pins = pins_with(tmp, {"openclaw": "2026.11.3", "node": "24.22.1"})
    code, out = reconcile(capsys, descriptor, skills, pins, "--apply")
    assert (code, out["status"]) == (0, "applied")


@pytest.mark.parametrize("runtime, key", [({"openclaw": "2026.12.1"}, "openclaw"), ({"node": "26.0.0"}, "node")])
def test_another_version_is_refused_before_writing(capsys, host, runtime, key):
    descriptor, skills, tmp = host
    code, out = reconcile(capsys, descriptor, skills, pins_with(tmp, runtime), "--apply")
    assert (code, out["status"], out["runtime"]) == (9, "runtime_mismatch", key)
    assert not any(skills.iterdir())


def test_an_unreadable_version_is_refused(capsys, host, monkeypatch):
    descriptor, skills, tmp = host
    monkeypatch.setenv("CSK_NODE", shlex.join([sys.executable, "-c", "print('no version here')"]))
    code, out = reconcile(capsys, descriptor, skills, pins_with(tmp, {"node": "24.22.1"}))
    assert (code, out["status"]) == (9, "runtime_unknown")


def test_lock_writes_the_runtime_block(capsys, tmp_path):
    out_path = tmp_path / "pins.json"
    code = main(["lock", str(RELEASE / "skills"), "--skills", "inbox-triage", "--out", str(out_path),
                 "--openclaw", "2026.11.3", "--node", "24.22.1"])
    capsys.readouterr()
    assert code == 0
    assert load_runtime_pins(out_path.read_text()) == {"openclaw": "2026.11.3", "node": "24.22.1"}
