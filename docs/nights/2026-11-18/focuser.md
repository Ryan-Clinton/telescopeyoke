# 18 November 2026: the NEMA 17 focuser focuses the 150P on the sky

The first night of the NEMA 17 drive on the telescope, with the 183M, the
filter wheel and the 0.9x corrector on the drawtube: the train the
28BYJ-48 could not move. Thin, thickening cloud; the Moon 64% lit; one
bright star near Mirfak and, later, the Double Cluster and Capella.

## What was on the focuser

- 17HS4401 NEMA 17 on a BigTreeTech TMC2209 V1.3, in the black
  screw-terminal carrier, the Nano's 5V on the carrier's CN5 row
  ([the bench session](../2026-11-09/nema-bench.md)), 12 V 2 A.
- The firmware counts the old motor's half-steps, 4096 to a turn of the
  motor, coupled one to one to the focuser's knob; the driver runs at 1/64
  (12,800 microsteps a turn), 200 microsteps to every 64 half-steps.
- On the printed bracket (Printables 436129, thickened 4 mm), fitted to the
  telescope on 16-17 November.
- The 150P's focuser is a Crayford: a smooth drawtube driven by friction
  from a smooth roller, no gears. Its tension screws were set on
  17 November, with the camera vertical, so the camera's weight does not
  run the drawtube down. Gary set them; the motor then turned a few turns
  each way on the telescope.
- A plus move takes the drawtube out.

## What happened

| Time (UT) | |
|---|---|
| 20:10 | A 2 s frame on Mirfak at gain 1500 showed nothing; a spiral search of 2 s frames (steps of 55' by 38') found the star 38' north of the GoTo, as a ring about 340 px across: focus far out, and the GoTo (from a home taken at power-on, no star alignment) about half a degree off |
| 20:29, 20:39 | `./focus.py --find`, with its steps cut that evening from half a turn to a thirty-second of a turn (128 half-steps), half a turn each way at most. Its readings were 136, 142, 50, 61 px going in and 95, 62, 63, 72 going out: the star had drifted out of the frame part way, and the search took a growth for the wrong way. Fixed since (below) |
| 20:46 | The star found again, 55' east of the last spot. Measured from single 2 s frames: 470 px across at 384 half-steps in; 303 px after 768 out; 82 px after 1,024 more; 29 px after 320 more; 50 px after 256 more (past focus). Focus was therefore about 1,600 half-steps out from where the evening began, about 0.4 of a turn |
| 20:48 | `./focus.py --walk-in` from just outside focus: HFR 10.89, 8.72, 5.69 (64-step moves), 4.17, 3.16, 2.03 (32), then 8-step moves 1.98, 1.90, 1.73, 1.76, 1.72, 1.78, **1.71** at −280, 1.89, 1.93, 2.35; out 56 past the best and in 32 to it for the gears' slack, then back out 24 to the best: **HFR 1.67, and the motor lifted the drawtube** |

The usual best with this train is about HFR 1.5 (15 November, by hand);
1.67 here was through haze on one bright star.

## What it proves

- The NEMA 17 moves the 183M's train both ways on the telescope,
  including lifting it outward, which the 28BYJ-48 never could with this
  train ([4 November](../2026-11-04/183m-first-night.md)).
- The motor focuses the telescope by itself: from far out (rings 470 px
  across), by motor moves measured on the stars, to HFR 1.67, with no hand
  on the knob.
- The walk-in works unchanged on the new drive.

## Not proven yet

- The gear slack and the sweep step on the sky (`./focus.py
  --measure-backlash`, `--measure-step`): they need a clear sky and a rich
  field. On the bench, unloaded, the slack was 4 half-steps.
- `./focus.py --find` from far out on its own: tonight's run was confused
  by the star leaving the frame. It now stops when the doughnuts vanish,
  and ends at the smallest doughnuts when they shrink and then grow
  (6055f3d); untried on the sky.
- Whether the drawtube holds focus overnight with the driver off between
  moves (it held from 20:51 to the end of the night's work without a
  refocus being asked for, but nothing measured it).
- What happens at the ends of the travel. The NEMA 17 is far stronger than
  the 28BYJ-48, which stalled harmlessly; nothing drives it past half a
  turn from where a run starts (the search) or past `[focuser] travel`
  (the walk-in), but the ends themselves have not been met.

## Loose ends found and fixed the same night

- The far-focus search's steps (1a16fa0, abc666e): 2,048 half-steps a step
  was half the drawtube's whole travel on this coupling.
- The guard hook allowed the far-focus search (1a16fa0); the sweeps stay
  blocked until the step and slack are measured.
- The far-focus search ends at the smallest doughnuts and stops when the
  star leaves (6055f3d).
- The 12 V lead to the focuser was found pulled tight. Two guiding
  calibrations had failed with Dec not following the north pulses; with
  the lead unplugged the third passed. That the lead held the tube back is
  likely, not proven. It goes back in with slack.
