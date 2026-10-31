"""What the stream shows, decided in one place (director.py): the target
from what the telescope was last aimed at, the camera's fresh picture over
any older state, the schedule never ending a night the camera is still
seeing, and each scene drawn as a viewer sees it."""
import pytest

import config
import director
import streamlook

NOW = 1792800000.0


def given(status=None, target=None, phase=None, image_age=None, run_imaging=False, schedule_over=False,
          between=False, lucky=None, procedure=None):
    return {"now": NOW, "status": status or {}, "target": target, "phase": phase, "image_age": image_age,
            "run_imaging": run_imaging, "schedule_over": schedule_over, "between": between, "lucky": lucky,
            "procedure": procedure, "transit": False}


def aimed(name, ago, state="reached", **more):
    import sky
    return dict({"name": name, "kind": sky.object_kind(name), "set_at": NOW - ago, "state": state}, **more)


M31_OLD = {"name": "M31", "age": 9000, "accepted": 50, "running": False, "stack": {"current": True}}
MOON_OLD = {"name": "Moon", "age": 9000, "object_kind": "moon", "running": False, "stack": {"current": True}}


@pytest.mark.parametrize("fresh, target, run, imaging, schedule_over, scene, name", [
    # 30 October 2026: the telescope filmed the Moon while the stream named M31 and said the night was over.
    (True, aimed("Moon", 600), M31_OLD, False, True, "moon_live", "Moon"),
    (True, aimed("Moon", 600), {}, False, True, "moon_live", "Moon"),
    (True, aimed("M31", 60), MOON_OLD, False, False, "deep_sky_live", "M31"),
    (False, aimed("Moon", 3600), MOON_OLD, False, False, "moon_stack", "Moon"),
    (False, None, M31_OLD, False, True, "end", None),
    # A run imaging names the target over an older GoTo, and its stack is the picture.
    (True, aimed("M33", 3600), dict(M31_OLD, age=10, running=True), True, False, "deep_sky_stack", "M31"),
])
def test_the_freshest_truth_wins_whatever_the_old_run_and_the_schedule_say(fresh, target, run, imaging,
                                                                          schedule_over, scene, name):
    phase = "imaging" if imaging else "live" if fresh else None
    d = director.direct(given(run, target, phase, 3 if fresh else 7200, imaging, schedule_over))
    assert (d["scene"], d["target"]) == (scene, name)
    if fresh:
        assert d["on_air"] and d["scene"] != "end"
    if run.get("name") and run["name"] != name:
        assert not d["run_current"] and any(run["name"] in why for why in d["ignored"])


def test_target_programme_and_activity_are_kept_apart():
    moon = director.direct(given(M31_OLD, aimed("Moon", 60), "lucky", 1, lucky="capturing"))
    assert (moon["target"], moon["programme"], moon["activity"]) == ("Moon", "lunar lucky imaging", "capturing")
    assert moon["scene"] == "moon_capture" and moon["image"] == "latest"
    mineral = director.direct(given(M31_OLD, aimed("Moon", 60), "mineral", 900, lucky="mineral"))
    assert (mineral["scene"], mineral["programme"], mineral["on_air"]) == ("moon_mineral", "mineral Moon", True)
    patrol = director.direct(given(dict(M31_OLD, name="M31-P3", age=10, running=True), None, "imaging", 10, True))
    assert (patrol["target"], patrol["programme"], patrol["activity"]) == ("M31-P3", "nova patrol", "imaging")


def test_focusing_and_polar_alignment_outrank_the_fresh_frame():
    d = director.direct(given(M31_OLD, aimed("M31", 60), "focus_walk", 2, procedure="focus"))
    assert d["scene"] == "focus" and d["image"] == "procedure" and d["priority"] > director.PRIORITY["live"]


def test_a_paused_run_keeps_its_stack_and_its_name_without_a_goto_on_record():
    paused = dict(M31_OLD, age=600, running=True)
    d = director.direct(given(paused, None, None, 600))
    assert (d["scene"], d["target"], d["run_current"], d["on_air"]) == ("deep_sky_stack", "M31", True, False)


def test_a_new_target_or_activity_is_announced_for_a_few_seconds():
    first = director.direct(given(M31_OLD, aimed("Moon", 5), "live", 2))
    assert first["headline"]["words"] == "NOW OBSERVING: THE MOON"
    later = director.direct(dict(given(M31_OLD, aimed("Moon", 5), "live", 2), now=NOW + 2), first)
    assert later["headline"] == first["headline"]                        # held for its seconds
    capturing = director.direct(dict(given(M31_OLD, aimed("Moon", 5), "lucky", 1, lucky="capturing"),
                                     now=NOW + 60), later)
    assert capturing["headline"]["words"] == "LUCKY IMAGING STARTED"
    quiet = director.direct(dict(given(M31_OLD, aimed("Moon", 5), "lucky", 1, lucky="capturing"),
                                 now=NOW + 60 + director.HEADLINE_S + 1), capturing)
    assert quiet["headline"] is None


