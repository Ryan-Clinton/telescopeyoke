# The replay engine checked against the night of 3 to 4 November 2026

Phase 5 of docs/observing-plan-spec.md. Everything here can be run again:

- `./history.py`: the costs (history.txt beside this file);
- `./nightreplay.py 2026-11-03 --check`: the check;
- `./nightreplay.py 2026-11-03`: the comparison;
- `--stress`: the stress nights (all three in replay.txt beside this file).

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
