# Confirmation results

Against the protocol fixed in `confirmation-protocol.md`; every deviation is in `deviations.md`.

## Step 1: hot-pixel and cosmic-ray cleaning, set 76 (QHY Minicam8M, 2.9 um, 348 mm, 600 s)

The protocol's run, stacked as `restack.py` stacks (binned 2x2, as `processing_scale = 2`):

| Session | Brightest-third flux, new / old cleaning | Peak, new | Grain, new | Visible cosmic pixels, new / old | Verdict |
|---|---|---|---|---|---|
| Ha, 10 October 2025 | 0.574 / 0.301 | 0.304 | 0.995 | 10 / 1 | **fail** (flux, peak) |
| Ha, 2 November 2025 | 0.911 | 0.875 | 0.987 | 120 / 179 | **fail** (flux, peak, grain) |
| OIII, 10 October 2025 | 0.171 | 0.168 | 0.996 | 2 / 2 | **fail** (flux, peak) |
| OIII, 29 October 2025 | 0.936 | 0.867 | 0.969 | 56 / 51 | **fail** (flux, peak, grain) |

**All four fail.** The old cleaning cut the stars further on every session where both were measured.

A diagnosis afterwards, not a verdict: the same first-night sessions at full resolution (no 2x2
binning). Binned, this camera's 1.72"/px becomes 3.44"/px and its stars' median width 1.8 px, so a
core is one pixel and both cleanings take it for a defect. Unbinned (median width 3.6 to 6.3 px):

| Session | Brightest-third flux, new / old | Peak, new / old | Verdict by the same mark |
|---|---|---|---|
| Ha, 10 October 2025 | 0.984 / 0.650 | 0.941 / 0.426 | would fail (flux, peak) |
| OIII, 10 October 2025 | 1.000 / 1.000 | 1.000 / 1.000 | would pass |

So most of the loss is the binning: the cleaning was made on this project's 183M at 750 mm, whose
binned stars are 2 to 3 px wide. On a rig whose binned stars are near 2 px, `processing_scale = 2`
undersamples them and the cleaning cuts their cores; even unbinned, the new cleaning took 1.6% of
the Ha stars' light, outside the 0.5% the mark allows. Nothing in the code is changed for this
here: a rig with fine pixels and short focus is the case to fix next, and the fix is checked on data
not yet read.

## Step 4: field widths, decided before any picture is made (25 November 2026)

From each stack's own header (plate solve, or focal length and pixel size), or the owner's stated
focal length where the header has neither. Wider than 3 degrees gets `--background level`.

