---
name: first-night
description: Take someone new from a fresh telescopeyoke checkout to their first picture. Use when they ask to install it, set it up, get started, get it working with their equipment, or type /first-night. Finds what is plugged in and says what is supported before anything is installed or moved.
compatibility: a fresh telescopeyoke checkout, Python 3.11 or later, Ubuntu or Windows, the internet
allowed-tools: Bash(./ty onboard) Bash(./ty onboard --json*) Bash(./ty onboard --no-check*) Bash(./onboard.py) Bash(./onboard.py --json*) Bash(./onboard.py --no-check*) Bash(python onboard.py*) Bash(py -3 onboard.py*) Bash(.\ty.cmd onboard*) Bash(./doctor.py --offline*) Bash(./doctor.py --json*) Bash(./newhardware.py) Bash(./ty capabilities *) Bash(lsusb) Bash(python doctor.py --offline*) Bash(python doctor.py --json*) Bash(python newhardware.py) Bash(py -3 doctor.py --offline*) Bash(py -3 doctor.py --json*) Bash(py -3 newhardware.py)
---

# First night

The person's guide is `docs/first-night.md`, the install `docs/setup.md`
(Windows: its "Windows" section), and what is supported `docs/hardware.md`
("What to expect of other equipment"). Read all three now. They may know
nothing about telescopes yet: say what each step is for, once, in a line,
the first time it comes up.

On Windows the scripts are run through Python: `python doctor.py ...` (or
`py -3 doctor.py ...`) wherever this says `./doctor.py ...`, and `ty` is
`ty.cmd` (`.\ty.cmd onboard`, or `python onboard.py`).

This is not the owner's rig: `docs/agents/owner-rig.md` is not about it.

**What they want first.** Ask, and aim for the smallest success that fits
what they have: no telescope yet, the demo (`./app.py --demo`); a camera
that works but a mount TelescopeYoke cannot drive, a frame indoors and a
plain line on what the mount needs (`docs/mounts.md`), with the hardware
report offered; the whole rig supported, the steps below. Polar surveys,
home calibration, the motor focuser and the discovery programmes come
later, if ever.

**Where it got to.** Start with `./ty onboard` (it runs before the
installer too): each step of the first setup, how it is known, and the
next. A setup broken off on another evening carries on from there, with
nothing done again and nothing taken as done. What works now (installed,
the mount connected, imaging ready) is checked each time; what was done
once (a frame, a picture) counts only for the camera and light path in
use. When the person says something no command can see, keep their word:
`./ty onboard --confirm telescope` or `camera` (those settings are theirs),
`frame`, `moves`, `first-light`, or `motor-focuser` / `manual-focuser`.
Only on their word, never on your own judgement.

## 1. What is here (reads only, nothing moves)

`./doctor.py --offline --json` (it runs before the installer: a missing
library is an answer, not a failure) and `./newhardware.py`, which lists
the serial ports, SynScan Wi-Fi networks and the USB cameras, wheels and
adapters it knows (one line each, so two of a kind show as two), each with
what TelescopeYoke can do with it, without sending anything to any of
them. A SynScan network it lists is one in reach or joined, not one that
has answered; and an empty list where the system's Wi-Fi tools are missing
proves nothing. A serial
adapter (FTDI, Prolific, CH340) says nothing about what is behind it. Ask what they have where it does not show:
mount and handset, telescope (aperture, focal length), camera, focuser,
filter wheel. Unsure of a model or a figure: a photo of its label helps
(a tube's label usually reads like "D=150mm F=750mm"; a camera's model is
on its body).

Then, as a suggestion, one line for each device from `docs/hardware.md`:
proven, unproven on this model, experimental through its ASCOM driver (Alpaca:
another maker's mount, camera, filter wheel or focuser, tried only on ASCOM's
simulator so far), seen but not supported, or not found. Say plainly which is
which: an Alpaca route is there to try with its driver, never proven on that
device; and offer the hardware report
(`./doctor.py --report`) or the Mount support form (`./newhardware.py`
fills it in, the person sends it) instead of a night of trying. Never
send a device a question unless the person names its port and agrees
(`./doctor.py --probe PORT` only reads).

## 2. Install, indoors

1. The installer: `./install.sh` on Ubuntu, `install.ps1` on Windows. Say
   first what it changes outside the folder (packages, device rules,
   the serial group).
2. Their site in `config.toml`: ask for their latitude and longitude, or
   the nearest town, and say it stays on this computer and out of git.
   Never guess it; `mount.py` refuses to move on the example site.
3. Their telescope and camera in `config.toml` (focal length, the camera
   and its sensor): the example's 150P and Altair 183C are one person's
   kit, not defaults.
4. The ASTAP star database (`docs/setup.md`, step 2), once they want the
   sky: a camera alone does not need it. A download that needs
   the person (a vendor's camera SDK behind a login): give the link and
   where the files go, then carry on from that step when they are there.
5. `./doctor.py --need` what their aim needs, until it is ready, plugging
   things in as it asks (`--offline` needs no network): `camera` for a
   frame alone (no plate solver or star database needed); `imaging` for
   the sky; `mount,imaging` to go on to the moves; `goto` before the
   first GoTo. A mount TelescopeYoke cannot drive is never asked for.
6. A first frame from the camera indoors (`./snap.py`), to see it works;
   once they have seen it, `--confirm frame`.

## 3. The first moves, beside the telescope

A suggested order for a mount nobody has watched move yet, with the
person beside it, the mount at home (counterweight down, tube to the pole)
and the handset set up (`docs/agents/setup-routine.md` for a SynScan);
offer it, and let them choose:

1. `./mount.py nudge` with a handset (a few degrees on Dec and back), or
   `./mount.py directions` without one (they say which way it turned):
   the right mount answers, and it turns the way it should.
2. Stopping: Ctrl+C in the terminal running a move (or interrupting the
   command in Claude Code) stops the motors before the command ends, on
   Linux. A second `./mount.py stop` from another window works on Linux
   only; on Windows the running command holds the port, so Ctrl+C there,
   or the mount's power switch.
3. Then one GoTo to something high and near the meridian, watched, and
   `./mount.py home`: the tube clears the tripod both ways.
4. A suggestion: before an unwatched night, one GoTo low in the south
   (25° up) and one near the zenith, watched. The limits in `mount.py`
   (20° up, 7.5 h from the meridian) were measured clear on one rig; on
   another, the camera end can reach the RA motor or the mirror end a
   leg (the owner's, 17 November 2026, before the tube was moved in
   its rings). Again after the tube or the camera train is moved.

Say each result in a line. Once they say it turned the right ways and
stopped, `./ty onboard --confirm moves`.

## 4. First light

At night, outside: the `nightly-setup` skill's order (focus, polar
alignment, GoTo), explaining each step the first time, then `imaging-run`
on something bright and big that the planner suggests (`./ty tonight`).
Finished with their first picture (`--confirm first-light` if it was not
made by an imaging run here).
