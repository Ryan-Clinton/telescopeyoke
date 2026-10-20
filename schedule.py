#!/usr/bin/env python3
"""Tonight's schedule: the agreed steps of a night, run in order, with when
each is expected to start and finish, for the console to show.

    ./schedule.py                         the schedule, with its times and progress
    ./schedule.py add "M31 panels" 60 -- ./patrol.py m31-panels
    ./schedule.py add "WASP-12 b" 250 --not-before 01:45 -- ./shoot.py WASP-12 --frames 0
    ./schedule.py add "Keep going" 0 --until 01:44 -- ./shoot.py {last} --frames 0
                                          more of whatever was imaged last, until then
    ./schedule.py wait "M31 novae" 30 PID  a step already running elsewhere, by its process id
    ./schedule.py run                     run the queued steps, one after the other
    ./schedule.py clear                   start a new schedule

Each step has a label, its expected minutes, a command, and maybe a time
not to start before; the times of the steps after a running one follow from
when it started. A step that fails stops the schedule and fetches the person
(alert.py call): nothing after it runs on a night that has gone wrong. Kept in
config.DATA/cache/schedule.json. 19 October 2026: the night's plan was a
script nobody could see, and the console said nothing between frames.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta

import activity
import config
import records

FILE = config.DATA / "cache" / "schedule.json"


def load():
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"steps": []}


def save(plan):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    records.write(FILE, plan)


def not_before(hhmm, now):
    """The next time it is `hhmm` (local), as unix seconds: tonight, or after
    midnight if that time has already gone today by more than twelve hours."""
    hour, minute = (int(v) for v in hhmm.split(":"))
    moment = datetime.fromtimestamp(now).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if moment.timestamp() < now - 12 * 3600:
        moment += timedelta(days=1)
    return moment.timestamp()


def view(plan=None, now=None):
    """Each step with its expected start and finish (unix seconds), and its
    progress (0 to 1) while it runs, from how long it has been going."""
    plan = load() if plan is None else plan
    now = time.time() if now is None else now
    out, free = [], now
    for step in plan["steps"]:
        s = dict(step)
        minutes = 60 * s["minutes"]
        if s.get("status") in ("done", "failed", "skipped"):
            s["start"], s["end"] = s.get("started"), s.get("finished")
            s["progress"] = 1.0 if s["status"] == "done" else None
        elif s.get("status") == "running":
            s["start"] = s["started"]
            s["end"] = not_before(s["until"], s["started"]) if s.get("until") else max(s["started"] + minutes, now)
            minutes = max(s["end"] - s["started"], 1) if s.get("until") else minutes
            s["progress"] = round(min(0.99, (now - s["started"]) / minutes), 3) if minutes else None
        else:
            start = max(free, not_before(s["not_before"], now) if s.get("not_before") else free)
            end = max(start, not_before(s["until"], now)) if s.get("until") else start + minutes
            s["start"], s["end"], s["progress"] = start, end, 0.0
        free = s["end"] if s["end"] is not None else free
        out.append(s)
    return {"steps": out, "now": now}


def add(label, minutes, command, not_before_=None, pid=None, until=None):
    plan = load()
    plan["steps"].append({"label": label, "minutes": minutes, "command": command, "not_before": not_before_,
                          "until": until,
                          "pid": pid, "status": "running" if pid else "queued",
                          "started": time.time() if pid else None, "finished": None})
    save(plan)


def mark(index, **fields):
    plan = load()
    plan["steps"][index].update(fields)
    save(plan)


def alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True
    except (OSError, ValueError):
        return False


def run(say=print, sleep=time.sleep, call=None, start=subprocess.run):
    """The queued steps in order. A step given by process id is waited for;
    the rest are started here, each when the one before has ended and not
    before its time."""
    plan = load()
    for i, step in enumerate(plan["steps"]):
        if step["status"] == "running" and step.get("pid"):
            say(f"waiting for {step['label']} (process {step['pid']})")
            with activity.doing("Schedule", f"waiting for {step['label']} to finish, imaging and its search"):
                while alive(step["pid"]):
                    sleep(20)
            mark(i, status="done", finished=time.time())
            continue
        if step["status"] != "queued":
            continue
        if step.get("not_before"):
            until = not_before(step["not_before"], time.time())
            while time.time() < until:
                sleep(min(60, until - time.time()))
        command = [c.replace("{last}", last_field() or "") for c in step["command"]]
        if step.get("until"):
            # More of whatever was imaged last, to fill the time before a
            # step that keeps to the clock (20 October 2026: the panels
            # ran early, and the frames all go into the panel's stack).
            left = round(not_before(step["until"], time.time()) - time.time())
            if left < 120 or not last_field():
                mark(i, status="skipped", started=time.time(), finished=time.time())
                say(f"{datetime.now():%H:%M} {step['label']}: skipped, {max(left, 0)} s left")
                continue
            command = ["timeout", "--signal=INT", str(left)] + command
        say(f"{datetime.now():%H:%M} starting {step['label']}")
        mark(i, status="running", started=time.time())
        with activity.doing("Schedule", step["label"], i + 1, len(plan["steps"])):
            done = start(command)
        # Stopped at its time by timeout is how a step with an end time ends.
        ok = done.returncode == 0 or (step.get("until") and done.returncode == 124)
        mark(i, status="done" if ok else "failed", finished=time.time(), exit=done.returncode)
        say(f"{datetime.now():%H:%M} {step['label']} {'done' if ok else f'failed (exit {done.returncode})'}")
        if not ok:
            (call or fetch)(f"The telescope needs you: {step['label']} stopped with an error.")
            return False
    return True


def last_field():
    """The field imaged most recently: the folder of the newest session."""
    sessions = [d for d in (config.DATA / "frames").glob("*/2*") if d.is_dir()]
    return max(sessions, key=lambda d: d.stat().st_mtime).parent.name if sessions else None


def fetch(words):
    subprocess.run([sys.executable, str(config.ROOT / "alert.py"), "call", words])


def show(say=print):
    for s in view()["steps"]:
        when = lambda t: datetime.fromtimestamp(t).strftime("%H:%M") if t else "--:--"
        done = "" if s["progress"] is None else f" {round(100 * s['progress'])}%"
        say(f"{when(s['start'])}-{when(s['end'])}  {s['status']:8}{done:>5}  {s['label']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="action")
    a = sub.add_parser("add")
    a.add_argument("label")
    a.add_argument("minutes", type=float)
    a.add_argument("--not-before", metavar="HH:MM")
    a.add_argument("--until", metavar="HH:MM", help="end the step then, whatever it is doing")
    a.add_argument("command", nargs=argparse.REMAINDER)
    w = sub.add_parser("wait")
    w.add_argument("label")
    w.add_argument("minutes", type=float)
    w.add_argument("pid", type=int)
    sub.add_parser("run")
    sub.add_parser("clear")
    args = ap.parse_args(argv)
    if args.action == "add":
        # Everything after "--" is the command; an option given after the
        # minutes lands in front of it, since the command takes the rest.
        rest = list(args.command)
        before, command = (rest[:rest.index("--")], rest[rest.index("--") + 1:]) if "--" in rest else ([], rest)
        if "--not-before" in before:
            args.not_before = before[before.index("--not-before") + 1]
        if "--until" in before:
            args.until = before[before.index("--until") + 1]
        if not command:
            ap.error("add needs the command after --")
        add(args.label, args.minutes, command, args.not_before, until=args.until)
    elif args.action == "wait":
        add(args.label, args.minutes, None, pid=args.pid)
    elif args.action == "run":
        sys.exit(0 if run() else 1)
    elif args.action == "clear":
        save({"steps": [], "made": time.time()})
    show()


if __name__ == "__main__":
    main()
