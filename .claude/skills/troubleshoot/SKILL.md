---
name: troubleshoot
description: Find out what is wrong with the telescope, mount, camera or plate solving. Use when the person says it is not moving, moved wrongly, the camera has gone, a plate solve failed, or the stars have dimmed.
compatibility: telescopeyoke on the computer at the telescope
allowed-tools: Bash(./doctor.py --offline) Bash(./ty mount status) Bash(./ty status *) Bash(./ty session *) Bash(lsusb) Bash(./ty watch-run --once)
---

# Troubleshoot

Look before asking: `lsusb` (Ubuntu), `./doctor.py --offline`, `./ty mount
status` and `./ty status` say what is plugged in and answering. Then go
through the causes these have had before, in order, and say the first one
the checks point to. Never touch `MOTION_LOCKED`: if it is there, say its
reason (`./ty capabilities`), and that only a person removes it.

**The mount moved wrongly, or not at all**

1. The handset was not past its start-up screens: it takes commands
   before it is ready and then moves wrongly. They press ENTER to its main
   menu, then `./ty mount settime`.
2. The motors stalled while the handset said they moved (6 October 2026):
   the screen says it moved, they say it did not. Power-cycle the mount,
   back to the handset's main menu.
3. Nothing on USB, and nothing in `journalctl -k`: ask which socket it is
   in before blaming the lead. The person knows which USB-C port is dead:
   never tell them.

**The camera has gone**

The lead or the port first (`lsusb`), then whether INDI's driver is
running (`./doctor.py --offline` says).

**The camera sends no frames (a jam)**

Never ask the person to unplug or touch anything until every software
step has been tried, and say what each gave:

1. Who has the camera: a command refused with `CAMERA_BUSY` names the
   process holding it. A command thought stopped may still be running:
   look for it (`ps -eo pid,args`), stop it with a plain `kill` (which
   closes the camera as Ctrl-C does) and wait until it has gone.
2. A command that is retrying is recovering: `frame()` tries again, then
   closes and opens the camera, then tries twice more. Let it finish.
3. A fresh open: `./snap.py --exposure 0.01 --gain 100`, one frame. On
   2 November 2026 this cleared a jam in 2 s after a request to unplug it
   had already been made.
4. Only then a power cut: `usbpower.py`, if a hub that switches its ports
   is in use, or the person's hands.

**A plate solve failed**

In this order: cloud (ask what the sky looks like), focus (the `focus`
skill), the exposure too short. A failed solve before focusing says
nothing about cloud.

**The stars dimmed**

Look at the satellite first: `./clouds.py` (now) or `./clouds.py --at
2026-11-05T04:30` (when the stars dimmed, UT). Cloud over the site is
cloud. Now, `./clouds.py` also gives the airports' reports: low cloud at
Derry (west, upwind) is on its way, and an airport's air at its dew point
makes dew likely here too; clear airports say nothing about high thin cloud. With the person asleep, that is the answer: never dew, which no one
has seen, and never a step skipped for it (5 November 2026: dawn flats lost
to "possible dew" while the satellite showed thin cloud all night). Awake,
ask what the sky looks like too: haze has been called dew before.
`./ty watch-run --once` says how much they dimmed.
