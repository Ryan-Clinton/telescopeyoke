"""A whole night against a made-up sky: plan, GoTo, plate solve, focus,
capture, drift assist, quality pass, status. Each part has its own tests;
this one checks they still work together.

The mount is the simulated handset, the camera renders star fields, and the
plate solver is told where the simulated mount is really aimed. Set
TY_NIGHT_FRAMES for a longer run than the default.
"""
import json
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
    assert "Improving" in heard and ("Minimum passed" in heard or "Worse" in heard)
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
    # On a slow machine a frame or two is set aside for the quality pass
    # instead of being stacked live; the two cloudy ones are always dropped.
    assert summary["captured"] == FRAMES and 2 <= summary["rejected"] <= 6
    assert (folder / summary["picture"]).name == "final.jpg" and (folder / summary["picture"]).exists()
    stacked = json.loads((folder / summary["folder"] / "restack.json").read_text(encoding="utf-8"))["summary"]
    assert stacked["median_residual_px"] < 0.5

    # Status: every way of asking sees the same finished run.
    run = valid(interface.run("session", agent.session), "image-session")["data"]
    assert (run["state"], run["captured"]) == ("finished", FRAMES)
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
    assert "the last 5 frames were all rejected; stopping" in capsys.readouterr().out
    assert 6 <= summary["accepted"] <= 8 and 13 <= summary["captured"] <= 22


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
