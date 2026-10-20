# Comet hunt, GOES-19 CCOR-1, 19 October 2026

The comet hunt (`sungrazer.py hunt`, every 6 hours) looked at 74 CCOR-1
level-3 pictures from 18 Oct 23:45 to 19 Oct 23:45 UTC and listed three
tracks heading in towards the Sun. Pictures: 1024 x 960 px, 0.01074°/px,
Sun near x 522, y 475; x and y here are array columns and rows from the
bottom (FITS order), half the native 2048 x 1920 frame.

| | Pictures (UTC) | First / last x, y | px per 12 min | Strength | Movie |
|---|---|---|---|---|---|
| 1 | 20:45–23:45 (13) | 914, 315 → 863, 332 | 3.52 | 150.1 | [candidate-1.gif](candidate-1.gif) |
| 2 | 16:45–20:00 (14) | 979, 295 → 926, 312 | 3.43 | 87.8 | [candidate-2.gif](candidate-2.gif) |
| 3 | 11:30–12:30 (5) | 579, 335 → 586, 373 | 7.72 | 6.8 | [candidate-3.gif](candidate-3.gif) |

`candidate-N-first-middle-last.png` is the first, middle and last frame of
each movie side by side. `look.json` is the hunt's full answer.

## What they are

- **1 and 2 are one object**, split by the gap 20:00–20:45: track 2
  carried on 45 minutes lands on track 1's first point. It is 5.45° from
  the Sun at 16:45 and 4.17° at 23:45, position angle 223° from solar
  north, a compact head with a short streak.
- **It is a known Kreutz comet**: the Sungrazer Project's report
  report_ms_20261019125628 (Michael Stark, CCOR-1, "Known Comet Now
  Entering", endorsed) has it at native x 2029, y 1352 at 14:30 UTC, moving
  −0.53 px/min in x. Halved and with y counted from the bottom that is
  1014, 284; track 2 carried back to 14:30 gives 1016, 283, and its rate
  in x is −0.272 px/min against the report's −0.267 (halved).
- report_bc_20261019233808 (Bill Collins, CCOR-1, potential Kreutz comet,
  19:45–21:30, native x about 890, y about 910) is a different object, on
  the other side of the Sun from this track.
- **3 is not a comet**: nothing shows in its movie; it lies along the
  bright edge round the occulter, where the background flickers.
- Planets: Venus is 10° from the Sun (inferior conjunction about 23–24
  October), outside the field; Mercury, Mars, Jupiter and Saturn are
  further. Spica is about 3.5° from the Sun but drifts only about 1° a day
  with the stars; this track moves about 4° a day.
