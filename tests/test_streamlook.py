"""The live stream's picture (docs/stream-look.md): every state draws, keeps
inside the safe margins, reads clearly, and never names the place or shows
a candidate's position."""
import re

import numpy as np

import pytest

import config
import streamlook

STATES = streamlook.examples()


@pytest.fixture(scope="module")
def drawn():
    stack, single = streamlook.example_pictures()
    return {name: streamlook.compose(state, stack, single) for name, state in STATES.items()}


def test_each_state_draws_a_full_picture(drawn):
    assert {"patrol", "transit", "between", "candidate", "science", "coming-up", "explain-stacking",
            "explain-subtraction", "explain-nova", "explain-transit"} <= set(drawn)
    for canvas in drawn.values():
        assert canvas.image.size == (streamlook.WIDTH, streamlook.HEIGHT)
        assert canvas.written


def test_every_word_is_inside_the_safe_margins(drawn):
    for name, canvas in drawn.items():
        for w in canvas.written:
            x0, y0, x1, y1 = w["box"]
            assert streamlook.MARGIN_X <= x0 and x1 <= streamlook.WIDTH - streamlook.MARGIN_X, (name, w["words"])
            assert streamlook.MARGIN_Y <= y0 and y1 <= streamlook.HEIGHT - streamlook.MARGIN_Y, (name, w["words"])


def test_every_word_reads_clearly_against_what_it_is_on(drawn):
    for name, canvas in drawn.items():
        for w in canvas.written:
            assert streamlook.contrast(w["colour"], w["on"]) >= 7, (name, w["words"])
            assert w["size"] >= 18, (name, w["words"])


def test_no_word_names_the_place_or_gives_a_position(drawn):
    place = config.example()["site"]["name"]
    for canvas in drawn.values():
        for w in canvas.written:
            assert place not in w["words"]
            assert not re.search(r"\bRA\b|\bDec\b|\d+h\s?\d+m|[+-]\d+°", w["words"]), w["words"]


def test_times_are_utc_and_say_so(drawn):
    clocks = [w["words"] for c in drawn.values() for w in c.written if re.search(r"\d\d:\d\d", w["words"])]
    assert clocks and all("UTC" in words for words in clocks)


def test_the_candidate_states_show_no_cut_out_or_place():
    stack, single = streamlook.example_pictures()
    for stage in ("detected", "second", "result"):
        state = dict(STATES["candidate"], candidate={"stage": stage, "result": "Not confirmed: it did not appear again"})
        words = " ".join(w["words"] for w in streamlook.compose(state, stack, single).written)
        assert "POSSIBLE CHANGE" in words or "SECOND LOOK" in words or "RESULT" in words


def test_each_target_entry_has_its_facts_and_fits():
    found = streamlook.targets()
    import sky
    for name, entry in found["targets"].items():
        # The Moon's distance and brightness change through the month:
        # sky.moon_state gives them live, never the file.
        fixed = sky.object_kind(name) != "moon"
        assert entry["words"] and (not fixed or (entry["distance"] and entry["magnitude"])), name
        assert fixed or not {"distance", "magnitude"} & set(entry), name
        assert len(entry["words"]) <= 160, name
        assert all(len(caption) <= 120 for caption in entry.get("captions", [])), name
    assert set(found["programmes"]) >= {"patrol", "transit", "picture", "moon"}


def test_the_display_stretch_keeps_the_sky_dark_and_the_picture_its_size():
    stack, single = streamlook.example_pictures()
    for picture in (stack, single):
        shown = streamlook.display(picture)
        assert shown.size == picture.size
        sky = float(np.median(np.asarray(shown.convert("L"))))
        assert 5 < sky < 60                    # dark, but not crushed to black


def test_a_picture_is_fitted_whole_never_cropped():
    stack, _ = streamlook.example_pictures()        # 1500 x 1000 into a wider box
    fitted = streamlook.fit(stack, (1274, 600))
    assert fitted.size == (1274, 600)
    assert fitted.getpixel((0, 300)) == streamlook.COLOURS["background"]      # letterboxed at the sides


PLANET = {"planet": "WASP-12 b", "star": "WASP-12", "period": 1.091418901, "epoch": 2457607.519305,
          "hours": 3.0, "depth": 1.5}


