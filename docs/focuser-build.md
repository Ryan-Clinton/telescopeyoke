# The motor focuser: from the first idea to a working build

[README](../README.md) · [All docs](README.md) · [The focuser](focuser.md) · [Validation](validation.md)

How the 150P's motor focuser came to be, from a 28BYJ-48 on a printed
bracket in mid-October 2026 to a NEMA 17 that focuses the cooled 183M's
train by itself, five weeks later. The reference for building and using it
is [focuser.md](focuser.md); this is the story, with what went wrong, since
most of what the project knows about focusing came from that.

## Why a motor at all

The telescope is a Sky-Watcher 150P on an EQ3 Pro, run from a laptop beside
it. Everything else could be done from indoors (the GoTo, the camera, plate
solving, the sky watch); focus meant going out to the knob in the cold, and
on a Crayford-style focuser the camera moves when it is touched. The aim was
simple: focus is the motor's job, run from the laptop, and nobody touches
the telescope.

## Part one: the 28BYJ-48 (12 October to 9 November)

**The first build, 12 October.** A 28BYJ-48 stepper on its ULN2003 board,
driven by an Arduino Nano clone (CH340 on USB), on a printed bracket and
coupler: AstroCosas's "Skywatcher 200P focuser" from Thingiverse, made for
the 200P but with a coupler for a 4 mm shaft. There were no short enough
screws for the coupler that night, so one was cut down with a Dremel, with
ordinary glasses for eye protection, which was more frightening than
expected. `focuser.py` loaded the firmware and turned the drawtube the same
day.

**First focus by motor, 13 to 17 October.** On 13 October the motor focused
the telescope, but from an inline script that was never kept; two nights
later nothing knew it could. That gave the project one of its rules: anything
used every night is written as a project command before its first use. By
15 October `focus.py --motor` reached HFR 2.47 with the 183C, and on
17 October 2.28 then 2.14. It now measures first (`--check`) and leaves good
focus alone. The gear slack was large, so it always finished moving inward.

**Measuring it without stars, 18 to 19 October.** The motor's screws were
tightened to take up slack and a Sharpie line drawn on the drawtube at
focus. To see what the motor really did, the owner built a bench rig: a
printed protractor, a blacked cocktail stick on the shaft, a phone on a
webcam mount streaming through DroidCam. `focuser.py bench` read the
stick's angle from the pictures: 0.088° a half-step, about 30 half-steps of
slack each way, back to the same place within a fraction of a degree. The
same day came `--walk-in`: from a little outside focus, small steps in,
downhill only, to the sharpest.

**Too weak, 20 to 22 October.** With the camera on, the motor would not push
the drawtube outward. Run free it was weaker one way than the other, so this
one was faulty as well as marginal. Two-coil stepping gave about a quarter
more torque, not enough. On the sky on 21 to 22 October the walk-in still
worked inward from a hand-set start (best HFR 2.19), but the owner was
disappointed that it did no better than fingers and the spoken-numbers aid.
The NEMA 17 parts were chosen and, after AliExpress let some orders expire,
ordered on 22 October for about £32: a 17HS4401, two TMC2209 drivers, a
screw-terminal carrier, a 12 V 2 A supply, and couplers.

**The night lost to a sweep, 23 October.** With focus set by hand a touch
out, the full `--motor` sweep was run on guessed sizes, the vanishing stars
were blamed on cloud, it was stopped part way twice, and the drawtube was
left about an inch from the Sharpie line. Nothing was imaged
([the record](nights/2026-10-23/focus-runaway.md)). Since then a hook
refuses the sweeps, and every move stays within a set travel of where a run
starts.

**A lift, and a metal coupler, 24 October to 1 November.** The walk-in learned
to try one move back out to its best (24 October). On 30 October, with bent
pins on the board straightened and the Nano on the powered hub, the motor
lifted the camera outward again over half a turn; on the laptop's own port it
stuck, so the hub's power mattered. On 31 October a 4 × 5 mm metal elastic
coupler replaced the printed one (two of the batch came with bores about four
times too big), and a thermistor went on the Nano's A0 for the camera's
temperature. On 1 November the motor's wiring order was found reversed, so
`[focuser] reversed` keeps plus as out.

**The 183M ends it, 4 November.** Gary's mono rig (the cooled Hypercam
183M, a Starlight Xpress wheel, a 0.9x corrector) went on the drawtube, with
about 10 mm cut off the tube so it reaches focus. The 28BYJ-48 could not move
that train at all: 320 half-steps out did nothing. Focus went back to the
hand and the spoken numbers until the NEMA 17.

## Part two: the NEMA 17 (2 to 18 November)

