"""Single-frame star width (median FWHM of find_stars, px, at the harness's scale) for every session the cleaning
was tested on, beside its verdict: where the cleaning starts to cut cores. Reads only."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, ".")
import numpy as np
import clip, stacking
work = clip.WORK / "input"
out = {}
groups = {"own": [s.replace("/", "-") for s in __import__("clip12").SESSIONS], "set76": ["set76b-Ha-2025-10-10", "set76b-Ha-2025-11-02", "set76b-OIII-2025-10-10", "set76b-OIII-2025-10-29"],
          "raw533": ["raw533-Abell1656", "raw533-LBN552", "raw533-M81", "raw533-NGC7293"]}
for g, names in groups.items():
    if g == "set76":
        import clip76  # noqa: F401  its calibration and reader
    if g == "raw533":
        import clip533  # noqa: F401
    for n in names:
        files = sorted((work / n).glob("light-*.fits"))[:6]
        if not files:
            continue
        _, h = stacking.load_light(files[0])
        w = []
        for p in files:
            x = clip.base(str(p), float(h["EXPTIME"]), int(float(h.get("GAIN", 0))))
            s = stacking.find_stars(np.dstack([x, x, x]).sum(axis=2), limit=200)
            if len(s):
                w.append(float(np.median(s[:, 3])))
        out[n] = round(float(np.median(w)), 2) if w else None
        print(g, n, out[n], flush=True)
json.dump(out, open(clip.WORK / "framewidth.json", "w"), indent=1)
