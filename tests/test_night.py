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


def test_through_cloud_a_run_waits_for_the_stars_and_ends_at_dawn(night, monkeypatch, capsys):
    _, folder = night
    monkeypatch.setattr(shoot, "CLOUD_STOP", 5)
    monkeypatch.setattr(shoot, "NIGHT_CHECK", 0)
    # Clear, sixteen frames of cloud, clear again. Long enough that five
    # judged rejections in a row come even when a slow computer leaves some
    # cloudy frames for later, unjudged (Windows CI, 16 October 2026).
    Sky.pause, Sky.cloudy = 0.6, range(5, 21)
    monkeypatch.setattr(shoot, "night_over", lambda name, site: "the Sun is -14° up" if Sky.taken >= 36 else None)
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
