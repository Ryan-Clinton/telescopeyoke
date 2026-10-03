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

What this cannot do: with the axis off the pole, the field still turns slowly
about the target, and the gears' own periodic wobble is untouched. The
stacker's rotation alignment deals with the first; short exposures deal with
the second. It is drift assist, not guiding.
