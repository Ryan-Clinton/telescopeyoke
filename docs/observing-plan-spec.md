# Spec: planning a night by what it gets, not by its clock

Status: decisions approved 4 November 2026. Phase 1 built (`outcome.py`)
and audited. Phase 5 built (`history.py`, `nightreplay.py`), checked against
the night of 3 to 4 November (docs/nights/2026-11-04/replay-check.md), deep
audited (changes required), corrected (the same file, "Correction round").
At the person's word the re-audit was not waited for: Phases 2, 3 and 4
were built on 4 November on the corrected engine (`goals.py`,
`windows.py`, `obligations.py`, `dispatch.py`), each off until switched on
in `[plan]`, and replayed on the same night
(docs/nights/2026-11-04/phases-2-4-replay.md), then reviewed and
corrected. None has run on the sky. Phases 2 and 3 are for one controlled
live night, with their outcome logs and the runner's choices kept; Phase 4
is held until the measured skyline at ralphie-side is corrected between
bearings 287 and 302, where the night's kept frames show it too high
(`./skylinecheck.py 2026-11-03`).
The order of work and its checkpoints: Phase 1,
audit; Phase 5, a deep audit of the replay engine (a flawed one would
make every later change look better than it is); Phases 2, 3 and 4,
with major design changes or unexpected failures reported; then a full
audit across simulated nights.
The phases below say what each one changes and how it is proven before it
is used. Until a phase is proven, today's planning and acquisition stay as
they are. Each phase is switched on by a setting (`[plan] goals`,
`windows`, `dispatch` in config.toml, all off by default) and can be
switched off again.

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
Professional systems use several approaches: dispatch, rolling-horizon
optimisation, fixed windows, and mixtures of these. Which suits depends on
the science. A dispatch scheduler doesn't fix the night's order in
advance; at each decision it takes the best observation for now. Examples: the Liverpool Telescope ("a simple despatch scheduler
which is run on demand"), RoboNet-II, NINA's Target Scheduler (asks its
planner again after every exposure), and Ekos's greedy scheduler. The
reason given is that a plan made in advance breaks when weather or kit
changes. ZTF instead solves the whole night as an integer program in
30-minute blocks. In Bellm et al.'s simulation of ZTF's May 2018
programmes, that gave 9% more of its volume measure than its own greedy
scheduler, and completed 81% of requested sequences against greedy's
64-79%. That is a comparison for hundreds of fields a night, and it does
not carry over as a number. For one telescope and a handful of targets,
this spec takes dispatch with a look ahead at what sets soonest, mixed
with fixed windows (Phase 3).

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

**Find discoveries by measuring the whole search, not the pictures.**
A transient survey judges itself by what it finds and how reliably, not
by integration:

- ZTF's pipeline keeps, with every detection, its subtraction, its
  significance, measurements of its shape, its history at that place and
  a real-or-bogus score, with cut-outs of the images.
- GOTO's classifier (Killestein et al. 2021) gives each candidate a
  calibrated probability with its uncertainty. It is trained without hand
  labels, from injected sources, and the uncertainty is used to order
  human vetting.
- Proper image subtraction (Zackay, Ofek and Gal-Yam 2016, which
  `difference.zogy` implements) warns that registration errors, PSF
  mismatch and correlated noise make a score untrustworthy where they
  dominate. M31-P8 shows this: its candidates sit where the score's local
  spread is 1.3 to 1.9 times what the model assumes
  (docs/nights/2026-11-04/p8-false-candidates.md).

So a deeper picture is not more sensitive if its subtraction is the
limit.

**Measure a transient against its host without its own light.**
Supernova surveys (the Supernova Legacy Survey among them) take the
galaxy's light away with a picture of the host made before the explosion
or long after it fades. A reference made while the supernova shines takes
the supernova's own light away with it.

**Give each kind of science its timing.**
- Moving objects are found by linking detections across visits and nights;
  Rubin's Solar System strategy is built on revisits.
- An exoplanet transit needs unbroken cadence through ingress and egress
  and an out-of-transit baseline before and after: the BAA asks for at
  least 30 minutes, ideally 60. Frames taken after a missed ingress
  cannot replace it.

**Treat automatic grading as provisional, and never delete.**
NINA's Image Grader documentation says "automatic image grading is
inherently problematic". Good early frames can make later acceptable ones
look bad, which is why its grading can be delayed. Rejected frames are
kept. telescopeyoke already keeps every raw frame, rejected or not.

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

## What the plan is for: discovery yield

