"""Tonight's schedule: its times, its progress, and running it."""
import json
import os
import time
import types

import pytest

import schedule

ENDED, TOLD = [], []
REAL_END, REAL_STATE, REAL_FILL = schedule.end, schedule.mount_state, schedule.fill


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
    monkeypatch.setattr(schedule, "fill", lambda *a, **k: None)     # tonight's real sky is not worked out


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
    ok = schedule.run(say=lambda s: None, call=called.append, sleep=lambda s: None,
                      start=lambda cmd: (ran.append(cmd), types.SimpleNamespace(returncode=0 if cmd == ["true"] else 1))[1])
    statuses = [s["status"] for s in schedule.load()["steps"]]
    assert not ok and ran == [["true"]] + [["false"]] * (1 + schedule.RETRIES) and statuses == ["done", "failed", "queued"]
    assert called and "two" in called[0] and "again after" in called[0]


def test_a_failed_step_is_tried_again_before_anyone_is_called():
    """1 November 2026: the camera jammed on a transit and the person was
    called; starting the same step again cleared it."""
    schedule.save({"steps": []})
    schedule.add("transit", 250, ["shoot"])
    codes, called = iter([1, 0]), []
    ok = schedule.run(say=lambda s: None, call=called.append, sleep=lambda s: None,
                      start=lambda cmd: types.SimpleNamespace(returncode=next(codes)))
    assert not called and schedule.load()["steps"][0]["status"] == "done"


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
    assert ok and ran[0][:2] == ["timeout", "--signal=INT"] and ran[0][3:7] == ["./shoot.py", "M31-P4", "--frames", "0"]
    assert ran[0][7] == "--minutes" and 56 < float(ran[0][8]) <= 60          # told its time, to end gracefully
    assert 3400 + 900 < int(ran[0][2]) <= 3600 + 900 and schedule.load()["steps"][0]["status"] == "done"


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
    assert schedule.run(say=lambda s: None, call=called.append, sleep=lambda s: None) is False
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
    monkeypatch.setattr(schedule, "busy", lambda: False)    # not this computer's own running imaging (1 November 2026)
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


def test_the_plan_changes_while_it_runs_skip_move_and_insert():
    """1 November 2026: every change of plan meant stopping the runner and
    editing its file by hand."""
    schedule.save({"steps": []})
    for label in ("one", "two", "three"):
        schedule.add(label, 1, ["true"])
    assert schedule.skip("2") == "two"
    assert schedule.move("three", 1) == "three"
    assert [s["label"] for s in schedule.load()["steps"]] == ["three", "one", "two"]
    with pytest.raises(SystemExit):
        schedule.skip("two")                       # already left out
    schedule.main(["add", "four", "1", "--at", "1", "--", "true"])
    ran = []
    schedule.run(say=lambda s: None, sleep=lambda s: None,
                 start=lambda cmd: ran.append(cmd) or types.SimpleNamespace(returncode=0))
    assert ran == [["true"]] * 3                    # four, three, one; two left out
    assert [s["label"] for s in schedule.load()["steps"]][0] == "four"


def test_a_step_with_an_end_time_tells_its_run_how_long_it_has(monkeypatch):
    """The run finishes gracefully, picture and all; the hard stop is only a backstop."""
    monkeypatch.setattr(schedule, "last_field", lambda: "M33")
    schedule.save({"steps": []})
    schedule.add("M81", 60, ["./shoot.py", "M81", "--frames", "0"], until="23:59")
    ran = []
    schedule.run(say=lambda s: None, sleep=lambda s: None,
                 start=lambda cmd: ran.append(cmd) or types.SimpleNamespace(returncode=0))
    command = ran[0]
    assert command[0] == "timeout" and "--minutes" in command
    minutes = float(command[command.index("--minutes") + 1])
    # The hard stop comes 15 minutes after the graceful one; the minutes are
    # given to a tenth, so they can round up by as much as 3 seconds.
    assert int(command[2]) >= minutes * 60 - 3 + 900


def test_next_ends_the_running_step_gracefully():
    told = []
    schedule.next_step(tell=lambda order: told.append(order) or {"note": "ok"})
    assert told == ["stop"]


# --- a target's path against what is in the way --------------------------------

