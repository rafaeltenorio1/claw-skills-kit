import pytest

from claw_skills_kit.reconciler.lockfile import LockfileError, dump_pins, load_pins

H1, H2 = "a" * 64, "b" * 64


def test_dump_then_load_round_trips():
    assert load_pins(dump_pins({"x": H1, "y": H2})) == {"x": H1, "y": H2}


def test_dump_is_deterministic_regardless_of_insertion_order():
    assert dump_pins({"y": H2, "x": H1}) == dump_pins({"x": H1, "y": H2})
    assert dump_pins({"x": H1}).endswith("\n")


def test_invalid_json_names_the_line():
    with pytest.raises(LockfileError, match="line 1"):
        load_pins("{")


@pytest.mark.parametrize("bad", ["[]", "{}", '{"skills": []}', '{"skills": 3}'])
def test_shape_is_checked(bad):
    with pytest.raises(LockfileError, match="skills"):
        load_pins(bad)


@pytest.mark.parametrize("bad", ['"abc"', '"%s"' % ("A" * 64), "5", "null"])
def test_a_pin_must_be_lowercase_sha256_hex(bad):
    with pytest.raises(LockfileError, match="'x'"):
        load_pins('{"skills": {"x": %s}}' % bad)
import pytest

from claw_skills_kit.reconciler.lockfile import LockfileError, dump_pins, load_pins

H1, H2 = "a" * 64, "b" * 64


def test_dump_then_load_round_trips():
    assert load_pins(dump_pins({"x": H1, "y": H2})) == {"x": H1, "y": H2}


def test_dump_is_deterministic_regardless_of_insertion_order():
    assert dump_pins({"y": H2, "x": H1}) == dump_pins({"x": H1, "y": H2})
    assert dump_pins({"x": H1}).endswith("\n")


def test_invalid_json_names_the_line():
    with pytest.raises(LockfileError, match="line 1"):
        load_pins("{")


@pytest.mark.parametrize("bad", ["[]", "{}", '{"skills": []}', '{"skills": 3}'])
def test_shape_is_checked(bad):
    with pytest.raises(LockfileError, match="skills"):
        load_pins(bad)


@pytest.mark.parametrize("bad", ['"abc"', '"%s"' % ("A" * 64), "5", "null"])
def test_a_pin_must_be_lowercase_sha256_hex(bad):
    with pytest.raises(LockfileError, match="'x'"):
        load_pins('{"skills": {"x": %s}}' % bad)
