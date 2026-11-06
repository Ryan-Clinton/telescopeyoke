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
# It cannot be read from the page by a script: the page is built in the
# browser by a site builder, and its HTML holds no links.
DRIVE_ID = "1fCiBsMPofrbb39R0QoapKPyMxBsXvuWo"
# drive.google.com/uc answers a file this big with a "can't scan for
# viruses" page; this address with confirm=t gives the file itself.
LINK_CHECKED = "6 November 2026"
URL = f"https://drive.usercontent.google.com/download?id={DRIVE_ID}&export=download&confirm=t"

WORKBOOK = config.DATA / "cache" / "compendium.xlsx"
TABLE = config.DATA / "cache" / "compendium.csv"
REPORT = config.DATA / "cache" / "compendium-import.json"   # what the last import took and left out

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

FIELDS = ["id", "nickname", "alt_id", "kind", "type", "sub", "class", "const", "ra_deg", "dec_deg",
          "mag", "size_arcmin", "surf_br", "rating", "note", "palette", "light", "aliases",
          "ngc", "ic", "messier", "edition"]


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


# His cross-reference columns (labelled in the second header row), and the
# name each gives an object. "Abell" is there twice, galaxy clusters and
# planetary nebulae, with numbers that overlap: neither is used, his own
# names ("Abell 1", "AbellG 2151") stand for them. Griffiths, Kohoutek,
# Minkowski, the SNR catalogue and O'Meara's lists are left out as well:
# their numbers are not how anyone types them.
CROSS = (("ngc", "NGC", "NGC "), ("ic", "IC", "IC "), ("messier", "Messier", "M"),
         ("caldwell", "Caldwell", "C"), ("arp", "Arp", "Arp "), ("hickson", "Hickson", "HCG "),
         ("ugc", "UGC", "UGC "), ("pgc", "PGC", "PGC "), ("barnard", "Barn.", "B "),
         ("gum", "Gum", "Gum "), ("lbn", "LBN", "LBN "), ("ldn", "LDN", "LDN "),
         ("rcw", "RCW", "RCW "), ("sh2", "Sh2", "Sh2-"), ("vdb", "vdB", "vdB "))


def _columns(rows):
    """Where each wanted column is, found from his two header rows rather
    than fixed letters, so a new edition that moves a column still reads."""
    top = next((r for r in rows[:20] if r.get("A") == "Object Name & Image"), None)
    if top is None:
        raise interface.Refusal("INVALID_REQUEST", "No 'Object Name & Image' header row: "
                                "this edition of the Compendium is laid out differently.")
    below = rows[rows.index(top) + 1]
    by_top = {v: k for k, v in top.items()}
    want = {"type": "Type", "sub": "Sub", "class": "Class", "size": "Size", "rating": "Rating",
            "note": "Notes", "const": "Const.", "nickname": "Nick.", "alt_id": "Alt. ID",
            "mag": "Visual", "surf_br": "Surf."}
    found = {key: by_top.get(head) for key, head in want.items()}
    # Each position is two columns, the sexagesimal one and then degrees
    # ("(Deg)" in the row below).
    for key, head in (("ra", "Right Ascension"), ("dec", "Declination")):
        start = by_top.get(head)
        deg = next((c for c, v in below.items() if v == "(Deg)" and _after(c, start)), None)
        found[key] = deg
    for key, head, _ in CROSS:
        found[key] = next((c for c, v in below.items() if v == head), None)
    optional = {"surf_br", "nickname", "alt_id", "class"} | {k for k, _, _ in CROSS[3:]}
    missing = [k for k, v in found.items() if v is None and k not in optional]
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


