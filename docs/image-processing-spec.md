# Finished pictures: what the paid tools do, and our own trained models

Spec, 21 November 2026. Part of stage A is built (section 4.1). Stage B's checks
and a first stage C model were run on 22 November (section 5.1): **the model was
not accepted and no picture uses it.** Stages D and E are not built. It covers two things: what the commercial astrophotography tools do that
TelescopeYoke does not, and how to train our own small neural networks for
the parts where training helps.

**Direction changed on 23 November 2026.** TelescopeYoke now automates the best
freely available tools instead of training its own models (`docs/free-tools-plan.md`).
Section 1 is current. The sections on training models are a record of what was tried;
their code (`denoiser.py`, `trainset.py`, `externalpairs.py`) was removed that day and is in git history.

How far to trust each statement:

- **Measured**: read from this repository, its data or the computers, on the date above.
- **Sourced**: from a linked page or paper. Vendors' pages are their own claims.
- **Proposed**: a design choice or estimate of ours, not yet tried.

## 1. Goal and limits

**Goal.** From a night's calibrated stacks, make the best finished colour picture
we can automatically, by driving freely available tools. Anyone who wants
TelescopeYoke to handle their image processing downloads those tools themselves.

**Limits, which no stage may relax:**

1. **Pictures only.** Nothing here changes a raw frame, a calibration master
   or any `final.fits`. Depth, subtraction, vetting, transits, variables and
   every other measurement keep reading the untouched stacks. A trained model
   can invent or remove a faint star, so its output must never reach the
   discovery pipeline.
2. **Labelled.** Every picture records which steps and which model version
   made it, in its JSON beside the JPEG, through `records.write` with its
   schema and stamp. A picture using a trained model says so.
3. **Fail back.** A missing tool, GPU or desktop gives today's picture and
   says which tool to download and why. An imaging night never waits on any of this.
4. **The night is not touched.** Heavy processing never runs on the laptop while
   the camera or mount is in use.
5. **No test suite.** A tool is accepted for a stage by measuring it on real
   held-out stacks, as a result recorded in `docs/validation.md`.
6. **The tools stay the user's own.** TelescopeYoke calls them as separate programs
   and never bundles them or their models. GraXpert's denoise model is CC BY-NC-SA 4.0.

## 2. Where we are (measured)

**The pipeline today.** Calibration with matched darks, filter flats,
flat-darks and bad-pixel maps; destriping; frame rejection and weighting by
sharpness, roundness, transparency and noise; registration, including the
half turn across the meridian; outlier-clipped averaging; a sky surface of
order 0, 1 or 2; colour balanced on the stars; an arcsinh stretch; LRGB, SHO
and HOO palettes; mosaics.

**Added for narrowband since this spec began** (section 4.1): a linear path,
star-width matching, star/nebula layers, optional wavelet noise reduction and
local contrast.

**Not in the deep-sky path**: deconvolution, edge-preserving noise reduction,
photometric colour calibration (Gaia is used for depth and photometry, not
colour), a hyperbolic stretch, continuum subtraction, per-pixel noise maps
for pictures. `lucky.py` has its own sharpening, for the Moon and planets.

**Our own data, 183M, as of today:**

| Filter | Sessions | Frames | Hours | Targets |
|---|---:|---:|---:|---:|
| Ha | 15 | 383 | 5.0 | 6 |
| L | 8 | 439 | 2.0 | 5 |
| OIII | 5 | 47 | 1.9 | 2 |
| SII | 3 | 29 | 1.0 | 1 |
| R | 3 | 109 | 0.5 | 2 |
| G | 1 | 100 | 0.4 | 1 |
| B | 1 | 100 | 0.4 | 1 |
| **All** | **36** | **1,207** | **11.2** | |

The older 183C colour camera adds 99 sessions and 24.6 hours. Its noise and
Bayer pattern differ, so it stays out of the first training set.

A stack at the 2x2 processing scale is about 2,560 x 1,690 pixels, or about 60
non-overlapping 256-pixel patches. That is at most about 2,200 patch positions
across all 36 sessions, before dropping short sessions. It is enough for a
rudimentary denoiser, with flips, quarter turns and random crops. It is not
enough for variety in OIII or SII, which have one or two targets.

**Computers:**

| | Laptop | Desktop (`ssh desktop`, WSL) |
|---|---|---|
| GPU | Radeon Pro WX 4150, no CUDA | GeForce GTX 1080, 8 GB, driver 581.80 |
| CPU, memory | 8 threads, 22 GB | Ryzen 9 3950X, 16 cores, 35 GB |
| Free disk | Storage disk 535 GB | 224 GB |
| PyTorch | none | none yet |

**PyTorch on the GTX 1080 (sourced).** Pascal cards need a CUDA 12.6 wheel.
PyTorch's notice says 2.14 is the last release with CUDA 12.x wheels, so the
environment must pin **PyTorch 2.14 or earlier, `cu126`**. Running it under WSL
on this card has not been tried, and is the first step of stage 1.

