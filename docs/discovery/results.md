# Looking for something new: results

[README](../../README.md) · Guides: [First night](../first-night.md) · [Setup](../setup.md) · [Imaging](../imaging.md) · [Calibration](../calibration.md) · [Focus](../focus.md) · Science: [Discovery](../discovery.md) · [Validation](../validation.md) · [Data](../data.md) · Developers: [Contributing](../../CONTRIBUTING.md) · [Agents](../agents/README.md)

[The discovery specification](../discovery.md)

What has been measured, with the dates. Each phase's proof is in the
[specification](../discovery.md#phases).

## What phase 0 measured

`depth.py` plate-solves a stack, matches its stars to Gaia DR3 for the zero
point, works out the 5-sigma limit from apertures dropped on empty sky, and
plants copies of the stack's own stars at G 13 to 19.5 to count how many the
star finder gets back (the brightest in rounds of their own, so their light
does not hide faint ones beside them). The 90% and 50% figures are of the
stars not lost by landing on a real one; that loss, 2 to 5% in these
fields, is crowding, given separately. Magnitudes are **unfiltered,
calibrated approximately to Gaia G**: the camera's colour response is not
G's, so a red or blue star can be off by a few tenths; a colour term from
Gaia's BP-RP is for later, before anything is reported. Measured on 16
October 2026 with the same code throughout:

| Stack | Frames | Stars | Sky (mag/″²) | 5σ on sky | 90% found | 50% found |
|---|---|---|---|---|---|---|
| M31, 13 Oct, 54 min | 202 × 16 s | 6.4″ | 19.1 | 17.91 | 17.02 | 17.59 |
| M31, 13 and 14 Oct, 95 min | 358 × 16 s | 6.4″ | 19.0 | 17.92 | 17.01 | 17.61 |
| M31, 14 Oct, 44 min | 164 × 16 s | 6.6″ | 18.7 | 17.71 | 16.83 | 17.30 |
| M31, 13 Oct, 8 min | 40 × 12 s | 6.2″ | 19.1 | 17.19 | 16.61 | 17.14 |
| M31, 6 Oct, 30 min | 120 × 15 s | 7.9″ | 18.8 | 17.22 | 16.50 | 17.10 |
| M33, 16 Oct, 24 min | 145 × 10 s | 6.1″ | 18.6 | 17.28 | 16.92 | 17.24 |

(The first night's M31 stack, 165 frames of 1 s, would not plate-solve.)

**How much a longer visit buys** (`depth.py --sweep`: the first 60 to 600 s
of the 13 October session, each stacked and measured the same way):

| Stack | 5σ on sky | 90% found | 50% found |
|---|---|---|---|
| 64 s (4 frames) | 16.46 | 16.06 | 16.34 |
| 128 s (8) | 16.77 | 16.40 | 16.72 |
| 176 s (11) | 16.88 | 16.54 | 16.76 |
| 304 s (19) | 17.08 | 16.59 | 16.97 |
| 608 s (38) | 17.29 | 16.80 | 17.20 |
| 3232 s (202) | 17.91 | 17.02 | 17.59 |

**A stack made for faint stars** (`restack.py --discovery`): every frame
that passes the checks, each weighted for a faint star's signal-to-noise,
transparency / (noise² x star width²), the poorest left out wherever they
would lower it (`stacking.point_weights`):

| Frames | Picture's stack, 50% found | Discovery stack, 50% found |
|---|---|---|
| 13 Oct | 17.59 (202 frames) | 17.55 (238) |
| 13 and 14 Oct | 17.61 (358) | 17.59 (421) |

What it says:

- **Within a night, time buys depth**, about 0.2 to 0.3 mag a doubling:
  17.0 in 5 minutes, 17.2 in 10, 17.6 in 54.
- **A second night bought nothing**, and neither weighting nor choosing the
  frames won it back: the 14 October frames had a brighter sky (18.7
  against 19.1) and slightly wider stars, but even the frames chosen and
  weighted for faint stars left the stack at 17.6. The noise in empty sky
  did not fall either (17.91 for 54 minutes, 17.92 for 95), which random
  noise would: something that does not average away sets a floor. The
  likeliest cause is the camera's own pattern. These frames had a bias
  frame only, no darks or flats, the frames drift only a few pixels in a
  session, and the difference images (phase 1) show vertical striping.
  **Dark frames, flats and dithering come before more hours.** That is a
  hypothesis until a session with them is measured the same way.
- **Star size matters as much as time.** `depth.py --model` fits every
  measurement kept to the magnitude half are found at:
  7.91 + 0.59 log10(seconds) − 2.5 log10(FWHM″) + 0.5 x sky, to about 0.3
  mag (the first night's 1 and 3 s frames are the outliers). The width and
  sky terms are fixed by physics; the other two are fitted. It predicts 5
  minutes at 4.5″ under a 19.1 sky reaching about 17.3, against 17.0 at
  today's 6.4″: **sharp focus is worth more than doubling the time.**
  `depth.py --predict --fwhm F --sky S --minutes M` gives the figure before
  a patrol: the check that says "refocus first", or "the sky is too
  bright; wait". It is planning-grade, good to the model's 0.3 mag, not an
  exact limit. The width and sky terms are held at what a perfect detector
  against the sky would give; once there are 20 independent stacks, from
  nights of different focus and sky, `depth.py --model --free` fits them
  too, and this camera and pipeline may well differ from the ideal (a sweep
  counts as one night, since its steps share its stars and sky).
- **The figures agree with each other.** The formula's 5-sigma limit and
  the planted stars' 50% point are within 0.35 mag on every stack.
- **The galaxy's glow costs little away from the core.** On M31's fainter
  and brighter glow the 50% point is within 0.1 to 0.2 mag of open sky,
  and crowding takes only 2 to 5% of planted stars: the discovery map
  (nova rate x completeness per panel) is worth making.

**Not yet a discovery completeness.** The stars are planted into the
finished stack, so this measures the star finder on that picture. It does
not test whether a nova in the raw frames survives calibration, lining up,
frame rejection, stacking, subtraction and vetting. Phase 1 plants
transients into the raw frames and runs the whole pipeline; that figure is
the real one, and may differ.

**How long a patrol visit should be is not settled by this.** Five
minutes a panel (about 17.0) against ten (17.2) trades 0.2 mag for half
the visits. Which wins depends on how many M31 novae spend how long
brighter than each limit: the scheduler should choose the length that
finds the most eruptions an hour, from these completeness curves, the
distribution of M31 novae's peak brightness and their rise and fall, and
the cadence. Five minutes is the starting point, not the answer.

**The next experiment: is the floor the camera's pattern?** Two sessions
on M31, as alike as the sky allows (same exposure, gain and time of
night, similar sky):

| | Session A | Session B |
|---|---|---|
| Calibration | bias only, as now | darks at the session's exposure and gain, and flats |
| Between frames | the mount's own drift | dithered a few pixels every few frames |

Both are measured with `depth.py --plant --sweep` and stacked to 5, 10,
30 and 60 minutes. If B keeps gaining depth past 30 minutes (17.5, 17.8)
where A flattens near 17.6, the floor was the pattern, and darks, flats
and dithering are a free gain. If B flattens too, the floor is elsewhere:
the residual galaxy glow, the stars' own crowding, or the stacking.
What it needs first: darks at 16 s and gain 1500 and a flat
(`calibrate.py`, both possible now), and dithering, which `shoot.py --dither N` now does (built 17 October
2026).

**First try, 17 October 2026, dithering alone.** Two M31 runs one after the
other: 80 frames of 16 s at gain 1500, dithered every 10 frames
(`frames/M31/20261017-215824`) and not (`20261017-225507`); restack kept
68 of each (18 minutes), bias only, no darks or flats. Stars 6.3" in both;
sky 19.0 and 19.2 mag per square arcsecond. `depth.py --plant --trials 10`,
400 stars a trial, 6000 in all; the scatter is the spread of the 50% point
with the planted stars redrawn 200 times (`mag_50_error`).

| | Dithered | Not dithered |
|---|---|---|
| 50% found, whole image | 17.38 ± 0.02 | 17.36 ± 0.02 |
| 50% found, open sky | 17.40 ± 0.04 | 17.38 ± 0.03 |
| 90% found, whole image | 16.76 | 16.94 |
| 5-sigma estimate, open sky | 17.50 | 17.27 |

No difference the planted stars can see. The 5-sigma estimate's 0.23 mag
was reported first and did not hold. At 18 minutes the stack is short of
the floor (it showed past 30), so this says dithering does not help a short
stack, not that the floor is not the pattern. Session A against B above,
with darks and flats and past 30 minutes, is still the test.

**What to improve, for discovery, in order:** sharp focus from the motor
focuser; tracking and round stars; dark frames, flats and dithering;
then a darker site or less stray light; a filter only if a test shows it
helps the star size or sky more than it costs light; a larger telescope
last.

## What phase 1 has measured so far

**Software complete; scientific validation under way.** Everything phase 1
asked for is built and tested, the end-to-end completeness is measured
with realistic fakes, and the pipeline has rediscovered a real nova it was
not given. What it has not done yet is find something of its own on a
night of this telescope's, which only patrols can do.

Three commands, each measured on the two M31 nights (14 October as the
new night, 13 October as the reference):

- **`difference.py`: proper image subtraction.** The new stack is laid on
  the reference by the two plate solves and lined up on their shared stars
  (1,654 stars, to 0.18 pixel). The subtraction is ZOGY (Zackay, Ofek and
  Gal-Yam), done in 512-pixel squares, each with its own star shapes
  and brightness scale, because the 150P has no coma corrector and its
  stars change shape towards the corners. The score allows for the stars'
  own photon noise, the 0.18-pixel lining-up error and a 3% brightness
  error. A bright peak with a dark partner beside it is a misplaced star
  and is dropped. Each candidate is labelled with how many *fading* peaks
  are as strong: what noise and imperfect subtraction alone produce.
  Getting there took four rounds against the real frames: 335 false
  candidates with one star shape for the whole picture, 169 in squares,
  then 132, 47 and 40 as the photon and lining-up noise, the zero rows at
  a stack's edge, M32's steep glow and the pairs were dealt with.
  On those stacks it left about 40 candidates, none above 7 sigma, each
  matched by 8 or more fading peaks as strong. Most of them came from the
  stack, not the subtraction: the laptop's 14 October stack was made before
  restack.py learned to turn frames from the far side of the meridian
  whenever they line up poorly (`9c4edb2`). **Restacked with today's code,
  the same two nights leave one candidate, at 5.4 sigma: about one false
  candidate a night, before vetting, and nothing new between 13 and 14
  October.**
  Fakes planted in the finished stack are found to G 18.2 (half) and 17.6
  (90%)**, 0.9 mag deeper than phase 0's star finder on the same stack:
  the subtraction's matched filter is a better detector of a single point.
- **`plant.py`: the discovery completeness.** Fakes planted in every raw
  frame, then the whole pipeline. 300 fakes at G 15 to 19.5 were planted
  in the 226 raw frames of 14 October (225 plate-solved; one went in
  unchanged); the copy went through the quality checks (164 frames kept),
  lining up, stacking and subtraction from 13 October:

  | Planted at G | Found |
  |---|---|
  | 15.0 to 16.5 | 117 of 122 (96%) |
  | 17.0 | 22 of 25 |
  | 17.5 | 25 of 30 |
  | 18.0 | 11 of 27 |
  | 18.5 to 19.5 | 0 of 96 |

  That first run said half found at G 17.9 and 90% at 16.9, but its fakes
  were planted with the reference's zero point (13 October, 23.10) into the
  new night's frames (14 October, 22.89): each fake was 0.2 mag brighter
  than its label. Since 17 October the fakes are also realistic: each
  takes its frame's own star shape in its part of the picture (a 3 x 3
  grid, so coma and trailing come with it), its own photon noise (from the
  frame's counts per electron, measured from the sky's grain above the
  bias), and the frame's clearness (a real star dims with haze); and the
  new night's own zero point. **Measured that way, with idealised colour
  (grey) taken out of the question by the colour term below: half found at
  G 17.8, 90% at G 16.9.** Planting into the finished stack had said 18.2
  and 17.6: the whole pipeline costs 0.4 mag at half and 0.7 at 90%.
  The colour term, fitted against Gaia's BP−RP on the same night's stars,
  is −0.34 mag per mag of colour about BP−RP 0.92: the 183C sees a red star
  fainter in G than Gaia does. Planted at three colours through the whole
  pipeline:

  | Fakes' colour (BP−RP) | Half found | 90% found |
  |---|---|---|
  | blue (0.2) | G 18.1 | G 17.55 |
  | grey (0.8) | G 17.8 | G 16.89 |
  | red (1.4) | G 17.73 | G 16.89 |

  A young nova is blue near its peak, so the blue row is the one closest
  to what the patrol hunts; the grey row is the figure quoted.
  For the patrol: a nova at G 17 or brighter is caught nine times in ten
  on a night like 14 October; at 18, about four in ten. It took 10
  minutes on the desktop's 12 workers, and the same run left one
  candidate that was not a fake.
- **`vet.py`: the evidence for each candidate.** On the clean 14 October
  stack the one candidate (5.4 sigma, about G 18.2, 26′ north-east of
  M31's centre along its long axis) passed every check: in both halves of
  the night (4.8 and 4.0 sigma), no known asteroid (SkyBoT), no VSX
  variable, not on the Rochester lists, no Gaia star within 2″. Pan-STARRS
  has nothing there brighter than about 20.8. But **`forced.py`**, which
  measures the place in every stack, does not see it in the 14 October
  stack itself (fainter than G 18.0, while the difference put it at 18.2),
  nor in any other; and noise makes two peaks that strong a night. So it is
  unconfirmed and most likely noise: a clean example of what the pipeline
  hands a person, and of why a real one has to be seen again on another
  night.

  Since 17 October a Gaia star close by is a **clue, not an explanation**:
  a transient can sit beside a catalogued star, and in a crowded field 2″
  is not nothing. Only a match to something catalogued as moving, varying
  or already reported explains a candidate; a Gaia star, light already in
  the reference, or halves not checked are listed with it as clues. Being
  in one half of the night only is said as it is, and whether that sets it
  aside is the programme's rule (`both_halves = true` for the nova
  programmes: a nova lasts the night; another kind of transient might
  not).
- **`reference.py`** keeps each field's reference as a numbered version
  that is never replaced, with the nights it was made from; M31's v1 is the
  13 and 14 October stacks together (half found at G 17.61), and a night in
  it is never compared with it. A stack whose nights include or follow an
  open candidate's first night, with the candidate in its field, is
  **refused as a reference** (`--force` overrides): a real, lasting nova
  baked into the reference would subtract itself away from every night
  after. **`forced.py`** gives a place's brightness or upper limit in
  every stack of a field, and with `--difference` the light above the
  reference there, without the galaxy or the faint stars underneath:
  patrols follow candidates up that way.
- **A real nova, recovered** (`recover.py`). Fakes prove the pipeline finds
  what was put there; the test that matters is something nobody put
  there. AT2024koe (M31N 2024-06a) erupted on 8 June 2024 in M31's outer
  disc, peaked at 16.2 on 12 June and was 19.5 by 3 July. From ZTF's public
  r-band images of 21 May (before) and 27 June (on the way down), cut out
  round it, `difference.py` found it **0.27″ from its published place, at
  10.8 sigma, the strongest of the 4 candidates, at r 19.4**. The first
  try missed it: a fixed 20-pixel mask round bright stars, right on this
  rig's stacks, hid it on ZTF's sharper images; the mask now goes with the
  stars' width (2 and 4 widths), which changed nothing on this rig's
  nights and stops a real nova near a bright star being hidden. These are
  ZTF's images (1.2 m, 1″ pixels), so this proves the software, not this
  telescope's depth.

**`patrol.py` puts it together** for one field: `./patrol.py m31-novae
--plan` says whether it is ready and what it would run, `./patrol.py
m31-novae` points, images and analyses, and `--analyse SESSION` does the
analysis on a night already taken. **`candidates.py`** keeps every
candidate as an object followed from night to night, and each patrol
measures the open ones again at their places whether or not the search
found them, so a real one is seen again. One missed on three nights,
each deep enough to have shown it even had it faded 0.2 mag a day (as
fast as a quick nova near its peak), is closed as most likely noise, with
its evidence kept; a slower miss does not count. The 14 October candidate
is on file as the first.

The Transient Name Server is not asked yet: its search needs an account
(a TNS bot key), which would be the person's own.

## The comet hunt

**Built 17 October 2026, by hand.** `./sungrazer.py fetch` and `look`
(with `--until` for a day in the past) do what the
[design](design.md#sungrazer-cloudy-night-mode) describes except the check
against comets already reported, which a person makes from the project's
list. Motion is measured per 12 minutes from each picture's own time, as
the archive has gaps. Two tests on archived C3 pictures: the bright
C/2024 G3 (ATLAS) on 13 and 14 January 2025 was found, its head and tail
the strongest candidates, alongside the bleed line from its saturated
head; the faint Kreutz comet SOHO-5175 on 25 January 2025 was not, on a
day crowded with outward-moving coronal material.

**Raw pictures, GOES-19, and planted comets, 17 October 2026.**
`--raw` takes LASCO's level-0.5 FITS files instead of the JPEGs (the
archive at umbra.nascom.nasa.gov/pub/lasco_level05/, or the last
fortnight's while it catches up), and `--camera ccor1` the Compact
Coronagraph on GOES-19 from NOAA's open archive on Amazon's S3. The
Cambridge list of SOHO comets shows why CCOR-1 matters: in 2026 nearly
every new comet has been found in it (G1), a handful in LASCO. The noise
is now measured in each 64-pixel square, as the inner corona is far
noisier than the edge. `look --plant 120` puts fake comets heading in
towards the Sun into the real pictures, with their real noise and
outflows, and counts them back:

| Pictures | Found at 3, 4, 6, 8 and 12 times the noise (of 20 each) |
|---|---|
| LASCO C3 JPEGs, 15 September 2026, 161 | 8, 17, 20, 20, 20 |
| LASCO C3 raw, the same hours, 161 | 1, 15, 20, 20, 20 |
| CCOR-1, 11 and 12 October 2026, 116 | 3, 8, 15, 18, 20 |

"Times the noise" is each picture's own noise, so the rows say how well
the search works on each kind of picture, not which kind goes fainter:
that needs the same comet measured in both. CCOR-1's first try found its
occulter's arm instead (blanked to 0, its edges flickering), now left
out. The raw pictures of 25 January 2025 give nothing heading for the
Sun either: SOHO-5175 is a Meyer-group comet (Y on the Cambridge list),
small and faint, and without its positions a miss cannot be told from
a comet not moving that way. In CCOR-1, after the arm, nothing heading for the Sun was found in the 30 hours
that held the 12 October CCOR-1 comet, and the project's own pages, with
its positions, would not answer from here to say where it was.

**A real faint comet found, 17 October 2026.** On 15 September 2026, the
day a Kreutz comet was found in C3, both the JPEGs and the raw pictures
give one object moving steadily in towards the Sun, about 2.3 pixels in
12 minutes, from 07:30 to after 20:00 UTC (in the JPEGs from (933, 759)
at 10:30 to (806, 672) at 23:54), the strongest candidate in both. No
planet was in the field that day. It is very likely that comet; until
the project's positions say so, it is not proven. It is not run all the
time for LASCO: the project is to be asked first. CCOR-1's archive is
NOAA's open one, meant for such use, so `./sungrazer.py hunt --install`
runs the CCOR-1 hunt every 6 hours as a systemd user timer: the last
day's pictures, only what heads in towards the Sun kept in
sungrazer/hunt-ccor1.json, pictures over 3 days old deleted.

## Variable stars

**First measured 17 October 2026, on the six M31 nights so far.**
`variables.py` stacks each night's kept frames in batches of 10 (160 s
of 16 s frames), measures every Gaia star alone in the picture at its
Gaia place, and puts each batch on Gaia's scale by a fit through all of
them: a surface over the picture (the vignetting each night's pointing
moves, there being no flats), the glow under each star, and its
brightness (sharp seeing measures a star on M31's disc, and a bright one
near a full well, differently from soft). Each point's noise is the
spread of stars as bright in its own batch, together with how far stars
as bright wander from night to night. What that gives, per 160 s point:

| G | Stars | Noise in a point | Night to night |
|---|---|---|---|
| 13 to 14 | 123 | 21 mmag (2%) | 16 mmag |
| 14 to 15 | 221 | 33 mmag | 15 mmag |
| 15 to 16 | 313 | 70 mmag | 30 mmag |

Stars brighter than G 13 are left out of judging: in 16 s frames on the
sharp 14 October night (6" stars) the G 11 to 12.7 ones lost light to
full wells, and every one of them looked variable. On galaxy light more
than 1.2 times the sky they are left out too. Of the 40 VSX variables in
the field, the clearest (TSVSC1 TN-N330012310-13-67-2, a contact binary)
is seen to vary; most of the others are rotating stars and δ Scuti
pulsators of a few hundredths of a magnitude, below this. A dip is three
batches or more in a row, each 3 times its noise and 2% fainter, not
shared by a fifth or more of the stars within 10'
(those are the sky's). Eight stars not in VSX are still flagged; every
one dips in the 13 October 23:26 session, where two of them 15' apart
sag and recover with the same shape: something on the picture that
night, not the stars. So no new variable yet, and the honest state is
that one session's drift can still pass for a dip; more nights will
show which flags repeat.

## Real or bogus

**First trained 17 October 2026** (`./realbogus.py train`), on the five M31
nights that have been subtracted, each subtracted again twice with 300
fake stars planted in the night's own stack (G 13 to 19.5, the night's own
star shape and noise). Real examples: the planted stars found, 1774.
Bogus: every other peak above 4 sigma, brightening or fading, 1374; the
candidates still waiting for a person's eyes were left out of both. No
person's dismissals yet. Eight measurements of each peak's patch (its
score, its width against the stars, how round, how sharp, a dark lobe
beside it, light in a ring round it, light in the reference under it, how
far its centre sits from its peak) go into a logistic regression.

Tested night by night, each night held out and the model trained on the
other four, at candidate strength (5 sigma or more), with the cut set to
keep 95% of the planted stars in training:

| Night held out | False candidates set aside | Planted stars kept |
|---|---|---|
| 4 October (a poor night, 197 candidates) | 124 of 399 | 173 of 198 |
| 6 October | 32 of 34 | 325 of 334 |
| 13 October 23:12 | 6 of 6 | 401 of 402 |
| 14 October 02:05 | 1 of 1 | 332 of 334 |
| 14 October 02:11 | 12 of 12 | 413 of 416 |
| All | 175 of 452 (39%) | 1644 of 1684 (98%) |

On the four ordinary nights it sets aside 51 of 53 false candidates; on
the poor night, a third. The heaviest weight is on the score, so part of
what it learnt is that stronger is likelier real; tested again with the
score left out, the shape alone sets aside 148 of the 452 with the same
planted stars kept, so most of it is the shape. The rest of the weights:
light in a ring round the peak and a wide or sharp spot count against it,
a shallow dark lobe for it.

Of the seven candidates on file from those nights, all between 5.1 and
5.4 sigma, it rates five likely bogus (0.03 to 0.16, below its cut of
0.22) and two not (0.38 and 0.34). That is advice: `vet.py` puts the
probability in each candidate's evidence and a clue when it is low, and
dismisses nothing. Two things it does not know: a real transient sitting
right on a bright star or a galaxy's core, as the planted stars are spread
evenly over the usable area; and anything unlike these five nights, until
it is trained on more of them. A person's dismissals join the training as
they come; train it again after new nights.

