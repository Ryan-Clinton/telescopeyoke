#!/usr/bin/env python3
"""The camera profiles and light paths (trains), and the one-time move of the
183C's own files under 183c/.

    ./cameras.py                    each camera profile and train, and which is in use and why
    ./cameras.py move-183c          what the move would do; nothing is moved
    ./cameras.py move-183c --go     move them, once

A profile is a [cameras.NAME] table in config.toml (the old single [camera]
table is the 183c's), a train a [trains.NAME] table (docs/mono-upgrade.md,
item 0). Each camera keeps its darks and flats, focus readings, readout and
lost-frame records, patrol references and zero points under its own name in
the data folder, so a night with one never spoils the other's records. The
183C's are still where they always were (calibration/, reference/ and some
of cache/) until move-183c --go moves them under 183c/; until then
everything finds them there, as before. Run the move in daylight with
nothing running. Nothing here uses the camera or moves the mount.
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

import config

# What is kept per camera, relative to the data folder: the 183C's, moved by move-183c.
PER_CAMERA = ("calibration", "reference", "cache/focus.json", "cache/focus_runs.jsonl",
              "cache/camera_timing.json", "cache/camera-fault.jsonl", "cache/camera-probes")
STAGING = ".183c-moving"


def describe(cfg=None):
    """The profiles, the trains and the camera in use, as data."""
    cfg = cfg or config.hardware()
    return {"in_use": config.camera_name(cfg), "chosen_by": cfg["camera"].get("chosen_by"),
            "train": cfg["train"]["name"], "focal_length_mm": round(config.focal_length(cfg), 1),
            "folder": str(config.camera_folder(cfg=cfg)),
            "cameras": {n: {k: p.get(k) for k in ("model", "serial", "mono", "cooled", "backend", "train")}
                        for n, p in cfg["cameras"].items()},
            "trains": {n: {k: t.get(k) for k in ("camera", "corrector", "filterwheel", "setup")}
                       for n, t in cfg["trains"].items()}}


def _repointed(value, old, new):
    """A record's value with paths under `old` made to point under `new`."""
    if isinstance(value, str) and (value == str(old) or value.startswith(str(old) + "/")):
        return str(new) + value[len(str(old)):]
    if isinstance(value, list):
        return [_repointed(v, old, new) for v in value]
    if isinstance(value, dict):
        return {k: _repointed(v, old, new) for k, v in value.items()}
    return value


def move_183c(data=None, go=False, say=print):
    """Move the 183C's own files from the data folder into data/183c/, once.
    Without `go`, only says what would move. The references' records name
    their files by full path, so those paths are changed to match. Returns
    the list of what moved (or would). Refuses when it has been done."""
    data = Path(data or config.DATA)
    target, staging = data / config.LEGACY_CAMERA, data / STAGING
    if target.exists():
        raise SystemExit(f"Already done: {target} exists.")
    if staging.exists():
        raise SystemExit(f"{staging} is left from a move that did not finish: look inside, put its "
                         "contents back where they came from, remove it and run this again.")
    found = [part for part in PER_CAMERA if (data / part).exists()]
    for part in found:
        say(f"{'moving' if go else 'would move'} {part} -> {config.LEGACY_CAMERA}/{part}")
    if not found:
        say("Nothing of the 183C's to move.")
    if not go:
        return found
    # Everything goes into a folder of another name first and that folder
    # takes the camera's name last, so a move cut off half way never leaves
    # a 183c/ that the scripts would take as the whole of it.
    staging.mkdir()
    for part in found:
        (staging / part).parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(data / part), str(staging / part))
    for record in sorted((staging / "reference").glob("*/*.json")) if "reference" in found else []:
        before = json.loads(record.read_text(encoding="utf-8"))
        after = _repointed(before, data / "reference", target / "reference")
        if after != before:
            import records
            records.write(record, after)
    staging.rename(target)
    say(f"Moved {len(found)} into {target}.")
    return found


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", nargs="?", choices=["move-183c"])
    ap.add_argument("--go", action="store_true", help="with move-183c: really move them")
    args = ap.parse_args(argv)
    if args.command == "move-183c":
        move_183c(go=args.go)
        return 0
    found = describe()
    print(f"In use: the {found['in_use']} ({found['chosen_by']}), on the {found['train']} train, "
          f"{found['focal_length_mm']:g} mm; its files in {found['folder']}")
    for name, profile in found["cameras"].items():
        print(f"  camera {name}: " + ", ".join(f"{k} {v}" for k, v in profile.items() if v not in (None, "")))
    for name, train in found["trains"].items():
        print(f"  train {name}: " + ", ".join(f"{k} {v}" for k, v in train.items() if v not in (None, "")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
