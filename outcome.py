#!/usr/bin/env python3
"""What each observation got: its frames from asked to stacked, its depth,
and whether it ran, could be searched and was worth it, against its
programme's goals (docs/observing-plan-spec.md, Phase 1).

    ./outcome.py frames/M31-P3/20261104-033025      one session
    ./outcome.py --night 2026-11-03                 every session of a night (the evening's date)
    ./outcome.py --night                            tonight's, or last night's before noon
    ./outcome.py --night 2026-11-03 --json

It only reads what the run, the stack and the search already wrote
(session.json, frames.jsonl, restack.json, depth.json, patrol.json and the
candidate books); it changes nothing, and says "pending" for what is still
being worked out in the background.
"""
import argparse
import json
import re
import statistics
import tomllib
from datetime import date, datetime, timedelta
from pathlib import Path

import config
import interface

ROOT = Path(__file__).parent
PROGRAMMES = ROOT / "programmes"
STALL_S = 30.0       # seconds between frames beyond the usual that count as a camera stall
FRAME_GAP_S = 5.6    # seconds between frames beyond the exposure, as patrol.FRAME_GAP_S (median, 4 Nov 2026)
NIGHT_TURNS = 12     # the hour (local) a night's sessions are counted from: noon to noon


def programme_for(field):
    """The programme a field belongs to and its goals: (name, goals), or
    (None, {}) for a field no programme watches."""
    for path in sorted(PROGRAMMES.glob("*.toml")):
        with path.open("rb") as f:
            p = tomllib.load(f)
        mosaic = p.get("mosaic")
        if p.get("target") == field or (mosaic and re.fullmatch(rf"{re.escape(mosaic)}-P\d+", field)):
            return path.stem, p.get("goals", {})
    return None, {}


def _json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def frames_log(session):
    """Each frame's line, as the run wrote it."""
    path = Path(session) / "frames.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def stalls(log, exposure=None):
    """Camera stalls from the frame times: (how many, minutes lost). A gap
    more than STALL_S beyond the usual one is a stall. The usual gap is the
    exposure and the camera's measured pace, not the session's own median:
    a session that stalled on most frames (M31-P6, 4 Nov 2026) has a stall
    for its median."""
    times = sorted(f["taken"] for f in log if isinstance(f.get("taken"), (int, float)))
    gaps = [b - a for a, b in zip(times, times[1:])]
    if not gaps:
        return 0, 0.0
    usual = exposure + FRAME_GAP_S if exposure else statistics.median(gaps)
    lost = [g - usual for g in gaps if g > usual + STALL_S]
    return len(lost), round(sum(lost) / 60, 1)


def search_state(session, field_watched):
    """Whether the session's search ran: ("searched", None), ("stopped", why),
    ("pending", None) while the background search has not finished, or
    ("none", None) for a session no search is meant for."""
    record = _json(Path(session) / "patrol.json")
    if record is None:
        return ("pending", None) if field_watched else ("none", None)
    for line in record.get("summary", []):
        if line.startswith("Stopped at "):
            return "stopped", line.split(": ", 1)[1] if ": " in line else line
    return "searched", None


def owed(field, session):
    """Open candidates first seen in this session and seen on no other night:
    each is owed a second look."""
    book = _json(config.DATA / "candidates" / f"{field}.json")
    if not book:
        return []
    name = Path(session).name
    return [k["id"] for k in book.get("candidates", [])
            if k.get("open") and k.get("first") == name and len(k.get("nights", [])) == 1]


def of_session(session):
    """What one session got, and what its programme asked of it."""
    session = Path(session)
    field = session.parent.name
    programme, goals = programme_for(field)
    plan = _json(session / "session.json") or {}
    log = frames_log(session)
    stack = (_json(session / "restack.json") or {}).get("summary", {})
    depth = _json(session / "depth.json") or {}
    mag_50 = depth.get("completeness", {}).get("all", {}).get("mag_50")
    stalled, stall_minutes = stalls(log, plan.get("exposure"))
    rejected = [f.get("reason") or "" for f in log if f.get("accepted") is False]
    state, why = search_state(session, programme is not None)
    record = {
        "session": str(session), "field": field, "programme": programme,
        "requested": plan.get("frames"),
        "captured": len(log) or stack.get("captured"),
        "accepted": sum(1 for f in log if f.get("accepted")) if log else None,
        "stacked": stack.get("stacked"),
        "integration_s": stack.get("total_exposure_s"),
        "depth_g": mag_50,
        "stalls": stalled, "stall_minutes": stall_minutes,
        "rejected": {"cloud": sum("cloud" in r for r in rejected),
                     "trailed": sum("trailed" in r for r in rejected),
                     "other": sum(not ("cloud" in r or "trailed" in r) for r in rejected)},
        "search": state, "search_stopped": why,
        "owed": owed(field, session),
        "goals": goals,
    }
    record.update(judge(record, goals))
    return record


def keep(session):
    """Work out a session's outcome and keep it beside it as outcome.json."""
    import records
    record = of_session(session)
    records.write(Path(session) / "outcome.json", record, schema="outcome#/$defs/session", stamp=True)
    return record


def during(started, finished, data=None):
    """Sessions begun between two moments (unix seconds): a schedule step's."""
    data = data or config.DATA
    out = []
    for folder in (data / "frames").glob("*/*/"):
        try:
            when = datetime.strptime(folder.name, "%Y%m%d-%H%M%S").timestamp()
        except ValueError:
            continue
        if started - 5 <= when <= finished and (folder / "session.json").exists():
            out.append((when, folder))
    return [folder for _, folder in sorted(out)]


