---
name: focus
description: Focus the telescope with its motor focuser. Use when the person says to focus, that the stars look soft or bloated, or as the focus step of nightly-setup. Checks the telescope points at a rich star field in clear sky, then runs the motor focus and reports the star size.
compatibility: telescopeyoke at the telescope with the motor focuser (firmware/focuser) and the camera plugged in
allowed-tools: Bash(./focus.py --motor --dry-run) Bash(./focus.py --report) Bash(./ty mount status)
---

# Focus

The project has a motor on the focuser (`docs/focuser.md`): nobody turns
the knob. Never ask the person for a hand on it while the motor is plugged
in; `./focus.py --field`, the hand-turned aid with tones, is only for a
telescope without the motor.

1. `./focus.py --motor --dry-run`: is the focuser plugged in and
   answering? If not, say so and stop.
2. `--motor` focuses wherever the telescope points. It needs a rich star
   field in a part of the sky the person said is clear. If it is not
   pointing at one, the GoTo to one (Deneb, or a rich field the planner
   suggests in clear sky) is a move: under nightly-setup's rule for moves.
3. When they asked for focus (or the routine's step is due), run
   `./ty focus --motor` in the background and carry on.
   - If this skill loaded only because they said the stars look soft, ask
     once, in a line: "Focus now?"
4. Report the HFR it ends on: about 2 to 2.5 is good on the 150P. If it is
   well above that, say so and suggest the cause in this order: cloud or
   haze (ask what the sky looks like), dew on the mirror, the field too
   sparse.

Focus comes before anything that plate-solves: blurred stars give no
solve, and a failed solve before focusing says nothing about cloud.