**Parts and a bracket, 2 to 8 November.** The motor arrived on 2 November
(and the rule came that a part in its box is news, not a cue to write its
code). The bracket is Tnever's "Auto Focus Motor Mount on Crayford focuser"
(Printables 436129), made for a Celestron Omni 150 and said to fit the 150/750.
The first print cracked at its 2 mm foot plate before it was ever fitted;
versions thickened underneath, so the face and the motor's height are
unchanged, were made, and 4 mm was chosen. The owner also wanted the
electronics off the focuser, in a box with only the motor lead running to it,
and one was designed on 8 November.

**One direction only, 9 to 16 November.** On the bench the NEMA 17 turned one
way and hummed the other, on every driver tried
([the bench session](nights/2026-11-09/nema-bench.md)). The first TMC2209 was
seated backwards by a guess at the board's ends and ran under 12 V that way;
the board's switch holes were read pin by pin with the Nano
(`./focuser.py vref`); the microstep settings were all tried. The write-up
went out for an outside review on 10 November, the focuser went back to the
bench, and two BigTreeTech TMC2209 V1.3 drivers were ordered from China, with
a multimeter. They came on 16 November, and the cause was found the same
day: **the carrier makes no 5 V of its own.** Its 5 V row (CN5) had nothing on
it, so the driver's logic ran on what leaked in from the Nano's signal wires:
enough with DIR high, too little with DIR low. With the Nano's 5V on CN5, the
BTT driver turned both ways. Measured on a dial, it runs at 1/64, eight times
finer than the firmware assumed; with 200 microsteps sent for every 64
half-steps, 512 half-steps turned 44.6° (45° on paper), with 4 half-steps of
slack, back within 0.01°.

**Onto the telescope, 16 to 17 November.** Fitting it showed why the print
is so thin: the four screws from the focuser are tiny, and a thicker plate
would leave them too short. Turning the motor round on the print to bring the
leads to a better side stripped the head off an M3 screw in a place too
tight to grip. Under the focuser's plate there were no gears: the 150P's
focuser is a smooth drawtube driven by friction from a smooth roller. With
the camera vertical, its whole weight on the drawtube, the tension screws
were brought up until the weight did not run it down, and Gary set them that
afternoon. The motor then turned a few turns each way on the telescope.

**First light, 18 November.** Through thin, thickening cloud, on one bright
star near Mirfak ([the night](nights/2026-11-18/focuser.md)):

- the star was found by a spiral search 38' from where the GoTo put it, as a
  ring about 340 px across: focus was far out;
- the far-focus search, its steps cut that evening from half a turn (half the
  drawtube's whole travel on this coupling) to a thirty-second of a turn,
  was confused by the star drifting out of the frame;
- found again, the ring measured 470, 303, 82 and 29 px as the motor took the
  drawtube out, and 50 px past focus: about 0.4 of a turn, lifting the whole
  train;
- the walk-in went from HFR 10.89 to its best 1.71, then out past the best and
  back for the slack, and finished at **HFR 1.67**, saying the motor had
  lifted the drawtube.

No hand touched the knob.

## What was learned

- **A focuser's motor has to lift the camera.** The 28BYJ-48 could push a
  light train in and never reliably pull a heavy one out; most of October's
  troubles came from that. The NEMA 17 on a proper driver does it with room
  to spare.
- **Read the board, not its picture.** The one-direction fault was a missing
  5 V on a carrier that looked as if it made its own. A meter and the board's
  pin map found it in an afternoon, after a week of trying drivers.
- **Measure the motor, don't assume it.** The driver's real step (1/64, not
  1/8) and the knob's real travel (half a turn is half the drawtube's travel)
  were both different from what the code assumed, and each one sized a move
  wrongly until it was measured.
- **Small, measured steps beat clever sweeps.** The walk-in, a small step
  out and tiny steps in, has worked on every drive; the sweep on guessed
  sizes lost a night. The sweeps stay refused until the slack and step are
  measured on the sky.
- **When the stars vanish, look at the frame first.** On first light the
  "lost focus" was a star that had drifted out of view.
- **Keep the leads slack.** The focuser's 12 V lead, pulled tight across the
  mount, may have held the tube back in Dec during guiding the same night.

## Still to do

- Measure the gear slack and the sweep step on the sky (`./focus.py
  --measure-backlash`, `--measure-step`), so the full sweep can run.
- Try the fixed far-focus search (6055f3d) from far out on the sky.
- Find whether the drawtube holds focus with the driver off between moves.
- The electronics box, and the cloud sensor that may share the Nano.

## The code, in order

The firmware is `firmware/focuser/focuser.ino` (STEP/DIR/EN on D9, D10, D8;
the driver off when still; `:H` to hold). `focuser.py` loads it and turns
the motor (`flash`, `test`, `move`, `bench`, `vref`, `temp`); `focus.py`
focuses with it (`--check`, `--find`, `--walk-in`, and the guarded sweeps).
The git history of those files, with each commit's reason, runs from
acacabf (12 October) to 6055f3d (18 November).
