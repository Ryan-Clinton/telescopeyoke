"""Stars decided once for all filters (freetools.remove_stars_together) on M33's R, G and B stacks of 5 November,
never used for any star test, against our old star removal after the same GraXpert denoise.

The filters are lined up as colour.py lines them up, and the same faint glows and lines are planted in all three.
The same pass mark as before: a planted thin line kept to within 5 points of our code, in every filter.
The originals are only read; Dark Star's images are not kept.
"""
import json, sys
from pathlib import Path
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE / "ft")); sys.path.insert(1, str(Path.home() / "telescopeyoke-laptop/remote/code"))
import numpy as np
from scipy import ndimage as N
import colour
import freetools

sys.argv = sys.argv[:1]
ns = {"__file__": str(HERE / "stars.py")}; exec((HERE / "stars.py").read_text().split("results = {}")[0], ns)
W, load, stretcher, ours, plants, star_scores = (ns[k] for k in ("W", "load", "stretcher", "ours", "plants", "star_scores"))

raw = {b: load(f"M33{b}-u") for b in "RGB"}
rows, cols = min(p.shape[0] for p in raw.values()), min(p.shape[1] for p in raw.values())
raw = {b: p[:rows, :cols] for b, p in raw.items()}     # cropped first, then lined up, as colour.py does
ref = np.nan_to_num(raw["R"]); reference = {"square": colour.stacking.centre_square(ref), "stars": colour.stacking.find_stars(ref)}
planes = {"R": raw["R"]}
for b in "GB":
    moved, info, _ = colour.lined_up(raw[b], reference)
    if not colour.fits_well(info): sys.exit(f"{b} did not line up")
    planes[b] = moved
good = np.all([np.isfinite(p) for p in planes.values()], axis=0)
# The block all three cover: B sits 821 px from R, so no whole row is covered by all three.
c = np.flatnonzero(good.mean(axis=0) > .5)
r = np.flatnonzero(good[:, c[0]:c[-1] + 1].mean(axis=1) > .98)
c = np.flatnonzero(good[r[0]:r[-1] + 1].mean(axis=0) > .98)
planes = {b: np.nan_to_num(p[r[0]:r[-1] + 1, c[0]:c[-1] + 1], nan=float(np.nanmedian(p))) for b, p in planes.items()}
glow, line = plants(planes["R"].shape)

cases, s, truth, grains = {"base": {}, "glow": {}, "line": {}}, {}, {}, {}
for b, x in planes.items():
    noise = 1.4826 * float(np.median(np.abs(x - np.median(x)))); s[b] = stretcher(x); grains[b] = freetools.grain(x)
    g, li = x + 3 * noise * glow, x + 5 * noise * line
    truth[b] = {"glow": s[b](g) - s[b](x), "line": s[b](li) - s[b](x)}
    for case, v in (("base", x), ("glow", g), ("line", li)):
        cases[case][b] = freetools.denoise(v)
together = {case: freetools.remove_stars_together(clean, grains) for case, clean in cases.items()}

results = {}
for b in planes:
    u = {case: s[b](cases[case][b]) for case in cases}
    made = {"ours-after-graxpert": {case: ours(cases[case][b], s[b]) for case in cases},
            "darkstar-together": {case: s[b](together[case][b]) for case in cases}}
    results[b] = {}
    for name, out in made.items():
        row = star_scores(u["base"], out["base"])
        for key, mask in (("glow", glow), ("line", line)):
            d = N.gaussian_filter(out[key] - out["base"], 1.5); cc = N.gaussian_filter(truth[b][key], 1.5); w = mask > .3
            row[key + "_kept"] = round(float((d[w] * cc[w]).sum() / (cc[w] ** 2).sum()), 3)
        results[b][name] = row; print("M33", b, name, row, flush=True)
json.dump(results, open(W / "union-scores.json", "w"), indent=1)
