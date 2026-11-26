"""CANDIDATE: the shipped lone-pixel rule with each found star's centre (3 by 3) left alone. Imported after
clip14rule, it replaces clip14rule.pair_aware, so every harness that runs the shipped rule runs this instead."""
import numpy as np

import clip14rule
import stacking

shipped = clip14rule.pair_aware


def spared(x):
    stars = stacking.find_stars(x, limit=2000)
    keep = np.zeros(x.shape, bool)
    for sx, sy in stars[:, :2]:
        r, c = int(round(sy)), int(round(sx))
        keep[max(0, r - 1):r + 2, max(0, c - 1):c + 2] = True
    out = shipped(x)
    out[keep] = x[keep]
    return out


clip14rule.pair_aware = spared
