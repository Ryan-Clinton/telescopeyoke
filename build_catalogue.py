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

BASE = "https://raw.githubusercontent.com/mattiaverga/OpenNGC/master/database_files/"
FILES = ("NGC.csv", "addendum.csv")
OUT = Path(__file__).parent / "data" / "targets.csv"

# Faintest magnitude kept per object type, for things that are neither Messier
# objects nor named. Tuned for a 150mm aperture.
MAG_LIMIT = {
    "G": 10.5, "GPair": 10.5, "GTrpl": 10.5, "GGroup": 10.5,
    "OCl": 8.0, "*Ass": 8.0, "Cl+N": 9.0,
    "GCl": 9.5,
    "PN": 11.0,
    "Neb": 10.0, "HII": 10.0, "EmN": 10.0, "RfN": 10.0, "SNR": 10.0,
}
NAMED_MAG_LIMIT = 11.5
SKIP_TYPES = {"Dup", "NonEx", "*", "Nova"}

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
            keep = mag is not None and mag <= MAG_LIMIT.get(r["Type"], -99)
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
            "messier": messier or "",
        })

    out.sort(key=lambda t: (t["messier"] == "", t["messier"] or 0, t["id"]))
    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", newline="") as f:
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
