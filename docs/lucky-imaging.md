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

## The mineral Moon (mineral.py)

    ./ty moon --mineral                       take the videos for it and make it
    ./ty lucky mineral COLOUR.ser ... [--detail DETAIL.ser] [--strength mild|standard|strong|auto|N]
    ./ty lucky stack VIDEO.ser --colour --flat   a colour stack divided by the flat
    ./ty lucky mineral COLOUR.ser ... --compare-flats none master FLAT.fits   which flat makes the videos agree best
    ./ty lucky mineral COLOUR.ser ... --slope mapped --no-send   the slope fitted on mapped highlands, not sent
    ./ty lucky reference CLEMENTINE.tif       the spacecraft colour map it is checked against, made small

The Moon's colours are real but faint, a percent or two either way.
Spacecraft maps, made through narrow filters, show many titanium-rich seas
as bluer, and fresh ground as bluer than old. This camera's broad colours
can show some of those differences between regions, but cannot tell how
much titanium or iron there is (Earth and Space Science 2023,
doi:10.1029/2022EA002710). So the mineral Moon is enhanced colour that goes
with composition and maturity, and is never read as an abundance.

**Whose colours.** The blue and red are the Hypercam 183C's: the IMX183's
Bayer filters, broad and overlapping. Two makers' EMVA 1288 reports for
cameras on the same sensor give its quantum efficiency at their test
wavelengths: blue 61 to 63 % at 460 to 467 nm, green 68 % at 530 to 533 nm,
red 43 to 50 % at 625 to 630 nm
([FLIR BFS-U3-200S6C](https://softwareservices.flir.com/BFS-U3-200S6-BD2/latest/EMVA/EMVA.html),
[Baumer VCXG.2-201C](https://media.baumer.com/mamfile_1963053.pdf)). No full
curve is published. So its B/R is this camera's own index, spanning about
460 to 625 nm, not Clementine's 415/750 nm ratio or Galileo's filters; the
files say so (`BANDS` in their FITS headers, `bands` in the json).

**Taking it (`./ty moon --mineral`).** First the usual detail video (8-bit,
fast). Then `--colour-videos` (3) colour videos of `--colour-frames` (200)
each. They are 16-bit, holding the camera's 12 bits whole, with the SER
header saying 12. In 8 bits the Moon's colours are only a step or two of
the scale. They are exposed to 55 % of the scale rather than 72 % so that
nothing clips, and the disc is put somewhere else across the sensor in each
(`dither_steps`): to the corners in turn, at 80 % of the room across and
down, so every two videos are apart across, down or both. A pattern of the
sensor's, from a flat's error or a colour gradient, then lands on a
different part of the Moon each time and fails the repeat test below, and
`follows` says whether the colour stays with the Moon or the sensor. Each colour video is stacked with `--flat`,
the flat from `calibrate.py flat` cut to the video's region. Each colour's
response changing slowly across the sensor would otherwise be turned up
with the rest. Then the mineral Moon is made from them. Turning the camera
in the focuser between nights does the same for rotation. That needs
hands, and the check below compares nights.

**Making it.** For each colour stack:

1. Red and blue are moved onto green, undoing the air's spread.
2. Pixels within 80 % of the white level are left out of that stack, fading
   out over 12 pixels. The white level is from the stack's record or the
   SER header's depth, never from the file's 8 or 16 bits.
3. The colour is worked out on 2×2 blocks, as log ratios of each colour to
   the three's mean.
4. The slope across the disc is taken off, fitted to the brighter half of
   the disc. `--slope mapped` fits it to the mapped highlands instead
   (`lunar.HIGHLANDS`, 8° round each). On 30 October 2026 that agreed worse
   with Clementine's map (rank correlation 0.19 against 0.38) and between
   the videos: the mapped points are all central and southern, so the
   slope was carried across the north from them. The brighter half takes
   in rays and lit seas as well as uplands; the json says which was used.

Across the stacks, each pixel's blue-against-orange is compared from video
to video, as a consistency score: the colour over its standard error
between the videos. Colour scoring under 2 is turned down in proportion.
With two or three videos, smoothed and sharing the optics and the air, the
score measures agreement; it is not a statistical significance, and it is
never quoted as "sigma". Then each video is left out in turn: where the
colour changes sign, or by more than half, without some one video (among
pixels with more than the typical colour), it is marked less sure. The result is turned up by a stated factor: mild 8,
standard 15, strong 25, a number, or auto (the strongest 1 % to 35 % of
the brightness).

**What it writes**, beside the first colour video as `NAME-mineral`:

| File | What |
|---|---|
| `.jpg`, `.fits` | Blue against orange only: the safe picture |
| `-full.jpg` | Every colour kept: exploratory, as the camera's green-magenta tint may not all be gone |
| `-balanced.jpg` | The colour as it is, its three colours balanced to a grey Moon, on the sharpened detail. Balanced, not calibrated: the Moon's mean is made grey |
| `-ratios.fits` | log B/R, R/G and B/G after calibration |
| `-ratio-br.jpg` | log B/R as grey, brighter bluer |
| `-confidence.jpg` | Green robust; amber faint, near the limb or terminator (Sun or view under 15°), not repeated, or changed by leaving one video out; red clipped or off the Moon |
| `-difference.fits` | The first two videos' blue-orange, one less the other |
| `.json` | The colour as measured (the strongest 1 %, the spread) and the factor it was turned up by, each video's white level, clipping and flat, how well the videos agree two by two and with each left out, whether the colour follows the Moon or the sensor, where the slope was fitted, the picture's orientation with its margin and plate-solve check, the check against the seas, and the comparison with the spacecraft map |
| `-flats.json` | With `--compare-flats`: for each flat, how well the videos agree, how much is sure, and the check against the seas |

**The check against the seas.** `lunar.orientation` is the IAU model of
the Moon's pole and prime meridian (Archinal et al. 2011). `lunar.view`
turns it into the point under us and the point under the Sun. `fit_turn`
finds how the picture lies on the sky: the turn from where the terminator
is, and which way round from the seas, which must come out darker than the
uplands once the light's angle is allowed for. That puts every named sea
on the picture. Spacecraft colour maps say Mare Tranquillitatis is bluer
than Mare Serenitatis and than the uplands (NASA's Galileo colour Moon).
The json says whether this picture agrees, by how much, in how many of the
videos, whether it holds with any one video left out, and its consistency
score.

**Checking the orientation.** The seas help choose the orientation, and
the same seas are then checked, so the orientation is checked by something
else where it can be. The json keeps the seas' score both ways round and
the margin between them. If a plate solve of the same night is within six
hours (`cache/last_solve.json`), its CD matrix gives the camera's angle on
the sky (`lunar.turn_from_solve`), turned 180° if the mount was on the
other side of the meridian. Without a solve, a margin under 1.1 marks the
orientation, and so the seas' check, not sure.

**Against a spacecraft map.** `./ty lucky reference FILE.tif` reads USGS's
Clementine UVVIS warped colour-ratio mosaic
([the record](https://astrogeology.usgs.gov/search/map/moon_clementine_uvvis_warped_color_ratio_mosaic_200m),
4.46 GB, 200 m a pixel, public domain; red 750/415 nm, blue 415/750) a
strip at a time and keeps its blue less red on 0.25° cells in
`cache/moon-colour-reference.npz` (11 MB). The mineral Moon then looks up
each sure pixel's latitude and longitude on it, averages both over 2°
cells and compares them by rank, and puts the named seas in order by each.

**Which flat.** `--compare-flats none master FLAT.fits` stacks the colour
videos again with each flat (in memory: the stacks on disk are left alone)
and says how well the videos then agree with each. A right flat makes the
Moon's colour repeat better; a wrong one adds a pattern that stays on the
sensor.

Not done:

- **Correcting the colour for the light's angle.** It would need each of
  this camera's colours' phase reddening, which has not been measured.
- **Calibrated colour.** That needs this camera's full spectral response,
  which no maker publishes, or a colour reference measured through it.

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

Restacked the next morning with the new stacker (each part from the frames
sharpest there, green detail, the best 5 to 40 %): the pixel noise halved,
but Tycho's rim and rays were softer than the first stack's every-pixel
picture. Filling in the greens costs detail at this sampling. The first
stack stays the night's picture, and `--pixels all` puts the every-pixel
picture back within reach of the new stacker.

Not yet tried on the sky: `./ty moon` itself (centring, the lunar hold,
the automatic exposure and region), the local frame choice, and readout
speeds faster than Speed 0 for short frames.

## The first mineral Moon, 30 October 2026

Three 8-bit videos of the 80 %-lit waning Moon, 2,513 frames
([the record](nights/2026-10-30/mineral-moon.md)). Mare Tranquillitatis came
out bluer than Mare Serenitatis by 2.0 % and than the uplands by 2.3 %, in
all three videos and with any one left out, as the spacecraft maps have it.
The orientation found from the picture (213°) agreed with the night's plate
solve (212.9°). Against Clementine's whole colour map the agreement is weak
so far: rank correlation 0.38 over 2,739 cells of 2°.
