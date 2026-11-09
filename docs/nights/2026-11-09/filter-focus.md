# 9 November 2026: focus in all seven filters

The 183M on the 150P, hand focused in L on the Double Cluster (64° up, east)
to HFR 1.5 with the spoken aid. Then, without touching the focuser, three
`./focus.py --check` frames in each filter (`./sxwheel.py move F`), 20:30–20:32:

| Filter | HFR (median of 3) | Frames |
|---|---|---|
| L | 1.50 | 1.57 1.50 1.49 |
| R | 1.64 | 1.53 1.64 1.69 |
| G | 1.45 | 1.39 1.90 1.45 |
| B | 1.46 | 1.46 1.49 1.35 |
| Ha | 1.30 | 1.43 1.24 1.30 |
| SII | 1.27 | 1.31 1.18 1.27 |
| OIII | 1.37 | 1.34 1.38 1.37 |

The usual best is 1.77. Every filter is as sharp as L within the scatter
from frame to frame (about ±0.2), so no filter needs its own focus and no
offset is kept: the two parfocal sets hold, and on this night the two sets
also focus together. The narrowband readings are a little lower, most
likely because fewer and fainter stars are measured through them, not
because they are sharper. `--check` used its own exposure; the `--exposure 10`
asked for in narrowband was not used.
