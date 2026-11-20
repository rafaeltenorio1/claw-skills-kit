import json
import shutil
from pathlib import Path

import pytest

from claw_skills_kit.reconcile import ReconcileError, compute_revisions, reconcile
from claw_skills_kit.reconciler.descriptor import HostDescriptor
from claw_skills_kit.reconciler.host import LocalHost
from claw_skills_kit.reconciler.smoke import CheckOutcome

FIXTURE = Path(__file__).parent / "fixtures/skills/demo-skill/client-config.template.md"
Q1, Q2 = "extra urgent_rules", "sender_rules / suppression_rules"


# --- helpers -------------------------------------------------------------------------

def add_skill(root: Path, name: str, skill_md: str = "# skill\n", script: str = "print(1)\n") -> None:
    d = root / name
    (d / "scripts").mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(skill_md)
    (d / "scripts/run.py").write_text(script)
    shutil.copy(FIXTURE, d / "client-config.template.md")


@pytest.fixture
def library_dir(tmp_path):
    root = tmp_path / "library"
    add_skill(root, "alpha")
    add_skill(root, "beta")
    return root


@pytest.fixture
def library(library_dir):
    return LocalHost(library_dir)


@pytest.fixture
def target_dir(tmp_path):
    return tmp_path / "host"


@pytest.fixture
def target(target_dir):
    return LocalHost(target_dir)


def desc(skills=("alpha",), clients=("client-a",)):
    return HostDescriptor("gw-1", "/srv/skills", tuple(clients), tuple(skills))


def pins(library, skills=("alpha", "beta")):
    return compute_revisions(library, skills)


def snapshot(host):
    return {p: host.read(p) for p in host.files()}


class FailingCheck:
    name = "always-fails"

    def run(self):
        return CheckOutcome(self.name, False, "boom")


class FlakyHost:
    """Wraps a host; writes/deletes raise once `fail_after` operations were done."""

    def __init__(self, inner, fail_after, fail_forever=False):
        self.inner, self.left, self.forever, self.dead = inner, fail_after, fail_forever, False

    def _tick(self):
        if self.dead:
            raise OSError("disk gone")
        if self.left == 0:
            self.left = -1  # fail this once; stay broken only if fail_forever
            self.dead = self.forever
            raise OSError("disk gone")
        if self.left > 0:
            self.left -= 1

    def read(self, path):
        return self.inner.read(path)

    def files(self, prefix=""):
        return self.inner.files(prefix)

    def write(self, path, data):
        self._tick()
        self.inner.write(path, data)

    def delete(self, path):
        self._tick()
        self.inner.delete(path)


# --- planning and applying -------------------------------------------------------------

def test_first_install_creates_layer1_template_and_blank_client_config(library, target):
    r = reconcile(desc(), library, target, pins(library), apply=True)
    assert r.status == "applied"
    assert target.files() == [
        "alpha/SKILL.md",
        "alpha/client-config.md",
        "alpha/client-config.template.md",
        "alpha/scripts/run.py",
    ]
    assert {c.action for c in r.changes} == {"create"}
    assert r.pending_answers == {"alpha": ("extra urgent_rules", "sender_rules / suppression_rules", "critical_senders")}


def test_default_is_a_dry_run_that_touches_nothing(library, target):
    r = reconcile(desc(), library, target, pins(library))
    assert r.status == "planned"
    assert len(r.changes) == 4
    assert target.files() == []


def test_second_run_changes_nothing(library, target):
    p = pins(library)
    reconcile(desc(), library, target, p, apply=True)
    before = snapshot(target)
    r = reconcile(desc(), library, target, p, apply=True)
    assert r.status == "unchanged" and r.changes == ()
    assert snapshot(target) == before


def test_existing_answers_are_kept_when_layer1_changes(library_dir, library, target):
    reconcile(desc(), library, target, pins(library), apply=True)
    cfg = target.read("alpha/client-config.md").decode()
    cfg = cfg.replace("| Anything with a deadline or a payment problem | |", "| Anything with a deadline or a payment problem | Overdue invoices |")
    target.write("alpha/client-config.md", cfg.encode())

    (library_dir / "alpha/SKILL.md").write_text("# skill v2\n")
    r = reconcile(desc(), library, target, pins(library), apply=True)

    assert r.status == "applied"
    assert [c.path for c in r.changes] == ["alpha/SKILL.md"]
    assert "Overdue invoices" in target.read("alpha/client-config.md").decode()
    assert r.pending_answers["alpha"] == ("sender_rules / suppression_rules", "critical_senders")


