import argparse
import json
import sys
import traceback
from pathlib import Path

from claw_skills_kit.skills import SkillError, apply_plan, plan_create, plan_remove
from claw_skills_kit.questions import QuestionError, add_question, change_question, remove_question
from claw_skills_kit.interview import InterviewError, apply_answers, load_answers, missing_required
from claw_skills_kit.reconcile import ReconcileError, compute_revisions, reconcile
from claw_skills_kit.reconciler.descriptor import DescriptorError, load_descriptor
from claw_skills_kit.reconciler.host import LocalHost
from claw_skills_kit.reconciler.layout import ANSWERS_FILE
from claw_skills_kit.reconciler.lockfile import LockfileError, dump_pins, load_pins
from claw_skills_kit.reconciler.smoke import CommandCheck
from claw_skills_kit.template_format import FillError, TemplateFormatError, fill_answers, parse_template

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_INVALID_TEMPLATE = 3
EXIT_INVALID_ANSWERS = 4
EXIT_MISSING_ANSWERS = 5
EXIT_ROLLED_BACK = 6
EXIT_ROLLBACK_FAILED = 7
EXIT_TENANT_CONFLICT = 8
EXIT_PIN = 9
EXIT_INVALID_INPUT = 10
EXIT_SKILL = 11
EXIT_EXISTING_CONFIG = 12
EXIT_QUESTION = 13
EXIT_ANSWER_WOULD_BE_LOST = 14

# QuestionError.status -> exit code.
_QUESTION_CODES = {
    "question_exists": EXIT_QUESTION,
    "question_not_found": EXIT_QUESTION,
    "golden_question": EXIT_QUESTION,
    "invalid_question": EXIT_QUESTION,
    "answer_would_be_lost": EXIT_ANSWER_WOULD_BE_LOST,
    "invalid_existing_config": EXIT_EXISTING_CONFIG,
}

# SkillError.status -> exit code.
_SKILL_CODES = {
    "invalid_skill": EXIT_SKILL,
    "skill_exists": EXIT_SKILL,
    "skill_not_found": EXIT_SKILL,
    "golden_skill": EXIT_SKILL,
    "answer_would_be_lost": EXIT_ANSWER_WOULD_BE_LOST,
    "rolled_back": EXIT_ROLLED_BACK,
    "rollback_failed": EXIT_ROLLBACK_FAILED,
}

# ReconcileError.status -> exit code. A status not listed here is treated as a bug (exit 1).
_REFUSAL_CODES = {
    "tenant_conflict": EXIT_TENANT_CONFLICT,
    "invalid_descriptor": EXIT_INVALID_INPUT,
    "library_revision_mismatch": EXIT_PIN,
    "unpinned_skill": EXIT_PIN,
    "skill_not_in_library": EXIT_SKILL,
    "invalid_skill": EXIT_SKILL,
    "invalid_template": EXIT_INVALID_TEMPLATE,
    "invalid_existing_config": EXIT_EXISTING_CONFIG,
}

TEMPLATE_FILE = "client-config.template.md"


class _Refusal(Exception):
    """A run that must stop with a reportable status (a refusal, not a bug)."""

    def __init__(self, status: str, code: int, **details: object) -> None:
        super().__init__(status)
        self.status = status
        self.code = code
        self.details = details


