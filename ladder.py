#!/usr/bin/env python3
"""The sub-length ladder: how long a guided sub this rig can take with round
stars, measured on the sky, never fixed in advance (docs/autoguiding.md,
proof step 3).

    ./shoot.py TARGET --guide --ladder [30,60,120,180,300] [--ladder-frames 3]
                          guided frames at each length in turn, the sensor
                          kept cold between them, then judged
    ./ladder.py           the kept result: each length's frames and the
                          longest that passed
    ./shoot.py TARGET --guide --exposure ladder
                          a guided run at the longest length that passed,
                          for this camera and light path

A length passes when all its frames were taken, each matched to its own raw
frame (right exposure, filter, camera), and, against the shortest length's
frames: at least KEPT_SHARE of them were both accepted and guided to their
end (GUIDED in the header), their median FWHM is within FWHM_GROWTH, and
their median roundness within ROUNDNESS_LOSS. A length not taken, or not
taken in full, fails. The answer is
the longest length that passed with every shorter one passing too: a
length that only passes past a failing one is luck, not the mount.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

import config
import interface

LENGTHS = (30, 60, 120, 180, 300)   # seconds: the spec's ladder
FRAMES = 3                          # guided frames at each length
KEPT_SHARE = 2 / 3                  # of a length's frames, accepted
FWHM_GROWTH = 1.2                   # median FWHM at most this times the shortest length's
ROUNDNESS_LOSS = 0.9                # median roundness at least this times the shortest length's
GUIDED_SHARE = 2 / 3                # of a length's frames, GUIDED to their end
SETTLE_ALLOW_S = 20                 # seconds a frame's minutes allow for the guider's settling
RESULT = config.DATA / "cache" / "sub-ladder.json"


def lengths(text):
    """`--ladder 30,60,120`: whole seconds, rising, each 1 or more."""
    try:
        values = [int(v) for v in str(text).split(",") if v.strip()]
    except ValueError:
        raise ValueError("lengths are whole seconds, comma-separated") from None
    if not values or any(v < 1 for v in values) or values != sorted(set(values)):
        raise ValueError("lengths are whole seconds, 1 or more, rising, none twice")
    return values


def blocks(seconds, frames, band):
    """The ladder as --blocks: one block of `band` per length, its minutes
    allowing `frames` frames and their settling."""
    return [(band, round(s * frames + SETTLE_ALLOW_S * frames) / 60) for s in seconds]


def measure(folder, exposure, band=None, frames=None):
    """One length's frames, from its session folder. Each frame's quality
    record (frames.jsonl) is matched by its index to its own raw frame
    (light-NNNN.fits, the header in extension 1), which must carry this
    exposure, the band, the camera in use, and GUIDED. A frame counts as
    good only if it was accepted and its raw frame says all of that; a
    missing or mismatched raw frame counts against the length, with why."""
    folder = Path(folder)
    entries = []
    try:
        for line in (folder / "frames.jsonl").read_text(encoding="utf-8").splitlines():
            entries.append(json.loads(line))
    except (OSError, ValueError):
        pass
    taken = [e for e in entries if not e.get("deferred")]
    camera, _ = config.light_path()
    good, guided, rms, problems = [], 0, [], []
    from astropy.io import fits
    for entry in taken:
        path = folder / f"light-{int(entry.get('index', -1)):04d}.fits"
        try:
            header = fits.getheader(path, 1)
        except (OSError, IndexError, KeyError):
            problems.append(f"frame {entry.get('index')}: no raw frame")
            continue
        wrong = []
        if abs(float(header.get("EXPTIME", -1)) - float(exposure)) > 0.5:
            wrong.append(f"exposure {header.get('EXPTIME')}")
        if band and header.get("FILTER") not in (None, band):
            wrong.append(f"filter {header.get('FILTER')}")
        if header.get("INSTRUME") and str(header.get("INSTRUME")) != str(camera):
            wrong.append(f"camera {header.get('INSTRUME')}")
        if wrong:
            problems.append(f"frame {entry.get('index')}: " + ", ".join(wrong))
            continue
        if header.get("GUIDED"):
            guided += 1
            if header.get("GUIDERMS") is not None:
                rms.append(float(header["GUIDERMS"]))
            if entry.get("accepted") and entry.get("fwhm"):
                good.append(entry)
    return {"exposure_s": exposure, "folder": str(folder), "asked": frames, "taken": len(taken),
            "accepted": sum(1 for e in taken if e.get("accepted")), "guided": guided, "good": len(good),
            "fwhm": round(float(np.median([e["fwhm"] for e in good])), 2) if good else None,
            "roundness": round(float(np.median([e["roundness"] for e in good])), 3) if good else None,
            "guide_rms": round(float(np.median(rms)), 2) if rms else None, "problems": problems[:10]}


def not_taken(exposure, frames, why):
    """A length the ladder asked for and did not get."""
    return {"exposure_s": exposure, "folder": None, "asked": frames, "taken": 0, "accepted": 0, "guided": 0,
            "good": 0, "fwhm": None, "roundness": None, "guide_rms": None, "problems": [why]}


def judge(rows):
    """Each length's pass or fail against the shortest's frames, and the
    longest that passed with all shorter ones passing. Returns (rows with
    `passed` and `why`, the longest length or None)."""
    base = rows[0] if rows else None
    longest, unbroken = None, True
    for row in rows:
        why = []
        asked = row.get("asked") or row["taken"]
        if row["taken"] < asked:
            why.append(f"incomplete: {row['taken']} of {asked} frames taken")
        if not row["taken"] or row["good"] / max(asked, 1) < min(KEPT_SHARE, GUIDED_SHARE):
            why.append(f"{row['good']} of {asked} accepted and guided to their end")
        if row.get("problems"):
            why.append(row["problems"][0] + (f" (and {len(row['problems']) - 1} more)" if len(row["problems"]) > 1
                                             else ""))
        if base and base["fwhm"] and row["fwhm"] and row["fwhm"] > FWHM_GROWTH * base["fwhm"]:
            why.append(f"FWHM {row['fwhm']:.2f} against {base['fwhm']:.2f}")
        if base and base["roundness"] and row["roundness"] and row["roundness"] < ROUNDNESS_LOSS * base["roundness"]:
            why.append(f"roundness {row['roundness']:.2f} against {base['roundness']:.2f}")
        if row["fwhm"] is None:
            why.append("no star measured")
        row["passed"] = not why
        row["why"] = "; ".join(why)
        if row["passed"] and unbroken:
            longest = row["exposure_s"]
        else:
            unbroken = False
    return rows, longest


def keep(target, band, rows, longest, path=None):
    """The result, for this camera and light path, with when and on what."""
    camera, focal = config.light_path()
    result = {"made": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "target": target, "filter": band,
              "camera": camera, "focal_mm": focal, "rows": rows, "longest_s": longest}
    path = path or RESULT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def kept(path=None):
    try:
        return json.loads((path or RESULT).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def longest_for_now(path=None):
    """The longest guided sub the kept ladder allows on this camera and light
    path, refused when there is none or it was made on another."""
    result = kept(path)
    if not result:
        raise interface.Refusal("INVALID_REQUEST", "No sub-length ladder kept: run ./shoot.py TARGET --guide "
                                "--ladder first.")
    if (result.get("camera"), result.get("focal_mm")) != config.light_path():
        raise interface.Refusal("INVALID_REQUEST", f"The kept ladder was made with {result.get('camera')} at "
                                f"{result.get('focal_mm')} mm, not the light path in use: run the ladder again.")
    if not result.get("longest_s"):
        raise interface.Refusal("INVALID_REQUEST", "The kept ladder passed no length: guided subs are not proven "
                                "at any length yet.")
    return float(result["longest_s"])


def report(result, say=print):
    say(f"Sub-length ladder of {result['made']}: {result['target']} in {result['filter']}, "
        f"{result['camera']} at {result['focal_mm']} mm")
    for row in result["rows"]:
        say(f"  {row['exposure_s']:>4g} s: {row['taken']}/{row.get('asked') or row['taken']} taken, "
            f"{row['accepted']} kept, {row['guided']} guided, {row['good']} both, "
            f"FWHM {row['fwhm'] if row['fwhm'] is not None else '-'}, round "
            f"{row['roundness'] if row['roundness'] is not None else '-'}, guide RMS "
            f"{row['guide_rms'] if row['guide_rms'] is not None else '-'}\"  "
            + ("pass" if row["passed"] else f"FAIL ({row['why']})"))
    say(f"Longest guided sub with round stars: {result['longest_s']} s" if result.get("longest_s")
        else "No length passed.")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="the kept result as JSON")
    args = ap.parse_args(argv)
    result = kept()
    if not result:
        sys.exit("No sub-length ladder kept yet: ./shoot.py TARGET --guide --ladder")
    if args.json:
        print(json.dumps(result, indent=1))
    else:
        report(result)


if __name__ == "__main__":
    main()
