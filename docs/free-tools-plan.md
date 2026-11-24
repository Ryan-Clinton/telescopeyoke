# Plan: use free tools for the picture pipeline

Status: **noise reduction is built (`colour.py --denoise graxpert`), the stacking's star-core fault is fixed, star removal is close; sharpening, stretch and colour calibration are still to test.**
Written 23 November 2026. `final.fits` and every other kept stack were only read.

**The aim:** TelescopeYoke does the best possible job of automating the freely available
tools. Anyone who wants it to handle their image processing downloads those tools
themselves; everything else in TelescopeYoke works without them. Training our own network
is no longer part of the way there.

## What was measured

The same ten held-out half-stacks of IC 405 and NGC 2174 (Ha, OIII, SII) and the same
planted faint filaments that judged our own models. Each method was mixed back with the
input until it had the stated share of the original grain, so all are compared at the same
noise. "Error" is against an independent stack of other frames, as a share of a plain
blur's error at that grain; lower is better.

| Method | Filament kept at 70 / 50 / 30% grain | Error against blur at 70 / 50 / 30% |
|---|---|---|
| Plain blur | 98.2 / 96.4 / 92.0 | 1.000 |
| **GraXpert 3.0.2 denoise** | **93.0 / 88.5 / 84.0** | **0.989 / 0.971 / 0.932** |
| DeepSNR 1.3.2 | 93.5 / 89.1 / 84.9 | 0.990 / 0.974 / 0.943 |
| Cosmic Clarity (AI3.6) | 91.5 / 85.9 / 80.2 | 0.994 / 0.985 / 0.975 |
| Our best model | 90.3 / 84.1 / 78.0 | 0.994 / 0.984 / 0.960 |
| Siril 1.4.5 NL-Bayes, defaults | 85.3 / 76.0 / 66.9 | 1.007 / 1.017 / 1.039 |
| Seti Astro Suite Pro 1.24.8, AI4 denoise | 78.8 / 65.3 / 51.7 | 1.001 / 1.027 / 1.135 |

- **GraXpert beat every model we trained on both measures, at every noise level.**
- **DeepSNR came closest and does not replace it:** it kept slightly more of the line at every
  grain but was slightly further from the independent stack at every grain, so it is not at
  least as good on both. The faintest 5% of stars in its worst stack read 28% low (GraXpert 21%).
  The suite's newer AI4 denoise did worse than its own older AI3.6 on both measures here.
- A plain blur still keeps more of a thin planted line, so no AI tool here is free of
  smoothing. GraXpert gets closer to the independent stack, and looks cleaner.
- Median star flux through GraXpert was 0.999 of the input, but the faintest 5% of the
  measured stars in the worst stack read about 21% low. **Denoised data is for pictures
  only, never for photometry, depth or discovery.**
- On the GTX 1080 a 4.5-megapixel stack took about 50 s in GraXpert and 9 s in Cosmic Clarity.

These are ten stacks from one rig, with each tool's model as released. Stretching,
sharpening and colour calibration have not been compared yet.

### Background removal

Known gradients (a tilt, a bowl, a corner glow) and four faint glows were added to copies of
five aligned IC 405 and NGC 2174 stacks. "Left" is how much of the gradient stayed, so lower
is better; "glow kept" should be near 1. Medians of the five, with the worst stack in brackets.

| Method | Tilt left | Bowl left | Corner left | Glow kept |
|---|---|---|---|---|
| **Our sky model** | **0.11 (0.23)** | **0.17 (0.31)** | 0.19 (0.27) | **0.88 (0.85)** |
| GraXpert AI, smoothing 0.5 | 0.13 (0.26) | 0.18 (0.28) | **0.10 (0.26)** | 0.86 (0.56) |
| GraXpert AI, smoothing 0.1 | 0.14 (0.28) | 0.19 (0.28) | 0.11 (0.26) | 0.85 (0.42) |
| Siril polynomial, degree 2 | 0.09 (0.62) | 0.30 (0.72) | 0.62 (0.67) | 0.90 (0.88) |
| Siril RBF, defaults | 0.30 (0.38) | 0.41 (0.64) | 0.44 (1.03) | 0.57 (0.43) |

**Our sky model stays.** GraXpert is about twice as good on a corner glow, but on IC 405's
SII it took off 44 to 58% of a faint glow where ours took 15%, and losing nebula is the worse
fault. Our model is also told where the nebula is from the Ha stack, which the tools are not.
Siril ran with automatic samples; placing them by hand might do better but is not automation.

Added on 24 November 2026, the same five stacks and measures, the tool's own defaults:

| Method | Tilt left | Bowl left | Corner left | Glow kept |
|---|---|---|---|---|
| Seti Astro Suite Pro ABE (polynomial 2 and RBF) | 0.26 (0.30) | 0.27 (0.33) | 0.30 (0.38) | 0.86 (0.84) |
| Seti Astro Suite Pro ABE, polynomial 2 only | 0.10 (0.12) | 0.31 (0.54) | 0.38 (0.54) | 0.95 (0.90) |