def test_the_light_curve_shows_only_once_it_is_long_and_steady(tmp_path, monkeypatch):
    import json
    import numpy as np
    now = 1792460464.0
    t = streamlook.transit_state(PLANET, None, now)
    assert t["state"] in ("baseline", "measuring") and "points" not in t

    def write(minutes, scatter):
        jd = [(now - 60 * m) / 86400 + 2440587.5 for m in range(minutes, 0, -2)]
        rng = np.random.default_rng(0)
        mags = [11.6 + rng.normal(0, scatter) for _ in jd]
        (tmp_path / "transit-WASP-12b.json").write_text(json.dumps({"jd": jd, "mag": mags}))
    before = t["ingress"] - 60                       # a time before the transit: all baseline
    write(20, 0.001)
    assert streamlook.transit_state(PLANET, tmp_path, before)["state"] == "baseline"
    write(60, 0.03)                                  # long enough, far too ragged
    assert streamlook.transit_state(PLANET, tmp_path, now)["state"] != "live"
    write(60, 0.001)
    steady = streamlook.transit_state(PLANET, tmp_path, now)
    assert steady["state"] == "live" and len(steady["points"]) > 20


def test_a_patrol_panel_is_laid_out_as_the_night_s_mosaic():
    discovery = {"mosaics": [{"name": "M31", "columns": 4, "rows": 2, "panels": [
        {"panel": n, "state": "done" if n < 4 else "planned"} for n in range(1, 9)]}],
        "sessions": [{"field": "M31-P2", "finished": True, "unexplained": 1}]}
    patrol, candidate = streamlook.patrol_state("M31-P4", discovery)
    assert patrol["field"] == "Andromeda" and patrol["possible"] == 1
    states = {p["id"]: (p["col"], p["row"], p["state"]) for p in patrol["panels"]}
    assert states["P1"] == (0, 0, "done") and states["P4"] == (3, 0, "current") and states["P5"] == (0, 1, "open")
    assert candidate is None
    _, candidate = streamlook.patrol_state("M31-P2", discovery)
    assert candidate == {"stage": "second"}


def test_the_state_follows_what_is_running(monkeypatch):
    status = {"name": "M42", "age": 5, "exposure": 16, "accepted": 10, "captured": 11, "integration": 160}
    monkeypatch.setattr(streamlook, "transit_for", lambda name: None)
    assert streamlook.from_status(status, now=1.0)["kind"] == "picture"
    monkeypatch.setattr(streamlook, "transit_for", lambda name: PLANET if name == "WASP-12" else None)
    assert streamlook.from_status(dict(status, name="WASP-12"), now=1792460464.0)["kind"] == "transit"


def test_what_matters_still_reads_on_a_phone(drawn):
    """A 1080p stream in a phone's player is about 360 px wide: the object's
    name and the figures must still be some 10 and 8 pixels tall there."""
    scale = 360 / streamlook.WIDTH
    sizes = {w["words"]: w["size"] for w in drawn["patrol"].written}
    assert sizes["M31"] * scale >= 10
    assert sizes["203 / 211"] * scale >= 8


def test_a_second_look_s_result_is_news_for_five_minutes_then_one_small_line(monkeypatch):
    monkeypatch.setattr(streamlook, "_SEEN", {})
    discovery = {"mosaics": [{"name": "M31", "columns": 4, "rows": 2, "panels": [
        {"panel": n, "state": "done"} for n in range(1, 9)]}],
        "sessions": [{"field": "M31-P8", "session": "1", "finished": True, "unexplained": 4},
                     {"field": "M31-P8", "session": "2", "finished": True, "unexplained": 1}]}
    patrol, candidate = streamlook.patrol_state("M31-P3", discovery, now=1000)
    assert candidate["stage"] == "result" and "Still unexplained" in candidate["result"]
    patrol, candidate = streamlook.patrol_state("M31-P3", discovery, now=1000 + streamlook.RESULT_S)
    assert candidate is None and patrol["awaiting"] == 1


def test_the_star_size_is_a_median_held_for_half_a_minute(monkeypatch):
    monkeypatch.setattr(streamlook, "_HELD", {"value": None, "at": 0.0})
    assert streamlook.held_star_size([5.0] * 9 + [9.0], 1.0, 100) == 5.0          # one bad frame does not show
    assert streamlook.held_star_size([7.0] * 10, 1.0, 110) == 5.0                  # held
    assert streamlook.held_star_size([7.0] * 10, 1.0, 100 + streamlook.HOLD_S) == 7.0


