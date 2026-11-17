import json

import pytest

from claw_skills_kit.reconciler.descriptor import (
    DescriptorError,
    TenantConflictError,
    check_single_tenant,
    load_descriptor,
)


def doc(**over):
    base = {"host_id": "gw-1", "skills_dir": "/srv/skills", "clients": ["client-a"], "skills": ["inbox-triage"]}
    base.update(over)
    return json.dumps(base)


def test_loads_a_minimal_descriptor_with_defaults():
    d = load_descriptor(doc())
    assert (d.host_id, d.clients, d.skills) == ("gw-1", ("client-a",), ("inbox-triage",))
    assert d.smoke.commands == () and d.smoke.timeout_seconds == 30.0


def test_loads_smoke_commands_and_timeout():
    d = load_descriptor(doc(smoke={"commands": [["openclaw", "skills", "list"]], "timeout_seconds": 5}))
    assert d.smoke.commands == (("openclaw", "skills", "list"),)
    assert d.smoke.timeout_seconds == 5.0


def test_invalid_json_names_the_line():
    with pytest.raises(DescriptorError, match="line 1"):
        load_descriptor("{")


def test_top_level_must_be_an_object():
    with pytest.raises(DescriptorError):
        load_descriptor("[]")


@pytest.mark.parametrize("key", ["host_id", "skills_dir"])
def test_required_strings_are_checked_and_named(key):
    with pytest.raises(DescriptorError, match=key):
        load_descriptor(doc(**{key: ""}))


@pytest.mark.parametrize("key", ["clients", "skills"])
def test_lists_must_be_lists_of_strings(key):
    with pytest.raises(DescriptorError, match=key):
        load_descriptor(doc(**{key: "nope"}))
    with pytest.raises(DescriptorError, match=key):
        load_descriptor(doc(**{key: [1]}))


def test_duplicate_skills_are_rejected():
    with pytest.raises(DescriptorError, match="duplicate"):
        load_descriptor(doc(skills=["a", "a"]))


@pytest.mark.parametrize("bad", [0, -1, "5", True])
def test_timeout_must_be_a_positive_number(bad):
    with pytest.raises(DescriptorError, match="timeout"):
        load_descriptor(doc(smoke={"timeout_seconds": bad}))


def test_smoke_commands_must_be_non_empty_argv_lists():
    with pytest.raises(DescriptorError, match="commands"):
        load_descriptor(doc(smoke={"commands": [[]]}))


def test_one_client_passes_the_tenant_check():
    check_single_tenant(load_descriptor(doc()))


def test_two_clients_are_refused_and_both_are_named():
    with pytest.raises(TenantConflictError, match="client-a, client-b"):
        check_single_tenant(load_descriptor(doc(clients=["client-a", "client-b"])))


def test_no_client_is_refused():
    with pytest.raises(DescriptorError, match="no client"):
        check_single_tenant(load_descriptor(doc(clients=[])))


def test_tenant_conflict_is_a_descriptor_error():
    assert issubclass(TenantConflictError, DescriptorError)
