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
| 7 | Scientific discovery reliability | not started |
| 8 | Calibration and scientific measurement accuracy | not started |
| 9 | Demo claims versus real-world proof | not started |
| 10 | Hardware onboarding and compatibility | not started |
| 11 | NINA/PHD2 companion | not started |
| 12 | State management and data integrity | not started |
| 13 | Observing scheduler and scientific yield | not started |
| 14 | Weather and environmental decisions | not started |
| 15 | Operational performance | not started |
| 16 | Network security and external integrations | not started |
| 17 | Public releases and installation | not started |
| 18 | Architecture, documentation and maintainability | not started |

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

