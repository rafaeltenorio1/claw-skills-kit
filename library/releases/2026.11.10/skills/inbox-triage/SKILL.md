---
name: inbox-triage
description: Sort new email into urgent, needs a reply, and can wait, then post one short summary. Never deletes or replies.
user-invocable: true
metadata:
  layer: 1
  version: 0.1.0
---

# Inbox triage

## Job
Read the email that arrived since the last run, sort each message into urgent, needs a reply, or can wait, and post
one short summary for the client. This skill only reads and sorts. It never deletes, archives, moves or answers email.

## Before you start
1. Load `client-config.md` from this skill's folder. If a client answer is blank, ask the questions in
   `interview.md` and stop.
2. If no mailbox is connected for this client, say so in one sentence and stop.

## Procedure
1. Collect the messages received since the last run.
2. Mark as urgent anything that matches the urgent rules in `client-config.md`.
3. Leave out what the suppression rules exclude.
4. Always list messages from the critical senders, whatever their content.
5. Write the summary: urgent first, then needs a reply, then a count of what can wait.

## Rules
- Follow the standards in `client-config.md`; they apply without asking.
- Never act on an email without the client's approval. Never print secrets.

## Output
One message: a line per urgent or needs-a-reply email (sender, subject, one-line reason), then
"N more can wait". If nothing is new, post nothing.

## Failure handling
If the mailbox cannot be read, post one line saying the triage did not run and why, in plain words.
