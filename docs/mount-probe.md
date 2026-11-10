# Mount probe: the slack and flex across the sky (plan)

Status: a plan, not built. Written 10 November 2026 after a night when the
guider could not hold Dec on the Soul Nebula.

## Why

On 10 November 2026 (docs/nights/2026-11-10/guiding.md):

- Every guider calibration measured about 11 s of Dec slack (10.7-11.7 s,
  "at least": a reversal moved nothing, so the true figure may be longer).
  At the Dec guide rate of about 8"/s that is about 90" of play.
- Guiding Dec both ways on the Soul (IC 1848, Dec +59, east of the pier,
  74° up), Dec reversed 10 times in 11 minutes, Dec RMS was 10.2" and every
  120 s frame was trailed (FWHM 9.7-14.5 px).
- Guiding Dec south only (`shoot --guide --dec-one-way south`), 3 of 4
  frames were round (roundness 0.74-0.89), but the guide star still wandered
  from +11" to -21" in Dec: north and south, with only south pulses sent.
  A slow ~9" Dec wander with mostly round main-camera stars suggests the
  guide scope flexing against the main tube.
- West and east RA rates differed by side: 0.82/0.65 px/s west of the pier
  (Vega, Veil) and 0.76/0.82 east (Alpheratz, drift taken off).
- The camera end of the tube is the heavy end (known). Gary: imbalance is
  not a big problem on this mount.

The guide logs alone cannot separate Dec slack from guide-scope flex, or say
whether either changes with where the scope points.

## Questions

1. Dec slack: how many seconds (and arcseconds) before Dec moves after a
   reversal, each way; does it change with position, pier side or altitude?
2. RA: are west and east equally strong everywhere; is there RA slack?
3. Flex: does the guide scope move against the main tube?
4. Drift: how fast and which way the star drifts unguided at each position
   (polar alignment error, ~1.7° tonight), which also tells one-way Dec
   guiding which way to push.

## Positions

Six, a bright star in a sparse field at each, chosen on the night from what
is up:

| # | Side | Where | Why |
|---|---|---|---|
| 1 | east | high, Dec about +60 | where guiding failed on 10 November |
| 2 | east | about 40° up, Dec about +20 | Dec loaded by the tube's weight |
| 3 | east | near the meridian, Dec about 0 | where guiding is normally calibrated |
| 4 | west | near the meridian, Dec about 0 | the same place, the other side |
| 5 | west | about 40° up, Dec about +20 | |
| 6 | west | high, Dec about +60 | |

Each position stands alone: the probe can run in parts across gaps in cloud.

## At each position (about 12 minutes)

1. GoTo with a plate solve to centre (about 1 min), through the project's
   own GoTo (dry run, motion lock, limits).
2. Unguided drift, 4 minutes: the guide camera follows the star every 2 s
   and the main camera plate-solves every 30 s, with no pulses. Gives the
   drift rate and direction. Comparing the two: if the guide star moves and
   the main camera's centre does not (or the other way), that is flex.
3. Slack, about 4 minutes: Dec north until the star moves, then reversals
   of growing length (2, 4, 8, 16, 24 s) until it clearly moves back, each
   way, three times; RA the same, west and east. Gives the slack in seconds
   and arcseconds with no cap below 24 s.
4. The usual guider calibration (about 5 min), with the drift taken off:
   axes angle, rates and the calibration's own slack figure, to compare.

About 75 minutes for all six.

## Built as

- A project command, `./mountprobe.py` (CLAUDE.md: anything new for the
  telescope is a command before its first use), with `--dry-run` and
  `--position N`, and a `--json` output with its schema in `schemas/`.
- It moves the mount only through the project's GoTo; otherwise only ST4
  pulses through the guide camera, with the motion check before each.
- It reuses: the GoTo with a plate solve, the guider's star finding and
  pulses (guider.Calibrator), and the drift measurement (still_drift).
- The main camera is borrowed from the keeper like any frame; nothing new
  for the cooler.
- Records: each position's figures to docs/nights/DATE/mount-probe.md and
  the raw readings beside the guide logs; `./guidelog.py` gains the slack
  in arcseconds.

## What the results decide

- Slack large everywhere: the Dec worm mesh needs adjusting (in daylight;
  how on the EQ3 Pro to be checked first). The probe run again afterwards
  measures the change.
- Slack that changes with position: a loading question; choose sides and
  parts of the sky to suit, and give guiding that.
- Flex found: tighten the guide scope's rings and shoe, then the drift step
  alone again.
- The drift's direction at each position: one-way Dec guiding can choose
  its direction by itself.

## Not in this plan

- Periodic error of the RA worm (about a 10-minute cycle): a long guiding
  run analysed by `./guidelog.py` is the better tool.
- Changing guiding settings: nothing here changes the guider's settings.
