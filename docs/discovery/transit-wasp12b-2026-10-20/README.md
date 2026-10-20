# WASP-12 b, night of 19–20 October 2026: a first transit attempt

The first exoplanet transit this rig has tried to measure. The frames were
taken and the measurement runs end to end, but the result does not stand as
a detection: the photometry has a noise floor of about 20 mmag that does not
improve with brightness, and cloud took the egress. This page sets out what
was taken, what was measured, where the noise appears to come from, and what
would settle it.

![The light curve](transit-WASP-12b.png)

*The star's light against its baseline before the transit, one point per 10
frames (40 s of exposure), times in UTC. Shaded: the predicted transit. Red:
the box that fits best. `transit-WASP-12b.json` holds every point.*

## The target

WASP-12 b: a hot Jupiter on a 1.09-day orbit around a G 11.5 star; published
depth 1.54%, duration 3.0 h (from the planet table `transits.py` keeps).
Predicted on this night: ingress 01:27, middle 02:57, egress 04:27 UTC.

## What was taken

- Sky-Watcher 150P (150 mm, f/5) on an EQ3 Pro, Altair Hypercam 183C (Sony
  IMX183, colour), gain 1500, 4 s frames, unguided, no dithering.
- Session `frames/WASP-12/20261020-014726`: 00:47 to 03:59 UTC, 992 frames
  taken, 973 kept (cloud from about 03:50). Three short restarts after
  camera hangs added 45 frames after 04:00 and are not in this curve.
- Calibration: a bias and a 1 s dark at gain 1500. **No flat frames.**
- Baseline before ingress: about 40 minutes (the BAA asks for at least 30,
  ideally 60). **None after egress**: cloud and camera hangs from 03:50.

## What was measured

`./transits.py measure frames/WASP-12/20261020-014726 --planet "WASP-12 b"`
(variables.py's photometry, run on 20 October after two fixes, b767d8a):

- the kept frames in 99 batches of 10, each batch stacked onto the first
  frame's pixels;
- the stacks plate-solved, every Gaia star of G 11.5 to 16 placed by its
  catalogue position;
- each star's light measured with weights shaped like a star of the first
  stack's width (FWHM 5.2 px, weighting radius 5.2 px), on the stack less a
  smooth background;
- magnitudes put on Gaia G by the night's ensemble, batch by batch, with a
  smooth surface over the field taking out vignetting that moves;
- a box fitted with its middle sought within an hour of the prediction.

Result: **dip 2.16 ± 0.47% (expected 1.54%)**, 89 points inside the box, 10
outside, **scatter 15.3 mmag per point outside it**. The fit puts the middle
24 minutes early, but with no baseline after the transit an earlier middle
and a deeper dip fit the same points, so the timing is not measured; the
command now says so (cd0ce83). The depth agrees with the published one
within its error, but it rests on ten points before ingress, and a slow
drift over the night would look much the same.

## Where the noise comes from

Every star's scatter about its own median, by brightness (robust, per
10-frame point; removing a smooth quadratic trend changes it by under 1
mmag):

| G | stars | scatter (mmag) |
|---|---|---|
| 11.4–12 | 33 | 22.1 |
| 12–12.5 | 32 | 21.0 |
| 12.5–13 | 45 | 22.9 |
| 13–13.5 | 89 | 27.2 |
| 13.5–14 | 79 | 36.9 |
| 14–15 | 277 | 66.2 |
| 15–16 | 395 | 155.4 |
| WASP-12 (11.5) | 1 | 16.7 |

What it should be for G 11.5 in 40 s through 150 mm: photon noise well under
1 mmag, scintillation about 2 mmag at this airmass (Young's formula). So the
bright stars stop improving at about 20 mmag: a systematic floor, not noise.
The ensemble's common correction per point is 4.7 mmag rms, so it is not the
sky changing for all stars alike.

Measured during the run (`frames.jsonl`):

- the field **drifted up to 80 px in x and y** across the sensor (unguided,
  polar alignment 0.6° low), and **rotated 0.45°**;
- star width 5.6 to 6.3 px (5–95%), so focus and seeing held fairly steady;
- sky background rose from 15 to 36 ADU (haze coming in before the cloud).

## Suspects, most likely first

1. **No flat field, with the stars wandering 80 px.** Each star crosses
   different pixels, dust shadows and vignetting through the night; with no
   flat, the sensitivity it meets changes by a percent or more. The ensemble
   surface takes out smooth vignetting, not pixel-scale or dust-scale
   structure. Fits a floor the same for every star.
2. **A weighting radius of one FWHM.** Only the core of each star is
   measured, so small changes in the star's shape across the field and
   through the night (coma, tilt, the 0.45° rotation, focus) change the share
   of light measured. Typical aperture photometry uses 2–3 FWHM.
3. **The colour sensor.** The stacks are luminance made from debayered
   colour; a star's light on the Bayer pattern changes as it drifts by a
   pixel, and the interpolation in registering each frame onto the first
   adds to it.
4. **Row stripes.** The camera reads faint row stripes into every frame
   (docs/banding.md, 1.3–2.4 ADU per row); against a star's light they are
   small, but they are not taken out before photometry here.
5. **The comparison ensemble.** Every star brighter than G 16 is in it,
   weighted by the whole field; a smaller set of steady stars near WASP-12's
   brightness and colour would be the usual choice.

## What would separate them

All from this night's frames; nothing needs the telescope:

- the scatter against the **weighting radius** (1, 2, 3 FWHM, and a plain
  aperture): if 2–3 FWHM drops the floor, suspect 2;
- the scatter against **how far each star drifted** and against its place
  in the field: if stars near the edge or near dust shadows are worse,
  suspect 1;
- the scatter of each **colour channel** measured on its own, raw, without
  debayering: suspect 3;
- the same with the **rows' median taken off** each frame first: suspect 4;
- WASP-12 against **5–10 hand-picked comparison stars** of G 11–12.5 near it:
  suspect 5.

And for the next attempt at the telescope: flat frames, guiding or at least
re-centring so the field stays within a few pixels, the target at the same
place on the sensor all night, an hour of baseline both sides, and the
transit chosen high in a clear forecast.

## Questions for a reviewer

- Is the ranking of suspects right for an unguided, unflatted colour CMOS
  rig, and is there a cause missing?
- Is 10-frame (40 s) binning sensible here, or would a fit on every frame
  with its own error be better?
- With baseline on one side only, is a fitted depth worth quoting at all,
  or only the drop between the baseline and the first hour?
- What scatter should a rig like this reach on a G 11.5 star, and what do
  amateur transit observers (ExoClock, the BAA, the ETD) usually get?
