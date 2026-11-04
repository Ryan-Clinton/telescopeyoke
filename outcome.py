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


def cause(entry):
    """Why a frame was not accepted by the run: cloud, trailed, deferred (the
    live stack was behind and left it to the quality pass: not a rejection),
    or other. One rule, shared with history.py."""
    if entry.get("deferred") or "kept for the quality pass" in (entry.get("reason") or ""):
        return "deferred"
    reason = entry.get("reason") or ""
    if "cloud" in reason:
        return "cloud"
    if "trailed" in reason:
        return "trailed"
    return "other"


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


def working_on(session, programme=None, proc=Path("/proc")):
    """Whether a live process is stacking or searching this session: a
    patrol or restack naming the session's folder, or the patrol running its
    programme (whose search is done in that process, panel after panel)."""
    folder, wanted = str(Path(session)), ("patrol.py", "restack.py")
    for entry in proc.glob("[0-9]*/cmdline"):
        try:
            args = entry.read_bytes().split(b"\0")
        except OSError:
            continue
        words = [a.decode(errors="replace") for a in args if a]
        if not any(w.endswith(wanted) for w in words):
            continue
        if any(folder in w for w in words) or (programme and programme in words):
            return True
    return False


def _alive(pid):
    """Whether process `pid` is still running."""
    import os
    try:
        os.kill(int(pid), 0)
    except (OSError, TypeError, ValueError):
        return False
    return True


