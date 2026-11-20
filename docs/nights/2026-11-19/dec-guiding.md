# 19 November 2026: Dec does not follow at guide rate (for Gary)

[All docs](../../README.md) · [Tonight's tests](test-plan.md) · [The 18 November guiding](../2026-11-18/focuser.md) · [After the clutch: the slack](dec-slack.md)

The EQ3 Pro since its service on 16 November, on the SynScan Wi-Fi
adapter. Balance: 1 kg of sand taped to the tube (700 g at the back,
300 g opposite the guide scope), and balanced again by hand this evening.
Guide camera binned, 9.55"/px; guide rate 7.1"/s. Air about 1.5 to 2 °C.
Times UT.

## What was measured

**Two calibrations on M34** (Dec +43°, hour angle -2.7 h, east of the
pier: the way the tube sat for 18 November's Capella run):

| | 20:31 | 20:44 |
|---|---|---|
| RA west | | 10 steps of 2.0 s, the star moved 134" |
| RA east | | 11 steps of 2.0 s back, 103" |
| Dec slack (north until the star moves) | 12 steps of 1.5 s (18 s) | 8 steps (12 s) |
| Dec north after that | 15 steps of 1.5 s moved the star 1.6 px (15") | 15 steps moved it 0.3 px (3") |
| due at the guide rate | about 160" | about 160" |

Both failed there: the guider stops when north pulses do not move the
star. The 20:44 run's track, look by look, is
[guide-calibration-20261119.png](guide-calibration-20261119.png): RA two
clean straight lines out and back, then Dec flat for 36 s of north
pulses (24 steps in all, slack included: 15" against 256" due).

**The pulse test** (20:46, `./guidecam.py pulse --seconds 5`): the motor
board's own axis positions around each 5 s pulse, the mount tracking:

| Pulse | RA axis beyond tracking | Dec axis |
|---|---|---|
| none | 0 (tracking 75.9" in 5 s) | 0.0" |
| north | | **+35.7"** |
| south | | **-35.7"** |
| east | +32.2" | 0.0" |
| west | -39.4" | 0.0" |

## What it shows

- **The Dec motor turns, at exactly the guide rate (7.1"/s), both ways.**
  The ST4 lead and the motor board are fine.
- **The tube does not follow the Dec motor at guide rate.** After the
  slack, 22 s of north pulses moved the star 3 to 15" where the motor
  turned about 160".
- RA follows its motor properly both ways.
- GoTos move Dec normally (M34 centred to 0.1' tonight).
- The same as 18 November on Capella, before the sand was added (17 and
  10 slack steps, then 15 north steps moved the star 0.6 and 0.9 px), so
  the balance change made no difference.

## What could do it (the questions for Gary)

1. The Dec worm not meshing with the wheel since the service, or set far
   loose: the motor and worm turn, the wheel catches only now and then.
   GoTos at speed may still drag the wheel round.
2. Stiff fresh grease at 1-2 °C: at guide rate the force is small and the
   axis sticks until it builds; GoTos break through it.
3. The Dec clutch: less likely, since a clutch slips under more force, not
   less.

What would settle it: a hand-rock test of the Dec axis with the clutch
locked (play you can feel is the worm), and the Dec worm's mesh checked.
