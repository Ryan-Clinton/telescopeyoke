"""Colour calibration compared: Siril 1.4.5's SPCC against our star-average balance (process.process), on M33's R, G
and B stacks of 5 November, lined up as colour.py lines them up. Neither was tuned on them.

The filters' make is not recorded, so SPCC runs with each RGB set in its database and the spread is reported.
Judged on Gaia DR3 stars in the field (ESA's Gaia archive): a Sun-like star (BP-RP 0.72 to 0.92) should come out
white, as SPCC's G2V white reference intends. Pass, fixed before any result: SPCC replaces ours only if Sun-like
stars come out closer to white, with the scatter of star colour against BP-RP no worse. Copies only.
"""
import csv, io, json, os, subprocess, sys, tempfile, urllib.parse, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path.home() / "telescopeyoke-laptop/remote/code"))
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
import colour, process

F = Path.home() / "telescopeyoke-laptop/freetools"; W = F / "spcc"; W.mkdir(exist_ok=True); SI = F / "dl/siril/squashfs-root/AppRun"
CENTRE = (23.4621, 30.6599)       # M33
FILTERS = {"Antlia": ("Antlia R", "Antlia G", "Antlia B"), "Astronomik DeepSky": tuple(f"Astronomik Deep Sky RGB {c}" for c in ("Red", "Green", "Blue")),
           "Astronomik 2c": tuple(f"Astronomik Typ 2 c {c}" for c in ("Red", "Green", "Blue")), "Baader": ("Baader R", "Baader G", "Baader B"),
           "Chroma": ("Chroma Red", "Chroma Green", "Chroma Blue"), "Optolong": ("Optolong Red", "Optolong Green", "Optolong Blue"),
           "ToupTek": ("ToupTek R", "ToupTek G", "ToupTek B"), "ZWO": tuple(f"ZWO Optimized for CMOS {c}" for c in ("Red", "Green", "Blue"))}


def load(band):
    d = fits.getdata(F / "real" / f"M33{band}-u.fits").astype(np.float32)
    d = d[0] if d.ndim == 3 else d
    return np.where(np.isfinite(d), d, np.nan)


def siril(d, script):
    Path(f"{d}/s.ssf").write_text("requires 1.4.0\nsetcpu 4\nsetext fits\n" + script + "close\n")
    env = {k: v for k, v in os.environ.items() if k != "LD_LIBRARY_PATH"}
    return subprocess.run([str(SI), "siril-cli", "-d", d, "-s", f"{d}/s.ssf"], env=env, capture_output=True, text=True,
                          cwd=d, stdin=subprocess.DEVNULL, timeout=1800)


def gaia(radius):
    query = (f"SELECT ra, dec, phot_g_mean_mag, bp_rp FROM gaiadr3.gaia_source WHERE 1=CONTAINS(POINT(ra, dec), "
             f"CIRCLE({CENTRE[0]}, {CENTRE[1]}, {radius})) AND phot_g_mean_mag BETWEEN 10 AND 15.5 AND bp_rp IS NOT NULL")
    data = urllib.parse.urlencode({"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": query}).encode()
    with urllib.request.urlopen("https://gea.esac.esa.int/tap-server/tap/sync", data, timeout=300) as r:
        return list(csv.DictReader(io.StringIO(r.read().decode())))


def fluxes(rgb, xy):
    """Each star's light in each channel, an aperture of 6 px less the median of a 10 to 15 px ring."""
    yy, xx = np.mgrid[-15:16, -15:16]; d = np.hypot(yy, xx); core, ring = d <= 6, (d >= 10) & (d <= 15)
    out = []
    for x, y in xy:
        r, c = int(round(y)), int(round(x))
        if not (16 <= r < rgb.shape[0] - 16 and 16 <= c < rgb.shape[1] - 16): out.append(None); continue
        p = rgb[r - 15:r + 16, c - 15:c + 16]
        out.append([float((p[..., k][core] - np.median(p[..., k][ring])).sum()) for k in range(3)])
    return out


def judge(f, bprp):
    """Sun-like stars' colour (B over R and G over R, in magnitudes; 0 is white) and the scatter round a line."""
    f = np.asarray(f); good = (f > 0).all(axis=1); f, bprp = f[good], bprp[good]
    br, gr = -2.5 * np.log10(f[:, 2] / f[:, 0]), -2.5 * np.log10(f[:, 1] / f[:, 0])
    sun = (bprp > .72) & (bprp < .92)
    fit = np.polyfit(bprp, br, 1); scatter = 1.4826 * float(np.median(np.abs(br - np.polyval(fit, bprp))))
    b, g = float(np.median(br[sun])), float(np.median(gr[sun]))
    return {"sun_like_stars": int(sun.sum()), "sun_b_minus_r": round(b, 3), "sun_g_minus_r": round(g, 3),
            "off_white": round(float(np.hypot(b, g)), 3), "scatter_mag": round(scatter, 3), "stars": int(good.sum())}