def judge(r, goals):
    """The three outcomes (ran, searchable, worth it), each met, short, more
    than asked, pending or not judged, and what limited the session."""
    ran = "met" if r["captured"] else "short"
    searchable_at = goals.get("searchable_frames")
    stacked = r["stacked"]
    if searchable_at is None:
        searchable = "not judged"
    elif stacked is None:
        searchable = "pending"
    else:
        searchable = "met" if stacked >= searchable_at else "short"
    if searchable == "met" and r["search"] == "stopped":
        searchable = "short"          # enough frames, but the search could not run on them
    worth_at, desired_depth = goals.get("worth_depth"), goals.get("desired_depth")
    desired_frames = goals.get("desired_frames")
    if worth_at is None:
        worth = "not judged"
    elif searchable != "met":
        worth = "short" if searchable == "short" else searchable
    elif r["depth_g"] is None:
        worth = "pending"
    else:
        worth = "met" if r["depth_g"] >= worth_at else "short"
    # The goal aimed for, apart from whether it was worth having at all.
    if desired_depth is None and desired_frames is None:
        desired = "not set"
    elif (desired_depth is not None and r["depth_g"] is None) or (desired_frames is not None and stacked is None):
        desired = "pending"
    else:
        reached = [r["depth_g"] >= desired_depth if desired_depth is not None else True,
                   stacked >= desired_frames if desired_frames is not None else True]
        beyond = (desired_depth is not None and r["depth_g"] >= desired_depth + 0.5) or \
            (desired_frames is not None and stacked >= 1.5 * desired_frames)
        desired = ("more than asked" if beyond else "met") if all(reached) else "short"
    limits = []
    if r["stall_minutes"]:
        limits.append(f"camera stalls: {r['stalls']}, {r['stall_minutes']:g} min lost")
    if r["rejected"]["cloud"]:
        limits.append(f"cloud: {_frames(r['rejected']['cloud'])} rejected")
    if r["rejected"]["trailed"]:
        limits.append(f"trailed: {_frames(r['rejected']['trailed'])} rejected")
    if searchable_at is not None and stacked is not None and stacked < searchable_at:
        limits.append(f"{stacked} stacked, under the {searchable_at} the search needs")
    if r["search"] == "stopped":
        limits.append(f"search stopped: {r['search_stopped']}")
    if worth_at is not None and r["depth_g"] is not None and r["depth_g"] < worth_at:
        limits.append(f"shallow: G {r['depth_g']:.2f}, under the G {worth_at:g} it needs to be worth it")
    return {"ran": ran, "searchable": searchable, "worth_it": worth, "desired": desired, "limited_by": limits}


def _frames(n):
    return f"{n} frame" + ("" if n == 1 else "s")


def night_sessions(evening, data=None):
    """Every session of the night that began on `evening` (a date): from
    noon that day to noon the next, by the session folders' names."""
    data = data or config.DATA
    start = datetime.combine(evening, datetime.min.time()) + timedelta(hours=NIGHT_TURNS)
    end = start + timedelta(days=1)
    out = []
    for folder in (data / "frames").glob("*/*/"):
        try:
            when = datetime.strptime(folder.name, "%Y%m%d-%H%M%S")
        except ValueError:
            continue
        if start <= when < end and (folder / "session.json").exists():
            out.append((when, folder))
    return [folder for _, folder in sorted(out)]


def evening_of(now=None):
    """The night being asked about: tonight's from noon, last night's before."""
    now = now or datetime.now()
    return (now - timedelta(hours=NIGHT_TURNS)).date()


def words(r):
    """One line for a person, then what limited it and what it leaves owed."""
    nums = (f"{r['requested'] or '?'} asked, {r['captured'] or 0} taken, "
            f"{r['accepted'] if r['accepted'] is not None else '?'} accepted, "
            f"{r['stacked'] if r['stacked'] is not None else 'pending'} stacked")
    seconds = f", {r['integration_s']:.0f} s" if r["integration_s"] else ""
    deep = f", G {r['depth_g']:.2f}" if r["depth_g"] is not None else ""
    head = f"{Path(r['session']).name[9:13]} {r['field']}: {nums}{seconds}{deep}"
    verdict = (f"ran {r['ran']}; searchable {r['searchable']}; worth it {r['worth_it']}; "
               f"desired {r['desired']}")
    lines = [head, f"    {verdict}"]
    if r["limited_by"]:
        lines.append("    limited by " + "; ".join(r["limited_by"]))
    if r["owed"]:
        lines.append(f"    owed a second look: {', '.join(r['owed'])}")
    return lines


def run(args, say=print):
    if args.session:
        records = [of_session(args.session)]
    else:
        evening = date.fromisoformat(args.night) if args.night else evening_of()
        records = [of_session(s) for s in night_sessions(evening)]
        if not records:
            say(f"No sessions on the night of {evening}.")
    for r in records:
        for line in words(r):
            say(line)
    return {"sessions": records}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("session", nargs="?", help="one session folder")
    ap.add_argument("--night", nargs="?", const="", default=None,
                    help="every session of the night that began on this date (YYYY-MM-DD); "
                         "alone, tonight's or last night's")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    if not args.session and args.night is None:
        ap.error("give a session folder or --night")
    interface.main("outcome", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