def test_a_step_names_its_target_from_its_command():
    assert schedule.step_target(["./shoot.py", "M33", "--minutes", "30"]) == "M33"
    assert schedule.step_target(["./patrol.py", "m33-novae", "--release"]) == "M33"     # the programme's target
    assert schedule.step_target(["./ty", "mount", "goto", "Vega", "--solve"]) == "Vega"
    assert schedule.step_target(["./shoot.py", "{last}", "--frames", "0"]) is None
    assert schedule.step_target(["./horizon.py", "--trace", "--daylight"]) is None
    assert schedule.step_target(None) is None


def path_of(alt_az, horizon):
    """A step from 0 to 3600 s, its target where `alt_az` says at each time."""
    step = {"command": ["./shoot.py", "TOI-2046"], "start": 0.0, "end": 3600.0}
    return schedule.path(step, {"site": {}, "horizon": horizon},
                         find=lambda name: {"ra": 0.0, "dec": 0.0},
                         where=lambda ra, dec, at: alt_az[at])


def test_a_target_behind_the_house_is_said_before_its_step():
    # 1 November 2026: the house corner, bearings 333-340 up to 68 degrees,
    # took the whole of TOI-2046 b's transit.
    house = {"min_altitude": 20, "blocked": [{"from": 333, "to": 340, "altitude": 68}],
             "skyline": [{"az": 0, "alt": 30}, {"az": 180, "alt": 30}], "margin": 2}
    checked = path_of({0.0: (60.0, 336.0), 1800.0: (58.0, 338.0), 3600.0: (55.0, 342.0)}, house)
    assert [p["at"] for p in checked["behind"]] == [0.0, 1800.0]
    words = schedule.path_words(checked)
    assert words.startswith("TOI-2046 is behind something at") and "bearing 336°, 60° up" in words
    assert "where the view starts at 68°" in words and "no skyline" not in words


def test_a_clear_path_says_nothing_and_an_unmeasured_spot_says_so():
    measured = {"min_altitude": 20, "skyline": [{"az": 0, "alt": 30}, {"az": 180, "alt": 30}], "margin": 2}
    high = {0.0: (60.0, 90.0), 1800.0: (62.0, 100.0), 3600.0: (61.0, 110.0)}
    assert schedule.path_words(path_of(high, measured)) is None
    words = schedule.path_words(path_of(high, {"min_altitude": 20}))
    assert words.startswith("no skyline measured at this spot") and "lowest 60° up" in words
    # Under the floor, with no skyline: behind, and said to be unmeasured.
    low = {0.0: (15.0, 200.0), 1800.0: (12.0, 210.0), 3600.0: (9.0, 220.0)}
    assert schedule.path_words(path_of(low, {"min_altitude": 20})).endswith("(no skyline measured at this spot)")


def test_a_step_with_no_target_or_an_unknown_one_is_not_checked():
    assert schedule.path({"command": ["./schedule.py", "end"], "start": 0.0, "end": 1.0}, {}) is None

    def unknown(name):
        raise schedule.interface.Refusal("TARGET_UNKNOWN", "no")
    step = {"command": ["./shoot.py", "Nowhere"], "start": 0.0, "end": 1.0}
    assert schedule.path(step, {"site": {}}, find=unknown) is None


def test_the_schedule_shows_a_warning_under_a_step_still_to_come(monkeypatch):
    plan = {"steps": [{"label": "done one", "minutes": 10, "status": "done", "command": ["./shoot.py", "M33"],
                       "started": 0.0, "finished": 600.0},
                      {"label": "TOI-2046 b", "minutes": 60, "status": "queued", "command": ["./shoot.py", "TOI-2046"]}]}
    monkeypatch.setattr(schedule, "load", lambda: plan)
    said = []
    schedule.show(say=said.append, check=lambda step: {"target": "TOI-2046", "skyline": True, "points": [],
                                                       "behind": [{"at": step["start"], "az": 336.0,
                                                                   "alt": 60.0, "limit": 68.0}]})
    assert len(said) == 3 and said[2].strip().startswith("! TOI-2046 is behind something")


# --- a lost step filled ----------------------------------------------------------

HOUR = 3600.0


