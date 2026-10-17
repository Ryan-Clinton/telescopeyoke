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
3. Nothing on USB: the laptop has one dead USB-C port; the other port, or
   the lead.

**The camera has gone**

The lead or the port first (`lsusb`), then whether INDI's driver is
running (`./doctor.py --offline` says).

**A plate solve failed**

In this order: cloud (ask what the sky looks like), focus (the `focus`
skill), the exposure too short. A failed solve before focusing says
nothing about cloud.

**The stars dimmed**

Ask what the sky looks like before saying cloud, dew or haze: haze has
been called dew before. `./ty watch-run --once` says how much they dimmed.