def search_state(session, programme=None, working=None):
    """Where the session's search is, said apart:
    - ("searched", None): it ran to the end;
    - ("stopped", why): it ran and stopped itself (too few frames, too shallow,
      a subtraction that did not match);
    - ("running", None): a live process is stacking or searching it;
    - ("failed", why): it started (its patrol.log is there) and ended without
      an answer;
    - ("not started", None): nothing ever searched it (`./patrol.py --sweep`
      does);
    - ("none", None): a session no programme searches.
    Only "running" is pending: a failed or never-started search is not left
    waiting for ever (the Phase 1 audit, 4 November 2026)."""
    session = Path(session)
    record = _json(session / "patrol.json")
    if record is not None:
        for line in record.get("summary", []):
            if line.startswith("Stopped at "):
                return "stopped", line.split(": ", 1)[1] if ": " in line else line
        return "searched", None
    if programme is None:
        return "none", None
    job = _json(session / "search.json")
    if job is not None:
        # The search's own record (patrol.search_job), from 4 November 2026.
        if job.get("state") == "failed":
            return "failed", job.get("error") or "the search failed"
        if job.get("state") == "running":
            if _alive(job.get("pid")):
                return "running", None
            return "failed", "the search's process ended without an answer"
    if (working or working_on)(session, programme):
        # Older sessions, and the stack made before the search starts.
        return "running", None
    log = session / "patrol.log"
    if log.exists():
        lines = [line for line in log.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
        return "failed", (lines[-1][:200] if lines else "its log is empty")
    return "not started", None


def camera_retries(session):
    """What the camera layer recorded getting each frame (altair.py's
    TY_RETRY and TY_GOT_S in the raw frames' headers, from 4 November 2026):
    frames that needed a retry, the failed tries and the seconds they took.
    None for a session taken before it was recorded."""
    from astropy.io import fits
    frames = tries = 0
    seconds = 0.0
    seen = False
    for path in sorted(Path(session).glob("light-*.fits")):
        try:
            header = fits.getheader(path)
        except OSError:
            continue
        if "TY_RETRY" not in header:
            continue
        seen = True
        if header["TY_RETRY"]:
            frames += 1
            tries += int(header["TY_RETRY"])
            seconds += max(0.0, float(header.get("TY_GOT_S", 0)) - float(header.get("EXPTIME", 0)))
    return {"frames": frames, "tries": tries, "minutes": round(seconds / 60, 1)} if seen else None


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
    gaps, gap_minutes = stalls(log, plan.get("exposure"))
    causes = [cause(f) for f in log if f.get("accepted") is False]
    state, why = search_state(session, programme)
    record = {
        "session": str(session), "field": field, "programme": programme,
        "requested": plan.get("frames"),
        "captured": len(log) or stack.get("captured"),
        "accepted": sum(1 for f in log if f.get("accepted")) if log else None,
        "stacked": stack.get("stacked"),
        "integration_s": stack.get("total_exposure_s"),
        "depth_g": mag_50,
        # Inferred: long gaps between frames' times. They may be the camera,
        # or something else the run did between frames.
        "gaps": gaps, "gap_minutes": gap_minutes,
        # Recorded: what the camera layer itself said each frame cost.
        "camera_retries": camera_retries(session),
        "rejected": {kind: causes.count(kind) for kind in ("cloud", "trailed", "other")},
        # Not rejected: set aside while the live stack was behind, for the
        # quality pass to judge (restack's stacked count includes them).
        "deferred": causes.count("deferred"),
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
        searchable = "pending" if r["search"] == "running" else "short"
    else:
        searchable = "met" if stacked >= searchable_at else "short"
    if searchable == "met" and r["search"] in ("stopped", "failed", "not started"):
        searchable = "short"          # enough frames, but the search did not run on them
    if searchable == "met" and r["search"] == "running":
        searchable = "pending"
    worth_at, desired_depth = goals.get("worth_depth"), goals.get("desired_depth")
    desired_frames = goals.get("desired_frames")
    if worth_at is None:
        worth = "not judged"
    elif searchable != "met":
        worth = "short" if searchable == "short" else searchable
    elif r["depth_g"] is None:
        # Pending only while something is still working on it; a search that
        # finished without measuring depth is short, not waiting for ever.
        worth = "pending" if r["search"] == "running" else "short"
    else:
        worth = "met" if r["depth_g"] >= worth_at else "short"
    # The goal aimed for. It can't be met by a session that wasn't worth
    # having: 24 frames whose search failed have not met a search's goal.
    if desired_depth is None and desired_frames is None:
        desired = "not set"
    elif worth in ("short", "pending"):
        desired = worth
    elif (desired_depth is not None and r["depth_g"] is None) or (desired_frames is not None and stacked is None):
        desired = "pending"
    else:
        reached = [r["depth_g"] >= desired_depth if desired_depth is not None else True,
                   stacked >= desired_frames if desired_frames is not None else True]
        beyond = (desired_depth is not None and r["depth_g"] >= desired_depth + 0.5) or \
            (desired_frames is not None and stacked >= 1.5 * desired_frames)
        desired = ("more than asked" if beyond else "met") if all(reached) else "short"
    limits = []
    retries = r["camera_retries"]
    if retries and retries["frames"]:
        limits.append(f"camera retries (recorded): {_frames(retries['frames'])}, {retries['tries']} failed tries, "
                      f"{retries['minutes']:g} min")
    if r["gap_minutes"]:
        limits.append(f"gaps between frames (inferred, the camera or the run): {r['gaps']}, "
                      f"{r['gap_minutes']:g} min")
    if r["rejected"]["cloud"]:
        limits.append(f"cloud: {_frames(r['rejected']['cloud'])} rejected")
    if r["rejected"]["trailed"]:
        limits.append(f"trailed: {_frames(r['rejected']['trailed'])} rejected")
    if searchable_at is not None and stacked is not None and stacked < searchable_at:
        limits.append(f"{stacked} stacked, under the {searchable_at} the search needs")
    if r["search"] == "stopped":
        limits.append(f"search stopped: {r['search_stopped']}")
    elif r["search"] == "failed":
        limits.append(f"search failed: {r['search_stopped']}")
    elif r["search"] == "not started":
        limits.append("never searched: ./patrol.py --sweep searches it")
    if worth_at is not None and r["depth_g"] is None and r["search"] in ("searched", "stopped") \
            and searchable == "met":
        limits.append("depth was never measured: ./depth.py SESSION --plant measures it")
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