raw = {b: load(b) for b in "RGB"}
rows, cols = min(p.shape[0] for p in raw.values()), min(p.shape[1] for p in raw.values())
raw = {b: p[:rows, :cols] for b, p in raw.items()}
ref = np.nan_to_num(raw["R"]); reference = {"square": colour.stacking.centre_square(ref), "stars": colour.stacking.find_stars(ref)}
planes = {"R": raw["R"]}
for b in "GB":
    planes[b], info, _ = colour.lined_up(raw[b], reference)
    if not colour.fits_well(info): sys.exit(f"{b} did not line up")
good = np.all([np.isfinite(p) for p in planes.values()], axis=0)
c = np.flatnonzero(good.mean(axis=0) > .5); r = np.flatnonzero(good[:, c[0]:c[-1] + 1].mean(axis=1) > .98)
c = np.flatnonzero(good[r[0]:r[-1] + 1].mean(axis=0) > .98)
rgb = np.stack([np.nan_to_num(planes[b][r[0]:r[-1] + 1, c[0]:c[-1] + 1], nan=float(np.nanmedian(planes[b]))) for b in "RGB"], axis=2)
rgb = (rgb - rgb.min()) / (rgb.max() - rgb.min())

# Siril's own plate solve needs the CDS catalogue service, which did not answer (24 November 2026): the picture
# is solved by ASTAP on the laptop instead, from lum.fits, and its WCS comes back as wcs.hdr.
if not (W / "wcs.hdr").exists():
    fits.PrimaryHDU(np.clip(rgb.mean(axis=2) * 65535, 0, 65535).astype(np.uint16)).writeto(W / "lum.fits", overwrite=True)
    sys.exit(f"solve {W / 'lum.fits'} and put its WCS header in {W / 'wcs.hdr'}, then run this again")
wcs_cards = fits.Header.fromfile(str(W / "wcs.hdr"), sep="", endcard=True, padding=False)
results = {}
with tempfile.TemporaryDirectory(dir=W) as d:
    head = fits.Header([c for c in wcs_cards.cards if c.keyword not in ("SIMPLE", "BITPIX", "NAXIS", "NAXIS1", "NAXIS2", "EXTEND", "END", "")])
    fits.PrimaryHDU(np.moveaxis(rgb, 2, 0).astype(np.float32), head).writeto(f"{d}/rgb.fits")
    done = siril(d, "load rgb\nsave solved\n")
    if not Path(f"{d}/solved.fits").exists(): sys.exit("Siril would not load the picture: " + (done.stdout + done.stderr)[-1500:])
    # Everything is measured on the file Siril solved, so its pixels and its WCS always agree.
    head = fits.getheader(f"{d}/solved.fits"); wcs = WCS(head).celestial
    rgb = np.moveaxis(fits.getdata(f"{d}/solved.fits").astype(np.float32), 0, -1)
    stars = gaia(0.6)
    xy = wcs.all_world2pix(np.array([[float(s["ra"]), float(s["dec"])] for s in stars]), 0)
    bprp = np.array([float(s["bp_rp"]) for s in stars])
    inside = (xy[:, 0] > 16) & (xy[:, 0] < rgb.shape[1] - 16) & (xy[:, 1] > 16) & (xy[:, 1] < rgb.shape[0] - 16)
    xy, bprp = xy[inside], bprp[inside]
    print(len(stars), "Gaia stars,", int(inside.sum()), "in the frame", flush=True)
    # Ours: sky off, then the average star white, as process.process does.
    sky = process.remove_sky(rgb.copy(), 2); grey = sky.mean(axis=2); spread = 1.4826 * np.median(np.abs(grey))
    star = (grey > 15 * spread) & (grey < .5 * grey.max()); balance = sky[star].mean(axis=0); gain = balance.mean() / balance
    base = fluxes(rgb, xy); keep = [i for i, f in enumerate(base) if f is not None]
    hits = np.median([sum(base[i]) for i in keep]) / (3 * 113 * spread)      # light in a 6 px aperture over its noise
    print("Gaia stars land on stars:", round(float(hits), 1), "(well above 1 if the WCS fits)", flush=True)
    results["none"] = judge([base[i] for i in keep], bprp[keep])
    results["ours"] = judge([np.array(base[i]) * gain for i in keep], bprp[keep]); results["ours"]["gains"] = [round(float(g), 4) for g in gain]
    print("none", results["none"], "\nours", results["ours"], flush=True)
    for name, (rf, gf, bf) in FILTERS.items():
        done = siril(d, f'load solved\nspcc "-monosensor=Sony IMX183" "-rfilter={rf}" "-gfilter={gf}" "-bfilter={bf}"\nsave out\n')
        if not Path(f"{d}/out.fits").exists():
            results[f"spcc {name}"] = {"error": (done.stdout + done.stderr)[-300:]}; print(name, "failed", flush=True); continue
        out = np.moveaxis(fits.getdata(f"{d}/out.fits").astype(np.float32), 0, -1)
        f = fluxes(out, xy); results[f"spcc {name}"] = judge([f[i] for i in keep], bprp[keep])
        print("spcc", name, results[f"spcc {name}"], flush=True)
        Path(f"{d}/out.fits").unlink()
json.dump(results, open(W / "scores.json", "w"), indent=1)
