# 19-20 November 2026: the Dec gears' slack, measured and not yet compensated

[All docs](../../README.md) · [Tonight's tests](test-plan.md) · [The first Dec report, for Gary](dec-guiding.md)

The EQ3 Pro since its service on 16 November, on the SynScan Wi-Fi
adapter; guide camera binned, 9.55"/px; guide rate 7.1"/s; one guide step
in Dec is a 1.5 s pulse, 10.7" of motor turn. Times UT. The raw logs are in
[dec-records/](dec-records/).

**The short answer: the slack has not been measured to a number, and
nothing compensates for it on the sky yet.** Five measurements tonight
gave four different sizes, and the one-way Dec guiding written for it has
never run with Dec pulses going out.

## The clutch, through the night

| Time | Clutch |
|---|---|
| to 21:31 at least | as left after the balance check at 17:43 |
| between 21:31 and 22:20 (time not noted) | tightened "a little" (owner) |
| 22:20 | a plate solve found Dec 3° from where the motor said: the tube had slipped |
| 22:39 | set lighter: "barely set, then a tiny push" |
| 23:07 | found very loose (the tube moved fitting a hot water bottle to the guide scope); tightened "a lot more" |

## Every Dec measurement tonight

| Time | What | Dec | Slack before the star moved | Then | Log |
|---|---|---|---|---|---|
| 20:31 | calibration, M34 | +43.1 | 12 steps | barely moves | [dec-guiding.md](dec-guiding.md) |
| 20:44 | calibration, M34 | +43.2 | 8 steps | 15" for 24 steps, 256" due | [dec-guiding.md](dec-guiding.md) |
| 20:46 | pulse test (motor board's own axis counts) | | | the board's Dec count moves 35.7" each way in 5 s: exactly the guide rate (the count, not the shaft) | [dec-guiding.md](dec-guiding.md) |
| 21:24 | Dec test, north | +57.1 | about 10-13 steps of creep, then a ~55" jump | full rate (11"/step) | [dectest-2124.txt](dec-records/dectest-2124.txt) |
| 21:31 | calibration | +57.2 | 4 steps north; reversals 8.8-17.7 s, "at least" | north 0.80 px/s, full rate | (guide-calibration.png sent to Telegram) |
| 22:31 | Dec test, clutch "a little" tighter | +43.2 | never caught up | north 77" of 639" due (12%), south 127" (20%) | [dectest-2231.txt](dec-records/dectest-2231.txt) |
| 23:16 | Dec test, clutch tight | +43.2 | north about 30-35 steps, south about 40 | then 96-114" per 10 steps, full rate | [dectest-2316.txt](dec-records/dectest-2316.txt) |
| 23:29 | calibration, IC 405 | +22.1 | 7 steps north; reversals 8.7-18 s, "at least" | north 0.77 px/s, full rate | [guider-calibrations.txt](dec-records/guider-calibrations.txt) |
| 23:52 | calibration, IC 405 | +22.0 | **more than 60 steps** | nothing: Dec dropped, RA-only guiding | [guider-calibrations.txt](dec-records/guider-calibrations.txt) |

(`guider-calibrations.txt` also holds the 14-15 November calibrations,
before the service: Dec slack taken up in 4-5 steps then full rate,
reversals about 8-15 s, every time.)

## What is settled

- **The ST4 lead and the motor board pass**: north and south pulses move
  the board's Dec count 35.7" each way in 5 s, exactly the guide rate
  (20:46). That count is the steps the board sends (`scope.axes()`, the
  SynScan position); the motor is an open-loop stepper, so it does **not**
  show that the motor shaft turned, that the worm turned, or that the axis
  followed. Where the movement is lost, between the board and the tube, is
  not yet known.
- **The loose clutch was the slipping.** The 3° slip at 22:20, the 12% and
  20% at 22:31 and the tube moving by hand at 23:07 all go with a clutch
  too light; with it tight (23:16 on) Dec has held: both GoTos to IC 405
  landed within 1', and the mount's Dec stayed +22.00° for an hour.
- **When the drive does catch, Dec moves at the full guide rate** (21:24,
  21:31, 23:16, 23:29).

## Slack, or something sticking

Two different faults, not to be run together:

- **slack** (backlash): movement lost after a reversal, the same each time
  from the same side, then a steady full rate;
- **sticking** (stiction, or a drive that engages only now and then): the
  axis holds against the motor until the force builds, then lets go with a
  jump, at any time, reversal or not.

21:24 looks like sticking: 13 north steps of creep, a jump of about 55",
then full rate. 23:52 does too: Dec had not been reversed by the guider
(it had run unguided), and 60 steps moved nothing. The page below says
"slack" for the steps before the star moved, whichever it was.

## What is not settled

1. **The slack's size.** 4, 7, 8, 12, 30-40 and more than 60 steps. A
   fixed backlash would give the same figure from the same side. Not one
   measurement was repeated at the same pointing and clutch setting, so it
   is unknown whether it wanders on its own (a worm mesh tight in places
   and loose in others), with where the tube points (balance, Dec +22
   against +43 and +57), or with the clutch.
2. **The 23:52 failure.** At the same pointing as the 23:29 pass, 23
   minutes later, 60 north steps (642" of motor turn) moved nothing. Before
   it the mount had run unguided for 13 minutes and dithered, so the gears
   may have been at the far side of their slack; that alone should be
   30-40 steps by 23:16's figure, not more than 60.
3. **Compensation on the sky.** The code has (commits 1815275, dea39be):
   slack taken up before the north leg, up to 60 steps, counted only when
   a step moves the star at half the rate due or more; RA-only guiding
   when Dec does not follow; and `--dec-one-way` so Dec is only ever
   pulsed one way and the slack is crossed once. **The one-way Dec
   guiding has not run with pulses going out**: every guided run tonight
   either failed to start or dropped Dec. The guider does take up slack on a Dec
   reversal when guiding both ways (`SLACK_START`, half the measured slack
   to start); one-way guiding avoids reversals altogether.
4. **The calibration's 60-step limit** is less than 23:52 needed.
5. **22:31 does not add up as Dec movement.** North moved the star 77",
   south 127", and it ended 153" from its start: for opposite moves it
   would be about 50". The two legs went about 86° apart. The clutch was
   slipping then; drift is taken off before the legs, but the track itself
   was not kept, so whether the tube moved sideways, sagged or the drift
   changed is unknown.
6. **A calibration that kept RA alone is not tried on Dec again** until a
   person asks for a fresh calibration (`./guidecam.py calibrate`). An
   automatic retry of up to 60 north steps was added and taken out again
   the same night: an automatic test on a drive not yet understood.

## The guided run, RA only (23:54 on)

[guiding-2354-ra-only.txt](dec-records/guiding-2354-ra-only.txt), every guide
look, about 5.4 s apart: RA held within ±3" (RMS about 1-2"), Dec sent
nothing and drifted **south at a steady 2.8"/min** (10" every 40 looks, to
-50" after 18 minutes). The main camera sees it too: a star moved 3-4 px
between 120 s frames, the same way every time
([ic405-guided-frames.jsonl](dec-records/ic405-guided-frames.jsonl)).

A steady drift with Dec not pulsed is most likely the polar axis, which
drifts Dec at about 0.26"/min for each arcminute it is out, so about 10'
out (inferred, not measured; a creeping Dec axis would look the same). The tripod and tube were handled fitting the hot water
bottle and dew shield; the 17:41 polar alignment had it 0.2° (12') out.

The frames are still good at 120 s: 5 kept, FWHM 5.9-6.1 px, roundness
0.89-0.90, 300 stars each (unguided 16 s frames earlier: 4.2-4.8 px,
0.79-0.90, 107-124 stars). 300 s is off: about 10" of Dec drift a frame.

## The explanations, as the evidence stands

| Explanation | Supported by | Contradicted by | Unknown |
|---|---|---|---|
| The clutch slipped | the 3° slip at 22:20, 12%/20% at 22:31, the tube moved by hand at 23:07; nothing slipped after it was tightened | | whether it still gives a little at guide-rate force |
| A large slack (backlash) of a fixed size | full rate once caught (21:24, 21:31, 23:16, 23:29) | the size: 4 to more than 60 steps | whether it repeats when the last real Dec movement is controlled |
| The slack depends on which way Dec last moved | could explain the spread | | **not shown**: the -0.4' and +1.0' before 23:29 and 23:52 were plate-solve residuals, under the 2' centring limit, so **no centring move was made** after either. The last Dec movements were the GoTos, the earlier calibration's legs and the unguided run's dithers, and their final directions were not recorded |
| Sticking (stiction) | 21:24's creep then a ~55" jump; 23:52 moving nothing for 60 steps; **10 November 2026, before the service**: one-way south pulses moved nothing for half a minute, then a 20-30" jump (the `--dec-stuck` note in `guider.py`) | | whether it is the grease (1-2 °C), the worm's mesh, balance or the clutch |
| The service caused it | 18 November's Capella calibrations failed the same way | 10 November's sticking and 12 November's ~11 s slack came before it; 14-15 November calibrations passed (4-5 steps) | what the service changed |
| The mount's Dec creep fought the guide pulses | `mount.py` sets a Dec creep after every GoTo from the drift model, and `guidecam.py calibrate` and `dectest` do not turn it off | the creep is set in 0.25"/s steps (`dec_creep`): tonight's drift (0.03-0.08"/s from a 0.2-0.3° polar error) rounds to 0, and at most it is 0.25"/s against 7.1"/s pulses; guided runs turn it off (`Supervisor.creep_off`); `cache/drift_model.json` holds no drift observations and creep 0.0 | the creep actually set before the standalone tests (20:31, 20:44, the Dec tests): only the latest is kept |
| The electronics | | the board counts guide-rate steps both ways (20:46) | whether the motor shaft turns: the count is open-loop |
| The guide star not being seen | 23:31-23:52: the run's guider ran at the camera's default gain and saw nothing (fixed, 2ac4572); before that, dew | | **a separate fault**: it stopped guiding from starting, not Dec from moving |

## The controlled test (designed, not run)

Not to be run until the owner says so. It needs a new mode of `guidecam.py
dectest`, written as a command first. Through the same ST4 path the guider
uses, the guide camera measuring the star after every step:

0. Set the Dec creep to 0 and record it; tracking on; nothing else moving
   (no run, no dither, no GoTo during the test). Note the last GoTo.
1. **Engage north**: 1.5 s north steps until the star moves north at 80% of
   the rate due or more for 5 steps in a row. Record the steps it took.
   Stop at 80 steps: "never engaged north".
2. **Idle control**: 120 s with no pulses (the drift measured), then 10
   north steps: once engaged, the same way after a rest should answer at
   once. If it does not, it is sticking, not slack.
3. **Reverse south**: south steps until it moves south at 80% for 5 in a
   row. The steps before that are the reversal's slack. Stop at 80.
4. **Idle control** south, as in 2.
5. **Reverse north** again, as in 3. Then the whole cycle once more.

Stop at once on: 80 steps in one direction without engaging, the star
lost, or the star more than 15' from where it started. At most about 14'
of pulses each way (80 x 10.7"); about 25-40 minutes, at about 4 s a step.

What it tells: the slack the same on each reversal and none after an idle
rest is backlash of a fixed size; slack that varies, or a rest that needs
taking up again, is sticking or the mesh. Neither settles the mechanical
cause: that is the daylight drive-response test below, and Gary.

## The daylight drive-response test


First find **where** the movement is lost, before any more calibration
changes or long Dec tests. Daylight, the tube on a distant landmark, the
clutch tight and untouched, nothing else moving:

1. A strip of tape as a flag on the Dec motor's shaft or the worm's end,
   and a chalk line across the Dec axis and its housing.
2. `./guidecam.py pulse --seconds 5`, several times in the same direction,
   then the other: the person watches the flag, the worm and the line.
3. The main camera on the landmark before and after each set
   (`moved.py` judges two pictures): the tube's own movement, measured
   apart from the board's count and from the guide camera.

| What is seen when the star (or landmark) does not move | Where it is |
|---|---|
| the motor flag does not turn | the motor or its drive from the board |
| the motor turns, the worm does not | the coupling between them (grub screw, gears) |
| the worm turns, the axis does not | the worm's mesh with the wheel, binding, or the clutch |
| the axis turns, the picture does not | the camera, the guide scope's mounting, or the measuring |

Tonight stays on RA-only guiding at 120 s. A polar alignment at 00:30
measured 0.3° (0.15° east, 0.24° low); the bolts were left alone: with Dec
guided the error would not matter, and with RA only it is what keeps the
Dec drift one way.

## The controlled test, run (20 November, 00:57-01:03)

`./guidecam.py dectest --engage --cycles 1` (commit d03b044) at IC 405,
Dec +21.9, east of the pier, guide camera at gain 400 (e98e25c; at its
default gain the first try at 00:56 found no star). The Dec creep was set
to 0 first. Nothing else moved during it: the imaging run was stopped and
no GoTo was made after the run's own at 00:51. Records:
[dec-engage-test-0059.txt](dec-records/dec-engage-test-0059.txt) (what it
printed), [dec-engage-test-0059.json](dec-records/dec-engage-test-0059.json)
(every look, drift taken off) and
[guide-cal-2359-ra-only.json](dec-records/guide-cal-2359-ra-only.json)
(the calibration whose RA direction the table below is split by).

**North never engaged in 80 steps; the test stopped there**, as designed,
before any rest or reversal. Steps of 1.5 s, 10.6" due each, 850" in all.
The track split along the calibrated RA direction and across it (Dec):

| Steps | Along Dec | Along RA |
|---|---|---|
| 0-10 | 6" | +10" |
| 10-35 | a further 47", steadily (about 2" a step: a fifth of the rate) | back to -11" |
| 35-80 | **nothing**: within 3" of -57" for 45 steps (480" of pulses) | wandering within ±10", back to 0 |

What it shows:

- **Not slack of any size**: slack is nothing, then the full rate. This
  was a slow movement of about 55", then a complete stop with the pulses
  still going out.
- **Not the last direction**: the creep was off and no reversal or GoTo
  came before it within the test.
- **The same as 23:52** (60 steps, nothing) **and 22:31** (12-20% of the
  rate).

What it does not show:

- **Which way the 55" went.** The calibration in force (23:59) kept RA
  alone; its north is the perpendicular to RA, with a sign assumed, not
  measured. The 55" could be the axis following the north pulses at a
  fifth of the rate, or settling south against them.
- **Where the movement is lost**: the motor not turning, the worm turning
  without driving the wheel, or the clutch slipping, look the same from
  the guide camera. The daylight drive-response test, or a person's hand
  on the motor housing and an eye on a tape mark across the clutch while
  pulses go, separates them.
- RA's ±10" wander during the test is about the size of the seeing and of
  the drift left after the drift measured before the test was taken off.

## After the result: what changed, and what is next

- **The test now counts only Dec movement, the way it pushes** (d12362c):
  across the calibrated RA direction, with the sign learned from the first
  leg that engages. 00:57's test counted movement of any direction; its
  failure stands (nothing moved for 45 steps), but a success under the old
  rule would not have proved Dec moved the right way.
- **The board's Dec count is now kept with every look** (`dec_axis`): does
  the controller register each step when the star does not move.
- **`--native`** sends the same steps as the mount's own slow move (the
  handset's variable rate, the command the photometric hold uses) in place
  of the ST4 lead. Run back to back with the ST4 test, at one pointing:
  both failing points at the drive (motor, gears, worm, clutch, load);
  native working and ST4 not points at the ST4 path.
- **Accurate GoTos do not show the drive answers guide-rate moves**: a
  slew's force can carry it through a resistance a 7"/s move does not.
- **The load on the axis is not known.** The assembled tube (150P,
  183M, filter wheel, motor focuser, guide scope and camera, 1 kg of sand,
  and tonight a hot water bottle on the guide scope) has never been
  weighed; set against the mount's rated payload it may be over. To weigh:
  the tube off the mount, on bathroom scales.
- **The drift measured before a test is taken off for the whole test**
  (eight 2 s frames, then extrapolated over minutes): the 55" and the
  flatness after it carry that uncertainty, a few arcseconds a minute,
  not the hundreds of arcseconds a working drive would have moved.
