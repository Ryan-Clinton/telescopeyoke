"""A patrol: its programme, its readiness, the commands it runs to point
and image, and the answer it gives. Nothing here moves a mount: the
commands are checked, and the motion lock stops the patrol before any of
them is started."""
import argparse
import json
import sys

import pytest

import config
import interface
import mount
import patrol


def test_a_programme_is_read_from_its_file_and_a_bare_name_still_works():
    p = patrol.programme("m31-novae")
    assert (p["target"], p["exposure"], p["gain"]) == ("M31", 16, 1500) and p["minutes"] > 0
    bare = patrol.programme("M33")
    assert bare["target"] == "M33" and bare["minutes"] == 30


def test_it_points_with_mount_py_and_images_with_shoot_py():
    goto, shoot = patrol.steps({"target": "M31", "exposure": 16, "gain": 1500, "minutes": 30})
    assert goto[1].endswith("mount.py") and goto[2:] == ["goto", "M31"]
    assert shoot[1].endswith("shoot.py") and shoot[2:] == ["M31", "--frames", "112", "--exposure", "16",
                                                            "--gain", "1500"]
    dry = patrol.steps({"target": "M31", "exposure": 16, "gain": 1500, "minutes": 30}, dry_run=True)
    assert all(cmd[-1] == "--dry-run" for cmd in dry)


