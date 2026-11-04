# Phases 2, 3 and 4 replayed on the night of 3 to 4 November 2026

Built 4 November 2026 (docs/observing-plan-spec.md), on the replay engine as
corrected after its deep audit (replay-check.md, "Correction round"). Each
phase is switched on by `[plan]` in config.toml (`goals`, `windows`,
`dispatch`) and is off until the person turns it on; off, the plan runs as
before. Nothing here has run on the sky: these are replays, and the spec's
proof for each phase asks for one real night after them.

Each policy calls the running code's own functions, as the corrected engine
requires: `goals` stops a patrol's capture by `shoot.goal_stop` (what
`shoot.py --accepted` stops by) with the rule from `goals.capture_rule`;
`windows` chooses steps by `windows.choose` and tells a flexible step its
cutoff through `schedule.prepared`; `dispatch` ranks by `dispatch.choose`
with the measured skyline (`dispatch.Sky`) and weighs second looks through
`patrol.second_look_put_off` and `obligations.allowance_left`. Costs come
from the 13 nights before 3 November, and depth is calibrated only by stacks
measured before it. Medians of 50 runs (30 for the stress nights); every
spread is in replay-phases.txt. Each policy builds on the one before.

## The ordinary night

| Measure | current | goals | windows | dispatch |
|---|---|---|---|---|
| Visits searchable | 5 | 6 | 6 | **4** |
| Fields worth it | 4 | 5 | 5 | **3** |
| Desired goal met | 1 | 2 | 2 | 1 |
| Accepted minutes | 110.9 | 113.9 | 113.9 | 130.1 |
| Minutes unused | 33.2 | 32.9 | 32.9 | 0 |
| Steps run below the planner's skyline | 0 | 0 | 0 | 1 |

- **Phase 2 (goals) is no worse on any measure and better on three**
  (searchable, worth it, desired met), each by one, inside the spreads'
  overlap: a modest gain, not a proven one.
- **Phase 3 (windows) changes nothing** on a night with no timed step.
- **Phase 4 (dispatch) fills the night (no unused time, 19% more accepted
  minutes) but searches fewer fields.** Read from its own ranking: the
  planner's skyline with its margin puts M31 below the limit from about
  03:05, so it held the panels back; they ran last, below that limit, and
  lost searchable visits. The record has the panels imaged 03:07 to 03:52
  with frames kept, so the sky model is stricter than what the telescope
  managed. The margin is the person's setting and was not loosened. A trade
  for the person, not a pass.

## A step the person times (`--protect`)

The engine's own `--protect HH:MM` puts a 20-minute timed step in the plan
after the step the record had running then, judged by its first frame
after the GoTo. Runs in which it was more than a minute late, of 50:

| Time | current | goals | windows | dispatch |
|---|---|---|---|---|
| 02:30 | 44 (worst 346 s) | 50 (484 s) | **0** | **0** |
| 03:40, inside the panels | 50 (412 s) | 50 (1064 s) | **0** | **0** |
| 04:30 | 49 (343 s) | 47 (343 s) | **0** | **0** |

- **Phase 3's proof holds:** with windows the timed step was taking frames
  at its start in every run.
- **Found by the replay and fixed:** the first build missed at 03:40 in 7
  of 50 runs, up to 209 s late. A flexible step told the cutoff was given
  the runner's usual 4-minute backstop after it, which ran into the
  window's setup. Before a protected start a step is now told to end
  `BACKSTOP_S` early, so its hard stop falls on the cutoff
  (`schedule.prepared`), and a flexible step needs 10 minutes before a
  window to start at all (`windows.MIN_FLEXIBLE_S`).
- **Goals without windows makes timed steps later** (to 1064 s at 03:40):
  captures that run to their goal push everything after them. Goals should
  not be switched on without windows on a night with a timed step.
- **What windows costs:** at 03:40 and 04:30, one or two searchable visits
  against goals alone (5 against 7, 4 against 6), for the setup reserved
  before the window (the 90th percentile of moves between targets and a
  focus check) and the flexible steps cut back to the cutoff.

## The stress nights

| Stress | Searchable (current / goals / windows / dispatch) | Accepted minutes |
|---|---|---|
| camera-dead | 3 / 3 / 3 / 3 | 68.7 / 69.6 / 69.6 / 69.5 |
| flicker | 5 / 5 / 5 / **3** | 56.0 / 55.1 / 55.1 / 64.0 |
| no-frames | 0 / 0 / 0 / 0 | 0 |
| depth-wrong | 3 / 3 / 3 / **2** | 121.9 / 123.2 / 123.2 / 130.3 |

Every policy ended every stress night safely: no step past its backstop,
no timed step missed. With no usable frames, goals ends each capture after
20 rejected in a row instead of running out the clock, so 122 minutes go
unused against current's 100.

## What changed in the code

- `goals.py`: purposes, timing and minimum, worth-it, desired and stretch
  levels per programme and planned target (`programmes/targets/`); a
  supernova's reference case (SN 2026sqf is case 3 until its discovery
  date is in its file); the one capture rule (`keep_capturing`), in place
  of `retakes()` and `SHOOT_CAP` when goals are on; a desired depth turned
  into frames by the depth model and the field's last measured stack; the
  quick depth from a frame log.
- `shoot.py --accepted N [--most N]` with `--minutes` as the time cap,
  stopped by `goal_stop`; `capture.json` says what stopped it.
- `difference.py` keeps `out_of_line_share` (where the subtraction, not
  the sky, limits the search) and each candidate's `local_score`;
  `outcome.py` counts a stack whose subtraction is out of line over
  `quality_max` (20%, provisional) as not worth it.
- `windows.py`: the four classes, setup from history, deadline steps placed
  around fixed windows, flexible steps timed back;
  `schedule.py add --protect hard|person --deadline --uncertainty`; the
  cutoff and the backstop in `schedule.prepared`.
- `obligations.py`: what is owed, why and until when, in
  `cache/obligations.json`; candidates weighed; the follow-up allowance,
  which `patrol.second_look_put_off` keeps to.
- `dispatch.py`: the next agreed step chosen at each step's end, every
  choice kept with its reasons in `cache/dispatch.jsonl`; it never adds a
  step.
- `nightreplay.py`: the goals, windows and dispatch policies; each visit's
  stop, stalls and shortfall cause; steps dispatch ran below the skyline.

## Not settled

- The skyline margin against what the record shows: dispatch should not be
  switched on until that is looked at with the person.
- The goals gain on the ordinary night is one visit, inside the spreads.
- The real-or-bogus score has no uncertainty recorded yet (`weigh` says
  so); the replay can't tell a strong candidate from a weak one, so every
  second look counts as uncertain there, and what is owed is the plan's own
  second-look steps.
- The focus check before a protected window is taken as 2 minutes until
  focus checks are timed.
- One night only, and the night the engine was tuned on (not independent).
