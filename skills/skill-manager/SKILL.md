---
name: skill-manager
description: Add, change or remove this client's skills and their settings questions when the client asks in plain words ("create a skill for X", "make it weekly", "stop doing Y"). Always confirms first.
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

| Goal | Command |
|---|---|
| New question | `lk question add $SKILLS/<skill> --key <key> --suggested "<hint>" [--answer "<value>"]` |
| New answer / new hint | `lk question change $SKILLS/<skill> --key <key> [--answer "<value>"] [--suggested "<hint>"]` |
| Remove question | `lk question remove $SKILLS/<skill> --key <key> [--discard-answer]` |
| New skill | `lk skill create $SKILLS --name <name> --description "<one line>" --question <key> "<hint>" ["<value>"] ... --instructions-file - <<'EOF'` (body lines, then `EOF`) |
| Remove skill | `lk skill remove $SKILLS --name <name> [--discard-answers]` |

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
   - Ask for any answer you need; never invent the client's answers. A suggestion is fine.
3. **Propose and ask.** Say what will change in one or two plain sentences and ask yes or no.
   Example: "Today the cleaning runs every day at 8:00. Should it run every 7 days at 8:00 instead?"
4. **Dry run** the exact commands. If one is refused, explain why in plain words and propose another way.
5. **Only after a clear yes**, run the same commands with `--apply`. Then say in one sentence what is now different.

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

- Apply anything the client did not confirm in this conversation.
- Create, change or remove an automation unless the client said yes to a question that named it (see Schedules).
- Use `--discard-answer(s)` unless the client agreed, after you told them, that their answers will be lost.
- Remove or rewrite a skill that came from operator (the tool refuses: say so plainly). Changes are for this client only.