| Set | Scale ("/px) | Field (deg) | Background |
|---|---|---|---|
| 07, 18 (2600MC at 363 mm, drizzled) | 1.01, 2.01 | 3.5 | level |
| 40 (D5500, 70 mm) | 11.6 | 15.6 | level |
| 44 (Bortle 8) | 3.67 | 3.9 | level |
| 72 (R50, Askar 80ED with 0.7x, stated) | about 1.8 | about 3.1 | level |
| 29, 31, 37, 74 (533MC, 400 to 750 mm) | 0.55 to 1.1 | 0.9 to 1.7 | auto |
| 28 (8" Dobson, 1200 mm, stated) | about 0.6 | about 0.5 | auto |

The rest, from their XISF headers or the owners' stated rigs (their TIFFs are not read by Pillow):

| Set | Scale ("/px) | Field (deg) | Background |
|---|---|---|---|
| 43 (533MC, RedCat 51, 2x drizzle, 10350 px) | about 1.55 | about 4.5 | level |
| 49 (2600MC at 370 mm) | 2.1 | 3.6 | level |
| 56 (D750 at 360 mm, stated) | about 3.4 | about 5.7 | level |
| 57 (D5300 at 300 mm, stated) | about 2.7 | about 4.5 | level |
| 65 (D7000 on a Z73 at 440 mm, 2x drizzle, stated) | about 1.1 | about 3.1 | level |
| 41 (2600MC on a 90 mm at 540 mm, stated) | about 1.4 | about 2.5 | auto |
| 78 (533MC at 249 mm) | 3.1 | 2.6 | auto |

## Step 1 on a colour camera (raw 2600MC Pro at 1000 mm, Bortle 2, no darks)

| Session | Brightest-third flux, new / old cleaning | Peak, new / old | Stack star width (px) | Verdict |
|---|---|---|---|---|
| Abell 1656 | 0.943 / 0.573 | 0.819 / 0.361 | 3.47 | **fail** (flux, peak) |
| LBN 552 | 0.970 / 0.498 | 0.926 / 0.364 | 3.12 | **fail** (flux, peak, cosmic) |
| M81 | 0.997 / 0.673 | 0.978 / 0.470 | 3.65 | **fail** (peak) |
| NGC 7293 | 1.000 / 0.738 | 1.000 / 0.542 | 3.71 | **pass** |

Three of four fail. The losses are real: leaving out every measured star whose centre is a lone
spike in the uncleaned stack (deviations 5 and 6) left out none, so the measured stars are stars, not
the sensor's hot pixels. **The cause is not found.** Undersampled single frames were the first guess, and they do not fit:
measured in single frames (median width of the stars found, px at the stacking scale), this
project's sessions run 2.5 to 4.9 and all pass, M33's R at 2.5 among them; set 76's run 2.7 to 3.6
and all fail, its OIII of 10 October at 3.6 losing 83%; the colour camera's run 3.2 to 4.1, M81 at
4.1 failing. So frame width does not separate passes from fails. What both other cameras' data has
and this project's does not is no dark frame; whether that, the flats, or something in the frames
themselves is the cause is the next thing measured, pixel by pixel in single frames.
This project's 183M at 750 mm (1.3"/px binned) passed all 11 of its sessions.

## Step 4: artefacts in the 17 pictures (colour.py's defaults, read by eye on 25 November 2026)

Every run ended with exit 0. Each picture was looked at whole for tiles, edges, rings and gradients.

| Set | Verdict | What is wrong |
|---|---|---|
| 07, 18, 29, 37, 40, 43, 49, 56, 74 | **pass** | nothing seen |
| 78 | **pass** (no artefact) | M42's core burnt out: needs HDR, a known gap |
| 31, 44 | pass, just | a thin red line down the left edge; 44 also a lighter band along the top |
| 28 | **fail** | the stack's footprint left in: dark wedges at the four corners, a green gradient along the bottom |
| 41 | **fail** | a purple gradient in the bottom-right corner, and an arc along the bottom edge (the Foraxx stretch of the same stacks has neither) |
| 57 | **fail** | a diagonal band down the left third, and an orange glow in the bottom-right corner |
| 65 | **fail** | a strip along the top with another background level from the rest |
| 72 | **fail** | dark round holes in the sky (two plainly, more faintly), and the Rosette hardly shows |

Five of 17 fail, all at the edges or in the background (28, 41, 57, 65, and 72's holes round what may be
dust motes) rather than the colour or the stars. Two paths, not one sky model: 41 and 65 went through the
narrowband mix and its sky model; 28, 57 and 72 are LRGB, whose background is `process.process`'s (and
`--background level` did nothing there: deviation of 26 November). Next: the sky model's edge handling and
what it does with a stack whose frames did not all cover the field.

What the data's owners said, recorded beside the verdicts and not changing them: 28's poster had "trouble
with the corners"; 57 is 3000 untracked frames of 0.6 s, so the field turned and the stack's footprint is a
turned shape; 72 has darks but no flats, and its poster names dust spots. 41 and 65 have no such note
(65 is a 2x drizzle stacked in DSS without a plate solution). So for 28 and 57 the question is the pipeline
not knowing a stack's valid footprint when it models the sky (to be measured: the footprint found and left
out of the background, the finished picture cropped). 72's holes are dust that no flat took off: a fault in the
input, and still a failure of the pipeline in what it says, since the picture is handed over as though it were sound.

### The stack's rejection is not the cause (clipmean, 25 November 2026)

Diagnostic, not a verdict: Abell 1656's 40 frames with each layer a plain mean (no rejection). The new
cleaning against none: brightest-third flux 0.945, peak 0.819, the same as through the clipped stack
(0.943, 0.819). So the light is lost before stacking, in each frame's cleaning as the harness applies it,
although the shipped rule alone touches only 9 pixels in a frame's 60 brightest stars. Next: one frame cleaned
and not, star by star, through the harness's own per-frame path (`clip3.frame`).

Found on the way: the harness keeps colour frames as float16, as `stacking.store_dtype` does, and 1,100
pixels per plane passed float16's 65504 and became inf (saturated stars over their flat). The plain mean
spread them until the stars could not be measured. The shipped store had the same hole; `register_file` now
keeps such a pixel at 65504. Not yet seen in a real restack.

### The rule, not the defect map, and only on some frames (cleanparts, 25 November 2026)

Diagnostic, not a verdict: five single frames of Abell 1656 (every eighth), each part of the cleaning
against the frame uncleaned, brightest-third stars. The defect map (2,893 pixels, 22 to 28 of them on
stars) takes nothing in any frame. The lone-pixel rule takes nothing in four frames and, in light-0008,
17% of the flux and 35% of the peak. So the stack's loss is the rule on a few frames, the brightest stars'
cores taken for lone spikes there. Next: what light-0008 has that the others do not (its star width first:
the sharpest frames are where a core is most nearly one pixel).

### Cause found: the lone-pixel rule takes star cores in the sharpest frames (cleanwidth, 25 November 2026)

Every one of Abell 1656's 40 frames, the rule alone against the frame uncleaned (brightest-third stars),
beside the frame's median star width in the green plane:

| Frames | Median width (px) | Flux kept | Peak kept |
|---|---|---|---|
| 12 that lose light | 3.22 (3.16 to 3.31) | 0.81 to 0.90 | 0.63 to 0.98 |
| 28 that lose nothing | 3.40 (3.22 to 3.72) | 1.000 | 1.000 |

Every frame at 3.25 px or less loses 10 to 19% of its brightest stars' light but one (light-0026, 3.22);
from 3.3 px up only light-0006 (3.31) loses any. The sky does not separate them (385 against 381). So
across sessions width did not sort passes from fails, but within one session it does: in a frame sharp
enough, the brightest stars' cores are narrow enough for the third-brightest-neighbour test to take them
for lone hits. The owner's 183M frames are wider at the stacking scale and never reach it. This is a fault
in the shipped rule (`stacking.clean`), not in the harness; counted, not fixed, as the protocol says. A fix
to try on unread data: leave any pixel at the peak of a star `find_stars` found, or scale the 40% with the
frame's measured width.

## Step 2: star removal on the shared sets (25 to 26 November 2026)

Every filter's stack of the 17 sets (53 stacks, `ds_real.py`, deviation 8), GraXpert's denoise then Dark Star
blended, against our star removal after the same denoise (`stars_chain.py`, `TY_ONE_MODE`).

**Pass on all 53**: the planted faint line is kept to within 5 points of ours in every stack (Dark Star
median 99.9%, lowest 70.8%; ours median 15.8%). Stars left, median: 0.2% against ours 1.1%; brightest 20:
0.8% against 5.6%.

Not part of the rule, and to look at in the pictures before Dark Star is trusted everywhere: in 7 stacks it
leaves its worst tenth of stars whole or nearly (D18 Ha, D31 B/G/L at 40 to 65%, D74 Ha and OIII, D78 Ha),
where ours leaves 17 to 74%. **On D74 Ha (the Tarantula) it removed no stars at all** (stars left 100%,
ours 28%). Crowded or bright-nebula fields, all of them.

Added after these results, and reported beside them rather than changing them: star removal also has to
remove stars. Against our own removal, more than 10 points more left by Dark Star blended: of all stars, 1 of
53 stacks (D74 Ha); of its worst tenth, 7 (the ones above). Production's LRGB path runs no star removal; the
36 broadband stacks here test Dark Star on
broadband data, not what an LRGB picture gets today.

### A candidate fix, first look (development data, 26 November 2026)

Diagnostic, not a verdict: the shipped lone-pixel rule with each found star's centre (3 by 3, from
`find_stars` on the frame) left alone (`cleanstar.py`, `starspare.py`), on all 40 Abell 1656 frames. The 12
frames that lost 10 to 19% under the shipped rule lose nothing (flux and peak 1.000), and no frame loses any.
It replaces about a third fewer pixels (median 720 against 1,104 a frame), so it may also spare some real hits:
the full pass mark, cosmic rays and fixed defects counted, runs next on the owner's 11 sessions, the four raw
2600MC sessions and set 76. Only if it passes all three is it judged once on the frozen raw sessions.

