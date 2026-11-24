"""StarNet2 after GraXpert's denoise, whole and blended, scored as stars_chain.py scores Dark Star.

Only the scores are kept: StarNet's images are deleted after measuring. The originals are only read.
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
F, W, load, stretcher, plants, star_scores, blended = (ns[k] for k in ("F", "W", "load", "stretcher", "plants", "star_scores", "blended"))
SN = F / "dl/starnet/gpu/starnet2"; LIBS = (F / "starnet_cuda_path").read_text().strip()


def starnet(u):
    with tempfile.TemporaryDirectory(dir=W) as d:
        fits.PrimaryHDU(u).writeto(f"{d}/in.fits")
        r = subprocess.run([str(SN), "--input", f"{d}/in.fits", "--output", f"{d}/out.fits"], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, env=dict(os.environ, LD_LIBRARY_PATH=LIBS))
        if "CUDA execution provider" not in r.stdout + r.stderr: sys.exit("StarNet is not on the GPU: " + (r.stdout + r.stderr)[-500:])
        if not Path(f"{d}/out.fits").exists(): sys.exit("StarNet: " + (r.stdout + r.stderr)[-800:])
        return np.squeeze(fits.getdata(f"{d}/out.fits")).astype(np.float32)


results = {}
for stem in stems:
    x = load(stem); s = stretcher(x); glow, line = plants(x.shape); noise = 1.4826 * float(np.median(np.abs(x - np.median(x))))
    g, l = x + 3 * noise * glow, x + 5 * noise * line; truth = {"glow": s(g) - s(x), "line": s(l) - s(x)}
    u = {k: s(freetools.denoise(v)) for k, v in {"base": x, "glow": g, "line": l}.items()}; results[stem] = {}
    whole = {k: starnet(v) for k, v in u.items()}
    for name, out in {"graxpert-starnet": whole, "graxpert-starnet-blend": {k: blended(u[k], whole[k]) for k in u}}.items():
        row = star_scores(u["base"], out["base"])
        for key, mask in (("glow", glow), ("line", line)):
            d = N.gaussian_filter(out[key] - out["base"], 1.5); c = N.gaussian_filter(truth[key], 1.5); w = mask > .3
            row[key + "_kept"] = round(float((d[w] * c[w]).sum() / (c[w] ** 2).sum()), 3)
        results[stem][name] = row; print(stem, name, row, flush=True)
    json.dump(results, open(W / os.environ.get("TY_SCORES", "starnet-scores.json"), "w"), indent=1)
