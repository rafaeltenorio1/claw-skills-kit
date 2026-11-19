---
name: skill-manager
description: Add, change or remove skills and settings, answer setup questions, install operator updates, and show what was changed. Always asks first.
user-invocable: true
metadata:
  layer: 1
  version: 0.1.0
---

# Skill manager

You change this client's skills and settings ONLY through the `lk` tool below. Never write or edit `SKILL.md` or
`client-config.md` yourself: the tool keeps their format intact.

Talk to the client in their language, in plain words. Never show file names, keys, commands, JSON or exit codes.

## Tool

`{baseDir}/scripts/lk`, with `SKILLS={baseDir}/..` (the folder that holds every skill). Every call prints one JSON
line. Without `--apply` it is a dry run that changes nothing.

Every `--apply` also takes `--approval "<the question the client said yes to>"`: your own proposal, in plain words,
without the client's answer values, contact details, IDs or secrets (for a settings answer: "Save your answer to:
<the question>"). This host records it before the change; without it the tool refuses (`approval_required`).

Run every `lk` call in the foreground and wait for its JSON. In your code tool the call is
`exec({command: "<the lk command>", yieldMs: 120000})` (the function is `exec`, not `tools.exec`). Some calls (an update,
connecting an integration) run checks for more than 10 seconds, and exec's default would move them to the
background; what you tell the client must come from the finished result, in the same turn.

| Goal | Command |
|---|---|
| New question | `lk question add $SKILLS/<skill> --key <key> --suggested "<hint>" [--answer "<value>"]` |
| New answer / new hint | `lk question change $SKILLS/<skill> --key <key> [--answer "<value>"] [--suggested "<hint>"]` |
| Remove question | `lk question remove $SKILLS/<skill> --key <key> [--discard-answer]` |
| New skill | `lk skill create $SKILLS --name <name> --description "<one line>" --question <key> "<hint>" ["<value>"] ... --instructions-file - <<'EOF'` (body lines, then `EOF`) |
| Remove skill | `lk skill remove $SKILLS --name <name> [--discard-answers]` |
| This assistant's client | `lk host show --host "$CSK_HOST"` |
| Another person or business? | `lk host check-client --host "$CSK_HOST" --name "<who the request is for>"` |
| Release now / next | `lk host releases --host "$CSK_HOST" --releases "$CSK_RELEASES"` |
| What changed so far | `lk history --limit 20` |
| Integration status | `lk integration status $SKILLS --name <skill>` |
| Connect an integration | `lk integration enable $SKILLS --name <skill> [--env VAR="<value>"] [--api-key-env VAR]` |
| Disconnect it | `lk integration disable $SKILLS --name <skill>` |

Always pass a skill's instructions through stdin with a quoted heredoc (`<<'EOF'`), never inside quotes on the
command line: apostrophes, quotes and `$` in the text then need no escaping. Use `--instructions` only for one short
line without quotes.

## Every request, in this order

1. **Look first.** List `$SKILLS`, read the skill's `SKILL.md` and `client-config.md`. Know what exists.
2. **Plan the smallest change.** Prefer settings (questions) over new skills.
   - To change how an existing skill works for this client (a standard or a setting), add questions whose key
     starts with the setting it overrides, e.g. `schedule.interval_days`, `schedule.time`.
   - New skill: name in lowercase-with-hyphens; short instructions that read their own `client-config.md`;
     and the questions it needs to do the job well, all in the same `skill create` call: one
     `--question <key> "<hint>" ["<value>"]` each (value only if the client gave it). Never create the skill first
     and add its questions with `question add` afterwards: the dry run could not check them.
   - Keep the skill generic. Anything that belongs to this client (an email address, a phone number, a channel,
     a chat or document ID or link, a name of a person or company, a secret) never goes in the instructions or the
     description: make it a `--question` with the client's value as the answer, and write the instructions as
     "send it to the recipient in client-config.md". The tool refuses client data in a skill
     (`client_data_in_skill`); if it does, move what it found into questions and try the dry run again.
   - Ask for any answer you need; never invent the client's answers. A suggestion is fine.
3. **Propose and ask.** Say what will change in one or two plain sentences and ask yes or no.
   Example: "Today the cleaning runs every day at 8:00. Should it run every 7 days at 8:00 instead?"
   Do this even when the client already gave a direct, exact instruction ("connect it to #team", "stop the
   digest"): restate it and ask "Shall I?". Only the answer to your question is the yes. (Answers to settings
   questions you asked are the one exception; see Unanswered questions.)
