# The mount is wonky; measure how wonky

[Back to the README](../README.md)

telescopeyoke does not assume a careful polar alignment, and it does not
trust the handset's own alignment model. It measures what the stars actually
do.

A polar axis that misses the pole makes the aim slide slowly in declination,
at a rate that depends only on the hour angle. So:

- `./mount.py compensate` photographs the sky at three RA positions, works
  out where the axis really points, and tells you how to fix it mechanically
  ("swing the north end 1.4° west, raise the axis 0.6°"). Or leave it: it
  then predicts the drift where the telescope is aimed, sets the Dec motor
  creeping against it, measures what is left, and says what exposure that
  allows.
- After that, every GoTo starts with the creep its part of the sky needs.
- `./mount.py drift` measures and trims the drift on its own: several plate
  solves with a line fitted through them, an uncertainty on the answer, part
  of the error corrected at a time, and the Dec motor never reversed for a
  small overshoot, because its gears have slack.
- `./shoot.py --assist` lets the pictures themselves report the drift, and
  trims the creep as the run goes.

Before any of that is trusted, measure how the mount answers:

- `./mount.py response` sets the Dec motor creeping at 0, -0.25, -0.5, -0.75
  and -1 arcsecond a second in turn, waits a minute each time for the gears
  to take it up, and measures the drift three times at each. It puts a
  straight line through the fifteen readings and says what the drift is with
  no creep, how much each arcsecond a second of creep changes it (it should
  be exactly one), how far repeats at one creep sit from each other, and
  whether any creep sits further off the line than the repeats explain:
  slack, a dead zone, or a rate the handset rounds away. About 35 minutes on
  one target; nothing is slewed, and the creep is put back afterwards. It
  changes nothing about how the creep is chosen. `--rates` and `--repeats`
  alter the sweep; the result is kept in `cache/creep_response.json`.
- `./mount.py pointing` goes to eight hour angles at Dec +40°, four each side
  of the meridian, with no correction applied, plate-solves at each and
  records how far out the aim is. It says, for each side, the average error,
  how far any one place is from that average and how the error changes with
  hour angle, and whether one correction for each side is enough (no place
  more than 0.25° from its side's average). Each side's average is kept as
  that side's pointing error. Places too low or behind something known are
  left out; the tube swings over the pole once. `--hours` and `--dec` alter
  it; the result is kept in `cache/pointing_survey.json`.

Neither has been run on the real mount yet.

What this cannot do: with the axis off the pole, the field still turns slowly
about the target, and the gears' own periodic wobble is untouched. The
stacker's rotation alignment deals with the first; short exposures deal with
the second. It is drift assist, not guiding.
