---
name: imaging-run
description: Start, watch or switch an imaging run of one target. Use when the person asks to image or photograph an object ("image M31", "start a run"), to switch target ("switch to M33"), or after nightly-setup for the first target.
compatibility: telescopeyoke at the telescope with the mount and camera plugged in, focused
allowed-tools: Bash(./ty mount goto * --dry-run) Bash(./ty shoot * --dry-run) Bash(./ty watch-run --once) Bash(./ty session *) Bash(./ty tonight *) Bash(./clouds.py) Bash(./clouds.py *)
---

# Imaging run

1. The target: what they asked for, or the best from `./ty tonight` in the
   part of the sky they said is clear.
2. `./ty mount goto TARGET --solve --dry-run`, then the GoTo itself, which
   with no approval asked.
3. `./ty shoot TARGET --frames 0 --recentre 8` (dry-run first), in the
   background. Tell them it is running and they can go in.
4. Start the watch as a Monitor: `./ty watch-run`. It prints nothing while
   all is well and a line when frames stop, stop being kept, the share kept
   halves, the stars dim or come back, or the run ends. Tell the person at
   once about each line; for dimming stars, the satellite and the airports
   first (the watch's line gives both and whether they agree; `./clouds.py`
   for the full reports; the airport upwind, by its wind, says what is
   coming), then ask what the sky looks like before saying haze or dew.
5. While they are inside nobody is watching the mount: make no move they
   did not ask for.

## Planning a picture with the mono camera

A picture needs L, R, G and B of one target, about three hours between
them: an hour or more of L and 30 to 40 minutes of each colour. Asked for
several targets in one night, give each its minutes and say what that
gets: under about an hour in all, a grey snapshot, not a picture.
5 November 2026: five targets in one night gave 34 minutes of M33 in L and
3 to 8 minutes of the rest, and no colour. `schedule.py end` reports each
block's minutes kept against those planned.

The filters: `./ty target TARGET --json` gives `palette` when Gary Imm's
Compendium is here (`./compendium.py status`): the palette he gives for that
kind of nebula (SHO, HOO, Ha+RGB or LRGB) and what his class says of its
light. Offer it as his, with its filters as `--blocks`
(`Ha:N,OIII:N` for HOO), and the person chooses; with no palette, LRGB as
above. It is advice: nothing picks a filter from it on its own.

## Switching target

Stop the run (`./ty run stop`), GoTo the new one at once and start its
run; restack the old one later (`./restack.py SESSION --on desktop`).
Never wait for the old run's stack first.
