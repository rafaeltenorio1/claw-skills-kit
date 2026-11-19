# Design decisions

The choices I made, why, and what I set aside. Things I had to assume are in `assumptions.md`.

## The toolkit

1. **A plain Python CLI that prints one JSON object and exits with a documented code.** The fleet is run by agents at
   a shell, so every result has to be readable by a program and nothing can wait for a prompt. Standard library only.

2. **Only one module knows the settings file's Markdown layout, and it only ever writes the answer column.** Every
   other byte of a client's `client-config.md` stays the same, so a diff of that file shows exactly what changed.

3. **A skill's revision is a hash of its files, without the client's settings file.** Clients can answer questions or
   add their own without the host looking out of date against its pins.

4. **The reconciler refuses before it writes, is a dry run by default, and checks its own rollback.** Every refusal
   (two tenants, wrong pins, wrong versions, unreadable settings) happens before the first write. If a check fails
   after writing, every file is put back and read again; it only says "rolled back" if they really match.

5. **Answers follow their question by key, and nothing invents them.** A template change keeps answers whose key still
   exists, reports removed ones by key, and lists blank ones as pending. Answers come from the client, never from the
   toolkit or the agent.

6. **Reports never contain answer values or secrets.** Only paths, hashes, keys and variable names. The review diff
   follows the same rule: skill files appear as a normal diff, the settings file only by which keys changed.

## Changes by conversation

7. **A client's request changes only their own gateway.** A operator question can get a new answer on one instance, but
   changing a golden skill for everyone is a new release on the operator's side.

8. **Questions that only one client has are extra rows in the same table, marked `Instance`.** The reconciler keeps
   them across updates. I set aside a separate overlay file because it would be one more file to keep in step on every
   host.

9. **The agent never edits Markdown by itself.** It chooses an operation and fills in the fields; small deterministic
   commands do the writing, so the file format is protected by code instead of by the model.

10. **Creating a skill takes its questions in the same command.** One dry run checks the whole change and one apply
    writes it, with rollback. Instructions go in through stdin so quotes and apostrophes don't break anything.

11. **Nothing changes without a yes to a plain question, even after a direct instruction.** The agent repeats the
    change and asks "Shall I?"; only that answer counts. The only exception is answering a settings question the
    agent just asked. I put this rule at the top of the workspace `AGENTS.md`, because the agent does not always load
    the skill manager, and OpenClaw's default `AGENTS.md` tells it to act freely and be proactive with automations.

12. **A schedule is its own yes, and the agent says it costs money.** Every automatic run uses the AI service. A
    simple reminder can be just an automation; anything with settings becomes a skill.

13. **Secrets never go through the chat.** The agent never asks for a key and refuses one that gets pasted, asking for
    it to be replaced. Integrations only store references to keys.

## Library and updates

14. **A sample library organised in releases.** Each release has the skills, their pins and short notes in plain
    words, and each skill follows the spec's template. The agent explains an update from those notes, not from file
    names.

15. **Updates go one release at a time.** The toolkit finds the release a host runs by comparing what is installed
    with each release's pins. Jumping straight to the newest would hide the notes in between and make a bad release
    harder to find.

16. **A hand-edited host is brought back only after a yes, with a backup.** It is reset to the closest release, keeps
    its answers, and the files that get replaced are copied first. If the hand edit was really a client rule, the agent
    offers to keep it as a setting instead.

17. **The smoke checks confirm the skills actually loaded.** I found that a skill OpenClaw cannot read simply
    disappears while `config validate` and `skills list` still succeed, so those two alone would accept a broken
    release.

18. **`doctor --lint` passes with a reviewed list of accepted findings.** In Docker it always warns that the gateway
    listens on all interfaces, which the container needs. Skipping the security check or dropping all warnings would
    also hide new problems, so the host description names the one finding I accept and anything else fails. Before
    installing anything, the setup runs OpenClaw's own repair (`doctor --fix`), because a fresh state has pending
    migrations that `doctor` reports.

19. **The pins also fix the OpenClaw and Node versions.** The reconciler refuses a host running other versions, so an
    upgrade is always an explicit change to the pins file.

20. **The broken release for the rollback demo is opt-in.** It only goes into the image when asked, so an ordinary
    "any updates?" never offers it by accident.

## Integrations, tenants, records, client data

21. **Integrations use OpenClaw's own config commands.** Enabling one only sets variables the skill declares, refuses
    values that look like secrets, takes a key only as a reference, and puts the config back if the skill still does
    not load. It never edits the config file by hand or touches the skill.

22. **The one-tenant rule is shown in chat through the reconciler's own check.** The agent asks the same check the
    reconciler uses; the reconciler would refuse anyway.

23. **Every applied change is recorded: the approval before, the result after.** Where recording is on, an apply
    needs an approval text, which may not contain the answer itself, contact details or secrets. The agent answers
    "what changed?" from this record. I did not use OpenClaw's chat history for this because it is not structured and
    holds the whole conversation.

24. **A check for client data in skills.** Emails, phone numbers, chat channels and IDs, document links and secrets
    are refused in a skill's text and reported by kind and line only. The same check runs over a whole library.

## The Docker host

25. **The Control UI in the browser is the interface**, served by the gateway on the host's loopback.

26. **A fresh instance with the toolkit built into the image and OpenClaw pinned.** The setup script redoes the whole
    configuration and can be run again safely. The image comes with a browser; a smaller image without it is one
    setting away.

27. **Defaults that cost model calls are off:** the bundled skill creator (it would let the agent write skill files
    freely), the 30-minute heartbeat and memory dreaming.

## The repository

28. **Pull requests are merged with merge commits.** The small commits stay visible as a sequence.

## Still open

- Whether the accepted `doctor` finding is acceptable to operator, or the network setup should change instead.
- Pins by content hash (today) or by git revision as well.
- Whether the reconciler should run on the host (today) or from an operations agent over the tailnet.