### Why a sharp core passes for a hit, and two candidates that failed (26 November 2026)

Sparing found stars' centres (candidate 1) kept every star's light on the owner's sessions but left 4,300 to
5,400 visible cosmic-ray pixels in each (the shipped rule 0 to 22): `find_stars` finds hits as well as stars.
Sparing only stars at least 70% of the frame's usual width (candidate 2) still left 5,056 and 2,584 on M33 L and
NGC 2174 OIII. Both fail and stay recorded as failures; neither went further.

`corelook.py` printed the replaced pixels in light-0008's brightest stars: 27 of the 60 brightest lost their
peak. A typical one, above the background: peak 66,505, neighbours 41,243, 20,462, 19,544 and less. The second
neighbour is over half the peak, but the third only 31%, under the rule's 40%, so the peak is taken for a hit
on a star's wing. Candidate 3 keeps the 40% where the second neighbour is under half the pixel's height (a lone
hit, or a pair) and asks only 20% where it is over half (a core); first on M33 L, NGC 2174 OIII and the 40
Abell 1656 frames.

Candidates 3 to 5 (development data; the shipped rule's own counts: M33 L 3 visible cosmic pixels, NGC 2174
OIII 0, pass at the shipped count plus 10; every star's light kept in both by all three):

| Candidate | M33 L cosmic | NGC 2174 OIII cosmic | Abell 1656 frames losing light |
|---|---|---|---|
| 3: third neighbour need reach only 20% where the brightest-but-one is over half the height | 9, pass | 3, pass | 1 of 40 (light-0011, flux 0.838) |
| 4: a core (second neighbour 25%+, third 15%+) is left | 19, **fail** | 9, pass | none in the first 18 |
| 5: as 4 at 30% and 25% | 16, **fail** | 4, pass | not run |

Candidate 3's leftover in light-0011 (`corelook_t.py`): cores with only one neighbour over half the peak (54,539
peak; 36,822, 21,682, 20,236). Candidates 4 and 5 spare those, but also some hits on M33 L's star wings. Candidate
6 uses 4's core test only in a frame whose stars' median width is 3.35 px or less, where the shipped rule was
seen to take cores; a wider frame is cleaned exactly as shipped.

