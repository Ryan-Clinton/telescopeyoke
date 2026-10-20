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
    ./schedule.py end                     the night is over: park the mount and tell the person
    ./schedule.py guard                   the same, if a night's imaging has stopped and it is morning
    ./schedule.py guard --install         run the guard every 10 minutes (a systemd user timer)

Each step has a label, its expected minutes, a command, and maybe a time
not to start before; the times of the steps after a running one follow from
when it started. A step that fails stops the schedule and fetches the person
(alert.py call): nothing after it runs on a night that has gone wrong. Kept in
config.DATA/cache/schedule.json. 19 October 2026: the night's plan was a
script nobody could see, and the console said nothing between frames.

When the last step has run in the morning (MORNING), the night is over:
the mount goes home and the person is told on their phone what the night
got and that it is parked (`end`); a schedule that finishes earlier only
says so, as the person may be out at the scope. A night can also end
outside the schedule (cloud, a camera that hangs, runs restarted by hand),
so `guard`, every 10 minutes from a timer, does the same once it is
morning, the night has imaged, nothing has been kept for IDLE_MINUTES,
nothing that drives the mount or camera is running, and the mount has
been tracking without being moved between two of its looks (STILL), so
nobody is at it with the handset. 20 October 2026:
the night ended at 05:28 in cloud, outside the schedule, and the mount
tracked on, unparked and unsaid, until the person came down. The person
asked for this; it moves the mount only home, through mount.py and its
motion lock, and only once a night.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import activity
import config
import records

FILE = config.DATA / "cache" / "schedule.json"
RUNNER = config.DATA / "cache" / "schedule.runner"     # the process id of `schedule.py run` while it runs
ENDED = config.DATA / "cache" / "night.ended"          # when a night was last ended (parked and told)
MORNING = (3, 9)           # local hours in which a night may be ended: after it, the person may be at the scope
IDLE_MINUTES = 30          # guard: no frame kept for this long
NIGHT_HOURS = 16           # a night's sessions: those begun within this many hours
IMAGING = ("shoot.py", "patrol.py", "starwatch.py", "focus.py", "focuser.py", "polaralign.py", "camera_setup.py",
           "mount.py", "direct.py", "console.py", "app.py", "planet.py", "skywatch.py", "snap.py", "tour.py")
