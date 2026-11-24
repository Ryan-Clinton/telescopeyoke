"""NGC 2174 in SHO the plain free way, for comparing by eye with colour.py: the three GraXpert-denoised stacks lined
up as colour.py lines them up, put in the channels by Siril 1.4.5's rgbcomp, its autostretch on each channel, the
suite's green removal (SCNR) as SHO pictures usually have. Neither Siril nor the suite has an automatic palette tool
beyond this. Copies only; the picture is written beside the comparisons.
"""
import os, subprocess, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path.home() / "telescopeyoke-laptop/remote/code"))
import numpy as np
from astropy.io import fits
from PIL import Image
import colour
import freetools

F = Path.home() / "telescopeyoke-laptop/freetools"; SI = F / "dl/siril/squashfs-root/AppRun"; SAS = F / "sas/bin/setiastrosuitepro"
SITE = F / "site/chain-old/frames/NGC2174"; OUT = Path(sys.argv[1] if sys.argv[1:] else F / "palette-siril.jpg")
planes = {b: colour.brightness(SITE / f"combined-{b}" / "final.fits") for b in ("SII", "Ha", "OIII")}
planes = {b: freetools.denoise(p) for b, p in planes.items()}
ref = np.nan_to_num(planes["Ha"]); reference = {"square": colour.stacking.centre_square(ref), "stars": colour.stacking.find_stars(ref)}
for b in ("SII", "OIII"):
    planes[b], info, _ = colour.lined_up(planes[b], reference)
    if not colour.fits_well(info): sys.exit(f"{b} did not line up")
rows, cols = min(p.shape[0] for p in planes.values()), min(p.shape[1] for p in planes.values())
with tempfile.TemporaryDirectory() as d:
    for b, p in planes.items():
        p = np.nan_to_num(p[:rows, :cols], nan=float(np.nanmedian(p))); lo, hi = np.percentile(p, (0.01, 99.999))
        fits.PrimaryHDU(np.clip((p - lo) / (hi - lo), 0, 1).astype(np.float32)).writeto(f"{d}/{b}.fits")
    Path(f"{d}/s.ssf").write_text("requires 1.4.0\nsetcpu 4\nsetext fits\nrgbcomp SII Ha OIII -out=rgb\nload rgb\n"
                                  "autostretch\nsave str\nclose\n")
    env = {k: v for k, v in os.environ.items() if k != "LD_LIBRARY_PATH"}
    r = subprocess.run([str(SI), "siril-cli", "-d", d, "-s", f"{d}/s.ssf"], env=env, capture_output=True, text=True, cwd=d,
                       stdin=subprocess.DEVNULL, timeout=600)
    if not Path(f"{d}/str.fits").exists(): sys.exit("Siril: " + (r.stdout + r.stderr)[-800:])
    r = subprocess.run([str(SAS), "process", "remove_green", "-i", f"{d}/str.fits", "-o", f"{d}/out.fits", "-q"], cwd=d,
                       capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=600,
                       env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
    if not Path(f"{d}/out.fits").exists(): sys.exit("SCNR: " + (r.stdout + r.stderr)[-800:])
    rgb = fits.getdata(f"{d}/out.fits").astype(np.float32)
rgb = np.moveaxis(rgb, 0, -1) if rgb.shape[0] == 3 else rgb
Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8)).save(OUT, quality=92)
print("saved", OUT)
