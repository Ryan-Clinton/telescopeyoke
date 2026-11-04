# Spec: planning a night by what it gets, not by its clock

Status: proposed, 4 November 2026. Nothing here is built yet; the phases
below say what each one changes and how it is proven before it is used.

## Why

On the night of 3 to 4 November 2026 the plan was a fixed list of steps,
each given a number of minutes:

- Five-minute M31 panels lost 2.4 to 3.0 minutes each to camera stalls.
  Panels 3, 5 and 6 came out with 6 or 7 stacked frames, under the 8 the
  search needs, and were never searched. M33 lost 17.7 of its 77 minutes.
- The panels' step had 45 minutes and ran 99, with second looks at weak
  candidates. The supernova after it, the one time-limited target, got 27
  of its 90 minutes.
- Every step "finished" when its timer ran out, whatever it had got.

The person's rule: more frames than needed beats too few (4 Nov 2026), and
"as many good frames as it can, rather than making do with fewer" (18 Oct
2026, `shoot.retakes`). Since that night the plan counts the real cost of
a visit, including stalls, keeps each patrol to its step's time and makes
up stalled frames within it (docs/flexible-plans.md). That fixes the
symptoms. This spec is the design underneath: plan by what each
observation needs and gets.

## What the best observatories and tools do

**Pick the next observation as the night goes, from what is true now.**
Most robotic telescopes use a dispatch scheduler. It doesn't fix the
night's order in advance; at each decision it takes the best observation
for now. Examples: the Liverpool Telescope ("a simple despatch scheduler
which is run on demand"), RoboNet-II, NINA's Target Scheduler (asks its
planner again after every exposure), and Ekos's greedy scheduler. The
reason given is that a plan made in advance breaks when weather or kit
changes. ZTF instead solves the whole night as an integer program in
30-minute blocks. That gained 9% on its measure, and completed 81% of
requested sequences against greedy's 64-79%, but over hundreds of fields
a night. With one telescope and a handful of targets, dispatch with a
look ahead at what sets soonest gets most of that.

**Value an observation in science terms, not minutes.**
ZTF weights each exposure by the volume of space it probes,
10^(0.6 (m_lim - 21)). Seeing, airmass, sky and filter all act through
the depth reached. NINA's Target Scheduler scores targets by priority,
percent complete, how soon each sets, and a penalty for switching.

**Count completion in accepted frames, not time.**
Target Scheduler keeps an exposure plan going until its accepted images
reach the number desired. Images are graded against the ones just before
on HFR, star count and guiding. A rejected image doesn't count, and nothing
is deleted.

**Stay on a target long enough.**
Target Scheduler has a "Minimum Time" per project and a target switch
penalty (default weight 67%), so it doesn't spend the night slewing.

**Protect what has a window.**
LCO gives each request windows it must fit inside entirely, and maximises
the total priority scheduled. ZTF runs time-critical programmes as queues
that interrupt the main scheduler. Rubin has a target-of-opportunity system
alongside its survey scheduler.

**Recover faults in the device layer, and keep going degraded.**
The ANU 2.3 m conversion found auto-recovery worked best inside the
telescope's control layer, which tells the layers above it is busy
recovering. The Liverpool Telescope's goal is to keep operating, degraded
if need be, when a subsystem fails.

**Prove a policy by simulating nights.**
ZTF's scheduler is the same code in simulation (with historical weather)
and on the sky. Policies are compared on simulated nights before use, and
Rubin's survey strategy is tuned the same way.

## What telescopeyoke has now (4 November 2026)

| Piece | Today | Gap against the above |
|---|---|---|
| `agent.recommend` | Builds the plan greedily: watch windows, second looks, research leads, then programmes in order of best time. Each costs `patrol.visit_minutes`. | Builds the plan once, from minutes. |
| `schedule.py run` | Runs the list in order. `--until` steps and patrol budgets end on time, `fill` fills a lost step's gap, and `due()` makes second looks give way. | A fixed list, and a step is done when its time is up. Time a step doesn't use is not given to anything. |
| `patrol.priorities` | Scores panels by novae reported × share caught at the expected depth × days unwatched ÷ minutes. Fields owed a second look go first. | Already a science value, but only within one mosaic. |
| `shoot.py` | Ends at `--frames` captured or `--minutes`. `retakes()` adds up to a quarter more frames for rejected ones, and none after 3 rejected in a row. | Stops on frames *captured*, not *accepted*. A stall (time, no frame) and a rejection (a frame, no use) share one cap. |
| `restack` / `depth` / `vet` | Measure stacked frames, integration, the depth where half of planted stars are found, and candidates. | Measured after the night, and never fed back to the plan. |
| `altair.py` | Retries a frame that doesn't come; reopens the camera; cuts its power at the hub when allowed. | Recovery time and success are not counted, and the plan doesn't know the camera is recovering. |
| Simulation | `--demo`, the mount simulator, and unit tests with a fake clock. | No whole-night replay to compare plans. |

## The design

Each phase is useful alone and is proven before the next.

### Phase 1: say what each observation got

Every step's result is the six numbers the person asked for:

1. frames requested
2. captured
3. accepted
4. stacked
5. integration in seconds
6. depth reached (G, half of planted stars found)

Its outcome is then *short*, *met* or *more than asked*, against the
programme's need (Phase 2).

