"""Tonight's schedule: its times, its progress, and running it."""
import json
import os
import time
import types

import pytest

import schedule

ENDED, TOLD = [], []
REAL_END, REAL_STATE = schedule.end, schedule.mount_state


@pytest.fixture(autouse=True)
def no_real_mount(monkeypatch):
    """No test here ever asks the real mount anything or sends a message: a
    night's end and each message are recorded instead."""
    import notify
    ENDED.clear()
    TOLD.clear()
    monkeypatch.setattr(schedule, "end", lambda **k: ENDED.append(k) or True)
    monkeypatch.setattr(notify, "send", lambda text, **k: TOLD.append(text))
    monkeypatch.setattr(schedule, "mount_state", lambda run=None: pytest.fail("the real mount was asked"))


def test_the_times_follow_from_a_running_step_and_a_step_not_before():
    plan = {"steps": [
        {"label": "M31 novae", "minutes": 30, "status": "running", "started": 1000.0},
        {"label": "M31 panels", "minutes": 60, "status": "queued"},
        {"label": "WASP-12 b", "minutes": 250, "status": "queued", "not_before": None},
    ]}
    steps = schedule.view(plan, now=1000.0 + 15 * 60)["steps"]
    assert steps[0]["progress"] == 0.5 and steps[0]["end"] == 1000.0 + 1800
    assert steps[1]["start"] == steps[0]["end"] and steps[2]["start"] == steps[1]["end"]


def test_a_step_running_late_pushes_the_rest_back():
    plan = {"steps": [{"label": "a", "minutes": 10, "status": "running", "started": 0.0},
                      {"label": "b", "minutes": 10, "status": "queued"}]}
    steps = schedule.view(plan, now=900.0)["steps"]
    assert steps[0]["end"] == 900.0 and steps[1]["start"] == 900.0 and steps[0]["progress"] == 0.99


def test_each_step_keeps_the_fields_the_public_live_page_reads():
    """ryanclinton.uk's live page shows tonight's plan from these (docs/live-page.md)."""
    plan = {"steps": [{"label": "a", "minutes": 10, "status": "running", "started": 0.0},
                      {"label": "b", "minutes": 10, "status": "queued"}]}
    for step in schedule.view(plan, now=60.0)["steps"]:
        assert {"label", "status", "start", "end"} <= set(step)


def test_steps_run_in_order_and_a_failure_stops_and_fetches_the_person():
    schedule.save({"steps": []})
    schedule.add("one", 1, ["true"])
    schedule.add("two", 1, ["false"])
    schedule.add("three", 1, ["true"])
    ran, called = [], []
    ok = schedule.run(say=lambda s: None, call=called.append,
                      start=lambda cmd: (ran.append(cmd), types.SimpleNamespace(returncode=0 if cmd == ["true"] else 1))[1])
    statuses = [s["status"] for s in schedule.load()["steps"]]
    assert not ok and ran == [["true"], ["false"]] and statuses == ["done", "failed", "queued"]
    assert called and "two" in called[0]


def test_a_step_already_running_elsewhere_is_waited_for():
    schedule.save({"steps": []})
    schedule.add("novae", 30, None, pid=999999999)
    schedule.add("panels", 60, ["true"])
    ok = schedule.run(say=lambda s: None, sleep=lambda s: None,
                      start=lambda cmd: types.SimpleNamespace(returncode=0))
    assert ok and [s["status"] for s in schedule.load()["steps"]] == ["done", "done"]


def test_a_time_not_to_start_before_is_kept_apart_from_the_command():
    schedule.save({"steps": []})
    schedule.main(["add", "GoTo", "3", "--not-before", "01:45", "--", "./mount.py", "goto", "WASP-12"])
    step = schedule.load()["steps"][0]
    assert step["not_before"] == "01:45" and step["command"] == ["./mount.py", "goto", "WASP-12"]


def test_a_step_with_an_end_time_images_the_last_field_until_then(monkeypatch):
    """20 October 2026: the panels ran early; the time before the transit's
    fixed start went on the last panel instead of waiting."""
    import time
    schedule.save({"steps": []})
    monkeypatch.setattr(schedule, "last_field", lambda: "M31-P4")
    until = time.strftime("%H:%M", time.localtime(time.time() + 3600))
    schedule.main(["add", "Keep going", "0", "--until", until, "--", "./shoot.py", "{last}", "--frames", "0"])
    ran = []
    ok = schedule.run(say=lambda s: None,
                      start=lambda cmd: (ran.append(cmd), types.SimpleNamespace(returncode=124))[1])
    assert ok and ran[0][:2] == ["timeout", "--signal=INT"] and ran[0][3:] == ["./shoot.py", "M31-P4", "--frames", "0"]
    assert 3400 < int(ran[0][2]) <= 3600 and schedule.load()["steps"][0]["status"] == "done"


