#!/usr/bin/env python3
"""Choose the next of tonight's agreed steps at each step's end
(docs/observing-plan-spec.md, Phase 4).

    ./dispatch.py           what would go next now, and why, from tonight's schedule
    ./dispatch.py --json

The schedule's list is the plan's first guess, shown and changeable as
ever. With [plan] dispatch on, the runner asks this module at each step's
end which queued step is best now. It chooses only among the steps the
person agreed to tonight, never adds one, and moves nothing itself. By
scientific opportunity, in this order:

1. what is owed and near its expiry (obligations.py), by its expiry;
2. the target that sets soonest, when waiting would lose it (a look ahead
   over the measured skyline and the house, from sky.Night);
3. the field longest unsearched to a useful depth (a neglected field
   gains most coverage);
4. on a tie, staying on the same target (no hopping), then the listed order.

Steps that are not up now wait for their turn. Protected steps and the
cutoff before them are Phase 3's (windows.py), which this hands its order
to. Every choice is kept, with its reasons, in cache/dispatch.jsonl, so it
can be explained and replayed.
"""
import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import config
import interface

LOG = config.DATA / "cache" / "dispatch.jsonl"
OWED_SOON_DAYS = 2.0      # an obligation this near its expiry goes first
LOOK_AHEAD = 1.5          # a target setting within this many times its step's minutes is urgent
NEGLECT_CAP_DAYS = 10.0   # patrol.DEBT_DAYS: unwatched longer counts as this long
STEP_S = 60               # seconds between visibility samples


def command_names(step):
    return [Path(c).name if c.endswith(".py") else c for c in step.get("command", [])]


def what(step):
    """(target name for the mount or None, [field folder names], programme)
    a step images, from its command."""
    import stacking
    cmd = command_names(step)
    if not cmd:
        return None, [], None
    if cmd[0] in ("patrol.py", "starwatch.py") and len(cmd) > 1:
        import patrol
        name = cmd[1]
        if (patrol.PROGRAMMES / f"{name}.toml").exists():
            p = patrol.programme(name)
            if p.get("mosaic"):
                return p["mosaic"], [f"{p['mosaic']}-P{n}" for n in range(1, 9)], name
            return p["target"], [stacking.folder_name(p["target"])], name
        return name, [stacking.folder_name(name)], None
    if cmd[0] == "shoot.py" and len(cmd) > 1:
        return cmd[1], [stacking.folder_name(cmd[1])], None
    return None, [], None


