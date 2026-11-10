#!/usr/bin/env python3
"""What the guide logs say about how well the guider is doing, run by run.

Reads frames/guide/guide-DATE.jsonl (one line per guide frame, written by
the guider) and, for each guiding run, says:

- the steady offset (mean error) and the scatter about it (SD), RA and Dec:
  an offset moves the stars but does not blur them; the scatter blurs them;
- how much of the frame-to-frame RA error is real (the lag-1 correlation:
  near 0, each frame's error is mostly seeing and centroid noise, which a
  pulse cannot fix; near 1, a real slow drift the guider should follow);
- what a pulse did: the error before it against the error on the next frame;
- how often each axis was pulsed, the Dec reversals and the slack share.

Read-only: it never touches the camera, the mount or the guider's settings.

    ./guidelog.py              tonight's runs
    ./guidelog.py --date 20261110
    ./guidelog.py --json
"""

import argparse
import json
import math
import sys
from datetime import datetime

import numpy as np

import config
import interface

LOG_FOLDER = config.DATA / "frames" / "guide"
FEW = 20        # frames: fewer in a run and it is not judged


def runs(date):
    """{run: [frames]} for the guide log of `date` (YYYYMMDD), in order."""
    path = LOG_FOLDER / f"guide-{date}.jsonl"
    if not path.exists():
        raise interface.Refusal("NOT_FOUND", f"No guide log for {date} ({path}).")
    found = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            frame = json.loads(line)
        except ValueError:
            continue
        found.setdefault(frame.get("run") or "?", []).append(frame)
    return found


def lag1(values):
    """The correlation of each value with the next: how much of it carries over."""
    if len(values) < 3 or np.std(values) == 0:
        return 0.0
    return float(np.corrcoef(values[:-1], values[1:])[0, 1])


def judge(frames):
    """One run's figures, or None when too few frames were guided."""
    good = [f for f in frames if f.get("state") == "guiding" and f.get("ra_err") is not None]
    if len(good) < FEW:
        return None
    ra = np.array([f["ra_err"] for f in good], float)
    dec = np.array([f["dec_err"] for f in good], float)
    pulses = np.array([f.get("pulse_s") or [0.0, 0.0] for f in good], float)
    started = good[0]["time"]["mid"]
    ended = good[-1]["time"]["mid"]
    answer = {
        "run": good[0].get("run"),
        "start": datetime.fromtimestamp(started).strftime("%H:%M"),
        "minutes": round((ended - started) / 60, 1),
        "frames": len(good),
        "lost": sum(1 for f in frames if f.get("state") != "guiding"),
        "snr": round(float(np.median([f["star"]["snr"] for f in good if f.get("star")])), 0),
        "total_rms": round(float(math.sqrt(np.mean(ra ** 2) + np.mean(dec ** 2))), 2),
        "scatter_rms": round(float(math.hypot(ra.std(), dec.std())), 2),
    }
    for axis, err, col in (("ra", ra, 0), ("dec", dec, 1)):
        pulsed = np.nonzero(pulses[:-1, col])[0]
        answer[axis] = {
            "offset": round(float(err.mean()), 2),
            "scatter": round(float(err.std()), 2),
            "carries_over": round(lag1(err), 2),
            "pulsed_share": round(float(np.mean(pulses[:, col] != 0)), 2),
            "before_pulse": round(float(np.abs(err[pulsed]).mean()), 2) if len(pulsed) else None,
            "after_pulse": round(float(np.abs(err[pulsed + 1]).mean()), 2) if len(pulsed) else None,
        }
    answer["reversals"] = sum(1 for f in good if f.get("reversal"))
    shares = [f.get("slack_share") for f in good if f.get("slack_share") is not None]
    answer["slack_share"] = [round(min(shares), 2), round(max(shares), 2)] if shares else None
    answer["reading"] = reading(answer)
    return answer


def reading(r):
    """What the figures say, in plain words."""
    said = []
    ra, dec = r["ra"], r["dec"]
    if ra["carries_over"] < 0.3:
        said.append(f"RA's frame-to-frame error is mostly noise (carries over {ra['carries_over']:.2f}): "
                    "a pulse can only fix the small part that carries over, and pulses sent on the rest add blur")
    elif ra["carries_over"] > 0.6:
        said.append(f"RA's error is a slow drift (carries over {ra['carries_over']:.2f}): it can be followed harder")
    for name, axis in (("RA", ra), ("Dec", dec)):
        if abs(axis["offset"]) > axis["scatter"] / 2 and abs(axis["offset"]) > 0.5:
            said.append(f"{name} sits {axis['offset']:+.1f}\" off the lock throughout: a steady push the "
                        "corrections do not catch up with (it shifts the stars, it does not blur them)")
    if ra["before_pulse"]:
        said.append(f"an RA pulse took the error from {ra['before_pulse']:.1f}\" to {ra['after_pulse']:.1f}\" "
                    "on the next frame (noise alone falls back that way too, so this flatters the pulse)")
    return said


def show(answers):
    for r in answers:
        print(f"Run {r['run']} from {r['start']}: {r['minutes']:g} min, {r['frames']} frames guided, "
              f"{r['lost']} not, star SNR {r['snr']:g}")
        print(f"  RMS {r['total_rms']:.2f}\" in all, {r['scatter_rms']:.2f}\" of it scatter (what blurs the stars)")
        for name in ("ra", "dec"):
            a = r[name]
            print(f"  {name.upper():3} offset {a['offset']:+.2f}\"  scatter {a['scatter']:.2f}\"  "
                  f"carries over {a['carries_over']:.2f}  pulsed {100 * a['pulsed_share']:.0f} % of frames")
        if r["reversals"] or r["slack_share"]:
            print(f"  Dec reversals {r['reversals']}, slack share {r['slack_share']}")
        for line in r["reading"]:
            print(f"  - {line}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", default=datetime.now().strftime("%Y%m%d"), help="YYYYMMDD (default: today)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    def work():
        answers = [a for a in (judge(f) for f in runs(args.date).values()) if a]
        if not args.json:
            show(answers) if answers else print(f"No run on {args.date} guided {FEW} frames or more.")
        return {"date": args.date, "runs": answers}

    interface.main("guidelog", work, args.json)


if __name__ == "__main__":
    sys.exit(main())
