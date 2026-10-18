# Naming the satellite in a frame

[README](../README.md) · Guides: [First night](first-night.md) · [Setup](setup.md) · [Imaging](imaging.md) · [Calibration](calibration.md) · [Focus](focus.md) · Science: [Discovery](discovery.md) · [Validation](validation.md) · [Data](data.md) · Developers: [Contributing](../CONTRIBUTING.md) · [Agents](agents/README.md)

Built on 18 October 2026 as `streak.py` (`ty streak`), from this
specification and its worked example of 13 October. What it found the first
time it was used is under "18 October 2026" below; what is still to do is
under "Not done yet".

## What it is for

A straight streak across a frame is nearly always a satellite. The person
sees it on the status page and asks what it was. telescopeyoke already knows
where the frame was pointing, when, and from where, which is everything
needed to answer:

    ./streak.py                          the newest frame with a streak in it
    ./streak.py frames/NGC7000/.../light-0001.fits

with an answer of this kind (the figures here are made up):

    A streak 0.33° long in light-0001.fits, taken 20:53:54.
    ONEWEB-0331 passed 0.06° from it at 20:53:53, 1,215 km away, moving
    0.34° a second: the streak's length and direction fit.

A streak that no satellite accounts for is said to be just that. It may be a
meteor, an aircraft or a satellite missing from the list, and the command
does not guess which.

## What happened on 13 October 2026

The first 2 s frame of a run on NGC 7000 had a streak 0.33° long, even in
brightness, with both ends inside the frame, which is 1.0° by 0.67°. Done by hand:

1. `solve.py --file` gave the frame's centre, scale and rotation.
2. The orbits of the 15,932 active satellites came from CelesTrak.
3. Each was placed in the sky as seen from the site, second by second, for
   50 seconds round the frame.

One satellite came within 2° of the frame's centre in that time: ONEWEB-0331,
0.65° from the centre at the nearest whole second, 20:53:53, at 1,215 km and
moving about 0.34° a second. The streak's middle is 0.29° from the centre.
So it is the only candidate, and not yet a proven match: a path 0.65° from
the centre would at most clip a corner of a frame this size, and placing it
second by second leaves a sixth of a degree of doubt along the track.