class Sky:
    """When each target is up tonight, above the measured skyline and the
    house: sky.Night's samples, looked up by target."""

    def __init__(self, cfg=None, now=None):
        import sky
        import goals
        self.cfg = cfg or goals.plan_config()
        self.night = sky.Night(self.cfg, now=datetime.fromtimestamp(now or time.time()).astimezone())
        self.cache = {}

    def up(self, target):
        """(unix times, above-the-limit mask) for a target, or None if it
        can't be found."""
        if target in self.cache:
            return self.cache[target]
        import mount
        try:
            t = mount.find_target(target)
        except (Exception, interface.Refusal):     # a Refusal is a SystemExit: named, so it is caught
            t = None
        if not t:
            self.cache[target] = None
            return None
        alt, az = self.night.altaz_fixed([t["ra"]], [t["dec"]])
        limit = self.night.horizon(az[0], self.night.min_alt)
        self.cache[target] = (self.night.unix, alt[0] > limit)
        return self.cache[target]

    def window(self, target, now):
        """(up now?, seconds before it sinks below the skyline, or None if
        it stays up until dawn or can't be told). Dawn ends every target
        alike, so it makes none urgent: on the replay of 3 to 4 November
        2026, counting it moved the supernova before the panels, and the
        panels lost two searchable visits to the night's end."""
        found = self.up(target)
        dark = self.night.dark
        unix = self.night.unix
        i = int(min(max(0, (now - unix[0]) // (unix[1] - unix[0])), len(unix) - 1))
        if found is None:
            return bool(dark[i]), None
        _, above = found
        if not (above[i] and dark[i]):
            return False, None
        j = i
        while j + 1 < len(above) and above[j + 1] and dark[j + 1]:
            j += 1
        if j + 1 < len(above) and not dark[j + 1]:
            return True, None            # up until dawn
        return True, float(unix[j] - now)

    def rises_in(self, target, now):
        """Seconds until a target that is down now comes up above the
        skyline in darkness tonight, or None if it doesn't before dawn (or
        can't be told)."""
        found = self.up(target)
        if found is None:
            return None
        _, above = found
        unix, dark = self.night.unix, self.night.dark
        i = int(min(max(0, (now - unix[0]) // (unix[1] - unix[0])), len(unix) - 1))
        for j in range(i, len(unix)):
            if above[j] and dark[j]:
                return max(0.0, float(unix[j] - now))
        return None


def neglect(fields, data=None, now=None):
    """Days since the most neglected of these fields was last searched to a
    useful depth (outcome worth it), capped; NEGLECT_CAP_DAYS when never.
    A mosaic's step gains most from its most neglected panel."""
    return max((field_neglect(f, data, now) for f in fields), default=0.0)


def field_neglect(field, data=None, now=None):
    data = data or config.DATA
    now = now or time.time()
    best = None
    for field in [field]:
        for folder in (data / "frames" / field).glob("*/"):
            try:
                r = json.loads((folder / "outcome.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if r.get("worth_it") == "met":
                try:
                    when = datetime.strptime(folder.name[:15], "%Y%m%d-%H%M%S").timestamp()
                except ValueError:
                    continue
                if when > now:
                    continue        # a replay at an earlier moment does not know it yet
                best = when if best is None else max(best, when)
    if best is None:
        return NEGLECT_CAP_DAYS
    return min(NEGLECT_CAP_DAYS, max(0.0, (now - best) / 86400))


def owed_on(fields, owed, today):
    """(days to the nearest expiry, strongest verdict) of the open
    obligations on these fields that need the telescope; (None, None) if none."""
    from datetime import date
    days, verdict = None, None
    for o in owed:
        if o["field"] not in fields or o.get("telescope") is False:
            continue
        left = (date.fromisoformat(o["until"]) - today).days
        days = left if days is None else min(days, left)
        v = (o.get("weighed") or {}).get("verdict")
        if v == "now" or verdict is None:
            verdict = v or verdict
    return days, verdict


def rank(items, now, last_target=None):
    """The items in the order to try them, each with its reasons. Each item:
    {index, label, target, minutes, up, stays_s, owed_days, owed_verdict,
    neglect_days}. Not up now: last, in listed order."""
    def key(it):
        owed = it["owed_days"] is not None and (it["owed_days"] <= OWED_SOON_DAYS or it["owed_verdict"] == "now")
        urgent = it["stays_s"] is not None and it["stays_s"] < LOOK_AHEAD * 60 * it["minutes"]
        return (not it["up"],
                0 if owed else 1, it["owed_days"] if owed else 0,
                0 if urgent else 1, (it["stays_s"] or 0) if urgent else 0,
                -round(it["neglect_days"]),
                0 if (last_target and it["target"] == last_target) else 1,
                it["index"])
    out = sorted(items, key=key)
    for it in out:
        why = []
        if not it["up"]:
            why.append("not up now")
        if it["owed_days"] is not None:
            why.append(f"owed, {it['owed_days']} days to expiry" + (f" ({it['owed_verdict']})" if it["owed_verdict"]
                                                                    else ""))
        if it["stays_s"] is not None:
            why.append(f"up {it['stays_s'] / 60:.0f} more minutes")
        why.append(f"{it['neglect_days']:.0f} days since searched to a useful depth")
        it["why"] = "; ".join(why)
    return out


def items_for(steps, now, sky=None, owed=None, data=None, today=None):
    """The queued steps as rank()'s items."""
    from datetime import date
    today = today or date.fromtimestamp(now)
    owed = owed or []
    out = []
    for i, s in enumerate(steps):
        if s.get("status") not in (None, "queued"):
            continue
        target, fields, _ = what(s)
        up, stays = sky.window(target, now) if (sky and target) else (True, None)
        days, verdict = owed_on(fields, owed, today)
        out.append({"index": i, "label": s["label"], "id": s.get("id", s["label"]), "target": target,
                    "minutes": float(s["minutes"]), "up": up, "stays_s": stays, "owed_days": days,
                    "owed_verdict": verdict, "neglect_days": neglect(fields, data, now) if fields else 0.0})
    return out


def choose(steps, now=None, sky=None, owed=None, costs=None, last_target=None, keep=True, data=None, when=None):
    """(step, until, wait, ranked): the queued step to run now, as
    windows.choose returns it, with the order it was offered in. Only a
    step whose target is up is offered: with none up, no step, and `wait`
    the seconds until the first queued target rises or a protected step's
    setup is due, whichever is sooner (None if neither comes before dawn:
    the steps stay queued and the runner says so). A protected step is
    windows.choose's to start when its time comes, up or not: the mount's
    own limits still refuse a target below them."""
    import windows
    now = now or time.time()
    ranked = rank(items_for(steps, now, sky, owed, data), now, last_target)
    by_index = {i: s for i, s in enumerate(steps)}
    order = [by_index[it["index"]] for it in ranked if it["up"]]
    step, until, wait = windows.choose(steps, now, costs, when, among=order)
    if step is None and sky is not None:
        rises = [sky.rises_in(it["target"], now) for it in ranked if not it["up"] and it["target"]]
        rises = [r for r in rises if r is not None]
        waits = [w for w in (wait, min(rises) if rises else None) if w is not None]
        wait = min(waits) if waits else None
    if keep and step is not None:
        try:
            LOG.parent.mkdir(parents=True, exist_ok=True)
            with LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"at": round(now), "chose": step.get("id", step["label"]), "until": until,
                                    "offered": [{"step": it["id"], "why": it["why"]} for it in ranked]}) + "\n")
        except OSError:
            pass
    return step, until, wait, ranked


def last_target_of(steps):
    done = [s for s in steps if s.get("status") in ("done", "failed") and s.get("finished")]
    if not done:
        return None
    return what(max(done, key=lambda s: s["finished"]))[0]


def run(args, say=print):
    import obligations
    import schedule
    import windows
    plan = schedule.load()
    now = time.time()
    store = obligations.refresh()
    step, until, wait, ranked = choose(plan["steps"], now, Sky(), obligations.open_ones(store),
                                       windows.costs(), last_target_of(plan["steps"]), keep=False)
    if step is None:
        say("Nothing to start now" + (f": the next protected step's setup begins in {wait / 60:.0f} minutes"
                                     if wait else ": nothing queued"))
    else:
        say(f"Next: {step['label']}" + (f", until {time.strftime('%H:%M', time.localtime(until))} "
                                        "(the next protected start, less its setup)" if until else ""))
    for it in ranked:
        say(f"  {it['label']}: {it['why']}")
    return {"next": step and step.get("id", step["label"]), "until": until, "wait_s": wait,
            "offered": [{"step": it["id"], "label": it["label"], "why": it["why"]} for it in ranked]}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("dispatch", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
