# Calibrating a mount, in order

[README](../README.md) · Guides: [First night](first-night.md) · [Setup](setup.md) · [Imaging](imaging.md) · [Calibration](calibration.md) · [Focus](focus.md) · Science: [Discovery](discovery.md) · [Validation](validation.md) · [Data](data.md) · Developers: [Contributing](../CONTRIBUTING.md) · [Agents](agents/README.md)

A modest mount is set up by eye: the tripod about level, the polar axis
about north, the tube about along it. Each "about" can be measured from the
stars and then either corrected or allowed for. This is the order to do it
in, because each step leans on the one before. `./ty characterise`, and the
application's Rig knowledge screen, list the same steps and say which have
been done.

| Step | What | Command | Leans on |
|---|---|---|---|
| 1 | Level the tripod roughly | none: a spirit level on the tripod's top plate before the head goes on | |
| 2 | Polar-align from the stars | `./polaralign.py`, then `--repeat 5` once to learn its scatter | 1 only for the bolts to behave |
| 3 | Find the true home position | `./mount.py findhome`, `./mount.py truehome`, mark the joints, restart, `./mount.py findhome` | 2 |
| 4 | See how the pointing differs east and west | `./mount.py pointing` | 3 |
| 5 | See that the telescope turns when the mount says so | nothing to run: steps 2 to 4 are judged by their plate solves as they go | |

Steps 2 to 4 have run on the real mount: polar alignment (13 and 17
October 2026), finding and marking home (17 October: 10.66° out by eye,
0.19° on the marks) and the pointing survey (17 October). Polar
repeatability (`--repeat 3`, 0.06° to 0.11° scatter) ran on 2 November;
step 5's check by night is still to be run.

**Stickered baseline, ralphie-side, 2 November 2026, 18:43.** The feet were
set by turning the whole tripod (bolts left centred), each turn checked with
`./polaralign.py --step 25 --repeat 3` from near Deneb, then stickers put
under all three feet. With the stickers on: **0.28° west of north, 1.55°
too low** (1.5° from the pole), scatter 0.11°. Azimuth is right on the
marks; the height is still to be set by the latitude scale or the north
leg's length, which does not move the feet. On these tiles a turn of the
whole tripod is jumpy: about 3 cm a foot moved it anything from 0.2° to
2.2°, so the feet can do about half a degree and the bolts the rest. A later
night back on the stickers is checked against this.
What follows is how each works.

## 1. Level, roughly

An equatorial mount does not need a level tripod: once the polar axis points
at the pole, the mount points and tracks the same however the tripod leans.
Level still earns its minute. With the tripod level the altitude and azimuth
bolts each do one thing, so alignment takes fewer rounds, and the same legs
on the same marks on the ground bring the axis back near where it was. Half
a degree is plenty. There is no software for this and none is planned.

## 2. Polar alignment

