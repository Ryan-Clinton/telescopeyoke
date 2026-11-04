#!/usr/bin/env python3
"""What the night owes, with why and until when (docs/observing-plan-spec.md,
Phase 4).

    ./obligations.py              what is owed now, refreshed from the records
    ./obligations.py --json

An obligation is one of:
- second look: an unconfirmed candidate's, seen on one night only;
- follow-up: a candidate seen again on another night: its brightness with
  an error and its last non-detection, then the person vets it;
- field short: a field whose last visit fell short of its minimum or of
  being worth it, which keeps its turn;
- search not run: frames that were never searched, or whose search failed
  (processing, never the telescope);
- interrupted: a protected step (a transit) cut short or failed, said by the
  runner with owe().

Each says what it is, why it is owed, when it stops counting, and whether
repeating it is still worth anything. They are kept between nights in
config.DATA/cache/obligations.json, never only in memory, refreshed from the
candidate books and the sessions' outcomes. This module reads and keeps
records; it never moves anything.

Candidates are weighed, not assumed (weigh()): their evidence level, their
real-or-bogus probability, their score against their own surroundings,
whether another look at the same depth could settle them, and how long they
stay useful. Uncertain ones share a bounded part of the night, the
follow-up allowance ([plan] follow_up_share); strong ones go first outside it.
"""
import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import config
import interface
import records

FILE = config.DATA / "cache" / "obligations.json"
USEFUL_DAYS = {"nova-patrol": 7, "moving": 1, "known-transient": 3, "lead": 30, None: 7}
FIELD_DAYS = 10           # a short field keeps its turn this long (patrol.DEBT_DAYS)
SEARCH_DAYS = 7           # frames unsearched this long are swept, not owed to the night
RB_STRONG = 0.5           # real-or-bogus probability of a strong candidate
LOCAL_STRONG = 5.0        # its score against its own surroundings
SETTLE_MARGIN = 0.3       # mag: a candidate this near the stack's depth can't be settled at the same depth
LOOK_S = 10 * 60          # a second look's frames (patrol.CONFIRM_MINUTES)


def _read(path=None):
    try:
        found = json.loads(Path(path or FILE).read_text(encoding="utf-8"))
        return found if isinstance(found, dict) else {}
    except (OSError, ValueError):
        return {}


def load(path=None):
    store = _read(path)
    store.setdefault("obligations", [])
    store.setdefault("allowance", {})
    return store


