#!/usr/bin/env python3
"""Draw a guiding graph: the guide star's RA and Dec error, frame by frame,
and the pulses sent, from the guider's own frame log.

    ./guidegraph.py --list                 # the runs in the latest log
    ./guidegraph.py                        # the latest run, to web/guide-graph.png
    ./guidegraph.py --date 2026-11-10 --run 4b6d6721 --out ~/guide.png
    ./guidegraph.py --no-send              # drawn, not sent
    ./guidegraph.py --calibration          # the last guide calibration, step by step, a failed one too

Each graph drawn is sent to the person's phone by Telegram (notify.py), with
its run and RMS as the caption (12 November 2026: "make the script do that
from now on"); --no-send keeps it here.

The same picture PHD2 draws, from frames/guide/guide-DATE.jsonl (one line a
frame, written by guider.guide): RA blue, Dec red, in arcseconds against
minutes, + west and north; the pulses below as bars, in seconds; frames
where the star was lost marked grey. The title gives the RMS of the whole
run, so a graph can be posted for advice (12 November 2026: asked for by
Gary).
"""
import argparse
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import config

LOG_FOLDER = config.DATA / "frames" / "guide"
OUT = config.DATA / "web" / "guide-graph.png"
SENT = config.DATA / "cache" / "guidegraph-sent.json"     # runs already sent, so a chain never sends one twice
W, H = 1400, 760
RA_COLOUR, DEC_COLOUR = (60, 130, 230), (220, 60, 60)
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def runs(path):
    """The runs in one frame log, in order: {run id: [frame rows]}."""
    found = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        found.setdefault(row.get("run", "?"), []).append(row)
    return found


def when(row):
    t = row.get("time")
    return t.get("mid") if isinstance(t, dict) else t


def summary(rows):
    """RMS of RA, Dec and total over the frames with a star, and the run's
    length in minutes."""
    good = [r for r in rows if "ra_err" in r]
    if not good:
        return None
    ra = math.sqrt(sum(r["ra_err"] ** 2 for r in good) / len(good))
    dec = math.sqrt(sum(r["dec_err"] ** 2 for r in good) / len(good))
    minutes = (when(rows[-1]) - when(rows[0])) / 60
    return {"ra": ra, "dec": dec, "total": math.hypot(ra, dec), "frames": len(rows),
            "lost": len(rows) - len(good), "minutes": minutes,
            "peak_ra": max(abs(r["ra_err"]) for r in good), "peak_dec": max(abs(r["dec_err"]) for r in good)}


def _font(size):
    try:
        return ImageFont.truetype(FONT, size)
    except OSError:
        return ImageFont.load_default()


