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

The same test on a USB 3 lead, 6 October 2026, indoors, 1 s exposures:

| Mode | Seconds per frame | Shutter open |
|---|---|---|
| Full frame 5440 x 3648, readout speed 2 | 1.54 | 65% |
| Readout speed 1 | 1.84 | 54% |
| Readout speed 0 | 2.41 | 42% |
| Binned 2x2 (2720 x 1824) | 1.12 | 89% |
| 2736 x 1824 and 1824 x 1216 modes | not measured: see below | |
| Fast exposure, native transfer | timed out | |

At 0.1 s exposures a full frame took 1.02 s (3.5 s on USB 2) and a binned
one 0.70 s. So the lead was most of it: about six times the frames at 1 s,
with the full sensor. The two smaller modes' rows cannot be trusted: the
frames came back full size and, at 1 s, faster than the exposure (0.91 s
and 0.77 s), so the test is not selecting the mode or is counting old
frames. That fault in `camera_test.py` is still to be found. The sensor was
in room light and burnt out for the 1 s run, so the colour pattern of the
binned frames is still unjudged. No night has been run on this lead.

On USB 2, the 2736 x 1824 mode collects nearly four times the light per hour. Not yet
adopted, for two reasons. Whether it keeps the colour pattern could not be
judged with the cap on (the driver still labels it RGGB); that needs one
frame of something coloured. And it halves the detail: after the colour
cells are combined the picture would be 1368 x 912 at 2.6 arcseconds per
pixel. With stars currently about 8 arcseconds wide that loses little, but it
is a real change to the pipeline, the darks and the plate-solve scale. The
2x2 binning rows of the benchmark were taken after the failed mode left the
camera at the smallest size, so they say nothing.

## Daytime frames and a binning trial, 6 October 2026

Taken outdoors on the USB 3 lead with the telescope at the zenith and near
the pole, about two hours before sunset, for `polaris.py`:

- **Exposure:** the sky reached 70% of full scale at 16 ms, gain 300. The
  first frame after opening the camera took 45 s (the exposure being found
  from 2 ms up); each frame after that about 1 s.
- **Colour of clear sky:** raw medians red 1734, green 3584, blue 3353, so
  blue over red 1.93, the same to within 0.05 across the frame. No cloudy
  frame was measured that afternoon (see the next item).
- **Colour of cloud:** at 18:13, with the Sun 4° up and cloud over the pole
  lit from below, `polaris.py check` read blue over red 0.55 at 2 ms and
  called it grey. That is sunset-lit cloud, redder than white; flat grey
  cloud at midday has still not been measured. Six minutes later the cloud
  had gone and the same patch read 1.61 at 19 ms: clear sky is less blue as
  the Sun goes down, so the line between clear and cloud was moved from 1.6
  to 1.2.
- **False stars:** none in blank sky, in single frames or one divided by
  another.
- **The search, 18:22 to 19:06 (sunset 18:50), recorded:** 266 looks in 35
  minutes, 6 to 9 seconds a look, with three frames added up for each. The
  quick aiming left the Dec axis within 0.05° of what was asked and the RA
  axis within 0.5°. Exposure rose from 22 ms to 144 ms as the light went;
  blue over red stayed between 1.55 and 1.86. In blank sky the brightest
  point of a look stood out 3.5 to 6.2 (a star needs 12). One look (194)
  reached 8.8 on a faint smear at the very edge of the frame that no
  neighbouring look showed. The last two looks reached 10.9 and 10.6 on a
  small round point that moved 990 pixels for a 0.366° step of the Dec
  axis, as a star should (1003 expected): a faint star showing at dusk. No
  Polaris within 3.3° of where the mount's axis pointed. A plate solve at
  19:07 failed: the sky still burnt out a 2 s frame.
- **Binning 2x2 over INDI, tried once and not adopted:** setting
  `CCD_BINNING` to 2 on the open camera ended with the connection to the
  INDI server broken (the server was restarted for the next command and the
  camera then worked as before). Whether the binning caused it was not run
  down. With the indoor timings above (0.70 s against 1.02 s a frame at
  short exposures) the gain would be a third of a second a look, and whether
  binned frames keep their colour pattern, which the cloud check needs, is
  still unjudged. `polaris.py` therefore reads full frames and reduces them
  itself.

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
