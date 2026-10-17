---
name: morning-summary
description: Say what last night's observing got. Use when the person asks how last night went, what we got, or for a summary of a night.
compatibility: telescopeyoke with a night's sessions under frames/
allowed-tools: Bash(./ty session *) Bash(./ty candidates *) Bash(./ty agent-report *)
---

# Morning summary

Hand the reading to the `night-analyst` agent: the night's folders are
many and long, and only its five lines are needed here. Give it the night
(the date, or "last night").

Pass on its answer as it gives it, in five lines:

1. What was taken: targets, frames kept of frames taken, total time.
2. How deep the stacks reached, against the usual for that target.
3. Candidates: new ones, and open ones seen again, with how many nights.
4. What went wrong, if anything: frames stopping, cloud, a stalled
   motor, a refused command.
5. What tonight should do: the field most overdue, a candidate to look at
   again, a measurement still missing (`./ty characterise`).

Then one line from `./ty agent-report --days 1` if the safety hooks
refused anything or a hardware command ran without the person asking.
