"""The shared colour stacks as TelescopeYoke session folders, so colour.py can read them (protocol deviation 3).

colour.py takes one mono stack per filter; these are single colour stacks. Each is split into its channels:
through a dual-band filter (from the owner's stated filter, decided before any was read) red is Ha and the mean of
green and blue is OIII (palette HOO); otherwise red, green and blue, with their mean as L (palette LRGB). Set 41's
two dual-band stacks give Ha and OIII from one and SII from the other (SHO). XISF and TIFF are read by Siril.
Writes frames/D<set>/combined-<BAND>/final.fits in its own data tree; the downloads are only read.
"""
import json, os, subprocess, tempfile, zipfile
from pathlib import Path
import numpy as np
from astropy.io import fits

D = Path("/mnt/d/telescopyokearchive/training-data/discord")
OUT = Path.home() / "telescopeyoke-laptop/freetools/ds-site"
SIRIL = Path.home() / "telescopeyoke-laptop/freetools/dl/siril/squashfs-root/AppRun"
DUAL = {"07-L-Extreme-9h", "18-NGC7822", "37-Hidden-533MC", "43-RunningChicken-533MC", "65-D7000-Z73", "74-533MC-Askar103",
        "78-M42-533MC"}
BROAD = {"28-Dobson-SV605CC", "29-planetary-533MC", "31-150PDS-533MC", "40-D5500-70mm", "44-Bortle8-3h", "49-2600MC-367mm",
         "56-Crescent-D750", "57-D5300-untracked", "72-Rosette-R50"}


def read(path, work):
    with open(path, "rb") as f:
        head = f.read(8)
    if head.startswith(b"SIMPLE"):
        with fits.open(path) as h:
            hdu = next(x for x in h if x.data is not None and x.data.ndim >= 2)
            return hdu.data.astype(np.float32)
    ext = ".xisf" if head == b"XISF0100" else ".tif"
    link = Path(work) / ("a" + ext)
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(path)
    Path(work, "s.ssf").write_text(f"requires 1.4.0\nsetcpu 4\nsetext fits\nload a{ext}\nsave b\nclose\n")
    env = {k: v for k, v in os.environ.items() if k != "LD_LIBRARY_PATH"}
    r = subprocess.run([str(SIRIL), "siril-cli", "-d", work, "-s", f"{work}/s.ssf"], env=env, capture_output=True,
                       text=True, cwd=work, stdin=subprocess.DEVNULL, timeout=1800)
    out = Path(work) / "b.fits"
    if not out.exists():
        raise RuntimeError("Siril: " + (r.stdout + r.stderr)[-300:])
    data = fits.getdata(out).astype(np.float32)
    out.unlink()
    return data


def planes(data):
    data = np.squeeze(data)
    if data.ndim != 3:
        raise ValueError(f"not a colour stack: {data.shape}")
    return [data[i] for i in range(3)] if data.shape[0] == 3 else [data[..., i] for i in range(3)]


def write(name, band, plane, origin):
    folder = OUT / "frames" / name / f"combined-{band}"
    folder.mkdir(parents=True, exist_ok=True)
    head = fits.Header([("FILTER", band), ("TY_CALIB", True), ("EXPTIME", 1.0), ("ORIGIN", origin[:60])])
    fits.PrimaryHDU(np.ascontiguousarray(plane, np.float32), head).writeto(folder / "final.fits", overwrite=True)


made = {}
with tempfile.TemporaryDirectory(dir=Path.home() / "telescopeyoke-laptop/freetools") as work:
    for s in sorted(DUAL | BROAD | {"41-Apertura90-2600MC"}):
        name = "D" + s.split("-")[0]
        try:
            if s == "41-Apertura90-2600MC":
                z = zipfile.ZipFile(D / s / "stack.download"); out = {}
                for member, bands in (("HO_L_Ultimate.tif", ("Ha", "OIII")), ("SO_ColourMagic_E2.tif", ("SII", None))):
                    target = Path(work) / member
                    with z.open(member) as src, open(target, "wb") as dst:
                        while block := src.read(1 << 20):
                            dst.write(block)
                    r, g, b = planes(read(target, work)); target.unlink()
                    out[bands[0]] = r
                    if bands[1]:
                        out[bands[1]] = (g + b) / 2
                for band, p in out.items():
                    write(name, band, p, s)
                made[name] = ("SHO", sorted(out))
            else:
                r, g, b = planes(read(D / s / "stack.download", work))
                if s in DUAL:
                    write(name, "Ha", r, s); write(name, "OIII", (g + b) / 2, s); made[name] = ("HOO", ["Ha", "OIII"])
                else:
                    for band, p in (("R", r), ("G", g), ("B", b), ("L", (r + g + b) / 3)):
                        write(name, band, p, s)
                    made[name] = ("LRGB", ["L", "R", "G", "B"])
            print(name, made[name], flush=True)
        except Exception as e:
            print(name, "not read:", repr(e)[:200], flush=True)
json.dump(made, open(OUT / "made.json", "w"), indent=1)
print("done", made)
