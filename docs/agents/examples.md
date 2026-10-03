# Worked examples

**"What should I image tonight?"**
1. `ty night --json` for the verdict and clear window.
2. `ty targets --now --limit 5 --json`.
3. Explain the top choices using their `tags`; mention the clear window.

**"Point at M27."**
1. `ty mount goto M27 --dry-run --json`.
2. Report the altitude, side of the mount and any warning (for example "the
   tube will swing over the pole").
3. If the person has asked for the move, run `ty mount goto M27 --solve`.
   If they only asked whether it is possible, stop at step 2.
4. Afterwards `ty mount status --json` to confirm it is tracking.

**"Why are the pictures poor?"**
1. `ty session --frames 60 --json`.
2. Look at `reasons` (cloud, trailing, bloated stars) and the trend in FWHM,
   roundness and star count.
3. `ty night --json` for cloud and wind at that hour.
4. Say which it is: cloud (stars dimmer or fewer), focus (FWHM rising with
   star count steady), wind or a knock (roundness falling).

**"Is the telescope ready?"**
1. `ty capabilities --json`.
2. For anything with `available: false`, quote that component's `message`.

**A refusal**
`ty mount goto M31 --dry-run --json` returning
`TARGET_BELOW_ALTITUDE_LIMIT`: say so, give the altitude, and offer
`ty target M31` to see when it rises. Do not look for a way round the limit.

**The mount is locked**
`capabilities.motion.locked` is true: report `lock_reason` and stop. Removing
the lock is the person's decision.
