import argparse
import json
import sys
import traceback
from pathlib import Path

from claw_skills_kit.evidence import evidence_path, history, record_approval, record_result
from claw_skills_kit.skills import NewQuestion, SkillError, apply_plan, plan_create, plan_remove
from claw_skills_kit.questions import QuestionError, add_question, change_question, remove_question
from claw_skills_kit.interview import InterviewError, apply_answers, load_answers, missing_required
from claw_skills_kit.reconcile import ReconcileError, compute_revisions, reconcile
from claw_skills_kit.review import review_diff
from claw_skills_kit.reconciler.descriptor import DescriptorError, load_descriptor
from claw_skills_kit.reconciler.host import LocalHost
from claw_skills_kit.reconciler.layout import ANSWERS_FILE
from claw_skills_kit.reconciler.lockfile import LockfileError, dump_pins, load_pins, load_runtime_pins
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
EXIT_INTEGRATION = 15
EXIT_HOST_CHECK = 16

# IntegrationError.status -> exit code.
_INTEGRATION_CODES = {
    "invalid_skill": EXIT_SKILL,
    "skill_not_found": EXIT_SKILL,
    "not_required": EXIT_INTEGRATION,
    "secret_value_refused": EXIT_INTEGRATION,
    "looks_like_secret": EXIT_INTEGRATION,
    "no_primary_env": EXIT_INTEGRATION,
    "invalid_integration": EXIT_INTEGRATION,
    "config_unreadable": EXIT_INVALID_INPUT,
    "rolled_back": EXIT_ROLLED_BACK,
    "rollback_failed": EXIT_ROLLBACK_FAILED,
    "openclaw_failed": EXIT_UNEXPECTED,
}

# QuestionError.status -> exit code.
_QUESTION_CODES = {
    "question_exists": EXIT_QUESTION,
    "question_not_found": EXIT_QUESTION,
    "library_question": EXIT_QUESTION,
    "invalid_question": EXIT_QUESTION,
    "answer_would_be_lost": EXIT_ANSWER_WOULD_BE_LOST,
    "invalid_existing_config": EXIT_EXISTING_CONFIG,
}

