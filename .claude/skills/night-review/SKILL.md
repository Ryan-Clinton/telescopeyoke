---
name: night-review
description: Say what went wrong in a night run by someone else's observatory software (NINA, PHD2, SGP, APT, Ekos) and why, from what it saved, without touching any of it. Use when the person runs their own capture program and asks why last night went badly, where the time went, how much usable data they got, or whether guiding, focus or cloud spoiled it.
compatibility: telescopeyoke installed (Windows or Linux); the night's frames folder, and NINA's and PHD2's logs if they have them
allowed-tools: Bash(./companion.py *) Bash(python companion.py *) Bash(py -3 companion.py *)
---

# A night reviewed

`companion.py` reads what their observatory already wrote and sends nothing
to any device: their mount, camera, focuser, wheel and capture program are
never touched, so NINA and PHD2 can keep running while it reads. Read
`docs/companion.md` first: how to read its report is there.

1. **Where things are.** Ask only for what is not found. On Windows:
   NINA's frames are where its Options > Imaging > Image file path says;
   its logs are in `%LOCALAPPDATA%\NINA\Logs` (one file a session, named by
   its start); PHD2's guide logs are in `Documents\PHD2`
   (`PHD2_GuideLog_DATE.txt`). The night is the date it began.
2. `companion.py check FOLDER --phd2-log FILE`: what it can read. A file it
   cannot read is said with why; for NINA's LZ4 or Zstandard XISF, tell
   them the file type to choose (the check says it).
3. `companion.py report FOLDER --phd2-log FILE --nina-log FILE --night
   DATE`, in the background for a big night (about a second a frame). No
   frames to hand: `report --nina-log FILE --phd2-log FILE --night DATE`
   gives the night from the logs alone, judging the saved frames by NINA's
   own star detection where its log has it. Logs from a computer in
   another zone: `--tz ZONE`.
4. Tell them in a few lines, in this order: how much was measured and how
   much is acceptable by its own best frames, setup by setup; the biggest
   losses with their likely causes; the gaps, explained (by NINA's or
   PHD2's log) or not; anything PHD2 said that its own steps did not bear
   out. Keep **measured** apart from **likely**, as the report does: it
   judges each setup against that night's best, never against a standard,
   and a "likely" is an inference.
5. Advice only where the report points to it, and only as a question to
   look at: a soft stretch with the focuser colder is a focus question; a
   trailed stretch with guiding normal is the mount or the wind; long
   autofocus or centring times are their sequence's settings. Never
   suggest changing their software's settings as a fact, and never offer
   to change anything on their rig: this only reads.
