import subprocess

from claw_skills_kit.reconciler.host import LocalHost
from claw_skills_kit.reconciler.smoke import CheckOutcome, CommandCheck, IntegrityCheck, run_checks

GOOD_CONFIG = b"""## Standards

| Setting | Standard |
|---|---|
| schedule | Every hour |

## Client answers

| Setting | Comes from | Suggested answer | Value |
|---|---|---|---|
| urgent | Q1 | deadlines | deadlines |
"""


class Fake:
    def __init__(self, name, outcome=None, boom=False):
        self.name, self._outcome, self._boom = name, outcome, boom

    def run(self):
        if self._boom:
            raise RuntimeError("secret-token-123")
        return self._outcome


def test_all_passing_checks_make_the_smoke_pass():
    r = run_checks([Fake("a", CheckOutcome("a", True)), Fake("b", CheckOutcome("b", True))])
    assert r.ok and r.failures == ()


def test_one_failing_check_fails_the_smoke_and_is_listed():
    r = run_checks([Fake("a", CheckOutcome("a", True)), Fake("b", CheckOutcome("b", False, "x"))])
    assert not r.ok and [f.name for f in r.failures] == ["b"]


def test_a_crashing_check_is_a_failure_and_does_not_leak_the_message():
    r = run_checks([Fake("a", boom=True)])
    assert not r.ok
    assert "secret-token-123" not in r.failures[0].detail
    assert "RuntimeError" in r.failures[0].detail


def test_no_checks_passes():
    assert run_checks([]).ok


def make_host(tmp_path, files):
    host = LocalHost(tmp_path)
    for path, data in files.items():
        host.write(path, data)
    return host


def test_integrity_passes_when_host_matches(tmp_path):
    files = {"s/SKILL.md": b"x", "s/client-config.md": GOOD_CONFIG}
    host = make_host(tmp_path, files)
    assert IntegrityCheck(host, files, ["s"]).run().ok


def test_integrity_detects_a_file_that_differs(tmp_path):
    host = make_host(tmp_path, {"s/SKILL.md": b"x"})
    out = IntegrityCheck(host, {"s/SKILL.md": b"y"}, ["s"]).run()
    assert not out.ok and "s/SKILL.md differs" in out.detail


def test_integrity_detects_a_missing_skill_file(tmp_path):
    host = make_host(tmp_path, {})
    out = IntegrityCheck(host, {}, ["s"]).run()
    assert not out.ok and "s/SKILL.md is missing" in out.detail


def test_integrity_detects_a_broken_client_config(tmp_path):
    files = {"s/SKILL.md": b"x", "s/client-config.md": b"not a config"}
    out = IntegrityCheck(make_host(tmp_path, files), files, ["s"]).run()
    assert not out.ok and "not a valid client config" in out.detail


def test_integrity_accepts_a_skill_without_client_config(tmp_path):
    files = {"s/SKILL.md": b"x"}
    assert IntegrityCheck(make_host(tmp_path, files), files, ["s"]).run().ok


def fake_runner(code=0, raises=None):
    def run(argv, **kwargs):
        if raises:
            raise raises
        return subprocess.CompletedProcess(argv, code, stdout=b"TOKEN=abc", stderr=b"")
    return run


def test_command_check_passes_on_exit_zero():
    assert CommandCheck(["openclaw", "skills", "list"], runner=fake_runner(0)).run().ok


def test_command_check_fails_on_non_zero_and_reports_only_the_code():
    out = CommandCheck(["openclaw", "doctor"], runner=fake_runner(2)).run()
    assert not out.ok and out.detail == "exit code 2"
    assert "TOKEN" not in out.detail


def test_command_check_reports_a_missing_command():
    out = CommandCheck(["nope"], runner=fake_runner(raises=FileNotFoundError())).run()
    assert not out.ok and out.detail == "command not found"


def test_command_check_reports_a_timeout():
    err = subprocess.TimeoutExpired("x", 3)
    out = CommandCheck(["x"], timeout=3, runner=fake_runner(raises=err)).run()
    assert not out.ok and "timed out" in out.detail


def test_command_check_really_runs_a_process():
    import sys
    assert CommandCheck([sys.executable, "-c", "pass"]).run().ok
    assert not CommandCheck([sys.executable, "-c", "raise SystemExit(3)"]).run().ok
