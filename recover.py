#!/usr/bin/env python3
"""Can the pipeline find a transient that really happened? A known one,
from archive images, run through the same subtraction and checks.

    ./recover.py AT2024koe 10.32290 40.96525 --before 2024-05-21 --after 2024-06-27
    ./recover.py AT2024koe 10.32290 40.96525 --before 2024-05-21 --after 2024-06-27 --json

Planted fakes prove the pipeline finds what was put there; this asks it to
find something nobody put there. For each date it takes the Zwicky
Transient Facility's public science image of the place with the sharpest
stars within three days in the same filter (IRSA), cuts out the field
round it, and subtracts the earlier from the later with difference.py,
each image placed by the sky position in its own header. It then says
whether a candidate came up at the transient's place, how strong and how
bright, where it ranks among all the night's candidates, and what the
catalogues say about it.

The images are ZTF's (a 1.2 m telescope, 1″ pixels), not this rig's, so this
proves the software, not the telescope's depth. Magnitudes are on ZTF's own
zero point (MAGZP) in its filter. Cut-outs are kept under cache/ztf/.
Nothing here moves the mount or uses the camera.
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np
import requests
from astropy.io import fits
from astropy.time import Time
from astropy.wcs import WCS

import config
import interface

SEARCH = "https://irsa.ipac.caltech.edu/ibe/search/ztf/products/sci"
DATA = "https://irsa.ipac.caltech.edu/ibe/data/ztf/products/sci"
WITHIN_DAYS = 3.0      # an image this close to the date asked for will do
SIZE = 600             # arcseconds across the cut-out
FOUND_WITHIN = 3.0     # arcseconds between the transient and the candidate that is it


def images_near(ra, dec, date, band, within=WITHIN_DAYS, get=requests.get):
    """ZTF science images of the place within `within` days of a date, in a
    filter (zg, zr, zi), sharpest first: rows of the IRSA search."""
    jd = Time(date).jd
    reply = get(SEARCH, timeout=120, params={
        "POS": f"{ra:.5f},{dec:.5f}", "ct": "csv",
        "WHERE": f"obsjd BETWEEN {jd - within} AND {jd + within} AND filtercode='{band}'",
        "columns": "field,ccdid,qid,filtercode,obsjd,filefracday,seeing,maglimit,infobits"})
    reply.raise_for_status()
    lines = [l for l in reply.text.splitlines() if l.strip()]
    if len(lines) < 2:
        return []
    keys = lines[0].split(",")
    rows = [dict(zip(keys, l.split(","))) for l in lines[1:]]
    clean = [r for r in rows if int(r["infobits"]) == 0] or rows     # flagged images only if nothing else
    return sorted(clean, key=lambda r: float(r["seeing"]))


def url(row, ra, dec, size=SIZE):
    ff = row["filefracday"]
    return (f"{DATA}/{ff[:4]}/{ff[4:8]}/{ff[8:]}/ztf_{ff}_{int(row['field']):06d}_{row['filtercode']}_"
            f"c{int(row['ccdid']):02d}_o_q{row['qid']}_sciimg.fits?center={ra:.5f},{dec:.5f}&size={size}arcsec&gzip=false")


def cutout(row, ra, dec, get=requests.get):
    """A cut-out of one image round the place, kept in the cache."""
    store = config.DATA / "cache" / "ztf"
    path = store / f"{row['filefracday']}_{row['field']}_{row['ccdid']}_{row['qid']}_{ra:.4f}_{dec:+.4f}.fits"
    if not path.exists():
        reply = get(url(row, ra, dec), timeout=300)
        reply.raise_for_status()
        if not reply.content.startswith(b"SIMPLE"):
            raise interface.Refusal("INVALID_REQUEST", "IRSA sent back something that is not a FITS image "
                                    "(its image server may be down for a while); try again later.")
        store.mkdir(parents=True, exist_ok=True)
        path.write_bytes(reply.content)
    return path


def load(path):
    """(image, its WCS, its zero point, its date) from a ZTF cut-out."""
    with fits.open(path) as hdul:
        image = hdul[0].data.astype(np.float32)
        header = hdul[0].header
    image = np.where(np.isfinite(image), image, 0.0)
    return image, WCS(header), float(header.get("MAGZP", 0)) or None, header.get("OBSJD")


def recover(name, ra, dec, before, after, band, say=print, get=requests.get, subtract=None):
    """Find the transient: the answer as a dict."""
    import difference
    import vet
    subtract = subtract or difference.subtract
    picked = {}
    for when, date in (("reference", before), ("new", after)):
        rows = images_near(ra, dec, date, band, get=get)
        if not rows:
            raise interface.Refusal("NO_SESSION", f"No ZTF {band} image of the place within {WITHIN_DAYS:g} days "
                                    f"of {date}.")
        picked[when] = rows[0]
        say(f"{when}: ZTF {band} {rows[0]['filefracday']}, seeing {float(rows[0]['seeing']):.1f}\", "
            f"limit {float(rows[0]['maglimit']):.1f}")
    ref, ref_wcs, _, _ = load(cutout(picked["reference"], ra, dec, get))
    new, new_wcs, zp, jd = load(cutout(picked["new"], ra, dec, get))
    record, _ = subtract(new, ref, new_wcs, ref_wcs, zp)
    found = record["candidates"]
    for c in found:
        if "ra" not in c:
            c["ra"], c["dec"] = (float(v) for v in ref_wcs.pixel_to_world_values(c["x"], c["y"]))
    distances = [float(vet.separation(ra, dec, c["ra"], c["dec"])) for c in found]
    best = int(np.argmin(distances)) if found else None
    hit = best is not None and distances[best] <= FOUND_WITHIN
    answer = {"name": name, "ra": ra, "dec": dec, "band": f"ZTF {band}", "reference_image": picked["reference"]["filefracday"],
              "new_image": picked["new"]["filefracday"], "candidates": len(found), "fading_peaks": record.get("fading_peaks"),
              "recovered": hit, "kind": "measured"}
    if hit:
        c = found[best]
        answer.update(arcsec_off=round(distances[best], 2), score=c["score"], mag=c.get("mag"),
                      rank=1 + sorted((x["score"] for x in found), reverse=True).index(c["score"]),
                      as_strong_fading=c.get("as_strong_fading"))
        say(f"recovered: {answer['arcsec_off']}\" from the known place, {c['score']:.1f} sigma, "
            f"{band} {c.get('mag')}, number {answer['rank']} of {len(found)} candidates "
            f"({c.get('as_strong_fading')} fading peaks as strong)")
    else:
        nearest = round(distances[best], 1) if found else None
        answer["nearest_arcsec"] = nearest
        say(f"NOT recovered: {len(found)} candidates, the nearest {nearest}\" from the known place")
    return answer


def run(args, say=print):
    answer = recover(args.name, args.ra, args.dec, args.before, args.after, args.band, say)
    kept = config.DATA / "cache" / "ztf" / f"recover-{args.name}.json"
    kept.write_text(json.dumps(answer, indent=1), encoding="utf-8")
    return answer


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("name", help="what it is called, for the record")
    ap.add_argument("ra", type=float, help="degrees")
    ap.add_argument("dec", type=float, help="degrees")
    ap.add_argument("--before", required=True, help="a date before it appeared (YYYY-MM-DD): the reference")
    ap.add_argument("--after", required=True, help="a date while it was there (YYYY-MM-DD)")
    ap.add_argument("--band", default="zr", choices=("zg", "zr", "zi"), help="ZTF filter (default zr)")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("recover", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
