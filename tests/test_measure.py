"""The rig measuring itself: whether the telescope really turned, how well
the polar measurement repeats, how the camera keeps time, how the drift
answers the creep, how the pointing changes across the sky, and the one view
of what has and has not been measured. Nothing here has a mount or camera."""
import json
import math
import sys
import time

import numpy as np
import pytest
from scipy import ndimage

import agent
import camera_test
import config
import focus
import interface
import moved
import mount
import polaralign
import polaris
import simulator
import tracking
from simulator import SimulatedHandset
from test_interface import valid

SITE = config.example()["site"]
rng = np.random.default_rng(11)


def stars(name, shift=(0.0, 0.0), seed=0):
    xy, flux = simulator.star_field(name)
    return simulator.render(xy + shift, flux, 1.6, seed=seed)


def wall(seed, shift=0):
    """Something with detail and no stars: a lit tree, a rendered wall."""
    texture = ndimage.gaussian_filter(np.random.default_rng(seed).normal(0, 1, (1100, 1400)), 6) * 400
    return np.roll(texture, shift, axis=1)[:, :1300] + 2000 + rng.normal(0, 5, (1100, 1300))


# --- did the telescope really turn? ----------------------------------------------------

def test_two_frames_of_one_star_field_are_the_same_view_and_another_field_is_not():
    assert moved.compare(stars("M27"), stars("M27", (1.5, -0.8), seed=1)) == "same"      # only the tracking's drift
    assert moved.compare(stars("M27"), stars("M31", seed=1)) == "changed"


def test_blank_frames_say_nothing_even_with_the_same_hot_pixels_in_both():
    hot = np.zeros((1100, 1300))
    hot[rng.integers(0, 1100, 300), rng.integers(0, 1300, 300)] = 3000
    blank = lambda seed: 300 + np.random.default_rng(seed).normal(0, 5, (1100, 1300)) + hot
    assert moved.compare(blank(1), blank(2)) is None


def test_a_lit_tree_with_no_stars_is_known_again_by_its_detail():
    assert moved.compare(wall(1), wall(1)) == "same"
    assert moved.compare(wall(1), wall(1, shift=90)) == "changed"
    assert moved.compare(wall(1), wall(2)) is None                       # nothing in common: no verdict


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    """Where the movement check keeps what it judged, in a folder of the test's own."""
    monkeypatch.setattr(moved, "MOVED_FILE", tmp_path / "moved.json")
    monkeypatch.setattr(moved, "LOG_FILE", tmp_path / "moved_log.jsonl")
    monkeypatch.setattr(moved, "PAIRS", tmp_path / "moved")
    monkeypatch.setattr(config, "DEMO", False)
    return lambda: [json.loads(line) for line in moved.LOG_FILE.read_text(encoding="utf-8").splitlines()]


def test_the_same_view_twice_after_turns_that_should_have_changed_it_stops_the_survey(evidence):
    watch = moved.Watch()
    assert watch.check(wall(1), 0.0) is None                       # the first look: nothing to compare
    assert watch.check(wall(1), 30.0) == "same"                    # once could be chance
    with pytest.raises(interface.Refusal) as stop:
        watch.check(wall(1), 30.0, "bearing 150°, 40° up")
    assert stop.value.code_name == "MOUNT_NOT_MOVING" and "bearing 150°" in stop.value.message
    # It says how far the view moved beside how far the mount was turned.
    assert "it moved 0° where the mount was turned 30.0°" in stop.value.message
    assert not moved.MOVED_FILE.exists()
    # Both judgements are kept with their figures, and both pairs of pictures, to set the thresholds from.
    kept = evidence()
    assert [k["verdict"] for k in kept] == ["same", "same"] and kept[1]["where"] == "bearing 150°, 40° up"
    assert kept[0]["by"] == "detail" and kept[0]["sure"] >= moved.SURE
    assert kept[0]["expected_deg"] == 30.0 and kept[0]["observed_deg"] == 0
    assert len(list(moved.PAIRS.glob("*.jpg"))) >= 1
    assert moved.checked() == {"same": 2, "changed": 0, "undecided": 0}


def test_a_view_that_changes_is_remembered_as_proof_and_small_turns_are_not_judged(evidence):
    watch = moved.Watch()
    watch.check(stars("M27"), 0.0)
    assert watch.check(stars("M27", seed=1), 0.2) is None          # too small a turn to expect a new view
    assert watch.check(stars("M31", seed=2), 20.0) == "changed"
    assert "view changed" in json.loads(moved.MOVED_FILE.read_text(encoding="utf-8"))["how"]
    assert moved.separation(0, 40, 90, 40) == pytest.approx(65.6, abs=0.2)
    kept = evidence()
    assert len(kept) == 1 and kept[0]["by"] == "stars" and kept[0]["share_in_place"] < moved.SHARE
    assert kept[0]["observed_deg"] is None            # two different fields: nothing to measure a shift by


