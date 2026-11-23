"""Background removal compared: known gradients and faint glows added to copies of real stacks.

A good method takes the added gradient off (residual near 0) and leaves the added glow (kept near 1).
Each method runs on the stack alone and on the stack plus each addition, so the stack's own
noise and nebula cancel in the difference. The originals are only read.
"""
import json, os, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path.home() / "telescopeyoke-laptop/remote/code"))
import numpy as np
from astropy.io import fits
import colour, process

F = Path.home() / "telescopeyoke-laptop/freetools"; W = F / "bg"; W.mkdir(exist_ok=True)
GX = F / "dl/graxpert/GraXpert-linux/GraXpert"; SI = F / "dl/siril/squashfs-root/AppRun"
STEMS = ("IC405-Ha", "IC405-SII", "NGC2174-Ha", "NGC2174-OIII", "NGC2174-SII")
GRADIENTS = ("tilt", "bowl", "corner")


def shape(kind, rows, cols):
    y, x = np.mgrid[0:rows, 0:cols].astype(np.float32); y /= rows; x /= cols
    if kind == "tilt": g = .7 * x + .3 * y
    elif kind == "bowl": g = (x - .45) ** 2 + (y - .55) ** 2
    elif kind == "corner": g = np.exp(-((x - 1) ** 2 + y ** 2) / (2 * .22 ** 2))
    else:   # four soft glows, placed the same every time
        g = np.zeros_like(x); r = np.random.default_rng(7)
        for cy, cx in r.uniform(.15, .85, (4, 2)):
            g += np.exp(-(((y - cy) * rows) ** 2 + ((x - cx) * cols) ** 2) / (2 * 80. ** 2))
    return (g - g.min()) / (g.max() - g.min())


def to_unit(a):
    low, high = float(a.min()), float(a.max()); high = low + (high - low) * 1.001
    return ((a - low) / (high - low)).astype(np.float32), low, high


def graxpert(a, smoothing):
    u, low, high = to_unit(a)
    env = dict(os.environ, LD_LIBRARY_PATH=(F / "graxpert_cuda_path").read_text().strip())
    with tempfile.TemporaryDirectory(dir=W) as d:
        fits.PrimaryHDU(u).writeto(f"{d}/in.fits")
        r = subprocess.run([str(GX), f"{d}/in.fits", "-cli", "-cmd", "background-extraction", "-output", f"{d}/out",
                            "-correction", "Subtraction", "-smoothing", str(smoothing)], env=env, capture_output=True,
                           text=True, stdin=subprocess.DEVNULL)
        if not Path(f"{d}/out.fits").exists(): sys.exit("GraXpert: " + (r.stdout + r.stderr)[-800:])
        return np.squeeze(fits.getdata(f"{d}/out.fits")).astype(np.float32) * (high - low) + low


def siril(a, how):
    u, low, high = to_unit(a)
    env = {k: v for k, v in os.environ.items() if k != "LD_LIBRARY_PATH"}
    with tempfile.TemporaryDirectory(dir=W) as d:
        fits.PrimaryHDU(u).writeto(f"{d}/a.fits")
        Path(f"{d}/s.ssf").write_text(f"requires 1.4.0\nsetext fits\nload a\nsubsky {how}\nsave b\nclose\n")
        r = subprocess.run([str(SI), "siril-cli", "-d", d, "-s", f"{d}/s.ssf"], env=env, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL)
        if not Path(f"{d}/b.fits").exists(): sys.exit("Siril: " + (r.stdout + r.stderr)[-800:])
        return np.squeeze(fits.getdata(f"{d}/b.fits")).astype(np.float32) * (high - low) + low


def ours(a, guide):
    clear = colour.clear_of_nebula(guide)
    if clear.mean() >= colour.MIN_CLEAR:
        return a - colour.sky_model(a, clear)
    return process.remove_sky(a[..., None].copy(), 1)[..., 0]


METHODS = {"ours": ours, "graxpert-0.1": lambda a, g: graxpert(a, .1), "graxpert-0.5": lambda a, g: graxpert(a, .5),
           "siril-rbf": lambda a, g: siril(a, "-rbf"), "siril-poly2": lambda a, g: siril(a, "2")}


def load(stem):
    with fits.open(F / "real" / f"{stem}.fits") as f:
        d = f[0].data.astype(np.float32)
    return d[0] if d.ndim == 3 else d


def pair(stem):
    """This filter and its target's Ha, lined up as colour.py lines them up, cut to where both have data."""
    ha = load(stem.split("-")[0] + "-Ha"); x = load(stem)
    rows, cols = min(ha.shape[0], x.shape[0]), min(ha.shape[1], x.shape[1]); ha, x = ha[:rows, :cols], x[:rows, :cols]
    if not stem.endswith("-Ha"):
        clean = np.nan_to_num(ha)
        x, info, _ = colour.lined_up(x, {"square": colour.stacking.centre_square(clean), "stars": colour.stacking.find_stars(clean)})
        if not colour.fits_well(info): sys.exit(f"{stem} did not line up")
    good = np.isfinite(x) & np.isfinite(ha)
    r = np.flatnonzero(good.mean(axis=1) > .98); c = np.flatnonzero(good.mean(axis=0) > .98)
    x, ha = x[r[0]:r[-1] + 1, c[0]:c[-1] + 1], ha[r[0]:r[-1] + 1, c[0]:c[-1] + 1]
    return np.where(np.isfinite(x), x, float(np.nanmedian(x))), np.where(np.isfinite(ha), ha, float(np.nanmedian(ha)))


def strength(x):
    return max(colour.nebula_level(x) - float(np.median(x)), 1e-6)


def score(base, changed, added):
    d = (changed - base)[::4, ::4]; a = added[::4, ::4]; d = d - np.median(d); c = a - np.median(a)
    return d, c


results = {}
for stem in STEMS:
    x, ha = pair(stem); rows, cols = x.shape
    amp, ha_amp = strength(x), strength(ha); results[stem] = {}
    cases = {g: (.3 * amp * shape(g, rows, cols), .3 * ha_amp * shape(g, rows, cols)) for g in GRADIENTS}
    cases["glow"] = (.1 * amp * shape("glow", rows, cols), .1 * ha_amp * shape("glow", rows, cols))
    for name, method in METHODS.items():
        base = method(x, ha); row = {}
        for case, (add, ha_add) in cases.items():
            d, c = score(base, method(x + add, ha + ha_add), add)
            if case == "glow":
                where = c > .2 * c.max(); row["glow_kept"] = round(float((d[where] * c[where]).sum() / (c[where] ** 2).sum()), 3)
            else:
                row[case] = round(float(np.sqrt(np.mean(d ** 2) / np.mean(c ** 2))), 3)
        results[stem][name] = row; print(stem, name, row, flush=True)
        json.dump(results, open(W / "scores.json", "w"), indent=1)