def test_a_step_with_an_end_time_already_past_is_skipped(monkeypatch):
    import time
    schedule.save({"steps": []})
    monkeypatch.setattr(schedule, "last_field", lambda: "M31-P4")
    until = time.strftime("%H:%M", time.localtime(time.time() + 30))
    schedule.main(["add", "Keep going", "0", "--until", until, "--", "./shoot.py", "{last}"])
    ran = []
    assert schedule.run(say=lambda s: None, start=lambda cmd: ran.append(cmd))
    assert ran == [] and schedule.load()["steps"][0]["status"] == "skipped"


def test_a_step_added_while_it_runs_is_taken_in_its_place():
    """20 October 2026: a step added mid-night needed the runner restarting."""
    schedule.save({"steps": []})
    schedule.add("panels", 60, ["panels"])
    schedule.add("transit", 250, ["transit"])
    ran = []

    def start(cmd):
        ran.append(cmd[0])
        if cmd == ["panels"]:            # while the panels run, a step goes in after them
            plan = schedule.load()
            plan["steps"].insert(1, {"id": "fill", "label": "fill", "minutes": 0, "command": ["fill"],
                                     "status": "queued"})
            schedule.save(plan)
        return types.SimpleNamespace(returncode=0)
    assert schedule.run(say=lambda s: None, start=start)
    assert ran == ["panels", "fill", "transit"]


def test_a_step_that_cannot_start_fails_and_fetches_the_person():
    """20 October 2026: a command cut wrongly ('goto' with no ./mount.py)
    crashed the runner at 01:45, and nobody was told."""
    schedule.save({"steps": []})
    schedule.add("GoTo", 3, ["no-such-program-anywhere"])
    called = []
    assert schedule.run(say=lambda s: None, call=called.append) is False
    assert schedule.load()["steps"][0]["status"] == "failed" and called


class Clock:
    """datetime with now() fixed at an hour, for the schedule's morning test."""
    def __init__(self, hour):
        self.hour = hour

    def now(self):
        import datetime
        return datetime.datetime(2026, 10, 20, self.hour, 0)

    def __getattr__(self, name):
        import datetime
        return getattr(datetime.datetime, name)


def test_the_night_ends_parked_and_told_when_the_last_step_has_run_in_the_morning(monkeypatch):
    monkeypatch.setattr(schedule, "datetime", Clock(6))
    schedule.save({"steps": []})
    schedule.add("one", 1, ["true"])
    assert schedule.run(say=lambda s: None, start=lambda cmd: types.SimpleNamespace(returncode=0))
    assert len(ENDED) == 1
    ENDED.clear()
    assert schedule.run(say=lambda s: None, start=lambda cmd: types.SimpleNamespace(returncode=0))
    assert ENDED == []                                   # nothing ran: nothing to end


def test_a_schedule_finished_in_the_evening_says_so_and_moves_nothing(monkeypatch):
    monkeypatch.setattr(schedule, "datetime", Clock(21))
    schedule.save({"steps": []})
    schedule.add("focus", 1, ["true"])
    assert schedule.run(say=lambda s: None, start=lambda cmd: types.SimpleNamespace(returncode=0))
    assert ENDED == [] and "still where it was" in TOLD[0]


def session(field, name, frames, age_s):
    d = schedule.config.DATA / "frames" / field / name
    d.mkdir(parents=True, exist_ok=True)
    for i in range(frames):
        f = d / f"light-{i + 1:04d}.fits"
        f.write_bytes(b"")
        os.utime(f, (time.time() - age_s, time.time() - age_s))
    return d


def mount(states):
    """A stand-in for mount.py status --json: answers from `states` in turn
    (None is a refusal, as interface.envelope gives one: ok false, data {})."""
    def run(command, **k):
        state = states.pop(0)
        reply = {"ok": state is not None, "data": state if state is not None else {}}
        return types.SimpleNamespace(stdout=json.dumps(reply))
    return run


