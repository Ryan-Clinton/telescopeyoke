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
STEMS = tuple(sys.argv[1:]) or ("IC405-Ha", "IC405-SII", "NGC2174-Ha", "NGC2174-OIII", "NGC2174-SII")


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
    """Dark Star's result only round stars that were really found, so a thin filament is never replaced.
    A disc grows with the star's brightness, for its halo and spikes, and only what Dark Star changed inside it is taken."""
    change = N.gaussian_filter(u - ds, 1.0); noise = 1.4826 * float(np.median(np.abs(change - np.median(change)))) + 1e-6
    rows, cols = u.shape; discs = np.zeros(u.shape, bool)
    for x, y, _, fwhm, round_ in stacking.find_stars(u, limit=4000):
        r0, c0 = int(round(y)), int(round(x))
        if not (0 <= r0 < rows and 0 <= c0 < cols): continue
        height = float(change[max(r0 - 2, 0):r0 + 3, max(c0 - 2, 0):c0 + 3].max())
        # A star whose core is clipped reads as not round, and is too big for the compact test below
        # (IC 1848, 24 November 2026).
        # A close double reads as not round too (NGC 2174's SII, 24 November 2026): any not-round detection
        # Dark Star took down by 0.3 or more is a star; the planted faint line, 5 sigma high, is 0.15 to 0.22 after the stretch.
        if round_ < .45 and height < .3: continue
        radius = int(np.clip(1.6 * max(fwhm, 2.5) * (1 + 5 * max(height - .25, 0)), 5, 45))
        top, left = max(r0 - radius, 0), max(c0 - radius, 0)
        yy, xx = np.ogrid[top - r0:min(r0 + radius + 1, rows) - r0, left - c0:min(c0 + radius + 1, cols) - c0]
        discs[top:r0 + radius + 1, left:c0 + radius + 1] |= yy ** 2 + xx ** 2 <= radius ** 2
    # Stars the finder called not round (on a filament, or touching another): compact and solid, unlike a line.
    labels, _ = N.label(change > 6 * noise)
    for n, box in enumerate(N.find_objects(labels), 1):
        h, w = box[0].stop - box[0].start, box[1].stop - box[1].start; area = int((labels[box] == n).sum())
        if area >= 6 and max(h, w) <= 40 and max(h, w) / max(min(h, w), 1) < 2.5 and area / (h * w) >= .5:
            top, left = max(box[0].start - 5, 0), max(box[1].start - 5, 0)
            discs[top:box[0].stop + 5, left:box[1].stop + 5] |= N.binary_dilation(labels[top:box[0].stop + 5, left:box[1].stop + 5] == n, iterations=4)
    mask = N.gaussian_filter((discs & (change > 2 * noise)).astype(np.float32), 1.5)
    mask = np.clip(mask * 1.6, 0, 1) * N.gaussian_filter(discs.astype(np.float32), 1.0)
    # Dark Star also lowers the broad level on a noisy stack, which showed as dark discs:
    # take off only what stands above the broad change.
    small = N.median_filter((u - ds)[::4, ::4], 31)
    broad = N.zoom(small, (rows / small.shape[0], cols / small.shape[1]), order=1)
    return (u - mask * np.maximum(u - ds - broad, 0)).astype(np.float32)


def dark_patches(out):
    """How far the darkest smooth patch falls below its surroundings, in that smooth image's noise."""
    soft = N.gaussian_filter(out, 6)[::4, ::4]; rest = soft - N.median_filter(soft, 23)
    return round(float(np.percentile(rest, .1) / (1.4826 * np.median(np.abs(rest - np.median(rest))) + 1e-9)), 2)


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
            "worst_tenth_left": round(float(np.percentile(left, 90)), 3), "dark_patch": dark_patches(out)}


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
    json.dump(results, open(W / ("held-out-scores.json" if sys.argv[1:] else "scores.json"), "w"), indent=1)
