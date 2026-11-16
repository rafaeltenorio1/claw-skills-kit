import argparse
import json
import sys
import traceback
from pathlib import Path

from claw_skills_kit.interview import InterviewError, apply_answers, load_answers, missing_required
from claw_skills_kit.template_format import FillError, TemplateFormatError, fill_answers, parse_template

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_INVALID_TEMPLATE = 3
EXIT_INVALID_ANSWERS = 4
EXIT_MISSING_ANSWERS = 5

TEMPLATE_FILE = "client-config.template.md"


class _Refusal(Exception):

    def __init__(self, status: str, code: int, **details: object) -> None:
        super().__init__(status)
        self.status = status
        self.code = code
        self.details = details


def _build_parser() -> argparse.ArgumentParser:

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
    return parser


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:

    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "fill":
            return _run_fill(parser, args.skill_dir, args.answers, args.out)
        parser.error(f"Unknown command: {args.command}")
    except _Refusal as refusal:
        _emit({"ok": False, "status": refusal.status, **refusal.details})
        return refusal.code
    except Exception as exc: 
        traceback.print_exc(file=sys.stderr) 
        _emit({"ok": False, "status": "unexpected_error", "error": str(exc)})
        return EXIT_UNEXPECTED


def _read_utf8(path: Path, status: str, code: int, what: str) -> str:
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise _Refusal(status, code, error=f"Cannot read {what}: {exc}") from None


def _write_if_changed(path: Path, data: bytes) -> bool:

    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_bytes(data)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
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

    template_text = _read_utf8(template_path, "invalid_template", EXIT_INVALID_TEMPLATE, "template")
    try:
        template = parse_template(template_text)
    except TemplateFormatError as exc:
        raise _Refusal("invalid_template", EXIT_INVALID_TEMPLATE, error=str(exc)) from None

    answers_text = _read_utf8(answers_path, "invalid_answers", EXIT_INVALID_ANSWERS, "answers file")
    try:
        filled = apply_answers(template, load_answers(answers_text))
    except InterviewError as exc:
        raise _Refusal("invalid_answers", EXIT_INVALID_ANSWERS, error=str(exc)) from None

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

    try:
        new_bytes = fill_answers(template_text, filled).encode("utf-8")
    except FillError as exc:
        raise _Refusal("invalid_answers", EXIT_INVALID_ANSWERS, error=str(exc)) from None

    changed = _write_if_changed(out_path, new_bytes)

    _emit({"ok": True, "status": "ok", "changed": changed, "out": str(out_path)})
    return EXIT_OK