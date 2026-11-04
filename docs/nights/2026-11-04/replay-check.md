# The replay engine checked against the night of 3 to 4 November 2026

Phase 5 of docs/observing-plan-spec.md. Everything here can be run again:

- `./history.py`: the costs (history.txt beside this file);
- `./nightreplay.py 2026-11-03 --check`: the check;
- `./nightreplay.py 2026-11-03`: the comparison;
- `--stress`: the stress nights (all three in replay.txt beside this file).

The figures down to "Limits the audit should weigh" are the first build's,
as the deep audit saw them. The engine was then corrected and its figures
changed: see "Correction round" at the end.

## What the check does

It replays the night under the policy the code had then ("as-run": 5-minute
panels, no budget, second looks after). Each visit starts where the record
says it started, so the check tests the visit's model, not timing drift:

- cadence;
- stalls;
- cloud;
- the quality pass;
- depth.

It then sets each session against what was recorded, over 50 runs.

## Result (50 runs)

| Measure | Median error over the night's 14 sessions |
|---|---|
| Frames captured | 6% |
| Frames accepted | 6% |
| Frames stacked | 8% |
| Depth (G) | 0.1 mag (worst 0.45) |
| Searchable verdict, as recorded | 75% of runs |

Where the replay disagrees, and why:

- **M31-P4 04:05:** recorded *not searchable* because its subtraction did
  not match the reference. The engine does not model subtraction quality,
  so it calls the visit searchable. Known limit.
- **M31-P3 03:30 and M31-P5 03:44:** 6 and 7 stacked frames against the
  8 the search needs. The replay stacks about one more, so it falls either
  side of the line.
- **M31-P8 04:43:** stopped by hand (`schedule.py next`) after 26 frames.
  The record says why, but the engine doesn't know it, so it takes the
  visit to its end. Not fitted to.
- **M33 01:17:** about 6% more frames than recorded. Some stalls start
  between two replayed frames and are missed.

What it took to get here, each fix found by the check itself:

- **Depth calibration.** The depth model is pooled over many nights, and
  this night's stacks sit 0.6 to 0.9 mag deeper than it. Depth is now
  calibrated by the night's own measured stacks, each left out of its own
  calibration, so the replay never reads back its own answer.
- **Thin cloud.** It dims stars without widening them or brightening the
  sky, so the model alone cannot see it. Each frame's star light, as a
  share of that field's clear-sky light, now carries it into both depth
  and the quality pass. Panel 1's cloudy second stack went from 1.1 mag
  too deep to within 0.05.
- **The quality pass.** It is modelled as restack does it: below 0.6 of
  the better half's light is cloud, then the best 85%. An accepted frame
  borrows only accepted frames' light. NGC 3310's 30 stacked of 55 is
  reproduced.

## What it found in the code

`./shoot.py NGC 3310 --minutes 90` with no `--frames` took the default
60 frames (75 with retakes). Started on time, the supernova would have
stopped after about half an hour of its 90, with the rest idle. Fixed:
`--minutes` alone now means as many frames as the minutes allow
(`shoot.frames_asked`, with its test).

## The comparison (50 runs; median, 10-90% in replay.txt)

| | as run 3 Nov | current code |
|---|---|---|
| Panel visits worth having (fields) | 7 | 5 |
| Searchable visits | 9 | 6 |
| Accepted minutes, whole night | 118 | 118 |
| Second looks | 3 | 0 (1 put off, owed) |
| M31 panels step, planned 45 min | 114 min | 37 min |
| Supernova, planned 90 min | 14 min | 92 min |
| Deadlines passed | 0 | 0 |

The night's plan gave eight panels 45 minutes. At their measured cost
(`patrol.visit_minutes`: 8 minutes, a quarter for stalls, 2.5 for the
GoTo) that holds three. The code as it ran took eight by taking the
supernova's time; the current code keeps the plan's time and leaves the
rest of the panels owed. The planner now sizes steps with the same cost,
so a plan made today would give the panels more time or fewer panels.
This replay keeps the night's own plan, so it does not show that.

