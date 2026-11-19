# claw-skills-kit

A small, stdlib-only Python toolkit for operator golden skills on OpenClaw gateways, and a Docker host where every check
the project spec asks for is shown **through a conversation with the agent**.

- **Interview runner** (`fill`, and the agent's interview in chat): fills a skill's Layer 2 settings from the client's
  answers and refuses blank required answers.
- **Reconciler** (`reconcile`): brings a gateway that already runs to a pinned library release, keeps the client's
  answers, runs smoke checks, rolls back on failure, and reports what changed.
- **Skill manager** (`skills/skill-manager/`): the agent-facing skill. The client asks in plain words; the agent
  proposes, waits for a yes, and only then runs the toolkit's commands.

Every command runs non-interactively, prints one JSON object and exits with a documented code.

## Quick start

Needs Docker (tested with Docker Desktop on Windows + WSL2) and an env file **outside the repository** with
`OPENCLAW_GATEWAY_TOKEN` and `ANTHROPIC_API_KEY` (default `~/.config/csk/openclaw-test.env`, `export NAME=value`
lines). Values never enter the repository, the image or the generated config: they are env references.

```bash
docker/up.sh                          # build, configure, start; then open http://127.0.0.1:18790/
CSK_DEMO_ROLLBACK=1 docker/up.sh   # also add a library release that is broken on purpose
CSK_DEMO_DRIFT=1 docker/up.sh      # also edit an installed operator skill by hand (a drifted host)
docker compose -f docker/compose.yml down -v   # delete the instance and its state
```

Without Docker: `uv run pytest -q` (385 tests) and `uv run python -m claw_skills_kit --help`.

## What the spec asks, and how it shows

| Spec requirement | In chat (Docker host) | Code |
|---|---|---|
| Non-interactive commands, exit codes, structured output | the agent runs them and reads the JSON | every command |
| Interview runner, refuse blank required answers | the agent finds blank answers and asks the skill's `interview.md` questions | `fill`, `question change` |
| Install or update skills, keep the client's answers | "Are there any updates?" -> notes in plain words -> yes -> applied, answers kept, new question asked | `host releases`, `reconcile` |
| Second run changes nothing | checked by command, not in chat: the same release again reports `unchanged` | `reconcile` |
| Failed smoke leaves the host as it was | a broken release is applied, the check fails, every file is restored and verified | `reconcile`, `host verify-skills` |
| Skill needing an integration loads only once enabled | "Can I use the team digest?" -> connect the channel -> it loads; the skill file never changes | `integration` |
| Refuse two tenants in one gateway | a request for another business is refused | `host check-client`, `reconcile` (exit 8) |
| No secrets in output | a pasted token is refused and the client is asked to replace it | `secrets audit --check` clean |
| Approvals from a human in chat, recorded | even a direct instruction gets "Shall I?"; "What changed?" is answered from the record | `--approval`, `history` |
| No client specifics in Layer 1 | "a skill that emails joao@..." -> the address becomes a setting | `skill create`, `lint` |
| Patch a host that already exists (drift) | hand edits are found, explained, reverted with a backup, answers kept | `host releases`, `reconcile --backup-dir` |

## What works, and how it was checked

Checked on **OpenClaw 2026.11.3** (`ghcr.io/openclaw/openclaw:2026.11.3-browser`) in Docker, by chatting with the agent
in the Control UI, then reading the agent's transcript and the files on the host. Model: `anthropic/claude-opus-5-5`.

- **Tests:** `uv run pytest -q`, 385 passed. `tests/fake_openclaw.py` stands in for the five OpenClaw commands the
  integration code calls.
- **Interview:** blank answers found and asked; only the Value cells of `client-config.md` changed.
- **Update 2026.11.10 -> 2026.11.18:** dry run, yes, `applied` with four checks (integrity, `config validate`,
  `skills list`, `host verify-skills`); answers kept; the new question asked. Running the same release again
  (by command, in a throwaway instance) reported `unchanged`.
- **Rollback:** update to the broken release `2026.11.25`: `rolled_back` (exit 6), the three skills byte-identical to
  2026.11.18 afterwards, host still on 2026.11.18.
- **Integration:** `team-digest` was `disabled`; after "connect it to #team-acme" and a yes, `ready`; the skill file
  never changed; `config validate` and `secrets audit --check` clean.
- **Tenant:** a request for "Beta Corp": `host check-client` exit 8, refused in plain words, descriptor unchanged.
- **Approvals:** direct instructions answered with "Shall I?"; "no" changed nothing; with `CSK_EVIDENCE` set, an
  apply without `--approval` is refused; "What have you changed?" answered from `lk history`.
- **Layer 1:** a skill asked with an email in its text was created with the email as a setting only (0 occurrences in
  `SKILL.md`); `lk lint --golden` passes the library and fails the broken demo release.
- **Drift:** a hand rule added to `inbox-triage` was detected (`drift`, closest release named), explained, reverted
  after a yes, with the hand-made file kept in a backup.
- **Secrets:** a pasted (fake) token was refused, with no tool call; it is in no file outside the chat history.
- **Docker setup:** `docker/up.sh` twice in a row exits 0; the second run changes nothing it already did; API key
  and gateway token values found in 0 files of the state directory.

## What does not work, or was not checked

Gaps marked **critical** are explicit items of the spec's checklist that are not met as written.

- **Critical: `openclaw doctor --lint --json` exits 1 in Docker.** The only finding is the expected warning that the
  gateway binds `lan` inside the container (needed for Docker's port publishing; the port is published on host
  loopback only). `config validate` passes. Not yet decided: accept a reviewed list of known findings, or change the
  network setup. See `docs/decisions.md`.
- **Gateway and Node versions are pinned in the Docker image, not checked by the reconciler.** The pins file pins skill
  revisions only; `reconcile` does not refuse a host running another OpenClaw version.
- **The reconciler's output is a list of changed paths with before/after hashes**, not a text diff. A text diff of
  `client-config.md` would print answer values, which reports never contain.
- **`verify-skills` checks that every managed skill is loaded**, not that the list is "exactly" those: OpenClaw's own
  bundled skills are present too.
- **Confirm-before-change is enforced by instructions** (`AGENTS.md`, `SKILL.md`). In this setup the agent can run
  shell commands without an approval prompt; the record of approvals is written by the toolkit, not by OpenClaw.
- **Automations** (schedules) are OpenClaw's own: no dry run and no rollback from the toolkit.
- **No real chat channel or mailbox is connected.** Skills that post or read email are configured, not run.
- **A secret pasted in chat stays in OpenClaw's conversation history**; the agent asks for it to be replaced.
- **Rollback covers the skills folder** (and, for integrations, one `skills.entries` block); the snapshot is in
  memory, so killing the process mid-apply does not roll back.
- **Only Docker Desktop on WSL2** was used, with one host; no remote host, no tailnet.
- Format details that come from one sample or from us are listed in `docs/assumptions.md`.

## What I would do next

1. Decide the `doctor --lint` rule with operator and make it a smoke check.
2. Pin the gateway version in the pins file and refuse a host that runs another one.
3. A model-free monitor per host (gateway ready, skills loaded, config valid) with an alert path that does not go
   through the agent (the spec's third problem).
4. CI on the repository: tests, `lk lint --golden` on the library, a `git grep` for key patterns.
5. Remote hosts over the tailnet, and an on-disk snapshot so an interrupted apply can still be rolled back.

## Commands

```bash
uv run python -m claw_skills_kit fill SKILL_DIR --answers ANSWERS.json --out OUT.md
uv run python -m claw_skills_kit lock LIBRARY --skills NAME [NAME ...] --out skills.lock.json
uv run python -m claw_skills_kit reconcile --host HOST.json --library LIBRARY --target SKILLS_DIR --pins skills.lock.json \
    [--apply [--approval TEXT] [--backup-dir DIR]]
uv run python -m claw_skills_kit question {add|change|remove} SKILL_DIR --key K [--suggested S] [--answer A] [--apply]
uv run python -m claw_skills_kit skill create SKILLS_DIR --name N --description D [--question KEY SUGGESTED [ANSWER]]... \
    (--instructions T | --instructions-file F|-) [--apply]
uv run python -m claw_skills_kit skill remove SKILLS_DIR --name N [--discard-answers] [--apply]
uv run python -m claw_skills_kit integration {status|enable|disable} SKILLS_DIR --name N [--env VAR=VALUE]... \
    [--api-key-env VAR] [--apply]
uv run python -m claw_skills_kit host {show|check-client --name C|releases --releases DIR|verify-skills} --host HOST.json
uv run python -m claw_skills_kit lint [--golden] SKILL_DIR [...]
uv run python -m claw_skills_kit history [--limit N]
```

Anything that writes is a dry run unless `--apply` is given. With `CSK_EVIDENCE` set, `--apply` also needs
`--approval`, recorded before the change. Reports carry paths, hashes, keys and variable names, never answer values
or secrets.

| Exit | Meaning |
|---|---|
| 0 | ok: read `status` (`planned`, `applied`, `unchanged`, ...) |
| 1 | unexpected error |
| 2 | usage error |
| 3 | invalid template |
| 4 | invalid answers file |
| 5 | missing required answers (`fill`) |
| 6 | check failed, host restored and verified (`rolled_back`) |
| 7 | restore failed, `unrestored` lists the paths |
| 8 | more than one tenant on a gateway (`tenant_conflict`) |
| 9 | pin missing or not matching the library |
| 10 | invalid input, including `approval_required`, `approval_has_client_data`, `approval_has_answer_value` |
| 11 | skill missing or invalid, including `client_data_in_skill`, `skills_not_loaded`, `lint_failed` |
| 12 | existing `client-config.md` unreadable (left untouched) |
| 13 | question refused |
| 14 | an answer would be lost (`--discard-answer(s)` needed, after asking the client) |
| 15 | integration refused (undeclared variable, a value that looks like a secret, a key given as a value) |

## Layout

```
src/claw_skills_kit/      cli.py (commands, exit codes), template_format.py (the only module that knows the Markdown
                     layout), interview.py, questions.py, skills.py, reconcile.py + reconciler/ (hashing, host,
                     descriptor, smoke, lockfile), integrations.py, layer1.py, evidence.py
skills/skill-manager SKILL.md the agent reads, scripts/lk wrapper
library/releases/    the sample golden library: one folder per release (skills, skills.lock.json, RELEASE.md)
library/demo-releases/  2026.11.25, broken on purpose (BROKEN_ON_PURPOSE.md); only in the image on request
host/AGENTS.csk.md   rules block placed at the top of the workspace AGENTS.md
docker/              Dockerfile, compose.yml, up.sh, bootstrap.sh, apply_agents_rules.py
docs/                decisions.md, assumptions.md, spec-answers.md
tests/               one file per module, plus fake_openclaw.py
```
