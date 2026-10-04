# How a picture is made

[Back to the README](../README.md)

`shoot.py` works on many short exposures, because a modest mount cannot hold
a star still for long. Each frame goes through:

```
raw frame → saved to disk → dark and flat applied → 2x2 Bayer cells to RGB
→ stars measured (sharpness, roundness, brightness, count)
→ rejected if cloud, wind or a knock spoiled it
→ lined up on the first frame: shift and rotation, to a fraction of a pixel
→ added to a running stack that leaves out satellite trails
→ web page updated
```

It prints a line per frame, such as `032 ACCEPT  FWHM 3.4  round 0.93  stars
74` or `033 REJECT  star brightness down 41% (cloud)`.

When the run ends, `restack.py` does the same job again with hindsight: it
measures every saved frame, judges each against the better half of the
session (so a half-cloudy night does not set a cloudy standard), keeps the
best 85% of those that pass, lines them up on the sharpest, weights each by
sharpness, roundness, transparency and noise, clips
outliers against the whole session's average, removes the sky gradient, and
writes `final.fits` and `final.jpg` in the session folder
(`frames/NAME/<date-time>/`).

Things worth knowing:

- **It uses the whole processor, and the camera never waits for it.** The
  per-frame work is shared between worker processes, one per physical core.
  If frames ever arrive faster than they can be stacked live, the extra ones
  are saved raw and marked `LATER`, and the quality pass picks them up.
  `--profile` on `shoot.py` or `restack.py` reports where the time went.
- **Frames are checked cheaply before the expensive work.** Quality is judged
  on a quarter-size image first; only frames that pass are calibrated in
  full, cleaned and lined up.
- **The 2x2 Bayer reduction is deliberate.** It halves the resolution to
  about 1.3 arcseconds per pixel on this telescope, which suits ordinary
  seeing; the sensor's native 0.66 would only record blur more finely.
- **Drift is used, not fought.** The mount is only sent back to the target
  once it has drifted a fifth of the frame. Until then the stars wander over
  different pixels, so the sensor's fixed pattern averages away.
- **Calibration frames make a visible difference** and are picked up
  automatically once made:

      ./calibrate.py dark --exposure 2 --gain 1500    # cap on; match your exposure and gain
      ./calibrate.py bias --gain 1500                 # cap on
      ./calibrate.py flat                             # cap off, evenly lit: twilight sky through a white T-shirt

  Masters are averaged with outliers left out. A flat is filed under the
  `setup` name in `config.toml`, because it only suits the arrangement it was
  taken with: change the name and take a new flat whenever the camera is
  rotated or refitted. This camera cannot report its temperature, so with a
  bias and a dark at the same gain the dark is scaled to each frame's own hot
  pixels instead of being matched by temperature.
- **Alignment is shift and rotation only**, no scale or lens distortion,
  which is enough for one session through one set of optics. `restack.py`
  reports how closely the stars matched; if that ever nears a pixel, it is
  time for more.

- **Raw frames are large**: about 20 MB each, so a 300-frame session is 6 GB.
  Delete a session's `light-*.fits` once you are happy with `final.fits`, or
  use `--no-save`.

## One picture from several sessions

Faint detail needs more light than one run usually collects. `./restack.py
M31 --all` stacks every saved M31 session into one picture, and `./restack.py
FOLDER FOLDER ...` stacks the ones named. The result goes to
`frames/M31/combined/` and `web/M31-final.jpg`.

- Sessions may differ in exposure length: frames are scaled to the first
  session's, and a longer frame counts for more because it is cleaner.
- They must share a gain; mixed gains are refused.
- The camera must not have been turned in the focuser between them. Frames
  that share fewer than eight stars with the reference are left out and
  counted in the report, so a turned session costs time but does not smear
  the picture.

Proven on made-up star fields; not yet on real sessions.
