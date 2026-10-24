---
name: focus
description: Check and, if needed, improve the telescope's focus with its motor focuser. Use when the person says to focus, that the stars look soft or bloated, or as the focus step of nightly-setup. Measures first, says the level, and only focuses when it is worse than usual or the person asks.
compatibility: telescopeyoke at the telescope with the motor focuser (firmware/focuser) and the camera plugged in
allowed-tools: Bash(./focus.py --motor --dry-run) Bash(./focus.py --report) Bash(./ty mount status)
---

# Focus

**Measure first, always.** Focus that was not touched since it was last
set is usually still good, and a focus run drives the drawtube well out
and back: minutes of sky, and a risk of leaving it worse if stopped part
way (17 October 2026: HFR 1.86 at the start, 3.52 after a stopped run).

0. `lsusb`, and `./focus.py --motor --dry-run`: the CH340 (`1a86:7523`)
   on the list is the motor focuser, and the motor does the focusing.
   Never the hand-turned aid while it is plugged in, whatever was said
   earlier about taking it off: ask one question if the two disagree.
1. The telescope must point at a rich star field in a part of the sky the
   person said is clear. If it does not, the GoTo to one (Vega, Deneb, or a
   field the planner suggests) is a move, under nightly-setup's rule.
2. `./focus.py --check`: three frames, about 15 seconds, nothing turns.
   Tell the person the number and what it is against, in one line:
   "Focus now HFR 1.86, usual 2.38: good."
3. **Good** (within 10% of the usual best): say so and move on. Do not
   focus unless the person asks; then `./focus.py --walk-in`.
4. **Soft**: say how soft, and focus with `./focus.py --walk-in` only,
   from the drawtube set a touch **out** from the Sharpie line by hand.
   **Never `--motor`, `--measure-step` or `--measure-backlash`** with
   their 256-step, 1536-overshoot guesses: on 23 October 2026 two of
   them, each stopped part way, left the drawtube about an inch from the
   Sharpie line after the person had said it was a touch out. The method
   proved on 20 October (two coils, 30 ms a half-step, out two turns with
   the camera on) is a small step out and tiny steps in: the walk-in.
   The person's word on how far out it is beats the HFR: HFR 13 can be a
   few tens of microns. Stars that vanish during a run mean the focuser,
   not cloud. A walk-in that ends past its best tries one move back out
   to it and says whether the motor lifted the drawtube: report that line
   too (24 October 2026: try it, don't assume it can't). It also checks
   the collimation on its first doughnuts: say that line once, and if it
   says "off", that Gary should collimate it (`docs/collimation.md`). The rest of this
   step is about the walk-in's log.
   Run it with its output to a log and a Monitor on the log
   (never through `tail`, which holds every line back until the end).
   Say nothing per reading: a Monitor event that changes nothing gets no
   reply. Say only a fault, or the end.
   Asked for a progress report: read the log's last lines and answer in
   one line from them, "coming in, +480, HFR 6.1, best 6.1, aim 2.3, 4
   min in". Every line starts with the time it was printed, and each
   stage (focuser open, camera open, measuring the start) is a line as it
   starts; a frame late by 15 s says "no picture from the camera ...
   still waiting". A run that ends "the camera sent no picture ... it has
   hung" says where the focuser was left: run `./camera_setup.py`, then
   `--check`. Never answer with guesses about buffering or what might be
   happening.
   A run sweeps nine positions through focus, three frames each, fits the
   curve and goes once to its lowest point (`docs/focuser.md`): no
   hunting, and it ends at tonight's best, not the usual. On a new night or
   after the focuser has been off, measure it first:
   `./focus.py --measure-step`, then `./focus.py --measure-backlash`, both
   from focus.
5. Report the HFR it ends on. Well above the usual: suggest the cause in
   this order: cloud or haze (ask what the sky looks like), dew on the
   mirror, the field too sparse.
6. **Never stop a focus run part way.** If it must stop, say where the
   focuser is, measure with `--check`, and focus again.

Never ask for a hand on the knob while the motor is plugged in; `./focus.py
--field`, the hand-turned aid with tones, is only for a telescope without
it, and only when `lsusb` shows no CH340 and the person has asked for it.
Focus comes before anything that plate-solves.
