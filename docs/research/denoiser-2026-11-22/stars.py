"""Stars measured in fixed apertures at the input's positions, so a quieter sky cannot change what is counted."""
import json, sys
from pathlib import Path
sys.path.insert(0, ".")
import numpy as np, torch
from scipy import stats
import denoiser as D, stacking
T = Path.home() / "telescopeyoke-laptop/training"
R = 15
yy, xx = np.mgrid[-R:R + 1, -R:R + 1]; rad = np.hypot(yy, xx); core, ring = rad <= 6, (rad > 9) & (rad <= 14)
def measure(a, stars):
    out = []
    for x, y in stars[:, :2]:
        c, r = int(round(x)), int(round(y))
        if not (R <= r < a.shape[0] - R and R <= c < a.shape[1] - R): out.append((np.nan, np.nan)); continue
        cut = a[r - R:r + R + 1, c - R:c + R + 1]; bg = np.median(cut[ring]); v = np.maximum(cut - bg, 0) * core; f = float((cut - bg)[core].sum()); t = v.sum()
        if t <= 0: out.append((f, np.nan)); continue
        mx, my = (v * xx).sum() / t, (v * yy).sum() / t
        out.append((f, 2.355 * np.sqrt(max((v * ((xx - mx) ** 2 + (yy - my) ** 2)).sum() / t / 2, 1e-6))))
    return np.array(out)
rows = []
index = [r for r in json.load(open(T / "pairs/index.json")) if r["role"] == "test"]
for model in ("own", "nebula"):
    net = D.network().cuda(); net.load_state_dict(torch.load(T / f"models/{model}.pt", map_location="cuda")["state"]); net.eval()
    for rec in index:
        p = T / "pairs" / rec["name"] / "split0"
        x, s = (np.load(p / f"{k}.npy").astype(np.float32) for k in "xs")
        raw = D.infer(net, torch, x, s, "cuda")
        stars = stacking.find_stars(x + 10.0, 300); base = measure(x, stars)
        for label, out in (("network alone", raw), ("stars protected", D.protected(x, raw))):
            m = measure(out, stars); ok = np.isfinite(base).all(1) & np.isfinite(m).all(1) & (base[:, 0] > 20)
            ratio, width = m[ok, 0] / base[ok, 0], m[ok, 1] / base[ok, 1]
            row = dict(model=model, session=rec["name"], filter=rec["filter"], kind=label, stars=int(ok.sum()), flux=round(float(np.median(ratio) - 1), 4), flux_scatter=round(float(1.4826 * np.median(np.abs(ratio - np.median(ratio)))), 4), width=round(float(np.median(width) - 1), 4), trend=round(float(stats.spearmanr(base[ok, 0], ratio).statistic), 3))
            rows.append(row); print(json.dumps(row), flush=True)
json.dump(rows, open(T / "stars.json", "w"))