## Limits the audit should weigh

- **One night.** Plans are kept for replay only from this night on
  (`cache/schedules/`), so no other night can be checked yet. Each night
  from now on adds one.
- **Direction is not modelled.** A field at a time the telescope wasn't on
  it borrows the cloud and transparency of frames taken nearest that time,
  wherever they pointed. Low altitude, the house to the west (M31-P8 at
  31° faded) and the Moon are not in it. Each visit's `recorded_share`
  says how much of its sky came from that same field within 5 minutes.
- **Stalls inside the night's span are the record's own gaps between
  frames (inferred).** The camera's recorded retries (`TY_RETRY`) begin
  with the next night.
- **Second looks follow the record.** A field gets one only if its search
  found something unexplained that night. Fields never searched are
  assumed to have found nothing.
- **Subtraction quality and the reference are not modelled** (see M31-P4).
- **Moves** come from the night's own (inferred: GoTo, plate solves and
  camera start), or `history.py`'s across nights, which include hand-run
  nights (median 4 min, 90% under 11).

## Correction round (after the deep audit, 4 November 2026)

The audit asked for six corrections. Each is below with what changed and
what it did to the figures. Outputs: `replay-check-corrected.txt` (the
check) and `replay-corrected.txt` (the comparison, protected starts and
stress nights) beside this file, 50 runs each (20 for stress).

### 1. One set of rules for the night and its replay

The current policy no longer has its own copy of the scheduler. The
runner, the patrol and shoot.py now make their choices through plain
functions of the clock, and the replay calls those same functions:

- `schedule.prepared`: how a step is started and told its time (budget,
  `--minutes`, the backstop, skipping);
- `patrol.fit`, `field_minutes`, `room`, `shoot_minutes`, `frames_for`,
  `second_look_frames`, `second_look_put_off`: which panels, how long, and
  whether a second look goes now;
- `shoot.frames_asked`, `shoot.stop_for`: when a capture ends.

A test spies on each and fails if the replay stops calling it, and changes
`patrol.STALL_SHARE` to show the replay changes with the code.

The as-run policy can't share code that no longer runs. It is a labelled
reconstruction (`AsRun`, "reconstructed: no running code behind it"),
reading its programmes from the commit that ran that night (`f9b763a`).

Building the reconstruction found three of the replay's own mistakes, now
fixed:

- a field patrol lets the telescope go once its frames are in, so its
  second look is a step of its own, not taken at once;
- panels are ordered as that step took them, not from the whole night;
- second looks follow the visit's own search, not any search of that field
  that night.

### 2. Chronological calibration

- **Costs** come from the nights before the replayed one only
  (`history.costs(before=...)`), the depth model included: 13 nights for 3
  November.
- **Depth** is calibrated only by that night's stacks measured before the
  moment it is decided (a stack's depth counts as known 10 minutes after its
  last frame). `--calibration leave-one-out` keeps the old way for
  comparison.

| Depth error, the acquisition check | Median | Worst |
|---|---|---|
| Leave-one-out (the first build) | 0.11 mag | 0.50 |
| Chronological (now the default) | 0.31 mag | 1.06 |

The audit was right: the leak made the depth look three times better than
a forecast the telescope could make. The worst is the night's first stack,
with nothing measured before it.

Independent validation needs nights the engine wasn't built on. 3 November
is the only night with a kept plan, and the engine was tuned against it, so
the check says so ("not an independent test"). Each night from 4 November
adds one held-out night.

### 3. Search failure is its own outcome

Each visit's search ends as `searched`, `subtraction`, `no reference`,
`unsolved`, `too few frames` or `too shallow`, and says whether that was
recorded or modelled.