def test_update_touches_only_the_skill_that_changed(library_dir, library, target):
    d = desc(skills=("alpha", "beta"))
    reconcile(d, library, target, pins(library), apply=True)
    (library_dir / "beta/scripts/run.py").write_text("print(2)\n")
    r = reconcile(d, library, target, pins(library), apply=True)
    assert [c.path for c in r.changes] == ["beta/scripts/run.py"]
    assert r.changes[0].action == "update"


def test_a_removed_question_is_reported_by_key_only_and_not_rendered(library, target):
    reconcile(desc(), library, target, pins(library), apply=True)
    cfg = target.read("alpha/client-config.md").decode()
    if not cfg.endswith("\n"):  # the fixture may or may not end with a newline
        cfg += "\n"
    cfg += "| old_question | Q9 | s | SECRET-ANSWER |\n"
    target.write("alpha/client-config.md", cfg.encode())

    r = reconcile(desc(), library, target, pins(library), apply=True)

    assert r.removed_answers == {"alpha": ("old_question",)}
    assert "SECRET-ANSWER" not in json.dumps(r.to_dict())
    assert "old_question" not in target.read("alpha/client-config.md").decode()


def test_report_never_contains_answer_values(library, target):
    reconcile(desc(), library, target, pins(library), apply=True)
    cfg = target.read("alpha/client-config.md").decode().replace(
        "| Anything with a deadline or a payment problem | |",
        "| Anything with a deadline or a payment problem | TOP-SECRET-VALUE |",
    )
    target.write("alpha/client-config.md", cfg.encode())
    r = reconcile(desc(), library, target, pins(library))
    assert "TOP-SECRET-VALUE" not in json.dumps(r.to_dict())


def test_unmanaged_skills_on_the_host_are_left_alone(library, target):
    target.write("legacy/SKILL.md", b"hand made")
    reconcile(desc(), library, target, pins(library), apply=True)
    assert target.read("legacy/SKILL.md") == b"hand made"


def test_stale_layer1_files_are_deleted_but_client_config_is_kept(library, target):
    reconcile(desc(), library, target, pins(library), apply=True)
    target.write("alpha/scripts/old.py", b"stale")
    r = reconcile(desc(), library, target, pins(library), apply=True)
    assert [(c.path, c.action) for c in r.changes] == [("alpha/scripts/old.py", "delete")]
    assert target.read("alpha/client-config.md") is not None


def test_a_filled_client_config_in_the_library_is_ignored(library_dir, library, target):
    (library_dir / "alpha/client-config.md").write_text("LEAKED CLIENT DATA")
    p = pins(library)
    reconcile(desc(), library, target, p, apply=True)
    assert "LEAKED" not in target.read("alpha/client-config.md").decode()


# --- refusals: nothing is written ------------------------------------------------------

def refusal(library, target, d=None, p=None):
    before = snapshot(target)
    with pytest.raises(ReconcileError) as info:
        reconcile(d or desc(), library, target, p if p is not None else pins(library), apply=True)
    assert snapshot(target) == before
    return info.value


def test_two_tenants_are_refused(library, target):
    assert refusal(library, target, desc(clients=("a", "b"))).status == "tenant_conflict"


def test_a_pin_that_does_not_match_the_library_is_refused(library, target):
    assert refusal(library, target, p={"alpha": "0" * 64}).status == "library_revision_mismatch"


def test_a_skill_without_a_pin_is_refused(library, target):
    assert refusal(library, target, p={}).status == "unpinned_skill"


def test_a_skill_missing_from_the_library_is_refused(library, target):
    assert refusal(library, target, desc(skills=("ghost",)), {"ghost": "x"}).status == "skill_not_in_library"


def test_a_skill_without_skill_md_is_refused(library_dir, library, target):
    (library_dir / "alpha/SKILL.md").unlink()
    assert refusal(library, target, p={"alpha": "x"}).status == "invalid_skill"


def test_a_skill_name_that_escapes_is_refused(library, target):
    assert refusal(library, target, desc(skills=("../x",)), {"../x": "x"}).status == "invalid_skill"


def test_a_broken_template_in_the_library_is_refused(library_dir, library, target):
    (library_dir / "alpha/client-config.template.md").write_text("not a template")
    assert refusal(library, target, p=pins(library)).status == "invalid_template"


