# Plan: use free tools for the picture pipeline

Status: **noise reduction is built (`colour.py --denoise graxpert`); the other stages are still to test.**
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

**The blend failed that mark on M81 and M82, so it is not wired in.** By eye it removes stars
much better and leaves no ghosts, but a very bright star keeps a faint ring and spikes, and a
star on a filament can leave a soft patch.

## What each stage becomes

| Stage | Today | Plan | State |
|---|---|---|---|
| Calibration, alignment, science stack | `stacking.py` | **Keep.** Photometry and discovery depend on its checks and records | Stays |
| Star-core clipping fault | Open | Fix in `stacking.py`, comparing with Siril's rejection | To do |
| Noise reduction | Optional in pictures | **GraXpert**, on each filter's linear stack; DeepSNR and the suite's AI4 tried and not better | Built |
| Background and gradients | Our sky model | **Keep ours**: no tool did as well overall (GraXpert AI, Siril, Seti Astro ABE) | Tested |
| Star removal | Plain code | Seti Astro Suite Pro's Dark Star; StarNet if its terms allow | Tested: far better on stars, missed the thin-line mark on one of two unseen stacks |
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
