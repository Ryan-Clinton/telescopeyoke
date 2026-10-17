---
name: discovery-night
description: Run a night hunting for novae and other new transients, with Tabby's star and exoplanet transits fitted in. Use when the person asks to patrol M31 or M33, look for novae, or run a discovery night.
compatibility: telescopeyoke at the telescope, set up and focused (nightly-setup), with a reference for each field or a first night to make one
allowed-tools: Bash(./patrol.py * --plan) Bash(./starwatch.py * --plan) Bash(./ty candidates *) Bash(./ty watch-run --once)
---

# Discovery night

The night is `docs/discovery.md`, "Running a discovery night"; the patrol
is `docs/agents/setup-routine.md` step 6b.

1. `./patrol.py m31-panels --plan` (or `m31-novae`, `m33-novae`): read it
   out. Anything marked NO is said once; the focus line comes before going
   on. A panel's first good night becomes its reference by itself.
2. On their go: `./patrol.py m31-panels` in the background, and `./ty
   watch-run` as a Monitor on each panel's run, telling the person each
   line it prints. The patrol moves the mount only through the project's
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