## Step 3: stretch on the shared sets (25 to 26 November 2026)

The 53 stacks of step 2 (`ds_stretch.py`, deviation 8: regions from the stack itself, the lines planted before
GraXpert), each tool at its default sky level. Medians:

| Method | Faint lines over grain | Line height | Grain | Bright detail | Burnt white |
|---|---|---|---|---|---|
| **Ours** (`process.display`) | 10.1 | 0.037 | 0.0034 | 0.0084 | 0.006% |
| Siril 1.4.5 autostretch | 5.4 | 0.062 | 0.0116 | 0.0130 | 0.016% |
| Siril 1.4.5 autoghs | 5.7 | 0.004 | 0.0023 | 0.0052 | 0.005% |
| Seti Astro Suite Pro statistical stretch | 5.4 | 0.063 | 0.0119 | 0.0138 | 0.020% |

**None passes; ours stays**, as on the owner's ten held-out pairs (`docs/free-tools-plan.md`, Stretch): ours
shows the faint lines higher over the grain in all 53 stacks. Siril's autostretch and the suite's stretch keep
more bright detail (about 1.6 times ours) and burn a little more white; autoghs keeps less of both. The same
caution as before: ours puts the sky at black, the tools at 0.25, and the rule measures in the faint nebula.

### Where the stacks' frames did not reach (noisemap, 26 November 2026)

