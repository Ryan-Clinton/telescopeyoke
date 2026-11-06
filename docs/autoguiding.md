# Autoguiding

[README](../README.md) · [All docs](README.md) · Guides: [First night](first-night.md) · [Setup](setup.md) · [Imaging](imaging.md) · [Calibration](calibration.md) · [Focus](focus.md) · Science: [Discovery](discovery.md) · [Results](results.md) · [Validation](validation.md) · [Data](data.md) · Developers: [Contributing](../CONTRIBUTING.md) · [Agents](agents/README.md)

**Specification, 6 November 2026.** **Status:** the ST4 lead works; stages 1 to 5 (star, calibration, loop; the guider's ownership, heartbeat, orders and watch on a hung loop; `shoot.py --guide`) are built and have not guided; the guide camera does not yet deliver 2 s frames on its hub ([the record](nights/2026-11-06/guide-camera.md)), which blocks any sky test; dithering while guided and longer subs (stages 6 and 7) are not built. This says what autoguiding
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
| Guiding software | Built, not run on the sky: `./guidecam.py star`, `calibrate` and `guide` (`guider.py`; the shared maths in `guidemath.py`). Not built: one owner of the camera, the heartbeat timer, orders, `shoot.py --guide`, dithering |
| Guide frames of 1 s and more | 6 November 2026, `./guidecam.py probe`: on the 183M's hub through the Trust hub, with the wheel unplugged, frames came with gaps of about 3 s even at 0.1 s, one frame in 12 s at 0.5 and 1 s, none at 2 s; the same in software trigger mode and at the slowest USB speed. The 2 November test took single frames only, so it was never seen. Guiding needs 2 s frames every few seconds. Later that evening, 2 x 2 binned (640 x 480) at USB speed 0: 149 of 150 2 s frames in 5 minutes, no gap over 2.08 s ([the fault](guide-camera-fault.md#what-cured-it)). Since 79a2f2d the guider opens the camera that way, at 9.55"/px |
| Long darks for the 183M at -5 °C | None at 120 to 300 s |

## The numbers

| | Guide camera on the 50 mm Orion Mini | 183M on the 150P with the 0.9x corrector |
|---|---|---|
| Focal length | 162 mm | 675 mm |
| Pixel | 3.75 µm, read 2x2 binned: 7.5 µm | 2.4 µm (binned 2x2: 4.8 µm) |
| Scale | **9.55"/px** binned (4.77"/px full size) | 0.73"/px (binned 2x2: **1.47"/px**) |
| Field | 1.70° x 1.27° (640 x 480 binned) | 1.11° x 0.74° |

The guide camera is read 2 x 2 binned at USB speed 0: at full size it drops
frames whatever the setting, and binned it sent 149 of 150 2 s frames in 5
minutes (6 November 2026, [the fault](guide-camera-fault.md)).

- **Guide ratio:** 6.5 against the 183M binned 2x2, within the usual rule of
  thumb (forum advice says under 5 to 10 [2]); 13 against it unbinned, past
  it. Guided imaging should be binned 2x2. A centroid good to about 0.1
  guide pixel is about 1", two thirds of a binned imaging pixel.
- **One guide pixel at the guide rate:** 9.55" / 7.1"/s, about **1.3 s** of
  pulse.

## The guiding command

`./guidecam.py guide`, a project command like the rest. PHD2 is not
installed. The project's rule is that anything used every night is a
project command before its first use, and the photometric hold in
`shoot.py` already contains a guider's hard parts. That hold learns each
direction separately, takes up Dec gear slack on a reversal, corrects only
part of each error, and gives up when corrections stop helping. The guider
should share that maths, not copy it, and not call the hold itself: the
hold is driven by the stacker's frame shifts and moves the mount through
the handset, the guider by a guide star and ST4. The parts both need (a
response learnt per direction, the slack from two opposite moves, the
partial correction) come out of `shoot.Hold` into plain functions in a
small module that both import. Each keeps its own loop.

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
- While guiding, look for the star only in a window round where it should
  be (the lock position plus the corrections just sent), not the whole
  frame, so a neighbour or a hot pixel is not mistaken for it. Every frame
  rejected is logged with its reason.