**Star size, measured on the NGC 2174 stacks** (second moments of unsaturated
stars, so a rough figure): Ha 4.66 stack pixels (6.8"), OIII 3.75 (5.5"), SII
3.71 (5.4"). Ha, from a different session, is about 25% wider. A star wider in
one channel gets a coloured rim, which fits the red-and-cyan stars in the HOO
picture, though that cause is not yet proven.

**One open fault that gates training.** Today's long darks flip between
median levels about 5 counts apart (78-79 and 83-84) from frame to frame, at
every exposure from 150 to 240 s. The cause is unknown. In the 20 raw SII
light frames checked (two sessions, 120 s) no such jump appears: frame-to-frame
shifts are 0 to 1 count and even across the sensor. That is one filter on one
night, so the check is repeated over every session entering a training set. A
shift shared unevenly between two half-stacks would be learned as signal. It
does not hold up the plain picture work.

## 3. What the paid tools have that we do not

Priority is what it would do for this rig's pictures. "Train?" says whether a
network is the right tool or plain code is.

| # | Capability | Who has it | What it does | Have it? | Train? | Priority |
|---|---|---|---|---|---|---|
| 1 | Star/nebula separation | StarXTerminator, StarNet | Processes stars and nebula apart, then recombines | No | Plain code first, model later | **1** |
| 2 | Noise reduction | NoiseXTerminator, GraXpert, PixInsight MLT | Removes grain, keeps structure | No | **Yes** | **1** |
| 3 | Photometric colour | PixInsight SPCC, Siril SPCC | Star colour from catalogue spectra and the filter and sensor curves | Star-average only | No | **2** (broadband) |
| 4 | Better gradient model | PixInsight DBE/MGC, APP, GraXpert | Follows sky gradients a polynomial cannot | Order 0-2 | Plain first | **2** |
| 5 | Controlled stretch | GHS (PixInsight, Siril) | Sets where contrast goes | Arcsinh only | No | **2** |
| 6 | Local contrast | PixInsight HDRMT, LHE; StarTools HDR | Reveals structure in bright cores | Narrowband, median scales | No | **2** |
| 7 | Deconvolution | BlurXTerminator, StarTools SVDecon, PixInsight | Undoes blur | No | Plain first, then **yes** | **3** |
| 8 | Star shape repair | BlurXTerminator "correct only" | Fixes coma, tilt and guiding elongation across the field | No | **Yes** | **3** |
| 9 | Star reduction, halos, fringes | SXT workflows, Siril "unpurple" | Smaller stars, no coloured rims | No | Follows from 1 | **3** |
| 10 | Narrowband into RGB | NBRGB, NBAccent | Adds Ha or OIII to a natural colour picture | No | No | **3** |
| 11 | Continuum subtraction | PCS script, PixelMath | Takes starlight out of Ha, using R | No | No | **4** |
| 12 | Local normalisation | APP LNC, PixInsight | Evens out sessions before stacking | Frame-level only | No | **4** |
| 13 | Per-pixel noise tracking | StarTools Tracking | Knows each pixel's noise through every step | No | Feeds 2 and 7 | **4** |
| 14 | Drizzle | PixInsight, Siril | Recovers resolution from undersampled data | No | - | **Not needed** |
| 15 | PSF matching between filters | PixInsight workflows | Brings each filter's stars to one width before colour is made | No | No | **1** |

Drizzle is rejected on the figures. The 183M at 675 mm is 0.73"/px, and 1.47"/px
at the 2x2 scale. Our stars are about 3.7 to 4.7 pixels FWHM at that scale, so the data are
not undersampled. Full resolution is already a setting (`processing_scale = 1`).

**What the money really buys.** Items 3 to 6 and 9 to 13 are ordinary
algorithms that free software such as Siril also has. The paid tools' real
advantage is trained models for items 1, 2, 7 and 8, and item 8 is the hardest
to match.

## 4. Plan

Plain methods come first because each stage needs one as its baseline: a model
that cannot beat a wavelet denoiser is not worth keeping.

| Stage | Delivers | Needs |
|---|---|---|
| A | A linear path (section 4.1); PSF matching between filters (4.2); 32-bit export; star mask and separation; wavelet noise reduction; photometric colour; GHS; local contrast; better gradient; narrowband into RGB; continuum subtraction | Plain code, filter curves, Gaia |
| B | Training-data diagnostics: the level flips, and the half-stack checks of section 5 | Plain code |
| C | Own-data denoiser (section 5) | PyTorch on the desktop; B passed |
| D | Star removal model (section 6.1) | Stage A's separation, stage C's tooling |
| E | Star repair, then separately modest sharpening (section 6.2) | Survey data, measured star shapes |

A and B can run side by side, and A's pictures do not wait for B. C to E each
start only when the one before has passed its acceptance.

### 4.1 A linear path to colour

Today's channels stay in floating point, but `process.process(whole=False)`
returns them on a 0 to 255 display scale, **after** background removal and an
arcsinh stretch, and `colour.narrowband` mixes those stretched channels. So the
mixing is unrounded but not linear, which matters most for faint OIII and SII.

Stage A separates the order: linear stacks; background removed from each;
channels scaled to each other; PSF matched; palette mixed; **one** display
stretch at the end. Today's path stays available as the comparison baseline. The
linear colour result is also saved as a 32-bit file beside the JPEG, so a
picture can be reprocessed without restacking. It is a picture product and
never replaces a `final.fits`.

**Built 21 November 2026, for narrowband** (`colour.py`, the default;
`--stretched` is the earlier method). Sky is fitted outside the nebula as the
strongest filter shows it, nebula and stars are balanced apart, and brightness
comes from the unblurred filters. On NGC 2174 the stars lost most of their
coloured rims and the Hubble palette shows gold and blue. A patch at one corner
of the sensor, in every filter, is taken out by a smooth map of the clear sky;
its cause is unknown, and 3.5% is trimmed off each edge.

**Measured with planted signal, 21 November 2026** (five stacks: NGC 2174 in Ha,
OIII and SII, NGC 281 in Ha and OIII; the NGC 281 stacks are uncalibrated;
one-off measurements, each planted at 1 and 3 times the pixel noise):

- *Sky map.* Applied across the whole frame it took 7 to 62% of a faint isolated
  glow (60 px sigma). It now acts only in the outer quarter, and 90 to 100% of
  the glow survives. Every bright patch counts as nebula except a smaller one
  along the frame's edge. With under 30% of the frame clear, no map is made.
- *Wavelet noise reduction.* At equal grain it kept no more faint detail than a
  plain Gaussian blur of sigma 0.7 to 0.8 px, on glows or thin filaments. Both
  lost 6 to 36% of a thin filament's flux on the nebula. So it is **off by
  default** (`--noise-reduction`), kept as the baseline for stage C.
- *Star widths.* After the global match, each ninth of the NGC 2174 frame is
  within -9 to +6% of Ha's width. Local kernels are not needed yet.

- *The whole sky chain, from the stack.* A glow planted at 3 times the pixel
  noise keeps 96 to 98% at 60 px sigma and 87 to 93% at 150 px. At 350 px it keeps
  only 32 to 48%, and at 800 px, about the frame's size, 2 to 13%. Fitting only a
  level first, so that every surface is fitted with the nebula masked, changed
  these by a few points and left the sky as flat. The first pass is now a level
  anyway. **A faint glow nearly as wide as the frame cannot be told from a sky
  gradient in one frame.** Keeping it needs a wider reference image (MGC, or
  perhaps the guide camera).
- *Coverage.* Empty stack pixels (zero, joined to the frame's edge) now travel
  through alignment as a mask. None of the six stacks measured had any, so
  today's pictures do not change because of this.

- *Horizontal streaks in NGC 2174's Ha.* Real nebula. The same pattern appears
  on two nights lined up on the sky (r 0.975) and not on the sensor (r -0.09), the
  framing about 680 px apart.
- *TGV noise reduction.* At equal grain it kept the same planted filaments as a
  plain blur (96 to 99% against 97 to 98%), in Ha and OIII at 1 and 3 times the
  noise, on one 420 px crop. Not added.
- *BiShrink noise reduction* (each coefficient shrunk using its parent scale; an
  undecimated db4 wavelet, not the original dual-tree transform). At equal grain, on
  two 420 px crops of NGC 2174 in Ha and OIII, it kept less of a planted filament at
  1 times the noise than a plain blur (85 to 93% against 97 to 98%) and about the
  same at 3 times (96 to 98% against 97 to 98%). Its error in the filament's shape
  was 2 to 4 times the blur's at 1 times the noise and up to twice at 3 times. Not added.
- *Stacking against Siril 1.4.0-rc2.* IC 405 in Ha, the 89 frames our stack kept,
  calibrated once by our code, then registered and stacked by each (Siril: global
  star alignment, winsorized 3-sigma rejection, additive-scale normalisation; it
  could not register 1 frame). Measured at our 2x2 pixels on the central 2000 x 1400:
  ours found 937 stars at 5 sigma, Siril 957; signal-to-noise of the 100th, 300th and
  600th brightest was 59.0, 19.9, 8.8 against 58.7, 20.1, 9.1; star width 5.03 against
  5.08 px. Siril's wFWHM weighting was sharper (4.90 px) but shallower (912 stars).
  **No meaningful difference**, so stacking is not where the next gain is. Only
  registration and stacking were compared, on one target.
- *NL-Bayes noise reduction* (Siril's, with its DA3D, VST and SOS variants). On planted
  filaments on NGC 2174 it beat a blur at equal grain, keeping 71 to 87% of a filament
  at 1 times the noise against 56 to 72%. Against an independent stack of other nights
  of IC 405 in Ha, its overall error equalled the best blur (76.7% of the input's
  against 76.8%), with about 6% less residual at middle scales. Below the 10% this
  spec asks for, so not added.
- *Rejection in short stacks.* Clipping at 4 spreads about the mean of all frames can
  never remove a lone outlier from 17 frames or fewer, as it inflates its own spread:
  planted trails stayed at full strength. Stacks of 5 to 40 frames now clip about the
  median, with a spread from the median deviation. Planted trails 15 times the noise
  went, and the noise stayed within 1% of ideal at 5 to 30 frames (at 5 frames a trail
  of 15 times the noise still leaves about a third). On 12 real IC 405 frames, 177
  pixels changed by over 5 counts and the grain did not change. Longer stacks are as before.
- *Generalised hyperbolic stretch* (`--ghs`, off by default). Contrast is aimed at 3
  times the sky's grain, and a constant slope above 90% of white keeps the stars' shape.
  On IC 405 it shows more of the outer nebula than the arcsinh stretch. It also lifts
  whatever gradient is left, so a corner glow shows more.
- *Level jumps between frames.* Fitting each frame against the session's median
  and the flat separates sky (which follows the flat) from a fixed offset. In the
  NGC 2174 Ha session, seven frames have offsets of +5 to +34 counts that do not
  follow the flat. All seven were already rejected from the stack, and the two
  largest have star flux down by 75 to 90% or more, so cloud is likely but not
  shown. One SII frame is exactly 5 counts low with its sky unchanged, the size of
  the dark level flips. A scan of 1,267 saved 183M lights in 31 sessions (at most
  80 per session) found 55 frames (4.3%) with a fixed offset of 3 counts or more
  that does not follow the flat: 37 of them 4 to 6 counts, both signs, in every
  filter and at 4, 16 and 120 s. That points at the camera's level rather than one
  exposure or filter, but some could be sky. Compared with the 622 other frames of
  those sessions, 47 of the 55 have their stars within 10% of normal, so cloud does
  not explain them; 8 are dimmed. Sensor temperature and the gap before the frame
  show no link, and about half are single frames. The usual size, 4 to 6 counts,
  matches the 78-79 against 83-84 flips seen in capped darks, so **the camera's
  black level changing between frames is the likely cause.** The per-frame log of
  the 260 capped darks of 21 November settles that the camera does jump with no sky:
  none of the 120 darks up to 3.7 s stepped by 3 counts or more, while from 30 s up
  37 steps did, between levels about 5 apart (78-79, 83-84, 88). Stage B levels each
  frame before pairing frames for training; no further darks are needed for this.

- *Pattern fixed to the sensor (stage B pilot, 22 November 2026).* In calibrated
  frames held in sensor coordinates, two independent halves of a session share a
  single-pixel pattern (correlation 0.19 to 0.46 in the seven sessions measured,
  gone after a 1-pixel shift), about 0.5 to 0.9 of one frame's noise. Rows, columns,
  outliers and the flat do not explain it; the master dark tracks it weakly with
  the opposite sign (-0.10 to -0.23), and its cause is not established. Dithering
  scatters it: carried through each frame's real alignment, it would correlate
  the two aligned halves by at most 0.0006 in six sessions, and by 0.02 in the one
  with a 6-pixel median dither and 12 frames. **Sessions with too little dither stay
  out of training.** What stage B has and has not shown is in section 5.1.

- *Star reduction* (`--star-reduction`, off by default). Each star keeps its peak
  and loses its wings, with one gain across filters. At 2 on NGC 2174, star width
  went from 7.1 to 5.3 px and all 1042 measured stars stayed. Measured before the
  final change to how the peak fades, which removed a ring round bright stars.
- *Deconvolution* (`--sharpen`, off by default). Richardson-Lucy on the star-free
  brightness, only where the nebula stands above the grain. On a Ha crop, 3 steps
  raised fine detail by a third with agreement with another night's stack almost
  unchanged (r 0.175 to 0.172). By 20 steps planted lines rang and r was 0.135. In
  the finished picture it still looks grainier at today's depth.

Local contrast is built (structure from 3 to 24 px, on the star-free layer), on
median scales. Beside a planted hard edge its dark rim is 22 px wide against 73 px
for Gaussians, at the same depth (30%), so a rim remains. `--no-contrast` leaves
it out for comparison. The
odd and even halves of a session agree on that structure (r 0.72 to 0.97) and do
not below 3 px, which it leaves alone. A centred hyperbolic stretch was tried and
not kept. Method notes: `docs/research/image-processing-methods-2026-11-21.md`.

Each picture's JSON is now stamped through `records.write` (schema `colour`),
with every effective setting and each source stack's SHA-256. Comparison runs
get their own file names. The usual name is the latest picture, and each
different make is also kept in `web/colour-runs/` under an identifier from its
method version, settings, stacks, code commit and the picture's own contents,
with its own record and `-linear.fits`. That file holds the colour, the separate
brightness, the local-contrast gain, the coverage and the display settings, and
makes the JPEG again byte for byte (checked on NGC 2174, plain and with star
reduction and sharpening). Each make costs about 90 MB. A run that
replaces a picture first keeps the old picture and record there, and runs with
`--night` or `--any-coverage` get their own file names. Section 7's other measures have not been run.

### 4.2 PSF matching

1. Measure each filter's star shape with the existing 3 x 3 grid
   (`plant.local_shapes`).
2. Bring the sharper filters **towards the widest**, never sharpening the
   widest. First try on NGC 2174: OIII and SII towards Ha, with a normalised
   Gaussian kernel of sigma `sqrt(target^2 - own^2)`, which preserves flux.
3. If the width varies materially from centre to corners, use a regularised
   kernel from the measured shapes in each part of the grid, smoothly blended.
   This is a few lines of NumPy; [photutils](https://docs.astropy.org/projects/photutils/en/stable/user_guide/psf_matching.html)
   is the reference for the method, and is not a new dependency.
4. Blur only what colour needs. The sharpest filter's unblurred image is kept
   for a separate detail layer.
   Built as the global Gaussian: on NGC 2174, OIII 5.05 to 5.78 px and SII
   5.13 to 5.81 px, against Ha's 5.88. Local kernels are not built.
5. Passes if star colour rims shrink and each filter's star flux is unchanged.
   Ha's extra width may be a focus or session difference, so it is also worth
   fixing at the telescope rather than blurring everything to it.

**Where it would live (proposed).** A `finish.py` command for the picture
steps, called by `colour.py`; `train.py` for building sets and training, which
runs on the desktop through the same route as `restack.py --on`. Each is
classed in `policy.py`, listed in `docs/agents/commands.md` and has a schema for
its `--json`. On the desktop everything is under `~/telescopeyoke-laptop/training/`.
PyTorch stays on the desktop and does not become a dependency of the laptop or
of a normal install.

## 5. Stage C: a denoiser from our own frames

**Method.** Noise2Noise: a network trained to predict one noisy image from
another of the same scene converges on the clean image, provided the two
noises are independent and zero-mean. Odd and even frames of a session supply
that pair for free. [Noise2Astro](https://arxiv.org/abs/2209.07071) applied it
to astronomy on simulated data, reporting about 98% flux recovery under
Poisson noise; [ASTERIS](https://arxiv.org/abs/2602.17205) splits real exposures
into two independent sets; [AstroSURE](https://arxiv.org/abs/2604.16793)
compares self-supervised methods on HST and CFHT, and finds transfer between
instruments limited. That last result is a reason to train on our own camera.

**Building the set (proposed):**

1. Use sessions with at least 8 accepted frames. Calibrate and register them
   with the existing pipeline onto one reference per session.
2. For each session make 4 random disjoint splits of the frames into A and B,
   balanced by frame FWHM so the two halves have matching star shapes. Each
   half is stacked alone: its own means, clipping and normalisation, computed
   from its own frames only. Halves are then matched in brightness scale.
   About 17 MB per image at the 2x2 scale, so roughly 5 GB in all.
3. Vary the split (1:1, 1:3) so the network sees several noise levels. A full
   stack has less noise than any half, and a network trained at one level
   misjudges another.
4. Give the network a noise-level map as a second input channel, from the
   frame scatter of the **input** half only.
5. Hold out whole **targets**, never just patches. **NGC 2174 is held out** in
   every filter until acceptance, because it is the picture we most want to
   judge and has Ha, OIII and SII.
6. SII has only that one target, so holding it out leaves no SII in training.
   SII results are reported apart, as a test on an unseen filter, and SII
   support stays **experimental** until a second SII target exists. OIII has
   two targets and is reported apart too.

More crops and more splits of the same frames do not add new sky. About 2,200
patch positions is enough to attempt a small denoiser, not evidence that it
will generalise.

**What breaks the method.** Anything shared by both halves is learned as real:
residual dark or flat error, hot pixels, banding, walking noise when dithering
was small, cloud that varies through the session, and the unexplained level
flips of section 2. Interpolation correlates noise between neighbouring pixels
within a frame, but not between different frames, so it should not break the
pairing (our reasoning: no source was found on this exact case).

**Stage B's entry check for each pair.** Measure the correlation between the
two halves' residuals, in blank sky and in rings around stars, and correlate
the A-B difference with the dark and flat residuals. A pair with a significant
correlation, unstable detector levels or strong cloud variation stays out.

An A-B difference **cannot** see a defect that is identical in both halves,
since it cancels, so it is one diagnostic and not the gate. Stage B adds:

- **Calibration defects shared by both halves:** individual darks are not kept, so
  masters cannot be split. A defect in a master is fixed to the sensor, so the
  detector-fixed check below sees it, and carrying that pattern through each
  frame's alignment measures what reaches the training pair.
- **Detector-fixed structure:** frames are stacked in detector coordinates,
  without registration, so sky averages away across dithers and anything fixed
  to the sensor remains. Sessions with too little dither to separate the two
  are marked and stay out.
- **Known defects:** planted dark, flat and banding errors of known size, run
  once to measure what size each diagnostic can detect. That figure is recorded
  with the diagnostics.

**Network (proposed).** A small residual U-Net, 4 levels, 32 base channels,
predicting a correction to its input. One model for all filters at first, with
the filter given as a condition only if results differ by filter. 256-pixel
crops, in FP32. Reported FP16 throughput on this GPU family is very poor (we
could not open NVIDIA's page to confirm it), so the batch is reduced before
mixed precision is tried, and it is kept only if a benchmark shows a gain.
Training time on the 1080 is unknown until that benchmark.

**Loss.** Noise-weighted L2 in **linear** units, the weights never derived
from the noisy target itself, which would bias the result. A loss taken after a stretch
would bias the mean of a noisy target and so bias flux. The input may be
compressed for the network to see, but its output and loss stay linear. A
flux-preserving correction after inference puts back the input's large-scale
level. That protects only large scales, so small faint structures rely on the
acceptance measures of section 7.
[PAU Survey](https://arxiv.org/abs/2611.05447) reports the same risk (erased
faint emission, biased fluxes) and uses flux-aware losses.

### 5.1 First results (22 November 2026)

Code: `trainset.py`, `denoiser.py`. The checks as run, their figures and the
sessions are in `docs/research/denoiser-2026-11-22/`.

**Data.** 18 of the 30 183M sessions with 8 or more frames gave pairs: 7 to train
(4 of them M33, one in Ha), M106 to watch training, and 10 of NGC 2174 and IC 405
held out. The rest had under 10 px of median dither or too few usable frames. So
OIII and SII were tested with no training target of their own.

**Stage B: every kept pair passes its measured checks.** That is evidence of
independence for what is measured, not proof of it. The sensor pattern is at single
pixels (gone after a 1 px shift, unchanged by removing rows and columns), the kind
alignment scatters best. `trainset.py` refuses a frame whose alignment residual is
over 2 px, and measures every pair twice. First, each half's own sensor pattern,
moved as that half's frames really were: a correlation beyond 0.02 either way, not a
number, or under 30% overlap is refused. Second, the real halves: the variance of
their difference against what their frames' scatter predicts, with limits fixed
before the first measurement (blank sky 0.85 to 1.15, rings round stars 0.85 to 1.5,
large-scale difference at most 0.5 of the fine noise). **35 pairs from 17 sessions
pass** (24 to train, 1 to watch training, 10 to test): sky 0.975 to 1.012, rings 0.977
to 1.039, large-scale at most 0.096, sensor correlation at most 0.013. M31-P4's
pairs were refused (sky 0.50, large-scale 1.58), which the sensor check alone had
passed, and 2 frames were refused for alignment.
Planted defects, six random patterns each in three sessions, show what would reach
a pair at 0.02: flat mottling of 0.15 to 0.37 of one frame's noise, rows of 0.29 to
0.70, columns of 0.23 to 0.52 where detected, single pixels of 1.4 to 2.1 or not at
all. Each kept session names its frames, masters, code, settings and software, and
is rebuilt when any of them changes; `trainset.py verify` reads every input and pair
again against the hashes kept when it was built (1,217 files, none different).
Removing a faulty missing-pixel test from the half-stacks left the first pair of all
18 sessions unchanged on a one-in-sixteen pixel sample.

**The level jumps do not change a normal stack.** Four sessions stacked as now and
with every frame levelled (up to 40 frames each; 4 to 22 frames off by 3 counts or
more, the largest by 17): the sky moved by 0.11 to 0.32 counts, the grain by at most
0.14%, the share of pixels kept by at most 0.01 points, and star flux and width in
fixed apertures by less than 0.0001%. Stacking is left as it is.

**Stage C, not accepted.** A 4-level U-Net, 12,000 steps (about 30 minutes without
the survey, 50 with). One model used our frames alone; one added 767 IGAPS Ha
frames with nebula, at our scale with our noise, as half of each batch's loss.
Medians over the 10 held-out sessions, at equal grain against a Gaussian blur,
stars taken from the input:

| Grain left | Faint filament kept: own / with IGAPS / blur | Error above the reference's noise: own / with IGAPS / blur |
|---|---|---|
| 70% | 87% / 88% / 98% | 0.750 / 0.753 / 0.757 |
| 50% | 78% / 80% / 96% | 0.557 / 0.560 / 0.566 |
| 30% | 70% / 72% / 92% | 0.380 / 0.381 / 0.389 |

The filaments were planted at the noise level. At three times the noise the
network and the blur are within about 3 points. The network has lower error than
the blur in 7 of 10 sessions alone and 9 of 10 with IGAPS, by about 1%, against
the 10% required. It beat the starlet baseline by about 10% at the model's own
strong smoothing, which says more about that baseline than the model. Star
brightness with stars protected: median within 0.1%, worst session 1.3% (0.9%
with IGAPS). Width: median within 0.2%, worst session 7.1% (6.3% with IGAPS),
over the 3% limit.

The 10 test sessions are **two independent targets**. Faint filament kept at 50%
grain, by target and filter (with IGAPS, own frames alone in brackets; blur 96 to 97%
in every row), and sessions with lower error than the blur:

| Target and filter | Sessions | Filament kept | Lower error than blur |
|---|---:|---|---|
| IC 405 Ha | 5 | 80% (78%) | 5 (4) |
| IC 405 SII | 1 | 78% (80%) | 1 (1) |
| NGC 2174 Ha | 2 | 79% (78%) | 1 (1) |
| NGC 2174 OIII | 1 | 80% (83%) | 1 (1) |
| NGC 2174 SII | 1 | 80% (74%) | 1 (0) |

These models were trained before the survey noise was rescaled to the noise map and
before the pair checks above, with M31-P4 still in training, and have not been
retrained. Survey frames within 2 degrees of a held-out field are now refused (the
nearest used was 2.03 degrees away). Next: Ha, OIII and SII
from more independent targets, dithered by at least 10 px, before changing the network.

### 5.2 The rest of this experiment (planned 22-23 November 2026)

Models are compared with the same pairs, steps and tests. **Model A** is our frames
alone. **Model B** adds IGAPS, the masters and the survey's real repeated pairs, and
can only show that the mixture helped. So each source is then added to A by itself:
IGAPS, Seti Astro's masters, AstrophotoMarket's masters and Seti Astro's real OIII
pair. Each model keeps a `.sources.json`: its sources, how each master was resampled,
and the crops each gave.

Seti Astro's 101 raw OIII subs of SNR G082.2+05.3 go through `externalpairs.py`, with
that camera's own darks and flats, in a folder apart from the active pairs. 95 subs
were used, and **1 of 4 pairs passed** the same checks; the others failed on the
sensor pattern (0.022) or on star rings (1.70 and 1.71). Those subs were at -8 to -1
degrees and their dark at -15, which may contribute. It is one field, so it does not
stand in for independent OIII targets.

**NGC 2174 and IC 405 now report results but cannot accept a model alone.** After
this many comparisons they have become part of development. Acceptance needs a field
that no model or choice has yet seen, under the unchanged limits of section 7.

### 5.3 Masters dropped from the first source comparison (found 23 November 2026)

Masters were identified by their folder and filter. Seti Astro keeps different targets
in folders all named `master`, so **9 different masters of the 61 files were dropped**
from every model trained with them, and the Seti Astro and mixed results in 5.2 did not
use that source in full. Each file now has its own identity, and only the same pixels
in two formats count as a duplicate: of 61 files, 37 decode as narrowband masters, 1 is
a duplicate and 36 are sampled. Each model's `.sources.json` gives every master's chance
of being drawn, its crops, and why each unused file was not used. Those models are to be
trained again before their source comparison is relied on.

## 6. Later models

### 6.1 Star removal (stage D)

Supervised, with partly synthetic pairs. Take nebula patches with their stars
removed by stage A, then add stars of known position and brightness, using
star shapes measured from our own frames and real brightness distributions
from Gaia. `plant.py` already plants stars in frames.

The weakness: the base patches contain stage A's leftovers. The loss therefore
ignores pixels where real stars were removed, and is taken only where the
answer is known. Star-dense Milky Way fields matter most: StarNet's author
reports this was the focus of its second version's extra training data.

### 6.2 Sharpening and star repair (stage E)

Supervised: take a sharp image, degrade it with our measured, field-varying
star shapes and real noise (today's darks included), and train the network to
undo it. **The choice of sharp data decides how honest this is.**

| Source | Sharpness | Field | Suitable? |
|---|---|---|---|
| [IPHAS](https://arxiv.org/abs/1406.4862) | 0.33"/px, median 1.1" in Ha | 1,860 sq deg of northern Milky Way | **Best first choice**: real Ha nebulae, wide, about our sky |
| [VPHAS+](https://doi.eso.org/10.18727/archive/65) | Not established | About 2,080 sq deg of southern Milky Way, Ha | Second source |
| [DECaPS2](https://arxiv.org/abs/2206.11909) | Not established here | 6.5% of the sky, the southern plane | Broadband star fields |
| [Hubble via MAST](https://archive.stsci.edu/hst/) | Far sharper | WFC3 is about 166" x 175", some 110 of our pixels | Real F656N, F502N, F673N, but too small and too sharp: teaches detail we could never resolve |
| Hobbyist uploads | Varies | Varies | **No**: licences mostly unstated |

**Pixel scale is not resolution.** IPHAS's median is 1.1" and our stars are
about 5.4" to 6.8", so the gap is **five to six times in FWHM**. The target of
training is therefore not the IPHAS image itself: it is IPHAS blurred to a
modest improvement over our measured PSF, so the network is asked for a small,
defensible gain. Asking it for IPHAS's or Hubble's detail is how a sharpener
starts inventing structure.

**Quality gate for IPHAS.** Use only frames with `in_dr2` true and `qcgrade`
A (A++, A+ or A; grades are per field), reading `qcproblems`, `seeing` and
`elliptic`. The page says moonlight and other background remain in the images,
and describes a 2D background filter for its sky metrics, but does not say whether
that filter is applied to the delivered pixels. So before any training a small
sample is checked for whether known extended emission survives.

**How much gain.** A first ceiling of a 5 to 10% reduction in measured star
width, with no entitlement even to that. A gain counts only where an independent
deeper stack supports it.

**Order.** Star-shape repair is trained and accepted first, against our measured
field-varying PSF. Sharpening of nebulae is a separate, later model.

**Hallucination is the main risk here.** It is measured directly in published
work ([SUNet deconvolution](https://arxiv.org/abs/2405.07842),
[CHEM](https://arxiv.org/abs/2512.09806), [FluxFlow](https://arxiv.org/abs/2605.03749)),
and models of similar accuracy can differ in how much they invent. So a
sharpener must pass the false-detail measures of section 7, and if it cannot
beat plain deconvolution without inventing detail, it is not shipped.

## 7. Acceptance

Measured once per model version on held-out targets, recorded in
`docs/validation.md`. Thresholds below are proposed starting points.

**Reference without a clean image.** Stack a quarter of a held-out session's
frames as the input, and use the other three quarters as an independent
reference. Nothing the model saw is in the reference, so a detail it invents
will not be there.

Every figure is reported with its uncertainty (from the repeated splits) and
separately for stars, blank sky and nebula. These thresholds are starting
points, not validated limits.

| Measure | Denoiser passes when |
|---|---|
| Error against the independent reference, in sky and in nebula | At least 10% lower than the wavelet baseline at equal smoothing |
| Star flux in an aperture | Median change within 1%, no trend with brightness |
| Star width | FWHM change within 3% |
| Faint planted stars | At least as many recovered as in the untouched stack |
| False sources | No more detections absent from the reference than the baseline has |
| Faint extended signal | Outer nebula level kept within 5%, on planted faint glows |
| Flux spread | Scatter of star flux error, and its trend with brightness, no worse than the baseline; faint stars reported apart |
| Fine detail | Keeps comparable power at small scales against the reference, so a result cannot pass by being smoother |
| Across filters | Holds in Ha, OIII and SII separately, or is limited to those that pass; never averaged into one score |
| By eye | The owner prefers it on NGC 2174, beside the baseline |

A sharpener adds: star shape improved across the frame rather than only at the
centre, and new structure confirmed in a genuinely deeper independent stack of
the same field. Absence from a noisy reference does not prove a feature was
invented, so an unconfirmed feature counts as unproven, and the model is not
accepted on it.

## 8. Risks

| Risk | What limits it |
|---|---|
| Too little data for OIII and SII | Train across filters; collect more; limit a model to the filters that pass |
| Shared artefacts learned as signal | Pre-check in section 5; fix the level flips first |
| Invented detail | Pictures only, labelled, section 7's measures, survey data near our resolution |
| Old GPU loses PyTorch support | Pin 2.14 `cu126`; the trained model can be exported to run without it |
| Model tied to this rig | Intended. A collimation, focal length or camera change means re-measuring, and perhaps retraining |
| Effort better spent on exposure | A few more hours per filter likely beats any model; imaging always comes first |

## 9. Licences

| Data or tool | Status |
|---|---|
| Our own frames | Ours |
| Hubble via MAST | Sourced: mostly CC0 with acknowledgement requested; some collections excepted, such as the Digitized Sky Survey (non-commercial) |
| Legacy Surveys | Sourced: acknowledgement text and a credit line on images; no licence for the data found |
| IGAPS (IPHAS merged with UVEX) | Read 22 Nov 2026 at <http://www.star.ucl.ac.uk/IGAPS/>, hosted by UCL: 527,736 frames, 3.0 TB. Use this and not `iphas.org`, whose pages now carry unrelated gambling links and whose image paths return 404. No formal licence for the images was found; the observatory's policy puts data in the public domain after a year, and the team asks for citation and acknowledgement. Used, with those |
| Seti Astro public data (Franklin Marek) | <https://www.setiastro.com/publicdata>: "This data is here to be used", including testing tools, credit appreciated. The site does not mention model training, and its footer reserves rights. Used with credit by the owner's decision (22 Nov 2026); its IC 405 set is never used |
| AstrophotoMarket free datasets | Each listing states CC0, CC BY or CC BY-NC, and forbids redistributing the source FITS. Only those licences are used, the FITS are never shared, and each author is credited |
| VPHAS+, DECaPS2 | Public releases; **reuse terms not established. Check before downloading** |
| GraXpert models | Reported CC BY-NC-SA on a third-party mirror, unconfirmed; application GPL-3. Not used |
| StarNet | Free; licence not established. Not used |
| AstroBackyard samples | No licence stated. Not used without the author's agreement |
| RC Astro | Paid; automated use terms not read. Not used |

There is one training set and everything in it must be publishable: the owner will
not keep a private model on data a public one could not use, and the model stays free.
Any dataset goes in a manifest with its source, licence, date and acknowledgement
text. Models trained from it name that manifest.

## 10. Questions for review

1. Is matching towards the widest filter right when that filter's extra width
   may come from a focus difference that could be fixed at the telescope?
2. Is a 32-bit FITS the right format for the linear colour result?

## Sources

- Noise2Astro: <https://arxiv.org/abs/2209.07071>
- ASTERIS: <https://arxiv.org/abs/2602.17205>
- AstroSURE: <https://arxiv.org/abs/2604.16793>
- PAU Survey denoising: <https://arxiv.org/abs/2611.05447>
- SUNet deconvolution: <https://arxiv.org/abs/2405.07842>
- CHEM: <https://arxiv.org/abs/2512.09806>
- FluxFlow: <https://arxiv.org/abs/2605.03749>
- RC Astro stand-alone tools: <https://www.rc-astro.com/stand-alone-rc-astro-tools/>
- StarNet (original repository mirror): <https://github.com/Starvexx/starnet>
- GraXpert: <https://github.com/Steffenhir/GraXpert>
- Siril 1.4: <https://siril.org/download/2025-12-05-siril-1-4-0/>
- Generalized Hyperbolic Stretch: <https://siril.org/tutorials/ghs>
- PixInsight reference: <https://pixinsight.com/doc/>
- Astro Pixel Processor: <https://www.astropixelprocessor.com/with-unique-features/>
- StarTools modules: <https://www.startools.org/modules>
- PhotometricContinuumSubtraction: <https://app.astrobin.com/forum/topic/138868/new-script-photometriccontinuumsubtraction-pixinsight>
- photutils PSF matching: <https://docs.astropy.org/projects/photutils/en/stable/user_guide/psf_matching.html>
- PyTorch CUDA 12.6 notice: <https://dev-discuss.pytorch.org/t/notice-cuda-12-6-wheels-will-no-longer-be-published-from-pytorch-2-15-drops-maxwell-pascal-volta/3432>
- MAST data use: <https://archive.stsci.edu/publishing/data-attributions>
- Legacy Surveys acknowledgement: <https://www.legacysurvey.org/acknowledgment-old/>
- IPHAS DR2: <https://arxiv.org/abs/1406.4862>
- IPHAS images and data: <https://www.iphas.org/images>, <https://www.iphas.org/data.html>
- ING data ownership: <https://www.ing.iac.es//astronomy/observing/data_ownership.html>
- Noise2Noise: <https://proceedings.mlr.press/v80/lehtinen18a.html>
- VPHAS+: <https://doi.eso.org/10.18727/archive/65>
- DECaPS2: <https://arxiv.org/abs/2206.11909>