TY_MOVING = ("shoot", "mount", "focus", "run", "polar-align", "goto")   # `ty` commands that drive the mount or camera
LOOKED = config.DATA / "cache" / "night.looked"        # guard: the mount's place at its last look
STILL = (0.02, 0.2, 15 * 60)   # guard: hours of RA, degrees of Dec, and seconds apart for "not moved between looks"


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
    try:
        runner = alive(int(RUNNER.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        runner = False
    return {"steps": out, "now": now, "runner": runner}


def add(label, minutes, command, not_before_=None, pid=None, until=None):
    plan = load()
    taken = {s.get("id", s["label"]) for s in plan["steps"]}
    step_id = label if label not in taken else f"{label} ({len(taken) + 1})"
    plan["steps"].append({"id": step_id, "label": label, "minutes": minutes, "command": command,
                          "not_before": not_before_,
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
    before its time. The plan is read again before every step and each step
    found by its id, so steps can be added, moved or dropped while it runs
    (20 October 2026: a step added mid-night needed the runner restarting,
    since it worked from the plan it had read at the start, by position)."""
    try:
        RUNNER.parent.mkdir(parents=True, exist_ok=True)
        RUNNER.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass
    ran = False
    while True:
        plan = load()
        steps = plan["steps"]
        for step in steps:
            step.setdefault("id", step["label"])
        waiting = next((s for s in steps if s["status"] == "running" and s.get("pid")), None)
        step = waiting or next((s for s in steps if s["status"] == "queued"), None)
        if step is None:
            if ran:
                if MORNING[0] <= datetime.now().hour < MORNING[1] and not busy():
                    end(say=say)
                else:
                    import notify
                    notify.send(f"Tonight's schedule finished at {datetime.now():%H:%M}. The telescope is still where "
                                "it was; it will be parked in the morning if nothing else runs.", say=say)
            return True
        number = steps.index(step) + 1
        if waiting:
            say(f"waiting for {step['label']} (process {step['pid']})")
            with activity.doing("Schedule", f"waiting for {step['label']} to finish, imaging and its search"):
                while alive(step["pid"]):
                    sleep(20)
            mark_id(step["id"], status="done", finished=time.time())
            continue
        if step.get("not_before"):
            until = not_before(step["not_before"], time.time())
            if time.time() < until:
                # A minute at a time, then the plan again: it may have changed.
                sleep(min(60, until - time.time()))
                continue
        command = [c.replace("{last}", last_field() or "") for c in step["command"]]
        if step.get("until"):
            # More of whatever was imaged last, to fill the time before a
            # step that keeps to the clock (20 October 2026: the panels
            # ran early, and the frames all go into the panel's stack).
            left = round(not_before(step["until"], time.time()) - time.time())
            if left < 120 or not last_field():
                mark_id(step["id"], status="skipped", started=time.time(), finished=time.time())
                say(f"{datetime.now():%H:%M} {step['label']}: skipped, {max(left, 0)} s left")
                continue
            command = ["timeout", "--signal=INT", str(left)] + command
        say(f"{datetime.now():%H:%M} starting {step['label']}")
        ran = True
        mark_id(step["id"], status="running", started=time.time())
        with activity.doing("Schedule", step["label"], number, len(steps)):
            try:
                done = start(command)
            except Exception as error:
                # A step that cannot even start is a failed step, not the end
                # of the runner: on 20 October 2026 a command cut wrongly
                # stopped the night at 01:45 with nobody told.
                say(f"{datetime.now():%H:%M} {step['label']} could not start: {error}")
                done = subprocess.CompletedProcess(command, 127)
        # Stopped at its time by timeout is how a step with an end time ends.
        ok = done.returncode == 0 or (step.get("until") and done.returncode == 124)
        mark_id(step["id"], status="done" if ok else "failed", finished=time.time(), exit=done.returncode)
        say(f"{datetime.now():%H:%M} {step['label']} {'done' if ok else f'failed (exit {done.returncode})'}")
        if not ok:
            (call or fetch)(f"The telescope needs you: {step['label']} stopped with an error.")
            return False


def tonight(now=None, hours=NIGHT_HOURS):
    """The night's sessions: [(field, frames kept, newest frame's time)]."""
    now = now or time.time()
    out = []
    for d in sorted((config.DATA / "frames").glob("*/2*")):
        try:
            begun = datetime.strptime(d.name[:15], "%Y%m%d-%H%M%S").timestamp()
        except ValueError:
            continue
        if now - begun > hours * 3600 or not d.is_dir():
            continue
        frames = list(d.glob("light-*.fits"))
        newest = max((f.stat().st_mtime for f in frames), default=begun)
        out.append((d.parent.name, len(frames), newest))
    return out


def summary(sessions):
    """What the night got, in one line: frames kept by field."""
    fields = {}
    for field, frames, _ in sessions:
        fields[field] = fields.get(field, 0) + frames
    return ", ".join(f"{field} {n} frames" for field, n in fields.items()) or "no frames kept"


def mount_state(run=subprocess.run):
    """The mount's status (mount.py status --json's data), or None if it
    did not answer properly: a refusal (handset not answering or not set
    up, port busy) is no answer, never "not at home"."""
    try:
        done = run([sys.executable, str(config.ROOT / "mount.py"), "status", "--json"], capture_output=True,
                   text=True, timeout=60)
        reply = json.loads(done.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    data = reply.get("data") if isinstance(reply, dict) else None
    if not reply.get("ok", True) or not isinstance(data, dict) or "at_home" not in data:
        return None
    return data


def go_home(home=None, wait=600):
    """mount.py home, stopped with Ctrl-C (so mount.py stops the motors
    itself) if it has not finished in `wait` seconds."""
    if home:
        return home()
    proc = subprocess.Popen([sys.executable, str(config.ROOT / "mount.py"), "home"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        proc.wait(timeout=wait)
    except subprocess.TimeoutExpired:
        import signal
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()


def end(say=print, send=None, run=subprocess.run, now=None, home=None):
    """The night is over: send the mount home (mount.py, so its motion lock
    and checks hold), check it got there, and tell the person on their
    phone. Returns whether it is parked."""
    import notify
    send = send or notify.send
    now = now or time.time()
    sessions = tonight(now)
    got = summary(sessions)
    try:
        # Written before any move, so a move that goes wrong is never tried again by the guard.
        ENDED.parent.mkdir(parents=True, exist_ok=True)
        ENDED.write_text(str(now), encoding="utf-8")
    except OSError:
        pass
    state = mount_state(run)
    if state is None:
        words = f"Observation is over. Tonight: {got}. The mount did not answer, so it may not be parked: please check it."
        parked = False
    else:
        if not state.get("at_home"):
            go_home(home)
            state = mount_state(run) or {}
        parked = bool(state.get("at_home"))
        words = (f"Observation is over. Tonight: {got}. The telescope is parked at home (by its axis readouts)."
                 if parked else
                 f"Observation is over. Tonight: {got}. The telescope could NOT be parked: it is still "
                 f"{state.get('state', 'where it was')}. Please check it.")
    say(words)
    send(words, say=say)
    return parked


def driving(line, names=IMAGING, ty=TY_MOVING):
    """Whether a command line runs a script that drives the mount or camera:
    by name anywhere in it (`timeout --signal=INT N ./shoot.py`), or as
    `ty shoot`, `ty mount` and the like."""
    words = [Path(w).name for w in line]
    return any(w in names for w in words) or any(a == "ty" and b in ty for a, b in zip(words, words[1:]))


def busy():
    """A process driving the mount or camera, by its command line."""
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            line = [w.decode(errors="replace") for w in (proc / "cmdline").read_bytes().split(b"\0") if w]
        except OSError:
            continue
        if driving(line):
            return True
    return False


def unmoved(state, now):
    """Whether the mount is tracking where it was at the guard's last look
    (within STILL): nobody is moving it with the handset or a program.
    Remembers this look."""
    last = None
    try:
        last = json.loads(LOOKED.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    try:
        LOOKED.parent.mkdir(parents=True, exist_ok=True)
        LOOKED.write_text(json.dumps({"time": now, "ra": state.get("ra_hours"), "dec": state.get("dec_deg")}),
                          encoding="utf-8")
    except OSError:
        pass
    if not last or state.get("state") != "tracking" or None in (last.get("ra"), state.get("ra_hours")):
        return False
    gap = now - last.get("time", 0)
    ra = abs(state["ra_hours"] - last["ra"]) % 24
    return 0 < gap <= STILL[2] and min(ra, 24 - ra) <= STILL[0] and abs(state["dec_deg"] - last["dec"]) <= STILL[1]


def guard(say=print, send=None, run=subprocess.run, now=None, running=None):
    """End the night (`end`) if it is over and nobody has: morning, the
    night has imaged, nothing kept for IDLE_MINUTES, the schedule not
    running, nothing driving the mount or camera, this night not already
    ended, and the mount tracking unmoved since the last look. Returns why
    it did nothing, or "ended"."""
    now = now or time.time()
    hour = datetime.fromtimestamp(now).hour
    if not MORNING[0] <= hour < MORNING[1]:
        return "not morning"
    sessions = tonight(now)
    if not sessions:
        return "nothing imaged tonight"
    if now - max(s[2] for s in sessions) < IDLE_MINUTES * 60:
        return "still imaging"
    try:
        if now - float(ENDED.read_text(encoding="utf-8")) < NIGHT_HOURS * 3600:
            return "already ended"
    except (OSError, ValueError):
        pass
    try:
        if alive(RUNNER.read_text(encoding="utf-8").strip()):
            return "the schedule is running"
    except OSError:
        pass
    if (running or busy)():
        return "something is driving the mount or camera"
    state = mount_state(run)
    if state is None:
        return "the mount did not answer"
    if state.get("at_home"):
        return "already at home"
    if not unmoved(state, now):
        return "not yet seen tracking unmoved"
    end(say=say, send=send, run=run, now=now)
    return "ended"


def install(say=print, run=subprocess.run, home=None):
    """The guard every 10 minutes, as a systemd user timer, from this
    checkout: the real one, whose motion lock and frames are the night's."""
    root = config.ROOT
    if Path(config.DATA).resolve() != Path(root).resolve() or (Path(root) / ".git").is_file():
        import interface
        raise interface.Refusal("INVALID_REQUEST", "Install the guard from the telescope's own checkout, where its "
                                "frames and motion lock are, not from a copy, a worktree or with TY_DATA set.")
    place = Path(home or Path.home()) / ".config" / "systemd" / "user"
    place.mkdir(parents=True, exist_ok=True)
    (place / "ty-night-end.service").write_text(
        "[Unit]\nDescription=telescopeyoke: park and say so when the night is over\n\n"
        f"[Service]\nType=oneshot\nWorkingDirectory={root}\n"
        f"ExecStart={sys.executable} {root / 'schedule.py'} guard\n", encoding="utf-8")
    (place / "ty-night-end.timer").write_text(
        "[Unit]\nDescription=telescopeyoke: check every 10 minutes whether the night is over\n\n"
        "[Timer]\nOnBootSec=10min\nOnUnitActiveSec=10min\n\n[Install]\nWantedBy=timers.target\n",
        encoding="utf-8")
    run(["systemctl", "--user", "daemon-reload"], check=True)
    run(["systemctl", "--user", "enable", "--now", "ty-night-end.timer"], check=True)
    say(f"The night-end guard runs every 10 minutes ({place / 'ty-night-end.timer'}). "
        "Stop it: systemctl --user disable --now ty-night-end.timer")


def mark_id(step_id, **fields):
    plan = load()
    for step in plan["steps"]:
        if step.get("id", step["label"]) == step_id:
            step.update(fields)
    save(plan)


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
    sub.add_parser("end")
    g = sub.add_parser("guard")
    g.add_argument("--install", action="store_true", help="run it every 10 minutes as a systemd user timer")
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
    elif args.action == "end":
        sys.exit(0 if end() else 1)
    elif args.action == "guard":
        if args.install:
            install()
        else:
            print(guard(say=lambda *_: None))
        return
    show()


if __name__ == "__main__":
    main()
