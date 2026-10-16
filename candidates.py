#!/usr/bin/env python3
"""Every candidate a field has had, as objects followed from night to night.

    ./candidates.py M31                  the open ones, with each night's measurement
    ./candidates.py M31 --all            closed ones too
    ./candidates.py M31 --json

A detection is not an object. Each night's candidates (vet.py's verdicts)
are joined to those already on file at the same place, within 5″, so one
object gathers its nights. patrol.py adds each night's, and measures every
open candidate in the new stack whether or not it was found again
(forced.py), so its history has the nights it was missing too, as limits.

A candidate stays open while it is unexplained. It is closed when a check
explains it (a known asteroid or variable, already reported), or after
CLOSE_AFTER nights in a row without being seen at a depth that should have
shown it. One seen on two or more nights is the one to look at hard.
Kept as candidates/NAME.json. Nothing here moves the mount or uses the camera.
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np

import config
import interface
import stacking

JOIN = 5.0         # arcsec: a detection this close to a candidate on file is the same object
CLOSE_AFTER = 3    # nights in a row unseen, each deep enough to have shown it, and it is closed


def path(name):
    return config.DATA / "candidates" / f"{stacking.folder_name(name)}.json"


def load(name):
    p = path(name)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"name": name, "candidates": []}


def save(book):
    p = path(book["name"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(book, indent=1), encoding="utf-8")


def arcsec(a, b):
    """Arcseconds between two (ra, dec) in degrees, near enough for 5″."""
    dra = (a[0] - b[0]) * np.cos(np.radians((a[1] + b[1]) / 2))
    return float(np.hypot(dra, a[1] - b[1]) * 3600)


def explained(verdict):
    return verdict.startswith(("known asteroid", "already reported", "known variable"))


def add_night(book, night, vetted):
    """Join one night's vetted candidates to the book: each to the open
    candidate it lies on, or as a new one. Returns the ids touched."""
    touched = []
    for c in vetted:
        if c.get("ra") is None or c["verdict"].startswith("not in both halves"):
            continue    # an artefact of one night is not an object
        where = (c["ra"], c["dec"])
        match = next((k for k in book["candidates"] if k["open"] and arcsec(where, (k["ra"], k["dec"])) <= JOIN), None)
        seen = {"night": night, "seen": True, "score": c["score"], "mag": c.get("mag"),
                "verdict": c["verdict"], "kind": "measured"}
        if match is None:
            match = {"id": f"{book['name']}-{night}-{len(book['candidates']) + 1:03d}", "ra": c["ra"],
                     "dec": c["dec"], "first": night, "open": True, "nights": []}
            book["candidates"].append(match)
        match["nights"].append(seen)
        if explained(c["verdict"]):
            match["open"], match["closed_because"] = False, c["verdict"]
        touched.append(match["id"])
    return touched


def follow_up(book, night, measure, depth_here):
    """Measure every open candidate not found tonight at its place in
    tonight's stack: `measure(ra, dec)` gives (mag, error, limit). A night
    where it is fainter than tonight's depth counts towards closing it."""
    for k in book["candidates"]:
        if not k["open"] or any(n["night"] == night for n in k["nights"]):
            continue
        mag, err, limit = measure(k["ra"], k["dec"])
        k["nights"].append({"night": night, "seen": mag is not None, "mag": mag, "error": err, "limit": limit,
                            "kind": "measured", "forced": True})
        misses = 0
        for n in reversed(k["nights"]):
            if n["seen"]:
                break
            if n.get("limit") is not None and (k_peak(k) is None or n["limit"] >= k_peak(k)):
                misses += 1
        if misses >= CLOSE_AFTER:
            k["open"], k["closed_because"] = False, f"not seen on {misses} nights deep enough to show it"


def k_peak(k):
    """The brightest a candidate has been seen."""
    seen = [n["mag"] for n in k["nights"] if n["seen"] and n.get("mag") is not None]
    return min(seen) if seen else None


def nights_seen(k):
    return sum(1 for n in k["nights"] if n["seen"])


def run(args, say=print):
    book = load(args.name)
    shown = [k for k in book["candidates"] if args.all or k["open"]]
    if not shown:
        say(f"No {'' if args.all else 'open '}candidates for {args.name}.")
    for k in shown:
        state = "open" if k["open"] else f"closed: {k.get('closed_because')}"
        say(f"{k['id']}  RA {k['ra']:.5f} Dec {k['dec']:+.5f}  seen on {nights_seen(k)} of {len(k['nights'])} "
            f"nights  ({state})")
        for n in k["nights"]:
            what = (f"G {n['mag']}" if n["seen"] and n.get("mag") is not None else
                    "seen" if n["seen"] else f"not seen, fainter than G {n.get('limit')}")
            say(f"    {n['night']}: {what}")
    return {"name": args.name, "candidates": shown}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("name", help="the field: an object or a mosaic panel")
    ap.add_argument("--all", action="store_true", help="closed candidates too")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("candidates", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
