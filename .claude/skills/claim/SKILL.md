---
name: claim
description: Prepare a claim for a telescopeyoke candidate on the Transient Name Server, filling the AT report form for the person to send. Only when the person types /claim ID.
disable-model-invocation: true
argument-hint: CANDIDATE-ID
compatibility: Claude Code with Claude in Chrome, the person logged in to the Transient Name Server themselves; without a browser tool it gives the form's fields as a list to paste
allowed-tools: Bash(./ty candidates *)
---

# Claim $ARGUMENTS

The procedure is `docs/agents/claiming.md`, "claim ID": read it now and
follow it. A report goes out under the person's name and stays on the
record: **you never press Submit.** The person does.

1. If tonight's check has not been done: `catalogue-researcher` with the
   candidate's RA, Dec and time, then `candidate-vetter` with the ID and
   those facts. Say the verdict first, in a line. If it is "bogus", or the
   researcher found it on the Transient Name Server already, stop and say
   so: the person decides whether to go on.
2. `./report.py $ARGUMENTS` for a fresh packet. Read
   `reports/$ARGUMENTS/report.json`: anything in its "Before sending" list
   (one night only, one half of the night, no last non-detection) is said
   to the person now, plainly.
3. In the browser: the person must already be logged in. Never type a
   password, and never make an account. Open the AT report form and fill
   it from `report.json`, field by field, as `claiming.md` lists. Attach
   `finding.png` if the form takes a file.
4. Stop before Submit. Say: "Filled in and checked; press Submit when you
   are happy", and name every field you were unsure of.
5. With no browser tool: give each field and its value as a list, in the
   form's order, for the person to paste.

Afterwards, when they say they have sent it: note the AT name it was given
in the session's notes and with `./candidates.py` as the person says.
