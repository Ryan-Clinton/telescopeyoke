# Why panel 8 gives false candidates every night

Measured on 4 November 2026 from M31-P8's real stacks; nothing below was
changed in the search. The two scripts beside this file reproduce every
number: `p8-candidates-against-surroundings.py DIFFERENCE.fits
CANDIDATES.json` and `p8-stack-noise-map.py STACK.fits`.

## What was tried and failed

- **The reference's stripes.** A deeper reference without them (the 20 Oct
  01:29 stack, 32 frames) gave 24 candidates on 4 Nov where v1 gave 4. It
  was withdrawn (`reference/M31-P8/withdrawn/`); v1 is in use again.
- **Corners fewer frames reached.** 4 Nov's restacked panel 8 has every
  frame reaching every pixel, and its noise is even to within 10-20% in
  128 px squares over the whole picture.

## What the measurements show

The search calls a peak a candidate at 5 times the significance map's
spread over the whole picture. The table gives each candidate's score
against its own surroundings: the map's level and spread in the 96 px
square around it.

| Night against v1 | candidates | dark peaks over 5 | local spread at the candidates (map median 0.96) | still 5 or more against its surroundings |
|---|---|---|---|---|
| 18 Oct 21:43 | 2 | 0 | 1.40, 1.62 | 0 of 2 |
| 20 Oct 00:41 | 4 | 1 | 1.27 to 1.87 | 0 of 4 |
| 4 Nov 03:51 (cloud, 8 frames) | 4 | 568 | 1.21 to 1.42 | 2 of 4 |
| 4 Nov 03:51 against v2 | 24 | 361 | 1.54 to 3.36, level +0.4 to +2.0 | 0 of 24 |

- On the two clean October nights every candidate sits where the local
  spread is in the top 1% of the map (its 99th percentile is 1.58), in the
  patch near v1's pixels x 76-434, y 490-560. None is 5 against its own
  surroundings. They are the ordinary noise of a patch that is 1.3 to 1.9
  times noisier than the search assumes.
- Against v2, 23 of the 24 lie in one patch about 70 x 110 px near v2's
  right edge, where the map is raised by +1 to +2 and its spread is 2 to 3
  times the median. Each covers 250-430 px at half its peak, where a point
  source covers about 40. They are one extended structure crossing the
  threshold many times, not 24 point sources.
- The two of 4 Nov that stay above 5 against their surroundings come from a
  stack whose noise has heavy tails everywhere: 568 dark peaks over 5
  against 0 or 1 on the October nights.

## Cause, as far as measured

The search's noise model underestimates the noise in that patch of panel 8
by a factor of 1.3 to 1.9 against v1, and a broad residual is left there
against v2. Not measured yet: why that patch is noisier. The reference's
own noise there is not raised (high-pass spread 1.24 at its left edge
against 1.27 in the middle).

## What it would take to correct it

Dividing the score by its local spread everywhere was tried on 2 November:
it removed most false candidates but lost a tenth of planted G 17-17.5
stars in a stack's poorly covered corner. The trade-off between fewer
false alarms and losing faint real novae there is the person's call, and
any change is measured on these four nights, with planted stars, before it
is used.
