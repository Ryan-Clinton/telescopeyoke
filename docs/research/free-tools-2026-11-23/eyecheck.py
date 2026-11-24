"""Eye check of freetools.remove_stars after GraXpert: for each stack, around its brightest star and its darkest
smooth patch, the denoised stack beside the starless one. Pictures stay on the desktop and in the archive."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "ft")); sys.path.insert(1, str(Path.home() / "telescopeyoke-laptop/remote/code"))
import numpy as np
from PIL import Image
from scipy import ndimage as N
import freetools
import stacking
C = Path(__file__).parent; ns = {"__file__": str(C / "stars.py")}; sys.argv = ["x"]
exec((C / "stars.py").read_text().split("results = {}")[0], ns)
rows = []
for stem in ("IC1848-chain", "M45-v4", "NGC7331-v4"):
    x = ns["load"](stem); s = ns["stretcher"](x); clean = freetools.denoise(x); out = freetools.remove_stars(clean, freetools.grain(x))
    a, b = s(clean), s(out)
    star = stacking.find_stars(a)[0]; places = [(int(star[1]), int(star[0]))]
    soft = N.gaussian_filter(b, 6)[::4, ::4]; rest = soft - N.median_filter(soft, 23); r, c = np.unravel_index(np.argmin(rest[10:-10, 10:-10]), rest[10:-10, 10:-10].shape)
    places.append(((r + 10) * 4, (c + 10) * 4))
    for r, c in places:
        r = int(np.clip(r - 200, 0, a.shape[0] - 400)); c = int(np.clip(c - 200, 0, a.shape[1] - 400))
        rows.append(np.hstack([a[r:r + 400, c:c + 400], np.ones((400, 6)), b[r:r + 400, c:c + 400]]))
    print(stem, "done", flush=True)
gap = lambda: np.ones((6, rows[0].shape[1]))
pic = np.vstack([p for row in rows for p in (row, gap())][:-1])
Image.fromarray((np.clip(pic, 0, 1) * 255).astype(np.uint8)).save(ns["W"] / "eyecheck.jpg", quality=90)
