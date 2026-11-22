"""Do the camera's level jumps change a normal stack? The same frames stacked as now, and with each frame levelled."""
import json, sys
from pathlib import Path
sys.path.insert(0, ".")
import numpy as np
from scipy import ndimage as N
import denoiser as D, stacking, trainset
T = Path.home() / "telescopeyoke-laptop/training"
def stacked(frames):
    n = len(frames); plane = frames[0].shape
    first = stacking.Stack(plane, after=10 ** 9)
    for f in frames: first.add(f)
    final = stacking.Stack(plane)
    final.reference = stacking.robust_reference(frames, n, [True] * n) if 5 <= n <= 40 else (first.mean(), first.spread())
    for f in frames: final.add(f)
    return final.result()[..., 0], final.weights[..., 0] / n
if __name__ == "__main__":
    for name in ("IC405/20261122-001737", "IC405/20261121-211523", "NGC2174/20261121-024924", "M33/20261105-001232"):
        work = T / "levels.dat"
        try:
            store, good, *_ = trainset.register(Path("../data/frames") / name, work)
            good = good[:: max(1, len(good) // 40)][:40]
            frames = [np.array(store[i], np.float32) for i in good]
            sample = np.stack([f[::4, ::4, 0] for f in frames]); middle = np.nanmedian(sample, axis=0)
            level = np.array([np.nanmedian(s - middle) for s in sample])
            a, wa = stacked(frames); b, wb = stacked([f - l for f, l in zip(frames, level)])
            use = (wa > .8) & (wb > .8); use[:80] = use[-80:] = False; use[:, :80] = use[:, -80:] = False
            fine = b - N.median_filter(b, size=9); noise = 1.4826 * np.median(np.abs(fine[use][::3])); sky = use & ~N.binary_dilation(fine > 4 * noise, iterations=4)
            grain = lambda x: 1.4826 * float(np.median(np.abs((x - N.gaussian_filter(x, 2))[sky][::3])))
            aa, bb = np.where(use, a, np.median(a[use])), np.where(use, b, np.median(b[use]))
            star = D.star_change(aa - np.median(aa[sky]), bb - np.median(bb[sky]))
            print(json.dumps({"session": name, "frames": len(good), "frames_off_by_3_or_more": int((np.abs(level) >= 3).sum()), "largest_level": round(float(np.abs(level).max()), 2), "sky_change_counts": round(float(np.median((b - a)[sky])), 3), "grain_as_now": round(grain(a), 4), "grain_levelled": round(grain(b), 4), "pixels_kept_as_now": round(float(wa[use].mean()), 5), "pixels_kept_levelled": round(float(wb[use].mean()), 5), "stars": star}), flush=True)
        finally:
            work.unlink(missing_ok=True)
