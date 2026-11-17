from __future__ import annotations

import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from claw_skills_kit.reconciler.host import Host
from claw_skills_kit.reconciler.layout import ANSWERS_FILE, SKILL_FILE
from claw_skills_kit.template_format import TemplateFormatError, parse_template


@dataclass(frozen=True)
class CheckOutcome:
    name: str
    ok: bool
    detail: str = ""


@dataclass(frozen=True)
class SmokeResult:
    outcomes: tuple[CheckOutcome, ...]

    @property
    def ok(self) -> bool:
        return all(o.ok for o in self.outcomes)

    @property
    def failures(self) -> tuple[CheckOutcome, ...]:
        return tuple(o for o in self.outcomes if not o.ok)


class Check(Protocol):
    name: str

    def run(self) -> CheckOutcome: ...


def run_checks(checks: Sequence[Check]) -> SmokeResult:

    outcomes = []
    for check in checks:
        try:
            outcomes.append(check.run())
        except Exception as exc:  # noqa: BLE001
            outcomes.append(CheckOutcome(check.name, False, f"check crashed: {type(exc).__name__}"))
    return SmokeResult(tuple(outcomes))


class IntegrityCheck:

    name = "integrity"

    def __init__(self, host: Host, expected: Mapping[str, bytes], skills: Sequence[str]) -> None:
        self._host = host
        self._expected = dict(expected)
        self._skills = tuple(skills)

    def run(self) -> CheckOutcome:
        problems = []
        for path, data in sorted(self._expected.items()):
            if self._host.read(path) != data:
                problems.append(f"{path} differs from what was written")
        for skill in self._skills:
            if self._host.read(f"{skill}/{SKILL_FILE}") is None:
                problems.append(f"{skill}/{SKILL_FILE} is missing")
            answers = self._host.read(f"{skill}/{ANSWERS_FILE}")
            if answers is not None:
                try:
                    parse_template(answers.decode("utf-8"))
                except (UnicodeDecodeError, TemplateFormatError):
                    problems.append(f"{skill}/{ANSWERS_FILE} is not a valid client config")
        return CheckOutcome(self.name, not problems, "; ".join(problems))


Runner = Callable[..., subprocess.CompletedProcess]


class CommandCheck:

    def __init__(
        self,
        argv: Sequence[str],
        timeout: float = 30.0,
        env: Mapping[str, str] | None = None,
        runner: Runner = subprocess.run,
    ) -> None:
        self._argv = list(argv)
        self._timeout = timeout
        self._env = dict(env) if env is not None else None
        self._runner = runner
        self.name = f"command: {' '.join(self._argv[:3])}"

    def run(self) -> CheckOutcome:
        try:
            proc = self._runner(
                self._argv, capture_output=True, timeout=self._timeout, env=self._env, check=False
            )
        except FileNotFoundError:
            return CheckOutcome(self.name, False, "command not found")
        except subprocess.TimeoutExpired:
            return CheckOutcome(self.name, False, f"timed out after {self._timeout:g}s")
        if proc.returncode == 0:
            return CheckOutcome(self.name, True, "")
        return CheckOutcome(self.name, False, f"exit code {proc.returncode}")