Diagnostic, not a verdict, for step 4's edge failures. D28 and D57 have no empty (zero or NaN) pixels, so the
pipeline's present test for a stack's edge (`process.remove_sky` leaves out exact zeros; `colour.combine` crops to
the finite rows and columns) finds nothing to leave out. The areas fewer frames reached show instead in the
grain: in 32 px blocks against the stack's usual grain, D28's frames make a turned square with its four corners
outside it (5% of the blocks over twice the usual grain), D57's untracked frames a diagonal band down the left
(13%), D65's a strip along the top (2%). D41, D18 and D29 have none (D72: 1%, round its dust). So the footprint can
be found from the stack alone; next, as a candidate on development data: leave the thinly covered blocks out of the
sky fit and crop the finished picture to the well covered rectangle, then judge on the frozen stacks.

**Candidate 6 on the owner's 11 sessions** (full pass mark, 26 November 2026): **all 11 pass**. Every star's light,
peak and grain kept (flux 0.9998 or better); visible cosmic-ray pixels 0 to 23, at most 6 above the shipped rule's
(M33 L 9 against 3), inside its plus 10; fixed defects left no worse. On the 40 Abell 1656 frames it keeps every
star's light. Next, on development data still: the four raw 2600MC sessions and set 76; then once on the frozen.

**Candidate 6 fails on development data, and stays recorded as a failure.** Abell 1656 stacked (raw 2600MC, full
pass mark, 26 November 2026): brightest-third flux 0.989 (needs 0.995), peak 0.960 (needs 0.99), visible
cosmic-ray pixels 109 (the shipped rule 12, so at most 22). It keeps far more starlight than the shipped rule
(0.943, 0.819), but in the sharp frames, the only ones where its core test acts, that test spares cosmic-ray hits
too. The other three 2600MC sessions and set 76 are finished for the record; candidate 6 is not promoted whatever
they show. Shape tests within one frame are not separating a sharp core from a hit, so further thresholds are
not tried.

### What comes next for the cleaning, and its limits

One candidate, then stop. It uses the other frames: a pixel the shape test calls a hit is left alone when the
session's lined-up reference has a star there. Its limits, fixed before it is written:
- It changes only which pixels the per-frame cleaning replaces. The frames on disk are never changed, the
  stack's own rejection is unchanged, and the replaced pixels of each frame are counted and kept beside it.
- A real one-frame signal must survive the cleaning: planted star-like sources present in one frame only (an
  asteroid, a flare, a transient) are measured with the pass mark, and must keep their light as stars do.
- Judged on the same pass mark on the owner's 11 sessions, the four raw 2600MC sessions and set 76; only if it
  passes all of them, once on the five frozen raw sessions. A failure there is recorded and not tuned against.
- If it fails, `stacking.clean` stays as it is, and the cleaning is recorded as proven on the owner's rig and not
  yet on other cameras.

### The footprint, and what is cropped

The covered-area candidate (`fp_patch.py`) is for stacks made elsewhere, which carry no coverage. A restack made
here already knows its coverage from each pixel's weight and trims to it (`stacking.Stack.covered`); the grain is
used only where no weight exists. The stacks are never cropped or changed: only the picture is cropped, and the
linear picture file is marked a picture product, not for measurement, with its crop in its header.

Candidate 6 on all four raw 2600MC sessions, for the record (not promoted):

| Session | Shipped rule | Candidate 6 |
|---|---|---|
| Abell 1656 | fail (flux 0.943, peak 0.819; cosmic 12) | fail (0.989, 0.960; cosmic 109) |
| LBN 552 | fail (0.970, 0.926; cosmic 36 against 24) | **pass** (1.000, 1.000; cosmic 30) |
| M81 | fail (peak 0.978) | fail (1.000, 1.000; cosmic 141 against 15) |
| NGC 7293 | pass | pass (cosmic 2) |

