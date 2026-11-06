# Autoguiding

[README](../README.md) · [All docs](README.md) · Guides: [First night](first-night.md) · [Setup](setup.md) · [Imaging](imaging.md) · [Calibration](calibration.md) · [Focus](focus.md) · Science: [Discovery](discovery.md) · [Results](results.md) · [Validation](validation.md) · [Data](data.md) · Developers: [Contributing](../CONTRIBUTING.md) · [Agents](agents/README.md)

**Specification, 6 November 2026. Not built.** This says what autoguiding
should do on this rig, what has to change around it, and how the first clear
night proves it. Figures measured on this rig say when; figures from other
people say whose; the rest are starting values to be tuned on the sky.

## Why

Unguided, the EQ3 Pro keeps stars round for tens of seconds, and the 183M
runs short subs. Guiding should allow 2 to 5 minute subs. That gives fewer
frames, less read noise per hour, and narrowband (Ha, SII, OIII) that is
worth doing. Gary, who sold us the rig, images that way: an hour per filter
in 3-minute subs, guided.

Gary's warning comes with it. Once guiding holds the stars on the same
pixels, the sensor's fixed pattern noise "walks" across a long stack. So
guiding and dithering are one piece of work here, never guiding alone.

## What is proven already

| What | Result | When |
|---|---|---|
| Guide camera | Altair GPCAM MT9M034M opens through libaltaircamlegacy 1.24 and takes frames (`./guidecam.py snap`) | 2 and 6 Nov 2026 |
| ST4 lead, camera to mount | `./guidecam.py pulse`: 5 s pulses moved Dec +35.7" (north) and -35.7" (south), and RA +32.8" (east) and -38.9" (west) beyond the tracking-only reading. All four work | 6 Nov 2026 |
| Guide rate | About 7.1"/s, just under 0.5x sidereal (15.04"/s), the handset's setting | 6 Nov 2026 |
| Pulses from the camera need no serial port | The ST4 lead goes from the guide camera to the mount, not through the handset, so a guider never competes with `mount.py` and `shoot.py` for `/dev/ttyUSB0` | by design |

## What is not ready

| What | State |
|---|---|
| Guide camera and filter wheel together | On the unpowered Trust hub off the 183M's internal hub, with both plugged in, the wheel never finishes its power-up turn and the guide camera stops sending frames. Each works alone (6 Nov 2026). Starlight Xpress recommends a powered hub "to ensure that the wheel motor has sufficient torque" [5] |
| Guide scope focus | Not done |
| Guide scope fitted firmly, and the balance with it | Not checked on the sky |
| Guiding software | None. No loop, no calibration, no dithering by the guider |
| Long darks for the 183M at -5 °C | None at 120 to 300 s |

## The numbers

