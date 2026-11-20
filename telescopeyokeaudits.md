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
| 1 | Mount safety and movement | not started |
| 2 | Hardware failure and recovery | not started |
| 3 | AI agent autonomy and permissions | not started |
| 4 | Autonomous full-night operation | not started |
| 5 | Guiding and calibration | not started |
| 6 | Camera, cooling, filters and focusing | not started |
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
