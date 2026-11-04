#!/usr/bin/env python3
"""What observing really costs, measured from every night kept: the time
between frames, the gaps between sessions (GoTo, plate solves, camera
start), long gaps within a session, the camera's own recorded retries,
rejections by cause, the share of accepted frames that reach the stack,
and how far measured depth sits from the depth model. Medians and 90th
percentiles with how many measurements and nights each rests on, never
one night's figure (docs/observing-plan-spec.md, Phase 5).

    ./history.py                 every night kept
    ./history.py --since 2026-10-18
    ./history.py --json

It reads the sessions' own records only. What is inferred (a gap between
frames' times) is kept apart from what was recorded (the camera layer's
TY_RETRY in each raw frame, from 4 November 2026).
"""
import argparse
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path

import config
import interface
import outcome

MOVE_MAX_S = 20 * 60     # a gap between sessions longer than this is a wait, not a move
NIGHT_TURNS = outcome.NIGHT_TURNS


def spread(values):
    """{median, p90, p10, n} of a list, or None when there is nothing."""
    values = sorted(v for v in values if v is not None)
    if not values:
        return None

    def at(share):
        return values[min(len(values) - 1, int(share * (len(values) - 1) + 0.5))]
    return {"median": round(statistics.median(values), 2), "p10": round(at(0.1), 2), "p90": round(at(0.9), 2),
            "n": len(values)}


def night_of(when):
    """The evening's date a moment belongs to (noon to noon)."""
    return (when - timedelta(hours=NIGHT_TURNS)).date()


def session_night(folder):
    """The evening's date of a session folder (or a folder inside one), from
    its name; None if it has no date."""
    for part in (Path(folder), *Path(folder).parents):
        try:
            return night_of(datetime.strptime(part.name, "%Y%m%d-%H%M%S"))
        except ValueError:
            continue
    return None


def sessions(since=None, data=None, before=None):
    """Every session with a frame log, oldest first, as dicts of what the
    measures need; with `before`, only nights before that evening."""
    data = data or config.DATA
    out = []
    for folder in sorted((data / "frames").glob("*/*/")):
        try:
            night = night_of(datetime.strptime(folder.name, "%Y%m%d-%H%M%S"))
        except ValueError:
            continue
        if (since and night < since) or (before and night >= before):
            continue
        log = outcome.frames_log(folder)
        times = sorted(f["taken"] for f in log if isinstance(f.get("taken"), (int, float)))
        if not times:
            continue
        plan = outcome._json(folder / "session.json") or {}
        out.append({"folder": folder, "field": folder.parent.name, "night": night.isoformat(),
                    "exposure": plan.get("exposure"), "log": log, "first": times[0], "last": times[-1],
                    "times": times})
    return sorted(out, key=lambda s: s["first"])


def frame_gaps(rows, exposure=None):
    """Seconds between frames beyond the exposure, stalls left out (they are
    measured apart), over every session with a known exposure, or only
    those of one exposure: readout and processing differ by exposure."""
    out = []
    for s in rows:
        if not s["exposure"] or (exposure is not None and s["exposure"] != exposure):
            continue
        for a, b in zip(s["times"], s["times"][1:]):
            beyond = b - a - s["exposure"]
            if 0 <= beyond <= outcome.STALL_S:
                out.append(beyond)
    return out


def frame_gaps_by_exposure(rows):
    return {f"{e:g}": spread(frame_gaps(rows, e)) for e in sorted({s["exposure"] for s in rows if s["exposure"]})}


def long_gaps(rows):
    """Inferred stalls: per session hour, how many gaps ran more than
    STALL_S beyond the usual, and how long each lost."""
    per_hour, lengths, hours = [], [], 0.0
    for s in rows:
        if not s["exposure"] or len(s["times"]) < 3:
            continue
        count, minutes = outcome.stalls(s["log"], s["exposure"])
        span = (s["last"] - s["first"]) / 3600
        if span < 0.1:
            continue
        hours += span
        per_hour.append(count / span)
        if count:
            lengths.append(60 * minutes / count)
    return {"per_hour": spread(per_hour), "seconds_each": spread(lengths), "hours": round(hours, 1),
            "kind": "inferred: a gap between frames' times, the camera or the run"}


def recorded_retries(rows):
    """The camera layer's own record (TY_RETRY, TY_GOT_S), where frames have it."""
    from astropy.io import fits
    frames = retried = 0
    seconds = []
    for s in rows:
        for path in sorted(s["folder"].glob("light-*.fits")):
            try:
                header = fits.getheader(path)
            except OSError:
                continue
            if "TY_RETRY" not in header:
                continue
            frames += 1
            if header["TY_RETRY"]:
                retried += 1
                seconds.append(float(header.get("TY_GOT_S", 0)) - float(header.get("EXPTIME", 0)))
    if not frames:
        return None
    return {"frames": frames, "share_retried": round(retried / frames, 3), "seconds_lost": spread(seconds),
            "kind": "recorded by the camera layer"}


def moves(rows):
    """Seconds from one session's last frame to the next session's first, the
    same night: the GoTo, its plate solves and the camera starting, and
    anything else done between (inferred). Gaps over MOVE_MAX_S are waits."""
    out = []
    for a, b in zip(rows, rows[1:]):
        gap = b["first"] - a["last"] - (b["exposure"] or 0)
        if a["night"] == b["night"] and 0 < gap <= MOVE_MAX_S:
            out.append(gap)
    return out


