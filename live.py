#!/usr/bin/env python3
"""Settings a run already going reads each time it needs them, so they can be
changed in the middle of the night without stopping anything.

    ./live.py                                   each setting, and its value now
    ./live.py patrol.second_look_minutes 6      from the next second look on
    ./live.py patrol.second_looks no            none, for the rest of tonight's patrols
    ./live.py --clear patrol.second_look_minutes  back to the usual

A patrol or an imaging run lives for hours, and what it read at the start it
kept: on 19 and 20 October 2026 the second look's length could not be changed
for the patrol going. Kept in config.DATA/cache/live.json; cleared by hand.
"""
import argparse
import json

import config

FILE = config.DATA / "cache" / "live.json"

# Each: what it is, the usual value, and its kind.
KNOWN = {
    "patrol.second_looks": ("whether a patrol goes back for a second look at a field with an unexplained "
                            "candidate", True, bool),
    "patrol.second_look_minutes": ("minutes of frames in a second look", 10.0, float),
    "shoot.cloud_stop": ("rejected frames in a row that end a run with --frames 0", 20, int),
    "shoot.assist_every": ("accepted frames between trims of the tracking's Dec creep", 15, int),
}


def _read():
    try:
        found = json.loads(FILE.read_text(encoding="utf-8"))
        return found if isinstance(found, dict) else {}
    except (OSError, ValueError):
        return {}


def get(name, default=None):
    """The setting now: as set, else `default`, else the usual. Read from the
    file every time, so a change applies at the next use."""
    value = _read().get(name)
    if value is None:
        return default if default is not None else KNOWN[name][1]
    return value


def parse(name, text):
    if name not in KNOWN:
        raise ValueError(f"No live setting {name}. Known: {', '.join(KNOWN)}")
    kind = KNOWN[name][2]
    if kind is bool:
        if text.lower() in ("yes", "on", "true", "1"):
            return True
        if text.lower() in ("no", "off", "false", "0"):
            return False
        raise ValueError(f"{name} is yes or no, not {text}")
    return kind(text)


def set_(name, value):
    found = _read()
    found[name] = value
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(found, indent=1), encoding="utf-8")


def clear(name):
    found = _read()
    found.pop(name, None)
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(found, indent=1), encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("name", nargs="?")
    ap.add_argument("value", nargs="?")
    ap.add_argument("--clear", metavar="NAME")
    args = ap.parse_args(argv)
    try:
        if args.clear:
            parse(args.clear, str(KNOWN.get(args.clear, (None, ""))[1]))   # known, or refused
            clear(args.clear)
        elif args.name:
            if args.value is None:
                ap.error("give the value too")
            set_(args.name, parse(args.name, args.value))
    except ValueError as error:
        ap.exit(2, f"{error}\n")
    now = _read()
    for name, (what, usual, _) in KNOWN.items():
        value = now.get(name)
        print(f"{name:30} {usual if value is None else value!s:>6}" + ("" if value is None else " (set)")
              + f"   {what}")


if __name__ == "__main__":
    main()
