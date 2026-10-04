# Checking it under real sky

[Back to the README](../README.md)

Much of the newer work is proven on made-up star fields and a simulated
mount, not yet on real sky. These are the experiments that will settle it.
Results go here as they are obtained; until then each one says "not yet run".

| # | Question | How | Result |
|---|---|---|---|
| 1 | Does "Best focus. Hold" land on the sharpest point? | `./focus.py`, noting the HFR when it speaks, then compare the star width (FWHM) of a stack taken there with one taken a touch either side. | Not yet run. |
| 2 | How much Dec drift does the compensation remove? | `./mount.py drift` before, `./mount.py compensate`, `./mount.py drift` after, at three or more hour angles. | First try did not settle; see the results below. One early figure: about -1.4"/s natural drift near M27 with the polar axis roughly 9 degrees out. |
| 3 | Does the quality pass beat the live stack and a plain stack? | `./compare.py` on the same 200 to 300 raw frames stacked three ways: star width, roundness, background noise, faint detail. | Partly: on 200 frames of M27, star width went from 8.4 to 6.9 px and roundness from 0.67 to 0.92 against the first-night stacker. |
| 4 | Does `--exposure auto` pick the exposure that gathers most usable light? | Run the same target at 1, 2, 3 and 4 s; compare accepted integration time and star shape with what auto chose. | It chose 1 s twice, on roundness. Whether 2 s would have given a better picture despite the stretch is untested. |
| 5 | Do four worker processes give the expected speed-up? | `./restack.py SESSION --profile` on 200 to 500 frames, with `--workers 1` and `--workers 4`. | 200 frames: 23.5 minutes before the rewrite, 3.9 minutes with four workers. |

## Why frames are slow: what has been checked

A 1 s exposure takes about 9 s to arrive and a 2 s one about 14 s. Checked on
the Hypercam 183C over a USB 2 lead:

| Suspect | Finding |
|---|---|
| USB link negotiated at the wrong speed | No: 480 Mbps, the USB 2 maximum (`./doctor.py` now reports it). |
| Readout speed left at its slowest | No: the driver's Speed control is already at 2, the top of its 0-2 range. |
| A frame-rate cap left on | No: FPS Limit is 0, which means none. |
| Sharing the USB bus | The camera, both webcams and the mount lead share the laptop's one USB 2 bus. The external webcam only runs while the mount moves. |
| Sending four times the pixels needed | **Yes, this is it.** See the table below. |
| Trigger and packaging overhead | Driver-sequenced "fast" exposures and native (non-FITS) transfer both timed out on this driver. |

`./camera_test.py --throughput`, 4 October 2026, 1 s exposures, cap on:

| Mode | Seconds per frame | Shutter open |
|---|---|---|
| Full frame 5440 x 3648, readout speed 2 (as used so far) | 9.3 | 11% |
| Readout speed 1 | 12.4 | 8% |
| Readout speed 0 | 18.0 | 6% |
| 2736 x 1824 mode | 2.4 | 41% |
| 1824 x 1216 mode | timed out | |
| Fast exposure, native transfer | timed out | |

The 2736 x 1824 mode collects nearly four times the light per hour. Not yet
adopted, for two reasons. Whether it keeps the colour pattern could not be
judged with the cap on (the driver still labels it RGGB); that needs one
frame of something coloured. And it halves the detail: after the colour
cells are combined the picture would be 1368 x 912 at 2.6 arcseconds per
pixel. With stars currently about 8 arcseconds wide that loses little, but it
is a real change to the pipeline, the darks and the plate-solve scale. The
2x2 binning rows of the benchmark were taken after the failed mode left the
camera at the smallest size, so they say nothing.

## First real results, night of 3-4 October 2026

M31 from a back garden, polar axis about 9 degrees out, USB 2 lead.

- **Exposure chosen by the tracking test:** 1 s both times. Roundness was
  0.70-0.72 at 1 s, 0.61-0.68 at 2 s, 0.45-0.53 at 3 s, 0.35 at 4 s. The
  polar alignment, not the camera, set the exposure.
- **Run 1:** 200 frames in 49 minutes, 199 accepted live, 165 stacked by the
  quality pass, 6 re-centres, stars lined up to 0.43 pixel. 165 s of light.
- **Run 2 (open-ended, stopped by cloud):** 75 frames, 46 stacked.
- **Combined:** 207 frames from both runs, 207 s, lined up to 0.36 pixel,
  with darks and bias applied. Dust lanes visible.
- **Field rotation:** the field turned about 4 degrees in an hour because of
  the polar error. The first attempt to combine the runs left out 108 frames
  that would not line up; the alignment now searches for a turn of up to 8
  degrees and only 2 were left out.
- **Drift assist, first real use:** it hunted instead of settling. Measured
  drift -1.31, then +1.06 after setting a creep of -1.00, then -1.29 after
  -0.25. The Dec motor seems to respond about twice as strongly as assumed,
  but three readings do not fit one explanation. Not fixed; needs a
  controlled test (set a creep, measure, repeat) before the logic is changed.
- **Home after a drift correction:** went the wrong way twice because the
  direction test did not wait for the gears to take up. Fixed.
- **Meridian:** the mount was already on the tube-over-pole side for both
  runs, so the upside-down handling in the combiner was not exercised.

## Known weaknesses found by the tests

- The focus tracker judges change against the readings' own jitter. If the
  knob is turned in steps with a pause after each, the steps themselves
  inflate that jitter and some real changes are announced as "No change".
  Turning slowly and steadily avoids it. Found by `tests/test_night.py`.
