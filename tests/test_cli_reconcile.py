import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from claw_skills_kit.cli import main

FIXTURE = Path(__file__).parent / "fixtures/skills/demo-skill/client-config.template.md"


@pytest.fixture
def env(tmp_path):
    library, target = tmp_path / "library", tmp_path / "host"
    skill = library / "alpha"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# alpha\n")
    shutil.copy(FIXTURE, skill / "client-config.template.md")
    target.mkdir()
    return {"library": library, "target": target, "tmp": tmp_path}


def descriptor(env, **over):
    data = {"host_id": "gw-1", "skills_dir": "/srv/skills", "clients": ["client-a"], "skills": ["alpha"]}
    data.update(over)
    path = env["tmp"] / "host.json"
    path.write_text(json.dumps(data))
    return path


def lock(env, capsys):
    out = env["tmp"] / "skills.lock.json"
    assert main(["lock", str(env["library"]), "--skills", "alpha", "--out", str(out)]) == 0
    capsys.readouterr()
    return out


def rec(env, capsys, host, pins, *extra):
    code = main(["reconcile", "--host", str(host), "--library", str(env["library"]),
                 "--target", str(env["target"]), "--pins", str(pins), *extra])
    return code, json.loads(capsys.readouterr().out)


def tree(path: Path):
    return sorted(p.relative_to(path).as_posix() for p in path.rglob("*") if p.is_file())


# --- lock ------------------------------------------------------------------------------

def test_lock_writes_pins_and_is_idempotent(env, capsys):
    out = env["tmp"] / "skills.lock.json"
    args = ["lock", str(env["library"]), "--skills", "alpha", "--out", str(out)]
    assert main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["changed"] is True and list(first["skills"]) == ["alpha"]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["changed"] is False


def test_lock_of_an_unknown_skill_exits_11(env, capsys):
    code = main(["lock", str(env["library"]), "--skills", "ghost", "--out", str(env["tmp"] / "l.json")])
    assert code == 11
    assert json.loads(capsys.readouterr().out)["status"] == "skill_not_in_library"


# --- reconcile -------------------------------------------------------------------------

def test_default_is_a_dry_run_and_exits_0(env, capsys):
    code, report = rec(env, capsys, descriptor(env), lock(env, capsys))
    assert code == 0 and report["ok"] is True and report["status"] == "planned"
    assert len(report["changes"]) == 3
    assert tree(env["target"]) == []


def test_apply_then_apply_again_changes_nothing(env, capsys):
    host, pins = descriptor(env), lock(env, capsys)
    code, report = rec(env, capsys, host, pins, "--apply")
    assert (code, report["status"]) == (0, "applied")
    assert "alpha/client-config.md" in tree(env["target"])
    code, report = rec(env, capsys, host, pins, "--apply")
    assert (code, report["status"], report["changes"]) == (0, "unchanged", [])


def test_a_stale_pin_exits_9_and_writes_nothing(env, capsys):
    host, pins = descriptor(env), lock(env, capsys)
    (env["library"] / "alpha/SKILL.md").write_text("# changed after pinning\n")
    code, report = rec(env, capsys, host, pins, "--apply")
    assert (code, report["status"]) == (9, "library_revision_mismatch")
    assert tree(env["target"]) == []


def test_two_tenants_exit_8(env, capsys):
    code, report = rec(env, capsys, descriptor(env, clients=["a", "b"]), lock(env, capsys), "--apply")
    assert (code, report["status"]) == (8, "tenant_conflict")
    assert tree(env["target"]) == []


def test_a_failing_smoke_command_exits_6_and_restores_the_host(env, capsys):
    smoke = {"commands": [[sys.executable, "-c", "raise SystemExit(3)"]], "timeout_seconds": 10}
    code, report = rec(env, capsys, descriptor(env, smoke=smoke), lock(env, capsys), "--apply")
    assert (code, report["status"], report["ok"]) == (6, "rolled_back", False)
    assert any(c["detail"] == "exit code 3" for c in report["smoke"]["checks"])
    assert tree(env["target"]) == []


def test_a_passing_smoke_command_lets_the_apply_stand(env, capsys):
    smoke = {"commands": [[sys.executable, "-c", "pass"]]}
    code, report = rec(env, capsys, descriptor(env, smoke=smoke), lock(env, capsys), "--apply")
    assert (code, report["status"]) == (0, "applied")


def test_a_bad_descriptor_exits_10(env, capsys):
    bad = env["tmp"] / "bad.json"
    bad.write_text("{")
    code, report = rec(env, capsys, bad, lock(env, capsys))
    assert (code, report["status"]) == (10, "invalid_descriptor")


def test_a_bad_pins_file_exits_10(env, capsys):
    pins = env["tmp"] / "pins.json"
    pins.write_text('{"skills": {"alpha": "nope"}}')
    code, report = rec(env, capsys, descriptor(env), pins)
    assert (code, report["status"]) == (10, "invalid_pins")


def test_a_target_that_is_not_a_folder_exits_10_and_is_not_created(env, capsys):
    shutil.rmtree(env["target"])
    code, report = rec(env, capsys, descriptor(env), lock(env, capsys), "--apply")
    assert (code, report["status"]) == (10, "invalid_input")
    assert not env["target"].exists()


def test_an_unreadable_existing_client_config_exits_12(env, capsys):
    (env["target"] / "alpha").mkdir()
    (env["target"] / "alpha/client-config.md").write_text("hand written")
    code, report = rec(env, capsys, descriptor(env), lock(env, capsys), "--apply")
    assert (code, report["status"]) == (12, "invalid_existing_config")
    assert (env["target"] / "alpha/client-config.md").read_text() == "hand written"


def test_the_real_command_line_works_end_to_end(env):
    host = descriptor(env)
    pins = env["tmp"] / "skills.lock.json"
    run = lambda *a: subprocess.run([sys.executable, "-m", "claw_skills_kit", *a], capture_output=True, text=True, env={**os.environ})
    r = run("lock", str(env["library"]), "--skills", "alpha", "--out", str(pins))
    assert r.returncode == 0
    r = run("reconcile", "--host", str(host), "--library", str(env["library"]),
            "--target", str(env["target"]), "--pins", str(pins), "--apply")
    assert r.returncode == 0
    assert json.loads(r.stdout)["status"] == "applied"
