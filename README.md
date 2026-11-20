# claw-skills-kit

**English** | [Português](README.pt-BR.md)

A small Python toolkit for managing a library of skills on OpenClaw gateways,
and a Docker host where everything it does can be shown by simply talking to the agent.

The setting I had in mind: an operator runs one OpenClaw gateway per client. Every client gets the same reviewed skills
(Layer 1: `SKILL.md`, scripts), and each client has their own settings (Layer 2: `client-config.md`, filled from a
short interview). The operator has to install and update skills on gateways that are already running, without losing
the client's answers, and the client should be able to ask for changes in plain words.

What I built:

- **Interview runner.** Fills a skill's client settings from the client's answers and refuses blank required answers.
  In chat, the agent finds the blank questions and asks them in plain words.
- **Reconciler.** Brings a gateway that is already running to a pinned release of the skill library: keeps the
  client's answers, runs smoke checks, rolls back if they fail, and shows what changed.
- **Skill manager.** The skill the agent reads. The client asks for something in plain words; the agent proposes it,
  waits for a yes, and only then runs the toolkit's commands.

Every command runs without prompts, prints one JSON object and exits with a documented code, because in a fleet an
agent is the one running them.

## Running it

You need Docker (I used Docker Desktop on Windows with WSL2) and an env file **outside the repository** with
`OPENCLAW_GATEWAY_TOKEN` and `ANTHROPIC_API_KEY` (by default `~/.config/claw-skills-kit/openclaw-test.env`). The
values never go into the repository, the image or the generated config; OpenClaw only gets references to them.

```bash
docker/up.sh                          # build, configure and start; then open http://127.0.0.1:18790/
CSK_DEMO_ROLLBACK=1 docker/up.sh      # also add a library release I broke on purpose
CSK_DEMO_DRIFT=1 docker/up.sh         # also edit an installed skill by hand, like an old host
docker compose -f docker/compose.yml down -v   # throw the instance away
```

Without Docker: `uv run pytest -q` runs the tests, and `uv run python -m claw_skills_kit --help` lists the commands.

## What it does, and where it shows

| Feature | What you see in chat | Command behind it |
|---|---|---|
| Interview runner | the agent asks the skill's blank questions (at most three) | `fill`, `question change` |
| Install or update, keep the client's answers | "Are there any updates?" -> what changes, in plain words -> yes -> done, answers kept | `host releases`, `reconcile` |
| A failed smoke test leaves the host as it was | a broken release fails its checks and everything is put back | `reconcile` |
| `doctor --lint` and `config validate` pass at the pinned version | part of every update's checks | `host doctor` |
| A skill that needs an integration loads only once enabled | "Can I use the team digest?" -> connect the channel -> it loads, the skill is untouched | `integration` |
| Refuse two tenants on one gateway | a request for another business is refused | `host check-client` |
| No secrets in output | a pasted token is refused and the client is told to replace it | `secrets audit --check` |
| Approvals from a human, recorded | the agent asks "Shall I?" before anything; "What changed?" comes from the record | `--approval`, `history` |
| No client specifics in a skill | "a skill that emails joao@..." -> the address becomes a setting | `skill create`, `lint` |
| Patch a host that already runs | hand edits are found, explained and reverted with a backup, answers kept | `host releases`, `reconcile` |
| Pin skill, gateway and Node versions | a host on another version is refused | `reconcile` |
| The diff is the review artifact | the planned change as a text diff (settings shown by key, never by value) | `reconcile --diff` |

## What works, and how I checked it

I tested on OpenClaw 2026.11.3 in Docker. For each flow I chatted with the agent in the Control UI and then checked
the agent's transcript and the files on the host, so I am not relying on what the agent says it did.

- **Unit tests:** `uv run pytest -q` passes (407 tests). A small fake of the OpenClaw CLI covers the commands the
  toolkit calls.
- **Interview:** blank answers were found and asked; only the answer cells of the settings file changed.
- **Update:** from the first release to the second, after a yes: applied with all smoke checks passing, the client's
  answers kept, the new question asked. Running the same release again changes nothing (checked by command).
- **Rollback:** an update to the release I broke on purpose failed its checks; the skill files were byte for byte
  the same afterwards and the host stayed on the previous release.
- **doctor:** `doctor --lint` passes on the host, with one reviewed exception (below). A host description without that
  exception made the check fail and the update roll back.
- **Versions:** pins asking for another Node version were refused before anything was written.
- **Integration:** the team digest skill stayed off until its channel was connected; then it loaded, and the skill
  file never changed.
- **Tenants:** a request for another business was refused and nothing changed.
- **Approvals:** the agent asked "Shall I?" even after direct instructions; "no" changed nothing; "What changed?" was
  answered from the record of approvals.
- **Client data:** a skill asked for with an email address was created with the address as a setting only; the
  library check passes on my library and fails on the broken release, as CI would.
