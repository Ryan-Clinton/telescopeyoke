"""Tonight's schedule: its times, its progress, and running it."""
import types

import schedule


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
