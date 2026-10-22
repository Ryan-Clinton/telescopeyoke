"""What the telescope is doing now, as the console shows it between frames."""
import pytest

import activity


@pytest.fixture(autouse=True)
def fresh():
    """Each test starts with nothing being done and nothing done before."""
    for path in (activity.FILE, activity._last_file(), activity._runs_file()):
        path.unlink(missing_ok=True)


def test_a_block_says_what_it_is_doing_and_clears_after():
    with activity.doing("Moving", "to M31"):
        now = activity.now()
        assert [n["words"] for n in now] == ["Moving: to M31"]
    assert activity.now() == []


def test_lines_from_ended_processes_are_dropped():
    activity._write({"999999-main": {"what": "Moving", "detail": "", "updated": 1e12, "started": 1e12}})
    assert activity.now(alive=lambda pid: False) == []


def test_nested_lines_come_outermost_first_with_their_counts():
    activity._write({"1-main": {"what": "Panel", "detail": "M31-P5", "step": 3, "of": 8, "updated": 100, "started": 10},
                     "2-block0": {"what": "Moving", "detail": "to M31-P5", "updated": 100, "started": 50}})
    words = [n["words"] for n in activity.now(clock=lambda: 120, alive=lambda pid: True)]
    assert words == ["Panel 3 of 8: M31-P5", "Moving: to M31-P5"]


def test_a_decorated_function_fills_its_words_from_its_arguments():
    seen = []

    @activity.during("Moving", "to {name}")
    def goto(name, fast=False):
        seen.append(activity.now()[0]["words"])
        return name
    assert goto("M31") == "M31" and seen == ["Moving: to M31"] and activity.now() == []


def test_an_error_inside_still_clears_the_line():
    try:
        with activity.doing("Plate solving"):
            raise RuntimeError("no stars")
    except RuntimeError:
        pass
    assert activity.now() == []


def test_a_status_file_that_cannot_be_written_never_stops_what_it_describes(monkeypatch, tmp_path):
    """It is written from inside a GoTo: a write failing must not fail the move."""
    blocked = tmp_path / "file-not-folder"
    blocked.write_text("")
    monkeypatch.setattr(activity, "FILE", blocked / "activity.json")

    @activity.during("Moving", "to {name}")
    def goto(name):
        return "arrived"
    assert goto("M31") == "arrived" and activity.now() == []


def test_a_solve_inside_a_goto_shows_under_it_and_leaves_it_there():
    with activity.doing("Moving", "to M31"):
        with activity.doing("Plate solving"):
            assert [n["words"] for n in activity.now()] == ["Moving: to M31", "Plate solving"]
        assert [n["words"] for n in activity.now()] == ["Moving: to M31"]


def test_a_file_that_is_not_what_it_should_be_is_ignored():
    activity.FILE.parent.mkdir(parents=True, exist_ok=True)
    activity.FILE.write_text("[1, 2, 3]")
    with activity.doing("Moving"):
        assert [n["words"] for n in activity.now()] == ["Moving"]


