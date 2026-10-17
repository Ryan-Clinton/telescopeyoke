---
name: nightly-setup
description: Set up the telescope for the night with the person outside at it. Use when they say they are going out, are at the telescope, or report the sky ("clear to the north, can see Polaris"). Runs the setup routine one step at a time, from checking what is plugged in to the first target centred.
compatibility: the telescopeyoke checkout on the computer at the telescope, with the mount's handset lead and the camera plugged in; Ubuntu or Windows
allowed-tools: Bash(./doctor.py --offline) Bash(./ty mount status) Bash(./ty capabilities *) Bash(lsusb)
---

# Nightly setup

The person is outside in the cold with their hands on the mount. The
routine is `docs/agents/setup-routine.md`: read it now if it is not
already in this session, and follow it in order, skipping only a step the
rig's state shows is done tonight (say which, and why).

## How to talk to them

- One short line at a time, only what needs their hands or their eyes.
- Never hand them a command to type: run it yourself.
- Never ask what they have already said. Reread before asking.
- No warnings about cables, standing clear or the tube swinging.

## Before each step

1. Look first: `./doctor.py --offline` and `./ty mount status` (read only;
   `lsusb` on Ubuntu). Advise from what is plugged in.
2. Dry-run what the step will do (`--dry-run`); anything that fails, fails
   now, indoors in your words, not with them waiting.

## When a step moves something

A move runs when they asked for it ("swing to Vega"), or when what they
just said they can see is the go for the routine's next step (CLAUDE.md).
Loading this skill is not a go by itself. Dry-run it, then send it at once
if the dry run passes. The safety hooks refuse what no one may do; the
project's commands refuse what is unsafe.

## The steps, in short

1. `./ty mount settime` once the handset is at its main menu.
2. Ask where the sky is clear, and choose every star from the answer.
3. `./ty mount nudge`, and ask whether they saw it tip and come back. If
   the screen says it moved and they say it did not, the motors stalled:
   power-cycle and back to 1.
4. Focus: the `focus` skill. It measures first (`./focus.py --check`, 15
   seconds) and says the level; it focuses only if that is soft or the
   person asks.
5. Polar alignment only if the tripod moved: the `polar-align` skill.
6. The first target: the `imaging-run` skill, or `discovery-night` when
   they ask for a patrol.

Finished when the first target is centred and running, or they stop.