It keeps the light everywhere but lets hits through in the sharp sessions: 2 of 4 pass, against the shipped 1.

Candidate 6 on set 76 (QHY Minicam8M), for the record: **all 4 fail**, much as the shipped rule did (Ha 10 Oct
flux 0.793, peak 0.603; OIII 10 Oct flux 0.171, peak 0.168; the other two on grain and cosmic counts). Set 76's
frames are 2.7 to 3.6 px wide, mostly over the 3.35 px at which candidate 6 acts, so here it is mostly the shipped
rule, and an 83% loss in a stack is not sharp cores alone: set 76 has a cause of its own, still open. To be found
in single frames, as Abell 1656's was (`cleanparts.py`), before candidate 7 is judged on set 76.

### Set 76's cause: stars under 2 px wide (cleanparts76, 26 November 2026)

Diagnostic, not a verdict: every fourth frame of set 76's two 10 October sessions, each part of the cleaning
against the frame uncleaned (brightest-third stars):

| Session | Frames' star width (px) | Defect map alone | Lone-pixel rule alone |
|---|---|---|---|
| Ha | 2.61 to 2.84 | keeps everything (45 to 54 map pixels on stars) | keeps 39 to 79% of the flux, 18 to 52% of the peak |
| OIII | 1.96 to 1.98 (one frame 3.42) | keeps **2 to 4%** (283 to 327 map pixels on stars) | keeps 2 to 4% |

So it is the star-core fault at its worst. Ha's stars are sharper than any Abell 1656 frame and the rule takes
their cores, as there. OIII's are under 2 px across, nearly one pixel. Every star is then a lone spike. The rule
takes it, and so does the defect map: the frames were not dithered, so the stars sat on the same pixels all
night, and the map's guard (a star's third-brightest neighbour stands out too) does not hold for a star that
small. No shape test can save such a star; only knowing it is a star can. That is candidate 7's test (a star in
this frame and in the reference), which must then also spare the map's pixels that are stars, not only the rule's.

### Candidate 7 on the owner's 11 sessions (26 November 2026, run on the laptop)

Candidate 7 (`mframe.py`): a pixel the shipped cleaning would replace, by the rule or by the defect map, is kept
when a star found in this frame matches one of the session's reference within 1.5 px. **All 11 pass**: every
star's light, peak and grain kept (flux 0.9999 or better), visible cosmic-ray pixels 0 to 24, never above the old
cleaning's plus 10, fixed defects left no worse. One caution: this run's old-cleaning baseline came out looser on
the laptop than on the desktop (fixed defects left 0.08 to 0.14 against 0.02 to 0.05; IC 405's cosmic count 24
against 0 in the first desktop run), so the same 11 are run again on the desktop (`clip14md`) before this counts.

Planted star-like sources in one frame only (20 a frame, 262 frames): the cleaning keeps a median 98.2% of their
light, at worst 76.5%, the same with the shipped rule and with candidate 7, as designed (it spares only stars the
reference has). So the shipped cleaning already takes a little of a one-frame source's light, up to a quarter in a
few frames: a thing to know for discovery work on single frames, measured here for the first time.

### The covered-area candidate: a first try with a bug, and a second (26 November 2026)

The first try (`fp_patch.py`) cut 10 of the 17 pictures to under 60% of the frame and refused them (D43 kept 2%,
D56 5%). Two faults of mine: its new function had the name of `colour.covered`, which lines the filters up, and
replaced it; and it counted a bright nebula's grain as thin coverage. Recorded as a failed try, not a verdict on the
idea. The second (`fp_patch2.py`, function `well_covered`) counts a block as thinly covered only when its grain is
over 1.5 times the usual, its level is the sky's (60th percentile or under), and it joins the frame's edge. On all 17
stacks it leaves the rest alone (99.5% or more kept) and finds D28's corners (the picture cropped to 66% of the
frame), D57's untracked band (63%) and D65's top strip (95%). Pictures of the five failures and five passes are
being made with it.

