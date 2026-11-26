"""CANDIDATE, NOT A VERDICT: the shipped lone-pixel rule with the pixels at found stars' centres spared
(find_stars on the frame; each centre's 3 by 3 left alone), on every Abell 1656 frame, beside the shipped rule.
Brightest-third flux and peak against the frame uncleaned, and how many pixels each rule replaces, so a
candidate that spares cosmic rays shows. Copies only; the full pass mark follows if this keeps the light."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, ".")
import numpy as np

import clipmean
import clip
import clip14rule
import stacking


def spared(x):
    stars = stacking.find_stars(x, limit=2000)
    keep = np.zeros(x.shape, bool)
    for sx, sy in stars[:, :2]:
        r, c = int(round(sy)), int(round(sx))
        keep[max(0, r - 1):r + 2, max(0, c - 1):c + 2] = True
    out = clip14rule.pair_aware(x)
    out[keep] = x[keep]
    return out


if __name__ == "__main__":
    name = clipmean.prepare("Abell1656", clipmean.NIGHTS["Abell1656"])
    clipmean.flat_for(clipmean.NIGHTS["Abell1656"])
    files = sorted((clip.WORK / "input" / name).glob("light-*.fits"))
    _, header = stacking.load_light(files[0])
    exposure, gain = float(header["EXPTIME"]), int(float(header["GAIN"]))
    for p in files:
        x = clip.base(p, exposure, gain)
        now, cand = clip14rule.pair_aware(x), spared(x)
        m = clip.measure({"none": x, "current": now, "aware": cand})
        row = {"frame": p.name, "shipped": m.get("current_brightest_third"), "spared": m.get("aware_brightest_third"),
               "replaced_shipped": int((now != x).sum()), "replaced_spared": int((cand != x).sum())}
        print(json.dumps(row), flush=True)
        with open(clip.WORK / "cleanstar.jsonl", "a") as f:
            f.write(json.dumps(row) + "\n")