def test_the_figures_behind_a_verdict_are_given():
    same = moved.judge(stars("M27"), stars("M27", (1.5, -0.8), seed=1))
    assert same["verdict"] == "same" and same["by"] == "stars" and same["share_in_place"] >= moved.SHARE
    assert same["shift_px"] == pytest.approx(1.7, abs=0.4) and same["stars_before"] >= moved.STARS
    blank = moved.judge(300 + rng.normal(0, 5, (1100, 1300)), 300 + rng.normal(0, 5, (1100, 1300)))
    assert blank["verdict"] is None and blank["sure"] < moved.SURE


def test_a_correction_that_changes_nothing_is_proof_from_the_plate_solve(evidence):
    assert moved.unchanged((-1.78, 1.57), (-1.77, 1.58), "GoTo M27")     # 142' out, corrected, still 142' out
    assert not moved.MOVED_FILE.exists()
    assert not moved.unchanged((-1.78, 1.57), (-0.10, -0.19))            # the real first night
    assert "plate solve" in json.loads(moved.MOVED_FILE.read_text(encoding="utf-8"))["how"]
    assert not moved.unchanged((0.05, 0.03), (0.05, 0.03))               # too small to judge, and not kept
    kept = evidence()
    assert [(k["by"], k["verdict"]) for k in kept] == [("plate solve", "same"), ("plate solve", "changed")]
    assert kept[0]["expected_deg"] == pytest.approx(2.37, abs=0.01) and kept[0]["observed_deg"] < 0.02
    assert kept[1]["observed_deg"] == pytest.approx(2.43, abs=0.02) and kept[0]["where"] == "GoTo M27"
    # A turn of 12 degrees that shows as 12, and one that shows as nothing.
    assert not moved.solved(12.0, 11.8) and moved.solved(12.0, 0.4)


@pytest.fixture
def scope(tmp_path, monkeypatch):
    for name in ("CLOCK_FILE", "POINTING_FILE", "DRIFT_FILE", "RESPONSE_FILE", "SURVEY_FILE", "LAST_SOLVE", "HOME_FILE"):
        monkeypatch.setattr(mount, name, tmp_path / f"{name}.json")
    monkeypatch.setattr(mount, "LOCK_FILE", tmp_path / "MOTION_LOCKED")
    monkeypatch.setattr(mount, "SETTLE", 0)
    monkeypatch.setattr(moved, "MOVED_FILE", tmp_path / "moved.json")
    monkeypatch.setattr(moved, "LOG_FILE", tmp_path / "moved_log.jsonl")
    monkeypatch.setattr(polaralign, "POLAR_FILE", tmp_path / "polar.json")
    monkeypatch.setattr(polaralign, "SETTLE", 0)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    made = mount.Mount(handset=SimulatedHandset(slew_seconds=0))
    made.say = lambda *words: print(*words)
    return made


def reachable():
    """A named star the mount may go to at whatever hour the tests are run."""
    for star in mount.STARS:
        try:
            mount.plan_goto(star, SITE)
            return star
        except interface.Refusal:
            pass
    pytest.skip("no named star is within the limits just now")


def test_a_goto_whose_corrections_do_nothing_is_stopped(scope, monkeypatch):
    scope.can_solve = True
    monkeypatch.setattr(scope, "measure_miss", lambda target, site: (-1.78, 1.57))     # the same miss every time
    with pytest.raises(interface.Refusal) as stop:
        scope.goto_target(reachable(), SITE, solve=True)
    assert stop.value.code_name == "MOUNT_NOT_MOVING" and "142'" in stop.value.message


# --- polar alignment: does it repeat? -----------------------------------------------------

def test_three_solves_that_come_back_the_same_stop_the_polar_measurement(scope, monkeypatch):
    from astropy.time import Time
    scope.zenith(SITE)
    scope.goto((mount.true_sidereal(SITE) + 30) % 360, 30.0)       # 2 h east, well below the pole
    stuck = {"ra": float(mount.true_sidereal(SITE) + 30) % 360, "dec": 30.0}
    monkeypatch.setattr(scope, "where_really", lambda *a, **k: dict(stuck, when=Time.now()))
    with pytest.raises(interface.Refusal) as stop:
        polaralign.measure(scope, SITE, step=12)
    assert stop.value.code_name == "MOUNT_NOT_MOVING"