# The palettes he gives for each kind of nebula ("Typical these nebulae are
# imaged with the following channel palettes", in the workbook's own help),
# as the wheel's filters (slots 1 L 2 R 3 G 4 B 5 Ha 6 SII 7 OIII). He gives
# none for galaxies, clusters, Stromgren spheres or the rest: nor does this.
PALETTES = {"SHO": ("SII", "Ha", "OIII"), "HOO": ("Ha", "OIII"),
            "Ha+RGB": ("Ha", "R", "G", "B"), "LRGB": ("L", "R", "G", "B")}
# A planetary nebula's class is shape, signal, progenitor ("BRN/c"); the signal letter.
PN_SIGNAL = {"O": "OIII strongest", "H": "Ha strongest", "C": "Ha and OIII comparable",
             "R": "Ha rim, OIII inside"}


def palette(sub, cls):
    """His palette for an object, (name, what his class says of its light),
    or ("", "") when he gives none."""
    sub, cls = (sub or "").strip(), (cls or "").strip()
    if sub == "Em":
        if cls.startswith("SHO"):
            m = re.fullmatch(r"SHO-([\d.]+)/([\d.]+)/([\d.]+)", cls)
            light = f"SII {m[1]}, Ha {m[2]}, OIII {m[3]} (strongest 1)" if m else "SII, Ha and OIII all 10% or more"
            return "SHO", light
        if cls.startswith("HII"):
            return "Ha+RGB", "Ha dominant: SII and OIII under 10% of it"
        if cls.startswith("WR"):
            return "HOO", "Wolf-Rayet nebula"
        return "", ""
    if sub == "SNR":
        return "HOO", "supernova remnant"
    if sub in ("PN", "PPN"):
        return "HOO", PN_SIGNAL.get(cls[1:2], "") if len(cls) >= 2 else ""
    if sub in ("Refl", "Dark", "Mol Cld", "Mol CLd"):
        return "LRGB", ""
    return "", ""


def _cross(text):
    """A cross-reference cell as its number: 189.0 -> "189"; a blank or a
    space (his empty cells) as ""."""
    n = _number(text)
    if n is not None:
        return str(int(n)) if n == int(n) else f"{n:g}"
    return (text or "").strip()