# SkillError.status -> exit code.
_SKILL_CODES = {
    "invalid_skill": EXIT_SKILL,
    "skill_exists": EXIT_SKILL,
    "skill_not_found": EXIT_SKILL,
    "library_skill": EXIT_SKILL,
    "client_data_in_skill": EXIT_SKILL,
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
    lock_parser.add_argument("--openclaw", metavar="VERSION", help="Pin the OpenClaw version hosts must run.")
    lock_parser.add_argument("--node", metavar="VERSION", help="Pin the Node version hosts must run.")

    rec_parser = subparsers.add_parser(
        "reconcile",
        help="Bring a host's skills to the pinned library revision (dry run unless --apply).",
    )
    rec_parser.add_argument("--host", type=Path, required=True, help="Host descriptor JSON.")
    rec_parser.add_argument("--library", type=Path, required=True, help="Folder holding the skills.")
    rec_parser.add_argument("--target", type=Path, required=True, help="The host's skills folder.")
    rec_parser.add_argument("--pins", type=Path, required=True, help="Pins file (skills.lock.json).")
    rec_parser.add_argument(
        "--diff", action="store_true",
        help="Add a text diff of the planned change. client-config.md is summarised by keys, never by values.",
    )
    rec_parser.add_argument(
        "--backup-dir", type=Path,
        help="With --apply: first copy every file that will be replaced or deleted to BACKUP_DIR/<UTC time>/.",
    )
    rec_parser.add_argument(
        "--apply", action="store_true", help="Write the changes. Without it nothing is touched."
    )
    _add_approval(rec_parser)

    q_parser = subparsers.add_parser(
        "question",
        help="Add, change or remove a question in one client's client-config.md (dry run unless --apply).",
    )
    q_sub = q_parser.add_subparsers(dest="action", required=True)
    for action, help_text in (
        ("add", "Add an instance-only question."),
        ("change", "Change an instance question, or only the answer of a library one."),
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
        _add_approval(a)

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
    create.add_argument(
        "--question", action="append", nargs="+", default=[], metavar="VALUE",
        help="A settings question written with the skill: KEY SUGGESTED [ANSWER]. Repeat for each question.",
    )
    create.add_argument("--apply", action="store_true", help="Write the skill. Without it nothing is touched.")
    _add_approval(create)
    remove = s_sub.add_parser("remove", help="Remove a skill that was created on this instance.")
    remove.add_argument("skills_dir", type=Path, help="The instance's skills folder.")
    remove.add_argument("--name", required=True)
    remove.add_argument(
        "--discard-answers", action="store_true", help="Allow removing a skill whose questions have answers."
    )
    remove.add_argument("--apply", action="store_true", help="Delete the skill. Without it nothing is touched.")
    _add_approval(remove)

    hist = subparsers.add_parser("history", help="Changes recorded on this host, newest first (CSK_EVIDENCE).")
    hist.add_argument("--limit", type=int, default=20, help="How many changes to show (default 20).")
    hist.add_argument("--evidence", type=Path, help="Evidence file; defaults to $CSK_EVIDENCE.")

    lint_parser = subparsers.add_parser(
        "lint",
        help="Library check: no client specifics in Layer 1, required files present (exit 11 on findings).",
    )
    lint_parser.add_argument("skill_dirs", nargs="+", type=Path, help="Skill folders to check.")
    lint_parser.add_argument(
        "--library", action="store_true",
        help="Library skills: also require client-config.template.md, interview.md (1-3 questions), lineage.md.",
    )

    h_parser = subparsers.add_parser("host", help="Read this host's descriptor (read-only).")
    h_sub = h_parser.add_subparsers(dest="action", required=True)
    show = h_sub.add_parser("show", help="The host, its one client and its library skills.")
    show.add_argument("--host", required=True, type=Path, help="Host descriptor (JSON).")
    check = h_sub.add_parser(
        "check-client",
        help="Could this gateway also serve CLIENT? Same tenant check as reconcile: exit 8 if it is another client.",
    )
    check.add_argument("--host", required=True, type=Path, help="Host descriptor (JSON).")
    check.add_argument("--name", required=True, help="The client the request is for.")
    rel = h_sub.add_parser(
        "releases",
        help="Which library release this host runs now, and the next one to install (read-only).",
    )
    rel.add_argument("--host", required=True, type=Path, help="Host descriptor (JSON).")
    rel.add_argument("--releases", required=True, type=Path, help="Folder with one sub-folder per release.")
    doctor = h_sub.add_parser(
        "doctor",
        help="Smoke check: openclaw doctor --lint passes, except findings listed in the descriptor's doctor_allow "
             "(exit 16 names the others).",
    )
    doctor.add_argument("--host", required=True, type=Path, help="Host descriptor (JSON).")
    verify = h_sub.add_parser(
        "verify-skills",
        help="Smoke check: OpenClaw finds every library skill of this host (exit 11 lists the missing ones).",
    )
    verify.add_argument("--host", required=True, type=Path, help="Host descriptor (JSON).")

    i_parser = subparsers.add_parser(
        "integration",
        help="Enable or disable a skill's integration in this gateway's config (skills.entries.<skill>).",
    )
    i_sub = i_parser.add_subparsers(dest="action", required=True)
    for action, help_text in (
        ("status", "Show what the skill needs and whether it loads now."),
        ("enable", "Provide the variables the skill declares (values) and/or its API key (a reference only)."),
        ("disable", "Remove what enable set; the skill stops loading."),
    ):
        p = i_sub.add_parser(action, help=help_text)
        p.add_argument("skills_dir", type=Path, help="The instance's skills folder.")
        p.add_argument("--name", required=True)
        if action == "enable":
            p.add_argument(
                "--env", action="append", default=[], metavar="VAR=VALUE",
                help="A variable the skill declares in requires.env, with a value that is not a secret.",
            )
            p.add_argument(
                "--api-key-env", metavar="VAR",
                help="The environment variable that holds the skill's API key (stored as a reference, never a value).",
            )
        if action != "status":
            p.add_argument("--apply", action="store_true", help="Change the config. Without it nothing is touched.")
            _add_approval(p)
    return parser


_LAST_PAYLOAD: dict[str, object] | None = None


def _emit(payload: dict[str, object]) -> None:
    global _LAST_PAYLOAD
    _LAST_PAYLOAD = payload
    print(json.dumps(payload, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    """Run the command and return the exit code. Never calls sys.exit itself.

    With CSK_EVIDENCE set, an applying command (--apply) needs --approval: the approval is recorded before the
    command runs and its outcome after, whatever the outcome (see evidence.py).
    """
    global _LAST_PAYLOAD
    parser = _build_parser()
    args = parser.parse_args(argv)
    _LAST_PAYLOAD = None
    record_id, path = None, None
    try:
        if getattr(args, "apply", False):
            record_id, path = _record_approval(args)
    except _Refusal as refusal:
        _emit({"ok": False, "status": refusal.status, **refusal.details})
        return refusal.code
    code = _dispatch(parser, args)
    if record_id is not None:
        record_result(path, record_id, _LAST_PAYLOAD, code)
    return code


def _add_approval(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--approval", metavar="TEXT",
        help="The question the client said yes to, in plain words (no answer values). "
             "Required with --apply when CSK_EVIDENCE is set; recorded before the change.",
    )


def _target_of(args: argparse.Namespace) -> str:
    if args.command == "reconcile":
        return str(args.library)
    for name in ("skill_dir", "skills_dir"):
        if getattr(args, name, None) is not None:
            value = str(getattr(args, name))
            return f"{value}/{args.name}" if getattr(args, "name", None) else value
    return ""


def _record_approval(args: argparse.Namespace):
    from claw_skills_kit.layer1 import find_client_specifics

    path = evidence_path()
    if path is None:
        return None, None
    approval = (args.approval or "").strip()
    if not approval:
        raise _Refusal("approval_required", EXIT_INVALID_INPUT,
                       error="This host records approvals: pass --approval with the question the client said yes to.")
    if "\n" in approval or len(approval) > 300:
        raise _Refusal("invalid_input", EXIT_INVALID_INPUT, error="--approval must be one line of at most 300 characters.")
    if find_client_specifics(approval):
        raise _Refusal("approval_has_client_data", EXIT_INVALID_INPUT,
                       error="Write the approval without contact details, IDs, links or secrets.")
    values = [getattr(args, "answer", None) or ""]
    values += [q[2] for q in (getattr(args, "question", None) or []) if len(q) > 2]
    if any(v.strip() and v.strip().casefold() in approval.casefold() for v in values):
        raise _Refusal("approval_has_answer_value", EXIT_INVALID_INPUT,
                       error='The approval must not repeat the answer: write "Save your answer to: <the question>".')
    try:
        return record_approval(path, args.command, getattr(args, "action", None), _target_of(args), approval), path
    except OSError as exc:
        raise _Refusal("evidence_unwritable", EXIT_INVALID_INPUT, error=f"Cannot record the approval: {exc}") from None


def _dispatch(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    try:
        if args.command == "history":
            return _run_history(args)
        if args.command == "fill":
            return _run_fill(parser, args.skill_dir, args.answers, args.out)
        if args.command == "lock":
            return _run_lock(args.library, args.skills, args.out, {"openclaw": args.openclaw, "node": args.node})
        if args.command == "skill":
            return _run_skill(args)
        if args.command == "question":
            return _run_question(args)
        if args.command == "reconcile":
            return _run_reconcile(
                args.host, args.library, args.target, args.pins, args.apply, args.backup_dir, args.diff
            )
        if args.command == "integration":
            return _run_integration(args)
        if args.command == "host":
            return _run_host(args)
        if args.command == "lint":
            return _run_lint(args.skill_dirs, args.library)
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


def _run_lock(library: Path, skills: list[str], out_path: Path, runtime: dict[str, str | None] | None = None) -> int:
    _require_dir(library, "library")
    try:
        revisions = compute_revisions(LocalHost(library), skills)
    except ReconcileError as exc:
        raise _refuse(exc) from None
    pinned = {k: v for k, v in (runtime or {}).items() if v}
    text = dump_pins(revisions, pinned)
    try:
        load_runtime_pins(text)
    except LockfileError as exc:
        raise _Refusal("invalid_pins", EXIT_INVALID_INPUT, error=str(exc)) from None
    changed = _write_if_changed(out_path, text.encode("utf-8"))
    _emit({"ok": True, "status": "ok", "changed": changed, "out": str(out_path), "skills": revisions,
           "runtime": pinned})
    return EXIT_OK


def _run_reconcile(
    host_path: Path, library: Path, target: Path, pins_path: Path, apply: bool, backup_dir: Path | None = None,
    want_diff: bool = False,
) -> int:
    descriptor_text = _read_utf8(host_path, "invalid_descriptor", EXIT_INVALID_INPUT, "host descriptor")
    try:
        descriptor = load_descriptor(descriptor_text)
    except DescriptorError as exc:
        raise _Refusal("invalid_descriptor", EXIT_INVALID_INPUT, error=str(exc)) from None

    pins_text = _read_utf8(pins_path, "invalid_pins", EXIT_INVALID_INPUT, "pins file")
    try:
        pins = load_pins(pins_text)
        runtime = load_runtime_pins(pins_text)
    except LockfileError as exc:
        raise _Refusal("invalid_pins", EXIT_INVALID_INPUT, error=str(exc)) from None
    _check_runtime(runtime)  # before anything else: a host on another OpenClaw or Node version is refused

    _require_dir(library, "library")
    _require_dir(target, "target")  # a typo must not silently create a new folder

    def smoke_commands():
        return [
            CommandCheck(argv, timeout=descriptor.smoke.timeout_seconds)
            for argv in descriptor.smoke.commands
        ]

    extra: dict[str, object] = {}
    try:
        if (apply and backup_dir is not None) or want_diff:
            plan = reconcile(descriptor, LocalHost(library), LocalHost(target), pins, apply=False)
            if want_diff:
                extra["diff"] = review_diff(plan, LocalHost(target))  # from the plan, before anything is written
            if apply and backup_dir is not None:
                extra.update(_backup_before_apply(plan, target, backup_dir))
        report = reconcile(
            descriptor, LocalHost(library), LocalHost(target), pins, apply=apply, extra_checks=smoke_commands
        )
    except ReconcileError as exc:
        raise _refuse(exc) from None

    code = {"rolled_back": EXIT_ROLLED_BACK, "rollback_failed": EXIT_ROLLBACK_FAILED}.get(report.status, EXIT_OK)
    _emit({"ok": code == EXIT_OK, **report.to_dict(), **extra})
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


def _new_question(values: list[str]) -> NewQuestion:
    if len(values) not in (2, 3):
        raise _Refusal(
            "invalid_question", EXIT_QUESTION,
            error=f"--question takes KEY SUGGESTED [ANSWER]; got {len(values)} value(s).",
        )
    return NewQuestion(*values)


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
            questions = [_new_question(values) for values in args.question]
            plan = plan_create(skills, args.name, args.description, instructions, questions)
        else:
            plan = plan_remove(skills, args.name, discard_answers=args.discard_answers)
        if args.apply:
            apply_plan(skills, plan)
    except SkillError as exc:
        details: dict[str, object] = {"error": str(exc)}
        if exc.findings:
            details["findings"] = list(exc.findings)  # kind and line only, never the text found
        raise _Refusal(exc.status, _SKILL_CODES.get(exc.status, EXIT_UNEXPECTED), **details) from None
    except QuestionError as exc:
        raise _Refusal(exc.status, _QUESTION_CODES.get(exc.status, EXIT_UNEXPECTED), error=str(exc)) from None

    # keys only, never answer values
    _emit({
        "ok": True, "status": "applied" if args.apply else "planned", "action": plan.action,
        "skill": plan.name, "files": sorted(plan.files), "questions": list(plan.questions),
        "discarded_answers": plan.had_answers and args.apply,
    })
    return EXIT_OK


def _parse_env_pairs(pairs: list[str]) -> dict[str, str]:
    env: dict[str, str] = {}
    for pair in pairs:
        name, sep, value = pair.partition("=")
        if not sep or not name:
            raise _Refusal("invalid_integration", EXIT_INTEGRATION, error="--env takes VAR=VALUE.")
        if name in env:
            raise _Refusal("invalid_integration", EXIT_INTEGRATION, error=f"{name} given twice.")
        env[name] = value
    return env


def _run_integration(args: argparse.Namespace) -> int:
    from claw_skills_kit import integrations as ig  # local: the other commands never need it

    _require_dir(args.skills_dir, "skills folder")
    skill_md_path = args.skills_dir / args.name / "SKILL.md"
    if "/" in args.name or "\\" in args.name or args.name.startswith(".") or not skill_md_path.is_file():
        raise _Refusal("skill_not_found", EXIT_SKILL, error=f"There is no skill called {args.name!r} here.")
    try:
        requirements = ig.read_requirements(skill_md_path.read_text(encoding="utf-8"))
        openclaw = ig.OpenClaw()
        config_file = openclaw.config_file()
        entry = ig.read_entry(config_file, args.name)
        if args.action == "status":
            status = ig.status_of(args.name, requirements, entry, openclaw.skill_ready(args.name))
            _emit({
                "ok": True, "status": "ready" if status.ready else "not_ready", "skill": args.name,
                "required_env": list(status.required_env), "primary_env": status.primary_env,
                "configured_env": list(status.configured_env), "api_key_ref": status.api_key_ref,
                "missing_env": list(status.missing_env),
            })
            return EXIT_OK
        if args.action == "enable":
            plan = ig.plan_enable(
                args.name, requirements, entry, _parse_env_pairs(args.env), args.api_key_env
            )
        else:
            plan = ig.plan_disable(args.name, requirements, entry)
        ready = None
        if args.apply:
            ready = ig.apply_plan(openclaw, config_file, plan)
    except ig.IntegrationError as exc:
        details: dict[str, object] = {"error": str(exc)}
        if exc.unrestored:
            details["unrestored"] = list(exc.unrestored)
        raise _Refusal(exc.status, _INTEGRATION_CODES.get(exc.status, EXIT_UNEXPECTED), **details) from None

    if not plan.changed:
        status = "unchanged"
    else:
        status = "applied" if args.apply else "planned"
    # variable names only, never values
    _emit({
        "ok": True, "status": status, "action": plan.action, "skill": plan.skill,
        "env": list(plan.env_names), "api_key_ref": plan.api_key_ref, "ready": ready,
    })
    return EXIT_OK


def _run_host(args: argparse.Namespace) -> int:
    """Read-only. check-client runs the reconciler's own tenant check on (this host's client + the new one)."""
    import dataclasses

    from claw_skills_kit.reconciler.descriptor import TenantConflictError, check_single_tenant

    text = _read_utf8(args.host, "invalid_descriptor", EXIT_INVALID_INPUT, "host descriptor")
    try:
        descriptor = load_descriptor(text)
        check_single_tenant(descriptor)
    except TenantConflictError as exc:
        raise _Refusal("tenant_conflict", EXIT_TENANT_CONFLICT, error=str(exc)) from None
    except DescriptorError as exc:
        raise _Refusal("invalid_descriptor", EXIT_INVALID_INPUT, error=str(exc)) from None

    base = {"host_id": descriptor.host_id, "client": descriptor.clients[0]}
    if args.action == "verify-skills":
        return _verify_skills(descriptor, base)
    if args.action == "doctor":
        allow = json.loads(text).get("doctor_allow", [])
        if not isinstance(allow, list) or not all(isinstance(a, str) and a for a in allow):
            raise _Refusal("invalid_descriptor", EXIT_INVALID_INPUT, error="'doctor_allow' must be a list of ids.")
        return _doctor(base, set(allow))
    if args.action == "releases":
        return _releases(descriptor, base, args.releases)
    if args.action == "show":
        _emit({"ok": True, "status": "ok", **base, "skills": list(descriptor.skills)})
        return EXIT_OK

    name = args.name.strip()
    if not name:
        raise _Refusal("invalid_input", EXIT_INVALID_INPUT, error="--name must not be empty.")
    if name.casefold() in {c.casefold() for c in descriptor.clients}:
        _emit({"ok": True, "status": "same_client", **base})
        return EXIT_OK
    try:
        check_single_tenant(dataclasses.replace(descriptor, clients=(*descriptor.clients, name)))
    except TenantConflictError:
        raise _Refusal(
            "tenant_conflict", EXIT_TENANT_CONFLICT, **base,
            error="This gateway already serves one client; another client needs its own gateway.",
        ) from None
    raise AssertionError("the tenant check accepted a second client")  # a bug: reported as unexpected_error


def _verify_skills(descriptor, base: dict[str, object]) -> int:
    """Every skill the descriptor manages must be in OpenClaw's inventory (`skills check --json`).

    Present in any state counts: ready, disabled, or waiting for an integration. A skill OpenClaw could not read
    (for example a broken SKILL.md frontmatter) is absent from the inventory, while `skills list` and
    `config validate` still exit 0 (observed on 2026.11.3), so this is the check that catches it.
    """
    from claw_skills_kit import integrations as ig

    try:
        openclaw = ig.OpenClaw()
        openclaw.rescan_skills(openclaw.config_file())  # otherwise the inventory can be a minute old
        inventory = openclaw.skill_inventory()
    except ig.IntegrationError as exc:
        raise _Refusal("openclaw_failed", EXIT_UNEXPECTED, error=str(exc)) from None
    missing = sorted(s for s in descriptor.skills if s not in inventory)
    if missing:
        raise _Refusal(
            "skills_not_loaded", EXIT_SKILL, **base, missing=missing,
            error="OpenClaw does not find these skills; their files may be broken.",
        )
    _emit({"ok": True, "status": "ok", **base, "skills": list(descriptor.skills)})
    return EXIT_OK


def _releases(descriptor, base: dict[str, object], releases: Path) -> int:
    """current = the release whose pins equal the installed skills' revisions; next = the release after it.

    Revisions ignore client-config.md, so the client's answers and instance-only questions never make a host look
    out of date. A host that matches no release has drifted: `current` is null and nothing should be applied.
    """
    _require_dir(releases, "releases folder")
    _require_dir(Path(descriptor.skills_dir), "skills folder")
    names = sorted(p.name for p in releases.iterdir() if (p / "skills.lock.json").is_file())
    target = LocalHost(Path(descriptor.skills_dir))
    installed: dict[str, str | None] = {}
    for skill in descriptor.skills:
        try:
            installed[skill] = compute_revisions(target, [skill])[skill]
        except ReconcileError:
            installed[skill] = None  # missing on the host
    current, closest, best = None, None, -1
    for name in names:
        try:
            pins = load_pins((releases / name / "skills.lock.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, LockfileError) as exc:
            raise _Refusal("invalid_pins", EXIT_INVALID_INPUT, error=f"{name}: {exc}") from None
        matching = [s for s in descriptor.skills if installed[s] is not None and pins.get(s) == installed[s]]
        if len(matching) == len(descriptor.skills):
            current = name
        if len(matching) >= best:  # ties go to the newer release
            closest, best = name, len(matching)
            drifted = [s for s in descriptor.skills if s not in matching]
    later = names[names.index(current) + 1:] if current else []
    payload: dict[str, object] = {
        "ok": True, "status": "ok" if current else "drift", **base, "current": current,
        "next": later[0] if later else None, "newer": later, "releases": names,
    }
    if current is None and closest is not None:
        # drift: the release nearest to the host, and the skills that differ from it (changed by hand or missing)
        payload.update(closest=closest, drifted=drifted)
    _emit(payload)
    return EXIT_OK


def _run_lint(folders: list[Path], library: bool) -> int:
    from claw_skills_kit.layer1 import lint_skill

    results: dict[str, list[dict[str, object]]] = {}
    for folder in folders:
        _require_dir(folder, "skill folder")
        results[folder.name] = [f.to_dict() for f in lint_skill(folder, library=library)]
    failed = {name: found for name, found in results.items() if found}
    # kinds and lines only, never the text found
    _emit({"ok": not failed, "status": "lint_failed" if failed else "ok", "skills": results})
    return EXIT_SKILL if failed else EXIT_OK


def _run_history(args: argparse.Namespace) -> int:
    path = args.evidence or evidence_path()
    if path is None:
        raise _Refusal("invalid_input", EXIT_INVALID_INPUT, error="No evidence file: set CSK_EVIDENCE or pass --evidence.")
    if args.limit < 1:
        raise _Refusal("invalid_input", EXIT_INVALID_INPUT, error="--limit must be at least 1.")
    entries = history(path, args.limit)
    _emit({"ok": True, "status": "ok", "count": len(entries), "changes": entries})
    return EXIT_OK


def _backup_before_apply(plan, target: Path, backup_dir: Path) -> dict[str, object]:
    """Copy the files a reconcile will replace or delete, so hand edits on a drifted host are never lost."""
    import shutil
    from datetime import datetime, timezone

    paths = [c.path for c in plan.changes if c.action in ("update", "delete") and (target / c.path).is_file()]
    if not paths:
        return {}
    folder = backup_dir / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    try:
        for rel in paths:
            (folder / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target / rel, folder / rel)
    except OSError as exc:
        raise _Refusal("backup_failed", EXIT_INVALID_INPUT, error=f"Nothing was changed; backup failed: {exc}") from None
    return {"backup": str(folder), "backed_up": sorted(paths)}


def _installed_version(command: list[str], pattern: str) -> str | None:
    import re
    import subprocess

    try:
        done = subprocess.run([*command, "--version"], capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.search(pattern, done.stdout) if done.returncode == 0 else None
    return match.group(1) if match else None


def _check_runtime(runtime: dict[str, str]) -> None:
    """Pinned OpenClaw and Node versions must equal what the host runs (versions only, never other output)."""
    import os
    import shlex

    commands = {
        "openclaw": (shlex.split(os.environ.get("CSK_OPENCLAW", "openclaw")), r"OpenClaw\s+(\S+)"),
        "node": (shlex.split(os.environ.get("CSK_NODE", "node")), r"v?(\d+\.\d+\.\d+)"),
    }
    for key, expected in runtime.items():
        command, pattern = commands[key]
        actual = _installed_version(command, pattern)
        if actual is None:
            raise _Refusal("runtime_unknown", EXIT_PIN, error=f"Cannot read the installed {key} version.")
        if actual != expected:
            raise _Refusal("runtime_mismatch", EXIT_PIN, runtime=key, pinned=expected, installed=actual,
                           error=f"The pins require {key} {expected}; this host runs {actual}.")


def _doctor(base: dict[str, object], allow: set[str]) -> int:
    """`openclaw doctor --lint --json` must report nothing beyond a reviewed list of known findings.

    doctor exits 1 on any warning (observed on 2026.11.3). In Docker one warning is expected: the gateway binds `lan`
    inside the container because port publishing needs it. Skipping the check or dropping warnings would also hide new
    ones, so findings are matched one by one against the descriptor's `doctor_allow` (requirement or check ids).
    """
    import os
    import shlex
    import subprocess

    command = shlex.split(os.environ.get("CSK_OPENCLAW", "openclaw"))
    try:
        done = subprocess.run([*command, "doctor", "--lint", "--json"], capture_output=True, text=True,
                              timeout=180, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise _Refusal("openclaw_failed", EXIT_UNEXPECTED, error=f"openclaw doctor could not run: {type(exc).__name__}") from None
    report = None
    for line in reversed(done.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                report = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    if not isinstance(report, dict) or not isinstance(report.get("findings"), list):
        raise _Refusal("openclaw_failed", EXIT_UNEXPECTED, error="openclaw doctor --lint --json returned no report.")
    findings = []
    for item in report["findings"]:
        if not isinstance(item, dict):
            continue
        ids = {str(item.get("requirement") or ""), str(item.get("checkId") or "")} - {""}
        findings.append({"check": item.get("checkId"), "requirement": item.get("requirement"),
                         "severity": item.get("severity"), "allowed": bool(ids & allow)})
    blocking = [f for f in findings if not f["allowed"]]
    if blocking:
        raise _Refusal("doctor_findings", EXIT_HOST_CHECK, **base, findings=findings,
                       error=f"openclaw doctor reports {len(blocking)} finding(s) not in doctor_allow.")
    _emit({"ok": True, "status": "ok", **base, "findings": findings})
    return EXIT_OK
