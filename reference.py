#!/usr/bin/env python3
"""The picture each field's new nights are compared with.

    ./reference.py M31                  what is kept for M31, and what could be
    ./reference.py M31 --make           keep the deepest measured M31 stack as its reference
    ./reference.py M31 --make --from frames/M31/20261013-232632
    ./reference.py --list

A reference is a stack whose depth.py measurement is kept beside it: the
deepest one is chosen, by where half the planted stars were found. It is
copied to reference/NAME/vN.fits with a record of where it came from, how
deep it reaches and how sharp its stars are, so a candidate found against it
can always say which reference it was. A new version never replaces an old
one: candidates found against v1 stay explained by v1.

difference.py uses the newest version when it is not told a reference. A
night is never its own reference: a session already used to make one is
refused as the new night.
"""
import argparse
import json
import shutil
import time
from pathlib import Path

import config
import depth
import interface
import stacking


def folder(name):
    return config.DATA / "reference" / stacking.folder_name(name)


def kept(name):
    """Every version kept for a field, oldest first, as their records."""
    out = []
    versions = [p for p in folder(name).glob("v*.json") if p.stem[1:].isdigit()]   # not v1-depth.json
    for path in sorted(versions, key=lambda p: int(p.stem[1:])):
        out.append(json.loads(path.read_text(encoding="utf-8")))
    return out


def newest(name):
    """The newest reference's FITS path, or None."""
    versions = kept(name)
    return Path(versions[-1]["file"]) if versions else None


def for_field(name):
    """(the reference to compare a field with, whose it is): the field's own
    newest, or for a mosaic panel with none yet (M31-P3) the whole object's,
    which difference.py uses where the two overlap. (None, None) if neither."""
    own = newest(name)
    if own is not None:
        return own, name
    whole = name.rsplit("-P", 1)[0] if "-P" in name else None
    if whole and newest(whole) is not None:
        return newest(whole), whole
    return None, None


def measured_stacks(name):
    """Every stack of a field whose depth has been measured with planted
    stars, deepest first."""
    out = []
    for record in sorted((config.DATA / "frames" / stacking.folder_name(name)).glob("*/*depth.json")):
        r = json.loads(record.read_text(encoding="utf-8"))
        half = r.get("completeness", {}).get("all", {}).get("mag_50")
        # The stack is beside its record; the path inside may be relative to
        # wherever depth.py was run.
        stack = record.parent / Path(r.get("stack", "final.fits")).name
        if half is None or not stack.is_file():
            continue
        out.append({"stack": str(stack), "mag_50": half, "fwhm_arcsec": r.get("fwhm_arcsec"),
                    "sky": r.get("sky_mag_per_arcsec2"), "zeropoint": r.get("zeropoint"),
                    "exposure_s": r.get("exposure_s"), "frames": r.get("frames"), "record": str(record)})
    return sorted(out, key=lambda r: -r["mag_50"])


def made_from(stack):
    """The sessions a stack was made from: its own folder, or for a stack of
    several sessions (frames/NAME/combined/) the ones its restack.json names."""
    log = stack.parent / "restack.json"
    if log.exists():
        named = json.loads(log.read_text(encoding="utf-8")).get("summary", {}).get("sessions")
        if named:
            return [str(Path(s) if Path(s).is_absolute() else config.DATA / s) for s in named]
    return [str(stack.parent)]


FIELD_REACH = 0.6    # degrees from a field's centre that its stack covers, about half the frame's diagonal


def contaminated(name, sessions):
    """Open candidates in the field that a reference made from these
    sessions could contain: first seen on or before the last of its nights
    and within the field. A reference with a real, lasting nova in it would
    subtract the nova away from every night after."""
    import candidates
    import mount
    import vet
    try:
        centre = mount.find_target(name)
    except interface.Refusal:
        return []
    last = max(Path(s).name for s in sessions)
    out = []
    for book_name in dict.fromkeys((name, name.rsplit("-P", 1)[0] if "-P" in name else name)):
        for k in candidates.load(book_name)["candidates"]:
            near = vet.separation(centre["ra"], centre["dec"], k["ra"], k["dec"]) <= FIELD_REACH * 3600
            if k["open"] and near and k["first"] <= last:
                out.append(k["id"])
    return out


