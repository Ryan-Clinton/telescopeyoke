#!/usr/bin/env python3
"""Build data/targets.csv from the OpenNGC database.

OpenNGC (https://github.com/mattiaverga/OpenNGC) is licensed CC-BY-SA-4.0;
data/targets.csv is a filtered derivative and carries the same licence.

Run this only to regenerate the catalogue, e.g. to change the brightness cuts.
"""
import csv
import io
import sys
import urllib.request
from pathlib import Path

import host  # noqa: F401  (makes printed output UTF-8 on Windows)

# A release, not master: master's working copy has lost the magnitudes of
# M22, M35, M71 and some forty more (November 2026), which the release has.
RELEASE = "v20260501"
BASE = f"https://raw.githubusercontent.com/mattiaverga/OpenNGC/{RELEASE}/database_files/"
FILES = ("NGC.csv", "addendum.csv")
OUT = Path(__file__).parent / "data" / "targets.csv"

# Faintest magnitude kept per object type, for things that are neither Messier
# objects nor named. Set for a camera stacking on a 150 mm telescope, not an
# eye at the eyepiece: a night's stack of M31 reaches about G 17.8, and the
# galaxies of magnitude 11 to 12 are the supernova watch's fields. Each is
# also kept only at least MIN_SIZE across: smaller is a smudge in the frame.
MAG_LIMIT = {
    "G": 12.0, "GPair": 12.0, "GTrpl": 12.0, "GGroup": 12.0,
    "OCl": 9.5, "*Ass": 9.5, "Cl+N": 10.0,
    "GCl": 11.0,
    "PN": 12.5,
    "Neb": 12.0, "HII": 12.0, "EmN": 12.0, "RfN": 12.0, "SNR": 12.0,
}
# The cut this catalogue had for the eyepiece, kept as well, so widening it
# never drops an object it held: a bright planetary nebula a few arcseconds
# across is still a sight.
EYE_LIMIT = {
    "G": 10.5, "GPair": 10.5, "GTrpl": 10.5, "GGroup": 10.5,
    "OCl": 8.0, "*Ass": 8.0, "Cl+N": 9.0,
    "GCl": 9.5,
    "PN": 11.0,
    "Neb": 10.0, "HII": 10.0, "EmN": 10.0, "RfN": 10.0, "SNR": 10.0,
}
MIN_SIZE = {"G": 1.5, "GPair": 1.5, "GTrpl": 1.5, "GGroup": 1.5, "PN": 0.5}
# A globular cluster OpenNGC gives no magnitude for is kept this wide or wider.
GLOBULAR_SIZE = 3.0
# Big enough to keep with no magnitude at all, or however faint: a cluster
# or nebula this wide (arcminutes) fills much of the 1.0° x 0.67° frame.
WIDE = 20.0
NAMED_MAG_LIMIT = 11.5
SKIP_TYPES = {"Dup", "NonEx", "*", "Nova"}

# Corrections to OpenNGC, each with where the right figure comes from. It
# gives the North America Nebula 120' x 30'; it is about 120' x 100' (as
# this catalogue has had since 15 October 2026), which matters for its
# mosaic and its surface brightness.
CORRECTIONS = {"NGC7000": {"MinAx": "100.00"}}

# Coarse classes used for scoring and display.
KIND = {
    "G": "galaxy", "GPair": "galaxy", "GTrpl": "galaxy", "GGroup": "galaxy",
    "OCl": "open cluster", "*Ass": "open cluster", "Cl+N": "cluster+nebula",
    "GCl": "globular",
    "PN": "planetary nebula",
    "Neb": "nebula", "HII": "nebula", "EmN": "nebula", "RfN": "nebula",
    "SNR": "nebula", "DrkN": "dark nebula",
    "**": "double star", "Other": "asterism",
}


def sexagesimal(text, hours):
    sign = -1.0 if text.startswith("-") else 1.0
    a, b, c = (float(p) for p in text.lstrip("+-").split(":"))
    deg = sign * (a + b / 60 + c / 3600)
    return deg * 15 if hours else deg


def number(text):
    return float(text) if text else None


def fetch(name):
    with urllib.request.urlopen(BASE + name, timeout=60) as r:
        return list(csv.DictReader(io.StringIO(r.read().decode()), delimiter=";"))


def main():
    rows = []
    for name in FILES:
        rows += [dict(r, addendum=(name == "addendum.csv")) for r in fetch(name)]

    out = []
    for r in rows:
        r.update(CORRECTIONS.get(r["Name"], {}))
        kind = KIND.get(r["Type"])
        if r["Type"] in SKIP_TYPES or not r["RA"] or kind is None:
            continue
        mag = number(r["V-Mag"]) or number(r["B-Mag"])
        messier = int(r["M"]) if r["M"] else None
        common = r["Common names"].split(",")[0].strip()
        if messier or r["addendum"]:
            keep = True
        elif common:
            keep = mag is None or mag <= NAMED_MAG_LIMIT
        else:
            size = number(r["MajAx"]) or 0.0
            wide = size >= WIDE and r["Type"] not in MIN_SIZE
            bright = mag is not None and mag <= MAG_LIMIT.get(r["Type"], -99)
            eye = mag is not None and mag <= EYE_LIMIT.get(r["Type"], -99)
            globular = r["Type"] == "GCl" and mag is None and size >= GLOBULAR_SIZE
            keep = eye or wide or globular or (bright and size >= MIN_SIZE.get(r["Type"], 0.0))
        if not keep:
            continue
        ident = r["Name"]
        if ident.startswith(("NGC", "IC")):
            prefix = "NGC" if ident.startswith("NGC") else "IC"
            ident = f"{prefix} {ident[len(prefix):].lstrip('0')}"
        out.append({
            "id": f"M{messier}" if messier else ident,
            "alt_id": ident if messier and not ident.startswith("M") else "",
            "name": common,
            "kind": kind,
            "const": r["Const"],
            "ra_deg": f"{sexagesimal(r['RA'], hours=True):.5f}",
            "dec_deg": f"{sexagesimal(r['Dec'], hours=False):.5f}",
            "mag": "" if mag is None else f"{mag:.1f}",
            "size_arcmin": r["MajAx"],
            "minor_arcmin": r["MinAx"],
            "surf_br": r["SurfBr"],
            "hubble": r["Hubble"],
            "messier": messier or "",
        })

    out.sort(key=lambda t: (t["messier"] == "", t["messier"] or 0, t["id"]))
    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    kinds = {}
    for t in out:
        kinds[t["kind"]] = kinds.get(t["kind"], 0) + 1
    print(f"wrote {len(out)} targets to {OUT}", file=sys.stderr)
    print(kinds, file=sys.stderr)


if __name__ == "__main__":
    main()
