# How a picture is made

[README](../README.md) · Guides: [First night](first-night.md) · [Setup](setup.md) · [Imaging](imaging.md) · [Calibration](calibration.md) · [Focus](focus.md) · Science: [Discovery](discovery.md) · [Validation](validation.md) · [Data](data.md) · Developers: [Contributing](../CONTRIBUTING.md) · [Agents](agents/README.md)

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
- **One run at a time.** A run holds the mount and camera (a lock in
  `cache/imaging.lock`, released however the run ends); a second run
  refuses to start until the first finishes or is stopped (`./ty run stop`).
- **A rejected frame is taken again.** With `--frames N`, each frame thrown
  out (cloud, a knock, a light) is replaced by one more, up to a quarter
  more than asked, so a run ends with as many good frames as it can. After
  three rejected in a row it stops retaking: that is cloud, not bad luck.
- **The black level has to sit above zero.** The camera's offset (`offset`
  under `[camera]`, also in the Settings screen) lifts every reading so the
  sky's grain is not cut off at zero; 46 gives the Altair 183C about 45 with
  the cap on. On 18 October 2026 it was 0: a bias read 1, the calibrated
  sky came out at -55, and the cloud check threw out 16 of 19 clear frames.
  `calibrate.py bias` now refuses a bias under 10 and says to raise the
  offset. Change the offset and the bias and darks must be taken again.
- **The camera's row stripes are taken out of every frame** before it is
  stacked (`stacking.destripe`): each row of each Bayer site is levelled
  against the rows round it, in four sections across the frame, since a
  stripe can be green at one side and magenta at the other. Part of the
  pattern is the same in every frame, so stacking alone never averaged it
  away: the green bands in all the stacks of 19 October 2026. The bias and
  dark have their row levels evened when loaded, so a master averaged from
  20 frames no longer stamps its own stripes into every light. Each row's
  level is taken from its sky alone: a first levelling finds where a
  galaxy, nebula or glow is, and that light is left out of the second.
  Measured from every pixel, as at first, a row's level followed a galaxy
  narrower than about 100 rows, and the levelling took real light (a
  synthetic galaxy 280 rows across lost 12% of its core, one 140 rows
  across 38%; now about 2% and 4%). Anything broader, a gradient or a
  galaxy filling the frame, is left alone. `depth.py SESSION
  --destripe-check` plants stars in a session's raw frames and measures
  them with and without the correction. What other owners of this camera
  have found, and what to try next: `docs/banding.md`.
- **Alignment is shift and rotation only**, no scale or lens distortion,
  which is enough for one session through one set of optics. `restack.py`
  reports how closely the stars matched; if that ever nears a pixel, it is
  time for more.

- **Raw frames are large**: about 20 MB each, so a 300-frame session is 6 GB.
  Delete a session's `light-*.fits` once you are happy with `final.fits`, or
  use `--no-save`.

## Mosaics: an object bigger than the frame

The frame is 1.0° x 0.67°; M31 and the North America Nebula are two or
three times that. `./mosaic.py M31 3x1` lays three panels along the
camera's long side, overlapping by 15%, turned as the last plate solve found
the camera, and keeps their centres in `mosaics/m31.json`. With no grid,
`./mosaic.py NGC7000` suggests the smallest one that covers the catalogue
size. Each panel is then a target like any other: `./mount.py goto M31-P1
--dry-run`, `./shoot.py M31-P1`, `./restack.py M31-P1 --all`, with its
frames under `frames/M31-P1/`.

- The centres are worked out once, so a panel shot on a later night lands
  where it did before, even if the camera has been turned since. Keep the
  camera's turn the same for the panels to tile neatly; `--replace` starts a
  new plan.
- `./stitch.py M31` joins the panels into one picture from every session of
  every night (`--with-whole` adds the object taken whole): each session stacked on its
  own and placed by its own plate solve, so a camera turned between nights
  changes nothing, then resampled onto one grid, the skies levelled and the
  overlaps blended, deeper sessions counting more. A mosaic patrol runs it
  when it ends, so the picture grows night by night; `--on desktop` stacks
  any session that has no stack yet on the desktop.
- Patrolled panel by panel on the real mount since 17 October 2026.

## Dithering

`./shoot.py M31 --frames 0 --dither 15` re-centres every 15 frames on a point
1.5′ or less off the target, in a different direction each time: a
plate-solved GoTo (`mount.py goto_target` with an offset), so it keeps every
check a re-centre has. The stars move tens of pixels across the sensor
between groups of frames, so the camera's own pattern (hot pixels, column
striping, and anything a dark or flat misses) falls on different stars and
averages away instead of building up. Each dither costs half a minute or
so. It cannot go with `--no-recentre`. Proven against the simulator only.

## A stack for finding faint stars

`./restack.py M31 --discovery` makes a second stack beside the picture,
`discovery.fits`, built to show the faintest point of light rather than to
look its best. Every frame that passes the checks is considered; each counts
by transparency / (noise² x star width²), with no floor and no ceiling, and
the poorest are left out wherever their wider stars would cost a faint star
more than their light gives. The picture, `final.fits` and `restack.json`
are left as they were; its record is `discovery.json`. `./depth.py` measures
either stack, so the two can be compared (`docs/discovery.md`).

## One picture from several sessions

Faint detail needs more light than one run usually collects. `./restack.py
M31 --all` stacks every saved M31 session into one picture, and `./restack.py
FOLDER FOLDER ...` stacks the ones named. The result goes to
`frames/M31/combined/` and `web/M31-final.jpg`.

- Sessions may differ in exposure length: frames are scaled to the first
  session's, and a longer frame counts for more because it is cleaner.
- They must share a gain; mixed gains are refused.
- Frames taken after the mount has swung to the other side of the meridian
  arrive upside down; they are recognised and turned back.
- The camera must not have been turned in the focuser between them. Frames
  that share fewer than eight stars with the reference are left out and
  counted in the report, so a turned session costs time but does not smear
  the picture.

Proven on made-up star fields; not yet on real sessions.
