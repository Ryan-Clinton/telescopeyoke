# Phases 2, 3 and 4 replayed on the night of 3 to 4 November 2026

Built 4 November 2026 (docs/observing-plan-spec.md), on the replay engine as
corrected after its deep audit (replay-check.md, "Correction round"), then
corrected again after their own review the same afternoon (below, "After
review"). Each phase is switched on by `[plan]` in config.toml (`goals`,
`windows`, `dispatch`) and is off until the person turns it on; off, the
plan runs as before. Nothing here has run on the sky: these are replays,
and the spec's proof for each phase asks for one real night after them.

| Phase | State |
|---|---|
| 2, goals | Modestly better in replay; for a controlled live night |
| 3, protected windows | Kept every timed start in replay; for a controlled live night |
| 4, dispatch | Held: the planner's skyline at ralphie-side rules out targets the record shows were imaged (below) |

Each policy calls the running code's own functions: `goals` stops a
patrol's capture by `shoot.goal_stop` (what `shoot.py --accepted` stops
by) with the rule from `goals.capture_rule`; `windows` chooses steps by
`windows.choose` and tells a flexible step its cutoff through
`schedule.prepared`; `dispatch` ranks by `dispatch.choose` with the
measured skyline (`dispatch.Sky`) and weighs second looks through
`patrol.second_look_put_off` and `obligations.allowance_left`. Costs come
from the 13 nights before 3 November, and depth is calibrated only by
stacks measured before it. Medians of 50 runs (30 for the stress nights);
every output, with its spread, is in replay-phases.txt. Each policy builds
on the one before.

## The ordinary night

| Measure | current | goals | windows | dispatch |
|---|---|---|---|---|
| Visits searchable | 5 | 6 | 6 | **3** |
| Fields worth it | 4 | 5 | 5 | **2** |
| Desired goal met | 1 | 2 | 2 | 1 |
| Accepted minutes | 110.9 | 113.9 | 113.9 | 114.7 |
| Steps left queued, target not up | 0 | 0 | 0 | 1 |

- **Phase 2 (goals) is no worse on any measure and one better on three**,
  inside the spreads' overlap: a modest gain, not a proven one.
- **Phase 3 (windows) changes nothing** on a night with no timed step.
- **Phase 4 (dispatch) loses the M31 panels.** It now only starts a step
  whose target is above the planner's skyline, and from about 03:05 that
  skyline has M31 down, so the panels are left queued. The record shows
  them imaged and kept then (next section). Dispatch is doing what the
  skyline tells it; the skyline is what is wrong.

## The skyline against the night's frames

`./skylinecheck.py 2026-11-03` puts every frame under the planner's limit
it fell below. At ralphie-side (the spot in config.toml) the measured
skyline rises from 27 degrees at bearing 285 to 69 at 292 and 72 at 300.
The M31 panels from 03:15 to 04:43 sat 29 to 40 degrees up at bearings
287 to 302: under that skyline by 25 to 40 degrees, and partly under the
blocked direction 274-294 up to 47 degrees in config.toml.

| Limit the frames were under | Frames | Kept |
|---|---|---|
| Clear of every limit | 286 | 251 |
| Inside the skyline's 2-degree margin | 0 | 0 |
| At or below the measured skyline | 94 | 47 |
| A blocked direction (config.toml) | 150 | 130 |

Some of those sessions kept every frame (M31-P1 at 03:37, 16 of 16, under
a skyline of 61 to 66 degrees; M31-P4 at 04:05, 16 of 16, under 70). So
the measured skyline is too high between bearings 287 and 302: it is not
its 2-degree margin that rules M31 out, and not a quality judgement. Why
it is too high there is not established: it may be the house corner
measured from another position, or the tracing's own pointing. The skyline
and the blocked list are the person's to correct (`horizon.py`, which asks
for what was seen); nothing here changes them.

## A step the person times (`--protect`)

