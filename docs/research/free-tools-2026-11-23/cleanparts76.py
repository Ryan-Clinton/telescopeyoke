"""DIAGNOSTIC, NOT A VERDICT: where set 76's cleaning takes the stars' light (OIII of 10 October loses 83% in the
stack). Single frames, every fourth: the guarded defect map's replacement alone, the shipped lone-pixel rule alone,
and both, each against the frame uncleaned (brightest-third stars), with the frame's star width and how many map
pixels sit on stars. As cleanparts.py did for Abell 1656. Copies only."""
import json
import sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, ".")
import numpy as np
from scipy import ndimage as N

import clip76g  # sets clip.base and load_light for set 76
import clip
import clip3
import clip13g
import clip14rule
import stacking

if __name__ == "__main__":
    for name, night in (("OIII", "2025-10-10"), ("Ha", "2025-10-10")):
        clip76g.bias(); clip76g.flat(name)
        session = clip76g.prepare(name, night)
        files = sorted((clip.WORK / "input" / session).glob("light-*.fits"))
        _, header = stacking.load_light(files[0].resolve())
        exposure, gain = float(header.get("EXPTIME", 600)), int(float(header.get("GAIN", 0)))
        first = clip.base(files[0], exposure, gain)
        h, w = first.shape
        rng = np.random.default_rng(7)
        ys, xs = rng.integers(3, h - 3, 600), rng.integers(3, w - 3, 600)
        vs = rng.choice((10., 30., 100.), 600).astype(np.float32)
        with Pool(3) as pool:
            got = pool.map(clip3.scores, [(str(p), exposure, gain, ys, xs, vs) for p in files])
        plain_map = clip13g.guarded(np.median(np.stack([g[0] for g in got]), axis=0))
        del got
        print(session, "map pixels", int(plain_map.sum()), flush=True)
        for p in files[::4]:
            x = clip.base(p, exposure, gain)
            mapped = x.copy(); mapped[plain_map] = N.median_filter(x, 5)[plain_map]
            rule = clip14rule.pair_aware(x)
            both = clip14rule.fix(x, plain_map)
            stars = stacking.find_stars(x, limit=300)
            near = np.zeros_like(plain_map)
            for sx, sy in stars[:, :2]:
                near[max(0, int(sy) - 6):int(sy) + 7, max(0, int(sx) - 6):int(sx) + 7] = True
            a = clip.measure({"none": x, "current": mapped, "aware": rule})
            b = clip.measure({"none": x, "current": both, "aware": both})
            row = {"session": session, "frame": p.name, "fwhm": round(float(np.median(stars[:, 3])), 2) if len(stars) else None,
                   "map_on_stars": int((plain_map & near).sum()), "map_only": a.get("current_brightest_third"),
                   "rule_only": a.get("aware_brightest_third"), "both": b.get("current_brightest_third")}
            print(json.dumps(row), flush=True)
            with open(clip.WORK / "cleanparts76.jsonl", "a") as f:
                f.write(json.dumps(row) + "\n")
