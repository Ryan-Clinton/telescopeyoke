"""The test half-stacks, plain and with the planted filaments, scaled 0-1 as a user would hand them to a tool."""
import json, sys
from pathlib import Path
import numpy as np
from astropy.io import fits
sys.path.insert(0, str(Path.home() / "telescopeyoke-laptop/training"))
T = Path.home() / "telescopeyoke-laptop/training"; F = Path.home() / "telescopeyoke-laptop/freetools"
def lines(shape, seed):
    r = np.random.default_rng(seed); yy, xx = np.mgrid[:shape[0], :shape[1]]; out = np.zeros(shape, np.float32)
    for _ in range(14):
        a = r.uniform(0, np.pi); c = r.uniform(.15, .85) * shape[0]; d = r.uniform(.15, .85) * shape[1]; w = r.uniform(1.2, 2.5)
        dist = (yy - c) * np.cos(a) - (xx - d) * np.sin(a); along = (yy - c) * np.sin(a) + (xx - d) * np.cos(a)
        out = np.maximum(out, np.exp(-dist ** 2 / (2 * w * w)) * (np.abs(along) < 170))
    return out
scale = {}
(F / "in").mkdir(exist_ok=True)
for rec in [r for r in json.load(open(T / "pairs3/index.json")) if r["role"] == "test"]:
    x = np.load(T / "pairs3" / rec["name"] / "split0/x.npy").astype(np.float32); p = lines(x.shape, 11)
    lo, hi = float(x.min()), float((x + 3 * p).max()) * 1.02
    scale[rec["name"]] = {"lo": lo, "hi": hi, "filter": rec["filter"]}
    for amp in (0, 1, 3):
        fits.PrimaryHDU(((x + amp * p - lo) / (hi - lo)).astype(np.float32)).writeto(F / "in" / f"{rec['name']}_a{amp}.fits", overwrite=True)
json.dump(scale, open(F / "scale.json", "w"), indent=1)
print(len(scale), x.shape, lo, hi)