def draw(rows, run_id, out, span=None):
    """The graph of one run, written to `out`. `span` is the error axis
    half-height in arcseconds (default: fits the run, at least 5)."""
    s = summary(rows)
    t0 = when(rows[0])
    minutes = max(s["minutes"], 0.5)
    span = span or max(5.0, math.ceil(max(s["peak_ra"], s["peak_dec"]) * 1.1))
    pulse_span = max(0.5, max(max(abs(p) for p in r.get("pulse_s", [0, 0])) for r in rows))

    img = Image.new("RGB", (W, H), (18, 18, 22))
    d = ImageDraw.Draw(img)
    small, mid, big = _font(15), _font(18), _font(22)
    left, right = 80, W - 30
    top, err_bottom = 70, 520
    pulse_top, bottom = 560, H - 60

    def x(row):
        return left + (when(row) - t0) / 60 / minutes * (right - left)

    def y_err(v):
        v = max(-span, min(span, v))
        return (top + err_bottom) / 2 - v / span * (err_bottom - top) / 2

    def y_pulse(v):
        mid_y = (pulse_top + bottom) / 2
        return mid_y - v / pulse_span * (bottom - pulse_top) / 2

    # the grid: arcseconds and minutes
    step = 1 if span <= 6 else 2 if span <= 12 else 5 if span <= 30 else 10
    v = -math.floor(span / step) * step
    while v <= span:
        d.line([(left, y_err(v)), (right, y_err(v))], fill=(70, 70, 80) if v == 0 else (40, 40, 48))
        d.text((left - 10, y_err(v)), f"{v:+g}\"" if v else "0", fill=(170, 170, 180), font=small, anchor="rm")
        v += step
    tick = 1 if minutes <= 12 else 2 if minutes <= 25 else 5
    m = 0
    while m <= minutes + 1e-6:
        gx = left + m / minutes * (right - left)
        d.line([(gx, top), (gx, err_bottom)], fill=(40, 40, 48))
        d.line([(gx, pulse_top), (gx, bottom)], fill=(40, 40, 48))
        d.text((gx, bottom + 8), f"{m:g}", fill=(170, 170, 180), font=small, anchor="mt")
        m += tick
    d.text(((left + right) / 2, bottom + 30), "minutes", fill=(170, 170, 180), font=small, anchor="mt")
    d.rectangle([left, top, right, err_bottom], outline=(90, 90, 100))
    d.rectangle([left, pulse_top, right, bottom], outline=(90, 90, 100))
    d.line([(left, y_pulse(0)), (right, y_pulse(0))], fill=(70, 70, 80))
    d.text((left - 10, pulse_top), f"+{pulse_span:.1f}s", fill=(170, 170, 180), font=small, anchor="rt")
    d.text((left - 10, bottom), f"-{pulse_span:.1f}s", fill=(170, 170, 180), font=small, anchor="rb")
    d.text((left + 8, pulse_top + 4), "pulses (s)", fill=(170, 170, 180), font=small)

    # lost frames, then the two error lines, then the pulse bars
    for r in rows:
        if "ra_err" not in r:
            d.line([(x(r), top), (x(r), err_bottom)], fill=(80, 80, 80), width=2)
    gaps = sorted(b - a for a, b in zip(map(when, rows), map(when, rows[1:])))
    pause = 3 * gaps[len(gaps) // 2] if gaps else math.inf     # a pause order: the line breaks
    for key, colour in (("ra_err", RA_COLOUR), ("dec_err", DEC_COLOUR)):
        line, last = [], None
        for r in rows:
            if key not in r or (last is not None and when(r) - last > pause):
                if len(line) > 1:
                    d.line(line, fill=colour, width=2)
                line = []
            if key in r:
                line.append((x(r), y_err(r[key])))
                last = when(r)
        if len(line) > 1:
            d.line(line, fill=colour, width=2)
    bar = max(1, (right - left) / max(len(rows), 1) * 0.35)
    for r in rows:
        ra_p, dec_p = r.get("pulse_s", [0, 0])
        cx = x(r)
        if ra_p:
            d.rectangle([cx - bar, min(y_pulse(0), y_pulse(ra_p)), cx, max(y_pulse(0), y_pulse(ra_p))],
                        fill=RA_COLOUR)
        if dec_p:
            d.rectangle([cx, min(y_pulse(0), y_pulse(dec_p)), cx + bar, max(y_pulse(0), y_pulse(dec_p))],
                        fill=DEC_COLOUR)

    for r in rows:
        if r.get("dec_held"):       # a Dec pulse held back by the sticking cap
            d.line([(x(r), y_pulse(0) - 4), (x(r), y_pulse(0) + 4)], fill=(240, 200, 60), width=2)
    start = datetime.fromtimestamp(t0)
    cap = next((r["dec_stuck_s"] for r in rows if r.get("dec_stuck_s")), None)
    d.text((left, 18), f"Guiding {start:%d %b %Y %H:%M}, run {run_id}: {s['minutes']:.1f} min, "
           f"{s['frames']} frames" + (f", {s['lost']} lost" if s["lost"] else "")
           + (f", Dec cap {cap:g} s (held: yellow)" if cap else ""),
           fill=(230, 230, 235), font=big)
    d.text((left, 46), f"RMS  RA {s['ra']:.2f}\"   Dec {s['dec']:.2f}\"   total {s['total']:.2f}\"",
           fill=(230, 230, 235), font=mid)
    legend = right
    for name, colour in (("Dec (+ north)", DEC_COLOUR), ("RA (+ west)", RA_COLOUR)):
        wtext = d.textlength(name, font=mid)
        d.text((legend - wtext, 46), name, fill=colour, font=mid)
        legend -= wtext + 30
    if any(abs(r.get(k, 0)) > span for r in rows for k in ("ra_err", "dec_err")):
        d.text((right - 8, top + 6), f"clipped at {span:g}\"", fill=(170, 170, 180), font=small, anchor="rt")

    out = Path(out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out, s


CAL_STEPS = config.DATA / "cache" / "guide-cal-steps.json"     # guider.CAL_STEPS_FILE
CAL_OUT = config.DATA / "web" / "guide-calibration.png"
LEG_COLOURS = {"west": (60, 130, 230), "east": (90, 170, 250), "north": (220, 60, 60), "south": (250, 140, 110),
               "start": (120, 120, 130)}


def legs(looks):
    """The looks cut into runs of one direction: [(leg, [looks])]."""
    out = []
    for look in looks:
        if out and out[-1][0] == look["leg"]:
            out[-1][1].append(look)
        else:
            out.append((look["leg"], [look]))
    return out


def draw_calibration(cal, out):
    """The last calibration's star track, step by step: how far the star had
    moved from where it began, in arcseconds, each leg coloured, and for each
    leg how far it went against how far its pulses should have moved it
    (19 November 2026: a calibration failing on Dec, for the mount's servicer)."""
    looks, scale = cal["looks"], cal["scale"]
    x0, y0 = looks[0]["x"], looks[0]["y"]
    moved = [math.hypot(k["x"] - x0, k["y"] - y0) * scale for k in looks]
    top_v = max(30.0, max(moved) * 1.15)
    img = Image.new("RGB", (W, H), (18, 18, 22))
    d = ImageDraw.Draw(img)
    small, mid, big = _font(15), _font(18), _font(22)
    left, right, top, bottom = 80, W - 30, 70, 520

    def px(i):
        return left + i / max(len(looks) - 1, 1) * (right - left)

    def py(v):
        return bottom - v / top_v * (bottom - top)

    step = 10 if top_v <= 60 else 30 if top_v <= 200 else 60
    v = 0.0
    while v <= top_v:
        d.line([(left, py(v)), (right, py(v))], fill=(40, 40, 48))
        d.text((10, py(v) - 8), f'{v:.0f}"', font=small, fill=(150, 150, 160))
        v += step
    rows, i = [], 0
    for leg, part in legs(looks):
        colour = LEG_COLOURS.get(leg, (200, 200, 200))
        points = [(px(i + k), py(moved[i + k])) for k in range(len(part))]
        if i:
            points = [(px(i - 1), py(moved[i - 1]))] + points       # joined to the leg before
        d.line(points, fill=colour, width=3)
        for p in points[1:]:
            d.ellipse([p[0] - 3, p[1] - 3, p[0] + 3, p[1] + 3], fill=colour)
        if leg in ("west", "east", "north", "south"):
            pulse = cal["step_ms"]["ra" if leg in ("west", "east") else "dec"] / 1000
            before = looks[i - 1] if i else looks[0]
            went = math.hypot(part[-1]["x"] - before["x"], part[-1]["y"] - before["y"]) * scale
            # RA's pulses move the star by the rate times cos(Dec) on the sky
            due = len(part) * pulse * cal["rate"] * (math.cos(math.radians(cal["dec"]))
                                                     if leg in ("west", "east") else 1)
            rows.append((leg, colour, f"{leg}: {len(part)} steps of {pulse:.1f} s, moved {went:.0f}\", "
                                      f"pulses due {due:.0f}\" ({went / due:.0%})" if due else leg))
        i += len(part)
    when = datetime.fromisoformat(cal["made"]).astimezone()
    d.text((left, 15), f"Guide calibration {when:%d %b %Y %H:%M}, Dec {cal['dec']:+.1f}, "
                       f"{'west' if cal['west'] else 'east'} of the pier, {cal['scale']:.2f}\"/px", font=big,
           fill=(230, 230, 235))
    d.text((left, 44), "how far the guide star has moved from its start, look by look; each leg's own colour",
           font=small, fill=(150, 150, 160))
    y = 545
    for _, colour, words in rows[:9]:
        d.rectangle([left, y + 4, left + 14, y + 18], fill=colour)
        d.text((left + 24, y), words, font=mid, fill=(220, 220, 225))
        y += 24
    d.text((left, H - 40), f"outcome: {cal['outcome'][:150]}", font=mid,
           fill=(120, 220, 140) if cal["outcome"] == "kept" else (240, 120, 100))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return Path(out), rows


def calibration_graph(args):
    """--calibration: draw the last calibration's track and send it."""
    try:
        cal = json.loads(CAL_STEPS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        sys.exit("no calibration's steps kept yet: they are kept from 19 November 2026 on")
    if len(cal.get("looks") or []) < 2:
        sys.exit("the last calibration measured fewer than two places: nothing to draw")
    out, rows = draw_calibration(cal, args.out if args.out != str(OUT) else CAL_OUT)
    when = datetime.fromisoformat(cal["made"]).astimezone()
    words = (f"Guide calibration {when:%d %b %H:%M}, Dec {cal['dec']:+.1f}: "
             + "; ".join(r[2] for r in rows if r[0] in ("north", "south"))[:600]
             + f". Outcome: {cal['outcome'][:200]}")
    print(f"{out}: {words}")
    if not args.no_send:
        import notify
        went = notify.send(words, pictures=[(str(out), words[:900])], documents=[(str(out), out.name)])
        print("sent by Telegram" if went else "not sent by Telegram (the bot is not set up here, or it failed)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--calibration", action="store_true",
                    help="the last guide calibration's star track, step by step, leg by leg, a failed one too")
    ap.add_argument("--date", help="the log's date, YYYY-MM-DD (default: the latest log)")
    ap.add_argument("--run", help="the run id, or its start (default: the latest run)")
    ap.add_argument("--list", action="store_true", help="list the runs in the log and stop")
    ap.add_argument("--out", default=str(OUT), help=f"where the PNG goes (default {OUT})")
    ap.add_argument("--span", type=float, help="the error axis, +/- this many arcseconds")
    ap.add_argument("--no-send", action="store_true", help="do not send the graph by Telegram")
    ap.add_argument("--fresh", type=float, metavar="MINUTES",
                    help="only a run that ended within this many minutes; otherwise nothing is drawn or sent "
                         "(12 November 2026: a guide run that found no star was followed by this morning's graph)")
    args = ap.parse_args()
    if args.calibration:
        return calibration_graph(args)

    logs = sorted(LOG_FOLDER.glob("guide-????????.jsonl"))
    if args.date:
        logs = [LOG_FOLDER / f"guide-{args.date.replace('-', '')}.jsonl"]
    if not logs or not logs[-1].exists():
        sys.exit(f"no guide frame log {'for ' + args.date if args.date else 'in ' + str(LOG_FOLDER)}")
    found = runs(logs[-1])
    if args.list:
        print(f"{logs[-1].name}:")
        for run_id, rows in found.items():
            s = summary(rows)
            start = datetime.fromtimestamp(when(rows[0]))
            print(f"  {run_id}  {start:%H:%M}  " + (f"{s['minutes']:5.1f} min  {s['frames']:4d} frames  "
                                                  f"RMS RA {s['ra']:.2f}\" Dec {s['dec']:.2f}\" "
                                                  f"total {s['total']:.2f}\"" if s else "no star found"))
        return
    picked = [k for k in found if not args.run or k.startswith(args.run)]
    picked = [k for k in picked if summary(found[k])]
    if not picked:
        sys.exit(f"no run {args.run or ''} with a star in {logs[-1].name}")
    run_id = picked[-1]
    good = summary(found[run_id])
    if good["lost"] > good["frames"] / 2:
        sys.exit(f"run {run_id} lost its star in {good['lost']} of {good['frames']} frames (cloud): no graph")
    if summary(found[run_id])["minutes"] < 1:
        sys.exit(f"run {run_id} guided for under a minute ({summary(found[run_id])['frames']} frames): no graph")
    if args.fresh is not None:
        ended = (time.time() - when(found[run_id][-1])) / 60
        if ended > args.fresh:
            sys.exit(f"the latest run with a star, {run_id}, ended {ended:.0f} min ago, not within {args.fresh:g}: "
                     "no graph")
    out, s = draw(found[run_id], run_id, args.out, args.span)
    words = (f"Guiding {datetime.fromtimestamp(when(found[run_id][0])):%d %b %H:%M}, run {run_id}: "
             f"{s['minutes']:.1f} min, RMS RA {s['ra']:.2f}\" Dec {s['dec']:.2f}\" total {s['total']:.2f}\"")
    print(f"{out}: {words}")
    try:
        sent = json.loads(SENT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        sent = []
    if not args.no_send and run_id in sent and not args.run:
        print(f"run {run_id} was sent already (13 November 2026: a chain sent one twice); --run {run_id} sends it again")
    elif not args.no_send:
        import notify
        went = notify.send(words, pictures=[(str(out), words)], documents=[(str(out), out.name)])
        print("sent by Telegram" if went else "not sent by Telegram (the bot is not set up here, or it failed)")
        if went:
            SENT.parent.mkdir(parents=True, exist_ok=True)
            SENT.write_text(json.dumps((sent + [run_id])[-200:]), encoding="utf-8")


if __name__ == "__main__":
    main()