def test_the_target_is_aimed_kept_for_the_night_and_cleared(tmp_path, monkeypatch):
    monkeypatch.setattr(director, "TARGET_FILE", tmp_path / "target.json")
    assert director.aimed(NOW) is None
    director.aim("Moon", now=NOW)
    assert director.aimed(NOW + 60) == {"name": "Moon", "kind": "moon", "set_at": NOW, "state": "slewing",
                                        "state_at": NOW, "confirmed": None}
    director.mark("Moon", "reached", confirmed="mount", miss_deg=0.123, now=NOW + 30)
    t = director.aimed(NOW + 60)
    assert (t["state"], t["confirmed"], t["miss_deg"], t["set_at"]) == ("reached", "mount", 0.12, NOW)
    assert director.observing("Moon", NOW + 60) and not director.observing("M31", NOW + 60)
    assert director.aimed(NOW + director.TARGET_S + 1) is None           # the safety net only
    director.clear()
    assert director.aimed(NOW + 60) is None


def test_a_damaged_target_record_never_stops_a_goto(tmp_path, monkeypatch):
    monkeypatch.setattr(director, "TARGET_FILE", tmp_path / "target.json")
    (tmp_path / "target.json").write_text('{"name": "Moon", "set_at": "yesterday"}')
    assert director.observing("Moon") is False


def test_a_goto_that_never_said_how_it_ended_counts_as_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(director, "TARGET_FILE", tmp_path / "target.json")
    director.aim("Moon", now=NOW)
    assert director.aimed(NOW + 60)["state"] == "slewing"
    assert director.aimed(NOW + director.SLEW_S + 1)["state"] == "failed"   # its process was killed


def test_a_video_keeps_the_gotos_word_or_takes_the_persons(tmp_path, monkeypatch):
    monkeypatch.setattr(director, "TARGET_FILE", tmp_path / "target.json")
    director.aim("Jupiter")
    director.mark("Jupiter", "centred", confirmed="plate solve")
    director.filming("Jupiter")
    assert (director.aimed()["state"], director.aimed()["confirmed"]) == ("centred", "plate solve")
    director.filming("Saturn")                    # aimed by hand: observed as the person says
    assert (director.aimed()["name"], director.aimed()["state"]) == ("Saturn", "filming")


@pytest.mark.parametrize("state, more, named, words", [
    ("slewing", {}, "Moon", "MOVING TO THE MOON"),
    ("centring", {}, "Moon", "CENTRING THE MOON"),
    ("reached", {"confirmed": "mount"}, "Moon", "NOW OBSERVING: THE MOON"),
    ("centred", {"confirmed": "camera"}, "Moon", "NOW OBSERVING: THE MOON"),
    ("failed", {}, None, None),
    ("off", {"miss_deg": 6.4}, None, None),
])
def test_a_target_is_only_observed_once_the_telescope_has_got_there(state, more, named, words):
    """A GoTo asked for is not a GoTo done: the stream never says it is
    observing what the telescope was only sent to."""
    d = director.direct(given(M31_OLD, aimed("Moon", 30, state, **more), "goto", None))
    assert d["target"] == named
    assert (d["headline"] or {}).get("words") == words
    if named is None:
        assert any(why.startswith("aimed at Moon: ") for why in d["ignored"])
    if state == "off":
        assert "6.4°" in " ".join(d["ignored"])


def test_moving_centring_then_observing_are_each_announced_once():
    told = []
    before = None
    for i, state in enumerate(["slewing", "slewing", "centring", "centred", "centred"]):
        d = director.direct(dict(given(M31_OLD, aimed("Moon", 30, state), "goto", None),
                                 now=NOW + i * (director.HEADLINE_S + 1)), before)
        if d["headline"] and d["headline"] != (before or {}).get("headline"):
            told.append(d["headline"]["words"])
        before = d
    assert told == ["MOVING TO THE MOON", "CENTRING THE MOON", "NOW OBSERVING: THE MOON"]


def test_update_writes_the_answer_and_the_report_says_what_it_left_out(tmp_path, monkeypatch):
    monkeypatch.setattr(director, "STATE_FILE", tmp_path / "broadcast.json")
    monkeypatch.setattr(director, "gather", lambda st, now=None, procedure=False:
                        given(M31_OLD, aimed("Moon", 60), "live", 2, schedule_over=True))
    d = director.update(M31_OLD, NOW)
    assert director.last()["scene"] == d["scene"] == "moon_live"
    report = director.report(d)
    for words in ("target:     Moon", "aim:        reached", "scene:      moon_live", "status target M31",
                  "schedule run to its end"):
        assert words in report