def test_repeated_measurements_give_their_scatter(scope, monkeypatch, capsys):
    answers = iter([(0.22, 0.05), (0.19, 0.02), (0.24, 0.06), (0.21, 0.04), (0.20, 0.03)])
    monkeypatch.setattr(polaralign, "measure", lambda *a, **k: next(answers))
    monkeypatch.setattr(mount, "Mount", lambda *a, **k: scope)
    monkeypatch.setattr(config, "load", config.example)
    scope.save_clock(SITE)
    args = type("Args", (), {"dry_run": False, "json": False, "step": 12.0, "repeat": 5})()
    result = polaralign.run(args)
    assert len(result["runs"]) == 5 and result["azimuth_deg"] == pytest.approx(0.21, abs=0.005)
    assert 0.01 < result["spread_deg"] < 0.03
    assert "scatter by 0.02°" in capsys.readouterr().out
    kept = json.loads(polaralign.POLAR_FILE.read_text(encoding="utf-8"))
    assert kept["repeats"] == 5 and kept["spread_deg"] == result["spread_deg"]
    # A single measurement afterwards keeps what is known of the scatter.
    monkeypatch.setattr(polaralign, "measure", lambda *a, **k: (0.1, 0.1))
    args.repeat = 1
    assert "runs" not in polaralign.run(args)
    assert json.loads(polaralign.POLAR_FILE.read_text(encoding="utf-8"))["spread_deg"] == result["spread_deg"]


def test_repeat_is_bounded_and_the_dry_run_says_how_many(scope):
    args = type("Args", (), {"dry_run": True, "json": False, "step": 12.0, "repeat": 5})()
    plan, notes = polaralign.run(args)
    assert plan["repeat"] == 5 and "5 times" in notes[0] and "Leave the bolts alone" in notes[0]
    args.repeat = 40
    with pytest.raises(interface.Refusal):
        polaralign.run(args)


def test_polaris_looks_less_far_after_a_recent_night_alignment(tmp_path, monkeypatch):
    monkeypatch.setattr(polaralign, "POLAR_FILE", tmp_path / "polar.json")
    assert polaris.aligned_says() is None
    polaralign.POLAR_FILE.write_text(json.dumps({"total_deg": 0.2, "measured": time.time() - 86400}))
    found = polaris.aligned_says()
    assert found["radius"] == pytest.approx(1.6, abs=0.06) and found["radius"] < polaris.RADIUS
    polaralign.POLAR_FILE.write_text(json.dumps({"total_deg": 0.2, "measured": time.time() - 30 * 86400}))
    assert polaris.aligned_says() is None                          # too long ago to count on
    polaralign.POLAR_FILE.write_text(json.dumps({"total_deg": 5.2, "measured": time.time()}))
    assert polaris.aligned_says() is None                          # too far out to narrow anything


# --- the camera's timekeeping ----------------------------------------------------------------

def test_frames_that_arrive_sooner_than_their_exposures_show_a_short_exposure():
    short = camera_test.timing_fit([{"asked_s": a, "cycle_s": 0.9 + 0.63 * a} for a in camera_test.ASKED])
    assert short["seconds_per_second_asked"] == pytest.approx(0.63, abs=0.005) and short["exposes_short"]
    assert "63%" in short["verdict"] and short["overhead_s"] == pytest.approx(0.9, abs=0.01)
    honest = camera_test.timing_fit([{"asked_s": a, "cycle_s": 0.5 + a} for a in camera_test.ASKED])
    assert not honest["exposes_short"] and "does not prove" in honest["verdict"]


def test_the_timing_table_is_taken_and_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(camera_test, "TIMING_FILE", tmp_path / "camera_timing.json")
    clock = {"now": 0.0}

    class Quick:
        def __init__(self, gain=0): pass
        def __enter__(self): return self
        def __exit__(self, *exc): pass
        def frame(self, seconds):
            clock["now"] += 0.4 + 0.63 * seconds
    monkeypatch.setattr(camera_test, "Camera", Quick)
    monkeypatch.setattr(camera_test.time, "monotonic", lambda: clock["now"])
    found = camera_test.timing(gain=300, asked=(0.5, 1.0, 4.0), frames=2)
    assert found["seconds_per_second_asked"] == pytest.approx(0.63, abs=0.01) and len(found["rows"]) == 3
    assert json.loads(camera_test.TIMING_FILE.read_text(encoding="utf-8"))["timing"]["exposes_short"]


