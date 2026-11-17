import pytest

from claw_skills_kit.reconciler.host import HostError, LocalHost


@pytest.fixture
def host(tmp_path):
    return LocalHost(tmp_path / "skills")


def test_read_returns_none_for_a_missing_file(host):
    assert host.read("a/SKILL.md") is None


def test_write_then_read_round_trips_and_creates_parents(host):
    host.write("a/scripts/run.py", b"x")
    assert host.read("a/scripts/run.py") == b"x"


def test_write_replaces_and_leaves_no_temp_file(host, tmp_path):
    host.write("a/f", b"1")
    host.write("a/f", b"2")
    assert host.read("a/f") == b"2"
    assert not list((tmp_path / "skills").rglob("*.csk-tmp"))


def test_files_lists_sorted_relative_posix_paths(host):
    host.write("b/SKILL.md", b"")
    host.write("a/x/y.md", b"")
    assert host.files() == ["a/x/y.md", "b/SKILL.md"]


def test_files_with_prefix_only_lists_that_subtree(host):
    host.write("a/1", b"")
    host.write("b/2", b"")
    assert host.files("a") == ["a/1"]


def test_files_of_a_missing_prefix_is_empty(host):
    assert host.files("nope") == []


def test_delete_removes_the_file_and_prunes_empty_directories(host, tmp_path):
    host.write("a/x/y.md", b"")
    host.delete("a/x/y.md")
    assert not (tmp_path / "skills" / "a").exists()
    assert (tmp_path / "skills").exists()


def test_delete_keeps_directories_that_still_have_files(host):
    host.write("a/1", b"")
    host.write("a/2", b"")
    host.delete("a/1")
    assert host.files() == ["a/2"]


def test_delete_of_a_missing_file_is_a_no_op(host):
    host.delete("a/none")


@pytest.mark.parametrize("bad", ["../x", "a/../../x", "/etc/passwd", ""])
def test_paths_that_escape_the_root_are_refused(host, bad):
    with pytest.raises(HostError):
        host.write(bad, b"x")
    with pytest.raises(HostError):
        host.read(bad)
