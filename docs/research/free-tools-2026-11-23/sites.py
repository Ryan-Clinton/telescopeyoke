"""Five copies of each target's stacks: untouched, and each method cut to half the grain. The originals are only read."""
import json, shutil, sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / "telescopeyoke-laptop/remote/code"))
import numpy as np
from astropy.io import fits
from scipy import ndimage as N

class D:
    @staticmethod
    def grain(a, sky):
        d = a - N.gaussian_filter(a, 3)
        return 1.4826 * float(np.median(np.abs(d[sky] - np.median(d[sky]))))

F = Path.home() / "telescopeyoke-laptop/freetools"; scale = json.load(open(F / "scale.json")); TARGET = .5; report = {}
SIDE = F / "sidecars"
for stem in ("IC405-Ha", "IC405-SII", "NGC2174-Ha", "NGC2174-OIII", "NGC2174-SII"):
    target, band = stem.split("-"); p = F / "real" / f"{stem}.fits"; hdu = fits.open(p); head = hdu[0].header.copy(); data = hdu[0].data.astype(np.float32); hdu.close()
    x = np.nan_to_num(data[0]); fine = x - N.median_filter(x, size=9); e = 1.4826 * np.median(np.abs(fine[::3, ::3])); star = N.binary_dilation(fine > 5 * e, iterations=4)
    sky = ~star; sky[:40] = sky[-40:] = False; sky[:, :40] = sky[:, -40:] = False; g0 = D.grain(x, sky); key = "real-" + stem; report[stem] = {"grain": round(float(g0), 4)}
    def mix(o):
        if D.grain(o, sky) > TARGET * g0: return o, 1.0
        lo, hi = 0., 1.
        for _ in range(16):
            k = (lo + hi) / 2; lo, hi = (k, hi) if D.grain(x + k * (o - x), sky) > TARGET * g0 else (lo, k)
        return x + hi * (o - x), hi
    def blur():
        lo, hi = 0., 6.
        for _ in range(16):
            k = (lo + hi) / 2; lo, hi = (k, hi) if D.grain(N.gaussian_filter(x, k), sky) > TARGET * g0 else (lo, k)
        return N.gaussian_filter(x, hi), hi
    made = {"original": (x, 0.0), "blur": blur()}
    for tool in ("siril", "cc", "graxpert"):
        made[tool] = mix(np.load(F / "out" / tool / f"{key}.npy").astype(np.float32) * (scale[key]["hi"] - scale[key]["lo"]) + scale[key]["lo"])
    for v, (a, m) in made.items():
        report[stem][v] = round(float(m), 3); report[stem][v + "_grain"] = round(float(D.grain(a, sky) / g0), 3)
        d = F / "site" / v / "frames" / target / f"combined-{band}"; d.mkdir(parents=True, exist_ok=True)
        for s in (SIDE / target / f"combined-{band}").glob("*"):
            if s.is_file(): shutil.copy(s, d / s.name)
        out = np.where(np.isfinite(data[0]), a, np.nan).astype(np.float32)
        fits.PrimaryHDU(np.stack([out] * data.shape[0]), head).writeto(d / "final.fits", overwrite=True)
json.dump(report, open(F / "sites.json", "w"), indent=1); print(json.dumps(report))
