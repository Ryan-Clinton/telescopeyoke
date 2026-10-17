---
name: imaging-run
description: Start, watch or switch an imaging run of one target. Use when the person asks to image or photograph an object ("image M31", "start a run"), to switch target ("switch to M33"), or after nightly-setup for the first target.
compatibility: telescopeyoke at the telescope with the mount and camera plugged in, focused
allowed-tools: Bash(./ty mount goto * --dry-run) Bash(./ty shoot * --dry-run) Bash(./ty watch-run --once) Bash(./ty session *) Bash(./ty tonight *)
---

# Imaging run

1. The target: what they asked for, or the best from `./ty tonight` in the
   part of the sky they said is clear.
2. `./ty mount goto TARGET --solve --dry-run`, then the GoTo itself, which
   is the move they asked for.
3. `./ty shoot TARGET --frames 0 --recentre 8` (dry-run first), in the
   background. Tell them it is running and they can go in.
4. Start the watch as a Monitor: `./ty watch-run`. It prints nothing while
   all is well and a line when frames stop, stop being kept, the share kept
   halves, the stars dim or come back, or the run ends. Tell the person at
   once about each line; for dimming stars, ask what the sky looks like
   before saying cloud, dew or haze.
5. While they are inside nobody is watching the mount: make no move they
   did not ask for.

## Switching target

Stop the run (`./ty run stop`), GoTo the new one at once and start its
run; restack the old one later (`./restack.py SESSION --on desktop`).
Never wait for the old run's stack first.