def rejections(rows):
    """Each cause's share of the frames taken, over all frames and night by
    night (a range, since cloud is the night's, not the kit's)."""
    totals, nights = {}, {}
    for s in rows:
        for f in s["log"]:
            kind = "accepted" if f.get("accepted") else outcome.cause(f)
            totals[kind] = totals.get(kind, 0) + 1
            night = nights.setdefault(s["night"], {})
            night[kind] = night.get(kind, 0) + 1
    taken = sum(totals.values()) or 1
    by_night = {kind: spread([n.get(kind, 0) / sum(n.values()) for n in nights.values()])
                for kind in ("cloud", "trailed", "other", "deferred")}
    return {"frames": taken, "share": {k: round(v / taken, 3) for k, v in sorted(totals.items())},
            "share_by_night": by_night}


def stacked_share(rows):
    """Stacked frames over accepted and deferred ones, session by session:
    what the quality pass keeps."""
    out = []
    for s in rows:
        stack = (outcome._json(s["folder"] / "restack.json") or {}).get("summary", {})
        offered = sum(1 for f in s["log"] if f.get("accepted") or outcome.cause(f) == "deferred")
        if stack.get("stacked") is not None and offered:
            out.append(min(1.0, stack["stacked"] / offered))
    return out


def depth_error(rows, data=None, before=None):
    """Measured depth less the depth model's prediction for the same stack:
    how far a modelled depth can be trusted. With `before`, the model is
    fitted only to stacks from nights before that evening."""
    import depth
    measured = depth.measurements((data or config.DATA) / "frames")
    if before:
        measured = [m for m in measured if (session_night(m["session"]) or before) < before]
    try:
        model, _ = depth.fit(measured)
    except interface.Refusal:
        return None, []
    out = []
    for s in rows:
        r = outcome._json(s["folder"] / "depth.json") or {}
        half = r.get("completeness", {}).get("all", {}).get("mag_50")
        if half is None or not r.get("fwhm_arcsec") or not r.get("sky_mag_per_arcsec2") or not r.get("exposure_s"):
            continue
        out.append(half - depth.predict(model, r["fwhm_arcsec"], r["sky_mag_per_arcsec2"], r["exposure_s"]))
    return model, out


def search_outcomes(rows):
    """How the searches of sessions with enough frames ended: searched to
    the end, or stopped by a subtraction that did not match, no reference,
    or a stack that would not solve (outcome.stop_kind), with the counts a
    replay draws its odds from. Stops for too few frames or too shallow a
    stack are left out: a replay works those out from its own frames."""
    counts = {}
    for s in rows:
        programme, goals = outcome.programme_for(s["field"])
        if not goals:
            continue
        state, why = outcome.search_state(s["folder"], programme, working=lambda *_: False)
        kind = "searched" if state == "searched" else outcome.stop_kind(why) if state == "stopped" else None
        if kind in ("searched", "subtraction", "no reference", "unsolved"):
            counts[kind] = counts.get(kind, 0) + 1
    return counts


def costs(since=None, data=None, before=None):
    """Every measure, as one record; with `before`, from nights before that
    evening only, as a replay of it must be (it cannot learn from itself)."""
    rows = sessions(since, data, before)
    model, errors = depth_error(rows, data, before)
    return {
        "since": since.isoformat() if since else None,
        "before": before.isoformat() if before else None,
        "search_outcomes": search_outcomes(rows),
        "nights": len({s["night"] for s in rows}), "sessions": len(rows),
        "frame_gap_s": spread(frame_gaps(rows)),
        "frame_gap_s_by_exposure": frame_gaps_by_exposure(rows),
        "move_s": spread(moves(rows)),
        "long_gaps": long_gaps(rows),
        "camera_retries": recorded_retries(rows),
        "rejections": rejections(rows),
        "stacked_share": spread(stacked_share(rows)),
        "depth_model_error": spread(errors),
        "depth_model": model,
    }


def words(c, say=print):
    def show(name, s, unit=""):
        if s is None:
            say(f"{name}: not measured yet")
        else:
            say(f"{name}: median {s['median']}{unit}, 10-90% {s['p10']}-{s['p90']}{unit} (n {s['n']})")
    say(f"{c['sessions']} sessions on {c['nights']} nights" + (f" since {c['since']}" if c["since"] else ""))
    show("between frames, beyond the exposure", c["frame_gap_s"], " s")
    for exposure, gap in c["frame_gap_s_by_exposure"].items():
        if gap and gap["n"] >= 20:
            show(f"  {exposure} s frames", gap, " s")
    show("between sessions (GoTo, solves, camera start; inferred)", c["move_s"], " s")
    g = c["long_gaps"]
    show(f"long gaps an hour ({g['kind']}, {g['hours']} h)", g["per_hour"])
    show("  each one lost", g["seconds_each"], " s")
    r = c["camera_retries"]
    say("camera retries (recorded): " + ("none recorded yet (from 4 November 2026)" if r is None else
        f"{100 * r['share_retried']:.1f}% of {r['frames']} frames"))
    j = c["rejections"]
    say("of " + str(j["frames"]) + " frames taken: " +
        ", ".join(f"{k} {100 * v:.1f}%" for k, v in j["share"].items()))
    show("stacked share of accepted", c["stacked_share"])
    show("measured depth less the model", c["depth_model_error"], " mag")


def run(args, say=print):
    since = date.fromisoformat(args.since) if args.since else None
    c = costs(since)
    words(c, say)
    return c


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", help="only nights from this date (YYYY-MM-DD)")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("history", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
