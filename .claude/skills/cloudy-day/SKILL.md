---
name: cloudy-day
description: Do the useful things that need no clear sky. Use when the person says it is cloudy, it is daytime, or asks what can be done today.
compatibility: telescopeyoke with the internet; the desktop reachable for heavy work
allowed-tools: Bash(./ty candidates *) Bash(./ty characterise *) Bash(./ty agent-report *) Bash(systemctl --user list-timers *)
---

# A cloudy day

Offer, in a few lines, whichever of these apply now:

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