Neither replaces ours. The polynomial alone keeps more of a faint glow and takes off more of a
tilt, but leaves about twice as much of a bowl or a corner glow. GraXpert's non-AI methods
(RBF, splines, kriging) were not tried: from its command line they need sample points saved
from its window, so they cannot run on their own.

### Star removal

Seti Astro Suite Pro 1.24.8's Dark Star (AI4 mono model) against our plain code, in stretched
brightness. Dark Star alone also removed faint nebula, up to 72% of a planted glow on a galaxy
stack, so it was tried as a blend: its result only on detected stars, and only the part
standing above the broad change. Six stacks, medians:

| Method | Star left | Brightest 20 left |
|---|---|---|
| Our code | 0.022 | 0.029 |
| **Dark Star, blended** | **0.004** | **0.006** |

The pass mark, set before the last check, was a thin faint line kept to within 5 points of our
code on two stacks not used to tune the blend:

| Unseen stack | Line kept, ours | Line kept, blend | Glow, blend (1.00 is perfect) |
|---|---|---|---|
| M33, 16 October | 0.977 | 0.991 | 1.037 |
| M81 and M82, 2 November | 0.973 | **0.863** | 1.021 |

**The blend failed that mark on M81 and M82.** By eye it removed stars much better and left no
ghosts, but a very bright star kept a faint ring and spikes.

**Second try, 24 November 2026: GraXpert first, as a picture has it.** Each method started from the
same GraXpert-denoised stack. On five stacks not used before (IC 1848, M1, M27, IC 405, M31), the
blend kept the line on all five (0.94 to 1.02, ours 0.52 to 0.65). Their scores also showed it
leaving IC 1848's brightest stars whole: a clipped core reads as not round, and the blend skipped
it. With that fixed (a clipped core Dark Star took far down counts as a star), the same pass mark
was applied to five more stacks never used for any of this work:

| Fresh stack | Star left, ours / blend | Brightest 20 left, ours / blend | Line kept, ours / blend | Glow, blend |
|---|---|---|---|---|
| M45 | 0.013 / 0.001 | 0.146 / 0.013 | 0.264 / **0.997** | 1.021 |
| NGC 7000 | 0.014 / 0.000 | 0.035 / 0.007 | 0.587 / **1.022** | 1.038 |
| M37 | 0.018 / -0.003 | 0.060 / 0.004 | 0.634 / **0.771** | 1.053 |
| NGC 7331 | 0.011 / -0.003 | 0.024 / 0.003 | 0.364 / **0.994** | 1.031 |
| M34 | 0.031 / 0.001 | 0.065 / 0.010 | 0.654 / **0.892** | 1.029 |