def trails(length, angle, count=15):
    image = np.zeros((900, 1300), np.float32)
    for _ in range(count):
        x0, y0 = rng.uniform(150, 1150), rng.uniform(150, 750)
        for t in np.linspace(-length / 2, length / 2, 4 * length):
            image[int(round(y0 + t * math.sin(angle))), int(round(x0 + t * math.cos(angle)))] += 15
    return ndimage.gaussian_filter(image, 1.6) + 300 + rng.normal(0, 4, image.shape)


def test_a_star_trails_length_is_read_from_the_frame():
    for length, angle in ((87, 1.1), (55, 0.3)):
        found, count = camera_test.trail_length(trails(length, angle))
        assert count >= 8 and found == pytest.approx(length, rel=0.07)
    assert camera_test.trail_length(300 + rng.normal(0, 4, (900, 1300))) == (None, 0)
    # Round stars are not trails.
    assert camera_test.trail_length(stars("M27"))[0] is None


# --- how the drift answers the creep -----------------------------------------------------------

def test_a_motor_that_answers_in_proportion_gives_a_straight_line():
    rows = [{"creep": c, "drift": -1.30 + 1.0 * c + n} for c in mount.CREEPS for n in (-0.03, 0.0, 0.03)]
    found = tracking.response(rows, west=False)
    assert found["natural_arcsec_s"] == pytest.approx(-1.30, abs=0.01)
    assert found["per_unit"] == pytest.approx(1.0, abs=0.01) and found["expected_per_unit"] == 1.0
    assert found["straight"] and found["repeat_scatter_arcsec_s"] == pytest.approx(0.03, abs=0.005)
    assert [g["measurements"] for g in found["by_creep"]] == [3] * 5


def test_slack_in_the_gears_shows_as_points_off_the_line():
    answer = lambda creep: -1.30 if abs(creep) < 0.6 else -1.30 + 2.0 * creep        # nothing, then too much
    rows = [{"creep": c, "drift": answer(c) + n} for c in mount.CREEPS for n in (-0.03, 0.0, 0.03)]
    found = tracking.response(rows, west=False)
    assert not found["straight"] and found["off_line_arcsec_s"] > 0.3
    assert tracking.response([{"creep": 0.0, "drift": -1.3}], west=False) is None      # one creep says nothing


def test_the_sweep_sets_each_creep_measures_it_and_puts_the_creep_back(scope, monkeypatch):
    scope.save_clock(SITE)
    set_to = []
    monkeypatch.setattr(scope, "dec_creep", lambda rate: set_to.append(rate) or rate)
    monkeypatch.setattr(scope, "measure_drift", lambda site: (0.0, -1.3 + set_to[-1], 0.05))
    found = scope.creep_response(SITE, rates=(0.0, -0.5, -1.0), repeats=2)
    assert set_to == [0.0, -0.5, -1.0, 0.0]                        # and back to what it was
    assert len(found["rows"]) == 6 and found["per_unit"] == pytest.approx(1.0) and found["straight"]
    assert json.loads(mount.RESPONSE_FILE.read_text(encoding="utf-8"))["natural_arcsec_s"] == pytest.approx(-1.3)


# --- how the pointing changes across the sky ------------------------------------------------------

def test_the_survey_is_planned_east_first_and_leaves_out_what_is_too_low_or_hidden(tmp_path, monkeypatch):
    monkeypatch.setattr(mount, "LOCK_FILE", tmp_path / "MOTION_LOCKED")
    spots, notes = mount.plan_survey(SITE)
    assert spots == sorted(mount.SURVEY_HOURS) and "swing over the pole once" in notes[-1]
    altitude, azimuth = polaralign.to_altaz(polaralign.vector(-60.0, 40.0), SITE["latitude"])
    house = {"blocked": [{"from": azimuth % 360 - 5, "to": azimuth % 360 + 5, "altitude": altitude + 10}]}
    spots, notes = mount.plan_survey(SITE, hours=(-4, -2, -1, 1, 2, 4), skyline=house)
    assert -4 not in spots and "behind something" in notes[0]
    with pytest.raises(interface.Refusal) as refused:
        mount.plan_survey(SITE, hours=(-5, -4, 1, 2), dec=5.0)
    assert "east side" in refused.value.message
    with pytest.raises(interface.Refusal) as refused:
        mount.plan_survey(SITE, hours=(-7, -1, 1, 2))
    assert refused.value.code_name == "TARGET_BEYOND_HOUR_ANGLE_LIMIT"
    mount.LOCK_FILE.write_text("testing")
    with pytest.raises(interface.Refusal) as refused:
        mount.plan_survey(SITE)
    assert refused.value.code_name == "MOTION_LOCKED"


