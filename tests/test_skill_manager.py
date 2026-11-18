"""The skill-manager SKILL.md must only teach commands the CLI really has."""
import re
from pathlib import Path

import pytest

from claw_skills_kit.cli import main

SKILL = Path(__file__).parents[1] / "skills/skill-manager/SKILL.md"
TEXT = SKILL.read_text()


def test_frontmatter_has_name_and_description_and_no_instance_mark():
    front = TEXT.split("---\n")[1]
    assert "name: skill-manager\n" in front and "\ndescription: " in front
    assert "csk_origin" not in front  # ours, not the client's: `skill remove` must refuse it


@pytest.mark.parametrize("command", sorted(set(re.findall(r"`lk (\w+ \w+)", TEXT))))
def test_every_command_in_the_skill_exists(command, capsys):
    with pytest.raises(SystemExit) as exc:
        main([*command.split(), "--help"])
    assert exc.value.code == 0


@pytest.mark.parametrize("flag", sorted(set(re.findall(r"(--[a-z][a-z-]*)", TEXT))))
def test_every_flag_in_the_skill_exists(flag, capsys):
    helps = []
    for cmd in (["question", "add"], ["question", "change"], ["question", "remove"],
                ["skill", "create"], ["skill", "remove"]):
        with pytest.raises(SystemExit):
            main([*cmd, "--help"])
        helps.append(capsys.readouterr().out)
    assert any(flag in h for h in helps)
