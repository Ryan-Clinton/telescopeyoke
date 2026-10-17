---
name: polar-align
description: Polar-align the mount by plate solving, telling the person which bolt to turn. Use when they ask to polar align, say the tripod has moved or its foot marks are lost, or as the polar step of nightly-setup. Needs focus first.
compatibility: telescopeyoke at the telescope with the mount and camera plugged in, focused, and a bright star in clear sky
allowed-tools: Bash(./polaralign.py --dry-run *) Bash(./ty mount status)
---

# Polar alignment

Only needed when the tripod has moved or its marks are lost; otherwise the
last alignment stands, so say that and skip it. The method and its pitfalls
are in `docs/calibration.md` ("Polar alignment") and
`docs/agents/setup-routine.md` step 5.

1. Focus first (the `focus` skill): the measurement is three plate solves.
2. A bright star in a part of the sky they said is clear (Vega in autumn
   evenings): `./ty mount goto Vega --solve`. Loading this skill because
   they said the tripod moved is not a go to slew: the move runs under
   nightly-setup's rule for moves.
3. Before the first measurement, they centre the two azimuth bolts.
4. `./polaralign.py --step 12` (dry-run first). A house or tree in the
   way of the third picture: a smaller `--step`.
5. After each round, tell them which bolt, which way and how far, in the
   program's own words, once. Never remind them to tighten: they tighten
   as they go.
6. Once they say they have turned it, run it again with `--turned` and
   what they turned, until the error is under 0.5°.

Report the final error and what it was at the start.
