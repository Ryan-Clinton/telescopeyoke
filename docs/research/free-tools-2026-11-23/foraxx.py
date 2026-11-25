"""The Foraxx dynamic palette beside colour.py's fixed one, for comparing by eye (not a verdict). Each filter's stack is
lined up as colour.py lines them up, stretched alone (black at its sky, white at its 99.9th percentile, an asinh
curve), then combined by Foraxx's published formulas, ~x being 1 - x:
  SHO: R = (O^~O) S + ~(O^~O) H,  G = ((O H)^~(O H)) H + ~((O H)^~(O H)) O,  B = O
  HOO: R = H,                    G as above,                               B = O
Copies only; the picture is written beside colour.py's.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / "telescopeyoke-laptop/freetools/pipe-new"))
import numpy as np
from PIL import Image
import colour

site, name = Path(sys.argv[1]), sys.argv[2]
bands = [b for b in ("SII", "Ha", "OIII") if (site / "frames" / name / f"combined-{b}" / "final.fits").exists()]
planes = {b: colour.brightness(site / "frames" / name / f"combined-{b}" / "final.fits") for b in bands}
ref = np.nan_to_num(planes["Ha"]); reference = {"square": colour.stacking.centre_square(ref), "stars": colour.stacking.find_stars(ref)}
for b in bands:
    if b != "Ha":
        planes[b], info, _ = colour.lined_up(planes[b], reference)
        if not colour.fits_well(info): sys.exit(f"{b} did not line up")
rows, cols = min(p.shape[0] for p in planes.values()), min(p.shape[1] for p in planes.values())


def stretch(p):
    p = np.nan_to_num(p[:rows, :cols], nan=float(np.nanmedian(p)))
    sky = float(np.median(p)); top = float(np.percentile(p, 99.9))
    x = np.clip((p - sky) / max(top - sky, 1e-9), 0, 1)
    return np.arcsinh(x * 40) / np.arcsinh(40)


s = {b: stretch(p) for b, p in planes.items()}
H, O = s["Ha"], s["OIII"]
w2 = (O * H) ** (1 - O * H)
G = w2 * H + (1 - w2) * O
if "SII" in s:
    w1 = O ** (1 - O)
    R = w1 * s["SII"] + (1 - w1) * H
else:
    R = H
rgb = np.clip(np.dstack([R, G, O]), 0, 1)
out = site / "web" / f"{name}-foraxx.jpg"
Image.fromarray((rgb * 255).astype(np.uint8)).save(out, quality=92)
print("saved", out)
