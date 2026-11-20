# 20 November 2026: the Dec drive measured on the main camera, and Dec guided north only

[All docs](../../README.md) · [Validation](../../validation.md) · [The 19-20 November Dec slack](../2026-11-19/dec-slack.md) · [Jobs owed](../../agents/owner-jobs.md)

The EQ3 Pro on its Wi-Fi adapter; the 183M (0.73"/px) and the guide camera
(binned, 9.55"/px, on the Orion Mini 50 mm). Times UT. The owner had
changed the balance since 19 November; Gary said the same day that the
16 November service did not touch the Dec axis, and that the fault is
probably its gears not meshing right. His suggestion for the guiding:
measure which way Dec drifts and guide Dec one way only, against the
drift, so the motor never turns back into the slack.

**The short answer: Dec does not move south at all, and moving north it
sticks and then jumps 20 to 30". Guiding Dec north only held it at 1.4"
RMS for four clear minutes, but cannot undo a jump north: only the
natural drift south (about 0.1"/s) brings the star back, which takes
minutes. RA guided at 1.1 to 2.4" RMS throughout. This is mechanical
(job 2), not something the guider can cure.**

## The main-camera Dec test (`./mount.py dectest`, new tonight)

Two plate solves 30 s apart for the natural drift, then 12 Dec pulses of
1.5 s at 7.5"/s (about 11.2" each) through the motor board one way, then
12 the other, a main-camera plate solve after each, the drift taken off.
Written because the guide scope's lens had misted inside (it was dried
indoors, its lens unscrewed from the tube).

| Time | Where | Guide scope | Natural Dec drift | Motor plus (north) | Motor minus (south) |
|---|---|---|---|---|---|
| ~19:45 | NGC 869, east, Dec +57 | off the tube | +0.04"/s | slack 2 pulses, then about +10" a pulse (9 of 11) | 12 pulses, 134" sent: moved about +1" net, nothing |
| ~20:12 | M31, east, Dec +45 | back on | -0.07"/s | slack 4 pulses (about 45"), then +13" a pulse (8 of 12) | 12 pulses, 134" sent: never moved more than half a pulse |

An earlier run is left out: a cloudy retry had been refused, and a refused
command stops the motors, so it ran untracked (fixed: the test turns
tracking on first). The same test on the west side, where the motor's
north and south change places, was cut off by cloud.

## The guider's calibration, 20:21, M31, east of the pier

West 11 steps, 0.59 px/s; east 0.53 px/s; the Dec slack taken up after
17 north steps of 1.5 s (about 25 s); north 11 steps at 0.84 px/s
(8.0"/s); south 11 steps moved the star in none. Before tonight such a
calibration kept RA alone. Now it also keeps the north it measured
(`dec_works: "north"`, commit 9ad6f2b), and `guide --dec-one-way north`
guides Dec north only; without `--dec-one-way`, Dec stays unguided.

## Three 10-minute guided runs, Dec north only (RMS in 2-minute pieces)

| Run | Minutes | RA RMS | Dec RMS | Dec mean | What happened |
|---|---|---|---|---|---|
| 1, ~20:25 | 0-4 | 1.6" | 3.7-4.2" | -3.8 to -3.0" | pulling in from about 4" south after calibration |
| | 4-8 | 1.4-1.7" | **1.4-1.5"** | -0.9" | Dec held as well as RA |
| | 8-10 | 2.5-2.8" | 4.5-6.4" | +3.9" | the star lost 5 times (thin cloud); Dec swung to +11" north and came back slowly |
| 2, 21:02 | 0-2 | 2.1" | 29" | +17" (peak +49") | north pulses piled up, then Dec jumped north (5.3 guide pixels, about 25", in one frame) |
| | 2-8 | 1.4-1.7" | 21-39" | +39" falling to +21" | no south pulses: only the drift brings it back |
| | 8-10 | 1.1" | 3.3" | +3" | back near the target |
| 3, ~21:15, with `--dec-stuck 3` | 0-2 | 1.9" | 6.4" | -1.6" | |
| | 2-4 | 1.9" | 16.6" | +16" | a jump north |
| | 6-8 | 1.8" | 15.3" | -1.4" (peak 31") | north pulses, then another jump |
| | 8-10 | 1.8" | 19-26" | +19 to +26" | waiting on the drift |

`--dec-stuck 3` (hold Dec pulses once 3 s have gone out with the star not
moving) did not stop the jumps: they come after the star has started to
move, not while it is stuck.

## What it shows

- **South: the Dec drive does not move the tube at all**, on the main
  camera as on the guide camera, with the guide scope on or off. Measured:
  134" of pulses, under 2" of movement, twice.
- **North: it sticks, then jumps.** A run of north pulses moves little,
  then 20-30" goes at once; between jumps it can follow at the full rate
  (run 1, minutes 4-8). Measured on the guide camera; the main-camera test
  saw the same uneven steps (+20", +10", +15", +9" for 11.2" sent).
- **The balance change did not cure it**: the failing way was south with
  the guide scope off and on. Whether the failing way follows the motor
  or the sky (the west-side test) is not yet known.
- **One-way guiding** works where Dec follows smoothly and fails where it
  jumps. A larger natural drift south (the polar axis set a little off on
  purpose) would bring the star back faster after a jump; it would not
  stop the jumps. Not tried.
- **For Gary (job 2)**: the worm's mesh with the Dec wheel first. Moving
  south the motor turns and the tube does not; moving north it sticks
  and releases.

## What changed

- `mount.py dectest` (485dc4a, 57a8585): the Dec drive on the main camera.
- `guider.py` (9ad6f2b): a calibration that finds Dec answers north only
  keeps north, and `guide --dec-one-way north` guides it.
