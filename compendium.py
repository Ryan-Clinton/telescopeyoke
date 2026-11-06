#!/usr/bin/env python3
"""Gary Imm's Deep Sky Compendium: download it, and keep its ratings and notes for the planner.

The Compendium (https://www.garyimm.com/compendium) is a free Excel workbook
of over 3,100 deep-sky objects, each with a rating from 0 to 5 and a note
written by an experienced imager. It is his work and is not ours to publish,
so it never goes in the repository: this fetches it from his own link onto
this computer, into cache/ (ignored by git), and reads it into a small table
there. sky.load_targets() uses that table when it exists, and the planner
works as it always has when it does not.

  ./compendium.py fetch          download the current edition and read it in
  ./compendium.py import FILE    read in a copy downloaded by hand
  ./compendium.py status         whether it is here, which edition, how much

The workbook carries Excel macros; nothing here runs them. Only the cells
are read, with the standard library.
"""
import argparse
import csv
import re
import shutil
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import config
import host  # noqa: F401  (makes printed output UTF-8 on Windows)
import interface

PAGE = "https://www.garyimm.com/compendium"
# The English workbook's Google Drive file, as linked from PAGE ("Compendium
# (xls) - English"; the 2026 6th edition, 36 MB, on 6 November 2026). When he
# publishes a new edition the link on his page changes: put its id= here.
DRIVE_ID = "1fCiBsMPofrbb39R0QoapKPyMxBsXvuWo"
# drive.google.com/uc answers a file this big with a "can't scan for
# viruses" page; this address with confirm=t gives the file itself.
URL = f"https://drive.usercontent.google.com/download?id={DRIVE_ID}&export=download&confirm=t"

WORKBOOK = config.DATA / "cache" / "compendium.xlsx"
TABLE = config.DATA / "cache" / "compendium.csv"

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RELS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

# His Type and Sub columns, as the planner's kinds. Anything not listed under
# "Neb" is a bright nebula; under "Gal", a galaxy.
NEBULA = {"PN": "planetary nebula", "PPN": "planetary nebula", "Dark": "dark nebula",
          "Mol Cld": "dark nebula"}
STARS = {"OC": "open cluster", "GC": "globular", "Star Cld": "open cluster", "YSO": "nebula",
         "HH": "nebula"}

# His objects that the catalogue lacks are added only this wide (arcminutes)
# or wider, the smallest build_catalogue.py keeps (MIN_SIZE): smaller is a
# smudge in the 150P's frame. A lensed quasar is in the Compendium too.
MIN_SIZE = {"galaxy": 1.5, "planetary nebula": 0.5}
SMALLEST = 1.0

FIELDS = ["id", "nickname", "alt_id", "kind", "type", "sub", "const", "ra_deg", "dec_deg",
          "mag", "size_arcmin", "surf_br", "rating", "note", "ngc", "ic", "messier", "edition"]


# --- reading the workbook --------------------------------------------------------

def _cells(book):
    """The main sheet's rows as {column letter: text}, with the shared
    strings filled in, and the workbook's title."""
    z = zipfile.ZipFile(book)
    names = {}
    for rel in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")):
        names[rel.get("Id")] = rel.get("Target")
    sheets = ET.fromstring(z.read("xl/workbook.xml")).find(f"{{{MAIN}}}sheets")
    first = next(iter(sheets))
    if first.get("name") != "Main":
        raise interface.Refusal("INVALID_REQUEST", f"{book} does not look like the Compendium: "
                                f"its first sheet is '{first.get('name')}', not 'Main'.")
    path = "xl/" + names[first.get(f"{{{RELS}}}id")].lstrip("/").removeprefix("xl/")
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for item in ET.fromstring(z.read("xl/sharedStrings.xml")):
            shared.append("".join(t.text or "" for t in item.iter(f"{{{MAIN}}}t")))
    rows = []
    for _, node in ET.iterparse(z.open(path)):
        if node.tag != f"{{{MAIN}}}row":
            continue
        row = {}
        for cell in node:
            value = cell.find(f"{{{MAIN}}}v")
            text = value.text if value is not None else None
            if cell.get("t") == "s" and text is not None:
                text = shared[int(text)]
            elif cell.get("t") == "inlineStr":
                text = "".join(t.text or "" for t in cell.iter(f"{{{MAIN}}}t"))
            if text is not None and text.strip():
                row[re.match(r"[A-Z]+", cell.get("r")).group()] = text.strip()
        rows.append(row)
        node.clear()
    return rows


