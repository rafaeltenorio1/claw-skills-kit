---
name: meeting-notes
description: Turn meeting notes pasted in the chat into a short summary and a list of action items with owners.
user-invocable: true
metadata:
  layer: 1
  version: 0.1.0
---

# Meeting notes

## Job
When the client pastes notes or a transcript from a meeting, write a short summary and the action items. This skill
works only on the text it is given. It does not join meetings, read calendars or send anything.

## Before you start
1. Load `client-config.md` from this skill's folder. If a client answer is blank, ask the questions in
   `interview.md` and stop.
2. If the client did not paste any notes, ask for them in one sentence and stop.

## Procedure
1. Read the notes once, end to end.
2. Write the summary in the style the client chose (`summary_style`).
3. List every decision that was made, one line each.
4. List the action items in the format the client chose (`action_item_format`). An item with no clear owner gets
   "owner: to confirm"; never guess a name.

## Rules
- Follow the standards in `client-config.md`; they apply without asking.
- Use only what is in the notes. Do not add facts, names or dates. Never print secrets.

## Output
Three parts, in this order: Summary, Decisions, Action items.

## Failure handling
If the notes are too short or unclear to summarise, say what is missing in one sentence and ask for it.