def make(name, source=None, force=False):
    """Keep a stack as the field's next reference version."""
    candidates = measured_stacks(name)
    if source:
        stack = depth.find_stack(source)
        chosen = next((c for c in candidates if Path(c["stack"]).resolve() == stack.resolve()), None)
        if chosen is None:
            raise interface.Refusal("INVALID_REQUEST", f"{stack} has no depth measurement with planted stars: "
                                    f"run ./depth.py {stack} --plant first.")
    elif not candidates:
        raise interface.Refusal("NO_SESSION", f"No measured stack of {name}: run ./depth.py {name} --plant "
                                "on its best session first.")
    else:
        chosen = candidates[0]
    sessions = made_from(Path(chosen["stack"]))
    held = contaminated(name, sessions)
    if held and not force:
        raise interface.Refusal("INVALID_REQUEST", f"{chosen['stack']} could contain open candidates "
                                f"({', '.join(held)}); a reference must not hold what it is looking for. "
                                "Settle them first (candidates.py), choose another stack (--from), or --force.")
    versions = kept(name)
    number = len(versions) + 1
    where = folder(name)
    where.mkdir(parents=True, exist_ok=True)
    target = where / f"v{number}.fits"
    shutil.copyfile(chosen["stack"], target)
    record = dict(chosen, version=number, file=str(target), source=chosen["stack"],
                  sessions=sessions, made=time.time(), held_back=held)
    (where / f"v{number}.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    # Its depth goes with it, so difference.py finds the zero point.
    shutil.copyfile(chosen["record"], depth.record_path(target))
    return record


def sessions_used(name):
    """Every session folder a kept reference of this field was made from."""
    used = set()
    for v in kept(name):
        used.update(Path(s).resolve() for s in v.get("sessions", []))
    return used


def run(args, say=print):
    if args.list:
        root = config.DATA / "reference"
        fields = sorted(p.name for p in root.glob("*/") if kept(p.name)) if root.exists() else []
        answer = {"fields": [{"name": f, "versions": len(kept(f)), "newest": kept(f)[-1]} for f in fields]}
        for f in answer["fields"]:
            say(f"{f['name']}: v{f['versions']}, half found at G {f['newest']['mag_50']}, from {f['newest']['source']}")
        if not fields:
            say("No references kept yet: ./reference.py NAME --make")
        return answer
    if not args.name:
        raise interface.Refusal("INVALID_REQUEST", "Name a field, or use --list.")
    if args.make:
        record = make(args.name, args.source, args.force)
        say(f"{args.name} v{record['version']}: {record['source']}, half of planted stars found at "
            f"G {record['mag_50']}, stars {record['fwhm_arcsec']}\"; kept as {record['file']}")
        return {"name": args.name, "made": record, "versions": kept(args.name)}
    versions, candidates = kept(args.name), measured_stacks(args.name)
    for v in versions:
        say(f"v{v['version']}: G {v['mag_50']}, stars {v['fwhm_arcsec']}\", from {v['source']}")
    if not versions:
        say(f"No reference kept for {args.name}.")
    for c in candidates[:5]:
        say(f"  could be: G {c['mag_50']}, stars {c['fwhm_arcsec']}\", {c['stack']}")
    return {"name": args.name, "versions": versions, "measured": candidates}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("name", nargs="?", help="the field: an object or a mosaic panel (M31-P3)")
    ap.add_argument("--make", action="store_true", help="keep the deepest measured stack as the next version")
    ap.add_argument("--from", dest="source", help="with --make: this stack instead of the deepest")
    ap.add_argument("--force", action="store_true",
                    help="with --make: even if the stack could contain an open candidate")
    ap.add_argument("--list", action="store_true", help="every field with a reference")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("reference", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