- **Recorded:** a visit the record has keeps the record's answer. M31-P4 at
  04:05 is now `subtraction` and not searchable, as recorded, where the
  first build called it searchable.
- **Modelled:** a visit the record has no answer for fails its subtraction
  at the rate earlier nights' searches did. That rate is drawn afresh in
  each run from the counts (10 failed of 33 before 3 November), so its
  uncertainty is in the spread. A field never imaged before has no
  reference.
- `searches_modelled_share` says how much of a policy's search outcomes
  were modelled.
- **Not modelled, and said in every replay:** a supernova's photometry, and
  what a search would discover.

### 4. Measures corrected

- **Accepted integration** uses each visit's own exposure.
- **Time** is split by what it went on: accepted frames, rejected frames,
  between frames, stalls, moves, waiting for a timed step, steps not
  modelled, and unused.
- **The deadline measure** is now two:
  - `ends_overrun`: a step past its end time by more than a minute;
  - `ends_past_backstop`: past even the hard stop, which must be 0.

### 5. Protected windows judged by the first frame

`--protect HH:MM` puts a step the person times into the plan, after the
step running at that time. `protected_starts_missed` counts its first
frame coming more than a minute late, after its GoTo and setup.

| Protected at | as-run 3 Nov | current code |
|---|---|---|
| 02:00, inside the 85-minute M33 step | missed, 41 min late | missed, 31 min late |
| 04:30, after the panels | missed, 20 min late | missed, 100 s late |

The current runner protects nothing yet, which is Phase 3's job:

- a step that is running when a timed step falls due runs on;
- a step that waits for its time starts its GoTo at that time, so its
  first frame is a GoTo late.

The replay now measures this. The first build's "0 deadlines missed" could
not see it.

### 6. Acquisition and the whole night checked apart

The check now has two parts:

1. **Acquisition:** each visit starts where the record started it.
2. **The whole night:** the as-run rules from the night's start, with no
   anchoring: which visits, in what order, and each step's start and
   length against the plan's record.

| Acquisition (chronological) | |
|---|---|
| Captured | within 1% (median) |
| Accepted | within 9% |
| Stacked | within 8% |
| Depth | 0.31 mag (worst 1.06) |
| Searchable verdict as recorded | 84% of runs |

| The whole night | |
|---|---|
| Step starts | within 0.6 min of the record (median) |
| Step lengths | within 0.7 min |
| Visits | 13.5 replayed, 14 recorded; the first 13 in the recorded order |
| Panels step | 92 min against 99 recorded. P8's second look was stopped by hand, which the replay doesn't know |

### The comparison now (50 runs, median)

| | as-run 3 Nov | current code |
|---|---|---|
| Fields worth having | 6 | 4 |
| Searchable visits | 8 | 5 |
| Accepted minutes | 115 | 111 |
| Second looks | 1.5 | 0 |
| M31 panels step, planned 45 min | 92 min | 36 min |
| Supernova, until 05:25 | 26.5 min | 70 min |
| Unused | 5 min | 33 min |

This still doesn't show which policy is better for science: the supernova's
photometry isn't modelled.

It does show a new cost of the current code. With only `--minutes`, the
supernova's run stops for good after 20 rejected frames in a row
(`shoot.stop_for`, `shoot.cloud_stop`). Under the current code the panels
finish early, so the supernova starts about 03:45 and meets the cloud
recorded around 04:45. In most runs it stops there at about 04:49 and
leaves the rest of its time unused, though the record shows the sky clear
again by 04:57.

Whether a step that has an end time should pause through cloud instead
(`--through-cloud`) is the person's decision. It isn't changed here.

### Also found

A shoot step told its end time is late by its own GoTo. `schedule.prepared`
gives shoot.py the minutes left when the step starts, but shoot.py starts
its clock after its own GoTo. The backstop ends it within 4 minutes. Phase
3's setup reserved before a window is the fix; it isn't changed here.