Candidate 7 on the four raw 2600MC sessions (desktop, 26 November 2026):

| Session | Shipped rule | Candidate 7 |
|---|---|---|
| Abell 1656 | fail (flux 0.943, peak 0.819) | **pass** (1.000, 1.000; cosmic 14 against 12) |
| LBN 552 | fail (0.970, 0.926; cosmic 36 against 24) | **fail, cosmic only** (0.9999, 1.000; cosmic 36 against 23) |
| M81 | fail (peak 0.978) | **pass** (1.000, 1.000; cosmic 24 against 15) |
| NGC 7293 | pass | see the line below |

Every star's light kept in all four. LBN 552 fails on cosmic rays by 3 pixels, and cannot do better by design:
candidate 7 only spares pixels the shipped cleaning would replace, never replaces more, and the shipped rule itself
leaves 36 there. That shortfall is the shipped cleaning's, not the star-core fault's. By the pass mark it is a fail,
and it stays one.
NGC 7293: raw533-NGC7293             RGB   rejected 0.0000 flux 1.0000 peak 1.0000 grain 1.0000 fixed 0.0137/0.0237 cosmic 2/3 PASS

Candidate 7 on set 76 (QHY Minicam8M, 26 November 2026):

| Session | Shipped rule | Candidate 7 |
|---|---|---|
| Ha 10 Oct | fail (flux 0.793, peak 0.603) | **pass** (0.998, 1.000; cosmic 6 against 1) |
| Ha 2 Nov | fail (grain) | fail (flux 0.991, grain 0.987) |
| OIII 10 Oct | fail (flux 0.171, peak 0.168) | fail (0.171, 0.168), unchanged |
| OIII 29 Oct | fail (flux, grain, cosmic) | fail (grain 0.970 only) |

The grain failures are the shipped cleaning's own (it smooths these frames' grain by 1.3 to 3%, as it did before).
OIII of 10 October is not a fair test of anything yet: its frames do not all show one field. Lined up on the
session's reference (its first frame), light-0004 matches 20 stars, light-0008, -0012 and -0016 none, their rough
shifts 150 to 500 px apart. A mosaic's panels or a re-pointing in one night's folder, so most frames have no
reference star to spare, and the harness's stack holds few frames. A data fault, to go in the register; the
session's result stays recorded as it is.

Candidate 7 so far: the owner's 11 pass (on the laptop; the desktop's run is going); of the other cameras' 8
sessions it passes 4 (the shipped rule 1) and keeps every star's light in all but the mixed OIII session; its other
failures are the shipped cleaning's own cosmic shortfall (LBN 552) and grain (set 76).

The second covered-area candidate's pictures (26 November 2026), against step 4's:
- **D65: fixed.** The strip along the top is gone and the rest of the picture is as before.
- **D18, D43, D56, D74, D31 (passes): unchanged**, as they should be.
- **D41 and D72: unchanged**, as expected. Their faults are not coverage: D41's purple corner is the sky model's,
  and D72's holes are dust in a stack with no flats.
- **D28 and D57: no picture.** The crop left 72% and 65% of the frame, and `colour.py`'s guard against filters
  that drifted apart (at least 75% shared) refused them. That guard is for filters that drifted off the target,
  which a thinly covered edge is not. A third version keeps the guard, counting what the filters share before
  the thin parts are left out (`fp_patch3.py`). It is making D28 and D57 now.

**Candidate 7 on the owner's 11 sessions, desktop (the run that counts): 10 pass, M33 L fails.** M33 L of
5 November leaves 18 visible cosmic-ray pixels against the old cleaning's 3 (at most 13); every star's light is kept
in all 11. The laptop run had passed it only because its baseline was looser (22 there), as feared. The cause is
plain from the design: candidate 7 leaves a found star's whole 3 by 3 centre alone, so a hit that lands on a real
star's core is spared with it, and M33 L, a crowded field with a star on many pixels, catches the most.

