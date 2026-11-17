from claw_skills_kit.models.hashing import revision_of, sha256_hex


def test_sha256_hex_matches_a_known_value():
    assert sha256_hex(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_revision_ignores_the_order_files_were_given_in():
    a = {"a/SKILL.md": b"1", "b/SKILL.md": b"2"}
    b = {"b/SKILL.md": b"2", "a/SKILL.md": b"1"}
    assert revision_of(a) == revision_of(b)


def test_revision_changes_when_a_file_changes():
    assert revision_of({"a": b"1"}) != revision_of({"a": b"2"})


def test_revision_changes_when_a_file_is_renamed():
    assert revision_of({"a": b"1"}) != revision_of({"b": b"1"})


def test_revision_cannot_confuse_path_and_content_boundaries():
    assert revision_of({"a": b"bc"}) != revision_of({"ab": b"c"})


def test_revision_of_nothing_is_stable():
    assert revision_of({}) == revision_of({})
