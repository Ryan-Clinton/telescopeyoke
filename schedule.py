#!/usr/bin/env python3
"""Tonight's schedule: the agreed steps of a night, run in order, with when
each is expected to start and finish, for the console to show.

    ./schedule.py                         the schedule, with its times and progress
    ./schedule.py add "M31 panels" 60 -- ./patrol.py m31-panels
    ./schedule.py add "WASP-12 b" 250 --not-before 01:45 -- ./shoot.py WASP-12 --frames 0
    ./schedule.py add "Keep going" 0 --until 01:44 -- ./shoot.py {last} --frames 0
                                          more of whatever was imaged last, until then
    ./schedule.py add "M42 LRGB" 60 --filters L:10,R:5,G:5,B:5 -- ./shoot.py M42
                                          one step per filter (a light path with the wheel)
    ./schedule.py wait "M31 novae" 30 PID  a step already running elsewhere, by its process id
    ./schedule.py run                     run the queued steps, one after the other
    ./schedule.py fill                    what from tonight's discovery list fills the first gap
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
import functools
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import activity
import config
import interface
import records
import storage

FILE = config.DATA / "cache" / "schedule.json"
RUNNER = config.DATA / "cache" / "schedule.runner"     # the process id of `schedule.py run` while it runs
ENDED = config.DATA / "cache" / "night.ended"          # when a night was last ended (parked and told)
MORNING = (3, 9)           # local hours in which a night may be ended: after it, the person may be at the scope
IDLE_MINUTES = 30          # guard: no frame kept for this long
NIGHT_HOURS = 16           # a night's sessions: those begun within this many hours
IMAGING = ("shoot.py", "patrol.py", "starwatch.py", "focus.py", "focuser.py", "polaralign.py", "camera_setup.py",
           "mount.py", "direct.py", "console.py", "app.py", "planet.py", "skywatch.py", "snap.py", "tour.py",
           "guidecam.py", "mountprobe.py")
TY_MOVING = ("shoot", "mount", "focus", "run", "polar-align", "goto")   # `ty` commands that drive the mount or camera
LOOKED = config.DATA / "cache" / "night.looked"        # guard: the mount's place at its last look
STILL = (0.02, 0.2, 15 * 60)   # guard: hours of RA, degrees of Dec, and seconds apart for "not moved between looks"


def load():
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"steps": []}


NIGHTS = config.DATA / "cache" / "schedules"   # each night's plan, kept for replaying it (nightreplay.py)


def save(plan):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    records.write(FILE, plan)
    # The night's copy, by the evening the plan was made: schedule.json is
    # cleared for the next night, and a replay needs the plan as it ran.
    if plan.get("steps"):
        made = plan.get("made") or time.time()
        evening = (datetime.fromtimestamp(made) - timedelta(hours=12)).date()
        records.write(NIGHTS / f"{evening.isoformat()}.json", plan)


SUN_SET = -0.833           # degrees: the Sun's centre at sunset, refraction and its radius allowed for


def _site():
    return (config.load() if config.FILE.exists() and not config.DEMO else config.example())["site"]


def last_sunset(now, site=None):
    """When the Sun last set (unix seconds) if it is down at `now`, or None
    while it is up. Looked for over the day before, five minutes at a time."""
    return _last_sunset(int(now // 300) * 300, json.dumps(site or _site(), sort_keys=True))


@functools.lru_cache(maxsize=32)
def _last_sunset(now, site_text):
    import numpy as np
    from astropy import units as u
    from astropy.coordinates import AltAz, EarthLocation, get_sun
    from astropy.time import Time
    site = json.loads(site_text)
    here = EarthLocation(lat=site["latitude"] * u.deg, lon=site["longitude"] * u.deg,
                         height=site.get("elevation_m", 0) * u.m)
    stamps = now - np.arange(0, 86400 + 1, 300)[::-1]
    times = Time(stamps, format="unix")
    alt = get_sun(times).transform_to(AltAz(obstime=times, location=here)).alt.deg
    if alt[-1] > SUN_SET:
        return None
    up = np.nonzero(alt > SUN_SET)[0]
    return float(stamps[up[-1] + 1]) if len(up) else float(stamps[0])


def not_before(when, now, sunset=last_sunset):
    """A step's clock time as unix seconds. "YYYY-MM-DD HH:MM" is that
    moment. "HH:MM" belongs to the observing night: in darkness, the night
    began at the last sunset, so a time gone since then is tonight's and
    already past (the step goes at once), and any other is the next time it
    comes (07:05 at 19:05 is tomorrow's dawn); in daylight it is the next
    time it comes, for the night ahead.
    2 November 2026: a dawn flat at 07:05, added at 19:05, was put at 07:05
    that morning by the old rule (gone by more than twelve hours means
    tomorrow), and a 22:10 asked for at 01:00 would have waited 21 hours."""
    when = when.strip()
    if " " in when or "T" in when:
        return datetime.fromisoformat(when.replace(" ", "T")).timestamp()
    hour, minute = (int(v) for v in when.split(":"))
    began = sunset(now)
    anchor = now if began is None else began
    moment = datetime.fromtimestamp(anchor).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if moment.timestamp() < anchor:
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


def due(plan=None, now=None):
    """The label of the next queued step when the step running now has used
    its planned minutes, else None. Extra work a run adds by itself (a
    patrol's second looks) gives way to it: on 4 November 2026 the M31
    panels' second looks ran 54 minutes past their 45 and left the supernova
    after them 27 of its 90."""
    plan = load() if plan is None else plan
    now = time.time() if now is None else now
    steps = plan.get("steps", [])
    running = next((s for s in steps if s.get("status") == "running"), None)
    if running is None or not running.get("started"):
        return None
    end = not_before(running["until"], running["started"]) if running.get("until") \
        else running["started"] + 60 * running["minutes"]
    if now < end:
        return None
    queued = next((s for s in steps if s.get("status") in (None, "queued")), None)
    return queued["label"] if queued else None


def add(label, minutes, command, not_before_=None, pid=None, until=None, protect=None, deadline=None,
        uncertainty=None):
    """A step at the end of tonight's plan. `protect` ("hard" for an
    occultation, a transit or an urgent transient), `deadline` and
    `uncertainty` (minutes before the start the event may come) are Phase
    3's (windows.py), used with [plan] windows on."""
    plan = load()
    taken = {s.get("id", s["label"]) for s in plan["steps"]}
    step_id = label if label not in taken else f"{label} ({len(taken) + 1})"
    step = {"id": step_id, "label": label, "minutes": minutes, "command": command,
            "not_before": not_before_,
            "until": until,
            "pid": pid, "status": "running" if pid else "queued",
            "started": time.time() if pid else None, "finished": None}
    for key, value in (("protect", protect), ("deadline", deadline), ("uncertainty", uncertainty)):
        if value is not None:
            step[key] = value
    plan["steps"].append(step)
    save(plan)
    return step_id


def add_blocks(label, minutes, command, blocks_text, protect=None, **step):
    """A colour set as blocks, one step per filter ("L:10,R:5,G:5,B:5"):
    each the imaging command with --filter and --frames added, its minutes
    in proportion to its frames, so each block is a run, and a stack, of one
    filter (filters.py). A hard window (a transit, an occultation) keeps one
    filter for its whole time, so blocks are refused for it. Returns the
    steps' ids."""
    import filters
    if protect == "hard":
        raise interface.Refusal("INVALID_REQUEST", "A hard window (a transit, an occultation) is taken in one "
                                "filter for its whole time: give it one --filter in its command, not blocks.")
    if not any(Path(c).name == "shoot.py" for c in command[:2]):
        raise interface.Refusal("INVALID_REQUEST", "--filters splits an imaging run (./shoot.py TARGET ...) "
                                "into blocks; this command is not one.")
    if any(c in ("--filter", "--frames", "--accepted") for c in command):
        raise interface.Refusal("INVALID_REQUEST", "With --filters each block sets its own --filter and "
                                "--frames: leave them out of the command.")
    try:
        parts = filters.blocks(blocks_text)
    except ValueError as problem:
        raise interface.Refusal("INVALID_REQUEST", f"--filters {blocks_text}: {problem}") from None
    total = sum(n for _, n in parts)
    first = step.pop("not_before_", None)        # the set starts then; the blocks follow one another
    return [add(f"{label} {name}", round(minutes * n / total, 1),
                list(command) + ["--filter", name, "--frames", str(n)],
                not_before_=first if i == 0 else None, protect=protect, **step)
            for i, (name, n) in enumerate(parts)]


def find(ref, plan):
    """The index of a step by its number as the schedule shows it (1 is the
    first) or by its id; a refusal if there is none."""
    steps = plan["steps"]
    if str(ref).isdigit() and 1 <= int(ref) <= len(steps):
        return int(ref) - 1
    for i, step in enumerate(steps):
        if step.get("id", step["label"]) == ref or step["label"] == ref:
            return i
    raise interface.Refusal("INVALID_REQUEST", f"No step {ref} in tonight's schedule.")


def skip(ref):
    """A queued step left out, while the schedule runs: the runner reads the
    plan again before every step (1 November 2026: changing the plan meant
    stopping the runner and editing its file by hand)."""
    plan = load()
    i = find(ref, plan)
    if plan["steps"][i]["status"] != "queued":
        raise interface.Refusal("INVALID_REQUEST", f"Step {i + 1} is {plan['steps'][i]['status']}, not queued.")
    plan["steps"][i].update(status="skipped", finished=time.time())
    save(plan)
    return plan["steps"][i]["label"]


def move(ref, position):
    """A queued step moved to `position` (1 is the first), among the rest."""
    plan = load()
    i = find(ref, plan)
    if plan["steps"][i]["status"] != "queued":
        raise interface.Refusal("INVALID_REQUEST", f"Step {i + 1} is {plan['steps'][i]['status']}, not queued.")
    step = plan["steps"].pop(i)
    plan["steps"].insert(max(0, min(int(position) - 1, len(plan["steps"]))), step)
    save(plan)
    return step["label"]


def say_outcomes(step, say=print):
    """What the step's sessions got (outcome.py), a line or three each: not
    only that its time is up. A search still running in the background is
    said as pending. A help: a failure here never stops the night."""
    try:
        import outcome
        latest = load()
        found = next((s for s in latest.get("steps", []) if s.get("id") == step.get("id")), step)
        sessions = outcome.during(found.get("started") or time.time(), found.get("finished") or time.time())
        for session in sessions:
            for line in outcome.words(outcome.of_session(session)):
                say("    " + line)
    except Exception as problem:      # a report, never a reason to stop
        say(f"    outcome not said: {problem.__class__.__name__}: {problem}")


def next_step(tell=None):
    """End the step that is running now, gracefully: its run finishes after
    the frame it is taking, keeps its picture and search, and the schedule
    goes on to the next step."""
    import shoot
    return (tell or shoot.tell)("stop")


def mark(index, **fields):
    plan = load()
    plan["steps"][index].update(fields)
    save(plan)


def alive(pid):
    import host
    return host.alive(pid)


BACKSTOP_S = 240   # a step told its end time is stopped this long after it, whatever it is doing
                   # (was 900: on 2 November 2026 the M31 panels ran 10 minutes into the transit's time)
RETRIES = 2       # a failed step is started again this many times before the person is fetched
RETRY_S = 30      # seconds between


SOURCE = Path(__file__).resolve()


def choosing(cfg=None):
    """Whether the runner chooses its next step ([plan] windows or dispatch
    on) rather than taking the list in order."""
    import goals
    return goals.enabled("windows", cfg) or goals.enabled("dispatch", cfg)


def choose_step(steps, say=print, now=None, cfg=None, sky=None, owed=None, costs=None):
    """(step, cutoff, hold): the step to start now and the time it must end
    by (unix seconds, before a protected start), or no step and how long to
    hold before asking again. A help that must never stop the night: if
    choosing fails, the first queued step goes as before."""
    import goals
    import windows
    now = now or time.time()
    try:
        costs = windows.costs() if costs is None else costs
        if goals.enabled("dispatch", cfg):
            import dispatch
            import obligations
            if owed is None:
                owed = obligations.open_ones(obligations.refresh())
            if sky is None:
                try:
                    sky = dispatch.Sky(cfg, now)
                except Exception as problem:   # no sky: every target counts as up
                    say(f"{datetime.now():%H:%M} the sky not worked out ({problem.__class__.__name__}); "
                        "every target counts as up")
                    sky = None
            step, cut, hold, ranked = dispatch.choose(steps, now, sky, owed, costs, dispatch.last_target_of(steps))
            if step is not None:
                why = next((it["why"] for it in ranked if it["id"] == step.get("id", step["label"])), "")
                say(f"{datetime.now():%H:%M} chosen next: {step['label']} ({why})")
            elif hold is None and ranked:
                # Nothing it agreed to is up, and nothing rises before dawn:
                # said, and left queued, never started below the skyline.
                say(f"{datetime.now():%H:%M} none of tonight's queued steps is up above the measured skyline "
                    f"again before dawn ({', '.join(it['label'] for it in ranked)}); they stay queued")
            elif hold is not None:
                say(f"{datetime.now():%H:%M} nothing queued is up yet: waiting {hold / 60:.0f} minutes")
        else:
            step, cut, hold = windows.choose(steps, now, costs)
        if step is not None and cut is not None:
            say(f"{datetime.now():%H:%M} {step['label']}: ends by {datetime.fromtimestamp(cut):%H:%M}, before the "
                "next protected start and its setup")
        return step, cut, hold
    except Exception as problem:     # never a reason to stop the night
        say(f"{datetime.now():%H:%M} next step not chosen ({problem.__class__.__name__}: {problem}); "
            "taking the list in order")
        return next((s for s in steps if s.get("status") == "queued"), None), None, None


def owe_interrupted(step, code, say=print):
    """A hard window that failed is owed (Phase 4): an interrupted transit
    can't be repeated tonight, and is said so for the next chance."""
    import windows
    if windows.protection(step) != "hard":
        return
    try:
        import obligations
        from datetime import date, timedelta as days
        obligations.owe("interrupted", step["label"], f"{step['label']} again, at its next window",
                        f"its protected window ended with an error (exit {code})",
                        (date.today() + days(days=30)).isoformat(), ref=step.get("id", ""))
    except Exception as problem:     # a record, never a reason to stop
        say(f"    not recorded as owed: {problem.__class__.__name__}: {problem}")


def restart():
    """The runner started again in its own process, with the code on disk now."""
    os.execv(sys.executable, [sys.executable, str(SOURCE), "run"])


def prepared(step, now, last=None, sunset=last_sunset, cut=None):
    """(command, seconds left) for a queued step started at `now`, with
    `last` the field imaged last: the command as the runner starts it, told
    its time, or (None, seconds left) for a step to skip. The runner and
    nightreplay.py both start steps through this, so a replay keeps to the
    night's own rules (the Phase 5 audit, 4 November 2026). `cut` (unix
    seconds): a flexible step must end by then, before the next protected
    start and its setup (Phase 3, windows.py); it is told so as a step is
    told its end time."""
    command = [c.replace("{last}", last or "") for c in step["command"]]
    patrolling = any(Path(c).name == "patrol.py" for c in command[:2])
    left = None
    own = not_before(step["until"], now, sunset) if step.get("until") else None
    ends = [x for x in (own, cut) if x is not None]
    if patrolling and not ends and "--budget" not in command:
        # A patrol is told the step's minutes and takes the panels that fit
        # (4 November 2026: 8 panels in a 45-minute step ran 99 minutes).
        command = command + ["--budget", f"{step['minutes']:g}"]
        # The patrol keeps to it itself; this hard stop is a backstop only,
        # BACKSTOP_S after, as for a step with an end time.
        command = ["timeout", "--signal=INT", str(round(60 * step["minutes"]) + BACKSTOP_S)] + command
    if ends:
        # More of whatever was imaged last, to fill the time before a
        # step that keeps to the clock (20 October 2026: the panels
        # ran early, and the frames all go into the panel's stack).
        left = round(min(ends) - now)
        # Before a protected start the backstop must not run into its setup:
        # the step is told to end BACKSTOP_S early, so the hard stop falls on
        # the cutoff (the replay of 3 November found windows 209 s late by it).
        early = BACKSTOP_S if cut is not None and (own is None or cut < own) else 0
        if left - early < 120 or (own is not None and not last):
            return None, left
        if any(Path(c).name in ("shoot.py", "patrol.py") for c in command[:2]):
            # The run is told its time and finishes gracefully, picture and all;
            # the hard stop is a backstop only (1 November 2026: steps cut off
            # mid-picture, and private timers that stopped the wrong run).
            # A patrol's --minutes is each field's; its whole time is --budget.
            command = command + ["--budget" if patrolling else "--minutes", f"{(left - early) / 60:.1f}"]
            left += BACKSTOP_S - early
        command = ["timeout", "--signal=INT", str(left)] + command
    return command, left


def run(say=print, sleep=time.sleep, call=None, start=subprocess.run, reload=None):
    """The queued steps in order. A step given by process id is waited for;
    the rest are started here, each when the one before has ended and not
    before its time. The plan is read again before every step and each step
    found by its id, so steps can be added, moved or dropped while it runs
    (20 October 2026: a step added mid-night needed the runner restarting,
    since it worked from the plan it had read at the start, by position).
    With `reload` (restart() from the command line), a runner whose own
    code has changed on disk starts again with it between steps: on 2
    November 2026 a runner started at 02:03 ran M81 and SN 2026sqf with the
    code from before steps were told their time, and both were cut off
    unstacked."""
    try:
        RUNNER.parent.mkdir(parents=True, exist_ok=True)
        RUNNER.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass
    ran = False
    try:
        loaded = SOURCE.stat().st_mtime
    except OSError:
        loaded = None
    while True:
        if reload and loaded is not None:
            try:
                now_ = SOURCE.stat().st_mtime
            except OSError:
                now_ = loaded
            if now_ != loaded:
                say(f"{datetime.now():%H:%M} schedule.py has changed: starting again with the new code")
                reload()
                return True
        plan = load()
        steps = plan["steps"]
        for step in steps:
            step.setdefault("id", step["label"])
        # A session's own blocks (shoot.py --blocks) are waited on, never
        # started: the session marks them; its process gone, the rest are ended.
        for s in steps:
            if s.get("session") and s["status"] in ("queued", "running") and not alive(s["session"]):
                end_session(s["session"])
                plan = load()
                steps = plan["steps"]
                break
        waiting = next((s for s in steps if s["status"] == "running" and s.get("pid")), None) or next(
            (s for s in steps if s.get("session") and s["status"] == "queued"), None)
        step = waiting or next((s for s in steps if s["status"] == "queued" and not s.get("session")), None)
        cut = None
        chooser = not waiting and step is not None and choosing()
        if chooser:
            # Phases 3 and 4 (docs/observing-plan-spec.md): protected steps keep
            # their start, flexible ones are timed back from it, and with
            # dispatch the next agreed step is chosen by what it would get.
            step, cut, hold = choose_step(steps, say)
            if step is None and hold is not None:
                sleep(min(60, max(1, hold)))
                continue
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
            if step.get("session"):
                end_session(step["session"])     # its own marks stand; only what it left open is closed
            else:
                mark_id(step["id"], status="done", finished=time.time())
            ran = True     # a night that imaged, though another process ran it: it is ended in the morning too
            continue
        if step.get("not_before") and not chooser:
            until = not_before(step["not_before"], time.time())
            if time.time() < until:
                # A minute at a time, then the plan again: it may have changed.
                sleep(min(60, until - time.time()))
                continue
        command, left = prepared(step, time.time(), last_field(), cut=cut)
        if command is None:
            mark_id(step["id"], status="skipped", started=time.time(), finished=time.time())
            say(f"{datetime.now():%H:%M} {step['label']}: skipped, {max(left, 0)} s left")
            continue
        try:
            if storage.words():
                # Room first: finished Moon videos go to the storage disk.
                storage.tidy(say=say)
                if storage.words():
                    say(f"{datetime.now():%H:%M} {storage.words()}")
        except Exception as problem:     # room is a help: the step runs all the same
            say(f"{datetime.now():%H:%M} disk not checked: {problem.__class__.__name__}: {problem}")
        say(f"{datetime.now():%H:%M} starting {step['label']}")
        ran = True
        mark_id(step["id"], status="running", started=time.time())
        with activity.doing("Schedule", step["label"], number, len(steps)):
            try:
                # TY_SCHEDULED: the step runs unattended, so what needs a person
                # watching (a focus offset measured only once) is refused in it.
                done = start(command, env={**os.environ, "TY_SCHEDULED": "1"})
            except Exception as error:
                # A step that cannot even start is a failed step, not the end
                # of the runner: on 20 October 2026 a command cut wrongly
                # stopped the night at 01:45 with nobody told.
                say(f"{datetime.now():%H:%M} {step['label']} could not start: {error}")
                done = subprocess.CompletedProcess(command, 127)
        # Stopped at its time by timeout is how a step with an end time ends.
        backstopped = done.returncode == 124 and command[:1] == ["timeout"]
        ok = done.returncode == 0 or backstopped
        if backstopped and not step.get("until"):
            say(f"{datetime.now():%H:%M} {step['label']}: ran past its {step['minutes']:g} minutes and was "
                "stopped by the backstop")
        mark_id(step["id"], status="done" if ok else "failed", finished=time.time(), exit=done.returncode)
        say(f"{datetime.now():%H:%M} {step['label']} {'done' if ok else f'failed (exit {done.returncode})'}")
        say_outcomes(step, say)
        if not ok and step.get("tries", 0) < RETRIES:
            # Tried again by itself before anyone is fetched: on 1 November 2026
            # the camera jammed on a transit, the person was called, and the
            # same step started again cleared it ("i would rather that was
            # tried b4 i got notified").
            tries = step.get("tries", 0) + 1
            mark_id(step["id"], status="queued", tries=tries)
            say(f"{datetime.now():%H:%M} trying {step['label']} again ({tries} of {RETRIES}) in {RETRY_S} s")
            sleep(RETRY_S)
            continue
        if not ok:
            if chooser:
                # Its retries used up: a hard window that failed is owed (Phase 4).
                owe_interrupted(step, done.returncode, say)
            try:
                offer = fill_words(fill())
            except Exception as problem:    # the offer is a help: the person is fetched all the same
                offer = f"No offer to fill the time: {problem.__class__.__name__}: {problem}"
            (call or fetch)(f"The telescope needs you: {step['label']} stopped with an error"
                            + (f", and again after {RETRIES} more tries. " if RETRIES else ". ") + offer)
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


def summary(sessions, now=None):
    """What the night got, in one line: by field and filter, the minutes of
    frames kept against the minutes planned for them, so a block that got
    nothing is said, not hidden in a count of frames taken. 5 November 2026:
    "M33 487 frames" was reported for a night whose colour could not be
    made and whose M81 frames were mostly the wrong field."""
    got, planned = delivered(now), promised(now)
    if not got and not planned:
        fields = {}
        for field, frames, _ in sessions:
            fields[field] = fields.get(field, 0) + frames
        return ", ".join(f"{field} {n} frames" for field, n in fields.items()) or "no frames kept"
    parts = []
    for field in dict.fromkeys([f for f, _ in planned] + [f for f, _ in got]):
        bands = dict.fromkeys([b for f, b in planned if f == field] + [b for f, b in got if f == field])
        parts.append(field + " " + ", ".join(
            f"{band} {got.get((field, band), 0) / 60:.0f}"
            + (f" of {planned[(field, band)]:g}" if (field, band) in planned else "") + " min"
            for band in bands))
    return "; ".join(parts) + " (minutes of frames kept, of minutes planned)"


def delivered(now=None, hours=NIGHT_HOURS):
    """{(field folder, filter): seconds of frames kept} for the night's sessions."""
    import stacking
    now = now or time.time()
    out = {}
    for d in sorted((config.DATA / "frames").glob("*/2*")):
        try:
            begun = datetime.strptime(d.name[:15], "%Y%m%d-%H%M%S").timestamp()
        except ValueError:
            continue
        log = d / "frames.jsonl"
        if now - begun > hours * 3600 or not log.exists():
            continue
        first = next(iter(sorted(d.glob("light-*.fits"))), None)
        if first is None:
            continue
        try:
            header = stacking.load_light(first)[1]
            kept = sum(1 for line in log.read_text(encoding="utf-8").splitlines()
                       if line.strip() and json.loads(line).get("accepted"))
        except (OSError, ValueError, IndexError):
            continue
        key = (d.parent.name, str(header.get("FILTER") or "-"))
        out[key] = out.get(key, 0.0) + kept * float(header.get("EXPTIME") or 0)
    return out


def promised(now=None, hours=NIGHT_HOURS):
    """{(field folder, filter): minutes planned} from tonight's session blocks
    ("M33 L, 90 min")."""
    import re

    import stacking
    now = now or time.time()
    out = {}
    for step in load().get("steps", []):
        found = re.match(r"^(.*) (\S+), ([\d.]+) min", step.get("label") or "")
        when = step.get("started") or step.get("finished")
        if not step.get("session") or not found or (when and now - when > hours * 3600):
            continue
        key = (stacking.folder_name(found[1]), found[2])
        out[key] = out.get(key, 0.0) + float(found[3])
    return out


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


DAWN_FILTERS = ("B", "G", "R", "L")    # the sky brightens through dawn: the faintest-through filter first
FLATS_LOG = config.DATA / "cache" / "dawn-flats.log"


def dawn_flats(popen=subprocess.Popen):
    """After a night with a cooled camera behind a filter wheel, take dawn
    sky flats in LRGB from where the telescope is parked, with nothing over
    the tube: calibrate.py waits for the twilight, camera closed until then.
    5 November 2026: after the 183M's first night no flats were taken (put
    down to dew that was really cloud), and by the time they were wanted
    the camera was packed away. Returns what to tell the person, or None."""
    import stacking
    camera = config.camera_name()
    if stacking.dark_method(camera) != "matched" or not config.hardware()["train"].get("filterwheel"):
        return None
    import shlex
    here = Path(__file__).parent
    python = shlex.quote(sys.executable)
    # Then the camera keeper (keeper.py), if it holds the camera, warms the
    # sensor slowly and lets it go: the night's one warm-up, after the flats.
    line = (f"{python} calibrate.py flat --twilight --tell --filters {' '.join(DAWN_FILTERS)}; "
            f"{python} keeper.py stop")
    FLATS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(FLATS_LOG, "w", encoding="utf-8") as log:
        popen(["sh", "-c", line], stdout=log, stderr=subprocess.STDOUT, cwd=str(here), start_new_session=True)
    return ("Dawn flats in B, G, R and L will be taken from where it is parked as the sky brightens, "
            "with nothing over the tube, and you will be told when they are kept or if they fail: "
            "leave the camera, wheel and focus as they are until then.")


def release_camera(popen=subprocess.Popen):
    """The camera keeper, if it holds the camera, told to warm the sensor
    slowly and let it go (in the background: the warm-up takes minutes)."""
    import keeper
    if not keeper.running():
        return False
    popen([sys.executable, str(Path(__file__).with_name("keeper.py")), "stop"], stdout=subprocess.DEVNULL,
          stderr=subprocess.DEVNULL, cwd=str(Path(__file__).parent), start_new_session=True)
    return True


# What watches the sky or the guide star for a night and has no business
# after it: stopped by tidy() at the night's end. The status page, the
# stream's watcher and the night-end timer are services and stay.
WATCHERS = ("skywatch.py", "rain.py", "mountprobe.py", "runwatch.py")


def tidy(say=print, wait_s=20):
    """Stop what was left watching for the night: the guider (by its own stop
    order, so its pulses end cleanly), then each watcher by Ctrl-C (so it
    closes what it holds), then by force if it is still there. Returns the
    lines said. 12 November 2026: a rain watch, a cloud watch and a loop of
    guide tests were all still running when the night was ended."""
    import signal
    said = []

    def tell(line):
        said.append(line)
        say(line)
    try:
        import guider
        state = guider.read_state() or {}
        if state.get("pid") and alive(str(state["pid"])) and state.get("state") not in ("stopped", "fault"):
            subprocess.run([sys.executable, str(Path(__file__).with_name("guidecam.py")), "tell", "stop"],
                           cwd=str(Path(__file__).parent), capture_output=True, timeout=60)
            tell("the guider: stopped")
    except Exception as problem:            # the night's end goes on without it
        tell(f"the guider could not be told to stop: {problem}")
    found = []
    for proc in Path("/proc").glob("[0-9]*"):
        try:
            line = [w.decode(errors="replace") for w in (proc / "cmdline").read_bytes().split(b"\0") if w]
        except OSError:
            continue
        names = [Path(w).name for w in line]
        if any(n in WATCHERS for n in names) and int(proc.name) != os.getpid():
            found.append((int(proc.name), next(n for n in names if n in WATCHERS)))
    for pid, name in found:
        try:
            os.kill(pid, signal.SIGINT)
        except OSError:
            continue
    end_by = time.time() + wait_s
    for pid, name in found:
        while time.time() < end_by and Path(f"/proc/{pid}").exists():
            time.sleep(0.5)
        if Path(f"/proc/{pid}").exists():
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        tell(f"{name} (process {pid}): stopped")
    return said


def end(say=print, send=None, run=subprocess.run, now=None, home=None, start_flats=None):
    """The night is over: stop what was left watching (tidy), send the mount
    home (mount.py, so its motion lock and checks hold), check it got there,
    start the dawn flats, and tell the person on their phone. Returns
    whether it is parked."""
    import notify
    send = send or notify.send
    now = now or time.time()
    tidy(say=say)
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
        if parked:
            import director
            director.clear()                # parked: the stream names no target now
        words = (f"Observation is over. Tonight: {got}. The telescope is parked at home (by its axis readouts)."
                 if parked else
                 f"Observation is over. Tonight: {got}. The telescope could NOT be parked: it is still "
                 f"{state.get('state', 'where it was')}. Please check it.")
        flats = (start_flats or dawn_flats)() if parked and sessions else None
        if flats:
            words += f" {flats}"
        elif release_camera():
            words += " The camera is being warmed slowly, then let go."
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


def last_activity():
    """When the telescope was last used for anything that is not a kept
    frame: the guider's heartbeat and logs, a mount probe, the cloud watch's
    frames, the camera's newest picture. 12 November 2026, 04:02: the guard
    ended a night of guide-scope tests in a clear spell (calibration at
    03:49, guiding at 04:02), parked the mount and warmed the camera, since
    none of that kept a frame."""
    places = [config.DATA / "cache" / "guide.json", config.DATA / "cache" / "guide-run.log",
              config.DATA / "cache" / "sky_seen.jsonl", config.DATA / "web" / "latest.jpg"]
    places += list((config.DATA / "frames" / "guide").glob("*"))
    times = []
    for place in places:
        try:
            times.append(place.stat().st_mtime)
        except OSError:
            pass
    return max(times, default=0.0)


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
    import keeper
    # A night of cloud keeps no frames but still leaves the camera cold and
    # the mount tracking towards its limit: the camera kept counts as a
    # night too (12 November 2026: nothing kept all night, nothing would
    # have parked it).
    if not sessions and not keeper.running():
        return "nothing imaged tonight and the camera not kept"
    if sessions and now - max(s[2] for s in sessions) < IDLE_MINUTES * 60:
        return "still imaging"
    if now - last_activity() < IDLE_MINUTES * 60:
        return "the telescope was in use within the last half hour"
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


def add_session(blocks, pid):
    """The blocks of one imaging session (shoot.py --blocks), one step each,
    owned by that process: it marks them itself (mark_block) and the runner
    never starts them, only waits while the process lives. Replaces any of
    that process's steps left from before. Returns the steps' ids in order.
    5 November 2026: the night's cold session showed on the console as one
    bar, or not at all."""
    plan = load()
    plan["steps"] = [s for s in plan["steps"] if s.get("session") != pid]
    taken = {s.get("id", s["label"]) for s in plan["steps"]}
    ids = []
    for label, minutes in blocks:
        step_id = label if label not in taken else f"{label} ({len(taken) + 1})"
        taken.add(step_id)
        plan["steps"].append({"id": step_id, "label": label, "minutes": float(minutes), "command": None,
                              "not_before": None, "until": None, "pid": pid, "session": pid,
                              "status": "queued", "started": None, "finished": None})
        ids.append(step_id)
    plan.setdefault("made", time.time())
    save(plan)
    return ids


def mark_block(step_id, status, kept_minutes=None):
    """A session's block as it starts ("running") or ends ("done", "skipped",
    "failed"), with the time. A block that ends says on the page how many
    minutes of frames it kept against its planned minutes: 5 November 2026,
    M81 and M82's L block was marked done with 3 of its 30 minutes kept."""
    now = time.time()
    fields = {"started": now} if status == "running" else {"finished": now}
    if kept_minutes is not None:
        plan = load()
        step = next((s for s in plan["steps"] if s.get("id", s["label"]) == step_id), None)
        if step is not None:
            fields["kept_minutes"] = round(float(kept_minutes), 1)
            fields["label"] = f"{step_id}: kept {kept_minutes:.0f}"
    mark_id(step_id, status=status, **fields)


def end_session(pid):
    """A session's process has gone: its blocks still queued are skipped and
    one still running is done (its frames are kept), with the time."""
    plan, now = load(), time.time()
    for step in plan["steps"]:
        if step.get("session") == pid and step["status"] in ("queued", "running"):
            step.update(status="done" if step["status"] == "running" else "skipped", finished=now,
                        started=step.get("started") or now)
    save(plan)


def last_field():
    """The field imaged most recently: the folder of the newest session."""
    sessions = [d for d in (config.DATA / "frames").glob("*/2*") if d.is_dir()]
    return max(sessions, key=lambda d: d.stat().st_mtime).parent.name if sessions else None


def step_target(command):
    """The object a step points the telescope at, by name, from its command:
    shoot.py NAME, patrol.py PROGRAMME (its programme's target) or a goto
    NAME. None when it names none ({last}, a park, a survey)."""
    words = list(command or [])
    for i, word in enumerate(words):
        script = Path(word).name
        after = words[i + 1] if i + 1 < len(words) else None
        if script in ("shoot.py", "patrol.py") and after and not after.startswith(("-", "{")):
            if script == "patrol.py":
                import patrol
                return patrol.programme(after).get("target")
            return after
        if word == "goto" and after and not after.startswith("-"):
            return after
    return None


def path(step, settings, find=None, where=None):
    """Where a step's target is at its start, middle and end, against what is
    in the way: the floor, the blocked list and the spot's measured skyline.
    `step` is one of view()'s steps. Returns None for a step with no target,
    else {"target", "points": [{"at", "alt", "az", "limit"}], "behind": the
    points under their limit, "skyline": whether one is measured here}.
    1 November 2026: TOI-2046 b was planned from a spot with no skyline, and
    the corner of the house took the whole transit."""
    name = step_target(step.get("command"))
    if not name or step.get("start") is None or step.get("end") is None:
        return None
    import horizon
    find = find or (lambda n: __import__("mount").find_target(n))
    try:
        target = find(name)
    except interface.Refusal:
        return None
    where = where or altaz(settings["site"])
    view_ = settings.get("horizon", {})
    floor = float(view_.get("min_altitude", 0))
    points = []
    for at in (step["start"], (step["start"] + step["end"]) / 2, step["end"]):
        alt, az = where(target["ra"], target["dec"], at)
        limit = max(floor, horizon.in_the_way(view_, az))
        points.append({"at": at, "alt": round(alt, 1), "az": round(az, 1), "limit": round(limit, 1)})
    return {"target": name, "points": points, "behind": [p for p in points if p["alt"] < p["limit"]],
            "skyline": bool(view_.get("skyline"))}


def altaz(site):
    """(altitude, azimuth) in degrees of a fixed RA and Dec at a unix time."""
    def at(ra, dec, unix):
        import mount
        from astropy import units as u
        from astropy.coordinates import AltAz, SkyCoord
        from astropy.time import Time
        when = Time(unix, format="unix")
        seen = SkyCoord(ra=ra * u.deg, dec=dec * u.deg).transform_to(
            AltAz(obstime=when, location=mount.location(site)))
        return float(seen.alt.deg), float(seen.az.deg)
    return at


def path_words(checked):
    """One line on a step's path, or None when nothing is in its way and the
    spot's skyline is measured."""
    if not checked:
        return None
    when = lambda t: datetime.fromtimestamp(t).strftime("%H:%M")
    if checked["behind"]:
        p = checked["behind"][0]
        return (f"{checked['target']} is behind something at {when(p['at'])}: bearing {p['az']:.0f}°, "
                f"{p['alt']:.0f}° up, where the view starts at {p['limit']:.0f}°"
                + ("" if checked["skyline"] else " (no skyline measured at this spot)"))
    if not checked["skyline"]:
        low = min(checked["points"], key=lambda p: p["alt"] - p["limit"])
        return (f"no skyline measured at this spot: {checked['target']} is checked against the blocked "
                f"list only (lowest {low['alt']:.0f}° up at bearing {low['az']:.0f}°)")
    return None


def settings():
    return config.load() if config.FILE.exists() and not config.DEMO else config.example()


FILL_GAP_S = 600       # a wait between steps shorter than this is not worth filling
FILL_OPEN_S = 4 * 3600  # how far ahead to look when nothing queued keeps to the clock


def gap(plan=None, now=None):
    """The first stretch of the schedule from now with nothing to do: (start,
    end, the 1-based place a step would go to fill it), end None when nothing
    queued after it keeps to the clock. None when the plan has no such gap."""
    now = time.time() if now is None else now
    steps = view(plan, now)["steps"]
    free = now
    for place, s in enumerate(steps, 1):
        if s["status"] in ("done", "failed", "skipped"):
            continue
        if s["status"] == "queued" and s["start"] - free >= FILL_GAP_S:
            return free, s["start"], place
        free = max(free, s["end"])
    return free, None, len(steps) + 1


def fill(plan=None, now=None, programmes=None, check=None):
    """What to put in the time a lost step leaves: the first of tonight's
    discovery programmes (in the order they come best) that is up at the
    start of the gap, fits it, has not been done tonight, and whose path is
    clear of everything known to be in the way. Returns {"label", "minutes",
    "command", "at", "words": the one command that takes it} or None.
    `programmes` and `check` stand in for agent.discovery_tonight() and
    path() (for the tests). 1 November 2026: when TOI-2046 b went behind the
    house, the telescope waited for a person to choose what next."""
    plan = load() if plan is None else plan
    now = time.time() if now is None else now
    found = gap(plan, now)
    if not found:
        return None
    start, end, place = found
    room = (end - start) / 60 if end else FILL_OPEN_S / 60
    if programmes is None:
        import agent
        programmes = agent.discovery_tonight()
    done = " ".join(" ".join(s.get("command") or []) for s in plan["steps"] if s.get("status") == "done")
    cfg = None
    for p in programmes:
        if not p.get("command") or not p.get("minutes") or p["minutes"] > room:
            continue
        window = p.get("in_clear") or p.get("window")
        if not window:
            continue
        opens, closes = (t.timestamp() if hasattr(t, "timestamp") else datetime.fromisoformat(t).timestamp()
                         for t in window)
        if not (opens <= start and start + 60 * p["minutes"] <= closes):
            continue
        if p["programme"] in done:
            continue
        step = {"command": p["command"].split(), "start": start, "end": start + 60 * p["minutes"]}
        if check is None:
            cfg = cfg or settings()
        checked = (check or (lambda s: path(s, cfg)))(step)
        if checked and checked["behind"]:
            continue
        label = f"{p['field']}: {p['programme']}, filling a lost step"
        words = (f"./schedule.py add \"{label}\" {p['minutes']:g} --at {place} -- {p['command']}")
        return {"label": label, "minutes": p["minutes"], "command": p["command"].split(), "at": place,
                "start": start, "words": words}
    return None


def fill_words(offer):
    """The offer said to a person, or that nothing fits."""
    if not offer:
        return "Nothing from tonight's discovery list fits the time left."
    return (f"To fill the time from {datetime.fromtimestamp(offer['start']):%H:%M}: {offer['label']} "
            f"({offer['minutes']:g} min): {offer['words']}")


def fetch(words):
    subprocess.run([sys.executable, str(config.ROOT / "alert.py"), "call", words])


def show(say=print, check=None):
    """The schedule, with a line under each step still to come whose target
    is in the way of something, or unchecked for want of a skyline."""
    cfg = None
    steps = view()["steps"]
    if any(s.get("status") == "queued" for s in steps):
        try:
            low = storage.words()
        except OSError:
            low = None
        if low:
            say(f"! {low}; ./storage.py --tidy moves finished Moon videos to the storage disk")
    for s in steps:
        when = lambda t: datetime.fromtimestamp(t).strftime("%H:%M") if t else "--:--"
        done = "" if s["progress"] is None else f" {round(100 * s['progress'])}%"
        say(f"{when(s['start'])}-{when(s['end'])}  {s['status']:8}{done:>5}  {s['label']}")
        if s.get("status") in ("queued", "running") and s.get("command"):
            try:
                if check is None:
                    cfg = cfg or settings()
                words = path_words((check or (lambda step: path(step, cfg)))(s))
            except Exception as problem:    # the check is a help: the schedule shows all the same
                words = f"path not checked: {problem.__class__.__name__}: {problem}"
            if words:
                say(f"             ! {words}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="action")
    a = sub.add_parser("add")
    a.add_argument("label")
    a.add_argument("minutes", type=float)
    a.add_argument("--not-before", metavar="HH:MM", help="tonight's clock time (in darkness, one gone since sunset goes at once), or YYYY-MM-DD HH:MM")
    a.add_argument("--until", metavar="HH:MM", help="end the step then, whatever it is doing; as --not-before")
    a.add_argument("--protect", choices=["hard", "person"],
                   help="with [plan] windows on: hard (an occultation, a transit, an urgent transient) starts its "
                        "frames at --not-before whatever ran before, its setup reserved before it")
    a.add_argument("--deadline", metavar="HH:MM", help="with [plan] windows on: finish by then; it may go earlier")
    a.add_argument("--uncertainty", type=float, metavar="MIN",
                   help="minutes before --not-before the event may come (a transit's timing error)")
    a.add_argument("--filters", metavar="F:N,...",
                   help="a colour set as blocks, one step per filter (L:10,R:5,G:5,B:5): the imaging command with "
                        "--filter and --frames added to each; not for a hard window, which keeps one filter")
    a.add_argument("command", nargs=argparse.REMAINDER)
    w = sub.add_parser("wait")
    w.add_argument("label")
    w.add_argument("minutes", type=float)
    w.add_argument("pid", type=int)
    a.add_argument("--at", type=int, metavar="N", help="put it at this place in the schedule (1 is the first)")
    sk = sub.add_parser("skip", help="leave out a queued step, while the schedule runs")
    sk.add_argument("step", help="its number as shown, or its label")
    mv = sub.add_parser("move", help="move a queued step to another place")
    mv.add_argument("step")
    mv.add_argument("position", type=int)
    sub.add_parser("next", help="end the step running now gracefully and go on to the next")
    sub.add_parser("fill", help="the discovery programme that best fills the first gap, as one command")
    sub.add_parser("run")
    sub.add_parser("clear")
    sub.add_parser("end")
    sub.add_parser("tidy", help="stop what was left watching for the night (the guider, sky, rain and run "
                                "watches, the mount probe); the services stay")
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
        if "--at" in before:
            args.at = int(before[before.index("--at") + 1])
        for flag in ("--protect", "--deadline", "--uncertainty"):
            if flag in before:
                setattr(args, flag[2:], before[before.index(flag) + 1])
        if args.protect not in (None, "hard", "person"):
            ap.error("--protect is hard or person")
        if not command:
            ap.error("add needs the command after --")
        if args.protect == "hard" and not args.not_before:
            ap.error("--protect hard needs --not-before, the time its frames must start")
        if "--filters" in before:
            args.filters = before[before.index("--filters") + 1]
        if args.filters:
            added_ids = add_blocks(args.label, args.minutes, command, args.filters, protect=args.protect,
                                   not_before_=args.not_before, until=args.until, deadline=args.deadline)
            print(f"added {len(added_ids)} blocks: {', '.join(added_ids)}")
            show()
            return
        added = add(args.label, args.minutes, command, args.not_before, until=args.until, protect=args.protect,
                    deadline=args.deadline,
                    uncertainty=float(args.uncertainty) if args.uncertainty is not None else None)
        if args.at:
            move(len(load()["steps"]), args.at)
        step = next((s for s in view()["steps"] if s.get("id") == added), None)
        try:
            words = path_words(path(step, settings())) if step else None
        except Exception as problem:     # the check is a help: the step is added all the same
            words = f"path not checked: {problem.__class__.__name__}: {problem}"
        if words:
            print(f"! {words}")
    elif args.action == "skip":
        print(f"left out: {skip(args.step)}")
        print(fill_words(fill()))
    elif args.action == "move":
        print(f"moved: {move(args.step, args.position)}")
    elif args.action == "fill":
        print(fill_words(fill()))
    elif args.action == "next":
        print(next_step()["note"])
    elif args.action == "wait":
        add(args.label, args.minutes, None, pid=args.pid)
    elif args.action == "run":
        sys.exit(0 if run(reload=restart) else 1)
    elif args.action == "clear":
        save({"steps": [], "made": time.time()})
    elif args.action == "end":
        sys.exit(0 if end() else 1)
    elif args.action == "tidy":
        if not tidy():
            print("Nothing was left watching.")
    elif args.action == "guard":
        if args.install:
            install()
        else:
            print(guard(say=lambda *_: None))
        return
    show()


if __name__ == "__main__":
    main()