**So candidate 7 fails, and by the stopping rule fixed before it was written, the cleaning stops here.**
`stacking.clean` stays as shipped. The shipped rule's record:
- On the owner's rig it passes all 11 sessions.
- On other cameras it fails sharp frames: Abell 1656, M81, LBN 552 and set 76.

Across candidates 1 to 7, two findings stand. Where a sharp core and a hit look alike in one frame, only another
frame tells them apart, and in sharp, crowded fields that still spares the hits that land on stars. The way on is
a value test, not a shape one: a pixel kept only when its value agrees with the reference's at that place. It is
recorded here as the next idea, not started.

The third covered-area candidate (`fp_patch3.py`), D28 and D57 (26 November 2026): both made, each against step 4's.
- **D28: better, not fixed.** The green gradient along the bottom is gone and the picture is cropped in. But
  parts of two corner wedges are still in it (bottom left, top right): the grain mask finds the wedges' outer
  parts and misses their inner edge, where fewer frames are missing.
- **D57: better, not fixed.** Most of the diagonal band is cropped away, but a sliver is left at the top left.
  The orange glow in the bottom-right corner is untouched, as it should be: it is in the data (by its look,
  amp glow or a light), not a coverage gap.

So the covered-area fix has one clean pass (D65), two improvements that still fail by eye (D28, D57), and changes
nothing it should not (the five passes, D41, D72). It is not ready to judge on frozen data.

The fifth covered-area version (`fp_patch5.py`) takes every filter's own footprint, not L's alone: D28's leftover
wedges were R, G and B's (26 November 2026).
- **D28: nearly fixed.** Gradient and wedges gone but for two slivers in the very bottom corners; cropped to 64%.
- **D57: fixed by eye.** Band and corner glow gone, cropped to 51% (an untracked stack, its two galaxies kept).
- **D65: better than version 2.** With OIII's thin strip out of the sky fit, the teal cast over the whole picture
  is gone too.
- **D31 (a pass): unchanged.**

The other 13 pictures are being made with it, to show it changes nothing it should not, before it is judged once
on the six frozen stacks.

### Is it Dark Star, or our blend? (26 November 2026)

Step 2's own scores already hold Dark Star's raw output beside the blended one (`stars_chain.py` keeps both). Stars
left, overall and worst tenth:

| Stack | Ours | Dark Star alone | Dark Star blended (ours) |
|---|---|---|---|
| D74 Ha (Tarantula) | 28%, 74% | **94%, 106%** | 100%, 101% |
| D74 OIII | 10%, 63% | 13%, **107%** | 14%, 101% |
| D78 Ha (M42) | 0.7%, 24% | 0.3%, **98%** | 0.2%, 100% |
| D18 Ha | 0.8%, 29% | 0%, **101%** | 0%, 100% |
| D31 L (M101) | 0.8%, 13% | 1.3%, 19% | 1.4%, **40%** |

So in the crowded and bright-nebula fields Dark Star itself leaves the stars; our blend changes little there. In
D31 the blend is what puts back a share of the worst tenth: that part is ours to fix, in `colour.py`'s blend. The
model's weights are not open, so Dark Star's own share could only be helped by what it is given (its tiling, its
stretch, the mode) or reported upstream; neither is started.

**Candidate 8 on the owner's 11 sessions (desktop): 10 pass, M33 L fails exactly as candidate 7 did** (18 visible
cosmic-ray pixels against 3; every star's light kept in all 11). The shape test removed none of the extra hits, so
they are not cores made brighter by a hit: they sit within the spared 3 by 3 where a hit is no brighter than its
star's core. Recorded as a failure; the 2600MC sessions and set 76 are run to the end, as asked, before the
evidence is read as a whole.

**Covered-area version 5 on the other 13 pictures (26 November 2026): no picture made worse.** Each is as it was in
step 4, cropped by at most 9% (D40 91%, D43 90%; most 94 to 100%). D41's purple corner and D72's dust holes are
unchanged, as expected: neither is coverage. With D28 nearly fixed and D57 and D65 fixed, version 5 is the
covered-area candidate to judge, once, on the six frozen stacks.
