"""Star removal compared on copies of real stacks, in the stretched brightness a picture uses.

Star left: what stays of each measured star's peak above its surroundings (0 is gone).
Hole: the star's place against its surroundings afterwards, in units of the sky's noise.
Glow and filament kept: planted nebula that survives (1 is all of it). The originals are only read.
"""
import json, os, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path.home() / "telescopeyoke-laptop/remote/code"))
import numpy as np
from astropy.io import fits
from scipy import ndimage as N
import colour, stacking

F = Path.home() / "telescopeyoke-laptop/freetools"; W = F / "stars"; CC = F / "sas/bin/cosmicclarity"
STEMS = ("IC405-Ha", "IC405-SII", "NGC2174-Ha", "NGC2174-OIII", "NGC2174-SII")


def load(stem):
    with fits.open(F / "real" / f"{stem}.fits") as f:
        d = f[0].data.astype(np.float32)
    d = d[0] if d.ndim == 3 else d
    return np.where(np.isfinite(d), d, float(np.nanmedian(d)))


def stretcher(x):
    sky = float(np.median(x)); noise = 1.4826 * float(np.median(np.abs(x - sky))) + 1e-6
    top = float(np.percentile(x, 99.99)); soft = 3 * noise; bottom = np.arcsinh(-3 * noise / soft); span = np.arcsinh((top - sky) / soft) - bottom
    return lambda a: np.clip((np.arcsinh((a - sky) / soft) - bottom) / span, 0, 1).astype(np.float32)


def darkstar(u):
    with tempfile.TemporaryDirectory(dir=W) as d:
        fits.PrimaryHDU(u).writeto(f"{d}/in.fits")
        r = subprocess.run([str(CC), "darkstar", "-i", f"{d}/in.fits", "-o", f"{d}/out.fits", "--gpu"], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
        if not Path(f"{d}/out.fits").exists(): sys.exit("Dark Star: " + (r.stdout + r.stderr)[-800:])
        return np.squeeze(fits.getdata(f"{d}/out.fits")).astype(np.float32)


def ours(a, s):
    star = colour.star_mask(a / max(colour.nebula_level(a), 1e-6))
    return s(colour.layers(a, star)[0])


def plants(shape):
    rows, cols = shape; y, x = np.mgrid[0:rows, 0:cols].astype(np.float32); r = np.random.default_rng(11); glow = np.zeros_like(x); line = np.zeros_like(x)
    for cy, cx in r.uniform(.15, .85, (4, 2)) * (rows, cols):
        glow += np.exp(-((y - cy) ** 2 + (x - cx) ** 2) / (2 * 60. ** 2))
    for cy, cx, t in zip(*(r.uniform(.2, .8, (2, 6)) * [[rows], [cols]]), r.uniform(0, np.pi, 6)):
        along = (x - cx) * np.cos(t) + (y - cy) * np.sin(t); across = -(x - cx) * np.sin(t) + (y - cy) * np.cos(t)
        line += np.exp(-across ** 2 / (2 * 2.5 ** 2)) * np.exp(-along ** 2 / (2 * 120. ** 2))
    return glow / glow.max(), line / line.max()


def blended(u, ds):
    """Dark Star's result only where it took off something compact; the original everywhere else."""
    change = N.gaussian_filter(u - ds, 1.0); noise = 1.4826 * float(np.median(np.abs(change - np.median(change)))) + 1e-6
    found = change > 4 * noise; labels, count = N.label(found); keep = np.zeros(count + 1, bool)
    for n, box in enumerate(N.find_objects(labels), 1):
        h, w = box[0].stop - box[0].start, box[1].stop - box[1].start; area = (labels[box] == n).sum()
        keep[n] = area >= 6 and (max(h, w) / max(min(h, w), 1) < 3.5 or area / (h * w) < .35 and max(h, w) > 30)
    mask = N.gaussian_filter(N.binary_dilation(keep[labels], iterations=3).astype(np.float32), 1.5)
    return (mask * ds + (1 - mask) * u).astype(np.float32)


def star_scores(u, out):
    """Measured out to 22 pixels, so a bright star's leftover halo counts as left."""
    bg = N.median_filter(u[::2, ::2], 15); bg = N.zoom(bg, (u.shape[0] / bg.shape[0], u.shape[1] / bg.shape[1]), order=1)
    noise = 1.4826 * float(np.median(np.abs((u - bg) - np.median(u - bg))))
    found = stacking.find_stars(u); pts = np.asarray([(int(round(p[1])), int(round(p[0]))) for p in found])
    pts = pts[(pts[:, 0] > 24) & (pts[:, 0] < u.shape[0] - 24) & (pts[:, 1] > 24) & (pts[:, 1] < u.shape[1] - 24)]
    left = []
    yy, xx = np.ogrid[-22:23, -22:23]; d2 = yy ** 2 + xx ** 2; core = d2 <= 9; ring = (d2 >= 256) & (d2 <= 484)
    for r, c in pts:
        a, b = u[r - 22:r + 23, c - 22:c + 23], out[r - 22:r + 23, c - 22:c + 23]
        h = np.mean(a[core]) - np.median(a[ring])
        if h > 5 * noise:
            left.append((np.mean(b[core]) - np.median(b[ring])) / h)
    return {"stars": len(left), "star_left": round(float(np.median(left)), 3), "brightest_20_left": round(float(np.median(left[:20])), 3),
            "worst_tenth_left": round(float(np.percentile(left, 90)), 3)}


results = {}
for stem in STEMS:
    x = load(stem); s = stretcher(x); glow, line = plants(x.shape); noise = 1.4826 * float(np.median(np.abs(x - np.median(x))))
    g, l = x + 3 * noise * glow, x + 5 * noise * line; u, ug, ul = s(x), s(g), s(l); results[stem] = {}
    ds = {"base": darkstar(u), "glow": darkstar(ug), "line": darkstar(ul)}
    made = {"ours": (ours(x, s), ours(g, s), ours(l, s)), "darkstar": (ds["base"], ds["glow"], ds["line"]),
            "darkstar-blend": (blended(u, ds["base"]), blended(ug, ds["glow"]), blended(ul, ds["line"]))}
    for name, (o, og, ol) in made.items():
        row = star_scores(u, o)
        for key, out, v, mask in (("glow_kept", og, ug, glow), ("line_kept", ol, ul, line)):
            d = N.gaussian_filter(out - o, 1.5); c = N.gaussian_filter(v - u, 1.5); w = mask > .3
            row[key] = round(float((d[w] * c[w]).sum() / (c[w] ** 2).sum()), 3)
        results[stem][name] = row; print(stem, name, row, flush=True)
    json.dump(results, open(W / "scores.json", "w"), indent=1)
