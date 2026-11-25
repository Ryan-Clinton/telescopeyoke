"""Protocol step 3 on the shared sets' finished stacks (real/*-ds.fits, staged by ds_real.py): stretch.py's
methods and measures, unchanged, with one deviation (deviation 8): a finished stack has no independent
half, so its regions (sky, faint, bright) come from the same stack smoothed, and the planted lines go
into the stack before GraXpert, the pair being the stack denoised without and with them.

stretch.py's own notes follow.

Stretching compared on the ten held-out half-stacks after GraXpert, each tool at its own default sky level.

Each stack and its copy with faint planted lines go side by side into one image, so one stretch serves both and
their difference is what the stretch shows of the lines. Methods: ours (process.display), Siril 1.4.5's
autostretch and autoghs (its stretch amount searched until the sky is at Siril's default, 0.25), Seti Astro Suite
Pro's statistical stretch. Ours puts the sky at black, so measuring on the sky, or putting the tools' sky there,
said nothing (24 November 2026, first try). Measured in display units in the faint nebula (the 30th to 60th
percentile of the independent half's smoothed brightness), away from stars:

  shown      the faint lines' height over the grain there (higher shows more faint nebula above the grain)
  bright     fine structure kept in the brightest 2% of the nebula (higher keeps more of the bright parts)
  clipped    share of the picture burnt to white

Pass, fixed before any result: a tool replaces ours only if its medians have shown and bright at least ours and
clipped no more than 0.1 points above ours. Copies only; the pictures are not kept.
"""
import json, os, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path.home() / "telescopeyoke-laptop/remote/code"))
import numpy as np
from astropy.io import fits
from scipy import ndimage as N
import process
import freetools

T = Path.home() / "telescopeyoke-laptop/training"; F = Path.home() / "telescopeyoke-laptop/freetools"; W = F / "stretch-ds"; W.mkdir(exist_ok=True)
SI = F / "dl/siril/squashfs-root/AppRun"; SAS = F / "sas/bin/setiastrosuitepro"


def lines(shape, seed):
    r = np.random.default_rng(seed); yy, xx = np.mgrid[:shape[0], :shape[1]]; out = np.zeros(shape, np.float32)
    for _ in range(14):
        a = r.uniform(0, np.pi); c = r.uniform(.15, .85) * shape[0]; d = r.uniform(.15, .85) * shape[1]; w = r.uniform(1.2, 2.5)
        dist = (yy - c) * np.cos(a) - (xx - d) * np.sin(a); along = (yy - c) * np.sin(a) + (xx - d) * np.cos(a)
        out = np.maximum(out, np.exp(-dist ** 2 / (2 * w * w)) * (np.abs(along) < 170))
    return out


def ours(pair):
    sky = float(np.median(pair)); noise = 1.4826 * float(np.median(np.abs(pair - sky)))
    rgb = np.repeat(((pair - sky) / noise)[..., None], 3, axis=2)
    return process.display(rgb, whole=False).mean(axis=2) / 255


def in_folder(pair, run):
    with tempfile.TemporaryDirectory(dir=W) as d:
        fits.PrimaryHDU(np.clip(pair, 0, 1).astype(np.float32)).writeto(f"{d}/a.fits")
        r = run(d)
        if not Path(f"{d}/b.fits").exists(): sys.exit("tool failed: " + (r.stdout + r.stderr)[-800:])
        return np.squeeze(fits.getdata(f"{d}/b.fits")).astype(np.float32)


def siril(pair, command):
    env = {k: v for k, v in os.environ.items() if k != "LD_LIBRARY_PATH"}
    def run(d):
        Path(f"{d}/s.ssf").write_text(f"requires 1.4.0\nsetcpu 4\nsetext fits\nload a\n{command}\nsave b\nclose\n")   # 4 cores, as agreed
        return subprocess.run([str(SI), "siril-cli", "-d", d, "-s", f"{d}/s.ssf"], env=env, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, cwd=d, timeout=600)
    return in_folder(pair, run)


def ghs(pair, target):
    lo, hi = 0.0, 10.0       # the stretch amount, searched until the sky's median matches
    for _ in range(9):
        amount = (lo + hi) / 2
        out = siril(pair, f"autoghs -2.8 {amount:.4f}")
        lo, hi = (amount, hi) if float(np.median(out)) < target else (lo, amount)
    return out


def sas(pair, target):
    return in_folder(pair, lambda d: subprocess.run(
        [str(SAS), "process", "stat_stretch", "-i", f"{d}/a.fits", "-o", f"{d}/b.fits", "--target-median", f"{target:.5f}", "-q"],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, cwd=d, timeout=600,
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen")))


results = {}
for path in sorted((F / "real").glob("*-ds.fits")):
    name = path.stem
    x = np.nan_to_num(fits.getdata(path).astype(np.float32)); valid = x != 0
    fine = x - N.median_filter(x, size=9); noise = 1.4826 * np.median(np.abs(fine[valid][::3]))
    star = N.binary_dilation(fine > 5 * noise, iterations=6); free = valid & ~star
    smooth_y = N.gaussian_filter(x, 8)
    sky = free & (smooth_y < np.percentile(smooth_y[free], 30)); bright = free & (smooth_y > np.percentile(smooth_y[free], 98))
    faint = free & ~sky & (smooth_y < np.percentile(smooth_y[free], 60))
    plant = lines(x.shape, 11); core = (plant > .8) & faint
    a0, a1 = freetools.denoise(x), freetools.denoise(x + 3 * noise * plant)
    top = float(np.percentile(a0[valid], 99.995)); a0, a1 = a0 / top, a1 / top
    pair = np.hstack([a0, a1]); cols = a0.shape[1]
    shown = ours(pair); target = 0.25      # Siril's and the suite's default sky level
    made = {"ours": shown, "siril-autostretch": siril(pair, f"autostretch -2.8 {target:.5f}"), "siril-autoghs": ghs(pair, target),
            "setiastro-stat-stretch": sas(pair, target)}
    rows = {}
    for method, d in made.items():
        d0, d1 = d[:, :cols], d[:, cols:]
        grain = 1.4826 * float(np.median(np.abs((d0 - N.gaussian_filter(d0, 3))[faint])))
        height = float(np.mean((d1 - d0)[core]))
        band = d0 - N.gaussian_filter(d0, 4)
        rows[method] = {"sky": round(float(np.median(d0[sky])), 5), "shown": round(height / max(grain, 1e-9), 3),
                        "line_height": round(height, 4), "grain": round(grain, 4), "bright": round(float(np.std(band[bright])), 4),
                        "clipped_pct": round(100 * float((d0[valid] >= .99).mean()), 3)}
        print(name, method, rows[method], flush=True)
    results[name] = rows
    json.dump(results, open(W / "scores.json", "w"), indent=1)