def test_gather_reads_the_aimed_target_lucky_stage_and_newest_picture(tmp_path, monkeypatch):
    import json
    import os

    import activity
    import stream
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(stream, "WEB", tmp_path / "web")
    monkeypatch.setattr(director, "TARGET_FILE", tmp_path / "cache" / "target.json")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "latest.jpg").write_bytes(b"x")
    os.utime(tmp_path / "web" / "latest.jpg", (NOW - 4, NOW - 4))
    (tmp_path / "web" / "lucky.json").write_text(json.dumps({"stage": "capturing", "at": NOW - 1}))
    monkeypatch.setattr(activity, "now", lambda *a, **k: [{"what": "Taking a lucky-imaging video"}])
    director.aim("Moon", now=NOW - 30)
    got = director.gather({}, NOW, procedure=None)
    assert got["target"]["name"] == "Moon" and got["phase"] == "lucky" and got["lucky"] == "capturing"
    assert round(got["image_age"]) == 4
    assert director.direct(got)["scene"] == "moon_capture"


# --- what the viewer sees -----------------------------------------------------------

def written(canvas):
    return " ".join(w["words"] for w in canvas.written)


def test_each_scene_is_drawn_as_the_viewer_should_see_it(tmp_path, monkeypatch):
    """Rendered, not only decided: on 30 October 2026 the state was right
    and the Moon was still drawn as a black box."""
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(streamlook, "moon_now", lambda now: {"illumination": 80, "waxing": True, "age_days": 10.2,
                                                             "distance_km": 371000.0, "size_deg": 0.54,
                                                             "altitude": 31})
    drawn = streamlook.scenes(tmp_path / "scenes", NOW, say=lambda line: None)
    assert {"moon-live", "moon-capture", "moon-stack", "moon-mineral", "deep-sky-stack", "deep-sky-live",
            "slew", "end"} <= set(drawn)
    x, y, w, h = streamlook.STACK_BOX
    for name in ("moon-live", "moon-capture", "moon-stack", "moon-mineral"):
        d, canvas = drawn[name]
        words = written(canvas)
        assert "THE MOON" in words and "M31" not in words and "STAR SIZE" not in words, name
        assert "FRAMES KEPT" not in words, name                         # the old M31 run's figures
        assert sum(canvas.image.getpixel((x + w // 2, y + h // 2 + 120))) > 300, name      # the disc, not black
        assert (tmp_path / "scenes" / f"{name}.png").exists()
    assert "LIVE VIEW" in written(drawn["moon-live"][1])
    assert "371,000 KM" in written(drawn["moon-live"][1])
    assert "CAPTURING THE SHARPEST MOMENTS" in written(drawn["moon-capture"][1])
    assert "CORRECTING THE ATMOSPHERE" in written(drawn["moon-stack"][1])
    assert "REVEALING THE MOON'S SUBTLE COLOUR" in written(drawn["moon-mineral"][1])
    for name in ("moon-stack", "moon-mineral"):              # the camera is done with: not paused
        assert "● PROCESSING" in written(drawn[name][1]) and "PAUSED" not in written(drawn[name][1])
    # A target just aimed at is announced across the top of the picture.
    assert "NOW OBSERVING: M31" in written(drawn["deep-sky-live"][1])
    assert "NOW OBSERVING: THE MOON" in written(drawn["moon-live"][1])
    # The M31 run imaging shows its own figures; the M31 live view after the Moon run shows none of the Moon's.
    assert "FRAMES KEPT" in written(drawn["deep-sky-stack"][1])
    assert "ILLUMINATED" not in written(drawn["deep-sky-live"][1])


def test_the_debug_overlay_writes_the_answer_over_a_copy(tmp_path):
    from PIL import Image
    picture = Image.new("RGB", (streamlook.WIDTH, streamlook.HEIGHT), (0, 0, 0))
    d = director.direct(given(M31_OLD, aimed("Moon", 60), "live", 2, schedule_over=True))
    out = streamlook.debug_overlay(picture, director.report(d))
    assert out is not picture and out.getpixel((41, 200)) != (0, 0, 0) and picture.getpixel((41, 200)) == (0, 0, 0)


def test_an_answer_that_cannot_be_worked_out_never_stops_the_stream(tmp_path, monkeypatch):
    import stream
    monkeypatch.setattr(director, "STATE_FILE", tmp_path / "broadcast.json")
    monkeypatch.setattr(director, "gather", lambda *a, **k: 1 / 0)
    monkeypatch.setattr(stream, "seeing", lambda now=None: True)
    d = director.update({"name": "M31"}, NOW)
    assert d["on_air"] and d["run_current"] and d["target"] == "M31" and "division" in d["ignored"][0]
    monkeypatch.setattr(director.records, "write", lambda *a, **k: 1 / 0)
    director.aim("Moon")                                                 # inside a GoTo: never an error
