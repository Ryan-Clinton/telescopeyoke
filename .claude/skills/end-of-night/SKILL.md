---
name: end-of-night
description: Wrap up a night's observing. Use when the person says they are packing up, done for the night, or going to bed. Never from the time alone; the run stops itself at dawn.
compatibility: telescopeyoke on the computer at the telescope; the desktop reachable by ssh for the restack
allowed-tools: Bash(./ty session *) Bash(./ty watch-run --once) Bash(./ty status *)
---

# End of the night

Only on the person's word. The imaging run stops at its own limits
(dawn, the target too low); this skill tidies up after it.

1. `./ty session` and `./ty watch-run --once`: is a run still going?
   If so, and they said they are done, `./ty run stop` (it finishes the
   run and makes its picture).
1b. Leave nothing running for the night: stop my own background loops
   and Monitors first (TaskStop each; a loop would start its watcher
   again), then `./schedule.py tidy` (the guider by its stop order, then
   the sky, rain and run watches and the mount probe). The camera keeper
   is let go by the warm-up (`./keeper.py stop`, or `schedule.py end`).
   What stays, always: the status page (`ty-serve`), the stream's watcher
   (`ty-stream`, idle when not imaging), the live client
   (`ryanclinton-live`) and the night-end timer (`ty-night-end.timer`).
2. Park only if they ask.
3. The night's stacks on the desktop, in the background:
   `./restack.py SESSION --on desktop` for each session tonight.
4. `./patrol.py --sweep` for any field with a reference.
5. One line on what the night got: frames kept, total time, and anything
   the patrol found. The full summary is `morning-summary`, tomorrow.
6. Flats with the 183M: `schedule.py end` starts the dawn sky flats itself
   after parking (cache/dawn-flats.log). Ending by hand before dawn, start
   them the same way: `./calibrate.py flat --filters B G R L --twilight` in
   the background. Never skip them for dew no one has seen or cloud: an
   overcast dawn makes good flats. Tell the person in one line to leave the
   camera, wheel and focus alone until they are done, and if they pack up
   first, the flats are lost: say so before, not after.
