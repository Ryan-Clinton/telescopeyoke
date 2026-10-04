# Checking it under real sky

[Back to the README](../README.md)

Much of the newer work is proven on made-up star fields and a simulated
mount, not yet on real sky. These are the experiments that will settle it.
Results go here as they are obtained; until then each one says "not yet run".

| # | Question | How | Result |
|---|---|---|---|
| 1 | Does "Best focus. Hold" land on the sharpest point? | `./focus.py`, noting the HFR when it speaks, then compare the star width (FWHM) of a stack taken there with one taken a touch either side. | Not yet run. |
| 2 | How much Dec drift does the compensation remove? | `./mount.py drift` before, `./mount.py compensate`, `./mount.py drift` after, at three or more hour angles. | Not yet run. One early figure: about -1.4"/s natural drift near M27 with the polar axis roughly 9 degrees out. |
| 3 | Does the quality pass beat the live stack and a plain stack? | `./compare.py` on the same 200 to 300 raw frames stacked three ways: star width, roundness, background noise, faint detail. | Partly: on 200 frames of M27, star width went from 8.4 to 6.9 px and roundness from 0.67 to 0.92 against the first-night stacker. |
| 4 | Does `--exposure auto` pick the exposure that gathers most usable light? | Run the same target at 1, 2, 3 and 4 s; compare accepted integration time and star shape with what auto chose. | Not yet run. |
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
| Sending four times the pixels needed | Open. The camera offers 2736 x 1824 and 1824 x 1216 modes and 2x2 binning; the pipeline halves the frame anyway. Whether those modes keep the colour pattern is not yet known. |
| Trigger and packaging overhead | Open: driver-sequenced "fast" exposures and native (non-FITS) transfer are untried. |

`./camera_test.py --throughput` times all of the open ones and prints the
frame time, the share of time the shutter is open, and the colour-pattern
check for each. Not yet run: it needs the camera to itself.

## Known weaknesses found by the tests

- The focus tracker judges change against the readings' own jitter. If the
  knob is turned in steps with a pause after each, the steps themselves
  inflate that jitter and some real changes are announced as "No change".
  Turning slowly and steadily avoids it. Found by `tests/test_night.py`.