def _columns(rows):
    """Where each wanted column is, found from his two header rows rather
    than fixed letters, so a new edition that moves a column still reads."""
    top = next((r for r in rows[:20] if r.get("A") == "Object Name & Image"), None)
    if top is None:
        raise interface.Refusal("INVALID_REQUEST", "No 'Object Name & Image' header row: "
                                "this edition of the Compendium is laid out differently.")
    below = rows[rows.index(top) + 1]
    by_top = {v: k for k, v in top.items()}
    want = {"type": "Type", "sub": "Sub", "size": "Size", "rating": "Rating", "note": "Notes",
            "const": "Const.", "nickname": "Nick.", "alt_id": "Alt. ID", "mag": "Visual",
            "surf_br": "Surf."}
    found = {key: by_top.get(head) for key, head in want.items()}
    # Each position is two columns, the sexagesimal one and then degrees
    # ("(Deg)" in the row below).
    for key, head in (("ra", "Right Ascension"), ("dec", "Declination")):
        start = by_top.get(head)
        deg = next((c for c, v in below.items() if v == "(Deg)" and _after(c, start)), None)
        found[key] = deg
    # The cross-references are labelled in the second row ("Abell" is there
    # twice, galaxy clusters and planetary nebulae: not used here).
    for key, head in (("ngc", "NGC"), ("ic", "IC"), ("messier", "Messier")):
        found[key] = next((c for c, v in below.items() if v == head), None)
    missing = [k for k, v in found.items() if v is None and k not in ("surf_br", "nickname", "alt_id")]
    if missing:
        raise interface.Refusal("INVALID_REQUEST", f"The Compendium's columns have changed: no {', '.join(missing)}.")
    return found, rows.index(top) + 2


def _after(col, start):
    """Whether spreadsheet column col comes after start (both letters)."""
    if start is None:
        return False
    value = lambda c: sum((ord(ch) - 64) * 26 ** i for i, ch in enumerate(reversed(c)))
    return value(col) > value(start) and value(col) - value(start) <= 2