def test_one_figure_a_side_is_enough_when_each_side_agrees_with_itself():
    rows = [{"hour_angle_h": h, "side": "east" if h < 0 else "west", "ha_error_deg": 0.1,
             "dec_error_deg": 5.8 if h < 0 else 0.2} for h in mount.SURVEY_HOURS]
    found = mount.pointing_summary(rows)
    assert found["one_correction_per_side_is_enough"] and found["sides"]["east"]["dec_error_deg"] == 5.8
    assert found["sides"]["west"]["spread_deg"] == 0 and "is enough" in found["verdict"]
    for row in rows:                                                # now an error that grows with hour angle
        row["dec_error_deg"] += 0.4 * row["hour_angle_h"]
    found = mount.pointing_summary(rows)
    assert not found["one_correction_per_side_is_enough"] and "not enough" in found["verdict"]
    assert found["sides"]["east"]["dec_error_per_hour"] == pytest.approx(0.4, abs=0.01)


def sky_as_solved(scope, error):
    """A where_really for the simulated mount: the sky where the handset
    believes it points, out by `error(west)` degrees in hour angle and Dec."""
    from astropy import units as u
    from astropy.coordinates import HADec, SkyCoord
    from astropy.time import Time
    offset = json.loads(mount.CLOCK_FILE.read_text(encoding="utf-8"))["offset_deg"]

    def where_really(ra_hint, dec_hint, radius=30, exposure=1.0):
        now = Time.now()
        ra, dec = scope.radec()
        out = error(scope.axes()[1] > 90)
        believed = mount.wrap(mount.true_sidereal(SITE) + offset - ra)
        seen = SkyCoord(HADec(ha=(believed + out[0]) * u.deg, dec=(mount.wrap(dec) + out[1]) * u.deg,
                              obstime=now, location=mount.location(SITE))).icrs
        return {"ra": float(seen.ra.deg), "dec": float(seen.dec.deg), "when": now}
    return where_really


def test_the_survey_measures_each_side_and_keeps_its_average(scope, monkeypatch):
    scope.save_clock(SITE)
    monkeypatch.setattr(scope, "where_really", sky_as_solved(scope, lambda west: (0.1, 0.2) if west else (0.1, 5.8)))
    found = scope.pointing_survey(SITE)
    assert [r["hour_angle_h"] for r in found["rows"]] == sorted(mount.SURVEY_HOURS)
    assert [r["side"] for r in found["rows"]] == ["east"] * 3 + ["west"] * 3
    assert found["sides"]["east"]["dec_error_deg"] == pytest.approx(5.8, abs=0.05)
    assert found["sides"]["west"]["dec_error_deg"] == pytest.approx(0.2, abs=0.05)
    assert found["one_correction_per_side_is_enough"]
    assert mount.load_pointing_error(west=False)[1] == pytest.approx(5.8, abs=0.05)
    assert mount.load_pointing_error(west=True)[1] == pytest.approx(0.2, abs=0.05)
    assert json.loads(mount.SURVEY_FILE.read_text(encoding="utf-8"))["dec_deg"] == mount.SURVEY_DEC


def test_a_survey_on_a_mount_that_is_not_turning_is_stopped(scope, monkeypatch):
    from astropy.time import Time
    scope.save_clock(SITE)
    monkeypatch.setattr(scope, "where_really", lambda *a, **k: {"ra": 100.0, "dec": 40.0, "when": Time.now()})
    with pytest.raises(interface.Refusal) as stop:
        scope.pointing_survey(SITE)
    assert stop.value.code_name == "MOUNT_NOT_MOVING"


