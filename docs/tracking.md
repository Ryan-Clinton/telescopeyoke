# The mount is wonky; measure how wonky

[README](../README.md) · [All docs](README.md) · Guides: [First night](first-night.md) · [Setup](setup.md) · [Imaging](imaging.md) · [Calibration](calibration.md) · [Focus](focus.md) · Science: [Discovery](discovery.md) · [Results](results.md) · [Validation](validation.md) · [Data](data.md) · Developers: [Contributing](../CONTRIBUTING.md) · [Agents](agents/README.md)

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

- `./mount.py pointing` goes to eight hour angles at Dec +40°, four each side
  of the meridian, with no correction applied, plate-solves at each and
  records how far out the aim is. It says, for each side, the average error,
  how far any one place is from that average and how the error changes with
  hour angle, and whether one correction for each side is enough (no place
  more than 0.25° from its side's average). Each side's average is kept as
  that side's pointing error. Places too low or behind something known are
  left out; the tube swings over the pole once. `--hours` and `--dec` alter
  it; the result is kept in `cache/pointing_survey.json`.

It was first run on the real mount on 17 October 2026 (`docs/validation.md`).

What this cannot do: with the axis off the pole, the field still turns slowly
about the target, and the gears' own periodic wobble is untouched. The
stacker's rotation alignment deals with the first; short exposures deal with
the second. It is drift assist, not guiding.
