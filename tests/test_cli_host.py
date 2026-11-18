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
