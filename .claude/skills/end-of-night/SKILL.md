---
name: end-of-night
description: Wrap up a night's observing. Use when the person says they are packing up, done for the night, or going to bed. Never from the time alone; the run stops itself at dawn.
compatibility: telescopeyoke on the computer at the telescope; the desktop reachable by ssh for the restack
allowed-tools: Bash(./ty session *) Bash(./ty watch-run --once) Bash(./ty status *)
---

# End of the night

Only on the person's word. The imaging run stops at its own limits
(dawn, the target too low); this skill tidies up after it.

1. `./ty session` and `./ty watch-run --once`: is a run still going?
   If so, and they said they are done, `./ty run stop` (it finishes the
   run and makes its picture).
2. Park only if they ask. Say once what to bring in first: the laptop if
   it is on battery, as it sleeps after 15 minutes idle and stops whatever
   is running.
3. The night's stacks on the desktop, in the background:
   `./restack.py SESSION --on desktop` for each session tonight.
4. `./patrol.py --sweep` for any field with a reference.
5. One line on what the night got: frames kept, total time, and anything
   the patrol found. The full summary is `morning-summary`, tomorrow.
