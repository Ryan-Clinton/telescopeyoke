#!/usr/bin/env python3
"""Everything a report of a new transient needs, gathered for a person to
check and send: never sent by the software.

    ./report.py M31-20261014-021118-001        a candidate on file (candidates.py)
    ./report.py M31-20261014-021118-001 --json

From the candidate book, the night's records (depth.json, candidates.json,
vetted.json) and the stacks, it puts together what the Transient Name
Server and the IAU's Central Bureau ask for:

- the position, with its uncertainty;
- when it was found (the middle of the night's frames, UTC);
- its magnitude with error and band, and the night's 5-sigma limit;
- the last time its place was measured without it, and how faint that was;
- the reference it was found against, and that reference's nights;
- the checks made (both halves of the night, asteroids, variables, the
  lists of reported novae and supernovae, Gaia) and what they found;
- a finding chart: the field round it, marked, with north up.

Every figure says whether it was measured here, inferred, or reported by
someone else. The packet is kept under reports/ID/ as report.json, the text
of an AT report ready to paste (report.txt) and finding.png, with how long it
took: the target is under five minutes from a confirmed candidate.
Nothing is sent, and nothing here moves the mount or uses the camera.
"""
import argparse
import json
import math
import time
from pathlib import Path

import numpy as np

import config
import interface
import records

BAND = "Clear (unfiltered CMOS), calibrated approximately to Gaia G"
CHART = 150        # pixels each side of the candidate in the finding chart (about 3.3′ at 1.32″)


def field_of(wanted):
    """The field a candidate's ID names: NAME-YYYYMMDD-HHMMSS-NNN, where a
    mosaic panel's NAME has a hyphen of its own (M31-P3)."""
    return wanted.rsplit("-", 3)[0]


def night_folder(name, night):
    return config.DATA / "frames" / name / night


def night_records(folder):
    """The night's own records, each or None."""
    out = {}
    for key, file in (("depth", "depth.json"), ("candidates", "candidates.json"), ("vetted", "vetted.json")):
        path = folder / file
        out[key] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    return out