def read(book):
    """The Compendium's objects, one dict per row of the main sheet."""
    rows = _cells(book)
    title = rows[0].get("A", "") if rows else ""
    edition = title.split("-", 1)[-1].strip() if "Compendium" in title else ""
    col, first = _columns(rows)
    out, skipped, seen = [], [], set()
    candidates = 0
    for row in rows[first:]:
        name = row.get("A")
        kind, ra, dec = row.get(col["type"]), _number(row.get(col["ra"])), _number(row.get(col["dec"]))
        # An object's row has its name and something of its own; the units
        # and totals rows under the headers have no name in A.
        if not name or not (kind or row.get(col["ra"]) or row.get(col["dec"])):
            continue
        candidates += 1
        if not kind or ra is None or dec is None:
            missing = [w for w, v in (("type", kind), ("RA", ra), ("Dec", dec)) if not v and v != 0]
            skipped.append((_ident(name), f"no {' or '.join(missing)}"))
            continue
        rating = _number(row.get(col["rating"]))
        mag, size = _number(row.get(col["mag"])), _number(row.get(col["size"]))
        surf = _number(row.get(col["surf_br"])) if col["surf_br"] else None
        ident = _ident(name)
        # Checked before anything uses it: a position the mount may be sent
        # to, a rating that weighs in the ranking.
        wrong = []
        if not 0 <= ra < 360:
            wrong.append(f"RA {ra}")
        if not -90 <= dec <= 90:
            wrong.append(f"Dec {dec}")
        if rating is not None and (rating != int(rating) or not 0 <= rating <= 5):
            wrong.append(f"rating {rating}")
        if size is not None and not 0 < size <= 3000:
            wrong.append(f"size {size}'")
        if ident in seen:
            wrong.append("a second row of that name")
        if wrong:
            skipped.append((ident, ", ".join(wrong)))
            continue
        seen.add(ident)
        cross = {key: _cross(row.get(col[key])) if col[key] else "" for key, _, _ in CROSS}
        aliases = [f"{prefix}{cross[key]}" for key, _, prefix in CROSS if cross[key]]
        if cross["barnard"]:
            aliases.append(f"Barnard {cross['barnard']}")
        aliases = [a for a in dict.fromkeys(aliases) if a.replace(" ", "") != ident.replace(" ", "")]
        cls = (row.get(col["class"]) or "").strip() if col["class"] else ""
        sub = (row.get(col["sub"]) or "").strip()
        scheme, light = palette(sub, cls)
        out.append({
            "id": ident, "nickname": (row.get(col["nickname"]) or "").split(",")[0].strip(),
            "alt_id": _ident(row.get(col["alt_id"]) or ""),
            "kind": _kind(kind, sub), "type": kind.strip(), "sub": sub, "class": cls,
            "const": row.get(col["const"], ""),
            "ra_deg": f"{ra:.5f}", "dec_deg": f"{dec:.5f}",
            "mag": "" if mag is None else f"{mag:g}", "size_arcmin": "" if size is None else f"{size:g}",
            "surf_br": "" if surf is None else f"{surf:.2f}",
            "rating": "" if rating is None else str(int(rating)),
            "note": " ".join((row.get(col["note"]) or "").split()),
            "palette": scheme, "light": light, "aliases": ";".join(aliases),
            "ngc": cross["ngc"], "ic": cross["ic"], "messier": cross["messier"], "edition": edition,
        })
    if len(out) < 1000:
        raise interface.Refusal("INVALID_REQUEST", f"Only {len(out)} objects read from {book}: "
                                "not the Compendium as it was known.")
    if len(skipped) > 0.02 * candidates:
        raise interface.Refusal("INVALID_REQUEST", f"{len(skipped)} of {candidates} rows fail the checks "
                                f"(first: {skipped[0][0]}: {skipped[0][1]}): the workbook's columns may mean "
                                "something else now.")
    # The whole sky, both hemispheres: RA in hours instead of degrees, or a
    # column moved, shows here first.
    ras, decs = [float(o["ra_deg"]) for o in out], [float(o["dec_deg"]) for o in out]
    if max(ras) - min(ras) < 300 or min(decs) > -45 or max(decs) < 60:
        raise interface.Refusal("INVALID_REQUEST", f"The positions span RA {min(ras):.0f}-{max(ras):.0f}°, "
                                f"Dec {min(decs):.0f} to {max(decs):.0f}°: not the whole sky, so the columns "
                                "are not read as they were meant.")
    reasons = {}
    for _, why in skipped:
        reason = re.sub(r"[-\d.]+'?$", "", why).strip() if not why.startswith("no ") else why
        reasons[reason] = reasons.get(reason, 0) + 1
    report = {"edition": edition, "candidate_rows": candidates, "accepted": len(out),
              "rejected": len(skipped), "reasons": reasons,
              "rejected_rows": [{"id": i, "why": w} for i, w in skipped]}
    for i, w in skipped:
        print(f"left out {i}: {w}", file=sys.stderr)
    return out, report


# --- keeping it --------------------------------------------------------------------

def keep(book):
    """Read the workbook and write the table the planner uses."""
    objects, report = read(book)
    TABLE.parent.mkdir(parents=True, exist_ok=True)
    import records
    records.write(REPORT, dict(report, workbook=str(book), fields=FIELDS), schema="compendium-import")
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
    before = (load() or [{}])[0].get("edition")
    s = keep(WORKBOOK)
    s["edition_before"] = before
    if before and before != s["edition"]:
        print(f"A new edition: {before} before, {s['edition']} now.", file=sys.stderr)
    elif before:
        print(f"The same edition as before ({before}): the link still gives it. A newer one on "
              f"{PAGE} needs its new link in compendium.DRIVE_ID.", file=sys.stderr)
    return s