(As first written this said the streak was 0.65° long and 0.59° from the
centre, and that its length agreed with the satellite's height. Those took
the plate solver's 1.32 arcseconds a pixel, which is for the half-size colour
picture, as the sensor's 0.66. The frame is half the size they assumed.)

What that did not settle:

- **The time.** The frame landed at 20:54:09, some 15 seconds after the
  satellite went through. The first frame of a run does arrive about that
  late (seen in `focus.py` the same night), but the frame carries no time of
  its own, so this was an inference.
- **The direction.** The streak's direction on the sky was not compared with
  the satellite's, because the solve's answer does not say whether the image
  is mirrored.

Both are fixed by the two changes under "What has to change first".

## How it works

1. **Find the streak.** In a frame binned 4x4 with the stars masked out, look
   for a thin straight line much longer than any star trail: a Hough
   transform, or a fit through the brightest connected run of pixels. Give
   back its two ends in pixels, or nothing. A streak that leaves the frame at
   an edge has an end that is "at least here".
2. **Put its ends on the sky.** Plate-solve the frame (`solve.py`), and turn
   the two ends into right ascension and declination. This needs the whole
   solution, mirror included, not only centre, scale and rotation.
3. **Know when.** The exposure's start and length, from the frame.
4. **Ask which satellites were there.** For every satellite in the list,
   work out its direction from the site at the start and end of the exposure
   (SGP4, then from the true equator of date to the frame's coordinates).
   Keep those whose path in that time lies within a tolerance of the streak.
5. **Judge the fit.** A candidate fits when its path is within about 0.2° of
   the streak, runs along it within about 5°, and covers about the same
   length. The time is given a few seconds either way, since orbits a day or
   two old are a second or so out along the track. Say how good each fit is;
   never name a satellite on position alone when two pass.
6. **Say so**, in a sentence, and as `--json`.

## 18 October 2026: the first use

Frame 4 of the M31-P6 panel (16 s from 21:47:59.4 UTC) had a streak 0.17°
long, entering at the top edge and ending sharply inside the frame, even in
brightness along its length. The frame's own start time was used. Against
that evening's orbits, fetched eight minutes after the frame, none of the
16,755 active satellites fits: the nearest, CENTISPACE-2 S3, passed 0.45°
from the streak's middle a minute before the shutter opened, in the Earth's
shadow. The command said so and did not guess.

Done by hand afterwards, and not part of the command: the frames before and
after it (2, 3, 5 and 6) have nothing on that line, so whatever it was
crossed during that one exposure. The streak's line extended passes 1.1°
from the radiant of the epsilon Geminids (RA 102°, Dec +27°), which peak
that night, with the radiant behind the end inside the frame. That fits a
meteor that lit inside the frame and flew out of it. The Orionids' radiant
is 13.8° off the line. CelesTrak's "active" list leaves out rocket bodies
and debris, so a dead satellite or a spent stage is not ruled out.

The 13 October frame (light-0001 of that NGC 7000 run) was run again. It
does carry its own start, 19:54:06.9 UTC from the INDI driver, which the
worked example above missed. With orbits fetched five days after the frame
(the only ones kept), ONEWEB-0331 is still the nearest, at 0.34° a second
and 1,205 km, but it does not fit: its path runs 14° from the streak and
0.41° off it, and it reached the streak 3 to 4 seconds before the shutter
opened. Five days is enough to put it seconds out along its path, so this
neither confirms it nor rules it out; the command says it fits nothing and
warns about the orbits' age.

## What had to change first

Both turned out done: frames carry DATE-OBS, the start of the exposure
(the Altair library writes it, and the INDI driver did on 13 October), and
`solve.py` keeps the CD matrix. As written before they were:

- **Frames must record when they were exposed.** `camera.py` should write
  the exposure's start (UTC, to a tenth of a second) and its real length into
  each frame's header, and `shoot.py` into `frames.jsonl`. Today neither has
  it. The 183C is known to expose for about 0.63 of the time asked on this
  laptop (`docs/validation.md`), which matters here: the streak's length
  divided by the real exposure is the satellite's speed.
- **`solve.py` must give the full solution.** The plate solver writes a WCS;
  keep it, so a pixel can be turned into a place in the sky.
- **One new dependency: `sgp4`.** It is small, and nothing in astropy does
  its job. It is needed only by this command, so import it there and say
  plainly when it is missing.

## Where the orbits come from

CelesTrak's "active" list: free, no key, about 2.5 MB. It is fetched as CSV
(OMM) rather than two-line elements, because catalogue numbers have passed
99,999, which two-line elements cannot carry. Kept under
`config.DATA / "cache" / "satellites"` by the time it was fetched, and a copy
up to a day from the frame is used. A frame from an earlier night needs the orbits of that
night: the list in the cache when the frame was taken is good, today's is
not, and the command should say when the orbits are too far from the frame's
date to trust.

## Where it shows

- `streak.py`, and `ty streak`, a read-only view.
- The status page: a line under a picture whose newest frame had a streak.
- `shoot.py` already sets aside frames that would spoil a stack. A streak
  frame can be named in the run's summary ("frame 1: ONEWEB-0331").

A `--json` answer means a schema in `schemas/`, the function, and
`tests/test_interface.py` together.

## Tests

- The streak finder, on made frames: a line among stars, a line off one
  edge, stars alone, a star trail from poor tracking (not a streak).
- The matching, with a made-up orbit placed to cross a made-up frame, and
  one placed to miss it; and two satellites near together, where neither
  must be named with confidence.
- The 13 October frame, kept small, with that night's orbit for ONEWEB-0331
  beside it, as a test that runs without the network.

## Not done yet

- The status page's line under the picture, and the streak frame named in
  `shoot.py`'s run summary.
- Rocket bodies and debris: CelesTrak's "active" list has payloads only. The
  whole catalogue needs a Space-Track account.
- The test on the 13 October frame with that night's orbits: none were kept.
- Saying when a streak lines up with an active meteor shower's radiant (done
  by hand on 18 October).

## Not in this

Tracking a satellite, predicting passes, or steering clear of them. This
names what has already crossed a frame.