The aim is discoveries that survive scrutiny, not the number of
candidates found or frames taken. The night is judged by what it could
find and how reliably, not by integration. For each programme the plan keeps, and Phase 5 reports:

| Measure | The question it answers | From |
|---|---|---|
| Depth | How faint the picture reaches | `depth.py` (planted stars, G) |
| Recovery completeness | What share of planted transients of each brightness the whole search finds, by place in the field | `difference.py --plant`, `depth.py` |
| Local significance | Whether a candidate stands out against the noise where it is, not only against the picture's average | the local spread of the score (docs/nights/2026-11-04/p8-false-candidates.md) |
| Difference-image quality | Where the subtraction itself limits the search: the share of the field whose local spread or residual level is out of line | the same, as a map and a share |
| False-candidate cost | How many candidates, second looks and minutes went to things that were not real | `candidates/*.json` dismissals, second looks |
| Coverage and cadence | Which fields, or what share of a programme's area, were last *searched to a useful depth* (worth it, Phase 1), and how often: G 17.5 every two nights is a different survey from G 17.5 every ten | `patrol.json` and `depth.json` per field; today's `last_watched` counts any imaging, and is replaced by this |
| Follow-up in time | Whether each candidate got its second look while it still counted | the obligations (Phase 4) |

Another 20 minutes on a field is worth what it adds to these. That might
be depth where the subtraction is clean, or nothing where it is not. An
hour on a well-covered field can be worth less than 20 minutes on a
neglected one with a candidate waiting.

## Evidence standard

What a thing is called follows its evidence, in reports, the night notes,
Telegram, the stream and the website. Each level needs all of the one
before:

| Level | Called | Needs |
|---|---|---|
| 1 | a detection | A difference peak above the threshold, with its record: time, frames, reference version, place, significance against the picture and against its own surroundings, real-or-bogus score with its uncertainty, and cut-outs. |
| 2 | a candidate worth a look | Nothing known explains it: no asteroid, variable, catalogued star change or earlier report (each check said as done, failed or not reachable). Present in both halves of the night. Not in a patch where the subtraction is known to be the limit, unless it stands out against its own surroundings. |
| 3 | a confirmed transient | Seen again at the same place on another night (a forced measurement of 3 sigma does not count as seen), by the same measure. Its brightness is measured with an error, and its last non-detection is known. |
| 4 | a reportable discovery | Level 3, and no report on the Transient Name Server at that place. The packet (`report.py`) has nothing left on its "Before sending" list. The person decides and sends it (docs/agents/claiming.md). |

The scientific agent never calls anything by a higher level than its
record supports, and says which checks could not be made, such as a
catalogue that didn't answer.

## Scientific decision contract

Who may decide what. This stays within AGENTS.md's rule that a person asks
for each move.

| Part | May | May not |
|---|---|---|
| The scientific agent (Claude) | Say what is most interesting tonight and why; judge what a night actually showed; propose follow-ups, with their reasons and windows; name gaps, recurring faults and opportunities missed. Every proposal is explained, recorded and can be replayed. | Move the mount or camera itself; change what tonight's plan is allowed to do without the person; improvise anything to do with safety. |
| The planner (`agent.recommend`, `schedule.py`) | Choose among the steps the person has agreed to tonight, by value, windows and conditions. | Add a step the person has not agreed to. |
| Execution and safety (`mount.py`, `shoot.py`, `altair.py`, the motion lock, the night-end guard) | Run the chosen step; keep every physical limit (skyline, hour angle, meridian, the lock); recover faults; stop for unsafe conditions. | Be overridden by any priority. A protected window is a reservation of time, never permission to pass a safety limit. |
| Analysis (`restack`, `depth`, `difference`, `vet`) | Measure outcomes, keep the evidence (frames, cut-outs, records), and feed the next choice. | Delete raw frames or evidence. |
| The person | Agree the night's steps; protect any step; decide anything that changes what can be found, what is observed first or the kit's safety; send any claim. | |

## The design

Each phase is useful alone and is proven before the next. Order: 1, 5, 2,
3, 4, so every change after Phase 1 is judged on replayed nights.

### Phase 1: say what each observation got

Every step's result is the six numbers the person asked for:

1. frames requested
2. captured
3. accepted
4. stacked
5. integration in seconds
6. depth reached (G, half of planted stars found), or the step's own
   measure (below)

Three outcomes are said apart, never folded into one "done":

- **Ran:** the step ran its course and kept frames.
- **Searchable:** there was enough to run the search or measurement at all.
  For a patrol panel, that is 8 stacked frames.
- **Worth it:** the result meets the step's purpose, such as a depth
  reached, a brightness measured to a given error, or a transit covered.

