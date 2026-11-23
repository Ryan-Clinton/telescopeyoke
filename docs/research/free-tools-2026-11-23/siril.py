"""Siril NL-Bayes, its default settings, on one prepared image at a time."""
import os, subprocess, sys
from pathlib import Path
import numpy as np
from astropy.io import fits
F = Path.home() / "telescopeyoke-laptop/freetools"; S = F / "dl/siril/squashfs-root"; W = F / "work-siril"
env = {k: v for k, v in os.environ.items() if k != "LD_LIBRARY_PATH"}
names = sys.argv[1:] or sorted(p.stem for p in (F / "in").glob("*.fits"))
for n in names:
    t = F / "out/siril" / f"{n}.npy"
    if t.exists(): continue
    (W / "a.fits").unlink(missing_ok=True); (W / "b.fits").unlink(missing_ok=True)
    (W / "a.fits").symlink_to(F / "in" / f"{n}.fits")
    (W / "s.ssf").write_text("requires 1.4.0\nsetext fits\nload a\ndenoise\nsave b\nclose\n")
    r = subprocess.run([str(S / "AppRun"), "siril-cli", "-d", str(W), "-s", str(W / "s.ssf")], env=env, capture_output=True, text=True)
    if not (W / "b.fits").exists(): sys.exit(r.stdout[-1500:] + r.stderr[-500:])
    x = fits.getdata(W / "b.fits").astype(np.float32).squeeze()
    if x.shape != fits.getdata(F / "in" / f"{n}.fits").shape: sys.exit(f"shape {x.shape}")
    np.save(t, x); print(n, flush=True)
