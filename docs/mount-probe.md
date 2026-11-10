# Mount probe: the slack and flex across the sky (plan)

Status: a plan, not built. Written 10 November 2026 after a night when the
guider could not hold Dec on the Soul Nebula; revised the same night after
review: built and run in three stages, the first passive.

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
  guide scope flexing against the main tube. That is a hypothesis, not a
  diagnosis: centroid noise at 9.55"/px, drift, refraction and real
  movement of the guide scope's mounting could each give it, and only
  measuring both cameras at once can tell.
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

## Stages

Each stage is built, run and read before the next is built.

### Stage 1: passive, one position (about 10 minutes)

Where guiding failed: the Soul (Dec about +59, east of the pier), or the
nearest bright star in a sparse field there.

1. GoTo with a plate solve to centre, through the project's own GoTo (dry
   run, motion lock, limits).
2. No pulses at all for 8 minutes. The guide camera follows the star every
   2 s; the main camera takes a short frame in L every 30 s and plate-solves
   it (L: solves through Ha failed all night; the frame's mid-exposure time
   recorded with it). Both give a track of position against time.
3. From the two tracks: the drift rate and direction each camera sees, and
   their difference. Drift the same in both is the mount; a difference that
   grows is the guide scope moving against the main tube (flex); scatter in
   the guide track alone is centroid noise.

Nothing is changed in the guider or the controller. Afterwards, guiding
resumes one-way in the direction stage 1 shows the drift needs.

### Stage 2: the slack, measured, one position (about 6 minutes)

Only once stage 1 has run. Dec north in steps of at most 1.5 s (the
calibration's own step; the guider's limit is 2.5 s a pulse, 3 s in
calibration) until the star moves, then reversals made of such steps,
counted up to 24 s of pulses in all, until the star clearly moves back;
each way, three times. RA the same, west and east. Gives the slack in
seconds and arcseconds with no cap below 24 s, and its spread over the
three tries.

It ends by stepping Dec the way guiding will push until the star moves,
so the gears are left against the side guiding uses (a known state), and
the guider's own calibration check runs before guiding resumes.

### Stage 3: across the sky, only if stages 1-2 show it matters

The same at up to six positions, a bright star in a sparse field at each:

| # | Side | Where | Why |
|---|---|---|---|
| 1 | east | high, Dec about +60 | where guiding failed on 10 November |
| 2 | east | about 40° up, Dec about +20 | Dec loaded by the tube's weight |
| 3 | east | near the meridian, Dec about 0 | where guiding is normally calibrated |
| 4 | west | near the meridian, Dec about 0 | the same place, the other side |
| 5 | west | about 40° up, Dec about +20 | |
| 6 | west | high, Dec about +60 | |

About 1 min to centre, 8 min passive, 6 min slack and 5 min calibration:
20 minutes a position before overheads, so two hours for six. Each
position stands alone and runs on a night given to it, never in place of
an imaging night.

## When a result counts

- Each figure is from three tries at least, and given with its spread.
- A drift direction counts when the drift is larger than twice its own
  spread in both stage 1 tracks; only then may one-way Dec guiding choose
  its direction from it, and only for that side and part of the sky.
- Flex counts when the difference between the two tracks grows by more
  than one guide pixel (9.55") over the 8 minutes and repeats on a second
  run.

## Built as

- A project command, `./mountprobe.py` (CLAUDE.md: anything new for the
  telescope is a command before its first use), with `--dry-run`,
  `--stage 1|2`, `--position N`, and a `--json` output with its schema in
  `schemas/`. Stage 2 and 3 code is written only after stage 1 has run.
- It moves the mount only through the project's GoTo; otherwise only ST4
  pulses through the guide camera, at most 1.5 s each, with the motion
  check before each.
- It reuses: the GoTo with a plate solve, the guider's star finding and
  pulses (guider.Calibrator), and the drift measurement (still_drift).
- The main camera is borrowed from the keeper like any frame; nothing new
  for the cooler.
- Records: each run's figures to docs/nights/DATE/mount-probe.md and the
  raw tracks beside the guide logs; `./guidelog.py` gains the slack in
  arcseconds.

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
