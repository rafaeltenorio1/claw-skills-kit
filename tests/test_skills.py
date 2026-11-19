import io
import json
from pathlib import Path

import pytest

from claw_skills_kit.cli import main
from claw_skills_kit.questions import add_question
from claw_skills_kit.reconciler.host import LocalHost
from claw_skills_kit.skills import (
    SkillError,
    apply_plan,
    is_instance_skill,
    plan_create,
    plan_remove,
    render_skill_md,
)
from claw_skills_kit.template_format import new_client_config, parse_template

GOLDEN_SKILL_MD = "---\nname: demo-skill\ndescription: Demo.\nmetadata:\n  layer: 1\n---\n\n# Demo\n"


@pytest.fixture
def skills_dir(tmp_path):
    d = tmp_path / "skills"
    (d / "demo-skill").mkdir(parents=True)
    (d / "demo-skill/SKILL.md").write_text(GOLDEN_SKILL_MD)
    return d


@pytest.fixture
def skills(skills_dir):
    return LocalHost(skills_dir)


def create(skills, name="weekly-report"):
    plan = plan_create(skills, name, "Sends a weekly report.", "# Weekly report\n\nDo the thing.")
    apply_plan(skills, plan)
    return plan


# --- the files a new skill gets --------------------------------------------------------

def test_new_client_config_is_a_valid_empty_document():
    t = parse_template(new_client_config("x"))
    assert (t.standards, t.fields) == ({}, ())


def test_skill_md_has_frontmatter_with_the_instance_mark():
    md = render_skill_md("weekly-report", 'Says "hi"', "# Body")
    assert md.startswith('---\nname: weekly-report\ndescription: "Says \\"hi\\""\n')
    assert "  csk_origin: instance\n" in md and md.endswith("\n# Body\n")
    assert is_instance_skill(md)


def test_a_golden_skill_md_is_not_an_instance_skill():
    assert not is_instance_skill(GOLDEN_SKILL_MD)
    assert not is_instance_skill("# no frontmatter\n  csk_origin: instance\n")
    # the mark only counts inside the frontmatter
    assert not is_instance_skill("---\nname: x\n---\n  csk_origin: instance\n")


# --- create ------------------------------------------------------------------------------

def test_create_dry_run_touches_nothing(skills):
    plan_create(skills, "weekly-report", "d", "body")
    assert skills.files("weekly-report") == []


def test_create_writes_skill_md_and_client_config(skills):
    create(skills)
    assert skills.files("weekly-report") == ["weekly-report/SKILL.md", "weekly-report/client-config.md"]


def test_questions_can_be_added_to_a_new_skill(skills):
    create(skills)
    text = skills.read("weekly-report/client-config.md").decode()
    edit = add_question(text, "report_day", "Monday")
    assert [f.key for f in parse_template(edit.text).fields] == ["report_day"]


@pytest.mark.parametrize("name", ["Weekly", "a/b", "../x", "-x", "", "a_b", "x" * 65])
def test_create_refuses_bad_names(skills, name):
    with pytest.raises(SkillError) as exc:
        plan_create(skills, name, "d", "body")
    assert exc.value.status == "invalid_skill"


@pytest.mark.parametrize("desc, body", [("", "b"), ("two\nlines", "b"), ("d", "  "), ("d", "---\nx")])
def test_create_refuses_bad_description_or_body(skills, desc, body):
    with pytest.raises(SkillError) as exc:
        plan_create(skills, "ok", desc, body)
    assert exc.value.status == "invalid_skill"


def test_create_never_overwrites_an_existing_skill(skills):
    with pytest.raises(SkillError) as exc:
        plan_create(skills, "demo-skill", "d", "body")
    assert exc.value.status == "skill_exists"


# --- remove ------------------------------------------------------------------------------

def test_remove_an_instance_skill_without_answers(skills, skills_dir):
    create(skills)
    apply_plan(skills, plan_remove(skills, "weekly-report"))
    assert not (skills_dir / "weekly-report").exists()


def test_remove_refuses_a_golden_skill(skills):
    with pytest.raises(SkillError) as exc:
        plan_remove(skills, "demo-skill", discard_answers=True)
    assert exc.value.status == "golden_skill"


def test_remove_refuses_a_missing_skill(skills):
    with pytest.raises(SkillError) as exc:
        plan_remove(skills, "nope")
    assert exc.value.status == "skill_not_found"


def test_remove_with_answers_needs_explicit_consent(skills):
    create(skills)
    text = skills.read("weekly-report/client-config.md").decode()
    skills.write("weekly-report/client-config.md", add_question(text, "day", "Mon", "Friday").text.encode())
    with pytest.raises(SkillError) as exc:
        plan_remove(skills, "weekly-report")
    assert exc.value.status == "answer_would_be_lost"
    assert plan_remove(skills, "weekly-report", discard_answers=True).had_answers


class BrokenHost:
    """Fails on the second write: the first one must be undone."""

    def __init__(self, inner):
        self.inner, self.writes = inner, 0

    def read(self, path):
        return self.inner.read(path)

    def files(self, prefix=""):
        return self.inner.files(prefix)

    def delete(self, path):
        self.inner.delete(path)

    def write(self, path, data):
        self.writes += 1
        if self.writes == 2:
            raise OSError("disk full")
        self.inner.write(path, data)


