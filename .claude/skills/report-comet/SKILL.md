---
name: report-comet
description: Report a comet found by the comet hunt to the Sungrazer Project. Use when the person says to report it, send it or submit it ("send it", "report comet 1", /report-comet N) after the hunt or comet-checker has found an unexplained track.
argument-hint: TRACK-NUMBER
compatibility: Claude Code with Claude in Chrome; without a browser tool it gives the form's fields as a list to paste
allowed-tools: Bash(./sungrazer.py form *) Bash(./sungrazer.py submitted *) Bash(./ty candidates *)
---

# Report comet $ARGUMENTS

The procedure is `docs/agents/claiming.md`, "report comet N". The person
saying to send or report it is the go: fill the form at once, no questions.
The first report is the one credited.

1. Check the track against the project's reports and the Cambridge list,
   unless that was done in this session already. If it is already found,
   don't send: say which comet and who found it.
2. `./sungrazer.py form $ARGUMENTS` (1 if no number): every field as the
   form names it, the Note to Admin already under 255 characters, five
   frames from first to last, name and email from `[reporter]` in
   config.toml. Add a line of your own with `--note "..."` (it refuses a
   note that would be too long), and `--group` if it is not Kreutz.
3. Open `https://sungrazer.nrl.navy.mil/report` in a **new tab** and fill
   it from that output, field by field.
   - Frames: fill the empty row, click "Add another item", wait 2 s, then
     `find` the inputs again: the row's refs change each time, and an old
     ref writes over row 1.
   - If Save comes back with an error the page reloads: `find` every field
     again and check its value before going on.
4. The form ends with a math CAPTCHA, which an agent may not answer. Say in
   one line that it is ready: they answer the CAPTCHA and press Save. Leave
   the tab open.
5. They paste or say the report's ID (report_XX_...): `./sungrazer.py
   submitted N ID`, so each later hunt follows it (endorsements, the
   Cambridge list) and never takes it for someone else's; and a bullet with
   it in the night's notes (`~/ryanclinton.uk/notes/DATE.md`).

Never close a tab you did not open; a tab that appears during the job is
the person's.

While `contributor` in `[reporter]` is "NEW USER", the note asks the admins
to add the name. Once the name appears on the form's Contributor list, set
`contributor` to it.

With no browser tool: the output of step 2 as a list to paste.
