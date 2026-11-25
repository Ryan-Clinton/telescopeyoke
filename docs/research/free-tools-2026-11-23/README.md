# Free noise-reduction tools against our models, 23 November 2026

The scripts and results behind `docs/free-tools-plan.md`. GraXpert 3.0.2, Cosmic Clarity's
AI3.6 model and Siril 1.4.5 ran on copies of ten held-out half-stacks with planted faint
filaments, then were scored at equal grain against a blur and an independent stack.

- `prep.py` makes the inputs, `run.py` and `siril.py` run the tools, `score.py` scores them.
- `sites.py` makes copies of the real stacks for `colour.py` to turn into comparison pictures.
- `run_more.py` and `score_more.py` ran DeepSNR 1.3.2 and the suite's AI4 denoise the same way
  (24 November 2026); `noise-more-scores.json` holds their results.
- `background.py` compares background removal; `background-scores.json` holds its results, and
  `background-abe-scores.json` Seti Astro Suite Pro's ABE, added on 24 November 2026.
- `stars.py` compares star removal; `stars-scores.json` holds its results. `stars_chain.py` runs
  GraXpert then Dark Star, and `stars_starnet.py` GraXpert then StarNet2 2.6.2, each whole and
  blended; `stars-chain-scores.json` and `stars-starnet-scores.json` hold their results on five
  stacks not used before, from before the blend was fixed for clipped star cores. StarNet's and
  DeepSNR's pictures are deleted once measured: only their scores are kept.
- `stars-chain-v4-scores.json` and `stars-chain-v5-scores.json`: the blend on two more sets of
  five stacks never used before, after each fix (clipped cores, then close doubles).
- `stars_union.py` checks stars decided once for all filters on M33's R, G and B; `stars-union-scores.json` holds the result.
- `eyecheck.py` makes the eye check of `freetools.remove_stars` round the brightest star and the
  darkest patch of three stacks. `colour-darkstar.patch` was the change to `colour.py` that put
  Dark Star in the pictures, before stars were decided for all filters at once; it is now in `colour.py`.
- `spcc.py` compares colour calibration on Gaia stars (`spcc-scores.json`).
- `stretch.py` compares stretches (`stretch-scores.json`); `palette.py` makes NGC 2174 the plain free way for comparing by eye.
- `sharpen.py` compares sharpening on the ten held-out pairs after GraXpert; `sharpen-scores-cpu.json` (ours, Siril) and `sharpen-scores-gpu.json` (the suite's sharpen) hold its results.
- `confirmation-protocol.md` fixes the rules for other people's data before it is read;
  `deviations.md` lists every change made after, and `confirmation-results.md` the results
  (25 November 2026). Their scripts are here (`clip76.py`, `clip533.py`, `clipmean.py`,
  `clip_m3.py`, `clip13g.py`, `corecut.py`, `framewidth.py`, `ds_sessions.py`, `ds-pictures.sh`,
  `foraxx.py`); they run on the desktop beside the harness in `training/stackexp/code`.
- `scores.json` holds every measurement; `sites.json` holds the strength that gave half the grain.

`prep.py` and `score.py` read the held-out pairs under `~/telescopeyoke-laptop/training/pairs3`
on the desktop, so those stay when other training data is removed.