| | Guide camera on the 50 mm Orion Mini | 183M on the 150P with the 0.9x corrector |
|---|---|---|
| Focal length | 162 mm | 675 mm |
| Pixel | 3.75 µm | 2.4 µm (binned 2x2: 4.8 µm) |
| Scale | **4.77"/px** | 0.73"/px (binned 2x2: **1.47"/px**) |
| Field | 1.70° x 1.27° (1280 x 960) | 1.11° x 0.74° |

- **Guide ratio:** 6.5 against the 183M unbinned and 3.3 binned. Both are
  comfortably within the usual rule of thumb (forum advice says under 5 to
  10 [2]). A centroid good to about 0.1 guide pixel is 0.5", a third of a
  binned imaging pixel.
- **One guide pixel at the guide rate:** 4.77" / 7.1"/s, about **0.67 s** of
  pulse.

## The guiding command

`./guidecam.py guide`, a project command like the rest. PHD2 is not
installed. The project's rule is that anything used every night is a
project command before its first use, and the photometric hold in
`shoot.py` already contains a guider's hard parts. That hold learns each
direction separately, takes up Dec gear slack on a reversal, corrects only
part of each error, and gives up when corrections stop helping. The guider
should share that code, not copy it.

It runs as its own process, in the background, beside `shoot.py`. The two
talk through one small state file, `config.DATA/cache/guide.json`, and an
order file, the way `shoot.tell()` works. The guide camera is not the
imaging camera, so `keeper.py` holding the 183M open is untouched.

### 1. Find a star

- Guide exposure: 2 s to start, so seeing averages out. Allowed range is
  0.5 to 4 s.
- Pick the brightest star that is not saturated (peak below about 230 of
  255), at least 30 px from the edge, with no brighter neighbour within
  15 px, and a signal-to-noise ratio above 10. Report its SNR and HFD.
- Centroid: the weighted centre of mass over a small box around the star,
  after taking off the median background. Expect about 0.1 px.
- No star: retry every 10 s and say so, the way the other steps retry
  through cloud.

### 2. Calibrate

- Pulse west in steps, measuring the star after each, until it has moved
  about 25 guide pixels or 15 steps have been sent. Then pulse east to come
  back. Then do the same north and south, taking up Dec slack first with
  north pulses until the star starts to move. This follows PHD2's practice
  [1][3].
- Step length: aim for 10 to 15 steps over the whole move, rounded up to
  the nearest 50 ms (S&T's guidance; the PHD2 developers' calculator).
  At 7.1"/s and Dec 0 that is about 1000 ms. RA motion shrinks by cos(Dec),
  so steps lengthen as 1/cos(Dec), capped at 3000 ms.
- From the two lines, record:
  - the camera's angle on the sky;
  - RA and Dec rates in px/s;
  - whether the axes are at right angles (a warning if they are more than
    10° off, as PHD2 warns).
- Keep the calibration in `config.DATA/cache/guide-cal.json`, labelled with
  the Dec, the side of the pier and the light path, as for the plate solves.
- Reuse it on later nights while the guide camera has not turned:
  - scale the RA rate by cos(Dec) for the target;
  - reverse Dec after a swing over the pole.

  Verify the reuse with one short north and one short west pulse at the
  start of each run. A full calibration happens only when that check
  fails.
- Best calibrated near Dec 0 and near the meridian. Accuracy falls off
  towards the pole (forum consensus [4]). Calibrating on the target is
  acceptable below Dec +60°.

### 3. Guide

Each guide frame:

1. Measure the star's offset from the lock position.
2. Convert it to RA and Dec errors with the calibration.
3. Compute each axis's correction, apply the per-axis rules below, and
   convert to a pulse length.
4. Send both pulses: RA and Dec at once, through the camera's
   `ST4PlusGuide`, one call per axis.

Starting settings, modelled on PHD2's defaults [1]:

| Axis | Algorithm | Start |
|---|---|---|
| RA | Hysteresis | Aggression 70 %, hysteresis 10 %, minimum move 0.15 guide px |
| Dec | Resist switch | Aggression 100 %, minimum move 0.20 guide px, a reversal only after 3 frames the same way, fast switch for an error above 3x the minimum move |

- **Longest pulse:** 2500 ms per axis per frame. A bigger error is taken
  back over several frames.
- **Dec backlash:** this is the EQ3 Pro's known weakness. Forum owners
  report Guiding Assistant backlash measurements in the thousands of
  milliseconds [6].
  - Measure it during calibration, as the hold already does.
  - A Dec reversal starts with the slack taken up.
  - If guiding in Dec flips back and forth, switch Dec to one direction
    only: correct only the way the polar drift pushes. The drift model in
    `tracking.py` already predicts which way that is.
  - PHD2's own advice is not to use the mount's backlash setting [6].
- **Star lost** (no star, or SNR below 6) for 3 frames running:
  - stop pulsing;
  - write `lost` to the state file;
  - keep looking;
  - resume when the star returns within 10 px of the lock position.
- **Saturation or a jump of more than 8 px in one frame:** ignore that
  frame, treating it as a passing satellite, a bird or a cosmic ray.

### 4. What the state file says

The guider writes the state file every frame, for `shoot.py`, the 8080 page
and the night's notes. It holds:

- the state: `calibrating`, `guiding`, `settling`, `lost`, `paused` or
  `stopped`;
- the star's position and SNR;
- the last error in RA and Dec, in arcseconds;
- the running RMS in RA, Dec and total over the last 30 frames, in
  arcseconds;
- the pulses sent;
- the lock position;
- the time.

The guider also appends every frame to `guide-DATE.jsonl` beside the
session's frames, for later analysis.

### 5. Orders it takes

`pause`, `resume`, `dither DX DY` (guide px), `relock` (find the star
again after a GoTo), `stop`. `shoot.py` sends them.

## Changes to `shoot.py`

- **`--guide`:** starts the guider, or uses one already running. While it
  guides:
  - the photometric hold is off, and the drift assist's Dec trims are off;
  - the Dec creep set by GoTo stays, which leaves the guider less to do;
  - `--guide` and `--hold` are refused together.
- **Each frame waits for "settled":** before an exposure starts, the guider
  must report `guiding` with an error under 1.5 guide px (about 7") for
  3 s, or 30 s pass, after which the frame is taken anyway and marked.
  This mirrors PHD2's settle tolerance, minimum time and timeout [2].
- **Headers:** `GUIDED`, and `GUIDERMS` (the guider's total RMS in
  arcseconds over the exposure).
- **Frames taken while guiding was `lost`:** kept, marked, and judged by
  the usual frame checks. They are not thrown away blind.
- **GoTo, re-centre, filter change, swing over the pole:**
  1. send `pause` first, then `relock` after;
  2. after a swing over the pole, reverse the calibration's Dec;
  3. if the reuse check fails, run a full calibration.
- **Dithering while guided:** move the guider's lock position, never a
  GoTo. Today's dither is a 1.5' GoTo every N frames, which would throw the
  guide star off the lock. The dither is random, between half and all of a
  set size. Start at 8 imaging pixels binned (about 12", or 2.5 guide px);
  forum practice is 5 to 10 imaging pixels [2]. Dither every frame for
  subs of 2 minutes or more, every 2 to 3 frames for shorter. Each dither
  waits for "settled".
- **Exposure:** a guided run's default sub goes to 120 s in L, R, G and B,
  and 300 s in Ha, SII and OIII, through the plan's per-filter blocks. The
  frame checks must not treat 300 s frames as if they were 15 s ones:
  - drift limits are in pixels per frame, not per second;
  - one rejected frame now costs 5 minutes, so cloud handling stops on the
    first starless frame, not after several.

### The four things every change to a night's imaging must say

- **Framing:** better. The guide star holds the field to about a pixel
  between re-centres, and dithers are kept small. Across filters, the lock
  position and the plate-solved re-centre keep each filter on the same
  framing. Filters drifting apart is the 5 November M33 failure; the spec
  must not repeat it.
- **Sensor temperature:** unchanged. The 183M stays open and cold under
  `keeper.py`, and the guide camera has no cooler.
- **Minutes lost:**
  - calibration: about 3 minutes once per night, or under a minute with a
    reused calibration;
  - each dither: the settle time, about 5 to 15 s;
  - each re-lock after a GoTo: about 10 s.

  Against that, there are far fewer frames to read out and reject.
- **Mount safety:**
  - pulses are arcseconds a second, at most 2.5 s each;
  - the guider refuses to start or pulse while `MOTION_LOCKED` exists;
  - it sends an ST4 stop on every exit, crash included;
  - it pauses during every slew;
  - it stops when the total correction since the last GoTo passes 10′,
    since anything that large is a fault and not guiding;
  - limits, the Sun exclusion and dry runs are still enforced by
    `mount.py` for every GoTo.

## On the 8080 page

A small guide panel showing:

- the state;
- the star's SNR;
- RA and Dec RMS in arcseconds;
- the last 100 errors as a line graph;
- `lost` in red.

The status JSON and its schema in `schemas/` change with it.

## Hardware before the first guided night

These need daylight or the user's hands. None needs the sky.

1. **Power.** The wheel and the guide camera on one powered hub, or on
   separate ports. Done when both stay up together for 10 minutes, with
   the wheel moving through all 7 filters and the guide camera taking
   frames throughout. `docs/usb-hub.md` has the history: the last powered
   hub, the RSH-ST04, dropped its devices and was returned.
2. **Guide scope focus**, on a distant roof edge in daylight, using
   `./guidecam.py snap`. Lock the helical focuser.
3. **Fitting.** The guide scope's shoe and rings fully tight. Forum
   experience is that guide-scope flexure and Newtonian mirror shift show
   as trailed or doubled stars while the guider reports good numbers [7].
4. **Balance.** Rebalance Dec and RA with the full train and the guide
   scope on.
5. **Darks:** 120 s and 300 s darks at -5 °C, gain as planned. Science
   refuses frames without matched darks, so these come first.

## The first clear night: proving it

In order, each with what counts as passing.

1. **Calibration** near the meridian and Dec 0 to +30. Passes with at least
   8 steps west and 8 north, the axes within 10° of right angles, and a
   measured guide rate within 20 % of 7.1"/s.
2. **Guide 10 minutes with no imaging.** Passes with a total RMS under 2.5".
   Note the RA and Dec RMS separately, and the backlash.
3. **Flexure check:** a guided 300 s L frame. Round stars with the guider
   reporting under 2.5" means no flexure. A trail in one direction while
   the guider was good means flexure or mirror shift: stop here and record
   it.
4. **A guided run with dithers:** 30 minutes of 120 s L frames, dithering
   each frame. Passes when 90 % or more of frames are kept, the settle time
   after a dither is under 20 s, and the stack shows no walking noise.
5. **The swing over the pole:** GoTo a target across the meridian, then
   relock. Passes when guiding resumes with Dec reversed and no new
   calibration.

Each result goes in `docs/nights/DATE/` and, where it changes what is
proven, is linked from `docs/validation.md`.

## Questions for review

1. **PHD2 instead of our own guider?** PHD2 can drive the camera through
   INDI. But this early GPCAM is only opened by the oaCapture legacy
   library, and INDI's ToupTek driver does not list it (tested 2 November
   2026). So PHD2 would need its own camera support for it, which is
   unknown. Is a guider of our own the right call, given the hold already
   exists?
2. **Calibration reuse:** is cos(Dec) scaling plus a Dec reversal after a
   swing over the pole enough on this mount, or should we recalibrate
   every target?
3. **Guide rate:** stay at 0.5x, or go to 0.75x? Forum advice for mounts
   with a lot of backlash favours a faster rate [6].
4. **One-direction Dec guiding:** start with it, or only fall back to it?
5. **Dither size and how often**, at 1.47"/px binned, for this sensor's
   fixed pattern noise.
6. **Off-axis guider later?** On a Newtonian an off-axis guider removes
   differential flexure, which forum users often recommend [7]. Is it worth
   planning for now?

## Sources

1. [PHD2 manual: guide algorithms](https://openphdguiding.org/man/Guide_algorithms.htm) (hysteresis, resist switch, minimum move); [PHD2 2.4.1 trouble-shooting](https://www.adgsoftware.com/phd2/archive/man-2.4.1/Trouble_shooting.htm) (at least 8 calibration steps); [PHD2 forum: calibration step size](https://groups.google.com/g/open-phd-guiding/c/gD9nPvqv3AI)
2. [N.I.N.A. docs: dithering](https://nighttime-imaging.eu/docs/master/site/advanced/dithering); [PHD2 forum: dither scale](https://groups.google.com/g/open-phd-guiding/c/SdXKBJehRWc); [SGP forum: optimal dithering settings](https://forum.sequencegeneratorpro.com/t/optimal-dithering-settings/248); [AstroBin: ASIAIR dithering, how much?](https://app.astrobin.com/forum/topic/134018/asiair-dithering-how-much)
3. [Sky & Telescope, December 2017, p. 67: calibration](https://www.nxtbook.com/nxtbooks/aas/st_201712/index.php?startid=67)
4. [PHD2 forum: declination-dependent guiding](https://groups.google.com/g/open-phd-guiding/c/XvBeZXHkGW8); [AstroBin: calibrate after meridian flip](https://app.astrobin.com/forum/topic/152960/calibrate-after-meridian-flip)
5. [SX Universal Filter Wheel handbook](https://manualmachine.com/starlightxpress/sx/1731761-user-manual) (powered hub recommended; under 100 mA from USB per retailers, e.g. [Adorama](https://www.adorama.com/sxufw1t.html))
6. [PHD2 Best Practices (2019)](https://www.openphdguiding.org/PHD2_BestPractices_2019-12.pdf); [IceInSpace: EQ3 Pro guiding advice](https://www.iceinspace.com.au/forum/archive/index.php/t-204077.html); [PHD2 forum: Guiding Assistant and Dec backlash](https://groups.google.com/g/open-phd-guiding/c/MtoeNTHQv4Y); EQ3 Pro guide rates 0.25x to 1x: [Wex](https://www.wexphotovideo.com/sky-watcher-eq3-pro-synscan-goto-deluxe-equatorial-mount-and-aluminium-tripod-1531007)
7. [AstroBin: differential flexure](https://app.astrobin.com/forum/topic/240772/guiding/differential-flexure-1); [IceInSpace: differential flexure, cure or OAG?](https://www.iceinspace.com.au/forum/archive/index.php/t-26578.html); [Jerry Lodriguss: mirror shift and flexure](https://astropix.com/books/BGDA/CHAPTER9/902.HTM)