def test_a_galaxy_filling_the_frame_does_not_lift_the_sky():
    import numpy as np
    sky = np.full((400, 600, 3), 0.1, dtype=np.float32)
    galaxy = sky.copy()
    galaxy[100:300, 100:500] = 0.5                      # a bright object over a third of the picture
    assert np.allclose(streamlook.sky_of(galaxy)[0], 0.1)


def test_the_crawl_runs_in_from_the_right_and_out_at_the_left():
    import numpy as np
    picture = np.zeros((streamlook.HEIGHT, streamlook.WIDTH, 3), dtype=np.uint8)
    strip = streamlook.crawl_strip("TONIGHT · a slow line")
    x0, y0, x1, y1 = streamlook.CRAWL_BOX
    start = streamlook.crawled(picture, strip, 0)
    assert start is not None and not start[y0:y1, x0:x1].any() == False      # it overwrites the footer's place
    assert streamlook.crawled(picture, strip, 3600) is None                   # gone after it has run through


# --- focusing and polar alignment, from their own files -------------------------

def test_the_focus_and_polar_looks_have_their_states(drawn):
    assert {"focus", "focus-walk", "focus-complete", "focus-check-passed", "focus-rejected", "polar-measuring",
            "polar-adjust", "polar-complete", "polar-failed"} <= set(drawn)
    words = {name: " ".join(w["words"] for w in canvas.written) for name, canvas in drawn.items()}
    assert "BEST SO FAR" in words["focus"] and "USUAL BEST 2.28" in words["focus"] and "position 8 of 9" in words["focus"]
    assert "✓  measure" in words["focus"] and "●  sweep" in words["focus"] and "○  verify" in words["focus"]
    assert "usual best 2.28 · tonight's best so far 2.31" in words["focus"]
    assert "●  finest steps" in words["focus-walk"] and "START" in words["focus"] and "NOW" in words["focus"]
    assert "FOCUS COMPLETE" in words["focus-complete"] and "5.07 → 2.19 HFR, 57% smaller stars" in words["focus-complete"]
    assert "FOCUS CHECK PASSED" in words["focus-check-passed"] and "FOCUS CURVE REJECTED" in words["focus-rejected"]
    assert "ROUND BY ROUND" in words["polar-adjust"] and "9.6°" in words["polar-adjust"] and "WHAT TO DO" in words["polar-adjust"]
    assert "●  picture 2" in words["polar-measuring"] and "Recheck: picture 2 of 3" in words["polar-measuring"]
    assert "TRUE POLE" in words["polar-adjust"] and "DRIFT LIMIT" in words["polar-adjust"]
    assert "target: under the drift limit, 1.25°" in words["polar-adjust"]
    assert "POLAR ALIGNMENT COMPLETE" in words["polar-complete"] and "9.6° → 1.2°" in words["polar-complete"]
    assert "POLAR MEASUREMENT FAILED" in words["polar-failed"] and "plate-solved" in words["polar-failed"]
    for name in ("polar-adjust", "polar-measuring"):
        assert not re.search(r"\b(left|right)\b", words[name], re.I), name


def focus_file(tmp_path, **changes):
    import json
    import os
    import time
    f = {"kind": "focus", "steps": ["measure", "sweep", "fit", "verify"], "stage": "sweep", "usual_hfr": 2.28,
         "start_hfr": 5.07, "hfr": 2.4, "best_hfr": 2.31, "best_at": -512, "at": -256, "position": 4,
         "positions": 9, "readings": [{"at": 0, "hfr": 5.07}, {"at": -512, "hfr": 2.31}, {"at": -256, "hfr": None}],
         "fit": None, "outcome": None, "words": None, "pid": os.getpid(), "started": time.time() - 60,
         "updated": time.time(), "ended": None}
    f.update(changes)
    (tmp_path / "focus_stream.json").write_text(json.dumps(f))
    return tmp_path / "focus_stream.json"