- **Drift:** a rule added by hand to a skill was found, shown as a diff, explained, and reverted after a yes, with the
  hand-made version kept in a backup.
- **Secrets:** a pasted (fake) token was refused without any tool call and is in no file outside the chat history.
- **Setup:** `docker/up.sh` twice in a row works and the second run changes nothing new; the key and token values are
  in no file of the gateway's state.

## What does not work, or I did not check

- **One `doctor` warning is accepted on purpose.** Inside a container the gateway has to listen on all interfaces so
  Docker can publish the port (I publish it on the host's loopback only), and `doctor` warns about that. The host
  description lists that one finding as accepted; any other finding fails the check.
- **The "Shall I?" rule is enforced by instructions**, not by OpenClaw. In this setup the agent can run shell commands
  without an approval prompt. What the toolkit enforces is that an apply needs an approval text and records it.
- **Schedules are OpenClaw automations**: the toolkit cannot dry-run or roll them back.
- **No real chat channel or mailbox is connected**, so skills that post or read email are set up but not run.
- **A secret pasted in chat stays in OpenClaw's conversation history.** That is why the agent asks for it to be
  replaced instead of just ignoring it.
- **The smoke check confirms my skills are loaded**, not that they are the only ones: OpenClaw's own skills are
  there too.
- **Rollback covers the skills folder** (and the one config block an integration touches). It is kept in memory, so
  killing the process in the middle of an apply does not roll back.
- **One host, Docker Desktop on WSL2 only.** No remote hosts, no tailnet.
- **The formats of `client-config.md`, `interview.md` and `lineage.md` are this toolkit's conventions**, not an
  OpenClaw standard.
- **The skill name rule** (`^[a-z0-9][a-z0-9-]{0,63}$`) is mine; I did not check OpenClaw's own rule.

## What I would do next

1. A model-free monitor per host with its own alert path, so a gateway that stops answering is noticed.
2. CI on the repository: the tests, the library check and a scan for key patterns.
3. Remote hosts over the tailnet, and a snapshot on disk so an interrupted apply can still roll back.
4. Pins by git revision as well as content hash.

## Commands

```bash
csk fill SKILL_DIR --answers ANSWERS.json --out OUT.md
csk lock LIBRARY --skills NAME... --out skills.lock.json [--openclaw VERSION] [--node VERSION]
csk reconcile --host HOST.json --library LIBRARY --target SKILLS_DIR --pins skills.lock.json [--diff] \
    [--apply [--approval TEXT] [--backup-dir DIR]]
csk question {add|change|remove} SKILL_DIR --key K [--suggested S] [--answer A] [--apply]
csk skill create SKILLS_DIR --name N --description D [--question KEY SUGGESTED [ANSWER]]... \
    (--instructions T | --instructions-file F|-) [--apply]
csk skill remove SKILLS_DIR --name N [--discard-answers] [--apply]
csk integration {status|enable|disable} SKILLS_DIR --name N [--env VAR=VALUE]... [--api-key-env VAR] [--apply]
csk host {show | check-client --name C | releases --releases DIR | verify-skills | doctor} --host HOST.json
csk lint [--library] SKILL_DIR...
csk history [--limit N]
```

`csk` is `uv run python -m claw_skills_kit` (or `skills/skill-manager/scripts/csk`). Anything that writes is a dry run
unless `--apply` is given. Where approvals are recorded, `--apply` also needs `--approval`. Reports carry paths,
hashes, keys and variable names, never answer values or secrets.

| Exit | Meaning |
|---|---|
| 0 | ok (read `status`: planned, applied, unchanged, ...) |
| 1 | unexpected error |
| 2 | usage error |
| 3 | invalid template |
| 4 | invalid answers file |
| 5 | missing required answers |
| 6 | a check failed, the host was restored and verified |
| 7 | restore failed (`unrestored` lists the paths) |
| 8 | more than one tenant on a gateway |
| 9 | a pin is missing or does not match (skills, OpenClaw or Node version) |
| 10 | invalid input, including a missing or unsafe approval |
| 11 | skill missing or invalid, including client data in a skill and skills not loaded |
| 12 | the existing settings file cannot be read (left untouched) |
| 13 | question refused |
| 14 | an answer would be lost (the client has to agree first) |
| 15 | integration refused |
| 16 | a host check failed (`doctor` findings) |

## Layout

```
src/claw_skills_kit/   the toolkit (cli.py has the commands and exit codes)
skills/skill-manager/  the skill the agent reads, and its csk wrapper
library/releases/      my sample skill library, one folder per release
library/demo-releases/ a release broken on purpose, only added on request
host/AGENTS.csk.md     the rules placed at the top of the workspace AGENTS.md
docker/                image, compose file, up.sh, bootstrap
docs/                  decisions.md (design decisions, English and Portuguese)
tests/
```
