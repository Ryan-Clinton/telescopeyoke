---
name: discovery-night
description: Plan and run a night hunting for novae and other new transients, with Tabby's star and exoplanet transits fitted in. Use when the person asks for tonight's outlook or plan, asks what to do tonight, asks to patrol M31 or M33, look for novae, or run a discovery night.
compatibility: telescopeyoke at the telescope, set up and focused (nightly-setup), with a reference for each field or a first night to make one
allowed-tools: Bash(./ty night) Bash(./ty night --json) Bash(./patrol.py * --plan) Bash(./starwatch.py * --plan) Bash(./ty candidates *) Bash(./ty watch-run --once)
---

# Discovery night

The night is `docs/discovery.md`, "Running a discovery night"; the patrol
is `docs/agents/setup-routine.md` step 6b.

0. Asked for the outlook or tonight's plan ("how's tonight looking"): run
   `./ty night` once (3 seconds) and answer from it straight away. That is
   the whole job: no patrol or starwatch plans, no reading docs or code, no
   other commands. The patrol plans only mean anything once it is dark;
   they belong to setup, step 1. Never fix or change code while answering:
   if something is broken, say so in a line at the end. Answer in this
   shape, nothing more:
   - One line: the verdict, the clear spell, when the Moon sets, the dew.
   - One line per `discovery` item, in its order: the programme, its
     `best_in_clear` time ("go about"), its length. One marked NOT up
     while clear is said once as skipped tonight.
   - One line: the free time after the programmes, for a big target.
   - Only if `skyline_measured` is false: one line saying so.

1. `./patrol.py m31-panels --plan` (or `m31-novae`, `m33-novae`): read it
   out. Anything marked NO is said once; the focus line comes before going
   on. A panel's first good night becomes its reference by itself.
2. On their go: `./patrol.py m31-panels` in the background. Say it has
   started, then each panel's result; never a line per frame or per plate
   solve. Tell them at once only if frames stop being kept
   (`./ty watch-run --once` to check). The patrol moves the mount only through the project's
   own GoTo and imaging, with their checks.
3. When asked, or when the plan says it is due: `./starwatch.py tabby
   --plan`, then `./starwatch.py tabby` (a 10-minute look); `./transits.py`
   lists whole transits tonight, and one is taken only if they ask.
4. Each panel's answer: how deep it reached and how many candidates are
   unexplained. Show each `patrol-N.png` before calling anything a find.
   An unexplained candidate also goes to the person's phone by itself,
   and the patrol takes a second look at once.
5. For a candidate: `catalogue-researcher` with its place, then
   `candidate-vetter`. A claim is `/claim ID`, the person's to start.
6. At the end: `./patrol.py --sweep` searches anything not yet searched.

A candidate is only interesting once `./ty candidates` shows it seen on
more than one night.
