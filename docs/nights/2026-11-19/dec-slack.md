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
| 20:46 | pulse test (motor board's own axis counts) | | | the Dec motor turns 35.7" each way in 5 s: exactly the guide rate | [dec-guiding.md](dec-guiding.md) |
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

- **The electronics are fine.** The Dec motor turns at exactly the guide
  rate both ways (20:46); the ST4 lead and motor board pass.
- **The loose clutch was the slipping.** The 3° slip at 22:20, the 12% and
  20% at 22:31 and the tube moving by hand at 23:07 all go with a clutch
  too light; with it tight (23:16 on) Dec has held: both GoTos to IC 405
  landed within 1', and the mount's Dec stayed +22.00° for an hour.
- **When the gears do catch, Dec moves at the full guide rate** (21:24,
  21:31, 23:16, 23:29).

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
   either failed to start or dropped Dec. Nothing sends an extra pulse
   the size of the slack on a reversal; one-way guiding was chosen instead.
4. **The calibration's 60-step limit** is less than 23:52 needed.

## The guided run, RA only (23:54 on)

[guiding-2354-ra-only.txt](dec-records/guiding-2354-ra-only.txt), every guide
look, about 5.4 s apart: RA held within ±3" (RMS about 1-2"), Dec sent
nothing and drifted **south at a steady 2.8"/min** (10" every 40 looks, to
-50" after 18 minutes). The main camera sees it too: a star moved 3-4 px
between 120 s frames, the same way every time
([ic405-guided-frames.jsonl](dec-records/ic405-guided-frames.jsonl)).

That steady drift with Dec not pulsed is not the gears: it is the polar
axis, which drifts Dec at about 0.26"/min for each arcminute it is out, so
about 10' out. The tripod and tube were handled fitting the hot water
bottle and dew shield; the 17:41 polar alignment had it 0.2° (12') out.

The frames are still good at 120 s: 5 kept, FWHM 5.9-6.1 px, roundness
0.89-0.90, 300 stars each (unguided 16 s frames earlier: 4.2-4.8 px,
0.79-0.90, 107-124 stars). 300 s is off: about 10" of Dec drift a frame.

## The test that would settle it

At one pointing, clutch untouched: four north/south cycles of 80 steps,
the star measured after every step (about 12 minutes,
`./guidecam.py dectest --steps 80`, run four times). Then:

- **the slack repeats** (within a few steps): raise the calibration's limit
  above it and guide Dec one way for real; measure Dec's RMS in a guided
  run.
- **it wanders**: that is the worm's mesh, for Gary with these logs; the
  nights stay RA-only at 120 s with the polar axis kept close.

Not yet run: the owner asked for this write-up first.
