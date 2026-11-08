---
name: cloudy-day
description: Do the useful things that need no clear sky. Use when the person says it is cloudy, it is daytime, or asks what can be done today.
compatibility: telescopeyoke with the internet; the desktop reachable for heavy work
allowed-tools: Bash(./ty candidates *) Bash(./ty characterise *) Bash(./ty agent-report *) Bash(systemctl --user list-timers *)
---

# A cloudy day

A cloudy day is research time: the telescope is not the only instrument.
Start these at once, each in the background, without offering them, and
say each result when it lands (docs/discovery.md, docs/archive.md):

A. **Kepler's archive:** `./archive.py screen --batch 200` (on the
   desktop for big batches) carries the screen of Kepler's stars on from
   where it stopped and ranks every star screened by how Tabby-like its
   dips are. Say the new top few, each with what the checks say (periodic,
   at an edge, only in one of SAP and PDCSAP), and look each one up
   (`catalogue-researcher`) before calling it strange.
B. **Papers:** `./literature.py --unread`. Read each abstract on Tabby's
   star and dipping stars, and say in a line what it claims, how
   sure it is (the paper's own words: sigma, "tentative", "confirmed")
   and what it means for the programmes (a new window goes into the
   programme's `[[watch]]`, with its source). Then mark them read
   (`./literature.py --read ID...`).
C. **Investigate:** `./investigate.py`, after A's batch has landed so its
   new leads are in the queue (it picks itself: a lead with a check
   unanswered first, then the top new one; run it again while `./ty
   research` shows any waiting or to ask again). Say its verdict
   (explained, likely explained, artefact, unexplained weak or strong) and why, "likely" with what is missing, whether it is known to science
   already, and whether this telescope can watch it; the report is
   `docs/research/LEAD.md`. An "unexplained" lead goes to
   `catalogue-researcher` before anything is called new. `./ty research`
   says how much of each survey is done and what is waiting.

Then, in a few lines, whichever of these apply now:

1. **Public transients:** `./brokers.py` for tonight's worth a look,
   `--unreported` for the last month's bright ones nobody has reported.
2. **Old nights again:** after any change to the search, `./patrol.py
   --sweep --all-history`.
3. **Stacks:** heavy restacks on the desktop (`./restack.py SESSION --on
   desktop`), in the background.
4. **Candidates:** open ones in `./ty candidates`, each through
   `catalogue-researcher` and `candidate-vetter`.
6. **Measurements still missing:** `./ty characterise` lists them and
   which need a clear night.

Then say which needs clear sky next, so tonight's plan is ready.