- These go into the run's record, the schedule's line for the step, the
  night notes and the morning summary.
- Built on what `restack.json` and `depth.json` already hold.
- Proof: the 3-4 Nov night is replayed from its records, and the result
  says panels 3, 5 and 6 were short and why.

### Phase 2: goals in accepted frames, not minutes

Each programme (`programmes/*.toml`) and planned target gets three goals:

- `minimum`: the least worth having. For a patrol panel, the 8 stacked
  frames the search needs.
- `desired`: the result aimed for, such as a depth or a frame count.
- `stretch`: more, if time is spare.

Each is in accepted frames or a depth, with minutes as a cap only.

- **The capture keeps going until `desired` accepted frames, or its cap.**
  A stall extends the time, up to the cap; a rejection extends the frame
  count. The two are counted apart. `retakes()` and the patrol's
  `SHOOT_CAP` merge into this one rule.
- **Planned and worst case are kept apart.** The plan books the expected
  cost (measured, Phase 5). The runner allows up to the worst case only
  out of time that nothing protected needs.
- **Proof:** a replay of 4 Nov's frame logs (stalls and rejections as they
  happened) shows each panel reaching its minimum. Then one real night.

### Phase 3: protected windows

A step that only works at certain times, such as a transit with its
baseline, an occultation or a supernova before it sets, is marked
`protected`, with its window.

- The runner works out every flexible step's time backwards from the next
  protected start, so a flexible step can never take it. This generalises
  today's `--until` and `--budget`.
- A protected step may still be cut by cloud, never by another step.
- **Proof:** a simulated night where the step before it overruns, stalls
  and takes second looks. The protected step starts on time every time.

### Phase 4: choose the next step at each step's end

After each step the runner asks the planner again what is best now. It
uses what is still owed:

- a target short of its minimum keeps its need;
- a field owed a second look goes first;
- spare time goes to the best `stretch`.

The fixed list becomes the plan's first guess, still shown on the console
and still changeable by the person.

- Kept from today: the person's moves only. Nothing in this design moves
  the mount except through the steps the person agreed to tonight.
- A minimum stay on a target (as Target Scheduler does) stops it hopping.
- **Proof:** Phase 5's replays, against the fixed list.

### Phase 5: costs from history, and whole-night replays

- **Costs** are measured from every night's logs, as medians and 90th
  percentiles, never from one night:
  - GoTo and solve time;
  - time between frames;
  - stalls an hour and their length;
  - rejection rates by cause;
  - stacked share.

  `patrol.visit_minutes` then takes them from that record, not from
  constants.
- **A night replay** runs the planner and the runner against a clock, with
  the stalls, rejections, GoTo times and cloud from recorded nights. It
  reports:
  - protected starts missed;
  - targets that reached their minimum, desired or stretch goal;
  - accepted integration;
  - time idle.

  It runs the current policy and the proposed one on the same nights. A
  change is kept only if it does better without missing a protected start.
- Ordinary nights, degraded ones (stalls like 1 Nov, patchy cloud like
  3 Nov) and exceptional ones (fog, 2 Nov) are reported apart.

### Camera recovery, measured

From the logs:

- how many stalls a night;
- how long each recovery took;
- how many recovered by retry, by reopening, or not at all.

`docs/camera-fault.md` holds the fault itself. The plan budgets for what
recovery costs. If recovery can be made quicker (the device layer saying
"recovering" so the run doesn't count it as lost time, or a shorter first
wait), that is cheaper than budgeting more time for it. Measured first.

## Not proposed

- **A whole-night optimiser (ILP).** With one telescope and a few targets,
  dispatch with look-ahead is what the comparable tools use, and ZTF's
  gain came from hundreds of fields.
- **A second planner.** `agent.recommend`, `schedule.py` and
  `patrol.priorities` are extended, not replaced.
- **Silencing candidates at known places.** See
  docs/nights/2026-11-04/p8-false-candidates.md.

## Decisions for the person

1. Each programme's `minimum` and `desired` goals. Proposed:
   - M31 panel: 8 stacked frames minimum, 24 desired.
   - M33 and M31 novae: depth G 17.5 desired.
   - A supernova: 30 minutes accepted desired.
2. Which kinds of step are protected. Proposed: exoplanet transits with
   their baseline, occultations, supernovae and comets near setting, and
   any step the person says is.
3. The order of the phases. Proposed: 1, 5 (costs and replays), 2, 3, 4,
   so every later change is judged on replays.

## Sources

- Liverpool Telescope robotic control and dispatch scheduler: https://telescope.astro.ljmu.ac.uk/TelInst/Robotic
- RoboNet-II: https://arxiv.org/pdf/0808.0813
- NINA Target Scheduler, concepts and planning engine: https://tcpalmer.github.io/nina-scheduler/concepts and https://tcpalmer.github.io/nina-scheduler/target-management/exposure-plans.html
- Ekos Scheduler: https://kstars-docs.kde.org/en/user_manual/ekos-scheduler.html
- ZTF surveys and scheduler (Bellm et al. 2019): https://arxiv.org/abs/1905.02209
- LCO network scheduler as an integer program (Lampoudi et al. 2015): https://arxiv.org/abs/1503.07170
- Rubin feature-based scheduler: https://rubin-scheduler.lsst.io/fbs.html
- ANU 2.3 m automation: https://arxiv.org/pdf/2409.19842
