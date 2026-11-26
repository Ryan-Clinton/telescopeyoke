"""DIAGNOSTIC: each shared stack's local grain (robust spread in 32 px blocks, after a 5 px median is taken
off) against the stack's typical grain, saved as a small picture: where a stack's frames did not all reach,
or the stacker filled the edge, the grain differs. Copies only."""
import sys
from pathlib import Path
import numpy as np
from astropy.io import fits
from PIL import Image
from scipy import ndimage as N

F = Path.home() / "telescopeyoke-laptop/freetools/ds-site/frames"
OUT = Path.home() / "telescopeyoke-laptop/freetools/noisemaps"; OUT.mkdir(exist_ok=True)
for s in sys.argv[1:]:
    band = next(b for b in ("L", "Ha", "G") if (F / s / f"combined-{b}/final.fits").exists())
    d = np.nan_to_num(fits.getdata(F / s / f"combined-{band}/final.fits").astype(np.float32))
    d = d[0] if d.ndim == 3 else d
    fine = d - N.median_filter(d, 5)
    B = 32; h, w = d.shape[0] // B * B, d.shape[1] // B * B
    blocks = np.abs(fine[:h, :w]).reshape(h // B, B, w // B, B).transpose(0, 2, 1, 3).reshape(h // B, w // B, -1)
    grain = 1.4826 * np.median(blocks, axis=2)
    ratio = grain / np.median(grain)
    img = np.clip(np.log2(np.maximum(ratio, 1e-3)) / 4 + 0.5, 0, 1)   # 1/4 to 4 times the usual grain, grey at 1
    Image.fromarray((img * 255).astype(np.uint8)).resize((w // 8, h // 8), Image.NEAREST).save(OUT / f"{s}.png")
    print(s, band, "blocks under half the usual grain:", round(float((ratio < 0.5).mean()), 3),
          "over twice:", round(float((ratio > 2).mean()), 3), flush=True)
