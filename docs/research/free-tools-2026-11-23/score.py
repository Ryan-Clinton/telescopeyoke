"""Each free tool against blur at equal grain, by the planted-filament and independent-half tests our models took."""
import json, sys
from multiprocessing import get_context
from pathlib import Path
sys.path.insert(0, str(Path.home() / "telescopeyoke-laptop/remote/code"))
import numpy as np
from scipy import ndimage as N

class D:
    @staticmethod
    def grain(a, sky):
        d = a - N.gaussian_filter(a, 3)
        return 1.4826 * float(np.median(np.abs(d[sky] - np.median(d[sky]))))

T = Path.home() / "telescopeyoke-laptop/training"; F = Path.home() / "telescopeyoke-laptop/freetools"
scale = json.load(open(F / "scale.json")); TOOLS = sys.argv[1:] or ["cc", "graxpert"]

def lines(shape, seed):
    r = np.random.default_rng(seed); yy, xx = np.mgrid[:shape[0], :shape[1]]; out = np.zeros(shape, np.float32)
    for _ in range(14):
        a = r.uniform(0, np.pi); c = r.uniform(.15, .85) * shape[0]; d = r.uniform(.15, .85) * shape[1]; w = r.uniform(1.2, 2.5)
        dist = (yy - c) * np.cos(a) - (xx - d) * np.sin(a); along = (yy - c) * np.sin(a) + (xx - d) * np.cos(a)
        out = np.maximum(out, np.exp(-dist ** 2 / (2 * w * w)) * (np.abs(along) < 170))
    return out

def search(make, sky, target):
    lo, hi = 0.0, 1.0
    for _ in range(14):
        k = (lo + hi) / 2
        lo, hi = (k, hi) if D.grain(make(k), sky) > target else (lo, k)
    return hi

def stars(x, o, fine, noise):
    """Flux, peak and width of the brightest unsaturated stars, tool over input."""
    lab, n = N.label(fine > 12 * noise)
    if not n: return {}
    idx = np.arange(1, n + 1); peaks = N.maximum(fine, lab, idx); keep = idx[np.argsort(peaks)[::-1][:300]]
    pos = N.maximum_position(fine, lab, keep); R = 15; yy, xx = np.mgrid[-R:R + 1, -R:R + 1]; rr = np.hypot(yy, xx); f, p, w = [], [], []
    def m(c):
        bg = np.median(c[(rr >= 10) & (rr <= 14)]); c = c - bg; a = np.clip(c, 0, None) * (rr <= 7); t = a.sum()
        return t, c[R, R], np.sqrt((a * rr ** 2).sum() / max(t, 1e-9))
    for r, c in pos:
        if r < R or c < R or r >= x.shape[0] - R or c >= x.shape[1] - R: continue
        a = m(x[r - R:r + R + 1, c - R:c + R + 1]); b = m(o[r - R:r + R + 1, c - R:c + R + 1])
        if a[0] > 0 and a[1] > 0: f.append(b[0] / a[0]); p.append(b[1] / a[1]); w.append(b[2] / a[2])
    return {"star_flux": round(float(np.median(f)), 4), "star_flux_low": round(float(np.percentile(f, 5)), 4), "star_peak": round(float(np.median(p)), 4), "star_width": round(float(np.median(w)), 4), "stars": len(f)}

def one(job):
    tool, rec = job; name = rec["name"]; path = T / "pairs3" / name / "split0"; meta = json.load(open(path / "meta.json"))
    x, y = (np.load(path / f"{k}.npy").astype(np.float32) for k in "xy"); valid = np.load(path / "valid.npy"); lo, hi = scale[name]["lo"], scale[name]["hi"]
    load = lambda a: np.load(F / "out" / tool / f"{name}_a{a}.npy").astype(np.float32) * (hi - lo) + lo
    fine = x - N.median_filter(x, size=9); noise = 1.4826 * np.median(np.abs(fine[valid][::3])); star = N.binary_dilation(fine > 5 * noise, iterations=4)
    soft = np.clip(N.gaussian_filter(star.astype(np.float32), 1.5) * 1.6, 0, 1); sky = valid & ~N.binary_dilation(star, iterations=3); floor = meta["input"] / meta["target"]
    raw = load(0); out = soft * x + (1 - soft) * raw; plant = lines(x.shape, 11); use = plant > .25; rows = []; star_row = stars(x, raw, fine, noise)
    keep = lambda t, o, amp: float(((t - o)[use & sky] * plant[use & sky]).sum() / (amp * (plant[use & sky] ** 2).sum()))
    err = lambda o: float(np.sqrt(max(np.mean((o[sky] - y[sky]) ** 2) - floor, 0)))
    full_grain = float(D.grain(out, sky))
    for amp in (1, 3):
        xp = x + amp * plant; rp = load(amp); op = soft * xp + (1 - soft) * rp
        for target in (.7, .5, .3):
            reached = full_grain <= target
            a = search(lambda k: x + k * (out - x), sky, target) if reached else 1.0
            sg = 4 * search(lambda k: N.gaussian_filter(x, 4 * k) if k else x, sky, target)
            to, tt = x + a * (out - x), xp + a * (op - xp); bo, bt = N.gaussian_filter(x, sg), N.gaussian_filter(xp, sg)
            rows.append(dict(tool=tool, session=name, filter=rec["filter"], amp=amp, grain=target, reached=reached, full_grain=round(full_grain, 3), mix=round(a, 3), net_keep=round(keep(tt, to, amp), 3), blur_keep=round(keep(bt, bo, amp), 3), net_err=round(err(to), 4), blur_err=round(err(bo), 4), input_err=round(err(x), 4), **star_row))
    return rows

if __name__ == "__main__":
    index = [r for r in json.load(open(T / "pairs3/index.json")) if r["role"] == "test"]
    jobs = [(t, r) for t in TOOLS for r in index]
    with get_context("fork").Pool(8) as pool:
        got = [row for rows in pool.imap_unordered(one, jobs) for row in rows]
    json.dump(got, open(F / "scores.json", "w"), indent=0)
    for t in TOOLS:
        R = [r for r in got if r["tool"] == t and r["amp"] == 1]
        print(t, "full grain", round(np.median([r["full_grain"] for r in R]), 3), "star flux", np.median([r["star_flux"] for r in R]), "worst", min(r["star_flux_low"] for r in R), "peak", np.median([r["star_peak"] for r in R]), "width", np.median([r["star_width"] for r in R]))
        for g in (.7, .5, .3):
            q = [r for r in R if r["grain"] == g]; ok = [r for r in q if r["reached"]]
            print(f"  grain {g}: reached {len(ok)}/{len(q)} keep {100*np.median([r['net_keep'] for r in ok]) if ok else float('nan'):.1f} blur {100*np.median([r['blur_keep'] for r in ok]) if ok else float('nan'):.1f} err/blur {np.median([r['net_err']/r['blur_err'] for r in ok]) if ok else float('nan'):.3f}")
