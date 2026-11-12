# Mount probe, stage 1: 11 November 2026

`./mountprobe.py` at the Soul Nebula (IC 1848), Dec +58.9, east of the
pier, about 64° up, mount tracking with no guide pulses, 8 minutes
from 21:02. Raw tracks: frames/guide/probe-20261111-211010.json.
An earlier try at 20:42 was clouded out after 2 minutes (10 guide
points, 2 solves) and is not used.

121 guide-camera points (2 s), 15 main-camera plate solves (L, 2 s).

| | main camera | guide camera |
|---|---|---|
| north drift | +25.5"/min | +27.9"/min |
| west drift | +13.1"/min | +13.9"/min (read -13.9", see below) |
| scatter north / west | 0.6" / 5.1" | 1.0" / 4.6" |

- The mount drifts about 26"/min north there. A polar alignment error of
  about 1.7° gives up to 27"/min, so this is the polar alignment, not
  slack. One-way Dec guiding there pushes south.
- The guide camera's RA came out the same size as the main camera's but
  the opposite way, which read as 215" of RA flex. The ST4 "west" pin
  moves the pointing east as the plate solves see it, so the probe now
  takes the guide camera's sign on each axis from the run itself (`axis_sign`).
  Guiding is not affected: it uses the measured pulse directions, not
  their names.
- With that, the two tracks part by 6.4" west (under one guide pixel,
  9.55") and 19.5" north (about two guide pixels) over the run. The
  north parting is a flex candidate only: it counts once a second run
  repeats it (docs/mount-probe.md).

## Second run: IC 405, west of the pier, 12 November 04:30

Dec +31.7 (the sky's: the handset, set again by eye at 04:22, was 3.4°
out), about 60° up, 8 minutes. Raw tracks: the newest
frames/guide/probe-20261112-*.json.

| | main camera | guide camera (turned to the sky's way) |
|---|---|---|
| north drift | -10.2"/min | -10.1"/min |
| west drift | +11.8"/min | +13.5"/min |
| scatter north / west | 0.7" / 15.1" | 5.0" / 12.6" |

- Dec read the other way round on this side (+10.1 by the pins), the
  same as RA did east of the pier: the probe printed 152" of north flex
  until `axis_sign` turned it. Both axes' signs now come from the run.
- With that, the tracks part by 0.9" north: the first run's 19.5" north
  candidate did not repeat. No north-south flex.
- West they part by 12.9", but each track's west scatter is 13-15" (the
  RA worm's periodic error over 8 minutes): not flex, not measurable at
  this length.
- Drift here is south 10"/min: one-way Dec pushes with the ST4 south pin on
  this side (the pins' frame: the guide track's +10.1).