def test_threads_writing_at_once_never_raise():
    import threading
    errors = []

    def busy(n):
        try:
            for _ in range(50):
                with activity.doing("Plate solving", str(n)):
                    pass
        except Exception as error:
            errors.append(error)
    threads = [threading.Thread(target=busy, args=(n,)) for n in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == [] and activity.now() == []


def test_words_can_be_made_from_the_arguments_by_a_function():
    seen = []

    @activity.during("Quality pass", lambda a: f"{a['session'].split('/')[-2]}: restacking")
    def run(session, keep=0.85):
        seen.append(activity.now()[0]["words"])
    run("frames/M31-P5/20261020-003500")
    assert seen == ["Quality pass: M31-P5: restacking"]


def test_the_quality_pass_and_the_search_say_what_they_are_doing():
    import patrol
    import restack
    assert restack.run.__wrapped__ and patrol.analyse.__wrapped__
    assert restack._field(["frames/M31-P5/a", "frames/M31-P5/b"]) == "M31-P5"


# --- imaging runs, a silent camera, stopped runs (22 October 2026) -----------
# The page said "Doing now: Nothing running" while a patrol's shoot.py had
# waited over five minutes for M31-P6's first frame from a camera that had
# stopped sending.

def test_an_imaging_run_says_how_many_frames_have_come(tmp_path):
    with activity.imaging("M31-P6", 19, 16, tmp_path / "session") as run:
        assert [n["words"] for n in activity.now()] == ["Imaging M31-P6: 0 of 19 frames of 16 s"]
        run.waiting()
        run.took(4)
        assert [n["words"] for n in activity.now()] == ["Imaging M31-P6: 4 of 19 frames of 16 s"]
        assert activity.phase() == "imaging"
    assert activity.now() == []
    ended = activity.last()
    assert ended["words"] == "Imaging M31-P6: 4 of 19 frames of 16 s" and not ended["stopped"]


def test_an_open_ended_run_counts_its_frames_alone():
    with activity.imaging("M33", None, 30) as run:
        run.took(12)
        assert activity.now()[0]["words"] == "Imaging M33: 12 frames of 30 s"


def test_a_patrol_shows_its_panel_with_the_imaging_run_under_it():
    import patrol
    title = patrol.heading({"name": "m31-panels"})
    assert title == "M31 panels"
    activity._write({"1-main": {"what": "Patrol", "heading": title, "detail": "panel 1 of 8, M31-P6",
                                "updated": 100, "started": 10},
                     "2-block0": {"what": "Imaging", "detail": "M31-P6", "frames": 0, "planned": 19,
                                  "exposure": 16.0, "waiting_since": 50, "updated": 100, "started": 40}})
    words = [n["words"] for n in activity.now(clock=lambda: 120, alive=lambda pid: True)]
    assert words == ["Patrol M31 panels: panel 1 of 8, M31-P6", "Imaging M31-P6: 0 of 19 frames of 16 s"]


def silent_run(waiting_since, others=()):
    entries = {"2-block0": {"what": "Imaging", "detail": "M31-P6", "frames": 0, "planned": 19, "exposure": 16.0,
                            "waiting_since": waiting_since, "updated": 1000, "started": 0}}
    entries.update(others)
    activity._write(entries)
    return activity.now(clock=lambda: 1000, alive=lambda pid: True)


def test_a_camera_that_has_sent_nothing_for_five_minutes_is_said_plainly():
    line = silent_run(waiting_since=700)[0]
    assert line["words"] == "Imaging M31-P6: 0 of 19 frames of 16 s — camera has sent no frame for 5 min"
    assert line["camera_silent_s"] == 300


def test_a_frame_taking_its_time_is_not_called_a_fault():
    # 2 x 16 s + 60 s = 92 s: 80 s of waiting is a slow frame, not a silent camera.
    line = silent_run(waiting_since=920)[0]
    assert line["camera_silent_s"] is None and "camera" not in line["words"]


def test_a_recentring_goto_is_not_the_camera_keeping_the_run_waiting():
    lines = silent_run(waiting_since=700, others={"2-block1": {"what": "Moving", "detail": "to M31-P6",
                                                                "updated": 1000, "started": 800}})
    assert [n["words"] for n in lines] == ["Imaging M31-P6: 0 of 19 frames of 16 s", "Moving: to M31-P6"]


def test_the_patrol_searching_the_last_panel_meanwhile_does_not_hide_a_silent_camera():
    lines = silent_run(waiting_since=700, others={"1-block3": {"what": "Searching", "detail": "M31-P5",
                                                                "updated": 1000, "started": 800}})
    assert lines[0]["camera_silent_s"] == 300


def test_a_run_whose_process_has_gone_is_stopped_with_when_and_how_far(tmp_path):
    folder = tmp_path / "frames" / "M31-P6" / "20261022-043951"
    folder.mkdir(parents=True)
    activity._write({"999999-block0": {"what": "Imaging", "detail": "M31-P6", "frames": 0, "planned": 19,
                                       "exposure": 16.0, "session": activity._session(folder),
                                       "updated": 1e12, "started": 1e12},
                     "999999-main": {"what": "Patrol", "heading": "M31 panels", "detail": "panel 1 of 8, M31-P6",
                                     "updated": 1e12, "started": 1e12 - 100}})
    assert activity.now(clock=lambda: 1e12 + 5, alive=lambda pid: False) == []
    ended = activity.last()
    assert ended["stopped"] and ended["words"] == "Imaging M31-P6: 0 of 19 frames of 16 s"
    assert activity.run_state(folder, []) == {"running": False, "stopped_at": 1e12 + 5, "camera_silent_s": None}


def test_a_run_a_process_is_running_is_running(tmp_path):
    with activity.imaging("M31-P6", 19, 16, tmp_path):
        assert activity.run_state(tmp_path)["running"] is True


def test_a_run_never_seen_ends_with_its_newest_file(tmp_path):
    (tmp_path / "session.json").write_text("{}")
    state = activity.run_state(tmp_path, [])
    assert not state["running"] and abs(state["stopped_at"] - (tmp_path / "session.json").stat().st_mtime) < 1


def test_a_run_stopped_by_hand_is_noted_as_stopped(tmp_path):
    try:
        with activity.imaging("M31-P6", 19, 16, tmp_path):
            raise KeyboardInterrupt
    except KeyboardInterrupt:
        pass
    assert activity.last()["stopped"] and activity.run_state(tmp_path, [])["running"] is False


def test_each_change_holds_the_files_lock_against_other_processes(monkeypatch):
    """The page drops dead processes' lines while live ones write theirs; a
    read-change-write without a lock between processes can lose a line."""
    import contextlib
    import records
    held = []

    @contextlib.contextmanager
    def locked(path):
        held.append(path)
        yield
    monkeypatch.setattr(records, "locked", locked)
    activity.set_("Patrol", "panel 1 of 8, M31-P6")
    activity.now()
    activity.clear()
    assert held == [activity.FILE] * 3


# --- commands that showed nothing before --------------------------------------

def test_restarting_the_camera_says_so(monkeypatch):
    import camera_setup
    seen = []
    monkeypatch.setattr(camera_setup, "setup", lambda args: seen.append([n["words"] for n in activity.now()]) or {})

    class Args:
        check = False
    camera_setup.run(Args())
    Args.check = True
    camera_setup.run(Args())
    assert seen == [["Restarting the camera"], ["Checking the camera"]] and activity.now() == []


class LookingCamera:
    seen = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def frame(self, seconds):
        import numpy as np
        LookingCamera.seen.append([n["words"] for n in activity.now()])
        return np.zeros((8, 8), dtype=np.uint16), {}


def test_a_look_says_so(monkeypatch):
    import snap
    LookingCamera.seen = []
    monkeypatch.setattr(snap, "Camera", LookingCamera)
    snap.look(1.0, 300)
    assert LookingCamera.seen == [["Taking a look: 1 s"]] and activity.now() == []


def test_watching_for_stars_says_so(monkeypatch):
    import datetime as real
    import skywatch
    times = iter([real.datetime(2026, 10, 22, 21, 0)] * 2)

    class Clock:
        @staticmethod
        def now():
            return next(times, real.datetime(2026, 10, 22, 23, 0))   # one frame, then past the end
    LookingCamera.seen = []
    monkeypatch.setattr(skywatch, "Camera", LookingCamera)
    monkeypatch.setattr(skywatch, "publish", lambda *a, **k: None)
    monkeypatch.setattr(skywatch, "datetime", Clock)
    skywatch.watch("22:00", 0, 2.0)
    assert LookingCamera.seen == [["Watching for stars: a 2 s frame every 0 s until 22:00"]]
    assert activity.now() == []


def test_every_way_of_focusing_with_the_motor_says_what_it_is_doing():
    import focus
    for mode in ("focus", "walk", "find", "sweep", "step", "backlash"):
        assert focus.MODE_WORDS[mode]
    assert focus.MODE_WORDS["walk"] == "walking in to the sharpest" and focus.MODE_WORDS["find"] == "finding focus"
    assert focus.run_motor.__wrapped__ and focus.run.__wrapped__ and focus.run_check.__wrapped__
    # Each is the between-targets card's focus step (the stream tells the stages apart).
    assert activity.step_of(activity.PHASES["Focusing with the motor"]) == "focus"
    assert activity.step_of(activity.PHASES["Focusing"]) == "focus"


def test_focusing_and_polar_alignment_are_told_apart_stage_by_stage():
    import focus
    phase = activity.phase
    words = focus.MODE_WORDS
    assert phase([{"what": "Checking focus"}]) == "focus_check"
    assert phase([{"what": "Focusing with the motor", "detail": words["focus"]}]) == "focus_sweep"
    assert phase([{"what": "Focusing with the motor", "detail": words["sweep"]}]) == "focus_sweep"
    assert phase([{"what": "Focusing with the motor", "detail": words["walk"]}]) == "focus_walk"
    assert phase([{"what": "Focusing with the motor", "detail": words["find"]}]) == "focus_find"
    assert phase([{"what": "Focusing with the motor", "detail": words["step"]}]) == "focus_calibrate"
    assert phase([{"what": "Focusing with the motor", "detail": words["backlash"]}]) == "focus_calibrate"
    assert phase([{"what": "Focusing", "detail": "by the live view"}]) == "focus_aid"
    assert phase([{"what": "Focusing with the motor"}, {"what": "Fitting the focus curve"}]) == "focus_fit"
    assert phase([{"what": "Focusing with the motor"}, {"what": "Checking the fitted focus"}]) == "focus_verify"
    assert phase([{"what": "Polar check"}]) == "polar_measure" and phase([{"what": "Polar recheck"}]) == "polar_recheck"
    assert {"focus_check", "focus_sweep", "focus_walk", "focus_find", "focus_fit", "focus_verify",
            "polar_measure", "polar_adjust", "polar_recheck"} == set(activity.BROADCAST)
    # The between-targets card still has its four steps: every focus stage is "focus".
    assert [activity.step_of(p) for p in ("goto", "solve", "focus_fit", "focus_walk", "imaging", "polar_measure",
                                          None)] == ["goto", "solve", "focus", "focus", "imaging", None, None]