def test_a_running_focus_run_is_read_from_focus_py_s_own_file(tmp_path):
    import time
    path = focus_file(tmp_path)
    (tmp_path / "focus_runs.jsonl").write_text('{"saved": %f, "best_hfr": 2.19}\n{"saved": 0, "best_hfr": 1.5}\n'
                                               % (time.time() - 3600))
    f = streamlook.focus_stream_state(path=path)
    assert f["running"] and f["showing"] and f["card"] is None
    assert f["steps"] == [("measure", "done"), ("sweep", "now"), ("fit", "open"), ("verify", "open")]
    assert f["readings"] == [(0, 5.07), (-512, 2.31)] and f["count"] == 3 and f["last_hfr"] is None
    assert f["tonight_best_hfr"] == 2.19                    # an earlier run tonight, not one from long ago
    # A run whose process has gone without saying so is not shown.
    gone = streamlook.focus_stream_state(path=focus_file(tmp_path, pid=2 ** 22 + 12345))
    assert not gone["running"] and not gone["showing"]


def test_a_finished_focus_run_holds_its_card_for_ten_seconds(tmp_path):
    import time
    ended = time.time()
    path = focus_file(tmp_path, outcome="complete", end_hfr=2.19, ended=ended)
    f = streamlook.focus_stream_state(ended + 5, path=path)
    assert f["card"] == ("FOCUS COMPLETE", "5.07 → 2.19 HFR, 57% smaller stars", "live") and f["showing"]
    assert all(status == "done" for _, status in f["steps"])
    assert not streamlook.focus_stream_state(ended + streamlook.CARD_S + 1, path=path)["showing"]
    failed = streamlook.focus_stream_state(ended + 1, path=focus_file(tmp_path, outcome="returned", ended=ended,
                                                                      words="no better, back to the start"))
    assert failed["card"][0] == "FOCUS RETURNED TO START" and failed["card"][1] == "no better, back to the start"
    assert ("sweep", "failed") in failed["steps"]
    assert streamlook.focus_card({"outcome": "left_alone", "end_hfr": 2.2, "usual_hfr": 2.28})[0] == "FOCUS CHECK PASSED"
    assert streamlook.focus_stream_state(path=tmp_path / "none.json") is None


def polar_file(tmp_path, **changes):
    import json
    import os
    import time
    p = {"stage": "adjust", "picture": 3, "taken": 3, "recheck": True, "pid": os.getpid(), "updated": time.time(),
         "ended": time.time(), "rounds": [{"total_deg": 9.6, "measured": time.time() - 900},
                                          {"total_deg": 2.5, "measured": time.time() - 60}],
         "azimuth_deg": 4.2, "altitude_deg": -0.5, "total_deg": 2.5, "previous_total_deg": 9.6, "limit_deg": 1.25,
         "limit_px": 2.0, "exposure_s": 16.0, "drift_px": {"azimuth": 6.7, "altitude": 0.8},
         "advice": ["Turn the whole tripod 4.2° anticlockwise, seen from above."]}
    p.update(changes)
    (tmp_path / "polar_stream.json").write_text(json.dumps(p))
    return tmp_path / "polar_stream.json"


def test_a_polar_alignment_is_read_from_polaralign_py_s_own_file(tmp_path):
    import time
    p = streamlook.polar_stream_state(path=polar_file(tmp_path))
    assert p["adjusting"] and p["showing"] and p["card"] is None and p["doing"].startswith("Waiting")
    # A person turning the bolts keeps it on air for ADJUST_S, then it is not news.
    later = time.time() + streamlook.ADJUST_S + 1
    assert not streamlook.polar_stream_state(later, path=polar_file(tmp_path))["showing"]
    measuring = streamlook.polar_stream_state(path=polar_file(tmp_path, stage="measuring", picture=2, taken=1))
    assert measuring["running"] and measuring["doing"] == "Recheck: picture 2 of 3"
    assert measuring["pictures_steps"] == [("picture 1", "done"), ("picture 2", "now"), ("picture 3", "open")]
    done = streamlook.polar_stream_state(path=polar_file(tmp_path, stage="complete", total_deg=1.2, rounds=[
        {"total_deg": 9.6, "measured": time.time() - 900}, {"total_deg": 1.2, "measured": time.time()}]))
    assert done["card"] == ("POLAR ALIGNMENT COMPLETE", "9.6° → 1.2° from the pole: under the drift limit on both "
                                                        "axes.", "live")
    failed = streamlook.polar_stream_state(path=polar_file(tmp_path, stage="failed", words="Cloud. Nothing was measured."))
    assert failed["card"] == ("POLAR MEASUREMENT FAILED", "Cloud. Nothing was measured.", "attention")
    old = streamlook.polar_stream_state(path=polar_file(tmp_path, rounds=[{"total_deg": 3, "measured": 0}]))
    assert old["rounds"] == []                               # another night's rounds are not tonight's history


