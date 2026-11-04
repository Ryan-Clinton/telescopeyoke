"""A whole night against a made-up sky: plan, GoTo, plate solve, focus,
capture, drift assist, quality pass, status. Each part has its own tests;
this one checks they still work together.

The mount is the simulated handset, the camera renders star fields, and the
plate solver is told where the simulated mount is really aimed. Set
TY_NIGHT_FRAMES for a longer run than the default.
"""
import concurrent.futures
import contextlib
import json
import math
import os
import sys
import time

import jsonschema
import pytest
from astropy import units as u
from astropy.coordinates import ICRS, HADec, SkyCoord
from astropy.time import Time

import agent
import camera
import config
import focus
import interface
import mcp_server
import mount
import restack
import shoot
import sky
import snap
import solve
import stacking
from simulator import SimulatedHandset
from test_interface import schema, valid
from test_stacking import as_mosaic, field, moved, render

FRAMES = int(os.environ.get("TY_NIGHT_FRAMES", 24))
SITE = config.example()["site"]
HOME_ERROR = (1.5, -1.0)   # how far the rough home position leaves the aim off: hour angle, Dec (degrees)


class Sky:
    """What the made-up telescope sees. The tests turn its knobs."""
    xy, flux = field()
    blur = 1.6          # star width; the focuser changes this
    slide = (1.4, -0.8)  # pixels the stars move per frame: the polar misalignment
    cloudy = ()         # frames taken under cloud
    taken = 0
    pause = 0.0         # seconds a frame takes to arrive


class FakeCamera:
    def __init__(self, port=None, gain=300):
        self.gain = gain

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    close = __exit__

    def use(self, profile):
        return 1

    def frame(self, seconds):
        time.sleep(Sky.pause)
        Sky.taken += 1
        n = Sky.taken
        # Longer exposures trail more on a drifting mount.
        trail = 1.0 + 0.4 * max(0.0, seconds - 2)
        lum = render(moved(Sky.xy, Sky.slide[0] * n, Sky.slide[1] * n),
                     Sky.flux * (0.3 if n in Sky.cloudy else 1), sigma=Sky.blur,
                     stretch_x=trail, seed=n)
        return as_mosaic(lum), {"EXPTIME": seconds, "GAIN": float(self.gain)}


@pytest.fixture
def night(tmp_path, monkeypatch):
    for name in ("CLOCK_FILE", "POINTING_FILE", "DRIFT_FILE", "LAST_SOLVE"):
        monkeypatch.setattr(mount, name, tmp_path / f"{name}.json")
    monkeypatch.setattr(mount, "LOCK_FILE", tmp_path / "MOTION_LOCKED")
    monkeypatch.setattr(mount, "SETTLE", 0)
    # The quality pass, which a real run leaves to the background, done in
    # place so these tests can look at what it made.
    monkeypatch.setattr(shoot, "restack_later", lambda folder: restack.run(folder))
    for module in (shoot, restack, agent):
        monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(shoot, "WEB", tmp_path / "web")
    monkeypatch.setattr(agent, "WEB", tmp_path / "web")
    monkeypatch.setattr(stacking, "CALIBRATION", tmp_path / "calibration")
    monkeypatch.setattr(focus, "PREVIEW", tmp_path / "web" / "latest.jpg")
    monkeypatch.setattr(focus, "FOCUS_FILE", tmp_path / "focus.json")
    (tmp_path / "web").mkdir()
    monkeypatch.setattr(snap, "publish", lambda *a, **k: None)
    monkeypatch.setattr(config, "load", config.example)
    for module in (camera, shoot, focus, solve):
        monkeypatch.setattr(module, "Camera", FakeCamera)
    monkeypatch.setattr(shoot, "ASSIST_EVERY", 8)
    Sky.taken, Sky.blur, Sky.cloudy, Sky.pause = 0, 1.6, (), 0.0

    scope = mount.Mount(handset=SimulatedHandset(slew_seconds=0))
    scope.can_solve = True
    scope.say = lambda *words: print(*words)
    monkeypatch.setattr(mount, "Mount", lambda *a, **k: scope)

    def solver(image, ra_hint=None, dec_hint=None, radius=30, **_):
        """Where the simulated mount is really aimed: where the handset
        believes, plus the error left by the rough home position."""
        offset = json.loads(mount.CLOCK_FILE.read_text(encoding="utf-8"))["offset_deg"]
        ra_handset, dec_handset = scope.radec()
        hour_angle = mount.wrap(mount.true_sidereal(SITE) + offset - ra_handset) + HOME_ERROR[0]
        spot = SkyCoord(HADec(ha=hour_angle * u.deg, dec=(mount.wrap(dec_handset) + HOME_ERROR[1]) * u.deg,
                              obstime=Time.now(), location=mount.location(SITE))).transform_to(ICRS())
        return {"ra": spot.ra.deg, "dec": spot.dec.deg, "rotation": 0.0, "scale": 1.32, "seconds": 0.1,
                "cd": [[-1.32 / 3600, 0.0], [0.0, 1.32 / 3600]]}

    monkeypatch.setattr(solve, "solve", solver)
    return scope, tmp_path


class AtOnce:
    """A worker pool that does each piece of work as it is handed over."""

    def submit(self, fn, *args, **kwargs):
        done = concurrent.futures.Future()
        try:
            done.set_result(fn(*args, **kwargs))
        except BaseException as problem:
            done.set_exception(problem)
        return done

    def map(self, fn, *iterables):
        return [fn(*item) for item in zip(*iterables)]