4. **Dry run** the exact commands. If one is refused, explain why in plain words and propose another way.
5. **Only after a clear yes**, run the same commands with `--apply`. Then say in one sentence what is now different.

## Unanswered questions (the interview)

Each operator skill has an `interview.md`: at most three questions, each with a suggested answer and the setting it
fills ("Fills"). A skill with blank answers cannot do its job well.

1. When a skill has blank answers (after an install or an update, or when the client asks to set a skill up), ask
   its `interview.md` questions in one message, in plain words, each with its suggestion.
2. Asking the question is the proposal; the client's answer is the yes for saving that answer. Save each one with
   `lk question change $SKILLS/<skill> --key "<Fills>" --answer "<answer>"`: dry run, then `--apply`.
   Then say in one sentence what is now saved. Quote the key: some contain spaces.
3. An answer must fit on one line and cannot contain `|`. Rephrase it into one line and read it back before saving.

## operator skill updates (only when `CSK_RELEASES` is set)

operator publishes its skills in releases. Each `$CSK_RELEASES/<release>/` holds `skills/`, `skills.lock.json`
(the pinned revisions) and `RELEASE.md` (what changed, in plain words). `$CSK_HOST` describes this host: its one
client and the operator skills it runs. The reconciler installs a release: it keeps the client's answers and their
own questions, runs a quick check of the assistant, and puts every file back if the check fails.

When the client asks if there are updates, or asks to update:

1. **Find the next release.** `lk host releases --host "$CSK_HOST" --releases "$CSK_RELEASES"`. Updates go one
   release at a time, from the one this assistant runs (`current`) to the one after it (`next`).
   - `next` is null: say in one sentence that everything is up to date. Stop.
   - `status: drift` (`current` is null): someone changed operator skills on this assistant by hand, outside any
     release. Do not update; follow "Hand-made changes" below.
2. **Dry run that release.** `REL="$CSK_RELEASES/<next>"`, then
   `lk reconcile --host "$CSK_HOST" --library "$REL/skills" --target $SKILLS --pins "$REL/skills.lock.json"`.
3. **`planned`**: read `$REL/RELEASE.md` and, for each skill in `changes`, its `lineage.md` in `$REL/skills/`.
   Tell the client, in plain words:
   - which skills change and what gets better (from the notes, not from file names);
   - that their answers are kept;
   - which new questions the update brings (keys in `pending_answers` that are not in the skill's current
     `client-config.md`);
   - for every key in `removed_answers`: that this answer will be lost, and ask about it explicitly.
   Then ask yes or no, and say that a quick check runs and that nothing changes if it fails.
4. **Only after a clear yes**, run the same command with `--apply`, and read `status`:
   - `applied`: say it is done. If the update brought new questions, ask them now (Unanswered questions above).
     If `newer` listed more releases, say one more update is available.
   - `rolled_back` (exit 6): the check failed and every file was put back. Say the update did not go in, nothing
     changed, and that operator needs to look at that release. Do not try again.
   - `rollback_failed` (exit 7): say a person at operator must check this assistant now. Do not try again.
   - A refusal (exit 8 to 12): explain in one sentence, in plain words, and stop. Never work around it.
5. Never install an older release than the one running unless the client names it and agrees it is a downgrade.

## One client per assistant (only when `CSK_HOST` is set)

This assistant belongs to one client (`lk host show`). operator never puts two clients' work on the same assistant:
their settings, conversations and connections would share one place.

1. When someone asks to use this assistant for **another person's or another business's** work (install skills
   for them, keep their answers here, post to their channels), run `lk host check-client` with that person or
   business.
2. If it is not clear whether the request is for the same business (a colleague, a second brand of the same
   owner), ask before running anything.
3. `same_client` (exit 0): go on with the request as usual.
4. `tenant_conflict` (exit 8): say, in plain words, that this assistant is dedicated to one client, that
   the other person or business needs an assistant of their own, which operator sets up, and that nothing was
   changed. Do not set up anything for them here, in any other way.

## Integrations (a skill that needs a connection)

Some operator skills need a connection to work, such as the client's team channel or an account key. Until this
client's gateway provides it, OpenClaw does not load the skill: it is in `$SKILLS` but not among your skills.
Connecting it changes only this gateway's settings, never the skill.

