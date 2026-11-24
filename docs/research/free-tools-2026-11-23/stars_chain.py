"""GraXpert's denoise, then Dark Star, against our star removal after the same denoise.

Every method starts from the same GraXpert-denoised linear stack, as a picture would.
Scores use stars.py's measures on stacks not used to tune anything. The originals are only read.
"""
import json, os, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path.home() / "telescopeyoke-laptop/remote/code"))
import numpy as np
from astropy.io import fits
from scipy import ndimage as N
import freetools

HERE = Path(__file__).parent; stems = sys.argv[1:]; sys.argv = sys.argv[:1]
ns = {"__file__": str(HERE / "stars.py")}; exec((HERE / "stars.py").read_text().split("results = {}")[0], ns)
F, W, CC, load, stretcher, ours, plants, star_scores, blended = (ns[k] for k in ("F", "W", "CC", "load", "stretcher", "ours", "plants", "star_scores", "blended"))


def darkstar(u, mode):
    with tempfile.TemporaryDirectory(dir=W) as d:
        fits.PrimaryHDU(u).writeto(f"{d}/in.fits")
        r = subprocess.run([str(CC), "darkstar", "-i", f"{d}/in.fits", "-o", f"{d}/out.fits", "--gpu", "--star-removal-mode", mode],
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
        if not Path(f"{d}/out.fits").exists(): sys.exit("Dark Star: " + (r.stdout + r.stderr)[-800:])
        return np.squeeze(fits.getdata(f"{d}/out.fits")).astype(np.float32)


results = {}
for stem in stems:
    x = load(stem); s = stretcher(x); glow, line = plants(x.shape); noise = 1.4826 * float(np.median(np.abs(x - np.median(x))))
    g, l = x + 3 * noise * glow, x + 5 * noise * line; truth = {"glow": s(g) - s(x), "line": s(l) - s(x)}
    clean = {"base": freetools.denoise(x), "glow": freetools.denoise(g), "line": freetools.denoise(l)}
    u = {k: s(v) for k, v in clean.items()}; results[stem] = {}
    made = {"ours-after-graxpert": {k: ours(v, s) for k, v in clean.items()}}
    for mode in ("unscreen", "additive"):
        made[f"graxpert-darkstar-{mode}"] = {k: darkstar(v, mode) for k, v in u.items()}
    made["graxpert-darkstar-blend"] = {k: blended(u[k], made["graxpert-darkstar-unscreen"][k]) for k in u}
    for name, out in made.items():
        row = star_scores(u["base"], out["base"])
        for key, mask in (("glow", glow), ("line", line)):
            d = N.gaussian_filter(out[key] - out["base"], 1.5); c = N.gaussian_filter(truth[key], 1.5); w = mask > .3
            row[key + "_kept"] = round(float((d[w] * c[w]).sum() / (c[w] ** 2).sum()), 3)
        results[stem][name] = row; print(stem, name, row, flush=True)
    json.dump(results, open(W / os.environ.get("TY_SCORES", "chain-scores.json"), "w"), indent=1)