- No star: try again every 10 s and say so, the way the other steps retry
  through cloud. The state is `lost`, not `fault`: cloud is not a broken
  guider.

### 2. Calibrate

- Pulse west in steps, measuring the star after each, until it has moved
  about 13 guide pixels (about 2', 25 at full size) or 15 steps have been sent. Then pulse east to come
  back. Then do the same north and south, taking up Dec slack first with
  north pulses until the star starts to move. This follows PHD2's practice
  [1][3].
- Step length: aim for 12 steps over the whole move, rounded up to the
  nearest 50 ms (S&T's guidance; the PHD2 developers' calculator). It is
  worked out, not fixed: 13 px x 9.55"/px / 7.1"/s / 12, which is
  **1500 ms** at Dec 0. RA motion shrinks by cos(Dec), so RA steps are that
  divided by cos(Dec), capped at 3000 ms. The rate used is the guide rate
  last measured, 7.1"/s until the first calibration replaces it.
- From the two lines, record:
  - the camera's angle on the sky;
  - RA and Dec rates in px/s;
  - whether the axes are at right angles (a warning if they are more than
    10° off, as PHD2 warns).
- Keep the calibration in `config.DATA/cache/guide-cal.json`, labelled with
  the Dec, the side of the pier and the light path, as for the plate solves.
- Reuse it on later nights while the guide camera has not turned:
  - scale the RA rate by cos(target Dec) / cos(calibration Dec), since the
    rate stored was measured at the calibration's Dec;
  - after a swing over the pole, use the Dec direction stored for this
    mount once it has been measured (below), never an assumed reversal.

  Verify the reuse with one short north and one short west pulse at the
  start of each run. A full calibration happens only when that check
  fails, never guiding on a guessed sign.
- Whether Dec reverses after a swing over the pole is not assumed: through
  ST4 it depends on the mount. The first night measures it (proof step 6)
  and the answer is stored with the calibration.
- Best calibrated near Dec 0 and near the meridian. Accuracy falls off
  towards the pole (forum consensus [4]). Calibrating on the target is
  acceptable below Dec +60°.

### 3. Guide

Each guide frame:

1. Measure the star's offset from the lock position.
2. Convert it to RA and Dec errors with the calibration.
3. Compute each axis's correction, apply the per-axis rules below, and
   convert to a pulse length.
4. Send the pulses through the camera's `ST4PlusGuide`, RA then Dec.
   That call takes one direction at a time, so the two run one after the
   other: Dec is sent only once `ST4PlusGuideState` says the RA pulse has
   finished, so no call can cut short the other axis's pulse. The next
   exposure starts only after both have ended, so a frame never mixes a
   move into its measurement. The cycle is the exposure, the readout and
   the pulses: at 2 s and a typical correction of a fraction of a guide
   pixel (one pixel is 1.3 s of pulse) that is about 3 s; at the worst,
   both axes at the 2.5 s cap, 7 s. The two together are capped at the
   exposure length; a longer total is shortened, both axes in
   proportion, and the rest taken back on the next frames. Each call's return value is checked, and a pulse
   still running past its length plus 1 s is a fault. Both axes at once
   comes later and only if a bench check with `./guidecam.py pulse` shows
   the SDK runs them together without one stopping the other.

Each frame is logged with four times: exposure start, its midpoint, when
the frame arrived and when each pulse went. The cadence and the delay from
midpoint to pulse are reported, and a frame arriving twice (same data) is
dropped.

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
  - Measure it during calibration, as the hold already does, repeated so
    it has a spread as well as a figure.
  - A Dec reversal starts with part of the slack taken up, not all of it:
    half the measured figure to start, raised or lowered by what the next
    frames show, never above the measured figure plus its spread.
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
  frame, treating it as a passing satellite, a bird or a cosmic ray. Not
  while settling after a dither or relock, when large moves are expected.

### 4. What the state file says

The guider writes the state file every frame, for `shoot.py`, the 8080 page
and the night's notes. It holds:

- the state: `calibrating`, `guiding`, `settling`, `lost`, `paused`,
  `fault` or `stopped`;
- the guider's process ID, a run ID made at start, and a heartbeat time,
  written once a second by its own timer whether or not a frame came in;
- the last order: its number, the run ID it was carried out under, and its
  outcome (`done` or `failed`, with the reason);
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
again after a GoTo), `stop`. `shoot.py` sends them, each a file of its own
in `cache/guide-orders/` with a random ID and the guider's run ID, so two
orders sent together can never overwrite each other; each gets a result
file of its own. An order is marked `done` only once what it asked for is
true, not when it is read:

- `pause`: any pulse running has finished or been stopped, and no more go;
- `relock`: a star found and its new lock position set;
- `dither`: the lock moved and the guider settled on it;
- `stop`: pulses stopped, the camera closed and its lock let go. A stop is taken between pulses during calibration and its check too, not only while guiding; the other orders are answered `failed` until guiding starts.

`shoot.py` accepts only a result with its own order's ID and the run
ID it sent to, so an answer left by an earlier guider never counts. Every
order has a timeout: 10 s for `pause`, 60 s for `relock` and `dither`. A
timed-out or `failed` order is a fault, and `shoot.py` stops guided imaging
with the reason.

### 6. Owning the guide camera

- One user of the guide camera at a time: every command that opens it
  takes a kernel lock (`flock` on `cache/guide.lock`) before opening it and
  lets it go only after closing it; `cache/guide.pid` says who holds it.
  The kernel drops the lock however the process ends, so nothing stale is
  left to take over. A second `guide` refuses, or `shoot.py --guide`
  attaches to the one running.
- **A hung guider:** the heartbeat's watch writes `fault` when the loop
  stops moving, but it cannot interrupt a call stuck inside the camera
  library, so the process may still hold the camera (`camera_held` stays
  true). Detecting the fault is not shutting down. The supervisor
  (`shoot.py`, stage 5) stops guided imaging at once and ends the process
  with `guider.terminate()`: SIGTERM, then SIGKILL after 10 s, after which
  the kernel lets go of the lock. It signals only the process that is
  still that guider: the state file carries the guider's process start
  time (`pid_start`), checked before each signal, so a pid used again by
  another process is never touched.
- **Orders are claimed one at a time.** After a stop, no frame is taken
  and no pulse sent; any order still waiting when the guider ends is
  answered `failed` ("the guider stopped"), never left to time out.
- `MOTION_LOCKED` is checked before every pulse, not only at start.
- **Stale state:** `shoot.py` trusts the state file only while its
  heartbeat is under 5 s old (the timer writes it every second) and the
  process and run ID match. Older is `fault`, whatever the file says.
- **Lost or fault:** `lost` means the camera is working but no star passes
  (cloud, a passing tree). `fault` means the guider cannot do its job: the
  camera stopped answering for 3 exposure lengths plus 5 s, an SDK call
  failed, a pulse did not finish, or a limit below was hit.
- **On the way out:** Ctrl-C, an exception, the camera timing out or
  unplugged: send an ST4 stop, write `stopped` or `fault` with the reason,
  release the pid file. A crash or a power cut cannot send the stop, so
  the protection there is the pulse cap: no pulse is longer than 2.5 s.

## Changes to `shoot.py`

- **`--guide`:** starts the guider, or uses one already running. While it
  guides:
  - the photometric hold is off, and the drift assist's Dec trims are off;
  - the Dec creep set by GoTo is turned off, so the guider is the only
    thing correcting Dec; it is put back when guiding ends. Whether a creep
    under the guider means fewer Dec reversals is tried later, once
    guiding is proven;
  - `--guide` and `--hold` are refused together.