A panel can be searchable but too shallow to be worth it; it is then not
counted as watched, and keeps its turn.

Each outcome is *short*, *met* or *more than asked*. The goals come in
full in Phase 2. Phase 1 starts with provisional ones from the decisions
below, and changes nothing in how frames are taken.

- Each result also keeps:
  - **what limited it:** cloud, stalls, seeing, a shallow stack, or a
    subtraction whose local spread was out of line;
  - **where it came from:** frames, settings, reference version, code
    version (already in each record's provenance);
  - **what it leaves owed:** a candidate's second look, a field still
    short, a measurement pending (Phase 4).
- These go into the run's record, the schedule's line for the step, the
  night notes and the morning summary.
- Built on what `restack.json`, `depth.json` and `patrol.json` already
  hold.
- **Proof:** the 3-4 Nov night is replayed from its records. The result
  says panels 3, 5 and 6 ran but were not searchable and why, and that
  panel 1's second stack was searchable in frames but too shallow
  (G 15.7).

Built as `outcome.py` (docs/nights/2026-11-04/outcomes.txt is the night
read back), with these corrections from its audit:

- **Desired depends on worth it.** A session not worth having can't meet
  its desired goal: 24 frames whose search failed have not met a search's
  goal.
- **Only a search actually running is pending.** It is found by a live
  patrol or restack process naming the session or its programme. A search
  that started and ended without an answer is *failed* (with its log's
  last line), and one that never started is *not started*, to be swept.
  Neither waits for ever.
- **Stalls are said by where they come from.** Long gaps between frames'
  times are *inferred*: the camera, or the run doing something else.
  From 4 November 2026 the camera layer records each frame's failed tries
  and the seconds they took (`TY_RETRY`, `TY_GOT_S` in the raw frame's
  header), and those are reported as *recorded*. Phase 5 learns equipment
  reliability from the recorded ones only.
- **Limits stay visible.** `worth_depth = 16.5` in the programmes is
  provisional, until it is set from measured completeness, and is never a
  permanent criterion. A target no programme watches (SN 2026sqf in
  NGC 3310) is *not judged* until Phase 2 gives it a goal of its own.

### Phase 2: goals by purpose, in accepted frames or a measure

Each programme (`programmes/*.toml`) and planned target gets three goals,
by what it is for:

- `minimum`: the least worth having.
- `desired`: the result aimed for.
- `stretch`: more, if time is spare.

There is no one measure for every programme:

| Purpose | Measured by |
|---|---|
| Nova patrol (M31, M33, panels) | stacked frames to be searchable; depth for worth it |
| Supernova or other known transient | its own brightness measured to a given error, against a reference of its host (see below) |
| Exoplanet transit | unbroken coverage of ingress, egress and the baseline before and after, at the precision the depth needs |
| Comet or moving object | coverage of its path, the depth it needs, and the repeat it needs |
| Research lead (a star to check) | the brightness measured to the error its question needs |

Each programme also says its timing. It is one of these:

- one observation to a quality;
- a revisit after an interval, such as a second look within the night or
  a panel every few nights;
- a sequence over several nights, such as a moving object's path;
- an unbroken time series, such as a transit;
- a follow-up by a deadline, such as an unconfirmed candidate.

The planner reads it from the programme. This is not a second planner.

- **A supernova's goal is its own.** 30 minutes can be plenty for a bright
  one in the open, and too little for a faint one on a galaxy's bright
  core. SN 2026sqf on 4 Nov is the example: 480 s stacked, but its light
  could not be told from NGC 3310's centre. A reference made from our own
  first visit would hold the supernova too, so subtracting it would take
  the supernova's light away. Before time is given, the plan says which
  case it is:
  1. **A reference from before the explosion exists:** an archive picture
     of the host, or our own from before. Its brightness can be measured
     against that.
  2. **No such reference:** a brightness measured against a model of the
     galaxy, or relative to the last visit, said as such with its error.
  3. **Neither is good enough:** a detection or an upper limit only, said
     as that. More frames don't change this case.

  The goal follows the case. Our own pictures become a host reference
  only after the supernova has faded below what they reach.
- **Grading suits the science.** A frame fit for a nova search (many
  stars, sharp) may not be fit for photometry (steady sky, unsaturated
  comparison stars). Each programme says what its frames are judged on.
  The judgement is provisional and is checked against the session as a
  whole, as `restack` already does with its better half. Raw frames are
  never deleted.
- **The capture keeps going until `desired` accepted frames, or its cap.**
  A stall extends the time, up to the cap; a rejection extends the frame
  count. The two are counted apart. `retakes()` and the patrol's
  `SHOOT_CAP` merge into this one rule.
- **Planned and worst case are kept apart.** The plan books the expected
  cost (measured, Phase 5). The runner allows up to the worst case only
  out of time that nothing protected needs.
- **Decisions use quick measures, and the slow one when it comes.**
  Depth from planted stars takes minutes of processing, and processing
  never holds the telescope. While it runs, the next choice uses what is
  known at once:
  - accepted frames;
  - star size, star count and sky level from the frame log;
  - the depth `depth.predict` gives for them (the model the patrol
    already uses for its expected depth).

  The measured depth replaces that when it comes and can change later
  choices (a field found too shallow keeps its turn).
- **Goals include search quality.** A patrol field is worth it only where
  its recovery completeness and difference-image quality are, not just
  its depth. A deeper stack whose subtraction is the limit is not counted
  as better.
- **Proof:** a replay of 4 Nov's frame logs (stalls and rejections as they
  happened). Each panel reaches its minimum where the night allowed it.
  Where it did not, the shortfall and its cause are said correctly. Then
  one real night.

