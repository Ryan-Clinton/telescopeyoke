"""Sharpening compared on the ten held-out half-stacks, each after GraXpert's denoise, as a picture would have it.

Methods: none, ours (colour.sharpened, 3 Richardson-Lucy steps), Seti Astro Suite Pro's Cosmic Clarity sharpen
(non-stellar only, and both), Siril 1.4.5 Richardson-Lucy with a PSF from the image's stars (its defaults).
Measured away from stars, in raw units, against the independent other half of each pair:

  detail     fine structure in the nebula, over none's (higher is sharper)
  grain      fine structure on empty sky, over none's (lower is better)
  agreement  change in correlation of the fine structure with the independent half (real detail raises it)
  ring       the deepest dip beside the planted lines, over the line's height (0 is none; negative is a ring)

Pass, fixed before any result: a tool replaces ours only if its medians have agreement at least ours,
detail at least ours, grain at most 2% above ours and ring no more than 0.02 deeper. Copies only.
"""
import json, os, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path.home() / "telescopeyoke-laptop/remote/code"))
import numpy as np
from astropy.io import fits
from scipy import ndimage as N
import colour

T = Path.home() / "telescopeyoke-laptop/training"; F = Path.home() / "telescopeyoke-laptop/freetools"; W = F / "sharpen"; W.mkdir(exist_ok=True)
SI = F / "dl/siril/squashfs-root/AppRun"; CC = F / "sas/bin/cosmicclarity"
scale = json.load(open(F / "scale.json"))


def lines(shape, seed):
    r = np.random.default_rng(seed); yy, xx = np.mgrid[:shape[0], :shape[1]]; out = np.zeros(shape, np.float32)
    for _ in range(14):
        a = r.uniform(0, np.pi); c = r.uniform(.15, .85) * shape[0]; d = r.uniform(.15, .85) * shape[1]; w = r.uniform(1.2, 2.5)
        dist = (yy - c) * np.cos(a) - (xx - d) * np.sin(a); along = (yy - c) * np.sin(a) + (xx - d) * np.cos(a)
        out = np.maximum(out, np.exp(-dist ** 2 / (2 * w * w)) * (np.abs(along) < 170))
    return out


def tool(u, run):
    with tempfile.TemporaryDirectory(dir=W) as d:
        fits.PrimaryHDU(u.astype(np.float32)).writeto(f"{d}/a.fits")
        r = run(d)
        if not Path(f"{d}/b.fits").exists(): sys.exit("tool failed: " + (r.stdout + r.stderr)[-800:])
        return np.squeeze(fits.getdata(f"{d}/b.fits")).astype(np.float32)


def cc(mode):
    return lambda u, fwhm: tool(u, lambda d: subprocess.run(
        [str(CC), "sharpen", "-i", f"{d}/a.fits", "-o", f"{d}/b.fits", "--gpu", "--temp-stretch", "--sharpening-mode", mode],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, env=dict(os.environ, QT_QPA_PLATFORM="offscreen")))


def siril(u, fwhm):
    def run(d):
        Path(f"{d}/s.ssf").write_text("requires 1.4.0\nsetext fits\nload a\nmakepsf stars -sym\nrl\nsave b\nclose\n")
        env = {k: v for k, v in os.environ.items() if k != "LD_LIBRARY_PATH"}
        return subprocess.run([str(SI), "siril-cli", "-d", d, "-s", f"{d}/s.ssf"], env=env, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL)
    return tool(u, run)


METHODS = {"none": lambda u, fwhm: u, "ours": lambda u, fwhm: colour.sharpened(u, fwhm, 3),
           "cc-nonstellar": cc("Non-Stellar Only"), "cc-both": cc("Both"), "siril-rl": siril}
# TY_METHODS runs a few, "none" always first as the base (24 November 2026: the GPU ones ran later).
METHODS = {k: v for k, v in METHODS.items() if k == "none" or k in os.environ.get("TY_METHODS", k).split(",")}


def band(a):
    return N.gaussian_filter(a, 1) - N.gaussian_filter(a, 4)


def spread(v):
    return 1.4826 * float(np.median(np.abs(v - np.median(v))))


results = {}
for rec in [r for r in json.load(open(T / "pairs3/index.json")) if r["role"] == "test"]:
    name = rec["name"]; path = T / "pairs3" / name / "split0"; lo, hi = scale[name]["lo"], scale[name]["hi"]
    x, y = (np.load(path / f"{k}.npy").astype(np.float32) for k in "xy"); valid = np.load(path / "valid.npy")
    fine = x - N.median_filter(x, size=9); noise = 1.4826 * np.median(np.abs(fine[valid][::3]))
    star = N.binary_dilation(fine > 5 * noise, iterations=6); free = valid & ~star
    smooth_y = N.gaussian_filter(y, 8)
    neb = free & (smooth_y > np.percentile(smooth_y[free], 70)); sky = free & (smooth_y < np.percentile(smooth_y[free], 30))
    plant = lines(x.shape, 11); core = (plant > .8) & free
    ring = N.binary_dilation(plant > .25, iterations=6) & ~N.binary_dilation(plant > .05, iterations=1) & free
    by = band(y); fwhm = colour.star_width(x) or 4.5
    graxpert = {a: np.load(F / "out/graxpert" / f"{name}_a{a}.npy").astype(np.float32) for a in (0, 3)}
    rows, base = {}, None
    for method, fn in METHODS.items():
        out = {a: fn(g, fwhm) * (hi - lo) + lo for a, g in graxpert.items()}
        b = band(out[0]); r = float(np.corrcoef(b[neb], by[neb])[0, 1])
        d = out[3] - out[0]; height = float(np.mean(d[core]))
        row = {"detail": spread(b[neb]), "grain": spread(b[sky]), "r": r, "line_height": height / 3,
               "ring": float(np.percentile(d[ring], 2)) / max(height, 1e-9)}
        if method == "none": base = row
        rows[method] = {"detail": round(row["detail"] / base["detail"], 4), "grain": round(row["grain"] / base["grain"], 4),
                        "agreement": round(row["r"] - base["r"], 4), "line_height": round(row["line_height"], 4),
                        "ring": round(row["ring"], 4)}
        print(name, method, rows[method], flush=True)
    results[name] = rows
    json.dump(results, open(W / os.environ.get("TY_SCORES", "scores.json"), "w"), indent=1)