def _number(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _ident(name):
    """His names as ours: "M 001" -> "M1", "NGC 0224" -> "NGC 224",
    "Barnard 007" -> "Barnard 7"."""
    m = re.fullmatch(r"(M|NGC|IC)\s*0*(\d+)(.*)", name)
    if m:
        number = f"{m.group(2)}{m.group(3).strip()}"
        return f"M{number}" if m.group(1) == "M" else f"{m.group(1)} {number}"
    # "Barnard 007", "Sh2-001": numbers without his padding, so they are
    # typed as people write them.
    return re.sub(r"(?<![\d.])0+(?=\d)", "", re.sub(r"\s+", " ", name))


def _kind(kind, sub):
    kind, sub = kind.strip(), (sub or "").strip()
    if kind == "Gal":
        return "galaxy"
    if kind == "Neb":
        return NEBULA.get(sub, "nebula")
    return STARS.get(sub, "open cluster")


def read(book):
    """The Compendium's objects, one dict per row of the main sheet."""
    rows = _cells(book)
    title = rows[0].get("A", "") if rows else ""
    edition = title.split("-", 1)[-1].strip() if "Compendium" in title else ""
    col, first = _columns(rows)
    out = []
    for row in rows[first:]:
        name = row.get("A")
        kind, ra, dec = row.get(col["type"]), _number(row.get(col["ra"])), _number(row.get(col["dec"]))
        if not name or not kind or ra is None or dec is None:
            continue    # the key, units and totals rows
        rating = _number(row.get(col["rating"]))
        cross = {k: "" if _number(row.get(col[k])) is None else str(int(_number(row.get(col[k]))))
                 for k in ("ngc", "ic", "messier")}
        mag, size = _number(row.get(col["mag"])), _number(row.get(col["size"]))
        surf = _number(row.get(col["surf_br"])) if col["surf_br"] else None
        out.append({
            "id": _ident(name), "nickname": (row.get(col["nickname"]) or "").split(",")[0].strip(),
            "alt_id": _ident(row.get(col["alt_id"]) or ""),
            "kind": _kind(kind, row.get(col["sub"])), "type": kind.strip(),
            "sub": (row.get(col["sub"]) or "").strip(), "const": row.get(col["const"], ""),
            "ra_deg": f"{ra:.5f}", "dec_deg": f"{dec:.5f}",
            "mag": "" if mag is None else f"{mag:g}", "size_arcmin": "" if size is None else f"{size:g}",
            "surf_br": "" if surf is None else f"{surf:.2f}",
            "rating": "" if rating is None else str(int(rating)),
            "note": " ".join((row.get(col["note"]) or "").split()),
            **cross, "edition": edition,
        })
    if len(out) < 1000:
        raise interface.Refusal("INVALID_REQUEST", f"Only {len(out)} objects read from {book}: "
                                "not the Compendium as it was known.")
    return out


# --- keeping it --------------------------------------------------------------------

def keep(book):
    """Read the workbook and write the table the planner uses."""
    objects = read(book)
    TABLE.parent.mkdir(parents=True, exist_ok=True)
    part = TABLE.with_suffix(".csv.part")
    with part.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(objects)
    part.replace(TABLE)
    return status()


def fetch():
    """Download the workbook from his link, then read it in."""
    WORKBOOK.parent.mkdir(parents=True, exist_ok=True)
    part = WORKBOOK.with_suffix(".xlsx.part")
    request = urllib.request.Request(URL, headers={"User-Agent": "telescopeyoke (personal observing planner)"})
    print(f"Downloading the Compendium (about 36 MB) from {PAGE} ...", file=sys.stderr)
    with urllib.request.urlopen(request, timeout=120) as r, part.open("wb") as f:
        shutil.copyfileobj(r, f)
    if not zipfile.is_zipfile(part):
        part.unlink()
        raise interface.Refusal("INVALID_REQUEST", "The link gave a web page, not the workbook: "
                                f"he may have published a new edition. Open {PAGE}, download the "
                                "English workbook by hand, and run ./compendium.py import FILE "
                                "(and put the new id= in compendium.DRIVE_ID).")
    part.replace(WORKBOOK)
    return keep(WORKBOOK)


def load():
    """The kept table, or [] when the Compendium has not been fetched."""
    if not TABLE.exists():
        return []
    with TABLE.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _keys(t):
    """The names one target is known by, spaces removed."""
    names = {t.get("id", ""), t.get("alt_id", "")}
    if t.get("messier") and str(t["messier"]).isdigit():
        names.add(f"M{t['messier']}")
    return {n.replace(" ", "").upper() for n in names if n}


def merge(targets):
    """Add his rating and note to the targets the catalogue has, and his
    other objects as targets of their own. A target is the same object when
    any of its NGC, IC or Messier names match."""
    rows = load()
    if not rows:
        return targets
    index = {}
    for t in targets:
        for k in _keys(t):
            index.setdefault(k, t)
    for r in rows:
        names = {n.replace(" ", "").upper() for n in (r["id"], r["alt_id"]) if n}
        names |= {f"{p}{r[k]}" for p, k in (("NGC", "ngc"), ("IC", "ic"), ("M", "messier")) if r[k]}
        mine = next((index[n] for n in names if n in index), None)
        rating = int(r["rating"]) if r["rating"] else None
        if mine is not None:
            if mine.get("rating") is None:    # the first of his rows for it wins
                mine.update(rating=rating, note=r["note"], imm=r["id"])
            continue
        size = _number(r["size_arcmin"])
        if size is None or size < MIN_SIZE.get(r["kind"], SMALLEST):
            continue
        target = {"id": r["id"], "alt_id": r["alt_id"],
                  "name": "" if r["nickname"] == r["id"] else r["nickname"], "kind": r["kind"],
                  "const": r["const"], "ra": float(r["ra_deg"]), "dec": float(r["dec_deg"]),
                  "mag": _number(r["mag"]), "size": size, "minor": None, "messier": False,
                  "hubble": None, "surf_br": _number(r["surf_br"]),
                  "rating": rating, "note": r["note"], "imm": r["id"]}
        targets.append(target)
        for k in _keys(target):
            index.setdefault(k, target)
    return targets


def status():
    rows = load()
    if not rows:
        return {"present": False, "page": PAGE, "table": str(TABLE)}
    ratings = {}
    for r in rows:
        ratings[r["rating"] or "none"] = ratings.get(r["rating"] or "none", 0) + 1
    return {"present": True, "edition": rows[0]["edition"], "objects": len(rows),
            "ratings": dict(sorted(ratings.items())), "table": str(TABLE),
            "workbook": str(WORKBOOK) if WORKBOOK.exists() else None, "page": PAGE}


def say(s):
    if not s["present"]:
        print(f"Not downloaded. ./compendium.py fetch gets it from {s['page']}.")
        return
    print(f"Imm Deep Sky Compendium, {s['edition']}: {s['objects']} objects, kept in {s['table']}.")
    print("Ratings (0 low to 5 high): " + ", ".join(f"{k}: {v}" for k, v in s["ratings"].items()))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", choices=("fetch", "import", "status"))
    ap.add_argument("file", nargs="?", help="with import: the workbook downloaded by hand")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if args.action == "import" and not args.file:
        ap.error("import needs the workbook: ./compendium.py import FILE")

    def work():
        if args.action == "fetch":
            s = fetch()
        elif args.action == "import":
            s = keep(Path(args.file))
        else:
            s = status()
        if not args.json:
            say(s)
        return s

    return interface.main("compendium", work, args.json)


if __name__ == "__main__":
    main()