def test_the_new_mount_commands_say_what_they_would_do(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(mount, "LOCK_FILE", tmp_path / "MOTION_LOCKED")
    for command, moves in (("pointing", True), ("response", False)):
        monkeypatch.setattr(sys, "argv", ["mount", "--demo", command, "--dry-run", "--json"])
        with pytest.raises(SystemExit) as done:
            mount.main()
        answer = json.loads(capsys.readouterr().out)
        assert done.value.code == 0 and answer["ok"] and answer["data"]["would_move"] is moves
        assert answer["warnings"]
    mount.LOCK_FILE.write_text("testing")
    monkeypatch.setattr(sys, "argv", ["mount", "--demo", "pointing", "--dry-run", "--json"])
    with pytest.raises(SystemExit):
        mount.main()
    assert json.loads(capsys.readouterr().out)["errors"][0]["code"] == "MOTION_LOCKED"


# --- focusing: how quickly it answered --------------------------------------------------------------

def test_the_focus_report_gives_each_levels_timing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(focus, "FRAMES_FILE", tmp_path / "focus_frames.jsonl")
    with pytest.raises(interface.Refusal):
        focus.report()
    frame = lambda level, capture, state="seeking": {
        "level": level, "binning": 1 if level == 3 else 2, "state": state, "best_hfr": 2.1, "saved": time.time(),
        "timing": {"capture_s": capture, "process_s": 0.1, "feedback_s": capture + 0.1, "cycle_s": capture + 0.15}}
    lines = [frame(1, 0.7)] * 4 + [frame(2, 0.72)] * 5 + [frame(3, 1.0)] * 6 + [frame(3, 1.0, "good")]
    focus.FRAMES_FILE.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    found = focus.report()
    assert [(row["level"], row["frames"], row["binning"]) for row in found["levels"]] == [(1, 4, 2), (2, 5, 2), (3, 7, 1)]
    assert found["levels"][0]["feedback_s"] == pytest.approx(0.8) and found["quick_levels_feel_live"]
    assert found["ended"] == "good" and found["ended_on_level"] == 3
    assert "heard within 0.82 s" in capsys.readouterr().out


# --- the one view of it all ---------------------------------------------------------------------------

@pytest.fixture
def rig(tmp_path, monkeypatch):
    import horizon
    for module, name in ((camera_test, "TIMING_FILE"), (focus, "FRAMES_FILE"), (focus, "RUNS_FILE"),
                         (mount, "POINTING_FILE"), (mount, "SURVEY_FILE"), (mount, "RESPONSE_FILE"), (mount, "HOME_FILE"),
                         (polaralign, "POLAR_FILE"), (horizon, "RESULTS"), (moved, "MOVED_FILE"),
                         (moved, "LOG_FILE")):
        monkeypatch.setattr(module, name, tmp_path / f"{name}.json")
    return tmp_path


def test_a_rig_nothing_is_known_about_says_how_to_measure_each_thing(rig):
    answer = valid(interface.run("characterise", agent.characterise), "characterise")["data"]
    assert answer["measured"] == 0 and answer["of"] == len(answer["items"]) == 13
    # In the order the work is done: align, find home, point, then the rest.
    assert [item["action"] for item in answer["items"]][:6] == ["polar", "polar-repeat", "find-home", "sync", "sync",
                                                                 "pointing-survey"]
    assert all(not item["measured"] and item["value"] is None and item["how"] for item in answer["items"])
    assert {"./camera_test.py --timing", "./polaralign.py --repeat 5", "./mount.py response",
            "./mount.py pointing"} <= {item["how"] for item in answer["items"]}
    # Each names the application's action that measures it, where there is one.
    import console
    named = {item["action"] for item in answer["items"]} - {None}
    assert named <= set(console.ACTIONS) and {"polar-repeat", "creep-response", "pointing-survey",
                                              "camera-timing", "camera-trail"} <= named
    assert [item["what"] for item in answer["items"] if item["action"] is None] == [
        "That the telescope turns when the mount says it has", "The skyline of the place it stands"]


def test_what_has_been_measured_is_reported_with_its_value_and_age(rig):
    now = time.time()
    polaralign.POLAR_FILE.write_text(json.dumps({"total_deg": 0.2, "measured": now - 2 * 86400,
                                                 "spread_deg": 0.02, "repeats": 5}))
    camera_test.TIMING_FILE.write_text(json.dumps({"timing": {"overhead_s": 0.9, "seconds_per_second_asked": 0.63,
                                                              "saved": now}}))
    mount.POINTING_FILE.write_text(json.dumps({"error_deg": [0.1, 5.8], "west": False, "saved": now,
                                               "sides": {"east": {"error_deg": [0.1, 5.8], "saved": now}}}))
    moved.MOVED_FILE.write_text(json.dumps({"how": "a plate solve after a correction", "saved": now}))
    mount.HOME_FILE.write_text(json.dumps({"ra_home_error_deg": 0.4, "dec_home_error_deg": -2.95, "fits": True,
                                           "saved": now}))
    answer = valid(interface.run("characterise", agent.characterise), "characterise")["data"]
    found = {item["what"]: item for item in answer["items"] if item["measured"]}
    assert answer["measured"] == len(found) == 6 and answer["summary"] == "6 of 13 measured"
    assert found["Where the home position really is"]["value"] == "out by +0.40° on the RA axis and -2.95° on the Dec axis"
    assert found["How far the polar axis is from the pole"]["value"] == "0.2°"
    assert found["How far the polar axis is from the pole"]["age_days"] == pytest.approx(2.0, abs=0.1)
    assert found["How well that measurement repeats"]["value"] == "±0.02° over 5 measurements"
    assert "0.63 s for each second asked" in found["How long a frame takes for the exposure asked"]["value"]
    assert "+5.80° in Dec" in found["Pointing error on the east side"]["value"]
    assert "0 moves seen to be real so far" in found["That the telescope turns when the mount says it has"]["value"]
    assert "Pointing error on the west side" not in found


def test_the_trail_test_can_be_shown_as_a_plan_first(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["camera_test", "--trail", "--dry-run", "--json"])
    with pytest.raises(SystemExit) as done:
        camera_test.main()
    answer = json.loads(capsys.readouterr().out)
    assert done.value.code == 0 and answer["ok"] and answer["data"]["tracking_interrupted"]
    assert answer["data"]["would_move"] is False and "starts it following again" in answer["warnings"][0]


# --- where home really is -------------------------------------------------------------------------------

def survey_of(ra_home, dec_home, cone=0.0, polar=(0.0, 0.0), dec=40.0, hours=mount.SURVEY_HOURS, noise=0.0):
    """What a pointing survey would find on a mount switched on `ra_home` and
    `dec_home` degrees from its true home, with a tube `cone` degrees out of
    square and a polar axis `polar` degrees (east of north, too high) out:
    each place's error worked out exactly, from where a tilted axis really points."""
    simulator_error = simulator.POLAR_ERROR
    simulator.POLAR_ERROR = polar
    rows = []
    try:
        for h in hours:
            s = -1 if h > 0 else 1                               # west: the tube over the pole
            # The mount's own coordinates, with every axis reading out by the home error...
            ha_mount = h * 15 + ra_home + s * cone / math.cos(math.radians(dec))
            dec_mount = dec + s * dec_home
            # ...and then the sky as a polar axis off the pole shows it.
            ha_real, dec_real = simulator.tilted(ha_mount, dec_mount, SITE["latitude"]) if any(polar) else (ha_mount, dec_mount)
            rows.append({"hour_angle_h": h, "side": "west" if h > 0 else "east",
                         "ha_error_deg": mount.wrap(ha_real - h * 15) + rng.normal(0, noise),
                         "dec_error_deg": dec_real - dec + rng.normal(0, noise)})
    finally:
        simulator.POLAR_ERROR = simulator_error
    return rows


def test_home_is_recovered_from_places_either_side_of_the_meridian():
    found = mount.home_fit(survey_of(0.4, -2.95), 40.0)
    assert found["ra_home_error_deg"] == pytest.approx(0.4, abs=0.01)
    assert found["dec_home_error_deg"] == pytest.approx(-2.95, abs=0.01)
    assert found["fits"] and found["rms_deg"] < 0.01 and found["places"] == 6


def test_home_is_told_apart_from_a_tube_out_of_square_and_a_polar_axis_still_a_little_out():
    # All four at once, and the plate solves a little uncertain: home still comes out to a few hundredths.
    found = mount.home_fit(survey_of(-0.8, 1.6, cone=0.3, polar=(0.25, -0.15), noise=0.01), 40.0)
    assert found["ra_home_error_deg"] == pytest.approx(-0.8, abs=0.06)
    assert found["dec_home_error_deg"] == pytest.approx(1.6, abs=0.06)
    assert found["tube_not_square_deg"] == pytest.approx(0.3, abs=0.05)
    assert found["polar_error_left_deg"] == pytest.approx(0.27, abs=0.08) and found["fits"]
    # A polar axis alone, with home exact, is not taken for a home error.
    alone = mount.home_fit(survey_of(0.0, 0.0, polar=(0.5, 0.3)), 40.0)
    assert abs(alone["dec_home_error_deg"]) < 0.03 and abs(alone["ra_home_error_deg"]) < 0.03


def test_places_that_fit_no_account_are_not_acted_on_and_too_few_are_refused():
    wild = survey_of(0.4, -2.95, noise=0.8)
    assert not mount.home_fit(wild, 40.0)["fits"]
    with pytest.raises(interface.Refusal) as refused:
        mount.home_fit(survey_of(0.4, -2.95, hours=(-4, -2, -1, 1)), 40.0)
    assert "two on each" in refused.value.message
    assert not mount.home_fit(survey_of(0.4, -14.0), 40.0)["fits"]             # too far out to be believed


def test_findhome_measures_afresh_in_one_run_and_truehome_goes_there(scope, monkeypatch, capsys):
    scope.save_clock(SITE)
    # Something stale in the cache from another night must not come into it.
    mount.POINTING_FILE.write_text(json.dumps({"error_deg": [9, 9], "west": False, "saved": 1.0,
                                               "sides": {"east": {"error_deg": [9, 9], "saved": 1.0}}}))
    with pytest.raises(interface.Refusal) as refused:
        mount.plan_true_home()                                     # nothing measured yet: nothing to go to
    assert "findhome first" in refused.value.message and scope.at_home()
    monkeypatch.setattr(scope, "where_really", sky_as_solved(scope, lambda west: (0.4, 2.95) if west else (0.4, -2.95)))
    found = scope.find_home(SITE)
    assert found["dec_home_error_deg"] == pytest.approx(-2.95, abs=0.05) and found["fits"]
    assert found["ra_home_error_deg"] == pytest.approx(0.4, abs=0.05) and len(found["rows"]) == 6
    assert "truehome --dry-run" in capsys.readouterr().out
    plan = mount.plan_true_home()
    assert plan["would_move"] and plan["dec_axis_deg"] == pytest.approx(92.95, abs=0.05)
    assert plan["ra_axis_deg"] == pytest.approx(-0.4, abs=0.05) and "tracking off" in plan["warnings"][0]
    scope.true_home()
    ra_axis, dec_axis = scope.axes()
    assert mount.wrap(ra_axis) == pytest.approx(-0.4, abs=0.1) and dec_axis == pytest.approx(92.95, abs=0.1)
    assert "Mark both joints now" in capsys.readouterr().out


def test_truehome_moves_only_on_a_measurement_from_this_session(scope):
    scope.save_clock(SITE)
    fit = {"ra_home_error_deg": 0.4, "dec_home_error_deg": -2.95, "rms_deg": 0.02, "fits": True,
           "goes_to": {"ra_axis_deg": -0.4, "dec_axis_deg": 92.95}}
    for change, words in (({"saved": time.time() - 3 * 3600}, "two hours old"),
                          ({"saved": json.loads(mount.CLOCK_FILE.read_text())["saved"] - 60}, "before the handset"),
                          ({"saved": time.time(), "fits": False, "rms_deg": 0.6}, "did not fit")):
        mount.HOME_FILE.write_text(json.dumps(dict(fit, **change)))
        with pytest.raises(interface.Refusal) as refused:
            scope.true_home()
        assert words in refused.value.message and scope.at_home(), words
    mount.HOME_FILE.write_text(json.dumps(dict(fit, saved=time.time())))
    mount.LOCK_FILE.write_text("testing")
    with pytest.raises(interface.Refusal) as refused:
        scope.true_home()
    assert refused.value.code_name == "MOTION_LOCKED" and scope.at_home()


def test_by_day_the_sensors_own_specks_are_not_taken_for_stars(evidence):
    # As on the first real frames: a bright sky with the same specks in every frame.
    specks = np.zeros((1100, 1300))
    ys, xs = rng.integers(20, 1080, 80), rng.integers(20, 1280, 80)
    for dy in range(3):
        for dx in range(3):
            specks[ys + dy, xs + dx] = 400
    sky = lambda seed: 9000 + np.random.default_rng(seed).normal(0, 12, (1100, 1300)) + specks
    assert moved.judge(sky(1), sky(2))["verdict"] == "same"            # gone by its stars, it would stop a working mount
    assert moved.judge(sky(1), sky(2), by_stars=False)["by"] != "stars"
    # By day nothing is stopped on the pictures' say-so, however alike they are: it is recorded, with the pair.
    watch = moved.Watch(daylight=True)
    for seed in (1, 2, 3, 4, 5):
        watch.check(sky(seed), 3.0)
    kept = evidence()
    assert len(kept) == 4 and all(k["recorded_only"] and k["by"] != "stars" for k in kept)
    assert len(list(moved.PAIRS.glob("*.jpg"))) >= 1 or all(k["verdict"] != "same" for k in kept)


def test_a_lead_that_comes_out_is_a_refusal_that_says_what_to_do(scope, monkeypatch):
    def gone(command):
        raise OSError(5, "Input/output error")
    monkeypatch.setattr(scope.s, "write", gone, raising=False)
    monkeypatch.setattr(scope.s, "reset_input_buffer", lambda: None, raising=False)
    with pytest.raises(interface.Refusal) as refused:
        scope.axes()
    assert refused.value.code_name == "MOUNT_NOT_CONNECTED" and "switch the mount off at the mount" in refused.value.message
