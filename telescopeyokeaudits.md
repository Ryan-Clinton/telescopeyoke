# **TelescopeYoke — Project Audit & Recommended Audit Programme**

Repository: [Ryan-Clinton/telescopeyoke](https://github.com/Ryan-Clinton/telescopeyoke?utm_source=chatgpt.com) · 20 November 2026 · Main branch `a08374b`

> **For every audit below: no testing.** Do not recommend tests, CI, a
> test harness, regression checks or simulator runs to verify a change,
> under any name. The owner will not have them back because (A) they took
> about 15 minutes a commit, (B) Claude could not be trusted not to run
> them on every commit, after being told to stop 13 times, and (C) they
> never caught a real fault. The full reasons are in `AGENTS.md`, "No
> testing, and why". A finding is checked by reading the code and proven
> on the telescope; the fix gets `ruff check` and nothing else.
> Testing is raised again only on evidence that other people are actually
> using TelescopeYoke, that the audits are leaving a pile of bugs, or that
> development is slowing because bugs testing would have caught are being
> lived with for a long time. Until then, don't raise it.

## Status

| # | Audit | Status |
|---|---|---|
| 1 | Mount safety and movement | done 20 Nov 2026, re-checked |
| 2 | Hardware failure and recovery | done 20 Nov 2026, re-checked |
| 3 | AI agent autonomy and permissions | done 20 Nov 2026, re-checked |
| 4 | Autonomous full-night operation | done 20 Nov 2026, re-checked |
| 5 | Guiding and calibration | done 20 Nov 2026, re-checked |
| 6 | Camera, cooling, filters and focusing | done 20 Nov 2026, re-checked |
| 7 | Scientific discovery reliability | done 20 Nov 2026, re-checked |
| 8 | Calibration and scientific measurement accuracy | done 20 Nov 2026, re-checked |
| 9 | Demo claims versus real-world proof | done 20 Nov 2026, re-checked |
| 10 | Hardware onboarding and compatibility | done 20 Nov 2026, re-checked; 3, 4, 8 and 9 done after |
| 11 | NINA/PHD2 companion | done 20 Nov 2026, re-checked |
| 12 | State management and data integrity | done 20 Nov 2026, re-checked |
| 13 | Observing scheduler and scientific yield | done 20 Nov 2026, re-checked; 7 done after |
| 14 | Weather and environmental decisions | done 20 Nov 2026, re-checked |
| 15 | Operational performance | done 20 Nov 2026, re-checked; 2-4 and 6 done after |
| 16 | Network security and external integrations | done 20 Nov 2026, re-checked; 2, 5 and 8 done after |
| 17 | Public releases and installation | done 20 Nov 2026, re-checked; release 0.4.2 waits for the owner |
| 18 | Architecture, documentation and maintainability | done 20 Nov 2026, re-checked; 7 and 8 deferred |

## **1. Initial assessment**

I've inspected the current repository structure, the latest commits, architecture, operating instructions, validation records, and the principal hardware-control components.

**TelescopeYoke has grown into a much larger and more ambitious project than a telescope-control application.**

It now covers:

- Physical observatory control: mounts, cameras, guiding, focusing, cooling and filter wheels.
- Autonomous observing: scheduling, weather decisions, target selection, imaging and recovery.
- Scientific discovery: transient detection, photometry, exoplanet transits and candidate verification.
- AI operation: Claude Code skills, specialist agents, safety hooks and structured commands.
- External observatories: the new NINA/PHD2 companion and ASCOM Alpaca integration.
- Public adoption: installation, hardware discovery, documentation, demonstrations and releases.

The architecture is reasonably well documented, and the project makes a valuable distinction between features demonstrated in simulation and those proven on real equipment.

However, **I would now concentrate on whether the different systems work reliably together**, rather than auditing individual features in isolation.

The existing operating instructions also explicitly rule out adding automated tests or CI. I'll respect that decision. My recommendations instead centre on code inspection, recorded evidence, operational safeguards and real-world verification.

### **What concerns me most**

The repository's own [outstanding work record](https://github.com/Ryan-Clinton/telescopeyoke/blob/main/docs/agents/owner-jobs.md?utm_source=chatgpt.com) identifies several important unresolved issues:

- Potential tube/tripod clearance problems west of the meridian.
- Declination drive behaviour that changes with balance.
- Cooler power and restart faults.
- Incomplete recovery from interrupted mount operations.
- Guiding changes awaiting real-sky comparison.

These are genuine operational uncertainties, not hypothetical software defects. They should influence the audit order.

## **2. Confirmed finding: safety fix missing from the latest release**

High priority

I found a concrete discrepancy between the current source code and the downloadable release.

The latest published release, [v0.4.1](https://github.com/Ryan-Clinton/telescopeyoke/releases/tag/v0.4.1?utm_source=chatgpt.com), points to commit `57f3c5a`.

At commit [f3a33f8](https://github.com/Ryan-Clinton/telescopeyoke/commit/f3a33f83bd5118ba86fb0896c84c90a3519978ea?utm_source=chatgpt.com), approximately an hour later, `mount.py` was updated to reject **named catalogue targets within 40° of the Sun while it is up**.

I checked both code versions:

- The released `v0.4.1` checks altitude and hour-angle limits for named GoTos, but lacks this Sun exclusion.
- Current `main` includes the new `refuse_near_sun()` check within `plan_goto()`.
- Pointing by azimuth and altitude already had a Sun check in both versions.

This matters because someone downloading the advertised release has a weaker safety check than someone cloning the latest source.

**Recommendation:** Publish the Sun-exclusion fix in a new release, and audit every movement entry point for consistent application of physical safety rules. Until then, users should not rely on v0.4.1 to reject named targets near the Sun.

This is an excellent example of why a release audit should examine more than whether the ZIP builds correctly.

## **3. The audits I would like to conduct**

The current repository contains **131 top-level Python modules, 57 JSON schemas, and 14 Claude Code skills**. That is enough complexity to justify separate, focused audits rather than one enormous code review.

I've ranked the audits according to operational risk, potential scientific impact, and the value of finding problems before more people start using TelescopeYoke.

P0 = immediate priority · P1 = important · P2 = improvement and maturity

| #      | Priority | Audit                                               | What I want to investigate                                                                                                                                                                                      |
| ------ | -------- | --------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **1**  | P0       | **Mount safety and movement**                       | Every possible movement path through `mount.py`, `direct.py`, Alpaca, the console and the scheduler. Meridian crossings, pier-side changes, collision zones, Sun avoidance and emergency stops.                 |
| **2**  | P0       | **Hardware failure and recovery**                   | What happens when USB disconnects, the handset stops responding, the camera crashes, power disappears, or an operation is interrupted halfway through. Can the system recover without making things worse?      |
| **3**  | P0       | **AI agent autonomy and permissions**               | Whether Claude can inadvertently bypass an operational safeguard through commands, shell wrappers, skill interactions or alternative execution paths. Inspect `policy.py`, hooks and all hardware entry points. |
| **4**  | P0       | **Autonomous full-night operation**                 | Follow a complete night from startup through imaging, guiding, clouds, retries and shutdown. Look for stuck states, repeated operations, unfinished work, and failures to park or warm the camera.              |
| **5**  | P1       | **Guiding and calibration**                         | Thorough inspection of `guider.py`, `guidecam.py`, `guidemath.py` and `phd2.py`. Calibration validity, Dec backlash, guide-star loss, correction feedback, dithering and recovery.                              |
| **6**  | P1       | **Camera, cooling, filters and focusing**           | Cross-module review of `altair.py`, `camera.py`, `keeper.py`, `shoot.py`, `focus.py` and `sxwheel.py`. Ensure state changes cannot corrupt an imaging session or damage equipment.                              |
| **7**  | P1       | **Scientific discovery reliability**                | Examine difference imaging, reference selection, candidate vetting, real/bogus classification, detection thresholds and false positives. Can the system distinguish a real discovery from processing artefacts? |
| **8**  | P1       | **Calibration and scientific measurement accuracy** | Darks, flats, bad pixels, filter matching, photometric precision, depth estimates, timestamps and astrometric measurements. Check the scientific assumptions against recorded results.                          |
| **9**  | P1       | **Demo claims versus real-world proof**             | Find anywhere the docs, the README or Claude treat something that only ran in the demo as proven on the telescope. The simulator stays as it is, for the demo and for trying a mount change first; it is not to be extended into a test bed. |
| **10** | P1       | **Hardware onboarding and compatibility**           | Follow a new user with unfamiliar equipment through `doctor.py`, `onboard.py`, `newhardware.py`, INDI, Alpaca and Windows support. Check where automatic discovery or setup assumptions break down.             |
| **11** | P1       | **NINA/PHD2 companion**                             | Audit log parsing, clock alignment, missing exposures, imaging gaps and cause attribution. Check how confidently it distinguishes facts from interpretations, especially with unfamiliar rigs.                  |
| **12** | P1       | **State management and data integrity**             | Concurrent processes, file locks, atomic writes, schema evolution, interrupted writes and stale state. Can one module make decisions using information another module has already invalidated?                  |
| **13** | P1       | **Observing scheduler and scientific yield**        | Review `schedule.py`, `dispatch.py`, `goals.py`, `obligations.py` and `nightreplay.py`. Does the planner maximise useful observations without sacrificing protected windows or operating constraints?           |
| **14** | P1       | **Weather and environmental decisions**             | Clouds, rain, dew, visibility, sky quality and forecast confidence. Identify how incorrect or stale environmental information influences autonomous decisions, including the limits of physical protection.     |
| **15** | P2       | **Operational performance**                         | Account for every minute between requesting an observation and obtaining a usable science frame. Examine repeated solves, unnecessary focusing, download delays, cooling interruptions and wasted transitions.  |
| **16** | P2       | **Network security and external integrations**      | Review the local control console, read-only API, MCP, remote access, credentials, logs, external downloads and public reporting. Check that boundaries are actually enforced in code.                           |
| **17** | P2       | **Public releases and installation**                | Release contents, dependency compatibility, platform-specific installation, version consistency, missing safety fixes and upgrade behaviour. Audit the actual downloadable version, not just `main`.            |
| **18** | P2       | **Architecture, documentation and maintainability** | Identify duplicated logic, contradictory operating instructions, oversized modules, obsolete paths, misleading validation claims and places where the different Claude skills disagree.                         |

## **4. Three particularly interesting investigations**

Beyond the immediate safety issues, these are the areas where I suspect a deeper audit could uncover significant opportunities.

### **The entire observatory as one state machine**

The system has quite sophisticated individual subsystems. But there are many independent processes that can affect the same equipment.

For example, consider an imaging run interrupted during a filter change while the camera is cooling, guiding is suspended, and the scheduler is preparing the next target.

I would trace who owns each device, who can resume an interrupted operation, which state is authoritative, and how every component knows the others have finished.

This is where subtle integration bugs tend to hide.

### **Are we actually getting the most science out of a clear night?**

The project has invested considerable effort in weather prediction, scheduling, guiding, focusing, imaging and scientific discovery.

I would like to audit the full observation chain using the actual recorded nights.

The observation-efficiency chain

Measure the time, failures and losses at each transition, rather than optimising each component independently.

A mount that takes ten seconds longer to settle might be insignificant. Repeatedly refocusing unnecessarily, abandoning recoverable sessions, or taking frames that ultimately fail science-quality checks could cost far more.

The key metric is **usable scientific data per hour of available sky**, not the speed of any single command.

### **The AI's understanding of the observatory**

There are now 14 Claude Code skills, six specialist agents, operational instructions, hardware records and a large collection of commands.

I would audit whether an agent actually receives enough current, trustworthy context to behave intelligently.

Can it distinguish an old fault from a current one? Does it know when hardware has changed? Can it recognise that an earlier diagnosis has been disproved? Does it follow the documented scientific priorities, or repeatedly fall back on familiar procedures?

I would specifically look for cases where **Claude's decisions are individually plausible but collectively unproductive**.

That is quite different from a conventional code audit.

## **5. My recommended order**

**First: Audits 1–4**

Establish whether the hardware can be operated safely, interrupted safely, and recovered predictably. The confirmed release discrepancy makes this particularly important.

**Second: Audits 5–9**

Examine whether the equipment and scientific pipeline are producing reliable observations, and whether anything is claimed as proven that has only run in the demo.

**Third: Audits 10–14**

Investigate interoperability, the companion, persistent state and intelligent observing decisions.

**Finally: Audits 15–18**

Improve efficiency, release quality and long-term maintainability before the project grows substantially further.

I would also use a consistent format for each detailed audit: verified findings with file and function references, severity, supporting evidence, recommended changes, and a clear distinction between what is demonstrated and what still needs real-world verification.

This initial pass was an architectural and risk assessment, not an exhaustive line-by-line audit of all 131 Python modules.

**My choice for Audit #1 is Mount Safety and Movement.** The recent Sun-exclusion fix, the outstanding meridian-clearance issue, and the number of different ways TelescopeYoke can command movement make this the most valuable place to start.

## 1. Mount safety and movement, 20 November 2026

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | Tube/tripod clearance is not modelled | P0 | Agreed and planned | Nothing to put in code yet: the safe envelope has to be measured with the tube as it is now (lowered on 20 Nov), west of the pier near the meridian (owner-jobs, item 1), with `./mount.py point --clearance-test` and someone at the mount. Waiting for the owner's hands |
| 2 | An aim-off moves the destination past the checks | P0 | Confirmed and fixed (the aim-off part) | `check_target()` holds the place actually aimed at (target plus `--aim-off`) to the altitude, Sun and hour-angle limits, in the GoTo and in its dry run. Demo: `goto M81 --aim-off 0 -6000` refused at -18°, `--aim-off 5 5` went. The pointing correction part is wrong: the correction makes the tube reach the checked place; the handset's own coordinates are not where the tube goes |
| 3 | Without a handset, power-on counts become home | P0 | Smaller than claimed, no change | The SynScan handset makes the same assumption (switched on at home); `direct.py` follows it, and GoTos still need the Dec direction watched. A mount switched on away from home is wrong with either |
| 4 | Stop leaves tracking on | P0 | Confirmed and fixed | `Mount.stop()` now turns tracking off too, as `direct.py` and `polaris.py` already did; every caller is an error or Ctrl+C path, and the next GoTo turns tracking on |
| 5 | Alpaca stop hides a failed AbortSlew | P0 | Confirmed and fixed | A stop with any part refused now refuses unless the driver says it is no longer slewing. Untried on a real Alpaca mount |
| 6 | A safe end point is not a safe path | P0 | Agreed and planned | Same measurement as 1; the route home was changed on 17 Nov from the record. Waiting for the owner's hands |
| 7 | Polar alignment's moves skip the Sun check | P0 | Smaller than claimed (night only), fixed | `polaralign.positions()` calls `mount.refuse_near_sun()` for each of its three positions |
| 8 | A slipped clutch leaves a false position | P0 | Partly right, fixed in the re-check | The pointing survey stops on a jump (mount.py, `JUMP`) and a solved GoTo on an unchanged miss (`moved.py`); a blind GoTo has no camera to tell. See 1, re-checked |
| 9 | No one process owns the mount | P1 | Agreed and planned | A lock taken at the first move would refuse `shoot.py` started by a patrol that has already moved the mount, so it needs an owner passed from parent to child; not done blind. No collision between processes is on record |
| 10 | Console Stop kills before stopping | P1 | Smaller than claimed, no change | Done in that order because Windows lets one process hold the port; the gap is the new process starting, a second or two |
| 11 | Point by bearing goes down to 2° | P1 | Owner's design, no change | The skyline trace and landmarks need low points, made by day with someone there |
| 12 | v0.4.1 lacks the Sun refusal | P0 | Confirmed, waiting | A 0.4.2 release waits for the owner's go |

## 1, re-audited at 233cdf1

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | Stop gives up at the first command that fails | P1 | Confirmed and fixed | `Mount.stop()` tries every part (cancel, the four rates, the Dec creep, tracking) and raises the first failure after all of them |
| 2 | The aim-off dry run reports the object, not the place aimed at | P1 | Confirmed and fixed | The dry run returns the aimed place's altitude, Dec, hour angle and side, with `aim_off_arcmin` (schema `goto-plan` updated). Demo: M81 5.527 h, aimed 30' east 5.435 h |
| 3 | Alpaca clears an axis's rate whose stop was refused | P1 | Confirmed and fixed | Only an axis whose zero rate was taken is recorded as stopped |
| 4 | The scheduler retries a step that failed on a suspected slip | P0 | Confirmed and fixed | `moved.refusal()` keeps `cache/mount-suspect.json`; while it is there `Mount.may_move` refuses anything run unattended (`TY_SCHEDULED`), and a person's next mount command clears it. Demo: the scheduled GoTo refused, the person's went and cleared it |

## 2. Hardware failure and recovery, 20 November 2026

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | An unanswered slewing query reads as "stopped" | P0 | Confirmed and fixed | `Mount.slewing()` asks again on a reply that is neither 0 nor 1 and refuses (HANDSET_NOT_ANSWERING) after four, so a GoTo never ends on a lost reply |
| 2 | A move that fails part way can leave an axis turning | P0 | Confirmed and fixed | `Mount.stopped_if_it_fails()` stops the mount whenever a GoTo, home or seek raises, whoever called it and whatever they catch |
| 3 | A failed re-centre counts as a success | P0 | Partly right, fixed | A refusal before anything moves (a limit, the Sun) still lets the run go on, tracking where it was; a move that began and failed, or a telescope found not turning, now ends the run |
| 4 | Stop gives up at the first failure | P0 | Confirmed | Fixed in 0893325 (`Mount.stop`); `direct.py`'s stop now halts each axis whether or not the other answered (and see 2, re-checked) |
| 5 | A cooler fault inside a keeper request leaves the keeper running | P0 | Confirmed and fixed | The keeper ends at once when a request leaves the cooler latched faulty: cooler off, camera closed, fault kept |
| 6 | A wheel reset between checks mislabels frames | P1 | Confirmed and fixed | The wheel is asked again as every frame ends, before it is kept; one that moved or does not answer stops the run with that frame not kept. The `check_every_s` setting is gone |
| 7 | An interrupted focuser move corrupts the kept position | P1 | Partly right, fixed | The Nano finishes every move it is given, so a move whose answer came is counted; one whose answer never came, or came wrong, now forgets the kept position until the next zero |
| 8 | Keeper stop reports success it has not seen | P1 | Confirmed and fixed | `keeper.stop()` says so and returns False when the keeper has not gone; the closing message says when the warm-up was cut short, with the temperature |

## 2, re-audited at 60fc90e

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | The stops catch `Exception`, and a Refusal is a `SystemExit` | P0 | Confirmed and fixed | `Mount.stop()`, `stopped_if_it_fails()` and `direct.py`'s stop catch `SystemExit` too, so a refused part no longer ends the stop |
| 2 | A stop sent is not a stop confirmed | P0 | Confirmed and fixed | After its parts, `Mount.stop()` waits up to 6 s (`STOP_CONFIRM_S`) for the mount to say no GoTo is under way, and refuses saying so if it does not |
| 3 | A refused re-centre still returns True | P1 | Smaller than claimed, no change | Inside a run the re-centre is always to the run's own target, and the run's first GoTo is planned and refused before it starts (`plan_goto` in `main`); a refusal mid-run leaves the mount tracking that target |
| 4 | The focuser counts any newline, and a serial failure keeps the old position | P1 | Confirmed and fixed | An interrupted move is counted only on its own `OK N` answer; any other failure after the order forgets the kept position |
| 5 | The keeper can still say "warmed up" without knowing | P1 | Confirmed and fixed | `warm_up()` returns whether the cooler took the off command; the keeper says "not known" when it did not, or the sensor could not be read |

## 3. AI agent autonomy and permissions, 20 November 2026

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | The agent can edit the safety code and the hooks | P0 | Right, and in conflict with the owner's way of working; waiting for the owner | The owner has Claude make code changes itself, in view, the mount's included (today's audits changed `mount.py` and `guard.py`). The movement limits are enforced in `Mount.may_move` and the plans, whatever the hooks say, and every edit to a safety file is now recorded (7). Blocking agent edits to `guard.py`, `policy.py` and `.claude/settings.json` is the owner's call |
| 2 | `ty spot NAME` and `ty research --html/--pull` count as read-only | P1 | Confirmed and fixed | `policy.classify`: `spot NAME` and `research --html` are `local_write`, `research --pull` is `external`, any word ty does not know is `hardware`; ty's options are read wherever they stand (`ty --json spot NAME` included) |
| 3 | `git -C . clean -xfd` gets past the lock's guard | P0 | Confirmed and fixed | `guard.git_subcommand()` skips git's global options before the subcommand is judged: `-C`, `-c`, `--work-tree=` and the rest now refused as `git clean -x` is |
| 4 | Claude's own move clears a suspected slip | P1 | By design, no change | In the main session a move is made only when the person asks for it (CLAUDE.local.md), which is the person's go; the night plan's moves run as `TY_SCHEDULED` and are refused |
| 5 | Grep and @-mentions reach config.toml past the secrets hook | P1 | Confirmed and fixed | `.claude/settings.json` denies `Read(./config.toml)` and `Read(./rigs/*.toml)`; the guard now also judges Grep, refusing a search of the settings file for the token or every line |
| 6 | `news.py` is not registered | P2 | Confirmed and fixed | Registered for SessionStart and UserPromptSubmit; run by hand it gave the 19 messages since it last ran (one of them a "warmed up ... safe to switch off" at -8.8 °C, the case 2.8 fixed) |
| 7 | The record misses edits to safety files and failed commands | P2 | Confirmed and fixed | `agentlog.event` records an edit to the mount, cooler, focuser, policy and hook files (path only), and PostToolUseFailure rows are marked `failed` |

## 3, re-audited at 89f215a

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | Wrapped git (`env git clean -x`, `sh -c "git clean -x"`) still gets past the lock's guard | P0 | Confirmed and fixed | `git clean` with `-x` or `-X` is refused anywhere in the line (`GIT_CLEAN_X`), and each command is unwrapped (`env`, `nohup`, `timeout` ...) before git's subcommand is judged; `env git rm` of the lock is refused too. A line that only mentions it (a commit message) is refused as well: written to a file instead |
| 2 | `.+` and `^.*$` get through the settings-search guard | P1 | Confirmed and fixed | A search of the settings file is allowed only when the whole pattern names one setting (`^latitude`, `focal_length_mm\s*=`); everything else is refused |
| 3 | Failed commands are counted as hardware commands that ran | P2 | Confirmed and fixed | A failed call is recorded as `event: failed` and left out of the hardware count |
| - | The owner's choices (Claude edits safety code; a person's ask is the go) | - | Agreed with the reviewer | They are trust decisions, written as such in rows 1 and 4 above, not technical enforcement |

## 4. Autonomous full-night operation, 20 November 2026

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | The application left open keeps the morning guard from parking | P0 | Confirmed and fixed | `app.py` and `console.py` are out of `schedule.IMAGING`; what they start (`mount.py`, `shoot.py` ...) is still found by its own name |
| 2 | A failed park is recorded as a night ended | P0 | Partly right, no change to the marker | `night.ended` is written before the move on purpose, so a move that went wrong is never tried again unattended; the person is told on their phone at once that it could NOT be parked. The camera part is 4 |
| 3 | An ordinary imaging step can run past its minutes | P0 | Confirmed and fixed | A `shoot.py` step with no end time is told `--minutes` (its step's) and given the same backstop as a patrol |
| 4 | The camera is not let go when the mount does not answer, or is already home | P0 | Confirmed and fixed | `end()` warms and lets the camera go when the mount does not answer; the guard does the same when the mount is already home or does not answer |
| 5 | A cloud watch retried after its deadline waits a day | P0 | Confirmed and fixed | `skywatch.watch()` takes a deadline less than 12 hours gone as passed and returns at once; one more than 12 hours gone is still the coming night's (02:00 asked at 20:55) |
| 6 | A step that ignores the backstop's Ctrl-C holds the night | P1 | Confirmed and fixed | Every backstop now has `--kill-after=900` (`KILL_AFTER_S`): 15 minutes for the run's warm-up and stack, then a kill, which exits 137 and counts as failed. The keeper holds the cooled camera, so a killed run does not cut its cooler |
| 7 | A step left "running" by a runner that died is passed over | P1 | Confirmed and fixed | At each pass, a running step with no process of its own that this runner did not start is marked failed (`interrupted`) and said |
| 8 | Old guider evidence can call a hardware failure cloud | P1 | Partly right, fixed | The guider's reason counts only when written since the step started; the satellite's cloud still counts, as the person asked (15 Nov: no alarm for a step lost to cloud) |
| 9 | The cloud live view is not stopped at the night's end | P1 | Confirmed and fixed | `liveview.py` is in `WATCHERS`, so `tidy()` stops it before the dawn flats |
| 10 | The cloud watch puts the filter back only when it finds stars | P2 | Confirmed and fixed | The filter goes back in the watch's `finally`, however it ends |

## 4, re-audited at aec4d99

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | `--minutes` added to `--blocks` and `--ladder` runs, which refuse it | P0 | Confirmed (a regression of aec4d99) and fixed | `prepared()` leaves `--minutes` off a run that times itself (`--blocks`, `--ladder`), with or without an end time; the backstop still applies |
| 2 | A second runner would take the first's running step for abandoned | P0 | Confirmed and fixed | `run()` refuses to start while another live process holds `cache/schedule.runner` |
| 3 | The morning guard says nothing when the mount does not answer | P0 | Confirmed and fixed | It tells the person once (the night then counts as ended), warms the camera, and never moves the mount |
| 4 | A run with its own `--minutes` gets no backstop | P1 | Confirmed and fixed | Every imaging step with no end time is backstopped at the longer of the step's minutes and the run's own |
| 5 | The satellite's cloud can still cover a hardware failure | P1 | Agreed and planned | The runner sees only the exit code (1 for every refusal), so it cannot yet tell a refused filter wheel from cloud. Planned: a run's refusal code kept beside its session for the runner to read; until then the person's rule (no alarm for a step lost to cloud, 15 Nov) stands |
| 6 | The 12-hour rule misreads a daytime ask for 02:00 | P2 | Smaller than claimed, no change | A cloud watch is started when its step runs, at night; a watch asked for by day sees no stars anyway |

## 5. Guiding and calibration, 20 November 2026

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | A south leg that never moved is made up from north and guided both ways | P0 | Confirmed and fixed | Fewer than three south steps that moved the star now gives a calibration for RA alone (`ra_only`), as a failed north does, with the reason kept |
| 2 | An RA-only guider is asked to dither in Dec | P1 | Confirmed and fixed | With Dec not guided, the guide loop makes only the dither's RA part, so the lock can be reached |
| 3 | The Dec-stuck cap cannot reach a run's guider | P1 | Partly right, fixed as a setting | `guidecam.py guide` takes `[guider] dec_stuck_s` from the settings when not given, so `shoot.py --guide` has it once a person sets it; off by default, as the reviewer advises (the Dec drive is waiting on its mechanical check, owner-jobs item 2) |
| 4 | Guide-camera library answers ignored (gain, exposure, pulse state, stop) | P1 | Confirmed and fixed | A refused gain or exposure stops the frame; a pulse state the library cannot give is never taken for ended (a stop is sent and the run told); `stop_pulse()` says whether the camera took it |
| 5 | Late guide frames can make their own cadence the normal one | P1 | Confirmed and fixed | The cycle a guide frame covers is never longer than its exposure plus 2 s (`CYCLE_EXTRA_S`), so late frames leave the gaps counted as lost |
| 6 | Frames do not say RA-only from two-axis guiding | P1 | Confirmed and fixed | Every guided frame carries `GUIDEMOD`: `RA`, `RA+Dec` or `PHD2` |
| 7 | PHD2 "Guiding" with no guide steps keeps the run going | P1 | Confirmed and fixed (untried on PHD2 itself) | No fresh guide step for `LOST_WAIT_S`, kept across frames, is a fault that stops guided imaging, as a stopped PHD2 is |
| 8 | PHD2's errors in arcseconds from an assumed 1"/px | P1 | Confirmed and fixed (untried on PHD2 itself) | No scale from PHD2, no RMS or largest error in arcseconds; GUIDED is still judged from the steps |
| 9 | Drift taken off over a long Dec test is not labelled uncertain | P2 | Agreed and planned | For the Dec drive's investigation once its mechanics are checked (owner-jobs item 2); no long calibrations run in its place |

## 5, re-audited at 0381373

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | GUIDEMOD (and GUIDER) dropped before the frame is saved | P1 | Confirmed and fixed | Both are in `stacking.KEPT`, so they reach the saved FITS |
| 2 | An RA-only dither projected from a random direction can shrink to nothing | P1 | Confirmed and fixed | With Dec not guided, `Supervisor.dither()` puts the whole distance along RA, one way or the other, and returns what it asked for |
| 3 | Three south steps need not be running | P1 | Confirmed and fixed | South counts only with three steps running that moved the star; its column is taken from the first such run |
| 4 | A dither not settled in 50 s is answered as made | P2 | Smaller than claimed, no change | The answer says "moved; not settled", the lock has moved, and the next frame waits for settling or is marked (13 Nov 2026: answering it as failed ended two runs) |

## 6. Camera, cooling, filters and focusing, 20 November 2026

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | An interrupted focus run goes back by a count it does not know | P1 | Confirmed and fixed | `focuser.Focuser.move` says whether the Nano confirmed the move (`confirmed`); the focus run's count becomes unknown when it did not, and the run is then left where it is with a word to zero again, never moved back from a guess |
| 2 | A filter change's focus move that fails part way leaves a wrong focus reference | P1 | Confirmed and fixed | The reference is marked unknown before the first turn and set only when every move is done; while it is unknown a filter change refuses (REFOCUS_NEEDED) until a focus run sets it |
| 3 | A focus command that opened a cooled camera closes it cold | P1 | Confirmed and fixed | `focus.let_go()`: a camera focus opened itself is warmed slowly (`shoot.warm`) before it closes, in `--check`, the motor focus and the interactive view; one lent by a session or kept by the keeper is left cold |
| 4 | A cooled frame of unknown sensor temperature passes as on target | P1 | Confirmed and fixed | `stacking.on_target` leaves out a frame with SET-TEMP and no TY_ONTGT, and says so. Measured first: none of the 1,067 cooled frames on disk is one, so no recorded result changes |
| 5 | The interactive view can close the camera mid-exposure | P1 | Confirmed and fixed | It waits up to three times the exposure plus 30 s (the camera's own retries) for the last frame, and says so if even that runs out |
| 6 | A deferred raw save that fails is still counted as kept for the quality pass | P1 | Confirmed and fixed | The run keeps each deferred save's result; a failure replaces that frame's entry ("raw file not written"), and `stacking.read_log` keeps a frame's last entry |
| 7 | A provisional offset need not have approached focus inward | P2 | Confirmed and fixed | Only a verified measurement that approached inward can be provisional; no offsets are kept yet, so nothing in use changes |
| - | The 19 Nov cooler record's open questions | - | Agreed | Hardware questions, not settled by code; they stay open in the record |

## 6, re-audited at b1a701b

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | The interactive view still closes the camera after its longer wait | P1 | Confirmed and fixed | After the wait it says so and waits for the frame (or its recovery) to end, never closing the camera under it |
| 2 | An interrupted Alpaca focuser move is counted as made | P1 | Confirmed and fixed | An interrupted move counts only when the focuser itself confirmed it; one that does not say is unknown |
| 3 | The interactive view's setup can fail before its cleanup | P1 | Confirmed and fixed | A failure between opening the camera and the loop lets it go warmed and closed |
| 4 | A failed deferred save can leave a half-written light file | P2 | Confirmed and fixed | `stacking.save_light` writes to a hidden partial name and renames it whole |
| 5 | Demo runs were recorded as checks of these changes | - | Right | Against AGENTS.md (the demo only for a change to how the mount moves): the line is gone from this plan, and no demo is run to check a change that does not move the mount |

## 7. Scientific discovery reliability, 20 November 2026

Verdicts and searches already recorded are not remade: every change below applies to searches run from now on (each result is stamped with the code that made it).

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | Explained neighbours can make a new candidate "residue" | P0 | Confirmed and fixed | `vet.residue()` counts only unexplained (or residue) detections within 2': a known variable and asteroid beside a new source leave it unexplained |
| 2 | A search a passing failure stopped is never swept again | P1 | Confirmed and fixed | `patrol.searchable()`: a session whose depth, difference or vet step was stopped by anything but a verdict on the data (INVALID_REQUEST: too shallow, a skewed subtraction) can be searched again |
| 3 | A catalogue outage stops the alert; an empty answer counts as "none" | P1 | Confirmed and fixed | A catalogue that refuses is "not asked" in the record and the vetting goes on to the alert; a VizieR answer without the VSX table is a failure, never kept for 30 days as no variables; Rochester pages that all fail for a year are "not asked", never "none reported" |
| 4 | Nearness alone closes a candidate as a known asteroid or variable | P1 | Agreed and planned | Checking the asteroid's predicted motion against the frames' times (SkyBoT gives it), and keeping a VSX match within 5" ambiguous where the source cannot be told apart, are changes to the verdicts' science: for a new version with the old verdicts compared against it |
| 5 | Candidates do not match across RA 0 | P1 | Confirmed and fixed | `candidates.arcsec` and the residue's distance wrap RA (359.9999 and 0.0001 at the equator: 0.72") |
| 6 | An explicit `--reference` can be the night itself | P1 | Confirmed and fixed | `difference.py` refuses a reference from the same session, or the field's kept reference made with this night, however it was named |
| 7 | A second look can call a candidate a false alarm without the depth to | P1 | Confirmed and fixed | A candidate not seen again is a false alarm only where the second look's limit there reached its brightest; otherwise it is said to be not ruled out |
| 8 | References are chosen by depth, not subtraction quality | P1 | Agreed and planned | The M31-P8 record (4 candidates against 24 from a deeper reference) is the evidence; a quality measure for choosing references is a change of its own, made against the recorded subtractions |
| 9 | The real/bogus model is not checked against the code it was trained for; its score is called a probability | P2 | Agreed and planned | The score stays advisory (it never dismisses a candidate); checking the model's provenance against the subtraction code, and saying "score" where it is not a calibrated probability, are planned |

## 7, re-audited at ae9ae91

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | An older reference version, or any stack named by path, escapes the independence check | P1 | Confirmed and fixed | `difference.py` takes the sessions of the very file named: every kept version's record whose file it is, and the stack's own (`reference.made_from`) |
| 2 | Alerts still match candidates by raw RA | P1 | Confirmed and fixed | `patrol.alert` and `notify.candidate_alert` match with `candidates.arcsec` (3.6", the old 0.001° box), across RA 0 |
| 3 | A search's answer and its alert's delivery are not told apart | P1 | Confirmed and fixed | The patrol record now keeps `alerted` and `alert_delivered` (schema updated), written again after the alert; an undelivered alert is said in the run's log and reaches the agent as "(not delivered)"; nothing is sent twice. `outcome.search_state` takes a failed `search.json` over an earlier answer |
| 4 | A bad VSX answer cached before the fix is still trusted | P1 | Confirmed and fixed | A cached answer is judged as a fresh one (`vsx_table`), and one that fails is deleted and asked again |
| 5 | A second look with one seen again says nothing of the rest | P2 | Confirmed and fixed | Every alerted candidate is said as seen again, gone where the look was deep enough, or not ruled out |

## 8. Calibration and scientific measurement accuracy, 20 November 2026

Results already recorded are not remade; each new one is stamped with the code that made it.

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | Vetting's stacks, and so the variable-star and transit light curves, calibrate without the frame's header | P1 | Confirmed and fixed (worse than claimed) | With no header the camera in use chose the masters: a 183C frame measured today was calibrated as the 183M's, and a 183M frame got the settings' defaults and no filter's flat. `vet.stacked` passes the frame's header |
| 2 | The flat-dark is looked for at the light's gain | P1 | Confirmed and fixed | The flat-dark is matched to the flat's own exposure, gain, offset, binning, readout and temperature. Measured first: all ten kept 183M flats were taken at the lights' settings (gain 1500, offset 80, speed 3, -5 °C), so no recorded calibration changes |
| 3 | The depth sweep calibrates without the header | P1 | Confirmed and fixed | `depth.sweep_stacks` and the planted-star test pass the frame's header |
| 4 | Transit middles in JD (UTC) against an ephemeris in BJD_TDB | P1 | Confirmed and fixed | The fit is made in BJD_TDB when the site is known, and every fit says its `time_standard` (schema updated); without a site it says the early or late is uncertain by up to 8 minutes |
| 5 | The calibration check reads only each folder's first frame | P1 | Confirmed and fixed | `stacking.require_frames` reads every frame's header and checks each set of settings (camera, train, filter and the dark's cards) once |
| 6 | The 183C's stacks say TY_CALIB with no masters | P2 | Confirmed and fixed | TY_CALIB stays "may enter science"; a 183C stack also says `TY_CALFUL`, whether dark, bias and flat were all applied |
| 7 | DATE-OBS is when the exposure was asked for, about 0.4-0.5 s before it began | P2 | Agreed and planned | A card with the measured lag and its uncertainty, for transit timing |
| 8 | Gaia positions are J2016, not the night's | P2 | Agreed and planned | Proper motion carried to the frame's epoch where Gaia gives it, and a position uncertainty on reported candidates |

## 8, re-audited at 30a8907

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | Vetting and the depth sweep use the first frame's calibration for all | P1 | Confirmed and fixed | Each frame is calibrated with its own masters (`stacking._calibration` on its own cards, one load per set of settings) |
| 2 | Restack certifies a stack from each session's first frame | P1 | Confirmed and fixed | TY_CALIB and TY_MISS come from every set of settings among the frames that went into the stack |
| 3 | The transit chart draws BJD middles on a UTC axis | P1 | Confirmed (a regression of 30a8907) and fixed | The record keeps the night's offset (`time_offset_days`, schema updated) and the chart puts the predicted and fitted middles back on UTC. The planner's windows stay in UTC with the ephemeris's middle: minutes against an hour's baseline either side, no change |
| 4 | The ephemeris's standard is assumed | P1 | Confirmed and fixed | The archive gives it per planet (`pl_tranmid_systemref`: on 20 Nov 2026 2,733 BJD, 796 BJD-TDB, 1,436 JD, 112 HJD, 49 blank). BJD and HJD middles are met with BJD_TDB, JD with JD; a blank one, or no site, is fitted in JD and its early or late said to be uncertain by up to 8 minutes. The planet list is fetched again for the new column |
| 5 | Cached light curves from before the change are reused | P2 | Confirmed and fixed | `variables.VERSION` is 2, so they are measured again with each frame's own masters; old records keep their stamp |
| 6 | The transit report names the 183C's calibration files for the 183M | P2 | Confirmed and fixed | It says the frames' own calibration: a matched camera's missing masters, or the 183C's dark and flat |

## 9. Demo claims versus real-world proof, 20 November 2026

Documentation only; `docs/validation.md` is the authority and is unchanged.

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | The homepage says each piece of a night has run on the real mount | P1 | Confirmed and fixed | It now says the steps and GoTos have; the night's end (parking and telling you) has not yet run by itself through a real night (validation: "the whole not yet through a real night") |
| 2 | The homepage sells the click and tone, which only the demo has run | P1 | Confirmed and fixed | Spoken numbers first, as used under real stars (and the default since 8 Nov); the click, tone and "Focus good" with `--tones`, said to be the demo's so far |
| 3 | Windows install and launch said with more confidence than the record | P1 | Confirmed and fixed | README and homepage say `try-demo.cmd`, `install.ps1`, the Start Menu and the window are untried on a real Windows machine; the Windows camera's indoor frames are said as proven |
| 4 | The demo's plate solves are the simulator's | P2 | Confirmed and fixed | The README says so beside the tour, and that the centring code is the real one and ASTAP is proven apart |
| 5 | The command references still call guiding unproven | P2 | Confirmed and fixed | `docs/commands.md` and `docs/agents/commands.md` give the 10 Nov and 19-20 Nov figures, the Dec drive's fault and that 300 s is not yet proven |
| 6 | The page's search description lists EQ5, HEQ5 and EQ6 bare | P2 | Confirmed and fixed | "run on an EQ3 Pro; EQ5, HEQ5 and EQ6 untried" |
| 7 | The README's evidence table puts ZTF archive data under the simulated rig, and says everything runs there | P2 | Confirmed and fixed | The cell says real archive data, not the rig, beside the planted fakes; "everything" is now "most of it", the column saying which |
| 8 | "Tested" in the agents' page reads as proof | P2 | Confirmed and fixed | A project command is "a script of the project's", with validation.md as the word on what is proven; the hooks' list says it was checked when built and there are no tests now; the page's own note on "tested" stays |

## 9, re-audited at 5abf3d6

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | The page's search descriptions still say "whole nights run with an AI agent" | P1 | Confirmed and fixed | Both say "nights run with an AI agent (a whole night ended by it alone not yet tried)" |
| 2 | The ZTF result is still in the simulated rig's column | P2 | Confirmed and fixed | The cell keeps the planted fakes; the ZTF result is a line under the table, as real astronomy that is neither this rig nor the simulator |
| 3 | Alpaca, PHD2 and the companion are said as one level of proof | P2 | Confirmed and fixed | Three claims: Alpaca on ASCOM's simulator, PHD2 against a pretend PHD2, the companion on the owner's 693-frame night and three observatories' published logs, not yet live |

## 10. Hardware onboarding and compatibility, 20 November 2026

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | Two INDI cameras: the first is used, labelled as the profile's | P1 | Confirmed and fixed | `camera.py` refuses two eligible INDI cameras unless `[indi] camera` names one, and uses only that one; the doctor says the same (a FAIL, no longer a WARN) |
| 2 | The mount can be the first lead or Wi-Fi adapter found | P1 | Partly right, fixed | Two leads matching `serial_match`, or two Wi-Fi adapters answering, are refused, naming them. The `/dev/ttyUSB0` fallback is smaller than claimed: the handset's echo test (`Kx` answered `x#`) refuses anything that is not a SynScan handset before any command |
| 3 | First moves counted done from corrected GoTos | P1 | Smaller than claimed; open (see 10, re-checked) | The step already says how it is known ("proven by use ... not the same as someone watching") apart from the person's word, and without a handset `direct.py` refuses GoTos until a person has watched the Dec direction, whatever onboarding says. Fixed after the loop: `--confirm moves` keeps the mount it was given for (`onboard.mount_identity`: link, lead adapter, address, device), and counts only while the settings reach that mount |
| 4 | One changed setting marks a whole part set | P1 | Fixed after the loop | A part is done only when every value is changed from the example's, measured (focal length and pixel size by a plate solve that agrees; width and height by a kept frame's size), or confirmed. The owner's telescope is now open: its aperture is the example's 150 mm, so `--confirm telescope` is theirs to give |
| 5 | The first-night skill and newhardware call Alpaca-reachable devices impossible | P1 | Confirmed and fixed | Both say "experimental through its ASCOM driver (Alpaca), tried only on ASCOM's simulator" where that route exists, apart from proven and unsupported |
| 6 | The doctor tells an Alpaca user to close their ASCOM driver | P2 | Confirmed and fixed | With `[mount] link = "alpaca"` it says to leave the driver and its Alpaca server running |
| 7 | A managed INDI server not yet running fails the camera check | P2 | Confirmed and fixed | It is a WARN: the server starts when the camera is first opened, and the camera is not yet checked |
| 8 | Two identical USB adapters share one identity in newhardware | P2 | Agreed; fixed after the loop | `host.serial_details` gives a hash of each adapter's serial number (or USB socket) as `local`; newhardware keeps devices known by it in cache/, and no report or answer carries it. Devices marked known before still count by kind |
| 9 | First-frame evidence does not name the light path's train | P2 | Agreed; fixed after the loop | A kept frame counts for the light path in use only when its TELESCOP is that train (frames from before TELESCOP was written count by camera and focal length) |

## 10, re-audited at 25ca017

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | The ambiguous-lead refusal covers only Linux's handset path | P1 | Confirmed and fixed | `host.one_serial_port()` is the one rule: the handset path (before and after a USB recovery), the EQDIR lead and Windows' COM ports all refuse two matching leads |
| 2 | The INDI device chosen is not tied to the profile its frames are labelled with | P1 | Confirmed and fixed | A profile that names its `model` refuses an INDI device whose name does not hold it |
| 3 | A managed INDI server not yet started let the doctor call imaging ready | P1 | Confirmed (a regression of 25ca017) and fixed | It is a FAIL again, saying the camera has not been seen yet and `./snap.py` opens it |
| 4 | Findings 3, 4, 8 and 9 are explained, not changed | P2 | Agreed | They stay open in the status table. The owner's rig has never given its word for "first moves" (its GoTos prove it by use), so requiring the word would mark a rig that has moved for weeks as not set up: binding the word to the mount's identity comes with it |

## 11. NINA/PHD2 companion, 20 November 2026

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | One zone for every log, no clock offset, alignment never doubted | P1 | Partly right, fixed | `--nina-tz`/`--phd2-tz` and `--nina-offset`/`--phd2-offset` give each log its own zone and clock offset; the report now says the clocks are taken to agree with the frames' UTC, after any offsets. Measuring the offset from the data is not attempted |
| 2 | Several NINA logs in the wrong order break the time matching | P1 | Confirmed and fixed | After reading, every list (exposures, saves, detections, focuser moves, targets, events, errors) is put in time order, and a line given twice counts once |
| 3 | A save is given to the last exposure started, however long before | P1 | Confirmed and fixed | Only within the exposure's length and two minutes (`SAVE_WITHIN_S`); otherwise it belongs to none |
| 4 | Files are matched by name alone, so two targets' LIGHT_001 are one | P1 | Confirmed and fixed | By folder and name (`file_key`); by name alone only when the frames were copied into folders of other names and nothing matches that way |
| 5 | No PHD2 session in a gap is "no guiding (measured)" even outside the log | P1 | Confirmed and fixed | Each log's span is kept; outside every span the report says PHD2's log does not cover then and guiding is not known |
| 6 | One pixel scale and cycle for every PHD2 session | P1 | Confirmed and fixed | Each session keeps the scale and exposure PHD2 gave for it, and a frame is judged by its own session's |
| 7 | Unsaved frames counted as starts minus saves in a window | P1 | Confirmed and fixed | Counted from each exposure's own matched save |
| 8 | The live watch ignores the frames already there as its reference | P2 | Confirmed and fixed | They are read into the reference without being said again |
| 9 | Frames with no start time weaken the timeline silently | P2 | Confirmed and fixed | The report says how many were measured but left out of the timeline |
| 10 | The report says unsaved frames are not seen even with NINA's log | P2 | Confirmed and fixed | With NINA's log it says they are from the log |

## 11, re-audited at ae1a11a

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | `--night` and the night a frame belongs to ignore the new zones | P1 | Confirmed and fixed | Both use the observing zone (`--nina-tz`, else `--tz`, else this computer's): `night_span` and `observing_date` |
| 2 | NINA's lines are interpreted in the order the files were given | P1 | Confirmed and fixed | Every file's lines are put in one time order, each once, before any is read, so a step begun in one log and finished in the next closes |
| 3 | The name-only fallback brings back the collision | P1 | Confirmed and fixed | A name is matched alone only when it is one file on each side; a name two targets share keeps its folder and stays unmatched |
| 4 | `sparse()` and `interruptions()` still use the log's one cycle | P1 | Confirmed and fixed | Each uses its own session's cycle (`at()`) |
| 5 | A frame being written when the watch starts is marked seen and never read | P2 | Confirmed and fixed | Only a frame that reads is taken in at the start; one that does not is left to the loop, which waits for it to stop growing |
| 6 | A save before its exposure could have ended is still given to it | P2 | Confirmed and fixed | A save more than 5 s before an exposure's end (`SAVE_EARLY_S`) is tried against the one before, and belongs to none if that does not fit either |

## 12. State management and data integrity, 20 November 2026

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | Schedule changes read, change and write with no lock | P1 | Confirmed and fixed | `schedule.transaction`: `add`, `skip`, `move`, `mark`, `mark_id`, `add_session` and `end_session` each hold the plan's lock (`records.locked`) across their read and write; none calls another |
| 2 | Obligations can be lost between a refresh and an owe | P1 | Confirmed and fixed | `refresh`, `owe` and `spend` each hold the store's lock across their read and write |
| 3 | The run's one order file: one order over another, one taken unread | P1 | Confirmed and fixed | The orders are a queue in that file, added to and taken under its lock; a stop is taken before any other, and an order for another run stays. An acknowledgement file, as the guider's orders have, is planned |
| 4 | Two runners can both pass the PID check | P1 | Confirmed and fixed | The runner holds an operating-system lock (`cache/schedule.runner.lock`) for its life; the PID file stays for saying who |
| 5 | The storage disk's move then link can lose a frame's path | P1 | Confirmed and fixed | Copied under a partial name, its size checked, renamed into place; the link made beside the original and swapped in for it, so the path always holds the original or a link to a whole copy |
| 6 | A reference version can be half published, two can take one number | P1 | Confirmed and fixed | Under the field's lock: the stack and its depth copied whole and renamed into place, and the version's record, which makes it kept, written last |
| 7 | One torn line hides a whole session's frame log | P1 | Confirmed and fixed | A line that is not whole is left out and said; nothing is made up, and the file is left as it is |
| 8 | Activity history written directly, its runs list without a lock | P2 | Confirmed and fixed | `records.write` for the last activity and `records.change` for the runs, still never failing the run |
| 9 | No common rule for reading older records | P2 | Agreed and planned | For the candidate books, obligations, references and calibration first: each reader to say the versions it reads and refuse a newer one |

## 12, re-audited at 148bdfe

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | The orders queue is rewritten with `write_text`; a broken one read as an order | P1 | Confirmed and fixed | Written with `records.write` under the lock; a file that is not whole is said and gives no order (a bare word is read as an order only if it is one of the known ones). The acknowledgement stays planned |
| 2 | `schedule.py clear` and `add_blocks` bypass the lock | P1 | Confirmed and fixed | Clear holds the plan's lock; `add_blocks` adds all its blocks under one lock (`_add` inside, `add` its locked form) |
| 3 | The archive copy is checked by size only; a relative archive path breaks the link | P1 | Confirmed and fixed | The copy is synced to disk and its SHA-256 compared with the original's before anything is replaced; the archive path is made absolute |
| 4 | A torn last log line and damage inside the log are said alike | P2 | Confirmed and fixed | A cut-short last line is said as an interrupted write; damage before the end is said loudly, with the line numbers, as frames' records missing |
| 5 | `runs.clear()` does not make a dict | P2 | Confirmed and fixed | A history of any other shape is begun again as a dict, under its lock |

## 13. Observing scheduler and scientific yield, 20 November 2026

The goals, windows and dispatch phases are off on the owner's rig ([goals], [windows] and [dispatch] unset), so findings 1, 3, 4, 6 and 8 change nothing on its nights until they are switched on.

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | A depth goal's frames go through the stacked share twice | P1 | Confirmed and fixed | `goals.capture_rule`: the model's stacked seconds give stacked frames (seconds over exposure), turned into accepted frames through the share once (960 s of 16 s frames: 60 stacked, 72 accepted, where it was 61) |
| 2 | A timed step with its own target is skipped with no field imaged last | P1 | Confirmed and fixed | Only a step whose command fills `{last}` waits on a field imaged last |
| 3 | Outcomes read newest first; a short field forgotten after three nights | P1 | Confirmed and fixed | Oldest night first, so a later success clears an earlier shortfall; a short field stays owed until a later night meets its goals or its 10 days run out, never closed for leaving the window scanned |
| 4 | A ranking that fails takes the list in order, dropping protected windows | P1 | Confirmed and fixed | It falls back to `windows.choose` (protected starts and their cut-offs kept), and to the list only if that fails too |
| 5 | A second look has no time limit of its own | P1 | Partly right, fixed | Its frames stay the depth it needs, and it now has `--minutes` at 1.5 times its minutes (`SHOOT_CAP`). Asking the next step's time in the single-field path, as the mosaic path does, is planned |
| 6 | A missing local score counts towards "strong" | P1 | Confirmed and fixed | Strong needs the local score measured and at least 5 |
| 7 | A protected event is started however late | P2 | Agreed; fixed after the loop | `windows.missed`: a hard or deadline step's latest useful start is its own `latest`, else half its minutes into its window (or half its minutes before its deadline); later, the runner skips it with the reason and owes it |
| 8 | The programme's own cap is ignored by the patrol | P2 | Confirmed and fixed | The patrol's capture uses the capture rule's `cap_minutes` when goals are on |
| 9 | Night replay cannot show more discoveries | P2 | Agreed, no change | The replay already says what it does not model; no claim of more discoveries is made from it |

## 13, re-audited at d52437e

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | A short field's later success outside three nights does not clear it | P1 | Confirmed and fixed | While a short field is owed, the refresh reads back FIELD_DAYS (10) nights, so a night that met it clears it after days off |
| 2 | A second look's cap ignores the time left; the single field does not ask the next step | P1 | Confirmed and fixed | Its `--minutes` is the smaller of 1.5 times its minutes and the patrol's time left; the single-field path asks `due_step()` as the mosaic does |
| 3 | The replay's caps no longer match the live patrol's | P1 | Confirmed (a mismatch of d52437e) and fixed | The replay uses the programme's own cap kept to the budget, and caps the second look as the live one is |
| 4 | The fallback can fail again on the costs | P2 | Confirmed and fixed | It passes `{}` (the setup defaults) when the costs could not be had |

## 14. Weather and environmental decisions, 20 November 2026

The rain alert stays on in every case (the owner's rule, 15 November 2026): these changes make it earlier and keep it from being cleared without evidence, never quieter.

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | A stale forecast copy can still give GO | P1 | Confirmed and fixed | When the Open-Meteo forecast used is a stale or unavailable copy, a GO is held back to MARGINAL with the reason said |
| 2 | The radar's newest picture has no age limit | P1 | Confirmed and fixed | Each look keeps the picture's age; older than 30 min (`STALE_MIN`) it is marked stale, and a stale picture never clears a rain warning |
| 3 | The warning counts arrival from the picture, not from now | P1 | Confirmed and fixed | `arrives_in_min` is the arrival from now (picture's minutes less its age) and decides the warning; `arrives_min` stays from the picture for the scores |
| 4 | Gusts and a lone wet centre do not touch the verdict | P1 | Partly right, fixed for wind | Gusts at or over 35 km/h (`GUST_SHAKES`) hold a GO back to MARGINAL. Rain stays the centres' majority for the verdict, as decided 4 November 2026, but the alert's own forecast and the radar still warn on their own |
| 5 | One centre left reads as full agreement | P2 | Confirmed and fixed | With only one centre answering, a GO is held back, said as no agreement to go by |
| 6 | Cloud can still cover a hardware failure; old evidence on lock contention | P1 | Partly fixed | The lock-contention fallback now takes kept evidence only within twice the age asked. A step's own failure reason reaching the runner is still planned (as in 4, re-checked, 5) |
| 7 | No forecast means "no rain" in the alerts | P1 | Confirmed and fixed | A forecast not read, or not reaching the hour ahead, is "not known": it keeps the rain state it had and is said as not known |
| 8 | No physical weather protection | P1 | Agreed, no change | The alerts are to fetch the person; parking is not shelter. The docs already say so (docs/alerts.md); nothing claims unattended weather protection |
| 9 | Sky quality not used to choose between targets | P2 | Agreed and planned | Measured frame quality and forecast seeing as advice between otherwise equal targets, later |

## 14, re-audited at 482fe49

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | A stale radar picture can still start a warning, and is scored as a new look | P1 | Partly right, fixed for the scores | A stale picture is kept out of the forecast scores (`note_seen`). One that shows rain still warns: a rain warning errs on the safe side, and the owner's rule is never to quieten the rain alert (15 Nov 2026) |
| 2 | A stale forecast copy can clear a rain alert | P1 | Confirmed and fixed | `alert.check` takes a stale or unavailable Open-Meteo forecast as not known, so it can never clear the rain state |
| 3 | A failed radar look can slow the watch to its relaxed pace | P1 | Confirmed and fixed | Without a fresh picture (none, an error, or stale) the watch keeps its normal pace; the relaxed one is only for a fresh radar showing nothing near |
| 4 | One-centre coverage judged by the spell's best hour | P2 | Confirmed and fixed | By its weakest hour (`min`) |

## 15. Operational performance, 20 November 2026

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | The patrol's plain GoTo then shoot.py's own | P1 | Smaller than claimed, no change | The second is the plate-solved centring: its `aim()` sends a GoTo to the same place from where the first arrived (so a short or no movement), then corrects it; and the first's refusal or failure stops the patrol before the camera is opened. Removing it changes how the mount moves on every patrol; worth measuring first (2) |
| 2 | No time from asking to a first usable frame | P1 | Agreed; fixed after the loop | `shoot.py` keeps each stage's end in session.json's `stages` (asked, filter, on_target, guiding, camera, first_frame, first_kept), and `./history.py` gives each stage's median and from asking to the first kept frame (measured; none yet, from tonight). The patrol's own GoTo before shoot.py is not in it |
| 3 | A single run's solved re-centre closes the camera without the keeper | P1 | Agreed; fixed after the loop | `shoot.lent_held`: a cooled camera with no keeper is opened once and lent to the run's re-centres and solves, as the blocks have done since 5 Nov; the owner's rig (keeper) and cameras with no cooler unchanged |
| 4 | The patrol budgets with fixed figures beside measured ones | P2 | Agreed; fixed after the loop | `./history.py` keeps every night's costs in `cache/history-costs.json` (14 days fresh; the patrol starts a quiet `--keep` when none is); the patrol plans with the measured frame gap for its exposure and the median gap between sessions when 20 or more are kept, else the fixed figures. Today: 1.7 s and 4.0 minutes against 5.6 s and 2.5 (34 frames in 10 minutes of 16 s, where it was 28). Night replay keeps the fixed figures |
| 5 | A second look says "10 minutes" and may take 15 | P2 | Confirmed and fixed | It says its minutes of exposure and frames, and the most minutes it may take |
| 6 | Two minutes for focus always added to a protected setup | P2 | Agreed; fixed after the loop | `windows.focus_seconds`: none when the last focus is under 6 h old at the window's start; else the median length focus runs now record (`seconds`, 3 or more), else 2 minutes |

## 15, re-audited at f5a1be3

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | The second GoTo's description was incomplete | - | Right | Corrected above: `aim()` sends a GoTo to the same place before measuring the miss. Both agree to keep it until the acquisition timings (2) show its cost |
| 2 | "at most 3 minutes" for 10 minutes asked reads wrongly | P2 | Confirmed and fixed | When the time left is less than the minutes asked, it says how few are available before the next step |

## 16. Network security and external integrations, 20 November 2026

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | Stream keys sent over plain RTMP | P1 | Confirmed and fixed | YouTube and Twitch go to their RTMPS (TLS) ingest points; this ffmpeg has `rtmps`. Twitch is still found by `live.twitch.tv`, so its bandwidth test is unchanged. Not yet tried on a real stream: the next stream is its proof, recorded in docs/validation.md then |
| 2 | Hue bridge's certificate not checked | P1 | Agreed; fixed after the loop | The bridge's certificate (SHA-256) is kept in `cache/hue.json` at pairing, or at the first call for an older pairing, and a bridge showing another is refused before the key is sent; `./alert.py pin` keeps a new one after a reset. No button was needed: the owner's bridge was pinned and its lights listed through the check, and a wrong pin was refused. A refused bridge leaves the speaker speaking |
| 3 | Credential files written with the default permissions | P1 | Confirmed and fixed | `config.save` makes its partial and backup readable by this user only; `records.write(..., private=True)` does the same, used for `cache/hue.json`. Files written before keep their mode until next written |
| 4 | Status server listens on every network | P2 | Confirmed and fixed | `serve.py --bind ADDRESS`; the default stays every network (the LAN page), and the help says to firewall others or give the LAN's address |
| 5 | Alpaca and PHD2 trust the network | P2 | Agreed, no change | Their own protocols have no authentication; addresses are named by the person, never searched. Fixed after the loop: an Alpaca answer is refused past 1 MB, a picture past 1 GB, and an ImageBytes picture whose size does not match its own header |
| 6 | The Compendium download has no size ceiling | P2 | Confirmed and fixed | Refused past 200 MB, and refused when its contents unpack to more than 800 MB; nothing is kept then |
| 7 | MCP and API inputs not bounded | P2 | Confirmed and fixed | An MCP message that is not an object, or whose params are not one, answers "Invalid request"; the API's `limit` is a number from 1 to 500, a bad one the default |
| 8 | Public status kept private by string replacement | P2 | Agreed; fixed after the loop, by field name | `serve.PLACE_FIELDS` (latitude, longitude, elevation, address, skyline ...) are left out of every API answer and of `web/status.json` whatever adds them; the site's name is still blanked. Every route was checked on 20 Nov 2026 and none carries the site's coordinates. A full list of allowed fields for the night's 95 KB answer was not made: it would drop each new field the page needs |

## 16, re-audited at 5fcf92a

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | `--install --bind` installed a service on every network | P1 | Confirmed and fixed | The address goes into the service's command (`unit(..., bind=)`), the default unchanged |
| 2 | `chmod 0600` is not owner-only on Windows | P1 | Right; fixed after the loop | `host.private()`: the mode, and on Windows `icacls` taking the file off its folder's permissions and granting this user alone (untried on Windows). Before that: | On Windows a checkout under the user's own folder is already theirs only by its default permissions; an explicit ACL is planned for a checkout elsewhere. Files written before 5fcf92a keep their mode until next written (the owner's config.toml can be made private by hand: `chmod 600 config.toml`) |
| 3 | A custom plain `rtmp://` address can still carry the key | P2 | Confirmed and fixed | Left out of the stream with the reason said: give its `rtmps://` address |
| 4 | MCP params `[]` and non-object arguments accepted | P2 | Confirmed and fixed | Params must be an object or absent; a tool's arguments must be an object, else "Invalid params". Each tool's own handler still checks its fields |
| - | RTMPS still to be proven on a live stream | - | Agreed | Recorded in docs/validation.md after the next stream |

## 17. Public releases and installation, 20 November 2026

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | Release 0.4.1 lacks the Sun refusal for named GoTos | P0 | Confirmed; release waits for the owner's go | The README now says so beside the download, and to use 0.4.1's GoTo by night only. Release 0.4.2 with the fix, and a note on the 0.4.1 release page, wait for the owner (releases are his) |
| 2 | install.sh does not check for Python 3.11 | P1 | Confirmed and fixed | It stops before installing anything on an older python3, naming Ubuntu 24.04 or Debian 12 as having it. Its comment no longer mentions CI |
| 3 | No upgrade procedure | P1 | Confirmed and fixed (documented) | The README says what to copy from the old folder (`config.toml`, `rigs/`, `cache/`, `calibration/`, `frames/`, `horizon/`, `web/`), to run the installer again for the launchers, and that the old folder is the way back. Separating data from code is planned |
| 4 | A zip of main reports itself as a release | P1 | Confirmed and fixed | `release.py` adds a `RELEASE` file (tag and commit) to the zip; `doctor.py` reports "release TAG (commit)" from it, and a zip without one as having no release record |
| 5 | Windows install leaves out the optional libraries | P2 | Agreed; fixed after the loop | `install.ps1` installs pyproject's `archive` and `wheel` extras (astroquery, hidapi), a failure not fatal and said; sxwheel.py's message names pip on Windows |
| 6 | No record of the library versions proven | P2 | Agreed; fixed after the loop | docs/validation.md, "The software the proofs above ran on": the owner's laptop's versions, older ones unproven |
| 7 | Windows claims need qualifying | P2 | Already so | The README says the camera has taken frames indoors and that the installer, demo launcher, Start Menu entries and window are untried |
| - | A SHA-256 with each zip | - | Agreed; fixed after the loop | `release.py` writes `NAME.zip.sha256`, publishes it beside the zip and puts the sum in the notes |

## 17, re-audited at 1bacb9d

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | The upgrade list leaves out folders of the person's | P1 | Confirmed and fixed | Checked against .gitignore: the README now lists every kept folder in four groups (settings and place, records, the camera makers' libraries, remembered measurements), says to stop everything first, and to leave lock and partial files and the motion lock behind |
| 2 | The 0.4.1 release page should carry the Sun warning | P0 | Agreed; waits for the owner | Editing a published release is the owner's, with 0.4.2 itself |

## 18. Architecture, documentation and maintainability, 20 November 2026

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | AGENTS.md and `ty` say only `ty mount` moves anything | P1 | Confirmed and fixed | Both now name the pass-throughs that drive hardware (`ty mount` motion, `ty shoot`, `ty focus`, `ty moon`, the camera through `ty lucky capture` and `ty collimation`) and make `policy.py` the reference |
| 2 | Dawn flats launched through `sh -c`; a failed launch skips the warm-up | P1 | Confirmed and fixed | The flats then `keeper.py stop` run in turn by Python itself (`python -c`), so Windows runs them too; if they cannot be started, `end()` says so and the camera is still warmed and let go (`release_camera`). `tidy()`'s /proc listing was Linux-only (corrected in the re-check below: it was not harmless) |
| 3 | The end-of-night skill can start the flats twice | P1 | Confirmed and fixed | The skill and owner-rig.md: `schedule.py end` starts them, never a second time; by hand only when the night ended without it or it says they could not be started |
| 4 | Kept JSON written outside records.py | P1 | Confirmed, two fixed | The guide calibration through `records.write` (whole or not at all); a reference's footprint added through `records.change` (under its lock). `focus.keep` is the live view's small file, not a record, and its Windows fallback is there on purpose: left |
| 5 | cloudy-day starts all three research jobs at once | P2 | Confirmed and fixed | A and B at once; C waits for A's batch |
| 6 | Stale statements in the docs | P2 | Confirmed and fixed | Fourteen skills; the skills used at the telescope since; `ty watch-run` built (`runwatch.py`); the simulator in `--demo` (the tests removed 4 November 2026); CLAUDE.md: `ruff check` is the one check |
| 7 | Command tables kept in several places | P2 | Agreed, no change now | The two pass-through tables agree; deriving one from the other planned when a command is next added |
| 8 | Large modules | P2 | Agreed, no refactor | As the audit says: split a responsibility out only when its feature needs work, night-end first |

## 18, re-audited at 6e97677

| # | Finding | Severity | Verdict | What was done |
|---|---|---|---|---|
| 1 | The upgrade note said to leave the motion lock behind | P0 | Right, my mistake, fixed | The README now says to copy the motion lock too: it stops the mount for a reason, and a new folder without it would not. Only `.lock` and `.part` files are left behind |
| 2 | `ty run` and `ty`'s writing views missed | P1 | Confirmed and fixed | `ty` names `ty spot NAME` and `ty research --html` (write here), `--pull` (fetches) and `ty run` (an order for the imaging run, which drives the telescope); AGENTS.md's safe list leaves out `ty run` |
| 3 | `tidy()` finds no watchers on Windows | P1 | Confirmed and fixed | `host.processes()` lists processes on both (/proc; the process table through PowerShell on Windows) and `host.interrupt()` stops them (Ctrl-C on Linux; on Windows, where another console cannot be sent one, it is ended). Untried on Windows |
| 4 | A second `schedule.py end` could start the flats twice | P2 | Confirmed and fixed | The waiting flats' process is kept in `cache/dawn-flats.pid`; while it runs, another end says they are already waiting and starts none |