**It passed on all five.** Dark Star used whole kept only 1% to 62% of the line. StarNet2
blended the same way scored about the same as Dark Star on the first five; Dark Star is kept as it
needs no further licence step. By eye, the stars go and the nebula and galaxies are untouched, but
the very brightest stars (M45's) stay almost whole, and one left a small black dot beside it.

**In the full pictures it is not right yet.** IC 405 in HSS looked right: AE Aurigae stays white
with no ring, the small stars are tighter and the filaments are untouched. NGC 2174 in SHO showed
a few close double stars in one filter's colour, red (SII) or blue (OIII): taken apart filter by
filter, a double read as not round in one filter and was kept there. Counting any detection Dark
Star took down by 0.3 or more as a star cleared most of them, and passed again on five more stacks
never used before:

| Fresh stack | Line kept, ours / blend | Brightest 20 left, ours / blend |
|---|---|---|
| M31, panel 2 | 0.202 / **0.986** | 0.017 / -0.002 |
| M31, panel 7 | 0.157 / **0.995** | 0.016 / 0.001 |
| NGC 3310 | 0.145 / **1.014** | 0.014 / 0.005 |
| SN 2026sqf's field | 0.400 / **1.020** | 0.021 / 0.013 |
| M33, 2 November | 0.284 / **1.009** | 0.010 / -0.002 |

Two coloured doubles are still left in NGC 2174, so **it is not wired into the pictures.** The
next step is to decide each star once, for all the filters together. `freetools.py stars` runs it
on a copy of a stack, and the change to `colour.py` is kept as
`docs/research/free-tools-2026-11-23/colour-darkstar.patch`.

### The star-core clipping fault (in the science stack)

`stacking.clean` replaces any pixel far brighter than its neighbours, in every frame before
alignment. On this rig's sharp stars that includes star cores. On 8 sessions, against no cleaning,
the brightest third of stars kept 92.7% to 99.9% of their light in the stack. In Tabby's star's
frames, measured in a 1.5 FWHM aperture, stars lost 11% (the faintest) to 23% (the brightest) of their light, and the light
curves' scatter rose from 24 to 35 mmag on the brightest stars and from 41 to 57 on the faintest
(85 frames of 21 November). This touches every stack, depth measurement and photometry run.

The candidate (scripts kept on the desktop under `training/stackexp`): a map of the sensor's fixed
defects, from the median of each session's frames, then the old test only on a pixel whose
second-brightest neighbour is barely above the background, as a hot pixel's or a cosmic ray's
is and a star core's is not. Pass mark, set before it ran, on every
session: brightest-third flux within 0.5%, peak within 1%, grain within 1%, fixed defects left no
worse than today, visible cosmic-ray pixels at most today's plus 10.

- It keeps every star's light (1.000) and the Tabby scatter back at the uncleaned level, and
  leaves fewer fixed defects than today on every session.
- It passed on 5 of the 8 sessions used to make it, and on all three unseen sessions it ran on (M33,
  5 November 01:21; Tabby, 22 November 18:25 and 18:53). On the other 3 it left 12 to 20 more visible
  cosmic-ray pixels than today.
- The neighbour test alone, with no map, left 3.4 times as much of the planted fixed defects.
- Siril 1.4.5's winsorized sigma rejection (3, 3) across the aligned frames, after the same
  defect map, caught the cosmic rays but failed the mark on all 11 sessions it ran: its grain
  differed from the plain stack's by 2% to 73% and the brightest stars' light by up to 20%. On two
  sessions it threw out 18% of all pixels, taking the sky's drift between frames for outliers. With Siril's own normalisation
  its stack was on a different scale from the frames and could not be compared fairly.

**Adopted on 24 November 2026** in `stacking.clean`, with the map made by `restack.py` from up to
24 of the session's kept frames. A map pixel whose third-brightest neighbour also stands out is
left alone, so a star that did not move between frames is never taken for a defect. A live stack
has no map yet and uses the neighbour test alone; the restack after a run uses both. Restacked
with it, Tabby's 85 frames of 21 November 20:05 kept 12% more starlight than the old cleaning
(26% more for the brightest third) with the same grain and no lone spikes left. Stacks already
made are not changed until they are restacked.

## What each stage becomes

| Stage | Today | Plan | State |
|---|---|---|---|
| Calibration, alignment, science stack | `stacking.py` | **Keep.** Photometry and discovery depend on its checks and records | Stays |
| Star-core clipping fault | Old cleaning cut star cores | A defect map and the lone-pixel test; Siril's rejection failed | Built |
| Noise reduction | Optional in pictures | **GraXpert**, on each filter's linear stack; DeepSNR and the suite's AI4 tried and not better | Built |
| Background and gradients | Our sky model | **Keep ours**: no tool did as well overall (GraXpert AI, Siril, Seti Astro ABE) | Tested |
| Star removal | Plain code | Seti Astro Suite Pro's Dark Star, blended | Passed the mark on two sets of five unseen stacks; two coloured doubles left in NGC 2174, not in the pictures yet |
| Sharpening and deconvolution | Our steps | GraXpert and Cosmic Clarity, with star and nebula checks | To test |
| Stretch | Ours, with a GHS option | Siril GHS | To test |
| Colour calibration, broadband | Star average | Siril SPCC | To test |
| Palette combination | `colour.py` | Keep unless Siril or Seti Astro Suite does it better | To test |

A tool replaces our code only if it does at least as well on the measures for that stage
on stacks not used to choose it, and the science stack stays untouched. When one wins, our
own code for that stage is deleted, so there aren't two ways of doing it.

## How it fits together

`colour.py` becomes a thin runner: take the science stacks, copy them, call each tool's
command line in turn, and record the tool, version and settings beside the picture. A
missing tool is reported plainly. Tools are installed by the user and never bundled.

**Licences.** GraXpert's program is GPL-3 and its denoise model is CC BY-NC-SA 4.0. Using
them for non-commercial pictures fits that; TelescopeYoke must not ship the model. Siril is
GPL-3. Each is called as a separate program.

Cosmic Clarity's own repository (MIT) was archived in 2026 and its work continues in Seti Astro
Suite Pro (GPL-3), which has a command line. **The suite's current AI models are not open
source:** their licence allows personal, non-commercial use within the suite only, and forbids
redistribution and use outside it. TelescopeYoke may only call the suite's own command, on a
copy the user installed, with models the user downloaded and accepted themselves. The owner
accepted those terms for this rig on 23 November 2026.

## What happens to the denoiser

Retired on 23 November 2026, with no separate repository and no public request for data.
Its code is in git history, the comparison's scripts are in
`docs/research/free-tools-2026-11-23/`, and `docs/validation.md` records the result. The
training data is deleted only once the owner confirms, keeping the held-out test pairs.
