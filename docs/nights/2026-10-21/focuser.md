# 21 to 22 October 2026: the motor focuser on the sky

The focuser is the 28BYJ-48 on two coils at 30 ms a half-step, with
`./focus.py --walk-in` at 40 ms ([docs/focuser.md](../../focuser.md)). The
camera was on Altair's own library from 00:06, and it lost frames all
night ([camera-stalls.md](camera-stalls.md)).

## It still cannot lift the drawtube out

- 23:37, `--motor` (a sweep that steps out and comes back in): the person at
  the telescope felt it going further and further in. The outward moves did
  not turn the drawtube; only the inward ones did. Stopped by hand.
- 00:31, `./focuser.py move 320` (outward): HFR 2.66 before, 2.73 after, so
  it did not move.
- So every run needed the person to set the drawtube a little **out** by hand
  first. After that the motor brings it in.

## The walk-ins

| Time | Start | Best | Ended | Steps near focus |
|---|---|---|---|---|
| 00:16 | HFR 10.87 | 10.3 | stopped on a cloud | 64 |
| 00:18 | 11.16 | **2.23** at −320 | −384, 2.66 | 32 |
| 03:30 | doughnuts 24 px, then 6.53 | 2.35 at −304 | −352, 3.39 | 16, three moves past the best |
| 03:37 | 11.01 | 2.85 at −208 | −288, 4.98 | went back to 32 after one bad reading (fixed) |
| 03:42 | 9.15 | **2.31** at −160 | −184, 2.6 then a cloud | 8 |
| 04:35 | doughnuts 23 px, then 5.07 | **2.19** at −272 | −296, **2.22** | 8 |

The usual best is HFR 2.28, and the sharpest the walk-in has reached was
1.58, on 19 October. Tonight's best, 2.19, is slightly better than the usual
best, but nowhere near 1.58. Every good run took one to two minutes, and the
person only had to set it out by hand first.

## What it cannot do

- **It cannot step back onto the best.** It moves inward only, so it always
  ends past focus: by up to 64 half-steps with 32-step moves, and 24 with
  8-step moves. The last run ended on 2.22, three hundredths from its best.
  Before the fixes, one run ended on 4.98.
- **Steps finer than 8 half-steps tell nothing on a night like this.** Near
  focus, 16 half-steps changed the HFR by about 0.1 to 0.3, and one reading
  of three 1 s frames wanders by about as much with the seeing. Finer steps
  would need five or six frames at each position.
- **The person was disappointed.** It focused no tighter than they manage by
  hand with the tones, and it needed their hand anyway.

## Changed tonight in `focus.py --walk-in`

- **Doughnuts:** it starts from doughnuts, coming in 128 half-steps at a
  time until the stars measure.
- **Finer steps:** 16 half-steps within 1.5 × the usual best, and 8 within
  1.15 ×. Each move is sized by the best so far, not by the last reading.
- **Clouds and the stop:** a reading over 1.8 × the best is taken again
  before it counts, and the run stops three moves past the best.
- **Readiness:** where it ends counts as focused for the patrol's readiness
  check.
- **Logging:** every line carries the time, and a hung camera ends the run
  in one plain line.

## What would fix it

A motor that can lift the drawtube out. Then the walk-in can go past focus
and come back onto the fitted best from the same side, the way the sweep
was designed to. The choices are in [docs/focuser.md](../../focuser.md):
a NEMA 14/17 on a TMC2209, a geared 28BYJ-48, or a ZWO EAF.