_told = []     # said once per process that an old table is not used


def load():
    """The kept table, or [] when the Compendium has not been fetched. A
    table kept by an older version of this (other columns) is read again
    from the kept workbook, or, with none, left unused with a message: the
    planner never fails for want of it."""
    if not TABLE.exists():
        return []
    with TABLE.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames == FIELDS:
            return list(reader)
    if WORKBOOK.exists():
        print("The Compendium's kept table is from an older version: reading the workbook again.",
              file=sys.stderr)
        try:
            keep(WORKBOOK)
        except (interface.Refusal, OSError, zipfile.BadZipFile) as problem:
            print(f"Could not: {problem}. The planner goes on without it.", file=sys.stderr)
            return []
        with TABLE.open(encoding="utf-8") as f:
            return list(csv.DictReader(f))
    if not _told:
        print("The Compendium's kept table is from an older version and there is no workbook to read "
              "again: ./compendium.py fetch. The planner goes on without it.", file=sys.stderr)
        _told.append(True)
    return []


def _key(name):
    return name.replace(" ", "").upper()


def _keys(t):
    """The names one target is known by, spaces removed."""
    names = [t.get("id", ""), t.get("alt_id", ""), *t.get("aliases", ())]
    if t.get("messier") and str(t["messier"]).isdigit():
        names.append(f"M{t['messier']}")
    return [_key(n) for n in names if n]


def _names(r):
    """His row's names, in the order they decide a match: its own name, its
    alternative, then Messier, NGC and IC."""
    names = [r["id"], r["alt_id"]] + [f"{p}{r[k]}" for p, k in (("M", "messier"), ("NGC ", "ngc"), ("IC ", "ic")) if r[k]]
    return [_key(n) for n in dict.fromkeys(names) if n]


def _his(r):
    """What he says of an object, attributed: added to a target."""
    scheme = r.get("palette", "")
    return {"rating": int(r["rating"]) if r["rating"] else None, "note": r["note"], "imm": r["id"],
            "sub": r["sub"],
            "palette": {"name": scheme, "filters": list(PALETTES[scheme]), "light": r.get("light", ""),
                        "source": "Gary Imm's Deep Sky Compendium"} if scheme else None}


# What the last merge did, for status(): how many matched, were added, and
# which of his rows named more than one target.
last = {}


def merge(targets):
    """Add what he says to the targets the catalogue has, and his other
    objects as targets of their own. A row is the catalogue's target when one
    of its names is: its own name first, then its alternative, Messier, NGC
    and IC, the first that matches deciding. A target two of his rows match
    takes the one whose own name it is, else the first."""
    rows = load()
    last.clear()
    if not rows:
        return targets
    index = {}
    for t in targets:
        for k in _keys(t):
            index.setdefault(k, t)
    ambiguous, clashes, matched, added = [], 0, set(), 0
    rows_for = {}
    for r in rows:
        names = _names(r)
        hits = list(dict.fromkeys(index[n]["id"] for n in names if n in index))
        if len(hits) > 1:
            # Only what he says is added to a target (its rating, note, names);
            # its position stays the catalogue's, so no match moves where the
            # telescope points. A row naming two targets, neither by its own
            # name, could be either: it adds to neither.
            if _key(r["id"]) not in {_key(h) for h in hits}:
                ambiguous.append(f"{r['id']}: {', '.join(hits)} (left to neither)")
                continue
            ambiguous.append(f"{r['id']}: {', '.join(hits)} (its own name, {r['id']})")
        if hits:
            rows_for.setdefault(hits[0], []).append(r)
        else:
            rows_for.setdefault(None, []).append(r)
    by_id = {t["id"]: t for t in targets}
    for tid, rs in rows_for.items():
        if tid is None:
            continue
        t = by_id.get(tid) or next(x for x in targets if x["id"] == tid)
        own = [r for r in rs if _key(r["id"]) in _keys(t)]
        best = (own or rs)[0]
        t.update(_his(best))
        matched.add(tid)
        # Every row that matched it lends its names: "C49" finds the Rosette.
        t["aliases"] = list(t.get("aliases", []))
        for r in rs:
            for a in [r["id"]] + [a for a in r.get("aliases", "").split(";") if a]:
                k = _key(a)
                if index.get(k, t) is not t:
                    clashes += 1
                    continue
                if k not in _keys(t):
                    t["aliases"].append(a)
                index[k] = t
    for r in rows_for.get(None, []):
        size = _number(r["size_arcmin"])
        if size is None or size < MIN_SIZE.get(r["kind"], SMALLEST):
            continue
        aliases = []
        for a in [a for a in r.get("aliases", "").split(";") if a]:
            if _key(a) in index:
                clashes += 1
            else:
                aliases.append(a)
        target = {"id": r["id"], "alt_id": r["alt_id"],
                  "name": "" if r["nickname"] == r["id"] else r["nickname"], "kind": r["kind"],
                  "const": r["const"], "ra": float(r["ra_deg"]), "dec": float(r["dec_deg"]),
                  "mag": _number(r["mag"]), "size": size, "minor": None, "messier": False,
                  "hubble": None, "surf_br": _number(r["surf_br"]), "aliases": aliases, **_his(r)}
        targets.append(target)
        added += 1
        for k in _keys(target):
            index.setdefault(k, target)
    last.update(matched=len(matched), added=added, ambiguous=ambiguous, alias_clashes=clashes)
    return targets


