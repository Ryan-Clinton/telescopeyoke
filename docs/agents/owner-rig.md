# The owner's rig

The skills choose their steps by what a rig has (`./ty onboard`'s `kit`).
This page is what they need to know about one rig in particular, the one
TelescopeYoke was written at: read it when working at that rig (its
`CLAUDE.local.md` says so), and never take any of it as true of another.

## What it is

A Sky-Watcher 150P on an EQ3 Pro with a SynScan handset; the cooled mono
Altair 183M behind a 0.9 coma corrector (675 mm) and a Starlight Xpress
USB filter wheel (1 L, 2 R, 3 G, 4 B, 5 Ha, 6 SII, 7 OIII; LRGB and SHO
parfocal); a home-built motor focuser (`docs/focuser.md`); an Altair GPCAM
guide camera (`./guidecam.py`). The 183C (colour) was its first camera.

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
- The motor check (`[mount] nudge_check`) has been off since 3 November
  2026.

## Focus

- While the CH340 is plugged in, the motor does the focusing; never the
  hand-turned aid, whatever was said earlier about taking it off.
- A walk-in starts from the drawtube set by hand a touch **out** from the
  Sharpie line on it. On 23 October 2026 two `--measure-step` and
  `--measure-backlash` runs, each stopped part way, left the drawtube
  about an inch from the line after the person had said it was a touch
  out.
- A walk-in's collimation line saying "off": Gary collimates it
  (`docs/collimation.md`).
- 10 November 2026: the focuser went to the bench, waiting for drivers;
  focus by hand until it is back.

## Imaging

- A picture with the 183M needs L, R, G and B of one target, about three
  hours between them: an hour or more of L and 30 to 40 minutes of each
  colour. 5 November 2026: five targets in one night gave 34 minutes of
  M33 in L and 3 to 8 minutes of the rest, and no colour.
- Stacks are made again on the desktop: `./restack.py SESSION --on desktop`.

## The night's end

- Flats with the 183M: `schedule.py end` starts the dawn sky flats itself
  after parking (cache/dawn-flats.log). Ending by hand before dawn:
  `./calibrate.py flat --filters B G R L --twilight` in the background.
- What stays running, always: the status page (`ty-serve`), the stream's
  watcher (`ty-stream`), the live client (`ryanclinton-live`), the
  night-end timer (`ty-night-end.timer`) and the satellite keeper
  (`ty-satellite.timer`).
