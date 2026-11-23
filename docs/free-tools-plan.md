# Plan: use free tools for the picture pipeline

Status: **a plan, measured for noise reduction only. Nothing in the pipeline has changed.**
Written 23 November 2026. `final.fits` and every other kept stack were only read.

The goal stays the one in `docs/image-processing-spec.md`: a finished colour picture close
to what a skilled person gets from the paid tools, without buying them. Training our own
network is no longer part of the way there.

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
| Cosmic Clarity (AI3.6) | 91.5 / 85.9 / 80.2 | 0.994 / 0.985 / 0.975 |
| Our best model | 90.3 / 84.1 / 78.0 | 0.994 / 0.984 / 0.960 |
| Siril 1.4.5 NL-Bayes, defaults | 85.3 / 76.0 / 66.9 | 1.007 / 1.017 / 1.039 |

- **GraXpert beat every model we trained on both measures, at every noise level.**
- A plain blur still keeps more of a thin planted line, so no AI tool here is free of
  smoothing. GraXpert gets closer to the independent stack, and looks cleaner.
- Median star flux through GraXpert was 0.999 of the input, but the faintest 5% of the
  measured stars in the worst stack read about 21% low. **Denoised data is for pictures
  only, never for photometry, depth or discovery.**
- On the GTX 1080 a 4.5-megapixel stack took about 50 s in GraXpert and 9 s in Cosmic Clarity.

These are ten stacks from one rig, with each tool's model as released. Background removal,
stretching, star removal, sharpening and colour calibration have not been compared yet.

## What each stage becomes

| Stage | Today | Plan | State |
|---|---|---|---|
| Calibration, alignment, science stack | `stacking.py` | **Keep.** Photometry and discovery depend on its checks and records | Stays |
| Star-core clipping fault | Open | Fix in `stacking.py`, comparing with Siril's rejection | To do |
| Noise reduction | None in pictures | **GraXpert**, on each filter's linear stack | Measured |
| Background and gradients | Our sky model | GraXpert AI, then Siril, against ours | To test |
| Star removal | Plain code | Cosmic Clarity Dark Star; StarNet if its terms allow | To test |
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
them for non-commercial pictures fits that; TelescopeYoke must not ship the model. Cosmic
Clarity's repository is MIT, and Siril is GPL-3. Each is called as a separate program.

## What happens to the denoiser

Retire it, with no separate repository and no public request for data:

- Remove `denoiser.py`, `trainset.py`, `externalpairs.py` and the request page.
- Keep one small scoring script from this comparison, since it is what chose the tool.
- Record in `docs/validation.md` what was found and why it stopped.
- Delete the training data and models once the owner has confirmed.