`./polaralign.py` measures where the RA axis points from three plate solves
and says which way to turn each bolt ([how](tracking.md)). On the real mount
six rounds took the axis from 3.3° to 0.1° (13 October 2026), once the
measurement took out the handset's own movement of the Dec axis
([validation](validation.md#night-of-13-october-2026)). `--repeat 5`,
with the bolts left alone, gives the scatter of the measurement itself,
which says what a reading of 0.1° is worth. On 1 November five checks
with the bolts alone scattered 0.06°, and on 2 November `--repeat 3` gave
0.06° to 0.11° ([validation](validation.md#2-november-2026)).
Each round tonight, the picture being taken and the advice are also kept in
`cache/polar_stream.json` for the live stream's polar look
([streaming.md](streaming.md#focusing-and-polar-alignment-on-air)).

### What to do with your hands

A measurement in degrees leaves the question of which bolt, which way and
how far. After each measurement `polaralign.py`, and the application's Polar
alignment screen with a drawing of each bolt as a clock face, says:

- **Centre the azimuth bolts before the first measurement**, with the same
  length of thread showing on each. On the first real night they were found
  already most of the way to one side, with little left to give, only after
  being told to go further that way.
- **More than 2° out in azimuth: turn the whole tripod.** The screen draws
  the tripod from above as a clock face, north at the top, with where the
  axis points now and the turn to make; west is anticlockwise seen from
  above. With the distance between two tripod feet in the settings
  (`feet_apart_cm` under `[mount]`, or the Settings screen) it also says how
  far each foot moves: the feet stand on a circle whose radius is that
  distance over √3, and a turn of θ moves each one radius × θ along it.
  Feet 87 cm apart and a turn of 10° is 8.8 cm. That is all three feet, the
  same way round the circle, each by that much: not one foot moved 8.8 cm
  and the others left where they were.
  Better than the geometry is what was measured on the tripod itself:
  `tripod_cm_per_degree` under `[mount]`. On the 150P's tripod on 15
  October 2026 a foot moved about 2.3 cm for each degree (6 cm gave 3.7°,
  7.5 cm gave 2.1°), far more than its spacing predicts, because the feet
  slide and twist on grass rather than rolling round a circle.
- **Up and down on the latitude scale.** With `latitude_degrees_per_mark`
  under `[mount]`, an altitude error is also given in marks on the mount's
  latitude scale, to the nearest quarter of a mark, which holds whichever
  bolt does the work. On the EQ3 Pro a mark is nearly 2°: one and a half
  marks moved the axis 2.8°.
- **Otherwise: which bolt to turn in, which to ease out first, and about how
  many turns**, once this mount's bolts have been learned. The two bolts of
  each pair are called left and right (azimuth) and rear and front
  (altitude), as seen standing behind the mount, on its south side, facing
  north. In is clockwise.
- **Nothing is assumed about the bolts.** Which one moves the axis which
  way, and how far a turn moves it, differ between mounts, so until it has
  been seen on this one the advice is to turn the left (or rear) bolt in a
  quarter of a turn and measure again.
- **It learns from what you tell it.** `./polaralign.py --turned 0.5 0` says
  that since the last measurement the left azimuth bolt went in half a turn
  and the altitude bolts were not touched (the right or the front bolt is a
  minus). The screen never asks for a plus or a minus: for each pair it asks
  which bolt you turned in, by name, and how far, from a quarter of a turn
  to four turns. The change in the
  axis divided by the turns is kept (`cache/polar_bolts.json`, the last
  twelve for each pair), the middle figure is used, and the advice says how
  far apart the figures have been: bolts have slack, and bind under load, so
  "about" is meant.

None of this has been used on the real mount yet. Left for when real
figures exist, and not built:

- **Slack on reversing.** A bolt turned back the other way may do nothing
  for the first part of a turn. If the kept figures show it (turns made
  after a reversal moving the axis less than turns continued the same way),
  the slack can be learned by itself and the advice can say "take up a
  quarter turn, then half a turn more". **Measured on 1 November 2026**
  (EQ3 Pro azimuth bolts, a half turn at a time, one bolt eased and the
  other turned in): the two half turns that continued the way the last one
  went moved the axis **0.94° and 0.98°**; the four that came straight
  after a change of direction moved **0.67°, 0.42°, 0.53° and 0.55°**. So a
  turn is worth about 1.9°, and about **0.45° (a quarter turn) is lost to
  slack each time the direction changes**. The 1.5 turns that overshot the
  pole that evening (3.3°, 2.2° a turn) went one way after a reversal had
  already taken the slack up. A quarter turn continuing the same way read
  as nothing (0.3° east before and after), but five checks over the next
  ten minutes with the bolts untouched read 0.19, 0.03, 0.00, 0.15 and
  0.04° east (a scatter of 0.06°): it had moved about 0.2°, and the mount
  settled into it after the check made just after the turn. So a check
  made at once after a small turn can miss part of it, and the scatter of
  a single measurement (0.06°) is small beside the half-turn figures above.
  A "quarter turn" by hand on these small knobs is really 35 to 55° (the
  person's own estimate), 0.1 to 0.15 of a turn: at 1.9° a turn, 0.2 to
  0.3°. A second one the same way, measured a minute after the turn and
  twice, moved it 0.28° (0.08° east to 0.2° west, both readings agreeing).
  Logs: `logs/polar-20261101*.log`.
- **The 2° limit.** It is a fixed first figure. With the bolts' travel
  known, the choice between the bolts and the whole tripod could go by how
  much travel is left on that side.
- **Other mounts' bolts.** The drawings name bolts by where you stand, which
  holds for any mount; drawings of a particular mount head would need a
  description of each kind of mount, and there is one mount so far.

The first test on a clear night is in [validation.md](validation.md),
experiment 17.

## 3. The true home position

The handset takes wherever the mount stood at switch-on for home: RA axis
0°, Dec axis 90°, the tube along the polar axis with the counterweight bar
down. Nothing on an EQ3 says when that is so. If the tube was really a few
degrees off the axis, every reading of that axis is wrong by as much for the
rest of the night.

`./mount.py findhome` measures it:

- It makes **one uninterrupted run** of plate solves at eight hour angles,
  four on each side of the meridian, at one declination, with no correction
  applied. Nothing remembered from another night, or from earlier the same
  night, goes into it.
- A Dec axis that reads wrong moves the aim one way on the east side and the
  other way on the west, where the tube is swung over the pole. An RA axis
  that reads wrong moves it the same way on both. A tube not square to the
  Dec axis changes sides too, but in hour angle. What is left of the polar
  error changes smoothly with hour angle. With `s` +1 on the east side and
  -1 on the west, in degrees:

      hour angle error =  a  +  s c / cos(dec)  -  tan(dec) (p cos h + q sin h)
      Dec error        =  s e               +  p sin h  -  q cos h

  The five unknowns (`a` and `e`, the home errors; `c`, the tube out of
  square; `p` and `q`, the polar error left) are found from the sixteen
  figures by least squares.
- It reports the two home errors, and how far the places sit from that
  account of them: all together (`rms_deg`) and each by itself
  (`residuals`), because an rms can hide one bad place among five good ones.
  Over 0.15°, or a home more than 10° out, and the answer is marked as not
  fitting: nothing will be moved on it.
- One place may be left out, never more: if the other places then fit and
  that one sits more than 0.3° from what they say, it is named, with how
  far out it is, and the answer comes from the rest. Look at its frame.
- The answer must also stand on all the places and not on one: each is
  left out in turn, and if home moves by more than 0.1° for any of them
  (`sway_deg`), it does not fit. That is why there are eight places and not
  six. With six, a single solve 0.6° out was absorbed by the fit and the rms
  stayed under 0.15°; with one place doubted there were then too few left to
  check the rest, and a second bad place went unseen.
- Sixteen figures for five unknowns is still not a great deal to spare, and
  0.15° and 0.1° are first figures from made-up solves. The first real
  run's residuals are what they will be set from.

`./mount.py truehome` then drives to the home just measured: home by the
axis readouts first, as `./mount.py home` goes, then the small step to the
readings where true home lies, and holds with tracking off. `--dry-run`
shows those readings first. It refuses unless the measurement was made in
this session of the handset, within the last two hours, and fitted. Then:

1. Mark both joints, across the gap, where they stand, with something that
   lasts a night of rain: a paint pen, nail varnish or a scratch. Wax crayon
   and chalk wash off, and then home has to be found again.
2. Switch the handset off and on with the mount on its marks, and press
   ENTER through to its main menu (`./mount.py settime` saves typing the date).
3. Run `./mount.py findhome` again. It should now find home within a tenth
   of a degree; what it finds is the slack in the gears and the width of the
   marks.

From then on, home is two marks lined up.

What is and is not established:

- The formulas were checked against the simulator's exact geometry for a
  tilted axis (they agree to 0.001°), and the fit recovers a home 2.95° out
  to 0.01°, and to 0.06° with a tube 0.3° out of square, a polar axis 0.3°
  out and plate solves uncertain by 0.01° all at once.
- The axis conventions are the ones `mount.py` already uses everywhere: the
  RA axis reads 90° on the meridian, and a Dec axis past 90° means the tube
  is over the pole, on the west side. Whether the real mount's readings obey
  the model as the simulated one's do is exactly what the second `findhome`,
  after the restart, shows.
- The move is made by the motors' own readings, so slack in the gears is not
  in it. Coming to home the same way each time keeps that the same.
- A spirit level on the counterweight bar and the tube at the zenith is
  another way to the same end, but the turn from there back to home has not
  been worked through for this mount's readings, and nothing here uses it.

## 4. Pointing, east and west

With home right, `./mount.py pointing` says how far out the aim still is on
each side and whether one correction for each side is enough
([how](tracking.md)).

## 5. That it really turned

On 6 October 2026 the motors stopped while the handset reported every move
as made. Steps 2 to 4 each compare the move asked for with the move the
plate solves show, stop the mount with `MOUNT_NOT_MOVING` if less than a
quarter of it is there, and keep every such judgement
(`cache/moved_log.jsonl`). By day, when the survey has only pictures to go by,
the judgement is recorded and stops nothing: the first real frames showed
the optics' own marks passing for a view that had not changed.
`./mount.py nudge`, a 5° tip from home and back,
is the check for a person standing beside it.

## Polar alignment, 2 November 2026

At ralphie-side, before the stickered baseline above:

- **17:40, from Deneb, the tripod not yet moved** (`--step 12`): 0.8° out,
  0.8° low and 0.3° west.
- **The tripod moved off a tile crack** (`--step 25 --repeat 3`): 1.5° out,
  1.2° west and 1.3° high.
- **Altitude by a leg:** about 2 cm on one leg moved the altitude 2.7°,
  roughly 1.3° a centimetre.
- **Azimuth by the feet:** on the tiles, 6.7 cm a foot moved the axis 2.1°,
  about 3.2 cm for each degree. The configured `tripod_cm_per_degree` is
  2.3 (measured on grass on 15 October).

## Dark frames, 2 November 2026

The 16 s darks at gain 1500 failed at 15:51 in daylight: the first frame
read 4094 of 4095. Daylight leaks past the cap on the tube through the open
mirror cell. Darks need full dark, or a cap on the camera itself. Only 1 s
and 4 s darks at gain 1500 exist; the M31 and M33 patrols shoot 16 s, so
they have no matching darks yet (record: [validation](validation.md#2-november-2026)).

## Darks, flats and bad pixels by camera

Each camera keeps its own masters in its own folder (`calibration/` under
`config.camera_folder()`), and the two cameras are calibrated two ways.

**The 183C** is as it always was: one dark per exposure and gain, a bias,
one flat per `setup`, any of them may be missing, and with a dark and a
bias the dark is scaled to each frame's own hot pixels, since the camera has
no thermometer. A new master replaces the old one.

**The 183M** (any profile with `cooled = true`, or `dark_method =
"matched"`) is matched, never scaled: the IMX183 has amp glow, which does
not follow the hot pixels. `./calibrate.py` waits for the cooler and keeps:

- darks by exposure, gain, offset, binning, readout speed and the cooler's
  set temperature (`dark-16s-g800-o50-b1-s0-t-5-v1.fits`); each frame's
  header carries all six (`OFFSET` and `XBINNING` from the camera since
  4 November 2026), and the dark used is the newest whose cards are the
  same. The cooler holds the temperature, so darks are made with the cap
  on, indoors or on a cloudy night, never in a clear window;
- flats by train and filter (`flat-183m-cc-L-v1.fits`), kept raw; the
  flat-dark is a dark at the flat's exposure from the same library, taken
  off and the flat normalised when it is used. Dawn sky flats need nothing
  over the tube: `./calibrate.py flat --filters B G R L --twilight` waits
  with the camera closed for the Sun at -12°, then takes each filter as
  the sky brightens (B first, the faintest through its filter), and
  warms the camera up after. `schedule.py end` starts it by itself once
  the mount is parked after a night with this camera, so the flats match
  the night's light path; the flat-darks wait for the cap (5 November
  2026: the 183M's first night got none, and the camera was packed away
  before any could be taken);
- a bad-pixel map (`./calibrate.py badpixels`, from the longest dark kept),
  whose pixels are replaced by the median of their neighbours; no bias.

Every 183M master is a new version (`-vN`), never overwriting one, and every
stack records which masters it used: `TY_DARK`, `TY_FLAT`, `TY_FDARK`,
`TY_BPM` in `final.fits` and `live.fits`, and `calibration` in
`restack.json` (the 183C's stacks record theirs too). A new library never
changes what an old result meant.

**It fails closed.** A 183M frame whose dark, flat, flat-dark or bad-pixel
map is missing or does not match is still stacked for the stream or a quick
look, but the stack says `TY_CALIB = F` and what was missing (`TY_MISS`,
and `restack.json`), and restack says UNCALIBRATED. Science refuses it with
`CALIBRATION_MISSING`, saying which: a difference image (either stack), so
it never enters a search; depth and its sweep; and photometry (variables,
precision, and so transits and the star watches). The 183C's frames are
taken as they always were.

## The handset's clock

`./mount.py settime` gives the handset the computer's date and time and the
site's position. It is run by hand and is not done automatically, for two
reasons. A handset still on its version screen answers commands but moves
by the wrong amounts, and the one sign of that the software has is the
default year, 2022, which setting the clock would wipe out. And it has run
on the real handset once (7 October 2026, at the main menu, where it worked):
whether the handset takes these commands at other times, and whether they
disturb anything else it holds, is not yet known.