def test_the_motion_lock_stops_the_patrol_before_anything_is_started(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    lock = tmp_path / "MOTION_LOCKED"
    lock.write_text("the tube caught on the tripod", encoding="utf-8")
    monkeypatch.setattr(mount, "LOCK_FILE", lock)
    started = []
    monkeypatch.setattr(patrol.subprocess, "run", lambda *a, **k: started.append(a))
    args = argparse.Namespace(programme="m31-novae", analyse=None, minutes=None, plan=False, dry_run=False)
    with pytest.raises(interface.Refusal) as refused:
        patrol.run(args, say=lambda *_: None)
    assert refused.value.code_name == "MOTION_LOCKED" and "caught on the tripod" in refused.value.message
    assert started == []


def test_the_plan_moves_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(mount, "LOCK_FILE", tmp_path / "MOTION_LOCKED")
    monkeypatch.setattr(patrol.subprocess, "run", lambda *a, **k: pytest.fail("the plan ran a command"))
    args = argparse.Namespace(programme="m31-novae", analyse=None, minutes=10, plan=True, dry_run=False)
    answer = patrol.run(args, say=lambda *_: None)
    assert answer["programme"]["minutes"] == 10
    reference = next(i for i in answer["readiness"] if i["what"] == "reference")
    assert not reference["ok"] and "--make" in reference["detail"]


def test_the_answer_names_each_verdict_and_lists_what_is_unexplained(tmp_path):
    session = tmp_path / "frames" / "M31" / "20261020-221500"
    session.mkdir(parents=True)
    unexplained = {"verdict": "unexplained: worth a person's eyes", "score": 6.2, "ra": 11.1, "dec": 41.5,
                   "mag": 17.4, "halves": [4.4, 4.6]}
    chain = {"depth": lambda: {"zeropoint": 23.1, "fwhm_arcsec": 6.1, "sky_mag_per_arcsec2": 19.2,
                               "completeness": {"all": {"mag_50": 17.4}}},
             "difference": lambda: {"candidates": [{}, {}], "threshold": 5.0, "fading_peaks": 2},
             "vet": lambda: {"candidates": [unexplained, {"verdict": "known asteroid 2006 WP197"}]}}
    said = []
    answer = patrol.analyse(session, say=said.append, chain=chain)
    text = "\n".join(answer["summary"])
    assert "G 17.4" in text and "2 candidates" in text and "1 known asteroid 2006 WP197" in text
    assert "Unexplained: 1" in text and "RA 11.10000" in text
    assert json.loads((session / "patrol.json").read_text(encoding="utf-8"))["summary"] == answer["summary"]


def test_a_night_with_nothing_new_says_so(tmp_path):
    session = tmp_path / "s"
    session.mkdir()
    chain = {"depth": lambda: {}, "difference": lambda: {"candidates": []}, "vet": lambda: {"candidates": []}}
    answer = patrol.analyse(session, say=lambda *_: None, chain=chain)
    assert answer["summary"][-1].startswith("Nothing unexplained")


def test_a_step_that_stops_ends_the_analysis_and_says_where(tmp_path):
    session = tmp_path / "s"
    session.mkdir()
    def no_reference():
        raise interface.Refusal("NO_SESSION", "No reference kept for M31.")
    chain = {"depth": lambda: {}, "difference": no_reference, "vet": lambda: pytest.fail("vetted anyway")}
    answer = patrol.analyse(session, say=lambda *_: None, chain=chain)
    assert answer["summary"][-1] == "Stopped at difference: No reference kept for M31."


def test_a_patrol_follows_up_the_candidates_on_file(tmp_path, monkeypatch):
    import candidates
    monkeypatch.setattr(config, "DATA", tmp_path)
    book = candidates.load("M31")
    candidates.add_night(book, "20261014-021118", [{"ra": 11.1, "dec": 41.5, "score": 5.4, "mag": 18.2,
                                                     "verdict": "unexplained: worth a person's eyes"}])
    candidates.save(book)
    session = tmp_path / "frames" / "M31" / "20261020-221500"
    session.mkdir(parents=True)
    chain = {"depth": lambda: {"zeropoint": 23.1}, "difference": lambda: {"candidates": []},
             "vet": lambda: {"candidates": []}, "measure": lambda: (lambda ra, dec: (18.1, 0.2, 18.5))}
    answer = patrol.analyse(session, say=lambda *_: None, chain=chain)
    assert any("seen on 2 of 2 nights; tonight seen again" in line and "look hard" in line
               for line in answer["summary"])


def test_a_field_out_of_reach_or_daylight_stops_the_patrol(tmp_path, monkeypatch):
    import polaris
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(mount, "LOCK_FILE", tmp_path / "MOTION_LOCKED")
    monkeypatch.setattr(config, "load", lambda: {"site": config.example()["site"]})
    def too_low(name, site):
        raise interface.Refusal("TARGET_BELOW_ALTITUDE_LIMIT", "M31 is at 12°, below the 20° limit.")
    monkeypatch.setattr(mount, "plan_goto", too_low)
    monkeypatch.setattr(polaris, "sun_now", lambda site, when=None: (5.0, 0.0))
    monkeypatch.setattr(patrol.subprocess, "run", lambda *a, **k: pytest.fail("it ran a command"))
    args = argparse.Namespace(programme="m31-novae", analyse=None, minutes=None, plan=False, dry_run=False)
    with pytest.raises(interface.Refusal) as refused:
        patrol.run(args, say=lambda *_: None)
    assert "below the 20° limit" in refused.value.message and "too light" in refused.value.message


def test_a_run_that_dawn_would_cut_short_is_said_to_be(monkeypatch):
    import polaris
    import shoot
    monkeypatch.setattr(config, "load", lambda: {"site": config.example()["site"]})
    monkeypatch.setattr(mount, "plan_goto", lambda name, site: {"altitude_deg": 60, "hour_angle_hours": 2.5,
                                                                "pier_side": "west"})
    monkeypatch.setattr(polaris, "sun_now", lambda site, when=None: (-20.0, 0.0))
    from astropy.time import Time
    start = Time("2026-10-17T05:00:00")
    monkeypatch.setattr(shoot, "night_over", lambda name, site, when: "the Sun is -11° up" if when > start + 20 / 1440 else None)
    items = patrol.sky_now({"target": "M31", "minutes": 60}, when=start)
    time_item = next(i for i in items if i["what"] == "time")
    assert "after about 20 of 60 minutes" in time_item["detail"] and not time_item["stops"]
