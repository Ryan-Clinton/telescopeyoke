# Checking it under real sky

[Back to the README](../README.md)

Much of the newer work is proven on made-up star fields and a simulated
mount, not yet on real sky. These are the experiments that will settle it.
Results go here as they are obtained; until then each one says "not yet run".
The account of everything tried so far, feature by feature, is at the end:
[What has and has not been proven, in full](#what-has-and-has-not-been-proven-in-full).

| # | Question | How | Result |
|---|---|---|---|
| 1 | Does "Focus good. Hold" land on the sharpest point, and how long does a turn of the knob take to be heard? | `./focus.py`, noting the HFR when it speaks and the `feedback_s` it prints on each level, then compare the star width (FWHM) of a stack taken there with one taken a touch either side. | Not yet run. |
| 2 | How much Dec drift does the compensation remove? | `./mount.py drift` before, `./mount.py compensate`, `./mount.py drift` after, at three or more hour angles. | First try did not settle; see the results below. One early figure: about -1.4"/s natural drift near M27 with the polar axis roughly 9 degrees out. |
| 3 | Does the quality pass beat the live stack and a plain stack? | `./compare.py` on the same 200 to 300 raw frames stacked three ways: star width, roundness, background noise, faint detail. | Partly: on 200 frames of M27, star width went from 8.4 to 6.9 px and roundness from 0.67 to 0.92 against the first-night stacker. |
| 4 | Does `--exposure auto` pick the exposure that gathers most usable light? | Run the same target at 1, 2, 3 and 4 s; compare accepted integration time and star shape with what auto chose. | It chose 1 s twice, on roundness. Whether 2 s would have given a better picture despite the stretch is untested. |
| 5 | Do four worker processes give the expected speed-up? | `./restack.py SESSION --profile` on 200 to 500 frames, with `--workers 1` and `--workers 4`. | 200 frames: 23.5 minutes before the rewrite, 3.9 minutes with four workers. |
| 6 | Does the polar measurement repeat? | `./polaralign.py --repeat 5` with the bolts left alone. It prints each answer and their scatter. | Not yet run. Five rounds on 6 October gave 5.2°, 1.1°, 0.4°, 0.6°, 0.2°, but the bolts were turned between them. |
| 7 | How quickly is a turn of the focuser heard on the USB 3 lead? | `./focus.py` on a rich field, then `./focus.py --report`: `feedback_s` on each level. Under about 1.2 s on levels 1 and 2 is the aim. | Not yet run. |
| 8 | How long is the shutter really open? | `./camera_test.py --timing` (cap on, any time), then `./camera_test.py --trail` on a field of bright stars away from the pole. | Timing by hand on 6 October: each second asked added 0.63 s to a frame. No trail yet. |
| 9 | Does the sky's drift answer the Dec motor in proportion? | `./mount.py response`: five creeps, three measurements at each, about 35 minutes on one target. | Not yet run. The three readings of 5 October (below) fit no one explanation. |
| 10 | Is one pointing correction for each side of the meridian enough? | `./mount.py pointing`: plate solves at -4, -2, -1, +1, +2 and +4 hours. | Not yet run. On 6 October the east side was 5.8° out in Dec and the west 0.2°, from one place each. |
| 11 | Does a stalled mount get caught, with no false alarms on a working one? | Run `./horizon.py --trace` and a `goto --solve` on a working mount and see that neither stops; the verdict of each comparison is in the survey's log. | One real record, by day, and it showed a fault: see 7 October 2026 below. By night, not yet run. |
| 12 | How true is a panorama's skyline? | Tie a panorama to the compass with two marks (`./panorama.py`), then `./horizon.py --trace` to check it at the bearings where it bends. | Not yet run. |
| 13 | Does the daytime search find Polaris once the axis is close? | `./polaris.py find` on a clear afternoon after a night alignment, the tripod not moved. It looks within 1.6° by itself. | Not yet run. Two searches on 6 October, with the axis several degrees out, found nothing. |
| 14 | Does a whole night work on Windows? | Mount and camera together: GoTo with centring, focus, a run. | Not yet run. |
| 15 | Does `findhome` find the home position, and does marking it hold? | After polar alignment: `./mount.py findhome`, `./mount.py truehome`, mark, restart on the marks, `./mount.py findhome` again. The second should read under 0.1°. | Not yet run. Two pointing errors from 6 October (Dec -6.1° east, -0.2° west) hint at a home about 3° out, but they were taken 75 minutes apart with the bolts turned between, so they prove nothing. |
| 16 | Does the handset take its clock from the computer? | `./mount.py settime` with the handset at its main menu, then read its date on its own screen. | Yes, once: 7 October 2026, at the main menu, it read back the computer's time to the second and its sidereal clock came to 0.01° from true. The date on its own screen was not looked at. |

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
  That test is now `./mount.py response` (experiment 9); the logic is
  unchanged until it has been run.
- **Home after a drift correction:** went the wrong way twice because the
  direction test did not wait for the gears to take up. Fixed.
- **Meridian:** the mount was already on the tube-over-pole side for both
  runs, so the upside-down handling in the combiner was not exercised.

## The next clear night

The six measurements that put real figures into `./ty characterise`, in an
order that wastes no setting-up ([why this order](calibration.md)). None has been made yet. About two and a half hours.

| Order | What | Command | Takes | Needs |
|---|---|---|---|---|
| 1 | Camera timing | `./camera_test.py --timing` | 3 minutes | Nothing: the cap can be on. Do it at dusk. |
| 2 | Focus response on the USB 3 lead | `./focus.py --field`, then `./focus.py --report` | 10 minutes | A rich field. Turn through focus and back until "Focus good". |
| 3 | Polar repeatability | `./mount.py goto NAME --solve` on a star east of south, then `./polaralign.py --step 12 --repeat 5` | 10 minutes | The bolts left alone throughout. |
| 4 | Real exposure from star trails | `./camera_test.py --trail` | 1 minute | Where step 3 left it: bright stars, away from the pole. |
| 5 | The true home, which measures the pointing each side as it goes | `./mount.py findhome --dry-run`, then `./mount.py findhome`, `./mount.py truehome`, mark, restart, `./mount.py findhome` | 40 minutes | Someone watching: the tube swings over the pole once each time. A marker for the joints. |
| 6 | Dec motor response | `./mount.py goto NAME --solve`, then `./mount.py response` | 35 minutes | One target, left alone. |

Movement checking needs no step of its own: steps 3 and 5 are judged by
their plate solves as they run, and each judgement goes into
`cache/moved_log.jsonl`. Afterwards `./ty characterise` should read 10 or 11
of 13, and the results go in the table above.

## What to look for in the movement check's first real records

`moved.py` can stop a command with a refusal, and its thresholds
(`LEAST` 0.5°, `MATCH` 4 pixels, `SHARE` 0.6, `SURE` 12, `PATIENCE` 2) come
from made-up frames. Every judgement is kept in `cache/moved_log.jsonl` with
how far the mount was turned (`expected_deg`), how far the view was seen to
move where that could be measured (`observed_deg`), and the figures behind
the verdict; the two pictures behind every "same view" are in `cache/moved/`.
After the first real survey, look there for:

- **Two blank or cloudy places taken for one.** Expected: no verdict
  (`"verdict": null`), because neither picture has anything to go by. A
  "same" here would be a false stop.
- **A rich star field after a small move.** A move between 0.5° and about
  1° leaves part of the old field in the new frame, shifted. Expected:
  "changed", because the stars are not where they were.
- **Detail that repeats**: a fence, roof tiles, a brick wall. Two different
  parts of it could match. Expected to be rare, and `PATIENCE` asks for two
  matches running; the kept pairs will show whether it happens.
- **Cloud moving over a mount that is stuck.** The detail changes though
  the telescope has not, so the check says "changed" and misses the fault.
  It fails towards carrying on, not towards a false stop.
- **Near the pole**, where a large turn of the RA axis moves the view
  little. The survey judges by the angle between the two directions on the
  sky, not by the axis readings, so a small move there is simply not judged
  (under `LEAST`). `polaralign.py` refuses above Dec 75°.

Where plate solves do the judging (`goto --solve`, `polaralign.py`,
`mount.py pointing`) the comparison is already a quantity: the move asked
against the move seen, with less than a quarter of it counting as stuck.
For pictures it is a quantity only when the two views overlap; two different
views share nothing to measure a shift by.

## Known weaknesses found by the tests

- The focus tracker judges change against the readings' own jitter. With the
  knob turned in steps and a pause after each, the steps themselves used to
  inflate that jitter, and real changes went unannounced. Found by
  `tests/test_night.py`. The jitter is now also judged from the usual step
  between one reading and the next, and the smaller figure believed when the
  two disagree by half. A step at every second frame can still pass for
  jitter; a pause of two frames or more after each turn does not.

## What has and has not been proven, in full

The README's "Current status" has the table. This is the account behind it.

Working on real hardware and real stars: the night report and web page,
mount moves through the handset, camera frames, focusing, plate solving,
`goto --solve` (centres a target to a fraction of an arcminute) and `sync`.
The pictures on this page came from an earlier, simpler version of
`shoot.py`.

Rewritten since those pictures, tested on simulated star fields, and being
proven on real sky: the stacking pipeline (frame scoring and rejection,
sub-pixel and rotation alignment, clipped and weighted stacking, saved raw
frames, the quality pass).

Windows: the tests and every `--demo` command pass with nothing plugged in,
and the camera has taken frames there: a Hypercam 183C on Windows 11, read
through Altair's own library (`altair.py`) instead of INDI, set up from
nothing by `camera_setup.py`. That was indoors with no telescope, so no star
has been through that route, and its picture has not been compared with the
INDI route's for which way up it is. The mount has not been driven from
Windows: the handset's lead has been found by name among the COM ports and
nothing more. The plate solver's Windows paths, the DirectShow webcam and the
spoken focusing aid are untried on real equipment. Camera and mount have not
been used together on Windows.

Written but not yet run for real: `calibrate.py` (no dark or flat frames have
been taken yet) and `camera_test.py --gain-sweep`.

Rewritten since they were last used on real hardware, and so far proven only
against the simulator and made-up data: `focus.py` (multi-star HFR, the
three levels, binned frames and the click and tone), `mount.py drift` (line-fitted, with the drift model),
`mount.py compensate` and `shoot.py --assist`. An earlier, cruder
`mount.py drift` did cancel most of the drift on the real mount.

`polaralign.py` was first run on the real mount on 6 October 2026, on a
night of broken cloud. With the full 25° turns its third photograph was of a
house, and then of a tree, so `--step` was added; with 12° turns it gave
5.2°, 1.1°, 0.4°, 0.6° and 0.2° from the pole over five rounds while the
adjusters were turned between them, the first of those agreeing with the
mount's latitude scale. A round takes one to two minutes. Two measurements
with nothing changed have not been compared, so how well it repeats is not
known. It is also offered in the application under Tools, which has not been
tried on the real mount. Its geometry is checked by the tests, and in the
demo it finds the pretend mount's polar error (1.4° east, 0.8° high) through
the real plate-solve path. It checks its three positions against the
altitude and meridian limits, and the motion lock, before anything moves. It
now keeps clear of the directions listed as blocked and goes back to where
it started when a photograph will not solve; both are tested on the
simulated mount and neither has happened on the real one since.

The way `focus.py` measures stars was used on the real telescope on 6 October
2026, before the click and tone were written, and at first misled: far out
of focus it measured forty specks of grain and hot pixels, read 3.2 whatever
was done, and the focuser was turned the wrong way by it. It now measures
only stars within a third of the second brightest, and with that the reading
fell from 11 to about 2 as the focuser was turned and the stars became
points. The user asked for the numbers spoken and nothing else, which is
`--numbers`. The plate solver would not take the soft stars at dusk either,
and now tries again on a frame averaged in blocks. Later the same night, with the focuser far out and no
star left to find, it read 2.2 from specks of the sky's grain; a star must
now stand out from the grain by 8 to count, and the rings are measured in
their place. On a field of four or five stars it still jumps about, most of
all between 8 and 20 where rings become stars: `--field`, written that
night and not yet used on the real mount, goes to a richer field first.

The pointing error is now kept for each side of the meridian. With the
polar axis 0.2° from the pole the real mount was 5.8° out in Dec on the east
side and 0.2° on the west, where one figure reversed across the pole had
been assumed; the next two GoTos on the east side landed 5' and 14' out in
Dec. The cause of the difference is not known.

The first imaging run after that alignment (207 frames of M31, cloud ending
it after 41 minutes) showed four faults. The camera exposes for less than it
is asked: frames meant to take 15 s arrived every 11.6 s, and timed alone,
each second asked for added 0.63 s. telescopeyoke and the INDI driver both
pass the time straight on, so the fault is in or below Altair's library
(1.53 of September 2022 here); a like fault is on record for another ToupTek
camera, but it is not confirmed to be the same, and no star-trail test has
been made. Every integration time reported is overstated by about a third
until it is fixed; a run now says so when it sees it. The mount drifted 19
arcminutes in 26 minutes with the polar axis 0.2° out, which that does not
explain; `mount.py drift` was not run. The live run under-read that drift
and re-centred late, and the final picture was framed on the most drifted
frame, with most of the galaxy's glow taken for sky. Those last are fixed
and the picture remade from the same frames; the fixes have not yet been
through a run on the real mount.

Written but never moved a real mount: control without the handset, through
the SynScan Wi-Fi adapter or an EQDIR lead (`direct.py`). The adapter has
been found on the network and asked for its firmware, gearing, position and
status, on a real EQ3. Every movement is tested only against a simulated
motor board, and which way the Dec motor turns has to be checked on each
mount, with someone watching, before a GoTo is allowed.

Written but never used with a real mount or camera: the application
(`app.py`) and its companion page (`console.py`). The server, its refusals,
the plan-then-confirm step and Stop are tested against the simulated mount
and stand-in jobs; the screens have been looked at in demo mode only. The
window itself has been opened on Ubuntu (GTK with WebKit). On Windows the
window (WebView2 through pywebview, or Edge's application mode) and the Start
Menu shortcuts have not been tried on a real machine. How long Stop takes during a real slew, on
Linux and on Windows, has not been measured.

Written but not yet tried where they are meant for: `./doctor.py --report`
asks the handset two things it has not been asked before, its firmware
version and the mount's model. Both are in Sky-Watcher's published protocol
and both only read, but they are tested against the simulated handset alone.
`try-demo.cmd` and `install.ps1 -Demo` have not been run on a real Windows
machine; `./install.sh --demo` and `./tour.py` have been, on Ubuntu.

Written for a second person's equipment and not yet tried on it: rigs have
been run only as tests, never with two real telescopes at once. `--probe`
has never met a real controller: the handset's part and the motor board's
part are each tested against stand-ins, and whether an EQStar answers either
is exactly what it is there to find out. The notice about ASCOM and EQMOD
reads the Windows registry where ASCOM is documented to keep its list, and
has not been run on a computer that has them. The report also now asks the
handset whether it gives a position (it keeps only yes or no, because the
answer would say roughly where the mount is); that too is from the published
protocol and tested on the simulated handset.

Not yet proven on the real sky: `polaris.py`. Its geometry is tested in
three dimensions on the simulated mount with a made-up daytime sky. On the
real mount (6 October 2026) the first version of the search turned as
intended for 23 minutes, out to 1.6° from home, and found nothing: there was
some cloud, the focus had been disturbed and not checked, and no frames were
kept, so there is no telling which it was. That is why the search now asks
for a focus check and can record every look. Daytime frames from the real
camera expose at about 16 ms with the Sun 14° up, take about a second each,
and show no false stars in blank sky. The reordered search then ran on the
real mount from 18:22 to 19:06 the same evening, across sunset: 266 looks in
35 minutes, about 8 seconds each, the tube stopping within 0.05° of where it
was sent, out to 3.3° from home, every look kept. It did not find Polaris,
and nothing stood out further than 8.8 until faint stars began to show at
dusk and it stopped itself. The likeliest reason is that the mount's axis
was more than 3° from the pole (it had been set by a phone compass); that
was not confirmed. Still untried on real hardware: the tipping of the tube
to prove a candidate, the bringing to the middle, `align`, and the watching
while the bolts are turned. Guesses still to be set from real
runs: the level of blue that counts as clear sky (from three frames), the
steps from "poor" to "very good" by the Sun's height, and how far a point
must stand out to count.

Written but never run on the real mount or camera: `landmark.py`. Finding
how far a view has moved is tested on made-up rooftops, and the turning back
on the simulated mount. Daytime frames have never been taken with the real
camera, so its choice of exposure is untried.

`horizon.py --trace --torch` was tried on the real mount on 6 October 2026,
with a torch in the finder's bracket. The idea holds: at 1 s a house wall
read 2186 and a tree 134 against a sky of 51, and the camera's reading, not
where the beam was seen to fall, is what tells them apart (the two do not
point at quite the same spot). The survey itself made 27 looks and was
stopped with nothing kept: from about the fifteenth every look read the same
bright 420 with no stars, up to 75° in the south. The motors had stopped
being driven, with no sound from them, while the handset went on reporting
each move as made, so the telescope sat on one lit tree for half an hour and
every bearing given in that time was wrong; the user, standing beside it,
said so before the readings were believed. Switching the mount off and on
put it right. The cause is not known: a USB lead may have caught, and a
status query sent while the survey was driving the mount garbled a reply at
about that time. The survey now takes a bright frame with stars in it for
thin cloud, and stops when a bright frame with none is too high up to be a
tree. Since then the survey compares each picture with the one before it
(`moved.py`): two running that match, after turns that should have changed
the view, stop it with `MOUNT_NOT_MOVING`. A GoTo with centring stops the
same way when a correction leaves the miss as it was, and so do
`polaralign.py` and `mount.py pointing` when their plate solves come back
the same. That has been tried on made-up star fields and textures only: how
alike two real frames of a lit tree are, and whether anything about the real
sensor makes two different views look alike, is not known. A plain GoTo with
no plate solve still takes the handset's word. No skyline has yet been
measured on the real mount.

Written but never run on the real mount or camera: `horizon.py --trace` and
`horizon.py --daylight`. The following, the adding of bearings and the checks
are tested against the simulated mount and made-up skylines. The scores that
tell daytime sky from a wall, the wait for the tube to steady by day and the
reading of a top from where the stars stop are first guesses and have not
seen a real frame; every look keeps its picture in `horizon/looks/` so that
the first real run can be checked. A frame is about two thirds of a degree
tall, so "the top is in this frame" only saves looks when the start is
already close: from a panorama or an earlier survey, not from nothing. The
camera is read at full size: a smaller or binned mode is not used because
nobody has yet recorded which of this camera's modes keeps its colour
pattern (`./camera_test.py --throughput` shows it).

`panorama.py` has found the skyline in three real phone panoramas of one
garden, two of them well and one (taken low, mostly walls and ground) badly;
a pale rendered wall is what it most often takes for sky, which is why the
line can be redrawn. No panorama has yet been tied to the compass with real
marks and compared with what the telescope sees, so how true the bearings
and heights come out is not known. The Horizon screen's drawing and marking
have been run through the console's own interface in the demo but not yet
used with a mouse.

Written on 7 October 2026 to turn the first nights' surprises into
measurements, and none of it yet run on the real mount or camera:
`polaralign.py --repeat`, `camera_test.py --timing` and `--trail`,
`mount.py response`, `mount.py pointing`, `focus.py --report` and
`ty characterise`. The arithmetic of each is tested on made-up figures and
on the simulated mount. `--trail` reads made-up trails about 4% short. The
trail measure, the movement check and the pointing survey each have
thresholds that are first figures. `mount.py pointing` swings the tube over
the pole once and must be watched the first time. `polaris.py find` now
looks within 1.6° when `polaralign.py` put the axis 0.2° from the pole in
the last fortnight; that assumes the tripod has not been moved, which
nothing checks.

### By day, 7 October 2026

Two hours of blue sky and then cloud and rain, with the mount set down on
the marks made on the ground the night before, home set by eye, and the
focuser not touched since the stars.

- **`mount.py nudge`** was written that morning because there was no small
  move among the checked commands. Its first run on the real mount tipped
  the tube 5° and brought it back; the person beside it saw it turn.
- **`mount.py settime`** was run once with the handset at its main menu. The
  handset took the date, time and position, read the time back to the
  second, and its sidereal clock then stood 0.01° from the true one.
- **A third daytime search for Polaris**: 246 looks in 40 minutes, about
  seven seconds each, under clear sky (blue over red about 2.4, exposures of
  13 ms), out to nearly 3° from the home position, ended by cloud over the
  pole. No star. Twenty-one points crossed the threshold, and every one was
  one of three blemishes that sit at the same place in the frame wherever
  the tube points (near pixels 2704, 545; 2675, 1408; and 1930, 1810 of the
  half-size picture); each was thrown out, either for not being there twice
  or because it did not move when the tube was tipped. That was the first
  use of the tipping on the real mount, and it rejected what it should.
  Nothing else in any frame stood out more than 9, and nothing was narrower
  than 24 pixels, where a focused star would be about 5. So either Polaris
  lay outside 3° of where the tube pointed at home, or the focus is out; the
  frames cannot say which. The search spends about a quarter of its looks
  re-testing those three blemishes, which it could learn to leave alone.
- **`horizon.py --trace --daylight`** made three looks, all at bearing 0°,
  72° to 75° up, all read as open sky under cloud, before rain stopped it.
  No skyline was kept.
- **The movement check's first real record** came from those looks, and it
  was nearly wrong. Going by "stars", it found 60 specks in each of two
  bright frames 3° apart, and 47% of them were in the same place: the
  sensor's and the optics' own marks, not the sky's. At 60% it would have
  called a working mount stuck. So by day the check no longer goes by stars
  at all, and what it makes of the detail is recorded
  (`cache/moved_log.jsonl`, `cache/moved/`) and never stops anything, until
  real frames have shown how to tell dust shadows from a view that has not
  changed. By night it is as it was, and still untried.
- **A lead was knocked out during a move home.** The command died with a
  traceback. It is now a refusal, `MOUNT_NOT_CONNECTED`, that says nothing
  more can be sent, a stop included, and to switch the mount off at the
  mount if a motor is still turning.