def test_an_unreadable_existing_client_config_is_refused_and_left_intact(library, target):
    target.write("alpha/client-config.md", b"hand written notes")
    err = refusal(library, target)
    assert err.status == "invalid_existing_config"
    assert target.read("alpha/client-config.md") == b"hand written notes"


# --- smoke failure and rollback ----------------------------------------------------------

def test_failed_smoke_on_first_install_leaves_the_host_empty(library, target):
    r = reconcile(desc(), library, target, pins(library), apply=True, extra_checks=lambda: [FailingCheck()])
    assert r.status == "rolled_back"
    assert [o.name for o in r.smoke.failures] == ["always-fails"]
    assert target.files() == []


def test_failed_smoke_on_an_update_restores_every_byte(library_dir, library, target):
    reconcile(desc(), library, target, pins(library), apply=True)
    target.write("alpha/scripts/extra.py", b"stale")
    before = snapshot(target)

    (library_dir / "alpha/SKILL.md").write_text("# v2\n")
    r = reconcile(desc(), library, target, pins(library), apply=True, extra_checks=lambda: [FailingCheck()])

    assert r.status == "rolled_back"
    assert snapshot(target) == before


def test_a_crash_midway_through_writing_is_rolled_back(library, target_dir):
    flaky = FlakyHost(LocalHost(target_dir), fail_after=2)
    r = reconcile(desc(), library, flaky, pins(library), apply=True)
    assert r.status == "rolled_back"
    assert r.error == "apply failed: OSError"
    assert flaky.files() == []


def test_if_the_restore_itself_fails_that_is_reported_loudly(library, target_dir):
    flaky = FlakyHost(LocalHost(target_dir), fail_after=2, fail_forever=True)
    r = reconcile(desc(), library, flaky, pins(library), apply=True)
    assert r.status == "rollback_failed"
    assert r.unrestored


def test_report_is_json_serialisable(library, target):
    r = reconcile(desc(), library, target, pins(library), apply=True)
    assert json.loads(json.dumps(r.to_dict()))["status"] == "applied"


# --- instance-only questions -------------------------------------------------------

def add_instance_row(target, row):
    """Add a row the way `append_fields` does: keep the file's final newline (or its absence)."""
    cfg = target.read("alpha/client-config.md").decode()
    end = "\n" if cfg.endswith("\n") else ""
    target.write("alpha/client-config.md", (cfg.rstrip("\n") + "\n" + row + end).encode())


def test_an_instance_question_survives_a_reconcile_with_its_answer(library_dir, library, target):
    reconcile(desc(), library, target, pins(library), apply=True)
    add_instance_row(target, "| interval_days | Instance | Every 7 days | 7 |")
    (library_dir / "alpha/SKILL.md").write_text("# skill v2\n")  # library skill changes

    r = reconcile(desc(), library, target, pins(library), apply=True)

    assert r.status == "applied"
    assert "| interval_days | Instance | Every 7 days | 7 |" in target.read("alpha/client-config.md").decode()
    assert r.removed_answers == {}


def test_a_blank_instance_question_is_kept_and_reported_as_pending(library, target):
    reconcile(desc(), library, target, pins(library), apply=True)
    add_instance_row(target, "| interval_days | Instance | Every 7 days | |")

    r = reconcile(desc(), library, target, pins(library))

    assert r.status == "unchanged"
    assert "interval_days" in r.pending_answers["alpha"]


def test_instance_questions_do_not_change_the_library_revision(library, target):
    p = pins(library)
    reconcile(desc(), library, target, p, apply=True)
    add_instance_row(target, "| interval_days | Instance | Every 7 days | 7 |")
    assert compute_revisions(library, ["alpha"]) == {"alpha": p["alpha"]}


def test_when_the_library_template_adopts_an_instance_key_the_answer_moves_to_its_row(library_dir, library, target):
    reconcile(desc(), library, target, pins(library), apply=True)
    add_instance_row(target, "| interval_days | Instance | Every 7 days | 7 |")
    tpl = library_dir / "alpha/client-config.template.md"
    tpl.write_text(tpl.read_text().rstrip("\n") + "\n| interval_days | Q4 | Every 3 days | |\n")

    reconcile(desc(), library, target, pins(library), apply=True)

    cfg = target.read("alpha/client-config.md").decode()
    assert "| interval_days | Q4 | Every 3 days | 7 |" in cfg
    assert "Instance" not in cfg