### Phase 3: protected windows

What is protected is a window, not a kind of object:

- **Hard windows:** occultations, exoplanet transits with their baseline,
  and transients whose science is in the next hour. These start on time
  whatever ran before.
- **Deadlines:** an object about to set or go behind the skyline, a comet
  heading into twilight, a follow-up needed before a known time. It must
  be finished by then; it may move earlier.
- **Flexible, high priority:** routine supernova photometry, nova patrols,
  mosaic panels. Chosen by value, never protected.
- **Protected by the person:** any step the person gives a start time or a
  window, whatever it is.

How the windows are kept:

- **The window starts with its setup.** A protected start reserves its
  GoTo, centring and a focus check before it, from Phase 5's measured
  costs. A transit's baseline begins with frames being taken, not with
  the GoTo.
- **Flexible steps are timed back from the next protected start.** The
  runner works out each flexible step's time backwards from it, setup
  included, so a flexible step can never take it. This generalises today's
  `--until` and `--budget`.
- **No other step cuts a protected one; safety and conditions can.** A
  protected window is a reservation of time, not permission. These stop
  it, whatever its priority:
  - unsafe weather, or cloud;
  - a mount limit (skyline, hour angle, meridian), lost position, or the
    motion lock;
  - a camera or mount fault that cannot be recovered;
  - power, or losing control of the kit.

  Those stay in the execution layer, independent of the planner.
- **Event times have their uncertainty.** A transit's predicted mid-time
  has an error, and an occultation's track has its width. The window
  covers the event's uncertainty as well as its length.
- **Setup is estimated by operation, conservatively for deadlines.** The
  setup a window reserves is not one fixed number. It is estimated from
  measured history by operation (GoTo by distance, a pole swing, plate
  solves, a focus check) and by recent faults. Before a hard window it
  uses the 90th percentile; elsewhere, the median.
- **Proof:** a simulated night where the step before it overruns, stalls
  and takes second looks. The protected step is taking frames at its
  window's start every time.

### Phase 4: choose the next step at each step's end

After each step the runner asks the planner again what is best now. It
chooses among tonight's agreed steps, within the limits the planner
already knows:

- the measured skyline and the house;
- altitude and airmass;
- the Moon's distance and the sky's brightness;
- twilight;
- the meridian and hour-angle limit;
- the expected image quality.

`sky.Night`, `horizon` and `schedule.path` already provide these.

**What is owed is kept, with why and until when.** It is kept between
nights in the candidate books and the schedule, never only in memory.
Each obligation says:

- what it is: an unconfirmed candidate's second look, an interrupted
  transit, a field short of its goal, a search not yet run, a failed
  plate solve;
- why it is owed;
- when it stops counting, such as a candidate that is no use to confirm
  after a week, or a transit that cannot be repeated tonight;
- whether repeating it is still worth anything.

**A candidate's claim on the night is weighed, not assumed:**

- **Confidence:** its evidence level, its real-or-bogus probability and
  that probability's uncertainty, and its significance against its own
  surroundings.
- **Novelty:** nothing catalogued, and not in a known problem patch.
- **What another look would settle:** a 5-sigma spot at the limit can't be
  settled by another visit at the same depth. That needs a deeper or
  steadier night, and waits for one.
- **Time sensitivity:** a nova fades over days, a moving object goes in
  hours, and a candidate past its usefulness is closed, not chased.

Uncertain candidates share a bounded part of the night: a follow-up
allowance, set with the person, which they cannot exceed. A candidate
with strong evidence (level 2 with high confidence) can go first at once.

