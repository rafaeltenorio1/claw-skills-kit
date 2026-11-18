import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
_spec = importlib.util.spec_from_file_location("apply_agents_rules", ROOT / "docker/apply_agents_rules.py")
rules = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rules)

BLOCK = (ROOT / "host/AGENTS.csk.md").read_text(encoding="utf-8")
DEFAULT = "# AGENTS.md - Your Workspace\n\nKeep conventions here.\n\n## Red Lines\n\n- Be careful.\n\n## Tools\n"


def test_inserts_the_block_before_the_first_section_and_keeps_the_rest():
    out = rules.apply_rules(BLOCK, DEFAULT)
    head, tail = out.split(rules.END)
    assert head.startswith("# AGENTS.md - Your Workspace\n\nKeep conventions here.\n\n" + rules.START)
    assert tail == "\n\n## Red Lines\n\n- Be careful.\n\n## Tools\n"


def test_a_second_run_changes_nothing():
    once = rules.apply_rules(BLOCK, DEFAULT)
    assert rules.apply_rules(BLOCK, once) == once
    assert once.count(rules.START) == 1


def test_an_old_block_is_replaced_in_place():
    old = rules.apply_rules(f"{rules.START}\n## Old rules\n{rules.END}\n", DEFAULT)
    out = rules.apply_rules(BLOCK, old)
    assert "Old rules" not in out and out == rules.apply_rules(BLOCK, DEFAULT)


def test_a_file_without_sections_gets_the_block_at_the_end():
    out = rules.apply_rules(BLOCK, "# Title\n")
    assert out.startswith("# Title\n\n" + rules.START)


def test_a_block_without_markers_is_refused():
    with pytest.raises(ValueError):
        rules.apply_rules("## Rules\n", DEFAULT)


def test_main_writes_once_and_reports_changed(tmp_path, capsys):
    block, target = tmp_path / "block.md", tmp_path / "AGENTS.md"
    block.write_text(BLOCK, encoding="utf-8")
    target.write_text(DEFAULT, encoding="utf-8")
    assert rules.main([str(block), str(target)]) == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True, "changed": True}
    assert rules.main([str(block), str(target)]) == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True, "changed": False}


def test_main_reports_a_missing_file(tmp_path, capsys):
    assert rules.main([str(tmp_path / "nope.md"), str(tmp_path / "AGENTS.md")]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False
