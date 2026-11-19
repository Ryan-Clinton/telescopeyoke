---
name: imaging-run
description: Start, watch or switch an imaging run of one target. Use when the person asks to image or photograph an object ("image M31", "start a run"), to switch target ("switch to M33"), or after nightly-setup for the first target.
compatibility: telescopeyoke at the telescope with the mount and camera plugged in, focused
allowed-tools: Bash(./ty onboard *) Bash(./ty mount goto * --dry-run) Bash(./ty shoot * --dry-run) Bash(./ty watch-run --once) Bash(./ty session *) Bash(./ty tonight *) Bash(./clouds.py) Bash(./clouds.py *)
---

# Imaging run

The kit decides the plan (`./ty onboard --no-check`): a colour camera
takes the target in one go; a mono camera with a filter wheel takes it
filter by filter (below). On the owner's rig, `docs/agents/owner-rig.md`
("Imaging") has its figures.

1. The target: what they asked for, or the best from `./ty tonight` in the
   part of the sky they said is clear.
2. `./ty mount goto TARGET --solve --dry-run`, then the GoTo itself, which
   with no approval asked.
3. The run, dry-run first (`--dry-run`: it fails if any later GoTo or
   filter change would be refused), then in the background. One of these
   shapes, which `shoot.py` keeps apart:

   | Asked for | Command |
   |---|---|
   | until cloud or dawn | `--frames 0 --recentre 8` |
   | N frames | `--frames N` |
   | M minutes | `--minutes M` (no `--frames`) |
   | N good frames | `--accepted N --minutes M` |
   | filters in turn (mono and wheel) | `--blocks Ha:90,OIII:120` (no `--frames`, `--minutes` or `--accepted`) |

   Then what they asked for and the rig has: `--guide` where the rig has a
   guider (`docs/autoguiding.md`: it calibrates itself if it must), with
   `--exposure ladder` or the length they name and `--dither N`; `--gain`
   at their camera's own setting (1500 is the owner's). Unguided, the 2 s
   default unless `--exposure auto` finds the tracking allows longer. Say
   the plan in one line (target, filters and minutes, exposure, guided or
   not, when it ends), then start it. Tell them it is running and they can
   go in.
4. Start the watch as a Monitor: `./ty watch-run`. It prints nothing while
   all is well and a line when frames stop, stop being kept, the share kept
   halves, the stars dim or come back, or the run ends. Tell the person at
   once about each line; for dimming stars, the satellite and the airports
   first (the watch's line gives both and whether they agree; `./clouds.py`
   for the full reports; the airport upwind, by its wind, says what is
   coming), then ask what the sky looks like before saying haze or dew.
5. While they are inside nobody is watching the mount: make no move they
   did not ask for.

## Planning a picture with a mono camera and filters

A picture needs every filter of its palette on one target, with time for
each: on the owner's 183M about three hours for LRGB (an hour or more of
L, 30 to 40 minutes of each colour). Asked for several targets in one
night, give each its minutes and say what that gets: too little of the
colours is a grey snapshot, not a picture (5 November 2026: five targets
in one night gave 34 minutes of M33 in L and 3 to 8 minutes of the rest,
and no colour). `schedule.py end` reports each block's minutes kept
against those planned. A colour camera has none of this: one block.

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