def programme(name, field, minutes, opens, closes):
    iso = lambda t: __import__("datetime").datetime.fromtimestamp(t).astimezone().isoformat()
    return {"programme": name, "field": field, "minutes": minutes, "command": f"./patrol.py {name}",
            "window": [iso(opens), iso(closes)], "in_clear": None}


def test_the_gap_a_lost_step_leaves_is_found_before_a_step_on_the_clock():
    now = 1000 * HOUR
    at = lambda t: __import__("datetime").datetime.fromtimestamp(t).strftime("%H:%M")
    plan = {"steps": [{"label": "TOI-2046 b", "minutes": 60, "status": "failed", "command": ["./shoot.py", "TOI-2046"],
                       "started": now - 600, "finished": now - 60},
                      {"label": "M81", "minutes": 60, "status": "queued", "command": ["./shoot.py", "M81"],
                       "not_before": at(now + 2 * HOUR)}]}
    start, end, place = schedule.gap(plan, now)
    assert start == now and end == pytest.approx(now + 2 * HOUR, abs=60) and place == 2
    # Nothing on the clock: the time after the last step is open.
    start, end, place = schedule.gap({"steps": []}, now)
    assert (start, end, place) == (now, None, 1)


def test_a_lost_step_is_filled_from_the_discovery_list_with_one_command():
    now = 1000 * HOUR
    at = lambda t: __import__("datetime").datetime.fromtimestamp(t).strftime("%H:%M")
    plan = {"steps": [{"label": "M31 novae", "minutes": 30, "status": "done", "command": ["./patrol.py", "m31-novae"],
                       "started": now - 3 * HOUR, "finished": now - 2 * HOUR},
                      {"label": "M81", "minutes": 60, "status": "queued", "command": ["./shoot.py", "M81"],
                       "not_before": at(now + 2 * HOUR)}]}
    listing = [programme("tabby", "Tabby", 10, now - HOUR, now + 5 * 60),       # sets before it would finish
               programme("m31-novae", "M31", 30, now - HOUR, now + 6 * HOUR),    # done tonight already
               programme("m33-novae", "M33", 150, now - HOUR, now + 6 * HOUR),   # longer than the gap
               programme("ngc7000", "NGC 7000", 45, now - HOUR, now + 6 * HOUR),  # behind the house
               programme("m33-short", "M33", 75, now - HOUR, now + 6 * HOUR)]
    # agent.discovery_tonight() gives datetimes; ty night --json gives the same as text.
    listing[-1]["window"] = [__import__("datetime").datetime.fromisoformat(t) for t in listing[-1]["window"]]
    behind = lambda step: {"behind": [1] if "ngc7000" in step["command"][1] else []}
    offer = REAL_FILL(plan, now, programmes=listing, check=behind)
    assert offer["command"] == ["./patrol.py", "m33-short"] and offer["at"] == 2 and offer["minutes"] == 75
    assert offer["words"].startswith('./schedule.py add "M33: m33-short, filling a lost step" 75 --at 2 -- ./patrol.py')
    assert schedule.fill_words(offer).startswith("To fill the time from ")
    # Nothing fits: said so plainly.
    assert REAL_FILL(plan, now, programmes=listing[:3], check=behind) is None
    assert schedule.fill_words(None).startswith("Nothing from tonight's discovery list fits")


def test_a_failed_step_fetches_the_person_with_the_offer(monkeypatch):
    monkeypatch.setattr(schedule, "fill", lambda *a, **k: {"label": "M33", "minutes": 75, "start": 0.0,
                                                          "words": "./schedule.py add M33 75 --at 2 -- ./patrol.py m33-novae"})
    monkeypatch.setattr(schedule, "RETRIES", 0)
    plan = {"steps": [{"id": "a", "label": "a", "minutes": 1, "status": "queued", "command": ["false"]}]}
    monkeypatch.setattr(schedule, "load", lambda: json.loads(json.dumps(plan)))
    monkeypatch.setattr(schedule, "mark_id", lambda step_id, **f: plan["steps"][0].update(f))
    called = []
    assert schedule.run(say=lambda *_: None, sleep=lambda s: None, call=called.append,
                        start=lambda c: types.SimpleNamespace(returncode=1)) is False
    assert called and "./schedule.py add M33 75 --at 2" in called[0]
