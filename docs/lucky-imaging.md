# Imaging the Moon

The Moon is not a deep-sky target. It has no stars around it to plate-solve
or line frames up on. It moves against the stars by about its own width an
hour. The air bends each part of it differently from moment to moment. So it
has its own mode, `./ty moon`, built on the lucky-imaging engine `lucky.py`.

    ./ty moon --dry-run          is it up, how big a region, how many frames fit on the disk
    ./ty moon                    centre, expose, video in bursts, stack
    ./ty moon --frames 2000 --bursts 4 --keep 5 10 20 40
    ./ty moon --colour           natural colour rather than green detail
    ./ty moon --focus-check Capella   measure focus on a star field first

## What `./ty moon` does (moon.py)

1. **GoTo** the Moon from its ephemeris (`mount.py`, with the limits and the
   motion lock as for any GoTo). This moves the mount.
2. **Finds the disc in the camera's own picture** (`lunar.find_disc`): the
   bright region, then a circle fitted to its edge. The terminator lies inside
   the true circle, so the fit is repeated on the edge points on or outside
   the last circle until only the sunlit limb is left. That finds a
   crescent's centre as well as a full Moon's, and a disc cut by the frame's
   edge.
3. **Centres it from that picture.** The first time on each side of the pier
   it makes two test moves, 5′ east then 5′ north, to measure how a move on
   the sky shows in the picture (which way, and how many pixels an
   arcminute). The measurement is kept in `cache/moon_calibration.json`, so
   later nights skip it. Then it moves by the offset it sees until the disc
   is within 4 % of its radius of the middle, using `goto --aim-off` (the
   Moon's position plus an offset).
4. **Sets the exposure** (`lunar.exposure_for`) so the bright surface sits
   at 72 % of the scale with no more than 0.1 % of it at the top. It uses the
   shortest exposure that gets there, since a short one freezes the air, and
   raises the gain only past 30 ms.
5. **Reads only the region round the disc** (`lunar.roi`: the disc plus 8 %
   of its diameter each side). A smaller region is a faster video.
6. **Takes the video in bursts.** Between bursts it finds the disc again and
   moves the mount back onto it: the lunar hold. That replaces a lunar
   tracking rate, which the handset does not offer over its lead.
7. **Stacks it** with `lucky.py`.

The number of frames is cut to what fits on the disk with 3 GB left free:
frames are kept 8 bits a pixel (the top 8 of the camera's 12), so a
2,900-pixel square is about 8.4 MB a frame. Focus is not done here: the
motor can only walk in (`focuser.md`), so a soft focus needs the drawtube
set a touch out by hand. `--focus-check STAR` measures focus first and stops
if it is soft.

## The engine (lucky.py)

    ./ty lucky capture Moon --frames 1000 --exposure 0.01 --roi X Y W H
    ./ty lucky stack frames/lucky/Moon-DATE-TIME.ser --keep 5 10 20 40 [--colour]

`capture` puts the camera in its video mode (`AltairCamera.video`: frames
back to back rather than one triggered exposure each) and writes the raw
Bayer frames to a SER file in `frames/lucky/`, the format every planetary
stacker reads. A JSON file beside it records what was asked and what came:
exposure, gain, region, frames a second, and frames the camera dropped
(from gaps in its frame numbers). A frame goes to the status page every 3 s,
and `web/lucky.json` says the stage (capturing, ranking, stacking, done) for
the stream's Moon panel.

`stack`:

1. **The detail picture.** It uses the green pixels, which are half the
   sensor's, and fills in each red or blue pixel with the mean of the four
   greens beside it. This way the colour pattern never shows up as detail
   for the sharpness measure or the alignment. `--colour` instead makes the
   mosaic into colour and bends every colour by the green's alignment. The
   Moon's colours are faint but real.
2. **Ranks** every frame by its fine detail: the spread of the Laplacian on
   a lightly smoothed copy, over the bright surface.
3. **Builds a reference** from the best frames, each moved onto the best and
   averaged. The air bends each frame a different way, so their average has
   the surface's true shape.
4. **Places alignment points where there is detail.** It uses a grid of
   96-pixel patches 48 apart, keeping those on the bright surface whose
   detail is above half the median. If there are more than 600, the 600 with
   the most detail are kept. Smooth maria and black sky cost nothing.
5. **Chooses frames part by part.** Each point ranks every frame by the
   sharpness of its own patch and takes its own best share, because the air
   is sharp over one crater and blurred over the next at the same moment.
   Only frames chosen somewhere are lined up and added, and a frame adds to
   each part of the picture as much as it was chosen there.
6. **Lines each frame up** as a whole (phase correlation on a quarter-size
   copy), then patch by patch to a fraction of a pixel. A point is trusted
   only when its correlation peak stands at least 4 standard deviations
   above the rest, its shift is within 24 pixels, and it agrees with the
   median of its trusted neighbours to within 3 pixels. The others take the
   bend of the points around them, so one bad match cannot pull the picture
   like a rubber sheet.
7. **Stacks several shares at once**, 5, 10, 20 and 40 % by default, since
   how many frames are worth keeping depends on the seeing. Each is kept
   unsharpened and sharpened (three scales, like a planetary stacker's
   wavelets), as FITS and as a picture: `NAME.bestK.fits`,
   `NAME.bestK.sharp.fits`, `NAME.bestK.jpg` and `NAME.bestK.sharp.jpg`. The
   share with the sharpest result goes to the status page. `NAME.stack.json`
   records what was done.

`planet.py` does the same job for planets with single triggered frames and
whole-frame alignment. It is not built on this engine yet.

Never the Sun: nothing here knows whether a solar filter is fitted, and
`mount.py` refuses to point near it.

## The first result, 24 October 2026

The 97 %-lit Moon, 31° up through thin haze: 300 frames of 20 ms at gain
100, from a 2944-pixel square of the sensor, at 4.2 frames a second
(readout Speed 0, which the camera needs for long frames,
`docs/nights/2026-10-21/camera-stalls.md`). That was the first version of
`lucky.py`, before the moves above: whole-frame ranking, the best 60 kept,
1329 alignment points, and a grey picture with every colour scaled to the
green's level. The stack shows no stripes, and the ray systems and small
craters are much crisper than the deep-sky stack of the same night. The
centring was done by hand-reckoned aim-offs and a fixed exposure, and the
Moon drifted toward the region's edge in the 10 minutes because the mount
tracks at the stars' rate. `./ty moon` does those three from the picture.

Not yet tried on the sky: `./ty moon` itself (centring, the lunar hold,
the automatic exposure and region), the local frame choice, and readout
speeds faster than Speed 0 for short frames.