The engine's own `--protect HH:MM` puts a 20-minute timed step in the plan
after the step the record had running then, judged by its first frame
after the GoTo. Runs in which it was more than a minute late, of 50:

| Time | current | goals | windows | dispatch |
|---|---|---|---|---|
| 02:30 | 44 (worst 346 s) | 50 (484 s) | **0** | **0** |
| 03:40, inside the panels | 50 (412 s) | 50 (1064 s) | **0** | **0** |
| 04:30 | 49 (343 s) | 47 (343 s) | **0** | **0** |

- With windows the timed step was taking frames at its start in every run.
- Found by the replay and fixed: the first build missed at 03:40 in 7 of
  50 runs, up to 209 s late, because a flexible step told the cutoff was
  given the runner's 4-minute backstop after it. Before a protected start a
  step is now told to end `BACKSTOP_S` early, so its hard stop falls on the
  cutoff (`schedule.prepared`), and a flexible step needs 10 minutes before
  a window to start at all (`windows.MIN_FLEXIBLE_S`).
- Goals without windows makes timed steps later (to 1064 s at 03:40):
  captures that run to their goal push everything after them. Goals should
  not be on without windows on a night with a timed step.
- What windows costs: at 03:40 and 04:30 one or two searchable visits
  against goals alone, for the setup reserved before the window and the
  flexible steps cut back to the cutoff.
- This is one recorded night with modelled moves, solves and focus checks:
  the real mount's timing is for a controlled live night.

## The stress nights

| Stress | Searchable (current / goals / windows / dispatch) | Minutes unused |
|---|---|---|
| camera-dead | 3 / 3 / 3 / 3 | 0 / 0 / 0 / 0 |
| flicker | 5 / 5 / 5 / 3 | 38 / 38 / 38 / 38 |
| no-frames | 0 / 0 / 0 / 0 | 100 / 86 / 86 / 125 |
| depth-wrong | 3 / 3 / 3 / 1 | 0 / 0 / 0 / 34 |

Every policy ended every stress night safely: no step past its backstop,
no timed step missed. With no usable frames goals now waits the cloud out
to each capture's time cap (86 minutes unused against today's 100);
dispatch's fewer visits are the panels left queued, as above.

## After review (4 November 2026)

- **Dispatch never starts a target it has judged down.** With nothing up
  it waits until the first queued target rises, or a protected step's
  setup is due; with nothing rising before dawn it says so and leaves the
  steps queued (`dispatch.choose`, `Sky.rises_in`). A protected step is
  started at its time whatever dispatch thinks; the mount's own limits
  still refuse a target below them.
- **Accepted is not stacked.** A frame the live stack had no time to
  measure counts toward the capture's goal only at the run's measured
  acceptance rate. The goal is judged on stacked frames (`outcome.judge`):
  29 accepted that the quality pass cuts to 18 is short of the 24 desired,
  and said so (tested). `capture.json` keeps accepted, unmeasured,
  rejected and cloud apart.
- **Cloud is waited out.** A frame lost to cloud costs time, not one of the
  frames the rejections may take, and cloud alone never ends a capture
  with time left; the time cap then lets the telescope go. Other
  rejections (trailed, soft) still end it after 20 in a row, or 3 once the
  desired count is taken.
- **A candidate seen again stays owed.** Level 3 is a follow-up of its own
  kind (its brightness with an error and its last non-detection, then the
  person vets it), counted from its latest night, not closed.

## Not settled

- The skyline between bearings 287 and 302 at ralphie-side (above).
- The goals gain on the ordinary night is one visit, inside the spreads.
- The real-or-bogus score has no uncertainty recorded yet (`weigh` says
  so); the replay can't tell a strong candidate from a weak one, so every
  second look counts as uncertain there, and what is owed is the plan's
  own second-look steps. The thresholds (`RB_STRONG`, `LOCAL_STRONG`,
  `SETTLE_MARGIN`) are provisional.
- The focus check before a protected window is taken as 2 minutes until
  focus checks are timed.
- One night only, and the night the engine was tuned on (not independent).