def test_a_failed_create_leaves_nothing_behind(skills, skills_dir):
    host = BrokenHost(skills)
    plan = plan_create(host, "weekly-report", "d", "body")
    with pytest.raises(SkillError) as exc:
        apply_plan(host, plan)
    assert exc.value.status == "rolled_back"
    assert not (skills_dir / "weekly-report").exists()


# --- CLI -----------------------------------------------------------------------------------

def run(capsys, *argv):
    code = main(["skill", *argv])
    return code, json.loads(capsys.readouterr().out)


def test_cli_create_dry_run_then_apply(capsys, skills_dir):
    args = ["create", str(skills_dir), "--name", "weekly-report", "--description", "d", "--instructions", "# B"]
    code, out = run(capsys, *args)
    assert (code, out["status"]) == (0, "planned") and not (skills_dir / "weekly-report").exists()
    code, out = run(capsys, *args, "--apply")
    assert (code, out["status"]) == (0, "applied")
    assert out["files"] == ["weekly-report/SKILL.md", "weekly-report/client-config.md"]


def test_cli_create_from_an_instructions_file(capsys, skills_dir, tmp_path):
    f = tmp_path / "body.md"
    f.write_text("# From file\n")
    code, _ = run(capsys, "create", str(skills_dir), "--name", "x", "--description", "d",
                  "--instructions-file", str(f), "--apply")
    assert code == 0 and "# From file" in (skills_dir / "x/SKILL.md").read_text()


def test_cli_create_reads_instructions_from_stdin_with_a_dash(capsys, monkeypatch, skills_dir):
    body = "# Weekly\n\nRead this client's client-config.md \"first\" — then $HOME stays literal.\n"
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(body.encode("utf-8")), encoding="utf-8"))
    code, out = run(capsys, "create", str(skills_dir), "--name", "x", "--description", "d",
                    "--instructions-file", "-", "--apply")
    assert (code, out["status"]) == (0, "applied")
    assert body in (skills_dir / "x/SKILL.md").read_text(encoding="utf-8")


def test_cli_create_writes_the_questions_with_the_skill_in_one_apply(capsys, skills_dir):
    base = ["create", str(skills_dir), "--name", "weekly", "--description", "d", "--instructions", "# B",
            "--question", "schedule.time", "Monday 8:00", "Monday 9:00",
            "--question", "critical_senders", "Clients and the accountant"]
    code, out = run(capsys, *base)
    assert (code, out["status"], out["questions"]) == (0, "planned", ["schedule.time", "critical_senders"])
    assert not (skills_dir / "weekly").exists()
    code, out = run(capsys, *base, "--apply")
    assert (code, out["status"]) == (0, "applied")
    assert "Monday 9:00" not in json.dumps(out)  # report has keys, never answer values
    t = parse_template((skills_dir / "weekly/client-config.md").read_text(encoding="utf-8"))
    assert [(f.key, f.comes_from, f.suggested, f.answer) for f in t.fields] == [
        ("schedule.time", "Instance", "Monday 8:00", "Monday 9:00"),
        ("critical_senders", "Instance", "Clients and the accountant", ""),
    ]


@pytest.mark.parametrize(
    "questions, status",
    [
        ([["k", "s"], ["k", "s2"]], "question_exists"),  # same key twice
        ([["k", "a|b"]], "invalid_question"),  # would break the table
        ([["k"]], "invalid_question"),  # missing the suggestion
        ([["k", "s", "a", "extra"]], "invalid_question"),
    ],
)
def test_cli_create_refuses_bad_questions_and_writes_nothing(capsys, skills_dir, questions, status):
    argv = ["create", str(skills_dir), "--name", "weekly", "--description", "d", "--instructions", "# B", "--apply"]
    for q in questions:
        argv += ["--question", *q]
    code, out = run(capsys, *argv)
    assert (code, out["status"]) == (13, status)
    assert not (skills_dir / "weekly").exists()


def test_cli_create_refuses_stdin_that_is_not_utf8(capsys, monkeypatch, skills_dir):
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(b"\xff\xfe bad"), encoding="latin-1"))
    code, out = run(capsys, "create", str(skills_dir), "--name", "x", "--description", "d",
                    "--instructions-file", "-")
    assert (code, out["status"]) == (10, "invalid_input") and not (skills_dir / "x").exists()


@pytest.mark.parametrize(
    "argv, code, status",
    [
        (["create", "{d}", "--name", "demo-skill", "--description", "d", "--instructions", "b"], 11, "skill_exists"),
        (["create", "{d}", "--name", "Bad", "--description", "d", "--instructions", "b"], 11, "invalid_skill"),
        (["remove", "{d}", "--name", "demo-skill", "--apply"], 11, "golden_skill"),
        (["remove", "{d}", "--name", "nope"], 11, "skill_not_found"),
    ],
)
def test_cli_refusals(capsys, skills_dir, argv, code, status):
    got, out = run(capsys, *[a.format(d=skills_dir) for a in argv])
    assert (got, out["ok"], out["status"]) == (code, False, status)


def test_cli_missing_skills_folder(capsys, tmp_path):
    code, out = run(capsys, "remove", str(tmp_path / "nope"), "--name", "x")
    assert (code, out["status"]) == (10, "invalid_input")