@contextlib.contextmanager
def at_once(workers=None):
    yield AtOnce()


def reachable_target():
    """Tonight's best target if the mount may go there now, else any object
    that is: the test must pass at any hour, in daylight too."""
    names = [t["id"] for t in agent.targets(limit=20, now=True, demo=True)["targets"]]
    names += [t["id"] for t in sky.load_targets() if t["dec"] > 62]
    for name in names:
        try:
            mount.plan_goto(name, SITE)
            return name
        except interface.Refusal:
            continue
    pytest.fail("nothing in the catalogue is reachable")


def test_a_whole_night(night, monkeypatch, capsys):
    scope, folder = night
    # Each frame is processed before the next is taken, here, so what the
    # run does cannot hang on the machine's speed (19 October 2026: on slow
    # CI runners the frames were still being processed when the run reached
    # its count, and the tracking assist never had its eight measured
    # frames). Setting frames aside when processing falls behind has its
    # own test.
    monkeypatch.setattr(stacking, "worker_pool", at_once)
    monkeypatch.setattr(shoot, "BACKLOG", 10 ** 6)

    # Plan: the night report and a target the mount is allowed to reach.
    assert valid(interface.run("night", lambda: agent.night(demo=True)), "night")["ok"]
    target = reachable_target()

    # GoTo and centre by plate solving, starting from a home position 1.5° out.
    scope.goto_target(target, SITE, solve=True)
    said = capsys.readouterr().out
    assert "off by +90.0'" in said and "centred" in said
    assert json.loads(mount.POINTING_FILE.read_text(encoding="utf-8"))["error_deg"] == pytest.approx(HOME_ERROR, abs=0.05)
    assert scope.state() == "tracking"

    # Focus: the knob is turned steadily towards focus and a little past it.
    widths = iter([4.5, 4.5, 4.5, 4.0, 3.5, 3.0, 2.6, 2.2, 1.9, 1.6, 1.6, 1.9, 2.3, 2.7, 3.1])

    class Focusing(FakeCamera):
        def frame(self, seconds):
            Sky.blur = next(widths)
            return super().frame(seconds)

    monkeypatch.setattr(focus, "Camera", Focusing)
    monkeypatch.setattr(sys, "argv", ["focus", "--frames", "15", "--quiet"])
    reading = focus.main()
    heard = capsys.readouterr().out
    assert "improving" in heard and ("Minimum passed" in heard or "worse" in heard)
    assert reading["best_hfr"] < reading["hfr"]          # it ended a little past focus
    assert agent.observing(demo=True)["optics"]["focus_state"] == "soft"
    Sky.blur = 1.6                                         # turned back to the best point

    # Capture: exposure chosen by the tracking test, frames stacked live with
    # two under cloud, the Dec creep trimmed from the drift, then the quality pass.
    Sky.taken, Sky.pause = 0, 0.6   # a real camera gives the workers time to keep up
    Sky.cloudy = (4 + 12, 4 + 13)     # the tracking test takes the first four frames
    monkeypatch.setattr(sys, "argv", ["shoot", target, "--frames", str(FRAMES), "--exposure", "auto",
                                      "--assist"])
    summary = shoot.main()
    said = capsys.readouterr().out
    assert "Selected exposure: 2 s" in said               # 3 s and 4 s trail on this mount
    assert "centred" in said                               # it re-centred before starting
    assert "Tracking assist" in said
    # Every frame is stacked live here (BACKLOG is lifted above, so a slow
    # machine sets none aside for the quality pass): the two cloudy ones
    # are always dropped, and each rejected frame is taken again, so the
    # run ends with as many good ones.
    assert 2 <= summary["rejected"] <= 6
    assert summary["captured"] == FRAMES + min(summary["rejected"], max(2, FRAMES // 4))
    assert (folder / summary["picture"]).name == "final.jpg" and (folder / summary["picture"]).exists()
    stacked = json.loads((folder / summary["folder"] / "restack.json").read_text(encoding="utf-8"))["summary"]
    assert stacked["median_residual_px"] < 0.5

    # Status: every way of asking sees the same finished run.
    run = valid(interface.run("session", agent.session), "image-session")["data"]
    assert (run["state"], run["captured"]) == ("finished", summary["captured"])
    assert run["reasons"]["star brightness down (cloud)"] == 2
    seen = valid(interface.run("observing", lambda: agent.observing(demo=True)), "observing")["data"]
    assert seen["tracking"]["drift_arcsec_s"] > 0 and seen["tracking"]["dec_creep_arcsec_s"] is not None
    assert seen["imaging"]["accepted"] == summary["accepted"]
    assert valid(interface.run("status", agent.status), "status")["data"]["imaging"]["target"] == target.replace(" ", "")   # a run is named as its folder is
    answer = mcp_server.call_tool("get_current_session", {})
    jsonschema.validate(answer["structuredContent"], schema("envelope"))
    assert answer["structuredContent"]["data"]["accepted"] == summary["accepted"]
    assert "frames" in agent.context(demo=True)


def test_an_open_ended_run_stops_when_cloud_arrives(night, monkeypatch, capsys):
    _, folder = night
    monkeypatch.setattr(shoot, "CLOUD_STOP", 5)
    # Every frame judged: on a slow computer (Windows CI) frames set aside
    # for the quality pass are not judged live, and the count wandered.
    monkeypatch.setattr(shoot, "BACKLOG", 10 ** 6)
    Sky.pause, Sky.cloudy = 0.6, range(9, 1000)    # clear for eight frames, then cloud for good
    monkeypatch.setattr(sys, "argv", ["shoot", "Test", "--frames", "0", "--exposure", "2",
                                      "--no-recentre", "--no-restack"])
    summary = shoot.main()
    said = capsys.readouterr().out
    assert "the last 5 frames were all rejected (" in said and "); stopping" in said
    # A slow computer leaves some frames for later, unjudged, and needs more
    # frames before five judged ones in a row are rejected (Windows CI).
    assert 4 <= summary["accepted"] <= 8 and 13 <= summary["captured"] <= 40


def test_frames_the_live_stack_has_no_time_for_are_kept_for_the_quality_pass(night, monkeypatch, capsys):
    """Capture never waits for processing: once BACKLOG frames are waiting,
    a new frame's raw file is kept, it is not taken again, and the quality
    pass stacks it with the rest."""
    _, folder = night
    monkeypatch.setattr(shoot, "BACKLOG", 1)
    Sky.pause, Sky.cloudy = 0.0, ()
    monkeypatch.setattr(sys, "argv", ["shoot", "Test", "--frames", "8", "--exposure", "2", "--no-recentre"])
    summary = shoot.main()
    said = capsys.readouterr().out
    assert "LATER   live stack behind; kept for the quality pass" in said
    assert summary["captured"] == 8
    session = folder / summary["folder"]
    assert len(list(session.glob("light-*.fits"))) == 8 and (session / "restack.json").exists()


def test_a_running_run_can_be_told_to_stop(night, monkeypatch, capsys):
    _, folder = night
    monkeypatch.setattr(shoot, "ORDERS", folder / "run_order.txt")
    Sky.pause = 0.6
    taken = FakeCamera.frame

    def frame(self, seconds):
        if Sky.taken == 5:
            assert shoot.tell("stop")["order"] == "stop"     # as "ty run stop" would, mid-run
        return taken(self, seconds)

    monkeypatch.setattr(FakeCamera, "frame", frame)
    monkeypatch.setattr(sys, "argv", ["shoot", "Test", "--frames", "0", "--exposure", "2",
                                      "--no-recentre", "--no-restack"])
    summary = shoot.main()
    assert "told to stop" in capsys.readouterr().out
    assert summary["captured"] == 6 and (folder / summary["folder"] / "live.fits").exists()
    assert not shoot.ORDERS.exists()
    with pytest.raises(SystemExit, match="Unknown order"):
        shoot.tell("explode")


def test_a_run_says_on_the_status_page_how_many_frames_it_has(night, monkeypatch):
    """22 October 2026: the page said "Nothing running" while shoot.py
    waited for M31-P6's first frame."""
    import activity
    seen = []
    taken = FakeCamera.frame

    def frame(self, seconds):
        seen.append([n["words"] for n in activity.now()])
        return taken(self, seconds)

    monkeypatch.setattr(FakeCamera, "frame", frame)
    monkeypatch.setattr(sys, "argv", ["shoot", "Test", "--frames", "3", "--exposure", "2",
                                      "--no-recentre", "--no-restack"])
    summary = shoot.main()
    assert seen[0] == ["Imaging Test: 0 of 3 frames of 2 s"]
    assert ["Imaging Test: 2 of 3 frames of 2 s"] in seen
    assert activity.now() == []
    ended = activity.last()
    assert ended["words"] == f"Imaging Test: {summary['captured']} of 3 frames of 2 s" and not ended["stopped"]
    state = activity.run_state(summary["folder"], [])
    assert state["running"] is False and state["stopped_at"] is not None


def test_through_cloud_a_run_waits_for_the_stars_and_ends_at_dawn(night, monkeypatch, capsys):
    _, folder = night
    monkeypatch.setattr(shoot, "CLOUD_STOP", 5)
    monkeypatch.setattr(shoot, "NIGHT_CHECK", 0)
    monkeypatch.setattr(shoot, "BACKLOG", 10 ** 6)   # every frame judged live, as above
    # Clear, forty frames of cloud, clear again. Frames are judged while
    # the next are taken, so a slow computer judges them well behind the
    # camera; sixteen cloudy frames were not always enough for five
    # rejections in a row to be seen before the clear ones (Windows CI,
    # 16 October and 1 November 2026).
    Sky.pause, Sky.cloudy = 0.6, range(5, 45)
    monkeypatch.setattr(shoot, "night_over", lambda name, site: "the Sun is -14° up" if Sky.taken >= 60 else None)
    monkeypatch.setattr(sys, "argv", ["shoot", "Test", "--frames", "0", "--exposure", "2",
                                      "--no-recentre", "--no-restack", "--through-cloud"])
    summary = shoot.main()
    said = capsys.readouterr().out
    assert "carrying on until it clears" in said and "stars again" in said
    assert "the Sun is -14° up; stopping" in said
    assert summary["accepted"] >= 8                   # frames after the cloud were kept too


def test_the_night_is_over_at_dawn_or_at_the_mounts_limit():
    from astropy.time import Time
    site = config.example()["site"]
    assert "Sun" in shoot.night_over("Vega", site, Time("2026-07-01T12:00:00"))
    import mount
    for hour in range(24):
        when = Time(f"2026-01-15T{hour:02d}:00:00")
        hour_angle = mount.where(mount.find_target("Vega"), site, when)[0] / 15
        why = shoot.night_over("Vega", site, when)
        if why and "Sun" not in why:
            assert hour_angle > mount.MAX_HOUR_ANGLE - shoot.LIMIT_MARGIN
    assert shoot.night_over("Not A Catalogue Name", site, Time("2026-01-15T23:00:00")) is None


def test_a_pause_says_what_the_frames_show_about_the_cloud():
    def frame(flux, background, accepted):
        return {"flux": flux, "background": background, "accepted": accepted}
    kept = [frame(56000, 83, True)] * 10
    # 15 October 2026: stars at a fifth and the sky no brighter was high haze; dew looks the same.
    hazy = shoot.what_dimmed(kept + [frame(11000, 45, False)] * 20)
    assert hazy.startswith("stars at 20% of their kept brightness, sky at 54%") and "haze" in hazy and "dew" in hazy
    lit = shoot.what_dimmed(kept + [frame(900, 250, False)] * 20)
    assert "lit by the town" in lit and "dew" not in lit
    gone = shoot.what_dimmed(kept + [frame(0, 80, False)] * 20)
    assert "thick cloud" in gone
    assert shoot.what_dimmed([frame(0, 80, False)] * 20) == "cloud?"       # nothing kept to compare with


def test_frames_the_live_stack_had_no_time_for_say_nothing_about_cloud():
    """On a slow computer some frames are only kept for later, with no
    figures: Windows CI ran with one worker and the cloud report crashed on
    them (16 October 2026)."""
    def frame(flux, background, accepted):
        return {"flux": flux, "background": background, "accepted": accepted}
    later = {"index": 0, "accepted": False, "fwhm": None, "stars": 0, "reason": "live stack behind"}
    log = [frame(56000, 83, True)] * 10 + [later, frame(900, 250, False), later] * 10
    assert "lit by the town" in shoot.what_dimmed(log)
    # Twenty frames kept for later on a clear night are not twenty rejections.
    assert shoot.judged([frame(56000, 83, True)] + [later] * 20) == [frame(56000, 83, True)]


def test_a_dithered_run_aims_a_little_off_the_target_between_frames(night, monkeypatch, capsys):
    """shoot.py --dither N re-centres every N frames on a point a little off
    the target, so the camera's own pattern lands on different stars."""
    scope, _ = night
    aims = []
    real = shoot.recentre
    monkeypatch.setattr(shoot, "recentre", lambda target, aim_off=(0.0, 0.0): aims.append(aim_off) or real(target, aim_off))
    target = reachable_target()
    monkeypatch.setattr(sys, "argv", ["shoot", target, "--frames", "12", "--exposure", "2",
                                      "--dither", "4", "--no-restack"])
    summary = shoot.main()
    said = capsys.readouterr().out
    assert aims[0] == (0.0, 0.0)                     # the run starts centred on the target
    dithers = aims[1:]
    assert len(dithers) == 2 and said.count("dithering: re-centring") == 2
    sizes = [math.hypot(*a) for a in dithers]
    assert all(shoot.DITHER / 2 <= r <= shoot.DITHER for r in sizes) and dithers[0] != dithers[1]
    assert summary["captured"] == 12 and summary["accepted"] >= 10


def test_a_dither_first_run_starts_off_the_target_and_stays(night, monkeypatch, capsys):
    """A second look at a candidate dithers before its first frame, so the
    candidate falls on other pixels than the first time, and no more."""
    aims = []
    real = shoot.recentre
    monkeypatch.setattr(shoot, "recentre", lambda target, aim_off=(0.0, 0.0): aims.append(aim_off) or real(target, aim_off))
    monkeypatch.setattr(sys, "argv", ["shoot", reachable_target(), "--frames", "8", "--exposure", "2",
                                      "--dither-first", "--no-restack"])
    shoot.main()
    dithered = [a for a in aims if a != (0.0, 0.0)]
    assert len(dithered) == 1 and capsys.readouterr().out.count("dithering: re-centring") == 1


def test_dithering_without_moving_the_mount_is_refused(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["shoot", "M31", "--dither", "4", "--no-recentre"])
    with pytest.raises(SystemExit) as stopped:
        shoot.main()
    assert stopped.value.code == 2


def test_a_dither_is_one_goto_without_plate_solving(monkeypatch):
    # 17 October 2026: a plate-solved dither took 1 to 3 minutes for a move of
    # an arcminute. Centring solves; a dither only has to land a little off.
    import mount
    calls = []
    monkeypatch.setattr(mount.Mount, "__init__", lambda self, watch=True: None)
    monkeypatch.setattr(mount.Mount, "goto_target",
                        lambda self, name, site, solve=False, aim_off=(0.0, 0.0): calls.append((solve, aim_off)))
    monkeypatch.setattr(config, "load", lambda: config.example())
    shoot.recentre("M31")
    shoot.recentre("M31", (1.0, -0.5))
    assert calls == [(True, (0.0, 0.0)), (False, (1.0, -0.5))]
    assert mount.SETTLE <= 10 or config.DEMO


def test_the_night_leads_with_each_discovery_programme_and_when_its_field_is_up():
    plan = agent.night(demo=True)["discovery"]
    names = {p["programme"] for p in plan}
    assert {"m31-novae", "m33-novae", "m31-panels", "tabby"} <= names
    for p in plan:
        assert p["command"] and p["command"].startswith("./")
        if p["window"]:
            assert p["window"][0] <= p["best_time"] <= p["window"][1]
    timed = [p["best_in_clear"] for p in plan if p["best_in_clear"]]
    assert timed == sorted(timed)
    assert "Discovery tonight" in agent.context(demo=True)


def test_each_discovery_window_is_cut_to_the_clear_spell():
    # 18 October 2026: Tabby is best at dusk, but the sky clears only at 23:00.
    from datetime import datetime
    at = lambda h: datetime(2026, 10, 18, h) if h < 24 else datetime(2026, 10, 19, h - 24)
    plan = [{"programme": "tabby", "window": [at(20), at(28)], "best_time": at(20)},
            {"programme": "m33", "window": [at(20), at(30)], "best_time": at(25)},
            {"programme": "early", "window": [at(19), at(22)], "best_time": at(20)}]
    out = {p["programme"]: p for p in agent.in_the_clear(plan, [at(23), at(31)])}
    assert out["tabby"]["in_clear"] == [at(23), at(28)] and out["tabby"]["best_in_clear"] == at(23)
    assert out["m33"]["best_in_clear"] == at(25)
    assert out["early"]["in_clear"] is None and plan[-1]["programme"] == "early"


def test_a_field_behind_the_measured_skyline_is_not_up(monkeypatch):
    # A wall all round: nothing in programmes/ is up in darkness.
    cfg = config.example()
    cfg["horizon"]["skyline"] = [{"az": float(az), "alt": 89.0} for az in range(0, 360, 10)]
    monkeypatch.setattr(agent, "_site", lambda demo: cfg)
    assert all(p["window"] is None for p in agent.discovery_tonight(demo=True))


def test_each_programme_says_when_it_last_ran(tmp_path):
    # 2 November 2026: M31 and M33 were patrolled the night before and the
    # outlook could not say so.
    done = tmp_path / "frames" / "M33" / "20261102-020454"
    done.mkdir(parents=True)
    (done / "final.fits").write_bytes(b"")
    (tmp_path / "frames" / "M33" / "20261103-210000").mkdir()      # started, nothing kept
    (tmp_path / "frames" / "M33" / "combined").mkdir()
    when = agent.last_run(["M33"], data=tmp_path)
    assert when.tzinfo is not None and when.astimezone().strftime("%Y%m%d-%H%M%S") == "20261102-020454"
    assert agent.last_run(["M31"], data=tmp_path) is None
    assert all("last_run" in p for p in agent.night(demo=True)["discovery"])


def test_a_jammed_camera_is_opened_again_and_the_run_goes_on_in_the_same_session(night, monkeypatch, capsys):
    """1 November 2026: a jam ended a transit run, and its restart began a new
    session from frame 0. The camera is opened again and the frames go on."""
    import indi
    _, folder = night
    monkeypatch.setattr(shoot, "JAM_WAIT_S", 0)
    taken, jammed = FakeCamera.frame, {"done": False}

    def frame(self, seconds):
        if Sky.taken == 2 and not jammed["done"]:
            jammed["done"] = True
            raise indi.IndiError("no frame within 16 s of a 4 s exposure")
        return taken(self, seconds)

    monkeypatch.setattr(FakeCamera, "frame", frame)
    monkeypatch.setattr(sys, "argv", ["shoot", "Test", "--frames", "5", "--exposure", "2",
                                      "--no-recentre", "--no-restack"])
    summary = shoot.main()
    out = capsys.readouterr().out
    assert "opening it again" in out and "the run goes on (1 of 3)" in out
    assert summary["captured"] == 5 and len(list((folder / summary["folder"]).glob("light-*.fits"))) == 5


def test_a_camera_that_stays_jammed_stops_the_run_after_a_few_tries(night, monkeypatch):
    import indi
    monkeypatch.setattr(shoot, "JAM_WAIT_S", 0)

    def frame(self, seconds):
        raise indi.IndiError("no frame within 16 s of a 4 s exposure")
    monkeypatch.setattr(FakeCamera, "frame", frame)
    monkeypatch.setattr(sys, "argv", ["shoot", "Test", "--frames", "5", "--exposure", "2",
                                      "--no-recentre", "--no-restack"])
    stopped = False
    try:
        shoot.main()
    except (indi.IndiError, SystemExit):
        stopped = True      # caught, not kept: a kept error keeps the run's rig lock open for the next test
    assert stopped


def kept_header(folder, summary):
    return stacking.load_light(sorted((folder / summary["folder"]).glob("light-*.fits"))[0])[1]


def test_a_run_through_the_183c_s_train_never_asks_a_filter_wheel(night, monkeypatch):
    import sxwheel
    _, folder = night

    def asked(**_):
        raise AssertionError("the 183C's train has no wheel")
    monkeypatch.setattr(sxwheel, "confirmed", asked)
    monkeypatch.setattr(sys, "argv", ["shoot", "Test", "--frames", "3", "--exposure", "2",
                                      "--no-recentre", "--no-restack"])
    kept = kept_header(folder, shoot.main())
    assert "FILTER" not in kept and "FILTPOS" not in kept


def test_a_run_through_a_train_with_the_wheel_labels_frames_with_the_position_it_confirmed(night, monkeypatch):
    import sxwheel
    _, folder = night
    plain = config.hardware
    monkeypatch.setattr(config, "hardware", lambda: dict(plain(), train={"name": "183m-cc", "filterwheel": True}))
    monkeypatch.setattr(sxwheel, "confirmed", lambda **_: (6, "Ha"))
    monkeypatch.setattr(sys, "argv", ["shoot", "Test", "--frames", "3", "--exposure", "2",
                                      "--no-recentre", "--no-restack"])
    kept = kept_header(folder, shoot.main())
    assert kept["FILTER"] == "Ha" and kept["FILTPOS"] == 6


def test_a_cooled_camera_is_waited_for_before_frames_and_warmed_once_at_the_run_s_end(night, monkeypatch, capsys):
    calls = []

    class Cooled(FakeCamera):
        def settle(self, say):
            calls.append(("settle", Sky.taken))
            say("camera: sensor at 0.3 °C, its target 0 °C")

        def warm_up(self, say):
            calls.append(("warm_up", Sky.taken))

    monkeypatch.setattr(shoot, "Camera", Cooled)
    monkeypatch.setattr(sys, "argv", ["shoot", "Test", "--frames", "3", "--exposure", "2",
                                      "--no-recentre", "--no-restack"])
    shoot.main()
    assert calls == [("settle", 0), ("warm_up", 3)]
    assert "sensor at 0.3 °C" in capsys.readouterr().out


def cooled_camera(calls, warm_fails=False):
    class Cooled(FakeCamera):
        def settle(self, say):
            calls.append(("settle", Sky.taken))

        def warm_up(self, say):
            calls.append(("warm_up", Sky.taken))
            if warm_fails:
                raise RuntimeError("the camera has gone")
    return Cooled


def test_a_cooled_run_that_fails_part_way_still_warms_and_keeps_its_own_error(night, monkeypatch):
    calls = []
    Cooled = cooled_camera(calls, warm_fails=True)       # and the warm-up itself fails too
    real = Cooled.frame

    def frame(self, seconds):
        if Sky.taken == 2:
            raise RuntimeError("something else broke")
        return real(self, seconds)
    monkeypatch.setattr(Cooled, "frame", frame)
    monkeypatch.setattr(shoot, "Camera", Cooled)
    monkeypatch.setattr(sys, "argv", ["shoot", "Test", "--frames", "5", "--exposure", "2",
                                      "--no-recentre", "--no-restack"])
    with pytest.raises(RuntimeError, match="something else broke"):
        shoot.main()
    assert calls == [("settle", 0), ("warm_up", 2)]


def test_a_cooled_run_stopped_by_ctrl_c_warms_on_the_way_out(night, monkeypatch):
    calls = []
    Cooled = cooled_camera(calls)
    real = Cooled.frame

    def frame(self, seconds):
        if Sky.taken == 1:
            raise KeyboardInterrupt
        return real(self, seconds)
    monkeypatch.setattr(Cooled, "frame", frame)
    monkeypatch.setattr(shoot, "Camera", Cooled)
    monkeypatch.setattr(sys, "argv", ["shoot", "Test", "--frames", "5", "--exposure", "2",
                                      "--no-recentre", "--no-restack"])
    with pytest.raises(KeyboardInterrupt):
        shoot.main()
    assert calls[-1] == ("warm_up", 1)


def test_a_cooled_run_is_not_warmed_when_it_pauses_to_dither_only_at_its_end(night, monkeypatch):
    calls = []
    monkeypatch.setattr(shoot, "Camera", cooled_camera(calls))
    monkeypatch.setattr(sys, "argv", ["shoot", reachable_target(), "--frames", "12", "--exposure", "2",
                                      "--dither", "4", "--no-restack"])
    shoot.main()
    assert [c[0] for c in calls].count("warm_up") == 1 and calls[-1][0] == "warm_up"   # once, at the end
    assert [c[0] for c in calls].count("settle") == 3        # opened three times, warmed once


def test_a_jam_that_is_opened_again_does_not_warm_but_the_last_one_does(night, monkeypatch):
    import indi
    calls = []
    Cooled = cooled_camera(calls)
    monkeypatch.setattr(shoot, "JAM_WAIT_S", 0)

    def frame(self, seconds):
        raise indi.IndiError("no frame")
    monkeypatch.setattr(Cooled, "frame", frame)
    monkeypatch.setattr(shoot, "Camera", Cooled)
    monkeypatch.setattr(sys, "argv", ["shoot", "Test", "--frames", "5", "--exposure", "2",
                                      "--no-recentre", "--no-restack"])
    with pytest.raises(indi.IndiError):
        shoot.main()
    assert [c[0] for c in calls].count("settle") == shoot.JAM_REOPENS + 1
    assert [c[0] for c in calls].count("warm_up") == 1 and calls[-1][0] == "warm_up"


def test_a_run_given_minutes_finishes_on_time_whatever_the_frame_count(night, monkeypatch, capsys):
    """1 November 2026: lost frames stretched a 75-minute patrol towards three
    hours and the plan's next targets."""
    Sky.pause = 0.3
    monkeypatch.setattr(sys, "argv", ["shoot", "Test", "--frames", "500", "--minutes", "0.03", "--exposure", "2",
                                      "--no-recentre", "--no-restack"])
    summary = shoot.main()
    assert "minutes taken: finishing" in capsys.readouterr().out
    assert 0 < summary["captured"] < 500


def test_one_clear_hour_is_an_hour_long_and_gives_each_programme_a_time():
    # 3 November 2026: one clear hour at 23:00 came out as 23:00-23:00, so
    # no programme had a time in the clear.
    from datetime import datetime
    w = {"clear_hours": 1, "clear_from": datetime(2026, 11, 3, 23), "clear_to": datetime(2026, 11, 3, 23)}
    clear = agent.clear_spell(w)
    assert clear == [datetime(2026, 11, 3, 23), datetime(2026, 11, 4, 0)]
    plan = agent.in_the_clear([{"programme": "m31", "window": [datetime(2026, 11, 3, 22), datetime(2026, 11, 4, 3)],
                                "best_time": datetime(2026, 11, 3, 22)}], clear)
    assert plan[0]["best_in_clear"] == datetime(2026, 11, 3, 23)
    assert agent.clear_spell({"clear_hours": 0, "clear_from": None, "clear_to": None}) is None


def test_the_recommendation_takes_what_can_finish_in_the_clear_and_says_why_the_rest_cannot():
    # 3 November 2026: an hour of clear sky, and the outlook listed every
    # programme without choosing.
    from datetime import datetime
    import patrol
    at = lambda h, m=0: datetime(2026, 11, 3, h, m) if h < 24 else datetime(2026, 11, 4, h - 24, m)  # noqa: E731
    clear = [at(23), at(24, 30)]
    prog = lambda name, minutes, mosaic=False, panels=1, window=(at(22), at(27)), watch=(), command=None: dict(  # noqa: E731
        programme=name, field=name, minutes=minutes, mosaic=mosaic, panels=panels,
        command=command or f"./patrol.py {name}", window=list(window) if window else None, best_time=at(23),
        last_run=None, watch=list(watch))
    plan = agent.in_the_clear([prog("m31-novae", 30), prog("m31-panels", 5, True, 8), prog("m33-novae", 75),
                               prog("tabby", 10, window=None),
                               prog("watched", 10, watch=[{"tonight": True}])], clear)
    lead = {"star": "KIC 2", "verdict": "unexplained, weak", "why_interesting": ["2 dips"],
            "command": "./mount.py goto 293.6600 +41.8700 --dry-run"}
    rec = agent.recommend(plan, clear, {"observe_tonight": [lead]})
    v = patrol.visit_minutes                                  # each field's capped capture, GoTo and plate solve
    order = [(s["what"], s["minutes"]) for s in rec["steps"]]
    # 90 min: 10 + 10 + 30 and their GoTos, then the panels that fit with theirs.
    used = v(10) + v(10) + v(30)
    panels = int((90 - used) // v(5))
    assert order == [("watched", v(10)), ("KIC 2", v(10)), ("m31-novae", v(30)), ("m31-panels", panels * v(5))]
    assert rec["steps"][0]["start"] == at(23) and \
        rec["steps"][1]["start"] == at(23) + __import__("datetime").timedelta(minutes=v(10))
    left = {s["what"]: s["why"] for s in rec["left_out"]}
    assert "cannot finish" in left["m33-novae"] and left["tabby"] == "not up tonight"
    assert rec["clear_minutes"] == 90
    none = agent.recommend(plan, None)
    assert none["steps"] == [] and "no clear spell" in none["note"]


def test_with_fog_forecast_a_brightness_measurement_is_left_out_unless_tonight_is_a_window():
    from datetime import datetime
    clear = [datetime(2026, 11, 3, 23), datetime(2026, 11, 4, 1)]
    prog = lambda name, command, watch=(): dict(  # noqa: E731
        programme=name, field=name, minutes=10, mosaic=False, panels=1, command=command, window=list(clear),
        best_time=clear[0], last_run=None, watch=list(watch))
    plan = agent.in_the_clear([prog("tabby", "./starwatch.py tabby"), prog("m31-novae", "./patrol.py m31-novae"),
                               prog("dipper", "./starwatch.py dipper", watch=[{"tonight": True}])], clear)
    lead = {"star": "KIC 2", "verdict": "unexplained, weak", "why_interesting": [], "command": "./mount.py goto 1 +2"}
    rec = agent.recommend(plan, clear, {"observe_tonight": [lead]}, fog=True)
    assert [s["what"] for s in rec["steps"]] == ["dipper", "m31-novae"]
    assert "steady sky" in rec["steps"][0]["why"]
    left = {s["what"]: s["why"] for s in rec["left_out"]}
    assert "fog" in left["tabby"] and "fog" in left["KIC 2"]
    assert [s["what"] for s in agent.recommend(plan, clear, fog=False)["steps"]] == ["dipper", "tabby", "m31-novae"]


def _plan_night():
    from datetime import datetime
    at = lambda h, m=0: datetime(2026, 11, 3, h, m) if h < 24 else datetime(2026, 11, 4, h - 24, m)  # noqa: E731
    prog = lambda name, minutes, mosaic=False, panels=1: dict(  # noqa: E731
        programme=name, field=name, minutes=minutes, mosaic=mosaic, panels=panels, command=f"./patrol.py {name}",
        window=[at(20), at(27)], best_time=at(23), last_run=None, watch=[])
    return at, [prog("m31-novae", 30), prog("m31-panels", 5, True, 8), prog("m33-novae", 75)]


def _end(rec):
    from datetime import timedelta
    return max(s["start"] + timedelta(minutes=s["minutes"]) for s in rec["steps"])


def test_asked_halfway_through_the_clear_spell_the_plan_starts_now():
    # 3 November 2026: asked at 23:00, the outlook said start at 23:00.
    at, plan = _plan_night()
    clear = [at(23), at(25)]
    rec = agent.recommend(agent.in_the_clear(plan, clear), clear, now=at(23, 40), is_ready=True)
    assert rec["from"] == at(23, 40) and rec["steps"][0]["start"] == at(23, 40)
    assert all(s["start"] >= at(23, 40) for s in rec["steps"])


def test_with_nothing_set_up_the_plan_leaves_time_to_set_up():
    at, plan = _plan_night()
    clear = [at(23), at(25)]
    early = agent.recommend(agent.in_the_clear(plan, clear), clear, now=at(22), is_ready=False)
    assert early["from"] == at(23)                    # time to set up before the clear spell
    late = agent.recommend(agent.in_the_clear(plan, clear), clear, now=at(23), is_ready=False)
    assert late["from"] == at(23, agent.SETUP_MINUTES) and late["ready"] is False
    assert late["steps"][0]["start"] == at(23, agent.SETUP_MINUTES)


def test_a_cloudy_night_or_a_clear_spell_gone_plans_nothing_and_says_go_by_the_sky():
    at, plan = _plan_night()
    cloudy = agent.recommend(agent.in_the_clear(plan, None), None, now=at(22))
    assert cloudy["steps"] == [] and "no clear spell" in cloudy["note"]
    clear = [at(23), at(24)]
    gone = agent.recommend(agent.in_the_clear(plan, clear), clear, now=at(24, 10))
    assert gone["steps"] == [] and "over" in gone["note"] and "go by the sky" in gone["note"]
    short = agent.recommend(agent.in_the_clear(plan, clear), clear, now=at(23, 45), is_ready=False)
    assert short["steps"] == [] and "set up" in short["note"]


def test_a_marginal_spell_is_not_filled_to_the_minute():
    from datetime import timedelta
    at, plan = _plan_night()
    clear = [at(23), at(24)]
    full = agent.recommend(agent.in_the_clear(plan, clear), clear, now=at(23))
    kept = agent.recommend(agent.in_the_clear(plan, clear), clear, now=at(23), marginal=True)
    assert _end(full) > at(23, 50)                       # an hour's work in an hour of sky
    assert _end(kept) <= at(24) - timedelta(minutes=agent.SLACK_MIN)


def test_a_candidate_seen_on_two_nights_gets_its_second_look_first():
    import patrol
    at, plan = _plan_night()
    clear = [at(23), at(25)]
    held = [{"candidate": "M31-P4-1", "field": "M31-P4", "nights": 2, "programme": "m31-panels"},
            {"candidate": "M33-1", "field": "M33", "nights": 2, "programme": "m33-novae"}]
    rec = agent.recommend(agent.in_the_clear(plan, clear), clear, now=at(23), followups=held)
    first = rec["steps"][0]
    # A mosaic's panels that fit go by their own priority: the candidate's panel alone, first.
    assert first["what"] == "M31-P4" and "M31-P4-1" in first["why"]
    assert first["command"] == f"./patrol.py M31-P4 --minutes {agent.FOLLOW_MINUTES}"
    assert first["minutes"] == patrol.visit_minutes(agent.FOLLOW_MINUTES)
    assert rec["steps"][1]["what"] == "m33-novae" and "M33-1" in rec["steps"][1]["why"]
    without = agent.recommend(agent.in_the_clear(plan, clear), clear, now=at(23))
    assert without["steps"][0]["what"] == "m31-novae"


def test_ready_means_a_plate_solve_within_the_hour(tmp_path, monkeypatch):
    import os
    import mount
    solve = tmp_path / "last_solve.json"
    monkeypatch.setattr(mount, "LAST_SOLVE", solve)
    assert not agent.ready()
    solve.write_text("{}")
    assert agent.ready()
    old = solve.stat().st_mtime - 2 * agent.READY_WITHIN
    os.utime(solve, (old, old))
    assert not agent.ready()


def test_only_tonights_events_are_said():
    from datetime import datetime, timezone
    now = datetime(2026, 11, 3, 23, tzinfo=timezone.utc)
    dark = {"end": datetime(2026, 11, 4, 5, 30, tzinfo=timezone.utc)}
    assert agent.tonight_event({"when": "2026-11-04T02:00:00+00:00"}, dark, now)
    assert not agent.tonight_event({"when": "2026-11-04T19:00:00+00:00"}, dark, now)      # tomorrow
    assert not agent.tonight_event({"when": "2026-11-03T13:00:00+00:00"}, dark, now)      # this morning


def test_the_outlook_is_short_and_leads_with_the_plan():
    # 3 November 2026: the answer to "what's interesting tonight?" read as a
    # research bulletin; the queue and the papers are ./ty research.
    text = agent.outlook(demo=True, open_candidates=[])
    assert text.startswith("PLAN") and "SKY:" in text
    assert "PAPER" not in text and "RESEARCH:" not in text and "next to look into" not in text
    assert len(text) < 4000
    night = agent.night(demo=True)
    valid(interface.run("night", lambda: night), "night")
    assert all("panels" in p for p in night["discovery"])


def test_fog_counts_only_inside_the_clear_spell():
    from datetime import datetime
    clear = [datetime(2026, 11, 3, 23), datetime(2026, 11, 4, 0)]
    assert not agent.foggy({"fog_hours": [datetime(2026, 11, 4, 5)]}, clear)
    assert agent.foggy({"fog_hours": [datetime(2026, 11, 3, 23)]}, clear)
    assert not agent.foggy(None, clear) and not agent.foggy({"fog_hours": [clear[0]]}, None)
