---
name: first-night
description: Take someone new from a fresh telescopeyoke checkout to their first picture. Use when they ask to install it, set it up, get started, get it working with their equipment, or type /first-night. Finds what is plugged in and says what is supported before anything is installed or moved.
compatibility: a fresh telescopeyoke checkout, Python 3.11 or later, Ubuntu or Windows, the internet
allowed-tools: Bash(./doctor.py --offline*) Bash(./doctor.py --json*) Bash(./newhardware.py) Bash(./ty capabilities *) Bash(lsusb)
---

# First night

The person's guide is `docs/first-night.md`, the install `docs/setup.md`
(Windows: its "Windows" section), and what is supported `docs/hardware.md`
("What to expect of other equipment"). Read all three now. They may know
nothing about telescopes yet: say what each step is for, once, in a line,
the first time it comes up.

This is not the owner's rig. Nothing in the other skills' dated notes (a
CH340 focuser, a cooled 183M, a Sharpie line, HFR figures) is about it.

## 1. What is here (reads only, nothing moves)

`./doctor.py --offline --json` (it runs before the installer: a missing
library is an answer, not a failure), `lsusb` on Linux, and
`./newhardware.py`, which lists serial ports and SynScan Wi-Fi networks
without sending them anything. Ask what they have where it does not show:
mount and handset, telescope (aperture, focal length), camera, focuser,
filter wheel.

Then one line for each device: proven, unproven on this model, seen but
not supported, or not found, from `docs/hardware.md`. Say plainly what
cannot work yet (a Celestron mount, a ZWO camera on Windows, another
make's filter wheel or motor focuser) and offer the hardware report
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
4. The ASTAP star database (`docs/setup.md`, step 2). A download that needs
   the person (a vendor's camera SDK behind a login): give the link and
   where the files go, then carry on from that step when they are there.
5. `./doctor.py --need mount,imaging` until both are ready, plugging things
   in as it asks; `--offline` needs no network.
6. A first frame from the camera indoors (`./snap.py`), to see it works.

## 3. The first moves, beside the telescope

Before any GoTo: the person beside the mount, in daylight or at dusk, the
handset set up (`docs/agents/setup-routine.md` for a SynScan). Each move
is said first and goes only on their go: a small `./mount.py goto` dry
run, then sent; they watch which way it turns, that `./mount.py stop`
stops it, and that the tube clears the tripod. Only after they say they
want moves made without asking does the night's plan slew by itself.

## 4. First light

At night, outside: the `nightly-setup` skill's order (focus, polar
alignment, GoTo), explaining each step the first time, then `imaging-run`
on something bright and big that the planner suggests (`./ty tonight`).
Finished with their first picture.