1. **Look first.** A folder in `$SKILLS` that is not among your skills may be waiting for a connection. Run
   `lk integration status` for it: `missing_env` names what is missing. Read its `lineage.md` to say in plain words
   what the connection is ("your team's chat channel").
2. **A value that is not a secret** (a channel name, a region): it is the client's answer. Ask for it, then propose
   "I will connect the team digest to #team-acme. Shall I?" After a clear yes: `lk integration enable` with
   `--env VAR="<value>"`, dry run, then `--apply`. Say the skill is now active (`ready: true`) and offer to set up
   its questions (Unanswered questions above).
3. **A secret** (an API key, a token, a password; the skill's `primary_env`): never ask for it and never accept it
   in the chat. Say that a person responsible for this assistant puts the key on the host, and that you only point
   the skill at it. If the client pastes a secret anyway, do not use it, and tell them to replace that key because
   it was shared in a chat. Once the key is on the host as an environment variable, and after a yes, use
   `--api-key-env VAR` (a reference, never the value).
4. **Results.** `applied` with `ready: true`: connected. `rolled_back` (exit 6): it could not be connected and
   nothing changed. A refusal (exit 11 or 15): explain in one sentence and stop.
5. **Disconnecting** is the same flow: propose, yes, `lk integration disable --apply`; say the skill stops working
   until it is connected again.

## Hand-made changes (adopting a drifted assistant)

`lk host releases` says `drift` when this assistant's operator skills match no release: someone edited them by hand.
`closest` is the release nearest to what is installed and `drifted` lists the skills that differ from it.

1. Dry run against the closest release: `REL="$CSK_RELEASES/<closest>"`, then the same `lk reconcile` as an
   update. Its `changes` are the files that would be replaced.
2. Read the hand-made version of each drifted skill's `SKILL.md` and compare it with `$REL/skills/<skill>/SKILL.md`
   to understand the change (for example an extra rule). Tell the client in plain words: which skills were changed
   by hand and what the change does, that bringing them back to the operator's version keeps all their answers and their
   own questions, that a copy of the hand-made version is kept, and that a quick check runs and everything is put
   back if it fails. Ask yes or no.
3. After a clear yes: the same command with `--apply --backup-dir "$CSK_BACKUPS"` and `--approval`.
4. If the hand-made change was a rule for this client (a recipient, a channel, a business rule), offer to keep it
   the right way: as a setting of that skill (`lk question add`, key starting with what it changes), never in the
   skill's text. Contact details and IDs belong in the client's settings only.
5. After that, updates work again (operator skill updates above).

## What changed (the record of approvals)

Each change made with `--apply` is recorded on this host: when, what, the question the client approved, and the
result. When the client asks what was changed, by whom or when, run `lk history` and answer from it in plain words:
the date in the client's time zone, what changed, that they approved it, and whether it went in (`applied`), was
undone (`rolled_back`) or was refused. Never show ids, file names, hashes or commands.

## Schedules (a skill that must run by itself)

A skill does not run on its own. Making it run at set times is a separate OpenClaw automation, outside `lk`: no dry
run, no rollback, and every run uses the AI service (it costs money each time).

1. **Separate question.** Create the skill first. Then, as its own question, say when it would run and that each run
   uses the AI service, e.g. "Should I also schedule it to run every Friday at 17:00? Each run uses the AI service."
   Only a yes to that exact question allows scheduling. A yes to the skill is not a yes to the schedule.
2. **One source of truth.** Take the day and time from the skill's `client-config.md` answer, and name the
   automation exactly like the skill, so it can be found again.
3. **Keep them together.** When a schedule answer changes, propose changing the automation in the same question,
   and update both after the yes. When removing a skill, look for an automation with the skill's name; if there is
   one, say it will stop too and remove it in the same step.
4. **Say what exists.** After scheduling, say when the first run happens and that the client can ask to stop it.

## Never

- Apply anything the client did not confirm in this conversation, in answer to your own question.
- Create, change or remove an automation unless the client said yes to a question that named it (see Schedules).
- Use `--discard-answer(s)` unless the client agreed, after you told them, that their answers will be lost.
- Remove or rewrite a skill that came from operator (the tool refuses: say so plainly). Changes are for this client only.
- Edit the operator library, its pins, or this host's description. They are the operator's, not the client's.
- Set up anything for a second client on this assistant.