def _report():
    import records
    kept = records.read(REPORT, None) if REPORT.exists() else None
    return kept and {k: kept[k] for k in ("edition", "candidate_rows", "accepted", "rejected", "reasons")}


def status():
    rows = load()
    if not rows:
        return {"present": False, "page": PAGE, "table": str(TABLE)}
    ratings = {}
    for r in rows:
        ratings[r["rating"] or "none"] = ratings.get(r["rating"] or "none", 0) + 1
    import compendium       # the module sky imports, also when this runs as a script
    import sky
    sky.load_targets()      # fills compendium.last
    last = compendium.last
    return {"present": True, "edition": rows[0]["edition"], "objects": len(rows),
            "ratings": dict(sorted(ratings.items())), "table": str(TABLE),
            "matched": last.get("matched", 0), "added": last.get("added", 0),
            "ambiguous": last.get("ambiguous", []), "alias_clashes": last.get("alias_clashes", 0),
            "link": URL, "link_checked": LINK_CHECKED,
            "import": _report(),
            "workbook": str(WORKBOOK) if WORKBOOK.exists() else None, "page": PAGE}


def say(s):
    if not s["present"]:
        print(f"Not downloaded. ./compendium.py fetch gets it from {s['page']}.")
        return
    print(f"Imm Deep Sky Compendium, {s['edition']}: {s['objects']} objects, kept in {s['table']}.")
    print("Ratings (0 low to 5 high): " + ", ".join(f"{k}: {v}" for k, v in s["ratings"].items()))
    if s.get("import"):
        i = s["import"]
        print(f"Last import: {i['candidate_rows']} object rows, {i['accepted']} taken, {i['rejected']} left out"
              + (" (" + ", ".join(f"{k}: {v}" for k, v in i["reasons"].items()) + ")" if i["reasons"] else "")
              + f"; the rows left out are in {REPORT}.")
    print(f"{s['matched']} matched to the catalogue's targets, {s['added']} added as targets of their own.")
    for line in s["ambiguous"]:
        print(f"  named more than one target: {line}")
    if s["alias_clashes"]:
        print(f"  {s['alias_clashes']} of his other names already name another target: left to that one.")
    print(f"The download link was taken from {s['page']} on {s['link_checked']}; a newer edition "
          "there has a new link, which this does not see until compendium.DRIVE_ID is changed.")


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