It chooses by scientific opportunity:

- obligations near their expiry first, by their worth;
- then the best expected gain in discovery yield (above): coverage of a
  neglected field, depth where the subtraction is clean, a candidate's
  follow-up;
- then the best `stretch`.

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
  - targets that ran, were searchable and were worth it, against their
    goals;
  - accepted integration;
  - time idle.

  It also reports discovery yield: coverage, recovery completeness of
  planted transients, false-candidate cost and follow-up in time.

  It runs the current policy and the proposed one on the same nights.
  There is no single score, and no weights summing unlike things:

  - **Constraints, pass or fail:** no protected start missed to another
    step, no safety limit passed, nothing deleted. A policy that fails one
    is rejected.
  - **Measures, side by side, each with its uncertainty:**
    - coverage to a useful depth and cadence;
    - recovery completeness;
    - follow-ups done in time;
    - accepted integration where it counts;
    - opportunities missed (a field up and clear, left unsearched);
    - false-candidate cost.

  A new policy is preferred only if it is no worse on any measure beyond
  its uncertainty and better on at least one. Where it trades one measure
  against another, the trade is shown to the person, who decides.

  The test of a policy is not that every goal is reached: weather can
  make that impossible. It is that it made the best choice available by
  those measures and reported each shortfall and its cause accurately.
- **Stress nights,** beyond what has happened:
  - a camera that never recovers;
  - cloud coming and going every few minutes;
  - a night with no usable frame;
  - depth predictions that turn out wrong;
  - a protected event that becomes impossible (cloud, a fault) part-way.

  Each must end safely, with the shortfall said and nothing protected
  taken by another step.
- **What was seen and what is modelled are said apart.** A night's records
  say what happened where the telescope was. They don't say what a
  different target at a different time would have given. So a replay:
  - takes what is recorded wherever the policy does what was done;
  - models the rest (cloud by time, stalls by rate, depth from the model)
    with its uncertainty;
  - reports every figure as recorded or modelled.

  No policy is credited with frames the records cannot establish.
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

Approved by the person on 4 November 2026:

1. **Goals.**
   - M31 panels: 8 stacked frames to be searchable, 24 desired. Worth it
     at a depth to be set from the panels' measured completeness. A
     depth-based stretch.
   - M31 and M33 novae: G 17.5 desired as a start, checked against the
     search's measured completeness before it is fixed.
   - Supernovae and other known transients: by their own purpose
     (detection, or a brightness to a given error), and by which of the
     three reference cases applies (Phase 2), never one time for all.
   - Transits: unbroken ingress, egress and baseline at the precision the
     depth needs.
2. **The follow-up allowance:** the share of a night uncertain candidates
   may take. Proposed: a quarter, with strong ones (level 2, high
   confidence) outside it.
3. **Protection.** The four classes in Phase 3: hard windows for
   occultations, transits and the most urgent transients; deadlines for
   setting objects; everything else flexible; the person can protect any
   step.
4. **Order.** 1, 5, 2, 3, 4.

The person is asked about any choice that changes what can be found
(sensitivity), what is observed first, or the safety of the kit.
Ordinary building choices are made without asking.

## Sources

- Liverpool Telescope robotic control and dispatch scheduler: https://telescope.astro.ljmu.ac.uk/TelInst/Robotic
- RoboNet-II: https://arxiv.org/pdf/0808.0813
- NINA Target Scheduler, concepts and planning engine: https://tcpalmer.github.io/nina-scheduler/concepts and https://tcpalmer.github.io/nina-scheduler/target-management/exposure-plans.html
- Ekos Scheduler: https://kstars-docs.kde.org/en/user_manual/ekos-scheduler.html
- ZTF surveys and scheduler (Bellm et al. 2019): https://arxiv.org/abs/1905.02209
- LCO network scheduler as an integer program (Lampoudi et al. 2015): https://arxiv.org/abs/1503.07170
- Rubin feature-based scheduler: https://rubin-scheduler.lsst.io/fbs.html
- ANU 2.3 m automation: https://arxiv.org/pdf/2409.19842
- GOTO real-bogus classification (Killestein et al. 2021): https://arxiv.org/abs/2102.09892
- Proper image subtraction (Zackay, Ofek and Gal-Yam 2016): https://arxiv.org/abs/1601.02655
- NINA Target Scheduler image grader: https://tcpalmer.github.io/nina-scheduler/post-acquisition/image-grader.html
- BAA exoplanet observing guidance: https://britastro.org/section_front/exoplanets
