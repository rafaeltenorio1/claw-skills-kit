# Design decisions

Each entry: what was decided, why, and what was set aside. "(Rafael)" marks a choice he made between options.
Assumptions and observed OpenClaw behaviour are in `assumptions.md`.

## Toolkit

**D1. A stdlib-only Python CLI: one JSON object on stdout, a documented exit code.** The spec's operators are agents at
a shell, so every outcome must be machine-readable and never need a prompt. No third-party runtime dependency.

**D2. Only `template_format.py` knows the Markdown layout, and only the Value column is ever written.** Every other
byte of `client-config.md` stays identical, so a diff of a client's file shows exactly the answers that changed.
Rewriting the tables was set aside: it would reformat what the client sees.

**D3. A skill's revision is a content hash that excludes `client-config.md`.** Pins in `skills.lock.json` stay valid
while a client answers or adds questions. A git commit as the revision is not used yet (see `assumptions.md`).

**D4. The reconciler refuses before writing, is a dry run by default, and restores verified by read-back.** Every
refusal (tenant, pins, library, unreadable config, template) happens before the first write. On a failed check every
touched file is put back and read again: `rolled_back` only if they match, otherwise `rollback_failed` with the paths.

**D5. Answers travel by key; blank answers never block an install and are never invented.** A template change keeps
answers whose key still exists, reports removed ones by key (`removed_answers`) and blank ones as `pending_answers`.
Values come from the client (interview) or from the host, never from the toolkit or the agent.

**D6. Reports never contain answer values or secrets.** Paths, hashes, keys and variable names only. This is why the
reconciler's output is a list of changes with hashes rather than a text diff (see README, gaps).

## Changes by conversation

**D7. Per-instance by default (Rafael).** A client's request changes their gateway only. A golden question can only get
a new answer per instance; changing a golden skill for everyone is a separate, operator side release.

**D8. Instance-only questions are extra rows in the same `## Client answers` table, marked `Instance` (Rafael).**
`reconcile` keeps them (row and answer); if the golden template later adopts the key, the answer moves to the golden
row. An overlay file was set aside: two files to keep in step on every host.

**D9. The agent never edits Markdown itself; it calls deterministic commands.** `question add|change|remove`,
`skill create|remove`, `integration`, `reconcile`. The agent chooses the operation and fills the fields; the format
is guarded by code, not by the model.

**D10. `skill create` takes its questions in the same call, and the body from stdin.** One dry run checks the whole
change and one `--apply` writes it with rollback; a heredoc avoids shell quoting (an apostrophe broke the first try).

**D11. Nothing changes without a yes to a plain-language question, even after a direct instruction (Rafael).** The
agent restates the change and asks "Shall I?"; only the answer to that question counts. The one exception is the
answer to a settings question the agent asked. The rule lives in a block at the top of the workspace `AGENTS.md`,
because the agent does not always load `skill-manager` (OpenClaw's default `AGENTS.md` says "Do freely" and
"Automations - Be Proactive").

**D12. Schedules are a separate yes that states the cost; a plain reminder may be just an automation (Rafael).** Each
automated run uses the AI service. A schedule takes its time from the skill's settings and the skill's name.

**D13. Secrets never go through the chat.** The agent never asks for a key and refuses one that is pasted, asking for
it to be replaced. Integrations store keys only as references (`{source: env, provider: default, id: VAR}`).

## Library and updates

**D14. A sample library with releases, each with its pins and plain-language notes.** Skills follow the spec's
template (`SKILL.md` sections, `client-config.template.md`, `interview.md` with at most three questions,
`lineage.md`). The agent explains an update from `RELEASE.md` and `lineage.md`, not from file names.

**D15. Updates go one release at a time, from the release the host runs.** `host releases` finds the current release by
comparing installed revisions with each release's pins. Jumping to the newest was set aside: it hides the
intermediate notes and makes a broken release harder to locate.

**D16. A host that matches no release has drifted, and is adopted only after a yes, with a backup.** The closest
release is applied, answers are kept, and every file that will be replaced is first copied to a dated backup. A
hand-made client rule is offered back as a setting, never as skill text.

**D17. A smoke check that OpenClaw actually loaded the managed skills (`host verify-skills`).** On 2026.11.3 a skill
OpenClaw cannot read disappears from its inventory while `config validate` and `skills list` still exit 0, so those
two alone would accept a broken release. The check forces a rescan first (see `assumptions.md`, O2).

**D18. The rollback demo release is opt-in.** `library/demo-releases/2026.11.25` is broken on purpose and only enters
the image with `CSK_DEMO_ROLLBACK=1`, so an ordinary "any updates?" never offers it by accident.

## Integrations, tenants, evidence, Layer 1

**D19. Integrations orchestrate OpenClaw's own config commands.** `integration enable` sets only variables the skill
declares in `requires.env`, refuses values that look like secrets, takes the key only as a reference, validates,
checks that the skill loads, and restores the `skills.entries.<skill>` block on failure. It never edits
`openclaw.json` by hand and never touches the skill. The snapshot is read from the config file because `config get`
redacts reference ids.

**D20. The tenant rule is shown in chat by the reconciler's own check.** `host check-client` runs `check_single_tenant`
on the host's client plus the requested one (exit 8). `reconcile` refuses a two-client descriptor on its own; the
check only makes the guarantee visible before anyone tries.

**D21. Approvals are recorded before the change and the outcome after.** With `CSK_EVIDENCE` set, `--apply` needs
`--approval`, refused if it holds contact details, secrets or the answer itself. Two fsync'ed JSON lines per change;
`lk history` merges them. Recording inside OpenClaw's own transcript was set aside: it is not structured and holds the
whole conversation.

**D22. A Layer 1 validator with the spec's list.** Emails, phone numbers, chat channels and IDs, drive links, secrets
and URL credentials, reported by kind and line only. `skill create` refuses them; `lint --golden` checks a library.

## Docker host

**D23. The Control UI in a browser is the interface (Rafael).** Served by the gateway on host loopback.

**D24. A fresh instance, the toolkit baked into the image, OpenClaw pinned (Rafael).** `ghcr.io/openclaw/openclaw:
2026.11.3-browser` (the plain image is one variable away). The image's Python is 3.11, so the toolkit runs in its own
3.14 venv. `bootstrap.sh` redoes the whole setup and is safe to run again.

**D25. Costly defaults off.** The bundled `skill-creator` (it would let the agent write skill files freely), the
30-minute heartbeat and memory dreaming are turned off; each would spend model calls.

## Repository

**D26. Merge commits, not squash, for the project's pull requests (Rafael).** The spec looks at whether the commits read
as a sequence; the small commits stay visible on `staging`.

## Open

- **The `doctor --lint` rule.** It exits 1 in Docker only because of the expected `gateway.bind: lan` warning. Options:
  a smoke check that passes when every finding is in a reviewed allowlist (by requirement id); `--severity-min error`
  (hides every warning, including new ones); or a network setup that does not need `lan`. Needs the operator's view.
- **The revision:** content hash (today) or git commit plus per-file hash.
- **Where the reconciler runs:** on the host (today) or from an operations agent over the tailnet.
