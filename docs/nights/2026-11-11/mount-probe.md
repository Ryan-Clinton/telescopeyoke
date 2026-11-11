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
  takes the guide camera's RA sign from the run itself (`ra_sign`).
  Guiding is not affected: it uses the measured pulse directions, not
  their names.
- With that, the two tracks part by 6.4" west (under one guide pixel,
  9.55") and 19.5" north (about two guide pixels) over the run. The
  north parting is a flex candidate only: it counts once a second run
  repeats it (docs/mount-probe.md).
