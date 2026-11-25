"""One frame of a failing session: which pixels each cleaning replaces inside its brightest stars, and the light
taken, with one star's centre shown before and after. Diagnostic only; reads copies."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, ".")
import numpy as np
import clip, clip13, clip14rule, stacking  # noqa: F401
import importlib
mod = importlib.import_module(sys.argv[1])          # clip533 or clip76: its calibration
name = sys.argv[2]
f = sorted((clip.WORK / "input" / name).glob("light-*.fits"))[3]
_, h = stacking.load_light(f)
x = clip.base(str(f), float(h["EXPTIME"]), int(float(h.get("GAIN", 0))))
stars = stacking.find_stars(np.dstack([x, x, x]).sum(axis=2), limit=300)
order = np.argsort(-stars[:, 2])[:60]
old = clip.current(x); new = clip14rule.pair_aware(x)
yy, xx = np.mgrid[-4:5, -4:5]; disc = np.hypot(yy, xx) <= 4
for label, y in (("old", old), ("new", new)):
    lost, hit = [], 0
    for i in order:
        cx, cy = int(round(stars[i, 0])), int(round(stars[i, 1]))
        if not (6 < cy < x.shape[0] - 6 and 6 < cx < x.shape[1] - 6):
            continue
        a, b = x[cy - 4:cy + 5, cx - 4:cx + 5], y[cy - 4:cy + 5, cx - 4:cx + 5]
        back = np.median(x[cy - 12:cy + 13, cx - 12:cx + 13])
        lost.append(float(((a - b)[disc]).sum() / max(((a - back)[disc]).sum(), 1e-6)))
        hit += int(((a != b) & disc).sum())
    print(label, "brightest 60 stars: median light taken", round(float(np.median(lost)), 3), "pixels replaced", hit)
i = order[5]; cx, cy = int(round(stars[i, 0])), int(round(stars[i, 1]))
np.set_printoptions(linewidth=200, precision=0, suppress=True)
print("star", cx, cy, "fwhm", round(float(stars[i, 3]), 2))
print("before\n", x[cy - 3:cy + 4, cx - 3:cx + 4]); print("new\n", new[cy - 3:cy + 4, cx - 3:cx + 4])
