---
name: end-of-night
description: Wrap up a night's observing. Use when the person says they are packing up, done for the night, or going to bed. Never from the time alone; the run stops itself at dawn.
compatibility: telescopeyoke on the computer at the telescope; the desktop reachable by ssh for the restack
allowed-tools: Bash(./ty onboard *) Bash(./ty session *) Bash(./ty watch-run --once) Bash(./ty status *)
---

# End of the night

What runs here depends on the rig (`./ty onboard --no-check`: a cooled
camera, filters) and on what the person has set up round it; on the
owner's rig, `docs/agents/owner-rig.md` ("The night's end") has its
services and flats.

Only on the person's word. The imaging run stops at its own limits
(dawn, the target too low); this skill tidies up after it.

1. `./ty session` and `./ty watch-run --once`: is a run still going?
   If so, and they said they are done, `./ty run stop` (it finishes the
   run and makes its picture).
1b. Leave nothing running for the night: stop my own background loops
   and Monitors first (TaskStop each; a loop would start its watcher
   again), then `./schedule.py tidy` (the guider by its stop order, then
   the sky, rain and run watches and the mount probe). The camera keeper
   of a cooled camera is let go by the warm-up (`./keeper.py stop`, or
   `schedule.py end`). Services the person installed to run always (the
   owner's are in `docs/agents/owner-rig.md`) stay.
2. Park by `./schedule.py end`, without being asked, once they say they
   are done: it parks, starts the dawn flats and warms the camera. Not
   `./mount.py home` alone: the night-end timer then finds the mount home
   and takes no flats. The one exception is a night whose optics are known
   to be spoiled (dew seen or measured: stars many times their usual size
   at a focus that was sharp), when flats would not match the frames: then
   `./mount.py home` and `./keeper.py stop`, and say why.
3. Where the person stacks on another computer (the owner: the desktop),
   `./restack.py SESSION --on HOST` for each session tonight (SESSION is
   the folder, `frames/OBJECT/DATE-TIME`), and where the other computer
   cannot (unreachable, or no Python with astropy there), `./restack.py
   SESSION` here instead, never left undone (20 November 2026: the desktop
   had no Python, nothing was stacked until the person asked), in the
   background.
4. `./patrol.py --sweep` for any field with a reference.
4b. `./clouds.py --scores 1 --keep`: the night's cloud and rain forecasts
   against what was seen, kept dated in cache/sky_scores/ with the scoring
   code's commit.
5. One line on what the night got: frames kept, total time, and anything
   the patrol found. The full summary is `morning-summary`, tomorrow.
6. Flats for a camera with matched calibration (the owner's 183M):
   `schedule.py end` starts the dawn sky flats itself after parking
   (cache/dawn-flats.log): never start them a second time. Only when the
   night was ended without `schedule.py end`, or its message says the flats
   could not be started, start them by hand:
   `./calibrate.py flat --filters FILTERS --twilight` in the background,
   with the filters the night used. Never skip them for dew no one has seen or cloud: an
   overcast dawn makes good flats. Tell the person in one line to leave the
   camera, wheel and focus alone until they are done, and if they pack up
   first, the flats are lost: say so before, not after.
6b. On the owner's rig, bring "Pictures in progress" in
   `docs/agents/owner-jobs.md` up to date: each target's stacked minutes
   by filter and what it needs next. Commit and push it.
7. The diary, where the person keeps one (`CLAUDE.local.md` says where):
   write the night's titled entry from its running notes and post it,
   without being asked, before this routine counts as finished. Do it
   however the night ended, parked early or flats cancelled included, and
   check the page is live. On the owner's rig the notes are
   `~/ryanclinton.uk/notes/DATE.md` and posting is
   `~/ryanclinton.uk/POSTING.md`.
