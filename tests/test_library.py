"""The sample skill library shipped in the Docker image (library/releases/<release>/).

Checks that each release follows the spec's template and that the update from the first release to the second
tells the story the agent explains in chat: answers kept, one new question, nothing discarded.
"""
import re
import shutil
from pathlib import Path

import pytest

from claw_skills_kit.interview import apply_answers
from claw_skills_kit.reconcile import compute_revisions, reconcile
from claw_skills_kit.reconciler.descriptor import HostDescriptor
from claw_skills_kit.reconciler.host import LocalHost
from claw_skills_kit.reconciler.lockfile import load_pins
from claw_skills_kit.template_format import fill_answers, parse_template

RELEASES = Path(__file__).parent.parent / "library/releases"
ALL = sorted(p.name for p in RELEASES.iterdir() if p.is_dir())
OLD, NEW = "2026.11.10", "2026.11.18"


def skills_of(release):
    return sorted(p.name for p in (RELEASES / release / "skills").iterdir() if p.is_dir())


def frontmatter(text):
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert match, "SKILL.md has no frontmatter"
    return match.group(1)


def interview_rows(text):
    rows = [line for line in text.splitlines() if re.match(r"\| Q\d+ \|", line)]
    return [[cell.strip() for cell in row.strip("|").split("|")] for row in rows]


def test_both_demo_releases_exist():
    assert OLD in ALL and NEW in ALL


@pytest.mark.parametrize("release", ALL)
def test_pins_match_the_skills_in_the_release(release):
    pins = load_pins((RELEASES / release / "skills.lock.json").read_text(encoding="utf-8"))
    assert sorted(pins) == skills_of(release)
    assert compute_revisions(LocalHost(RELEASES / release / "skills"), sorted(pins)) == dict(pins)


@pytest.mark.parametrize("release", ALL)
def test_each_skill_follows_the_template(release):
    for name in skills_of(release):
        folder = RELEASES / release / "skills" / name
        assert {"SKILL.md", "client-config.template.md", "interview.md", "lineage.md"} <= {
            p.name for p in folder.iterdir()
        }
        front = frontmatter((folder / "SKILL.md").read_text(encoding="utf-8"))
        assert re.search(rf"^name: {name}$", front, re.M)
        description = re.search(r"^description: (.+)$", front, re.M).group(1)
        assert len(description) < 160
        assert re.search(r"^  layer: 1$", front, re.M)
        version = re.search(r"^  version: (\S+)$", front, re.M).group(1)
        assert f"  - {version}:" in (folder / "lineage.md").read_text(encoding="utf-8")

        template = parse_template((folder / "client-config.template.md").read_text(encoding="utf-8"))
        questions = interview_rows((folder / "interview.md").read_text(encoding="utf-8"))
        assert 1 <= len(questions) <= 3, "the spec allows at most three interview questions"
        assert {(q[0], q[3]) for q in questions} == {(f.comes_from, f.key) for f in template.fields}


def descriptor(target):
    return HostDescriptor("demo-host", str(target), ("demo-client",), ("inbox-triage", "meeting-notes"))


def pins(release):
    return load_pins((RELEASES / release / "skills.lock.json").read_text(encoding="utf-8"))


def test_update_keeps_answers_and_asks_only_the_new_question(tmp_path):
    target = tmp_path / "skills"
    target.mkdir()
    host = LocalHost(target)
    old = LocalHost(RELEASES / OLD / "skills")
    new = LocalHost(RELEASES / NEW / "skills")

    assert reconcile(descriptor(target), old, host, pins(OLD), apply=True).status == "applied"
    for skill in ("inbox-triage", "meeting-notes"):  # the client answered the interview
        path = target / skill / "client-config.md"
        text = path.read_text(encoding="utf-8")
        template = parse_template(text)
        answers = {f.key: f"answer for {f.key}" for f in template.fields}
        path.write_text(fill_answers(text, apply_answers(template, answers)), encoding="utf-8")

    plan = reconcile(descriptor(target), new, host, pins(NEW))
    assert plan.status == "planned"
    assert dict(plan.pending_answers) == {"meeting-notes": ("summary_language",)}
    assert dict(plan.removed_answers) == {}
    assert {c.path for c in plan.changes} >= {"inbox-triage/SKILL.md", "meeting-notes/client-config.md"}

    assert reconcile(descriptor(target), new, host, pins(NEW), apply=True).status == "applied"
    inbox = parse_template((target / "inbox-triage/client-config.md").read_text(encoding="utf-8"))
    assert all(f.answer == f"answer for {f.key}" for f in inbox.fields)
    assert "grouping" in inbox.standards
    assert reconcile(descriptor(target), new, host, pins(NEW)).status == "unchanged"


def test_the_library_is_not_modified_by_the_test(tmp_path):
    # guard against a test or tool writing into the shipped library
    copy = tmp_path / "copy"
    shutil.copytree(RELEASES, copy)
    for release in ALL:
        assert compute_revisions(LocalHost(copy / release / "skills"), skills_of(release)) == dict(pins(release))
