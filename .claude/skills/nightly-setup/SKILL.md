---
name: nightly-setup
description: Set up the telescope for the night with the person outside at it. Use when they say they are going out, are at the telescope, or report the sky ("clear to the north, can see Polaris"). Runs the setup routine one step at a time, from checking what is plugged in to the first target centred.
compatibility: the telescopeyoke checkout on the computer at the telescope, with the mount's handset lead (or its SynScan Wi-Fi adapter on the router) and the camera plugged in; Ubuntu or Windows
allowed-tools: Bash(./doctor.py --offline) Bash(./ty mount status) Bash(./ty capabilities *) Bash(lsusb) Bash(./newhardware.py) Bash(./ty onboard *) Bash(./onboard.py *)
---

# Nightly setup

**What this rig has** decides the steps: `./ty onboard --no-check`
gives its kit (the camera, cooled or not, mono or colour, a filter wheel
or not, a motor focuser or not) and anything of its first setup still to
do (with the first moves not yet watched, offer the `first-night` skill's
first moves). On the owner's rig, `docs/agents/owner-rig.md`
has its devices and figures: read it.

The person is outside in the cold with their hands on the mount. The
routine is `docs/agents/setup-routine.md`: read it now if it is not
already in this session, and follow it in order, skipping a step the
rig's state shows is done tonight (say which, and why) or one the person
says to skip.

## How to talk to them

- One short line at a time, only what needs their hands or their eyes.
- Never hand them a command to type: run it yourself.
- Never ask what they have already said. Reread before asking.
- No warnings about cables, standing clear or the tube swinging.

## Before each step

1. Look first: `./newhardware.py` (or `lsusb` on Ubuntu), `./doctor.py
   --offline` and `./ty mount status` (read only). Name every device on
   the list before doing anything, as this rig's devices are known (the
   owner's: `docs/agents/owner-rig.md`); anything else is named and left
   alone. If what the person said disagrees with the list, the list is
   what is plugged in: ask that one question before acting on either.
   Never start a command for a device not on the list, or leave out one
   that is on it.
2. Dry-run what the step will do (`--dry-run`); anything that fails, fails
   now, indoors in your words, not with them waiting.
3. To see what the camera sees, `./snap.py --exposure 2` (the owner's
   rig: the gain in `docs/agents/owner-rig.md`): one frame, on the status
   page. Never `shoot.py` for a look: it starts an
   imaging run, which makes a stack and a session that then show on the
   page as work done (18 October 2026: three looks at Deneb).

## When a step moves something

A move runs at once, with no approval asked: what they ask for ("swing to
Vega"), the routine step their sky report fits, and every slew of the plan.
Dry-run it, then send it at once if the dry run passes. A suggestion for a
rig nobody has watched move yet: offer to say each move first, until they
have seen it turn the right way and stop. The safety hooks refuse what no one may do; the
project's commands refuse what is unsafe.

## The steps, in short

1. `./ty mount settime` once the handset is at its main menu, or, with
   `[mount] link = "wifi"`, once `./mount.py status` reads the adapter on
   the router (no screens; switched on at home; `sethome` and `directions`
   as `docs/agents/setup-routine.md` step 1 says), and where
   the kit says `keeper` (a cooled camera keeper.py can hold),
   `./keeper.py start` in the background at the same time: the camera
   cools slowly while the rest of the setup goes on, and stays open and
   cold for every step until the night's end. Say it is cooling only once
   `./keeper.py status` says so. A cooled camera without `keeper`: its own
   software cools it, if at all; say so. Not cooled: no keeper.
2. Ask where the sky is clear, and choose every star from the answer.
3. Only if the settime dry run says the motor check is on (`[mount]
   nudge_check`, off since 3 Nov 2026): `./ty mount nudge`, and ask whether
   they saw it tip and come back. If the screen says it moved and they say
   it did not, the motors stalled: power-cycle and back to 1. Off: straight
   to focus.
4. Focus: the `focus` skill, by motor or by hand as the rig has. It measures first (`./focus.py --check`, 15
   seconds) and says the level; it focuses only if that is soft or the
   person asks.
5. Polar alignment only if the tripod moved: the `polar-align` skill.
6. The first target: the `imaging-run` skill, or `discovery-night` when
   they ask for a patrol.

Finished when the first target is centred and running, or they stop.
