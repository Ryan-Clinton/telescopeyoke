# Calibrating a mount, in order

[Back to the README](../README.md)

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

**None of steps 2 to 5 has been run on the real mount with this code**
except single polar measurements. What follows is how each is meant to
work, and what is proven only on the simulated mount.

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
five rounds took the axis from 5.2° to 0.2° (6 October 2026). `--repeat 5`,
with the bolts left alone, gives the scatter of the measurement itself,
which says what a reading of 0.2° is worth. That has not been run yet.

## 3. The true home position

The handset takes wherever the mount stood at switch-on for home: RA axis
0°, Dec axis 90°, the tube along the polar axis with the counterweight bar
down. Nothing on an EQ3 says when that is so. If the tube was really a few
degrees off the axis, every reading of that axis is wrong by as much for the
rest of the night.

`./mount.py findhome` measures it:

- It makes **one uninterrupted run** of plate solves at six hour angles,
  three on each side of the meridian, at one declination, with no correction
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
  square; `p` and `q`, the polar error left) are found from the twelve
  figures by least squares.
- It reports the two home errors, and how far the places sit from that
  account of them (`rms_deg`). Over 0.15°, or a home more than 10° out, and
  the answer is marked as not fitting: nothing will be moved on it.

`./mount.py truehome` then drives to the home just measured: home by the
axis readouts first, as `./mount.py home` goes, then the small step to the
readings where true home lies, and holds with tracking off. `--dry-run`
shows those readings first. It refuses unless the measurement was made in
this session of the handset, within the last two hours, and fitted. Then:

1. Mark both joints, across the gap, where they stand.
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

## The handset's clock

`./mount.py settime` gives the handset the computer's date and time and the
site's position. It is run by hand and is not done automatically, for two
reasons. A handset still on its version screen answers commands but moves
by the wrong amounts, and the one sign of that the software has is the
default year, 2022, which setting the clock would wipe out. And it has run
on the real handset once (7 October 2026, at the main menu, where it worked):
whether the handset takes these commands at other times, and whether they
disturb anything else it holds, is not yet known.
