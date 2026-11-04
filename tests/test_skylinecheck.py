"""The planner's skyline set against a night's frames: which limit each
frame was under, measured skyline and its margin kept apart, and how many
were kept."""
import copy

import numpy as np

import config
import skylinecheck
import test_nightreplay as t


def cfg(skyline_alt, margin=2.0, floor=0.0):
    c = copy.deepcopy(config.example())
    c["horizon"].update(min_altitude=floor, margin=margin, blocked=[],
                        skyline=[{"az": float(a), "alt": float(skyline_alt)} for a in range(0, 360, 15)])
    return c


def test_each_frame_is_put_under_the_limit_it_fell_below():
    az = np.array([100.0])
    floor, blocked, raw, padded = skylinecheck.limits_at(az, {"min_altitude": 20, "margin": 2,
                                                               "skyline": [{"az": 0.0, "alt": 30.0},
                                                                           {"az": 180.0, "alt": 30.0}]})
    assert skylinecheck.classify(31.0, floor[0], blocked[0], raw[0], padded[0]) == "margin"
    assert skylinecheck.classify(29.0, floor[0], blocked[0], raw[0], padded[0]) == "skyline"
    assert skylinecheck.classify(19.0, floor[0], blocked[0], raw[0], padded[0]) == "floor"
    assert skylinecheck.classify(40.0, floor[0], blocked[0], raw[0], padded[0]) == "clear"


def test_frames_kept_under_the_skyline_say_it_is_too_high(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    t.session(tmp_path, "M33", t.at(1, 16), 12, cloud={0, 1})
    result = skylinecheck.check(t.EVENING, tmp_path, cfg(89.0))
    s = result["sessions"][0]
    assert s["found"] and s["limits"]["skyline"] == {"frames": 12, "kept": 10}
    assert "too high there" in result["verdict"]


def test_a_skyline_below_every_frame_holds(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    t.session(tmp_path, "M33", t.at(1, 16), 12)
    result = skylinecheck.check(t.EVENING, tmp_path, cfg(1.0, margin=0.5))
    assert result["sessions"][0]["limits"]["clear"]["frames"] == 12
    assert result["verdict"] == "every frame clear of every limit"
