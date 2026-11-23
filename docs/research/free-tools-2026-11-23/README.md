# Free noise-reduction tools against our models, 23 November 2026

The scripts and results behind `docs/free-tools-plan.md`. GraXpert 3.0.2, Cosmic Clarity's
AI3.6 model and Siril 1.4.5 ran on copies of ten held-out half-stacks with planted faint
filaments, then were scored at equal grain against a blur and an independent stack.

- `prep.py` makes the inputs, `run.py` and `siril.py` run the tools, `score.py` scores them.
- `sites.py` makes copies of the real stacks for `colour.py` to turn into comparison pictures.
- `background.py` compares background removal; `background-scores.json` holds its results.
- `stars.py` compares star removal; `stars-scores.json` holds its results.
- `scores.json` holds every measurement; `sites.json` holds the strength that gave half the grain.

`prep.py` and `score.py` read the held-out pairs under `~/telescopeyoke-laptop/training/pairs3`
on the desktop, so those stay when other training data is removed.