def _build_parser() -> argparse.ArgumentParser:
    """`fill` subcommand: skill_dir (positional), --answers and --out (both required)."""
    parser = argparse.ArgumentParser(prog="claw-skills-kit")
    subparsers = parser.add_subparsers(dest="command", required=True)

    fill_parser = subparsers.add_parser(
        "fill",
        help="Fill a skill's client-config.template.md with answers from a JSON file.",
    )
    fill_parser.add_argument(
        "skill_dir",
        type=Path,
        help="Path to the skill directory containing client-config.template.md.",
    )
    fill_parser.add_argument(
        "--answers",
        type=Path,
        required=True,
        help="Path to the client answers JSON file.",
    )
    fill_parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Destination path for the filled client-config.md.",
    )

    lock_parser = subparsers.add_parser(
        "lock", help="Write the pins file: the current revision of each named library skill."
    )
    lock_parser.add_argument("library", type=Path, help="Folder holding the skills.")
    lock_parser.add_argument("--skills", nargs="+", required=True, help="Skill names to pin.")
    lock_parser.add_argument("--out", type=Path, required=True, help="Where to write the pins file.")

    rec_parser = subparsers.add_parser(
        "reconcile",
        help="Bring a host's skills to the pinned library revision (dry run unless --apply).",
    )
    rec_parser.add_argument("--host", type=Path, required=True, help="Host descriptor JSON.")
    rec_parser.add_argument("--library", type=Path, required=True, help="Folder holding the skills.")
    rec_parser.add_argument("--target", type=Path, required=True, help="The host's skills folder.")
    rec_parser.add_argument("--pins", type=Path, required=True, help="Pins file (skills.lock.json).")
    rec_parser.add_argument(
        "--apply", action="store_true", help="Write the changes. Without it nothing is touched."
    )

    q_parser = subparsers.add_parser(
        "question",
        help="Add, change or remove a question in one client's client-config.md (dry run unless --apply).",
    )
    q_sub = q_parser.add_subparsers(dest="action", required=True)
    for action, help_text in (
        ("add", "Add an instance-only question."),
        ("change", "Change an instance question, or only the answer of a golden one."),
        ("remove", "Remove an instance-only question."),
    ):
        a = q_sub.add_parser(action, help=help_text)
        a.add_argument("skill_dir", type=Path, help="The skill folder on the host (holds client-config.md).")
        a.add_argument("--key", required=True, help="Setting name (first column).")
        if action in ("add", "change"):
            a.add_argument("--suggested", required=action == "add", help="Suggested answer / question hint.")
            a.add_argument("--answer", help="The client's answer (Value column).")
        if action == "remove":
            a.add_argument(
                "--discard-answer", action="store_true", help="Allow removing a question that has an answer."
            )
        a.add_argument("--apply", action="store_true", help="Write the change. Without it nothing is touched.")

    s_parser = subparsers.add_parser(
        "skill", help="Create or remove a skill on one client's instance (dry run unless --apply)."
    )
    s_sub = s_parser.add_subparsers(dest="action", required=True)
    create = s_sub.add_parser("create", help="Create a skill with SKILL.md and an empty client-config.md.")
    create.add_argument("skills_dir", type=Path, help="The instance's skills folder.")
    create.add_argument("--name", required=True, help="Skill name: lowercase letters, digits, hyphens.")
    create.add_argument("--description", required=True, help="One line: what the skill does.")
    body = create.add_mutually_exclusive_group(required=True)
    body.add_argument("--instructions", help="SKILL.md body (Markdown).")
    body.add_argument(
        "--instructions-file", type=Path, help="File holding the SKILL.md body; '-' reads it from stdin."
    )
    create.add_argument("--apply", action="store_true", help="Write the skill. Without it nothing is touched.")
    remove = s_sub.add_parser("remove", help="Remove a skill that was created on this instance.")
    remove.add_argument("skills_dir", type=Path, help="The instance's skills folder.")
    remove.add_argument("--name", required=True)
    remove.add_argument(
        "--discard-answers", action="store_true", help="Allow removing a skill whose questions have answers."
    )
    remove.add_argument("--apply", action="store_true", help="Delete the skill. Without it nothing is touched.")
    return parser


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    """Run the command and return the exit code. Never calls sys.exit itself."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "fill":
            return _run_fill(parser, args.skill_dir, args.answers, args.out)
        if args.command == "lock":
            return _run_lock(args.library, args.skills, args.out)
        if args.command == "skill":
            return _run_skill(args)
        if args.command == "question":
            return _run_question(args)
        if args.command == "reconcile":
            return _run_reconcile(args.host, args.library, args.target, args.pins, args.apply)
        parser.error(f"Unknown command: {args.command}")
    except _Refusal as refusal:
        _emit({"ok": False, "status": refusal.status, **refusal.details})
        return refusal.code
    except Exception as exc:  # noqa: BLE001 - a bug must still produce JSON for the caller
        traceback.print_exc(file=sys.stderr)  # details for the developer, off stdout
        _emit({"ok": False, "status": "unexpected_error", "error": str(exc)})
        return EXIT_UNEXPECTED


def _read_utf8(path: Path, status: str, code: int, what: str) -> str:
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise _Refusal(status, code, error=f"Cannot read {what}: {exc}") from None


def _read_stdin_utf8(status: str, code: int, what: str) -> str:
    """Text piped in by the caller (e.g. a heredoc), so long text needs no shell quoting."""
    try:
        return sys.stdin.buffer.read().decode("utf-8")
    except (OSError, UnicodeDecodeError, AttributeError) as exc:
        raise _Refusal(status, code, error=f"Cannot read {what} from stdin: {exc}") from None


def _write_if_changed(path: Path, data: bytes) -> bool:
    """Atomic write; returns False (and touches nothing) when the file is already right."""
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_bytes(data)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)  # no-op after a successful replace
    return True


def _run_fill(
    parser: argparse.ArgumentParser,
    skill_dir: Path,
    answers_path: Path,
    out_path: Path,
) -> int:
    template_path = skill_dir / TEMPLATE_FILE
    if out_path.resolve() == template_path.resolve():
        parser.error(f"--out must not point to the skill's own {TEMPLATE_FILE}.")

    # 1. Read and parse the template
    template_text = _read_utf8(template_path, "invalid_template", EXIT_INVALID_TEMPLATE, "template")
    try:
        template = parse_template(template_text)
    except TemplateFormatError as exc:
        raise _Refusal("invalid_template", EXIT_INVALID_TEMPLATE, error=str(exc)) from None

    # 2. Read, load and apply the answers
    answers_text = _read_utf8(answers_path, "invalid_answers", EXIT_INVALID_ANSWERS, "answers file")
    try:
        filled = apply_answers(template, load_answers(answers_text))
    except InterviewError as exc:
        raise _Refusal("invalid_answers", EXIT_INVALID_ANSWERS, error=str(exc)) from None

    # 3. Required answers must be complete before anything is written
    missing = missing_required(filled)
    if missing:
        raise _Refusal(
            "missing_required",
            EXIT_MISSING_ANSWERS,
            missing=[
                {"key": f.key, "comes_from": f.comes_from, "suggested": f.suggested}
                for f in missing
            ],
            error="Missing required answers: " + ", ".join(f.key for f in missing) + ".",
        )

    # 4. Fill the original text (only the Answer cells change)
    try:
        new_bytes = fill_answers(template_text, filled).encode("utf-8")
    except FillError as exc:
        raise _Refusal("invalid_answers", EXIT_INVALID_ANSWERS, error=str(exc)) from None

    # 5. Write (atomic, and only if the content actually changed)
    changed = _write_if_changed(out_path, new_bytes)

    # 6. Report
    _emit({"ok": True, "status": "ok", "changed": changed, "out": str(out_path)})
    return EXIT_OK


def _require_dir(path: Path, label: str) -> None:
    if not path.is_dir():
        raise _Refusal("invalid_input", EXIT_INVALID_INPUT, error=f"{label} is not a folder: {path}")


def _refuse(exc: ReconcileError) -> _Refusal:
    return _Refusal(exc.status, _REFUSAL_CODES.get(exc.status, EXIT_UNEXPECTED), error=str(exc))


def _run_lock(library: Path, skills: list[str], out_path: Path) -> int:
    _require_dir(library, "library")
    try:
        revisions = compute_revisions(LocalHost(library), skills)
    except ReconcileError as exc:
        raise _refuse(exc) from None
    changed = _write_if_changed(out_path, dump_pins(revisions).encode("utf-8"))
    _emit({"ok": True, "status": "ok", "changed": changed, "out": str(out_path), "skills": revisions})
    return EXIT_OK


def _run_reconcile(host_path: Path, library: Path, target: Path, pins_path: Path, apply: bool) -> int:
    descriptor_text = _read_utf8(host_path, "invalid_descriptor", EXIT_INVALID_INPUT, "host descriptor")
    try:
        descriptor = load_descriptor(descriptor_text)
    except DescriptorError as exc:
        raise _Refusal("invalid_descriptor", EXIT_INVALID_INPUT, error=str(exc)) from None

    pins_text = _read_utf8(pins_path, "invalid_pins", EXIT_INVALID_INPUT, "pins file")
    try:
        pins = load_pins(pins_text)
    except LockfileError as exc:
        raise _Refusal("invalid_pins", EXIT_INVALID_INPUT, error=str(exc)) from None

    _require_dir(library, "library")
    _require_dir(target, "target")  # a typo must not silently create a new folder

    def smoke_commands():
        return [
            CommandCheck(argv, timeout=descriptor.smoke.timeout_seconds)
            for argv in descriptor.smoke.commands
        ]

    try:
        report = reconcile(
            descriptor, LocalHost(library), LocalHost(target), pins, apply=apply, extra_checks=smoke_commands
        )
    except ReconcileError as exc:
        raise _refuse(exc) from None

    code = {"rolled_back": EXIT_ROLLED_BACK, "rollback_failed": EXIT_ROLLBACK_FAILED}.get(report.status, EXIT_OK)
    _emit({"ok": code == EXIT_OK, **report.to_dict()})
    return code


def _run_question(args: argparse.Namespace) -> int:
    config_path = args.skill_dir / ANSWERS_FILE
    if not config_path.is_file():
        raise _Refusal("invalid_input", EXIT_INVALID_INPUT, error=f"No {ANSWERS_FILE} in {args.skill_dir}")
    text = _read_utf8(config_path, "invalid_existing_config", EXIT_EXISTING_CONFIG, ANSWERS_FILE)
    try:
        if args.action == "add":
            edit = add_question(text, args.key, args.suggested, args.answer or "")
        elif args.action == "change":
            edit = change_question(text, args.key, suggested=args.suggested, answer=args.answer)
        else:
            edit = remove_question(text, args.key, discard_answer=args.discard_answer)
    except QuestionError as exc:
        raise _Refusal(exc.status, _QUESTION_CODES.get(exc.status, EXIT_UNEXPECTED), error=str(exc)) from None

    if edit.text == text:
        status, changed = "unchanged", False
    elif args.apply:
        changed = _write_if_changed(config_path, edit.text.encode("utf-8"))
        status = "applied"
    else:
        status, changed = "planned", False
    # keys only, never answer values
    _emit({
        "ok": True, "status": status, "changed": changed, "action": edit.action, "key": edit.key,
        "discarded_answer": edit.had_answer and status == "applied", "out": str(config_path),
    })
    return EXIT_OK


def _run_skill(args: argparse.Namespace) -> int:
    _require_dir(args.skills_dir, "skills folder")
    skills = LocalHost(args.skills_dir)
    try:
        if args.action == "create":
            if args.instructions_file == Path("-"):
                instructions = _read_stdin_utf8("invalid_input", EXIT_INVALID_INPUT, "instructions")
            elif args.instructions_file is not None:
                instructions = _read_utf8(
                    args.instructions_file, "invalid_input", EXIT_INVALID_INPUT, "instructions file"
                )
            else:
                instructions = args.instructions
            plan = plan_create(skills, args.name, args.description, instructions)
        else:
            plan = plan_remove(skills, args.name, discard_answers=args.discard_answers)
        if args.apply:
            apply_plan(skills, plan)
    except SkillError as exc:
        raise _Refusal(exc.status, _SKILL_CODES.get(exc.status, EXIT_UNEXPECTED), error=str(exc)) from None

    _emit({
        "ok": True, "status": "applied" if args.apply else "planned", "action": plan.action,
        "skill": plan.name, "files": sorted(plan.files),
        "discarded_answers": plan.had_answers and args.apply,
    })
    return EXIT_OK
