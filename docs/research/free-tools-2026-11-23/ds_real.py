"""Protocol step 2 on the shared sets: every filter's stack of each set into the star tests' folder
(real/D..-FILTER-ds.fits), binned 2 by 2 when over 10 megapixels, as am_real.py does. Prints the stems."""
from pathlib import Path
import numpy as np
from astropy.io import fits
F = Path.home() / "telescopeyoke-laptop/freetools"
stems = []
for target in sorted((F / "ds-site/frames").iterdir()):
    for p in sorted(target.glob("combined-*/final.fits")):
        band = p.parent.name.split("-", 1)[1]
        d = fits.getdata(p).astype(np.float32)
        d = d[0] if d.ndim == 3 else d
        if d.size > 10e6:
            r, c = d.shape[0] // 2 * 2, d.shape[1] // 2 * 2
            d = d[:r, :c].reshape(r // 2, 2, c // 2, 2).mean(axis=(1, 3))
        stem = f"{target.name}-{band}-ds"
        fits.PrimaryHDU(d).writeto(F / "real" / f"{stem}.fits", overwrite=True)
        stems.append(stem)
print(" ".join(stems))
