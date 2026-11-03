---
name: cloudy-day
description: Do the useful things that need no clear sky. Use when the person says it is cloudy, it is daytime, or asks what can be done today.
compatibility: telescopeyoke with the internet; the desktop reachable for heavy work
allowed-tools: Bash(./ty candidates *) Bash(./ty characterise *) Bash(./ty agent-report *) Bash(systemctl --user list-timers *)
---

# A cloudy day

A cloudy day is research time: the telescope is not the only instrument.
Start these at once, each in the background, without offering them, and
say each result when it lands (docs/discovery.md step 9, docs/seti.md,
docs/archive.md):

A. **Kepler's archive:** `./archive.py screen --batch 200` (on the
   desktop for big batches) carries the screen of Kepler's stars on from
   where it stopped and ranks every star screened by how Tabby-like its
   dips are. Say the new top few, each with what the checks say (periodic,
   at an edge, only in one of SAP and PDCSAP), and look each one up
   (`catalogue-researcher`) before calling it strange.
B. **Radio SETI:** `./seti.py sweep KIC8462852 --blocks 3` carries the
   search of Tabby's star's Green Bank cadence on, one 2.9 MHz block at a
   time, from where it stopped. Say how much of the band is done and any
   candidate, with the note that a candidate is ours until checked
   against known interference and the published searches.
C. **Papers:** `./literature.py --unread`. Read each abstract on Tabby's
   star, dipping stars and SETI, and say in a line what it claims, how
   sure it is (the paper's own words: sigma, "tentative", "confirmed")
   and what it means for the programmes (a new window goes into the
   programme's `[[watch]]`, with its source). Then mark them read
   (`./literature.py --read ID...`).

Then, in a few lines, whichever of these apply now:

1. **Comets:** the hunt runs by itself every 6 hours (`systemctl --user
   list-timers ty-sungrazer.timer`); its newest finds are in `./ty
   candidates` as `comets`. Anything heading for the Sun goes to
   `comet-checker`.
2. **Public transients:** `./brokers.py` for tonight's worth a look,
   `--unreported` for the last month's bright ones nobody has reported.
3. **Old nights again:** after any change to the search, `./patrol.py
   --sweep --all-history`.
4. **Stacks:** heavy restacks on the desktop (`./restack.py SESSION --on
   desktop`), in the background.
5. **Candidates:** open ones in `./ty candidates`, each through
   `catalogue-researcher` and `candidate-vetter`.
6. **Measurements still missing:** `./ty characterise` lists them and
   which need a clear night.
7. **The tests:** `./ty test-run` in the background.

Then say which needs clear sky next, so tonight's plan is ready.