def save(store, path=None):
    path = Path(path or FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    records.write(path, store, stamp=True)


def _day(stamp):
    return datetime.strptime(stamp[:8], "%Y%m%d").date()


def level(c):
    """The candidate's evidence level (the spec's evidence standard): 1 a
    detection, 2 a candidate worth a look (unexplained by every check made,
    in both halves of the night), 3 seen again on another night."""
    nights = [n for n in c.get("nights", []) if n.get("seen") and not n.get("forced")]
    if len(nights) >= 2:
        return 3
    verdicts = [n.get("verdict", "") for n in c.get("nights", [])]
    if any(v.startswith("unexplained") for v in verdicts):
        return 2
    return 1


def weigh(c, depth_g=None, today=None, purpose="nova-patrol"):
    """A candidate's claim on the night, weighed:
    - confidence: level, real-or-bogus probability (its uncertainty is not
      recorded yet, and is said so), score against its own surroundings;
    - novelty: a dismissal or a known problem patch closes it;
    - what another look would settle: one at the limit of its stack waits
      for a deeper or steadier night;
    - time: past its usefulness it is closed, not chased.
    Returns a dict with `verdict`: now, allowance, wait or close, and why."""
    today = today or date.today()
    first = _day(c.get("first", "19700101"))
    useful = first + timedelta(days=USEFUL_DAYS.get(purpose, 7))
    last = (c.get("nights") or [{}])[-1]
    rb, local, mag = last.get("real_bogus"), last.get("local_score"), last.get("mag")
    out = {"id": c.get("id"), "level": level(c), "real_bogus": rb, "rb_uncertainty": None,
           "local_score": local, "mag": mag, "until": useful.isoformat()}
    if not c.get("open", True) or c.get("dismissed"):
        return {**out, "verdict": "close", "why": c.get("closed_because") or "closed"}
    if out["level"] >= 3:
        # Seen again on another night: not done with, but a different
        # follow-up. Its brightness with an error and its last non-detection
        # (the evidence standard's level 3), then the person vets and claims.
        last_night = max((_day(n["night"]) for n in c.get("nights", []) if n.get("night")), default=first)
        out["until"] = (last_night + timedelta(days=USEFUL_DAYS.get(purpose, 7))).isoformat()
        if today > date.fromisoformat(out["until"]):
            return {**out, "verdict": "close", "why": f"past its usefulness ({out['until']})"}
        return {**out, "verdict": "now", "why": "seen again on another night (level 3): measure its brightness with "
                                                "an error and its last non-detection, then the person vets it"}
    if today > useful:
        return {**out, "verdict": "close", "why": f"past its usefulness ({useful})"}
    if depth_g is not None and mag is not None and mag > depth_g - SETTLE_MARGIN:
        return {**out, "verdict": "wait", "why": f"G {mag:.2f} at the stack's limit (G {depth_g:.2f}): another look at "
                                                 "the same depth can't settle it; it waits for a deeper night"}
    strong = out["level"] >= 2 and rb is not None and rb >= RB_STRONG and (local is None or local >= LOCAL_STRONG)
    if strong:
        return {**out, "verdict": "now", "why": f"strong: level 2, real-or-bogus {rb:.2f}"}
    return {**out, "verdict": "allowance", "why": "uncertain: from the night's follow-up allowance"
                                                  + ("" if rb is None else f" (real-or-bogus {rb:.2f})")}


def _key(o):
    return f"{o['kind']}:{o['field']}:{o.get('ref', '')}"


def refresh(today=None, data=None, path=None, nights=3):
    """The store brought up to date from the candidate books and the last
    `nights` nights' outcomes; past obligations expired, met ones done."""
    import goals
    import outcome
    data = data or config.DATA
    today = today or date.today()
    store = load(path)
    found = {}
    for book_path in sorted((data / "candidates").glob("*.json")):
        try:
            book = json.loads(book_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        field = book.get("name") or book_path.stem
        purpose = goals.of(field)["purpose"]
        for c in book.get("candidates", []):
            depth_g = _depth_of(data, field, c.get("first", ""))
            w = weigh(c, depth_g, today, purpose)
            if c.get("open") and len(c.get("nights", [])) == 1:
                found[f"second look:{field}:{c['id']}"] = {
                    "kind": "second look", "field": field, "ref": c["id"],
                    "what": f"a second look at {c['id']}", "why": "seen on one night only; unconfirmed",
                    "until": w["until"], "worth": w["verdict"] in ("now", "allowance"), "weighed": w}
            elif c.get("open") and w["level"] >= 3:
                # Seen again: kept owed, as a follow-up of its own kind.
                found[f"follow-up:{field}:{c['id']}"] = {
                    "kind": "follow-up", "field": field, "ref": c["id"],
                    "what": f"{c['id']}: brightness with its error and last non-detection, then the person vets it",
                    "why": "seen again on another night (level 3)",
                    "until": w["until"], "worth": w["verdict"] == "now", "weighed": w}
    for back in range(nights):
        evening = today - timedelta(days=back + 1)
        for session in outcome.night_sessions(evening, data):
            try:
                r = outcome.of_session(session)
            except Exception:       # one unreadable session is not the store's
                continue
            field = r["field"]
            if r["programme"] is None:
                continue
            if r["search"] in ("failed", "not started"):
                found[f"search not run:{field}:{Path(session).name}"] = {
                    "kind": "search not run", "field": field, "ref": Path(session).name,
                    "what": f"the search of {field} {Path(session).name}",
                    "why": f"search {r['search']}" + (f": {r['search_stopped']}" if r["search_stopped"] else ""),
                    "until": (evening + timedelta(days=SEARCH_DAYS)).isoformat(), "worth": True,
                    "telescope": False}
            short = "short" in (r["searchable"], r["worth_it"])
            key = f"field short:{field}:"
            if short:
                found[key] = {"kind": "field short", "field": field, "ref": "",
                              "what": f"{field} again, to its goals",
                              "why": "; ".join(r["limited_by"][:2]) or "short of its goals",
                              "until": (evening + timedelta(days=FIELD_DAYS)).isoformat(), "worth": True,
                              "since": Path(session).name}
            elif r["worth_it"] == "met" and key in found and found[key].get("since", "") < Path(session).name:
                found.pop(key)
    kept = {_key(o): o for o in store["obligations"]}
    now_iso = datetime.now().isoformat(timespec="seconds")
    for key, o in kept.items():
        if o.get("state") != "open":
            continue
        if key in found:
            continue
        if o["kind"] == "interrupted":
            if o["until"] < today.isoformat():
                o.update(state="expired", closed=now_iso)
            continue
        o.update(state="done" if o["until"] >= today.isoformat() else "expired", closed=now_iso)
    for key, o in found.items():
        if o["until"] < today.isoformat():
            o["state"] = "expired"
        else:
            o["state"] = "open"
        old = kept.get(key, {})
        kept[key] = {**old, **o, "made": old.get("made", now_iso)}
    store["obligations"] = sorted(kept.values(), key=lambda o: (o["state"] != "open", o["until"], _key(o)))
    save(store, path)
    return store


def _depth_of(data, field, session_name):
    try:
        d = json.loads((data / "frames" / field / session_name / "depth.json").read_text(encoding="utf-8"))
        return d.get("completeness", {}).get("all", {}).get("mag_50")
    except (OSError, ValueError):
        return None


def owe(kind, field, what, why, until, ref="", path=None):
    """An obligation the runner records itself (an interrupted transit, a
    failed plate solve)."""
    store = load(path)
    o = {"kind": kind, "field": field, "ref": ref, "what": what, "why": why, "until": until, "worth": True,
         "state": "open", "made": datetime.now().isoformat(timespec="seconds")}
    store["obligations"] = [x for x in store["obligations"] if _key(x) != _key(o)] + [o]
    save(store, path)
    return o


def open_ones(store=None, path=None):
    store = store or load(path)
    return [o for o in store["obligations"] if o.get("state") == "open" and o.get("worth")]


# --- the follow-up allowance --------------------------------------------------------

def evening_key(now=None):
    import outcome
    return outcome.evening_of(datetime.fromtimestamp(now) if now else None).isoformat()


def share(cfg=None):
    if cfg is None:
        import goals
        cfg = goals.plan_config()
    return float((cfg.get("plan") or {}).get("follow_up_share", 0.25))


def may_follow_up(candidate_weights, night_seconds, now=None, path=None, cfg=None):
    """(go?, why) for a second look at a field whose candidates are
    weighed as given: a strong one goes at once; uncertain ones only while
    the night's follow-up allowance lasts; ones that wait or are closed
    don't take the telescope."""
    verdicts = [w["verdict"] for w in candidate_weights]
    if "now" in verdicts:
        return True, "a strong candidate: it goes first, outside the allowance"
    if "allowance" not in verdicts:
        why = next((w["why"] for w in candidate_weights if w["verdict"] == "wait"), None)
        return False, why or "nothing open worth another look"
    store = load(path)
    return allowance_left(store["allowance"].get(evening_key(now), 0.0), night_seconds, share(cfg))


def allowance_left(used, night_seconds, follow_up_share):
    """(go?, why) for an uncertain candidate's second look with `used`
    seconds of the night's follow-up allowance gone: the patrol and
    nightreplay.py both ask this."""
    allowed = follow_up_share * night_seconds
    if used + LOOK_S > allowed:
        return False, (f"the night's follow-up allowance is spent ({used / 60:.0f} of {allowed / 60:.0f} minutes); "
                       "it goes first on the next clear night")
    return True, f"uncertain: {used / 60:.0f} of the night's {allowed / 60:.0f} follow-up minutes used before it"


def spend(seconds, now=None, path=None):
    store = load(path)
    key = evening_key(now)
    store["allowance"][key] = round(store["allowance"].get(key, 0.0) + seconds, 1)
    save(store, path)


def words(store):
    lines = []
    for o in open_ones(store):
        lines.append(f"{o['what']}: {o['why']}; until {o['until']}"
                     + (f" ({o['weighed']['verdict']}: {o['weighed']['why']})" if o.get("weighed") else ""))
    return lines or ["Nothing owed."]


def run(args, say=print):
    store = refresh()
    for line in words(store):
        say(line)
    return {"obligations": open_ones(store), "allowance": store["allowance"]}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("obligations", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
