---
name: team-digest
description: Post a short end-of-day digest of what was decided and what is still open to the client's team channel.
user-invocable: true
metadata:
  layer: 1
  version: 0.1.0
  openclaw:
    requires:
      env: [TEAM_DIGEST_CHANNEL]
    os: [linux]
---

# Team digest

## Job
At the end of the working day, write one short digest of what was decided and what is still open, and post it to
the client's team channel. This skill only summarises what this assistant already worked on; it does not read email
or calendars.

## Before you start
1. Load `client-config.md` from this skill's folder. If a client answer is blank, ask the questions in
   `interview.md` and stop.
2. The team channel is the one named in `TEAM_DIGEST_CHANNEL`. This skill only loads once the client has connected
   it, so never ask for it in the chat.

## Procedure
1. Collect today's decisions and open items from this assistant's work (for example meeting-notes summaries).
2. Keep only what the readers chosen by the client need (`digest_audience`).
3. Write the digest with the sections the client chose (`digest_sections`).

## Rules
- Follow the standards in `client-config.md`; they apply without asking.
- Never post anything the client has not seen during the day. Never print secrets.

## Output
One message to the team channel. If this assistant cannot post there yet, show the digest in this chat and say
which channel it is meant for.

## Failure handling
If posting fails, keep the digest in this chat and say in one sentence that it was not posted and why.
