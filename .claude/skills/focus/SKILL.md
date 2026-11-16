---
name: focus
description: Check and, if needed, improve the telescope's focus, with the motor focuser where the rig has one and by hand where it does not. Use when the person says to focus, that the stars look soft or bloated, or as the focus step of nightly-setup. Measures first, says the level, and only focuses when it is worse than usual or the person asks.
compatibility: telescopeyoke at the telescope with the camera plugged in; the motor focuser (firmware/focuser) where the rig has one
allowed-tools: Bash(./focus.py --motor --dry-run) Bash(./ty mount status) Bash(./ty onboard *) Bash(./onboard.py *)
---

# Focus

**Which focuser.** `./ty onboard --no-check`, its kit line: the project's
motor focuser (`docs/focuser.md`) only where the person has said the rig
has one (`motor_focuser` true). A CH340 on USB is not one by itself: it
is the chip on many leads. Not known: ask once, and on their word
`./ty onboard --confirm motor-focuser`. On the owner's rig,
`docs/agents/owner-rig.md` ("Focus") says which it is: read it.

**Measure first, always.** Focus that was not touched since it was last
set is usually still good, and a focus run drives the drawtube well out
and back: minutes of sky, and a risk of leaving it worse if stopped part
way (17 October 2026: HFR 1.86 at the start, 3.52 after a stopped run).

1. The telescope must point at a rich star field in a part of the sky the
   person said is clear. If it does not, the GoTo to one is a move, under
   nightly-setup's rule: in setting up, the field `./polaralign.py --where`
   names, so the polar check can start from the same place.
2. `./focus.py --check`: three frames, about 15 seconds, nothing turns.
   Tell the person the number and what it is against, in one line:
   "Focus now HFR 1.86, usual 2.38: good." A rig with no usual yet: say
   the number, and that the first good focus becomes the usual.
3. **Good** (within 10% of the usual best): say so and move on. Do not
   focus unless the person asks.
4. **Soft**, or asked: with the motor focuser, the walk-in below; without
   one, the hand aid below.
5. Report the HFR it ends on. Well above the usual: suggest the cause in
   this order: cloud or haze (ask what the sky looks like), dew on the
   mirror, the field too sparse.
6. **Never stop a focus run part way.** If it must stop, say where the
   focuser is, measure with `--check`, and focus again.

Focus comes before anything that plate-solves.

## With the motor focuser: the walk-in

`./focus.py --motor --dry-run` first. Then `./focus.py --walk-in` only,
from the drawtube set by hand a touch **out** from focus (where focus
was, if it has been marked). **Never `--motor`, `--measure-step` or
`--measure-backlash`** with their 256-step, 1536-overshoot guesses: two
of them, each stopped part way, once left the drawtube about an inch out.
The method proved on 20 October 2026 is a small step out and tiny steps
in, downhill only, stopping once the stars are clearly past their best,
then one move back out to the best (`docs/focuser.md`). Nothing to
measure first. The person's word on how far out it is beats the HFR: HFR
13 can be a few tens of microns. Stars that vanish during a run mean the
focuser, not cloud.

- A walk-in that ends past its best tries one move back out and says
  whether the motor lifted the drawtube: report that line too.
- It checks the collimation on its first doughnuts: say that line once,
  and if it says "off", that the mirrors want collimating
  (`docs/collimation.md`).
- Run it with its output to a log and a Monitor on the log (never through
  `tail`, which holds every line back until the end). Say nothing per
  reading: say only a fault, or the end.
- Asked for progress: read the log's last lines and answer in one line,
  "coming in, +480, HFR 6.1, best 6.1, aim 2.3, 4 min in". Every line
  starts with its time; a frame late by 15 s says "no picture from the
  camera ... still waiting". A run that ends "the camera sent no picture
  ... it has hung" says where the focuser was left: `./camera_setup.py`,
  then `--check`. Never answer with guesses about buffering.

While the motor focuser is plugged in, never ask for a hand on the knob.

## Without one: by hand

**The spoken hand-focus aid (`./focus.py` with no option) only with the
person at the knob, and only after asking them.** Before it: `./focus.py
--check` in the filter in use, say the number against the usual, and if
it is soft or sees no stars, ask whether it is cloud. Run the aid only
when they say the sky is clear there and they are at the telescope to
turn the knob; with nobody there, or cloud, it measures nothing. A focus
left untouched does not go soft in minutes: cloud does. Judge from the
readings once they read steady, never from the first few.
15 November 2026: the aid was started unasked while cloud was passing; it
read "no star in view", then HFR 1.5 with nobody touching the knob. The
person: "if im not there to tell you if its cloud or not there is no
point in running it".

`./focus.py --field` (the aid with tones, after a GoTo to a bright star)
only when they ask for it.
