# The owner's rig

The skills choose their steps by what a rig has (`./ty onboard`'s `kit`).
This page is what they need to know about one rig in particular, the one
TelescopeYoke was written at: read it when working at that rig (its
`CLAUDE.local.md` says so), and never take any of it as true of another.

## What it is

A Sky-Watcher 150P on an EQ3 Pro (on its SynScan Wi-Fi adapter since 16 November 2026); the cooled mono
Altair 183M behind a 0.9 coma corrector (675 mm) and a Starlight Xpress
USB filter wheel (1 L, 2 R, 3 G, 4 B, 5 Ha, 6 SII, 7 OIII; LRGB and SHO
parfocal); a home-built motor focuser (`docs/focuser.md`); an Altair GPCAM
guide camera (`./guidecam.py`) on an Orion Deluxe Mini 50 mm guide scope
(162 mm, f/3.2: about 4.8"/px, a field of 1.7° by 1.3° full size). The 183C (colour) was its first camera.

The EQ3 Pro was serviced by Gary on 16 November 2026: the motors taken off,
all the old yellow and brown grease cleaned out, new grease put in and the
worm gears set (no thrust bearings fitted: Gary says they are not needed);
the bent south latitude bolt straightened the same evening. Gary said on
20 November that he did not work on the Dec axis that night, and that the
Dec fault is probably its gears not meshing right.
Guiding figures from before that date (Dec slack, RMS) are from the old
grease and worm settings.

From 16 November 2026 the mount is reached through its SynScan Wi-Fi
adapter on the house router (`[mount] link = "wifi"`), the handset kept in
the box as a fallback. The router's Wi-Fi is sketchy at louie-side and
fine at ralphie-side (the owner, 16 November); an extender if it has to be.

## On USB

| USB ID      | What it is                           |
|-------------|--------------------------------------|
| `0403:6015` | FTDI lead to the SynScan handset     |
| `16d0:0c77` | Altair 183C camera                   |
| `16d0:0b2a` | Altair GPCAM guide camera (`./guidecam.py`) |
| `1a86:7523` | CH340: the motor focuser             |

Name every device `lsusb` lists before doing anything; `doctor.py` does
not check the focuser, so `lsusb` is the only place it shows. Anything
else on the list is named and left alone. If what the person said
disagrees with the list ("took the focuser off" while the CH340 shows),
the list is what is plugged in: ask that one question before acting on
either (18 October 2026: the CH340 was on USB, I took "took the
autofocuser off earlier" to mean it was still off, and ran the
hand-turned aid instead of the motor).

## The camera's lead, and a jam

Since 1 November 2026 there is no hub: the RSH-ST04 kept
dropping off the laptop and has been returned to Amazon
(`docs/usb-hub.md`). The camera goes on the 3 m lead straight into a laptop
USB-A socket, where it has never dropped off USB and on 1 November kept
every 1 s frame at 5000 Mb/s. With no hub nothing can cut its power, so a
jam (no frame at all) gets software steps first, then hands: (a) a command
refused with `CAMERA_BUSY` names the process holding the camera
(`cameralock.py`); stop a stale one with a plain `kill` and wait until it is
gone; (b) a command that is retrying is recovering (`altair.py`'s `frame()`
tries again, closes and reopens, then tries twice more): let it finish; (c)
a fresh open, `./snap.py --exposure 0.01 --gain 100`; (d) only then pull the
lead and put it back. With a hub that switches each
port's power, `./camera_test.py --power-cycle` does that from the laptop,
and with `power_cycle_on_jam = true` the camera does it by itself after a
frame is lost twice; without one, the setting only says it could not
(`docs/camera-fault.md`, "The evening of 1 November 2026"). The focuser's
Nano on a laptop socket can turn the focuser inward but not lift the
drawtube outward (`docs/focuser.md`, 30 October 2026); on 1 November its
motor turned and the knob did not, so focus was by hand with the spoken aid.

## Setting up

- With the 183M, `./keeper.py start` in the background at the settime
  step: the camera cools slowly (1 °C a minute) to -5 °C while the setup
  goes on, and stays open and cold until the night's end.
- A look at what the camera sees: `./snap.py --exposure 2 --gain 1500`.
- The dew shields (from Gary, 20 November 2026) go on every night at
  setup, after the lens caps come off. They are not permanent: they come
  off at the night's end so the caps can go back on (the 150P dewed over
  about 02:00-02:50 on 20 November without one).
- The motor check (`[mount] nudge_check`) has been off since 3 November
  2026.
- No streaming on test nights: `./testmode.py on --why "..."` before any
  indoor or daytime test that takes camera frames, and `off` after
  (23 November 2026: a test video put the stream on air and sent YouTube
  alerts to the owner's phone).

## Focus

- While the CH340 is plugged in, the motor does the focusing; never the
  hand-turned aid, whatever was said earlier about taking it off.
- The motor is a NEMA 17 on a BTT TMC2209 since 18 November 2026, when it
  focused the 183M's train by itself, from rings 470 px across to HFR 1.67
  (`docs/nights/2026-11-18/focuser.md`). It lifts the drawtube, so
  `./focus.py --auto` moves it either way from wherever it is: no hand on
  the knob, no move first. A plus move is out; 4096
  half-steps is a turn of the knob, half a turn about half the travel.
- Far out (rings, no star measuring): `./focus.py --find`, a thirty-second
  of a turn a step, half a turn each way, further only while the doughnuts
  keep shrinking (from 20 November, not yet tried on the sky; that night
  focus was about 2,200 half-steps out after the focuser was worked on, and
  the old half-turn limit stopped two searches); `--auto` runs it itself.
- Focus moves as the night cools: 20 November, 190 half-steps between
  18:46 and 19:58 as the focuser went from 2.1 to 0.6 °C, the stars from
  HFR 1.96 to 6-8 (taken at first for cloud). Soft stars with clear sky:
  `./focus.py --check` before blaming the sky.
- The sweeps (`--motor`, `--measure-step`) stay refused by the guard: on
  23 October 2026 two of them, each stopped part way, left the old drive's
  drawtube about an inch from the Sharpie line. `--measure-backlash`
  (8 half-steps at a time, from focus) is allowed from 19 November 2026.
- Its 12 V lead runs with slack: pulled tight on 18 November, it may have
  held the tube back in Dec.
- A focus run's collimation line saying "off": Gary collimates it
  (`docs/collimation.md`).

## Imaging

- A picture with the 183M needs L, R, G and B of one target, about three
  hours between them: an hour or more of L and 30 to 40 minutes of each
  colour. 5 November 2026: five targets in one night gave 34 minutes of
  M33 in L and 3 to 8 minutes of the rest, and no colour.
- Stacks are made again on the desktop: `./restack.py SESSION --on desktop`.

## The night's end

- Flats with the 183M: `schedule.py end` starts the dawn sky flats itself
  after parking (cache/dawn-flats.log); never a second time. Only when
  the night ended without it, or it says they could not be started:
  `./calibrate.py flat --filters B G R L --twilight` in the background.
- The night's diary entry: written from the running notes and published
  through the inbox (`~/ryanclinton.uk/POSTING.md`) at the end of every
  night, with that night's stacks, without being asked.
- The dew shields come off and the lens caps go back on, after the dawn
  flats are done.
- What stays running, always: the status page (`ty-serve`), the stream's
  watcher (`ty-stream`), the live client (`ryanclinton-live`), the
  night-end timer (`ty-night-end.timer`) and the satellite keeper
  (`ty-satellite.timer`).

## As of 20 November 2026

- **Dec guiding, until Gary has fixed the Dec drive (job 2)**: on the
  east side Dec does not move south at all and moving north sticks then
  jumps 20-50"; on the west side neither way moved more than about 17" for 403" of
  pulses
  (20 November, on the main camera and the guide camera:
  [dec-one-way.md](../nights/2026-11-20/dec-one-way.md); 19 November:
  [dec-slack.md](../nights/2026-11-19/dec-slack.md)). How to work with it:
  - **Guide with plain `--guide`**: the kept calibration (20 November)
    says Dec answers north only, so the guider guides RA and sends Dec
    nothing. RA holds 1-2" RMS; Dec drifts 0.07-0.2"/s, so frames of
    120 s or less (round at 120 s on 19 November); re-centring between
    blocks keeps the framing.
  - **`--dec-one-way north`** guides Dec north only (held 1.4" RMS for four
    clear minutes on 20 November) but only where the natural drift is
    south (measure it: `./mount.py dectest` gives it first, or
    `./guidecam.py star`), and a 20-50" jump north takes minutes to drift
    back. East of the meridian only: on the west side Dec did not move
    either way. Not the everyday setting.
  - **`./mount.py dectest`** measures the Dec drive on the main camera:
    the drift, then 12 pulses each way with a plate solve after each
    (moves at most 2', needs a clear sky: 20 of 24 solves or more).
  - **True home set 22 November 2026** (it had been 8.0° out in Dec, 1.04°
    in RA). The findhome answers turned down before it came from about 0.3°
    of RA slack: the same places read that far apart by the way they were
    reached. findhome now reaches every place moving west, and agreed with
    itself to 0.04° over 12 places. Home by eye is only the start: the owner
    relies on the search for accuracy, so run it at setup on a clear sky
    rather than asking for the joints to be marked.
  The jobs owed are [owner-jobs.md](owner-jobs.md).
- **Latitude bolts**: the rear bolt in lowers the axis, the front bolt in
  raises it (13 October 2026); the old rear bolt rises then jerks lower.
- **Focuser**: backlash 16 and 32 half-steps at two reversals, 48 kept
  (measured 20 November, after the owner tightened the four screws holding
  the wheel to the barrel and adjusted the tension screw; 156 on 19
  November). Focus moved about 2,200 half-steps out with that work. The
  drawtube slipped about 4 half-steps a round trip on 19 November; not
  measured since the tension screw was adjusted again. `--measure-step` stays refused by the small-focus guard.
- **Guide camera**: gain 400 (`[guider] gain`, the default since
  20 November); the guide scope dews below about 2 °C, and its heater
  strip is now due 4 December. 20 November its lens was misted inside
  from the night before: the lens unscrews from the tube in its cell
  (never take the glass out of the cell), and an hour or two warm and
  open dried it. After it is refitted the guide camera came up on USB
  only at the second plugging.
- **Collimation**: 14% of the ring's radius off centre, towards the left
  of the frame (the focus run of 20 November): for Gary.
- **Stacking**: the desktop has no Python for `restack.py --on desktop`
  yet: stack on the laptop.