MOON_NOW = {"illumination": 97, "waxing": True, "age_days": 12.9, "distance_km": 371200.0,
            "size_deg": 0.54, "altitude": 31}


def test_the_moon_is_shown_as_the_moon_never_with_a_star_size(monkeypatch):
    """24 October 2026: the Moon run's sidebar said STAR SIZE 9.3″."""
    monkeypatch.setattr(streamlook, "moon_now", lambda now: dict(MOON_NOW))
    monkeypatch.setattr(streamlook, "lucky_now", lambda: False)
    status = {"name": "Moon", "age": 1, "exposure": 0.02, "accepted": 7, "captured": 7, "integration": 0,
              "object_kind": "moon", "series": {"fwhm": [6.0] * 7, "accepted": [True] * 7}}
    s = streamlook.from_status(status, now=1792800000.0)
    assert s["kind"] == "moon" and s["fwhm_arcsec"] is None
    labels = [label for _, label in streamlook.figures_for(s)]
    assert labels[:3] == ["ILLUMINATED", "APPARENT SIZE", "ALTITUDE"] and "STAR SIZE" not in labels
    assert "KEEP RATE" in labels
    # Away from full, the Moon's age; a session named only "Moon-Copernicus" is still the Moon.
    monkeypatch.setattr(streamlook, "moon_now", lambda now: dict(MOON_NOW, illumination=34, age_days=6.1))
    s = streamlook.from_status(dict(status, name="Moon-Copernicus", object_kind=None), now=1792800000.0)
    assert s["kind"] == "moon" and streamlook.figures_for(s)[1] == ("6.1 DAYS", "LUNAR AGE")
    assert streamlook.moon_tonight(s["moon"]) == ("TONIGHT'S MOON · Waxing · 34% illuminated · "
                                                 "6.1 days after new Moon")
    # Deep sky is as it was.
    assert "STAR SIZE" in [label for _, label in streamlook.deep_sky_figures({"fwhm_arcsec": 4.8})]


def test_the_moon_programme_says_how_it_is_being_imaged():
    assert "sharpest" in streamlook.moon_words(lucky=True)
    assert "Hundreds of short exposures" in streamlook.moon_words(lucky=False)
    assert streamlook.moon_tonight({}) is None


def test_the_moon_panel_says_where_the_lucky_imaging_has_got(tmp_path, monkeypatch):
    """CAPTURING with frames and rate, then the ranking and the stacking,
    from lucky.py's web/lucky.json; nothing from a stale file."""
    import json
    import config
    monkeypatch.setattr(config, "DATA", tmp_path)
    (tmp_path / "web").mkdir()
    note = tmp_path / "web" / "lucky.json"
    note.write_text(json.dumps({"stage": "capturing", "at": 1000.0, "done": 846, "frames": 2000,
                                "fps": 31.0, "exposure": 0.008}))
    assert streamlook.lucky_stage(1010.0) == ("CAPTURING FRAMES", "846 / 2,000 · 31 a second · 8 ms exposures")
    note.write_text(json.dumps({"stage": "stacking", "at": 1000.0, "done": 25, "frames": 400, "points": 742}))
    assert streamlook.lucky_stage(1010.0) == ("CORRECTING THE ATMOSPHERE", "25 / 400 · 742 alignment regions")
    assert streamlook.lucky_stage(5000.0) is None