def own_data(monkeypatch, tmp_path):
    monkeypatch.setattr(schedule.config, "DATA", tmp_path)
    monkeypatch.setattr(schedule, "ENDED", tmp_path / "cache" / "night.ended")
    monkeypatch.setattr(schedule, "RUNNER", tmp_path / "cache" / "schedule.runner")
    monkeypatch.setattr(schedule, "LOOKED", tmp_path / "cache" / "night.looked")
    monkeypatch.setattr(schedule, "mount_state", REAL_STATE)


def test_ending_the_night_parks_the_mount_and_says_what_the_night_got(monkeypatch, tmp_path):
    own_data(monkeypatch, tmp_path)
    now = time.mktime((2026, 10, 20, 5, 40, 0, 0, 0, -1))
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now - 4 * 3600))
    session("WASP-12", stamp, 3, 900)
    moved, sent = [], []

    def end(states):
        return REAL_END(say=lambda *_: None, send=lambda text, **k: sent.append(text), now=now,
                        run=mount(states), home=lambda: moved.append("home"))
    assert end([{"at_home": False, "state": "tracking"}, {"at_home": True}]) and moved == ["home"]
    assert sent == ["Observation is over. Tonight: WASP-12 3 frames. "
                    "The telescope is parked at home (by its axis readouts)."]
    sent.clear()
    assert not end([{"at_home": False, "state": "tracking"}, {"at_home": False, "state": "tracking"}])
    assert "could NOT be parked: it is still tracking" in sent[0]
    # A refusal from mount.py (handset not answering) is no answer: nothing moves.
    sent.clear()
    moved.clear()
    assert not end([None]) and moved == [] and "did not answer" in sent[0]
    assert schedule.ENDED.exists()                      # written before any move: never tried twice


def test_the_guard_ends_a_night_only_in_the_morning_once_imaging_has_stopped(monkeypatch, tmp_path):
    own_data(monkeypatch, tmp_path)
    ended = []
    monkeypatch.setattr(schedule, "end", lambda **k: ended.append(k) or True)
    morning = time.mktime((2026, 10, 20, 6, 0, 0, 0, 0, -1))
    evening = time.mktime((2026, 10, 20, 21, 0, 0, 0, 0, -1))
    idle = lambda: False  # noqa: E731
    assert schedule.guard(now=evening, running=idle) == "not morning"
    assert schedule.guard(now=morning, running=idle) == "nothing imaged tonight"
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(morning - 4 * 3600))
    d = session("WASP-12", stamp, 2, 0)
    for f in d.glob("*.fits"):
        os.utime(f, (morning - 300, morning - 300))
    assert schedule.guard(now=morning, running=idle) == "still imaging"
    for f in d.glob("*.fits"):
        os.utime(f, (morning - 3600, morning - 3600))
    assert schedule.guard(now=morning, running=lambda: True) == "something is driving the mount or camera"
    tracking = {"at_home": False, "state": "tracking", "ra_hours": 6.33, "dec_deg": 27.86}
    assert schedule.guard(now=morning, running=idle, run=mount([None])) == "the mount did not answer"
    assert schedule.guard(now=morning, running=idle, run=mount([dict(tracking, at_home=True)])) == "already at home"
    assert schedule.guard(now=morning, running=idle, run=mount([tracking])) == "not yet seen tracking unmoved"
    moved = dict(tracking, dec_deg=40.0)                 # someone at the handset between the looks
    assert schedule.guard(now=morning + 600, running=idle, run=mount([moved])) == "not yet seen tracking unmoved"
    assert ended == []
    assert schedule.guard(now=morning + 1200, running=idle, run=mount([moved])) == "ended" and len(ended) == 1
    schedule.ENDED.parent.mkdir(parents=True, exist_ok=True)
    schedule.ENDED.write_text(str(morning + 1200))
    assert schedule.guard(now=morning + 1800, running=idle) == "already ended" and len(ended) == 1


def test_anything_driving_the_mount_or_camera_is_seen_however_it_was_started():
    assert schedule.driving(["timeout", "--signal=INT", "600", "./shoot.py", "WASP-12"])
    assert schedule.driving(["python3", "/home/x/telescopeyoke/ty", "mount", "goto", "M31"])
    assert schedule.driving(["/usr/bin/python3", "./mount.py", "findhome"])
    assert not schedule.driving(["python3", "./schedule.py", "guard"])
    assert not schedule.driving(["python3", "./ty", "night"])