def mid_time(folder):
    """The middle of a night's kept frames, from their DATE-OBS, UTC; or None."""
    from astropy.time import Time
    import stacking
    log = folder / "restack.json"
    names = [Path(k).name for k in json.loads(log.read_text(encoding="utf-8")).get("kept", [])] if log.exists() else []
    paths = [folder / n for n in names if (folder / n).exists()] or sorted(folder.glob("light-*.fits"))
    stamps = []
    for p in paths[:: max(1, len(paths) // 20)]:
        header = stacking.load_light(p)[1]
        if header.get("DATE-OBS"):
            stamps.append(Time(header["DATE-OBS"]).jd + float(header.get("EXPTIME", 0)) / 2 / 86400)
    return Time(float(np.median(stamps)), format="jd").isot[:19] if stamps else None


def position_error(fwhm_arcsec, score, residual_px, scale):
    """Arcseconds: a star's centroid to about its width over its
    signal-to-noise, and the lining-up of the two nights, together."""
    centroid = fwhm_arcsec / max(score, 1.0)
    return round(math.hypot(centroid, residual_px * scale), 2)


def last_miss(k, first_night):
    """The latest night before the first detection on which its place was
    measured and it was not there, with how faint it must have been."""
    misses = [n for n in k["nights"] if not n["seen"] and n.get("limit") is not None and n["night"] < first_night]
    return max(misses, key=lambda n: n["night"]) if misses else None


def assemble(name, k, folder, rec, when, earlier=None):
    """The packet as a dict, from what is on file. `earlier` is the history
    of the place in stacks before the first detection (forced.py), for the
    last non-detection when the book has none."""
    first = next(n for n in k["nights"] if n["seen"])
    depth = rec.get("depth") or {}
    found = rec.get("candidates") or {}
    vetted = next((c for c in (rec.get("vetted") or {}).get("candidates", [])
                   if c.get("ra") is not None and abs(c["ra"] - k["ra"]) < 3e-4 and abs(c["dec"] - k["dec"]) < 3e-4),
                  None)
    scale = depth.get("scale_arcsec_per_px", 1.32)
    packet = {
        "id": k["id"], "object": name, "ra": round(k["ra"], 6), "dec": round(k["dec"], 6),
        "ra_hms": hms(k["ra"] / 15), "dec_dms": dms(k["dec"]),
        "position_error_arcsec": position_error(depth.get("fwhm_arcsec", 6.0), first.get("score") or 5.0,
                                                found.get("alignment_residual_px", 0.2), scale),
        "discovered_utc": when, "night": first["night"],
        "mag": first.get("mag"), "mag_error": first.get("error") or (round(1.0857 / (first.get("score") or 5.0), 2)),
        "band": BAND,
        "limit_5sigma": (depth.get("limit_5sigma") or {}).get("sky"),
        "nights_seen": sum(1 for n in k["nights"] if n["seen"]), "nights_measured": len(k["nights"]),
        "reference": found.get("reference"), "science": found.get("new"),
        "difference": str(folder / "difference.fits") if folder else None,
        "checks": {key: (vetted or {}).get(key) for key in ("halves", "asteroid", "variable", "reported", "gaia",
                                                            "in_reference")},
        "verdict": (vetted or {}).get("verdict", first.get("verdict")),
        "kinds": {"ra": "measured", "dec": "measured", "position_error_arcsec": "inferred",
                  "discovered_utc": "measured", "mag": "measured", "mag_error": "inferred",
                  "limit_5sigma": "inferred", "checks": "reported", "last_non_detection": "measured"},
    }
    miss = last_miss(k, first["night"])
    if miss is None and earlier:
        before = [r for r in earlier if r.get("in_picture") and r.get("mag") is None and r.get("limit")
                  and r["session"] < first["night"]]
        miss = {"night": before[-1]["session"], "limit": before[-1]["limit"]} if before else None
    packet["last_non_detection"] = {"night": miss["night"], "limit": miss["limit"]} if miss else None
    packet["not_yet"] = missing(packet)
    return packet


def missing(p):
    """What a report would still want before it is sent."""
    out = []
    if p["nights_seen"] < 2:
        out.append("seen on one night only: confirm it on another night, or in someone else's picture")
    if p["mag"] is not None and p["limit_5sigma"] is not None and p["mag"] > p["limit_5sigma"]:
        out.append(f"G {p['mag']} is fainter than that night's 5-sigma limit ({p['limit_5sigma']}): "
                   "at the edge of what the stack can show")
    if p["last_non_detection"] is None:
        out.append("no earlier measurement of its place without it")
    if not (p["checks"].get("halves") and min(p["checks"]["halves"]) >= 3):
        out.append("not shown in both halves of the night")
    out.append("the Transient Name Server not searched here (it needs an account): search it by hand first")
    return out


def hms(hours):
    h = int(hours)
    m = int((hours - h) * 60)
    s = ((hours - h) * 60 - m) * 60
    return f"{h:02d}:{m:02d}:{s:05.2f}"


def dms(deg):
    sign = "+" if deg >= 0 else "-"
    deg = abs(deg)
    d = int(deg)
    m = int((deg - d) * 60)
    s = ((deg - d) * 60 - m) * 60
    return f"{sign}{d:02d}:{m:02d}:{s:04.1f}"


def text(p):
    """An AT report's fields, in the order the TNS form asks, to paste."""
    miss = p["last_non_detection"]
    lines = [
        f"Candidate {p['id']} ({p['object']} field), NOT YET SENT",
        f"RA (J2000)        {p['ra_hms']}  ({p['ra']:.6f} deg)",
        f"Dec (J2000)       {p['dec_dms']}  ({p['dec']:+.6f} deg)",
        f"Position error    {p['position_error_arcsec']} arcsec",
        f"Discovery date    {p['discovered_utc']} UT (middle of the night's frames)",
        f"Discovery mag     {p['mag']} +/- {p['mag_error']}  {p['band']}",
        f"Limiting mag      {p['limit_5sigma']} (5 sigma, that night's stack)",
        ("Last non-detection " + (f"{miss['night']}: fainter than {miss['limit']}" if miss else "none on file")),
        "Instrument        Sky-Watcher 150P (750 mm f/5) on EQ3 Pro, 183C colour CMOS, stacked",
        f"Seen on           {p['nights_seen']} of {p['nights_measured']} nights measured",
        f"Checks            halves {p['checks'].get('halves')}; asteroid {name_of(p['checks'].get('asteroid'))}; "
        f"variable {name_of(p['checks'].get('variable'))}; reported {name_of(p['checks'].get('reported'))}; "
        f"Gaia star {name_of(p['checks'].get('gaia'))}",
        f"Reference         {p['reference']}",
        "Before sending:",
    ] + [f"  - {item}" for item in p["not_yet"]]
    return "\n".join(lines) + "\n"


def name_of(match):
    return "none" if not match else match.get("name") or f"G {match.get('g')}"


def chart(science, ra, dec, name, path, half=CHART):
    """A finding chart: the field round the place resampled onto a grid with
    north up and east left (as on the sky, and as reports expect), marked."""
    from astropy.io import fits
    from astropy.wcs import WCS
    from PIL import Image, ImageDraw
    import depth
    import difference
    lum = depth.brightness(fits.getdata(science))
    wcs = depth.plate(lum, name)
    scale = float(np.sqrt(abs(np.linalg.det(wcs.wcs.cd))))
    grid = WCS(naxis=2)
    grid.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    grid.wcs.crval = [ra, dec]
    grid.wcs.crpix = [half + 1, half + 1]
    # East to the left: RA falls as the column number rises.
    grid.wcs.cd = np.array([[-scale, 0.0], [0.0, scale]])
    cut = difference.onto(lum, wcs, (2 * half + 1, 2 * half + 1), grid)
    lo, hi = np.nanpercentile(cut, [5, 99.7])
    img = np.clip((np.nan_to_num(cut, nan=lo) - lo) / (hi - lo + 1e-9) * 255, 0, 255).astype(np.uint8)
    # Row 0 of the grid is its south edge; a picture's first row is its top.
    picture = Image.fromarray(img[::-1]).convert("RGB").resize((600, 600))
    draw = ImageDraw.Draw(picture)
    c, r = 300, 26
    draw.ellipse([c - r, c - r, c + r, c + r], outline=(255, 60, 60), width=2)
    draw.text((10, 8), f"N up, E left   {(2 * half + 1) * scale * 60:.1f}' across", fill=(255, 255, 255))
    draw.text((10, 580), f"{hms(ra / 15)} {dms(dec)}", fill=(255, 255, 255))
    picture.save(path)
    return str(path)


def run(args, say=print):
    import candidates
    import forced
    began = time.monotonic()
    name = field_of(args.id)
    book = candidates.load(name)
    k = next((c for c in book["candidates"] if c["id"] == args.id), None)
    if k is None:
        raise interface.Refusal("INVALID_REQUEST", f"No candidate {args.id} on file: ./candidates.py {name} --all")
    first = next(n for n in k["nights"] if n["seen"])
    folder = night_folder(name, first["night"])
    rec = night_records(folder)
    earlier = None
    if last_miss(k, first["night"]) is None and not args.quick:
        earlier = forced.history(name, k["ra"], k["dec"], say=lambda *_: None)
    packet = assemble(name, k, folder, rec, mid_time(folder), earlier)
    out = config.DATA / "reports" / args.id
    out.mkdir(parents=True, exist_ok=True)
    if not args.quick and packet["science"] and Path(packet["science"]).exists():
        packet["finding_chart"] = chart(packet["science"], k["ra"], k["dec"], name, out / "finding.png")
    packet["seconds"] = round(time.monotonic() - began, 1)
    records.write(out / "report.json", packet, schema="report", stamp=True)
    (out / "report.txt").write_text(text(packet), encoding="utf-8")
    say(text(packet).rstrip())
    say(f"gathered in {packet['seconds']} s; kept under {out}")
    return packet


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("id", help="a candidate on file, as candidates.py names it")
    ap.add_argument("--quick", action="store_true", help="no finding chart and no search of earlier stacks")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("report", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