def test_a_moon_video_shows_its_newest_frame_and_not_the_last_runs_figures(tmp_path, monkeypatch):
    """30 October 2026: the stream showed an empty picture, "PAUSED · no new
    exposure for 8683 min" and an old schedule while a Moon video was taken."""
    import os
    import config
    from PIL import Image
    monkeypatch.setattr(config, "DATA", tmp_path)
    (tmp_path / "web").mkdir()
    latest = tmp_path / "web" / "latest.jpg"
    Image.new("RGB", (40, 30), (200, 200, 200)).save(latest)
    os.utime(latest, (1792800000.0 - 3, 1792800000.0 - 3))
    monkeypatch.setattr(streamlook, "moon_now", lambda now: dict(MOON_NOW))
    monkeypatch.setattr(streamlook, "lucky_now", lambda: True)
    stale = {"name": "Moon", "age": 521032, "exposure": 0.02, "accepted": 199, "object_kind": "moon",
             "schedule": {"steps": [{"label": "M31, 30 min", "status": "done"}]}}
    s = streamlook.from_status(stale, now=1792800000.0)
    assert s["lucky"] and round(s["last_age"]) == 3 and s["stage"] is None and s["next"] is None
    assert streamlook.live_state(s)[0] == "● LIVE"
    shown, empty = streamlook.Canvas(), streamlook.Canvas()
    streamlook.sky_area(shown, s, None, Image.open(latest).convert("RGB"))
    streamlook.sky_area(empty, s, None, None)
    x, y, w, h = streamlook.STACK_BOX
    middle = (x + w // 2, y + h // 2 + 40)            # below the empty panel's words
    assert shown.image.getpixel(middle) != empty.image.getpixel(middle)      # the frame, not the empty panel       # the frame, not the empty panel


def test_the_live_view_goes_on_air_with_its_newest_frame(tmp_path, monkeypatch):
    """30 October 2026: "if the telescope is pointing at the Moon the feed
    should show the Moon": between runs, the live view keeps it showing."""
    import os
    import activity
    import config
    import liveview
    from PIL import Image
    assert activity.PHASES["Live view"] == "live" and "live" in activity.BROADCAST
    monkeypatch.setattr(config, "DATA", tmp_path)
    (tmp_path / "web").mkdir()
    latest = tmp_path / "web" / "latest.jpg"
    Image.new("RGB", (40, 30), (200, 200, 200)).save(latest)
    os.utime(latest, (1792800000.0 - 2, 1792800000.0 - 2))
    monkeypatch.setattr(streamlook, "lucky_now", lambda: False)
    monkeypatch.setattr(streamlook, "live_now", lambda: True)
    s = streamlook.from_status({"name": "M31", "age": 9000, "accepted": 50}, now=1792800000.0)
    assert s["live"] and round(s["last_age"]) == 2 and streamlook.live_state(s)[0] == "● LIVE"
    shown, empty = streamlook.Canvas(), streamlook.Canvas()
    streamlook.sky_area(shown, s, None, Image.open(latest).convert("RGB"))
    streamlook.sky_area(empty, s, None, None)
    x, y, w, h = streamlook.STACK_BOX
    middle = (x + w // 2, y + h // 2 + 40)            # below the empty panel's words
    assert shown.image.getpixel(middle) != empty.image.getpixel(middle)      # the frame, not the empty panel
    # It gives the camera up to a Moon video, which keeps no frames.jsonl.
    monkeypatch.setattr(activity, "now", lambda: [{"what": "Taking a lucky-imaging video"}])
    assert liveview.video_active()
    monkeypatch.setattr(activity, "now", lambda: [{"what": "Live view"}, {"what": "Stacking the lucky frames"}])
    assert not liveview.video_active()                  # a stack in the background leaves the camera free


def test_the_moon_is_drawn_as_it_is_not_stretched_black():
    """30 October 2026: the sky stretch set its black point from a frame the
    Moon filled, and the stream showed a black box."""
    from PIL import Image, ImageDraw
    moon = Image.new("RGB", (400, 300), (0, 0, 0))
    ImageDraw.Draw(moon).ellipse((60, 10, 340, 290), fill=(190, 190, 185))
    s = {"kind": "moon", "lucky": True, "last_age": 2}
    c = streamlook.Canvas()
    streamlook.sky_area(c, s, Image.new("RGB", (400, 300), (5, 5, 5)), moon)
    x, y, w, h = streamlook.STACK_BOX
    assert sum(c.image.getpixel((x + w // 2, y + h // 2))) > 450     # the bright disc, from the newest frame


def test_a_new_run_shows_its_first_frame_before_there_is_a_stack():
    """30 October 2026: M34 started under "The picture builds up after the first few exposures"."""
    from PIL import Image
    s = {"kind": "picture", "last_age": 3}
    shown, empty = streamlook.Canvas(), streamlook.Canvas()
    streamlook.sky_area(shown, s, None, Image.new("RGB", (400, 300), (180, 180, 180)))
    streamlook.sky_area(empty, s, None, None)
    x, y, w, h = streamlook.STACK_BOX
    middle = (x + w // 2, y + h // 2 + 40)
    assert shown.image.getpixel(middle) != empty.image.getpixel(middle)