- **Each frame waits for "settled":** before an exposure starts, the guider
  must report `guiding` with every error under 0.5 guide px (about 5") for
  two guide frames over at least 3 s. After 30 s still `guiding` but not inside that, the frame is
  taken and marked. No other state ever times out into a frame, and the
  two kinds of trouble are handled apart:
  - `lost` (the guider working, no star: cloud) and `calibrating`:
    `shoot.py` waits, as it waits through cloud now, and after 5 minutes
    stops guided imaging with the reason;
  - `fault`, a stale heartbeat or a guider process that has died: no
    waiting. `shoot.py` stops the guider if it is still there, starts a
    new one once, which runs its reuse check (a recalibration if that
    fails) within 3 minutes. If that new one does not reach `guiding`,
    guided imaging stops with the reason. A second fault in the same run
    stops it without a restart.

  It never carries on unguided unless the run was started to allow it. This follows PHD2's
  settle tolerance, minimum time and timeout [2].
- **Headers:** `GUIDED`, `GUIDERMS` (the guider's total RMS in arcseconds
  over the exposure), `GUIDEMAX` (the largest error) and `GUIDELST`
  (seconds lost). The frame's own stars still decide whether it is kept;
  the guider's figures explain a rejection.
- **Frames taken while guiding was `lost`:** kept, marked, and judged by
  the usual frame checks. They are not thrown away blind.
- **GoTo, re-centre, swing over the pole:** anything that moves the
  telescope.
  1. send `pause`, and wait until the state file shows it carried out, so
     no pulse is going when the slew starts;
  2. the GoTo;
  3. `relock`: a new lock position from where the star is now, since a
     re-centre means the old one is wrong;
  4. after a swing over the pole, the Dec sign as measured for this mount,
     and the reuse check; if that fails, a full calibration;
  5. settle, then the next frame.
- **Filter change:** the telescope does not move, so the guider keeps
  guiding and keeps its lock. The next frame waits for "settled" in case
  the wheel's turn shook it.
- **Dithering while guided:** move the guider's lock position, never a
  GoTo. Today's dither is a 1.5' GoTo every N frames, which would throw the
  guide star off the lock.
  - Each dither is a random offset from the original lock position, between
    half and all of a set size. It never adds to the last one, so the field
    cannot wander.
  - Size and how often are settings (`--dither-size`, `--dither N`). Start
    at 8 imaging pixels binned (about 12", or 1.25 guide px); forum practice
    is 5 to 10 imaging pixels [2]. Start dithering every frame for subs of
    2 minutes or more, every 2 to 3 frames for shorter.
  - Each dither waits for "settled". At 15 s a dither that is 5 % of a
    300 s sub; the settle times are logged so the cost is known.
  - Whether it worked is measured: the stack's background noise and any
    walking pattern, against an undithered stack of the same target.
- **Exposure:** unchanged by default. Guided runs keep today's sub lengths
  until the ladder test (proof step 3) has measured star shape, HFD and the
  share of frames kept at 30, 60, 120, 180 and 300 s. The plan's per-filter
  blocks then take the longest length that kept its stars round. The frame
  checks must not treat 300 s frames as if they were 15 s ones:
  - drift limits are in pixels per frame, not per second;
  - one rejected frame now costs 5 minutes, so a starless frame is treated
    as cloud at once (wait and retry, as now) rather than after several.
    A run stops only on a fault that persists: the camera, the mount or the
    guider, not cloud.

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
  - it checks `MOTION_LOCKED` before every pulse;
  - it sends an ST4 stop on every exit it controls; after a crash or power
    cut the 2.5 s cap is the limit;
  - it is confirmed paused before every slew;
  - three limits, each a `fault`:
    1. **guide error:** the star more than 15 guide px (about 2.4′) from
       the lock for 5 frames running while `guiding`;
    2. **correction since relock:** the pulses sent since the last
       acknowledged `relock`, added up per axis with their signs and turned
       into arcseconds by the calibration, past 10′ on either axis. Signs
       count, so ordinary back and forth cancels and only a steady push
       builds up; 10 frames running at the longest pulse the same way is a
       runaway as well;
    3. **dither:** the lock never more than the dither size from where the
       last `relock` set it, which the random offset already keeps to.

    All three start again only on an acknowledged `relock`, never on a
    dither;
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
   frames throughout. `./guidecam.py wheeltest` runs it: 2 s guide frames
   (binned, speed 0) while the wheel turns to the next filter every 15 s,
   and says PASSED with 90 % of the frames, no gap over 4 s, no library
   error and every turn arriving. `docs/usb-hub.md` has the history: the last powered
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

## The order it is built in

The camera and the star tracking, then calibration, then the closed loop,
then the safety and recovery above, then `shoot.py`, then dithering, then
longer subs, then an unattended run. Each is proven on the sky before the
next is given control.

## The first clear night: proving it

Before the sky: the wheel and the guide camera together for 10 minutes, as
in hardware step 1.

In order, each with what counts as passing.

1. **Calibration** near the meridian and Dec 0 to +30. Passes with at least
   8 steps west and 8 north, the axes within 10° of right angles, and a
   measured guide rate within 20 % of 7.1"/s.
2. **Guide 10 minutes with no imaging.** Passes with a total RMS under 2.5"
   and no runaway. Note the RA and Dec RMS separately, the backlash, the
   measured cycle time, the delay from exposure midpoint to pulse, and the
   pulse lengths. If the error grows while pulses are long, lower the
   longest pulse or the aggression before going on.
   Then kill the guider process: `shoot.py` must see the stale heartbeat
   and start no new frame.
3. **Sub length ladder:** guided L frames of 30, 60, 120, 180 and 300 s,
   a few of each. The guider's RMS is not enough: the frames' own star
   shapes decide the longest length used.
4. **Flexure check:** at the longest length the ladder allows, several
   guided frames on one side of the meridian and several on the other.
   Stars elongated the same way across frames while the guider reported
   under 2.5" means flexure or mirror shift: record it and stop there. One
   round frame does not clear it; several on both sides do.
5. **A guided run with dithers:** 30 minutes of L frames at the ladder's length, dithering
   each frame. Passes when 90 % or more of frames are kept, the settle time
   after a dither is under 20 s, each dither landed within 1 guide px of
   its offset, the field has not wandered, and the stack shows no walking
   noise. A GoTo during it must show no pulse in the log between `pause`
   and `relock`.
6. **The swing over the pole:** GoTo a target across the meridian, then
   relock. Passes when the reuse check shows which way Dec went, guiding
   resumes the right way without running away, and the answer is stored.
7. **A full session:** several filters on one target, the 183M kept cold
   throughout, and every filter's frames on the same framing.

Each result goes in `docs/nights/DATE/` and, where it changes what is
proven, is linked from `docs/validation.md`.

## Measuring and publishing the mount's periodic error

### Why it is worth doing

- **Sky-Watcher publishes no periodic error figure** for the EQ3 Pro, or
  for any of its mounts as far as a search on 6 November 2026 found.
- **Figures in circulation are retailer estimates that disagree:**
  - HEQ5: "±10 arcsec" [8], and 3–5" and 5–10" on two pages of one blog
    network;
  - EQ6-R: 12–15" on a blog, and 1.00" on AstroBin's equipment page [9].
- **Measured results are scattered** through single forum posts, mostly for
  other mounts. CCDWare cites a survey of 50 PEMPro users but shows no
  per-mount table [10].
- **No published EQ3 Pro curve with its data was found**, and no shared
  database for any mount. Owners do measure their own mounts, with PHD2's
  Guiding Assistant or PECPrep, but the measurements stay on their laptops.
- **Single spec numbers hide a lot of variation**: a forum post gives typical
  uncorrected error as ±15" "but can vary widely between mounts" [11].
- **The general range** quoted for entry-level mounts is 30–120" peak to
  peak [12].

That search was a handful of queries, so nothing here is claimed as a
first. What is offered is an openly reproducible measurement of one EQ3
Pro: the raw data, the method and the code, so anyone can check it or
measure their own the same way.

### What is known about ours

The RA worm wheel has 130 teeth: 35,200 handset counts per worm turn
(`docs/agents/hardware.md`). A sidereal day of 86,164.1 s divided by 130
gives a worm period of **662.8 s, about 11 minutes**. The periodic error
should repeat on that cycle, with harmonics from the other gears.

### The measurement: `./guidecam.py pe`

A project command, written before its first use.

1. A star near Dec 0 and near the meridian, where RA motion and the error
   are at their largest.
2. Tracking only: no guiding, no drift assist trims, no hold.
3. Guide camera frames of 1 to 2 s, for at least 5 worm periods (about an
   hour). That follows EQMOD's PECPrep guidance of at least five periods
   [13].
4. Each frame records, one row of the raw CSV:
   - the exposure's start and midpoint (UTC), and the time it arrived;
   - the raw centroid x and y in guide pixels, the star's peak, SNR and
     HFD, and whether it was used or why not;
   - the RA and Dec axis readings from the handset (the motor counts),
     and the time each was read;
   - the mount's state: tracking on, sidereal rate, no guiding, no creep.

   The run's header holds what is the same for every row: the guide
   camera, exposure, gain, binning, the scale, the calibration's angle and
   rates, the star's RA and Dec, the site's latitude, the hour angle at the
   start, and the handset's power-on time if known. The cadence and every
   gap longer than two exposures are reported, since frames do not come
   at an exactly even rate.

   The handset is read only.
5. The analysis, every step kept beside the raw data so it can be redone:
   - centroid to RA arcseconds, using the scale and the camera's angle
     from the guider's calibration;
   - take out the steady drift, which comes from polar alignment,
     refraction and the tracking rate, not the worm. A straight line
     first; a quadratic as a check. If the two give a peak-to-peak more
     than 10 % apart, both are published and the drift is named as a
     limit, not hidden;
   - plot the residuals against time before folding, so drift that is not
     a straight line is seen, not taken for periodic error;
   - fold on the worm's angle (counts modulo 35,200), not the clock;
   - each worm turn on its own: its own curve and peak-to-peak. The
     result is the mean of the turns' peak-to-peak, with their spread and
     a 95 % interval from resampling the turns (a bootstrap over whole
     turns, not frames, since frames within a turn are not independent);
   - the average curve, the strongest harmonics (as periods in seconds)
     and the steepest rate of change in "/s, the number that matters for
     guiding;
   - a held-out check: fit the curve on all turns but one, and say how
     well it predicts the one left out, in turn for each. A curve that
     does not predict its own held-out turns better than a flat line is
     not periodic error, and is not published as such.
6. Frames hit by wind, or with the star lost, are flagged and left out of
   the fit, with a count of how many.

**The worm's phase holds only within one power-on.** The handset counts
from wherever the mount sat when it was switched on (`mount.py`), so counts
modulo 35,200 give a phase whose zero is different each time it is
powered up. Within a night that does not matter: the motor counts follow
the worm, and releasing the RA clutch turns the axis, not the worm. Between
nights, the curves are lined up by fitting the phase offset between them
(the shift that best matches them), and the offset is published with the
fit. A fixed zero would need a mark on the worm itself, which is not
planned.

So the fold on the worm's angle buys this: within a night, gaps and an
uneven cadence do not smear the curve as a fold on the clock would, and
between nights only one number, the offset, has to be fitted. The same
curve could drive periodic error correction later, within a power-on.

**A second night** repeats the measurement. The result counts as this
mount's periodic error only when the two nights' curves, once lined up,
agree within their intervals. Until then it is one night's figure and is
called that.

**The first run is kept for good**, raw, as the uncorrected baseline: if
periodic error correction is ever added, its improvement is measured
against it.

### What gets published

- `docs/results.md`, with the figure, the curve as a picture, the method,
  and the raw CSV in the repository. Linked from `docs/validation.md`.
- The user's blog entry on ryanclinton.uk, through the usual inbox.
- Forum posts on Cloudy Nights and Stargazers Lounge, written by the user
  as with their other public posts.
- The method made usable by other owners: `pe` should work from any
  camera's frames, and from a mount reached through `direct.py` as well as
  the handset, so others can measure theirs the same way.
- Later, if others take part: an open table of mount, unit, date,
  peak-to-peak, method and link to data. It would show the spread between
  units that single spec numbers hide.

### Limits

- **One mount is not the model.** The first result is "this EQ3 Pro", and
  only many owners would make a figure for the model.
- **Seeing** blurs a single 2 s frame by 1 to 2". The fold over 5 or more
  turns averages that down, and the per-turn spread shows how far.
- **Phase between nights** is fitted, not measured (above).
- **Wind** shows as spikes that do not repeat with the worm.

### When

On the first clear night, after the guider's calibration (proof step 1),
since `pe` uses its scale and angle. Or on any later night with an hour
spare. Results go in `docs/nights/DATE/` like the rest.

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
7. **Periodic error measurement:** is an hour of 2 s guide camera frames at
   4.77"/px enough for a figure worth publishing? Is folding on the worm's
   angle from the handset sound? And has anyone already published an EQ3
   Pro curve that the search missed?

## Sources

1. [PHD2 manual: guide algorithms](https://openphdguiding.org/man/Guide_algorithms.htm) (hysteresis, resist switch, minimum move); [PHD2 2.4.1 trouble-shooting](https://www.adgsoftware.com/phd2/archive/man-2.4.1/Trouble_shooting.htm) (at least 8 calibration steps); [PHD2 forum: calibration step size](https://groups.google.com/g/open-phd-guiding/c/gD9nPvqv3AI)
2. [N.I.N.A. docs: dithering](https://nighttime-imaging.eu/docs/master/site/advanced/dithering); [PHD2 forum: dither scale](https://groups.google.com/g/open-phd-guiding/c/SdXKBJehRWc); [SGP forum: optimal dithering settings](https://forum.sequencegeneratorpro.com/t/optimal-dithering-settings/248); [AstroBin: ASIAIR dithering, how much?](https://app.astrobin.com/forum/topic/134018/asiair-dithering-how-much)
3. [Sky & Telescope, December 2017, p. 67: calibration](https://www.nxtbook.com/nxtbooks/aas/st_201712/index.php?startid=67)
4. [PHD2 forum: declination-dependent guiding](https://groups.google.com/g/open-phd-guiding/c/XvBeZXHkGW8); [AstroBin: calibrate after meridian flip](https://app.astrobin.com/forum/topic/152960/calibrate-after-meridian-flip)
5. [SX Universal Filter Wheel handbook](https://manualmachine.com/starlightxpress/sx/1731761-user-manual) (powered hub recommended; under 100 mA from USB per retailers, e.g. [Adorama](https://www.adorama.com/sxufw1t.html))
6. [PHD2 Best Practices (2019)](https://www.openphdguiding.org/PHD2_BestPractices_2019-12.pdf); [IceInSpace: EQ3 Pro guiding advice](https://www.iceinspace.com.au/forum/archive/index.php/t-204077.html); [PHD2 forum: Guiding Assistant and Dec backlash](https://groups.google.com/g/open-phd-guiding/c/MtoeNTHQv4Y); EQ3 Pro guide rates 0.25x to 1x: [Wex](https://www.wexphotovideo.com/sky-watcher-eq3-pro-synscan-goto-deluxe-equatorial-mount-and-aluminium-tripod-1531007)
7. [AstroBin: differential flexure](https://app.astrobin.com/forum/topic/240772/guiding/differential-flexure-1); [IceInSpace: differential flexure, cure or OAG?](https://www.iceinspace.com.au/forum/archive/index.php/t-26578.html); [Jerry Lodriguss: mirror shift and flexure](https://astropix.com/books/BGDA/CHAPTER9/902.HTM)
8. [Astronomics: HEQ5 Pro](https://astronomics.com/collections/sky-watcher/products/sky-watcher-heq5-pro-equatorial-computer-goto-mount-s30400)
9. [AstroBin equipment: EQ6-R Pro](https://app.astrobin.com/equipment/explorer/mount/995/sky-watcher-eq6-r-pro)
10. [CCDWare: PEMPro](https://ccdware.com/?p=1146)
11. [Stargazers Lounge: EQ5 periodic error correction](https://stargazerslounge.com/topic/157386-eq5-periodic-error-correction)
12. [astrojolo: mount periodic error](https://astrojolo.com/gears/mount-periodic-error/)
13. [EQMOD PECPrep](https://eq-mod.sourceforge.net/docs/PECPrep.pdf); EQ3-2's 130-tooth wheel: [IceInSpace](https://iceinspace.com.au/forum/archive/index.php/t-143412.html)
