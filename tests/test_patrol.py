"""A patrol: its programme, its readiness, the commands it runs to point
and image, and the answer it gives. Nothing here moves a mount: the
commands are checked, and the motion lock stops the patrol before any of
them is started."""
import argparse
import json
import sys
from pathlib import Path

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


def test_a_mosaic_plan_with_no_night_left_would_move_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(mount, "LOCK_FILE", tmp_path / "unlocked")
    monkeypatch.setattr(patrol.subprocess, "run", lambda *a, **k: pytest.fail("the plan ran a command"))
    monkeypatch.setattr(patrol, "fields", lambda p: ["M31-P1", "M31-P2"])
    monkeypatch.setattr(patrol, "priorities", lambda p, names, *a: [{"field": n, "minutes": 5} for n in names])
    monkeypatch.setattr(patrol, "night_left", lambda p, site: 0)
    monkeypatch.setattr(config, "load", config.example)
    args = argparse.Namespace(programme="m31-panels", analyse=None, minutes=None, plan=True, dry_run=False)
    answer = patrol.run(args, say=lambda *_: None)
    assert answer["order"] == [] and answer["would_move"] is False
    assert answer["target"] is None and answer["goto"] is None


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
    from astropy import units as u
    monkeypatch.setattr(shoot, "night_over", lambda name, site, when: "the Sun is -11° up" if when > start + 20 * u.min else None)
    items = patrol.sky_now({"target": "M31", "minutes": 60}, when=start)
    time_item = next(i for i in items if i["what"] == "time")
    assert "after about 20 of 60 minutes" in time_item["detail"] and not time_item["stops"]


def test_a_programme_that_dithers_passes_it_to_shoot():
    _, shoot_cmd = patrol.steps({"target": "M31", "exposure": 16, "gain": 1500, "minutes": 30, "dither": 15})
    assert shoot_cmd[-2:] == ["--dither", "15"]
    assert patrol.programme("m31-novae")["dither"] == 15


def test_panels_are_ordered_by_novae_share_caught_and_time_unwatched(monkeypatch):
    import mosaic
    spots = {"M31-P1": (10.0, 41.0), "M31-P2": (11.0, 41.5), "M31-P3": (12.0, 42.0)}
    monkeypatch.setattr(mount, "find_target", lambda name: {"id": name, "ra": spots[name][0], "dec": spots[name][1]})
    monkeypatch.setattr(mosaic, "field", lambda cfg=None: (1.0, 0.67))
    known = [(11.0, 41.5)] * 5 + [(10.0, 41.0)]
    now = 1_800_000_000
    last = {"M31-P1": now - 86400, "M31-P2": now - 3 * 86400, "M31-P3": None}
    p = {"minutes": 5}
    rows = patrol.priorities(p, list(spots), known, lambda name: 17.0, last.get, now=now)
    assert [r["field"] for r in rows] == ["M31-P2", "M31-P3", "M31-P1"]
    p2 = rows[0]
    assert p2["novae_reported"] == 5 and p2["days_unwatched"] == 3.0
    assert p2["priority"] == pytest.approx(6 * patrol.completeness(17.0) * 3.0 / (5 + patrol.OVERHEAD), abs=1e-3)
    assert rows[1]["days_unwatched"] == patrol.DEBT_DAYS          # never watched counts as the longest
    # Only what the night allows, highest first.
    assert [r["field"] for r in patrol.fit(rows, 14)] == ["M31-P2", "M31-P3"]


def test_the_share_of_novae_caught_rises_with_depth():
    assert patrol.completeness(17.5) == pytest.approx(0.5)
    assert patrol.completeness(16.5) < 0.2 < 0.8 < patrol.completeness(18.5)


def test_a_mosaic_programme_plans_its_panels_once_and_keeps_them(tmp_path, monkeypatch):
    import mosaic
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(mosaic, "folder", lambda: tmp_path / "mosaics")
    monkeypatch.setattr(mosaic, "path", lambda name: tmp_path / "mosaics" / f"{name}.json")
    monkeypatch.setattr(mosaic, "load", lambda name: json.loads((tmp_path / "mosaics" / f"{name}.json").read_text())
                        if (tmp_path / "mosaics" / f"{name}.json").exists() else None)
    monkeypatch.setattr(mosaic, "camera_axes", lambda angle=None: ((1.0, 0.0), (0.0, 1.0), "test"))
    monkeypatch.setattr(mosaic, "field", lambda cfg=None: (1.0, 0.67))
    names = patrol.fields({"mosaic": "M31", "grid": "4x2"})
    assert names == [f"M31-P{n}" for n in range(1, 9)]
    assert (tmp_path / "mosaics" / "M31.json").exists()
    assert patrol.fields({"target": "M33"}) == ["M33"]


def test_a_panels_first_night_becomes_its_reference(tmp_path, monkeypatch):
    import reference
    from test_reference import measured
    monkeypatch.setattr(config, "DATA", tmp_path)
    session = measured(tmp_path, "20261020-221500", 17.1)
    (tmp_path / "frames" / "M31-P6").mkdir(parents=True)
    panel_session = tmp_path / "frames" / "M31-P6" / "20261020-221500"
    session.rename(panel_session)
    record = json.loads((panel_session / "depth.json").read_text())
    record["stack"] = str(panel_session / "final.fits")
    (panel_session / "depth.json").write_text(json.dumps(record))
    made = patrol.first_reference("M31-P6", panel_session, say=lambda *_: None)
    assert made and reference.newest("M31-P6") is not None
    assert patrol.first_reference("M31-P6", panel_session, say=lambda *_: None) is None   # only the first night


def test_a_new_stack_of_a_field_with_a_reference_is_searched_in_the_background(tmp_path, monkeypatch):
    import reference
    from test_reference import measured
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.delenv("TY_PATROL", raising=False)
    monkeypatch.setattr(config, "DEMO", False)
    first = measured(tmp_path, "20261013-232632", 17.6)
    reference.make("M31")
    later = measured(tmp_path, "20261020-221500", 17.4)
    started = []
    start = lambda cmd, **kw: started.append(cmd)
    assert patrol.search_later(first, say=lambda *_: None, start=start) is None      # the reference's own night
    assert patrol.search_later(later, say=lambda *_: None, start=start) == str(later / "patrol.log")
    assert started == [[sys.executable, str(patrol.ROOT / "patrol.py"), "--analyse", str(later)]]
    (later / "patrol.json").write_text("{}")
    assert patrol.search_later(later, say=lambda *_: None, start=start) is None      # searched already
    monkeypatch.setenv("TY_PATROL", "1")
    (later / "patrol.json").unlink()
    assert patrol.search_later(later, say=lambda *_: None, start=start) is None      # the patrol searches its own
    assert len(started) == 1


def test_a_sweep_searches_what_was_missed_and_all_history_reaches_back(tmp_path, monkeypatch):
    import datetime
    import reference
    from test_reference import measured
    monkeypatch.setattr(config, "DATA", tmp_path)
    measured(tmp_path, "20261001-220000", 17.6)
    reference.make("M31")
    old = measured(tmp_path, "20261005-220000", 17.2)
    new = measured(tmp_path, "20261020-221500", 17.4)
    now = datetime.datetime(2026, 10, 21, 9, 0)
    searched = []
    search = lambda session: searched.append(session) or {"summary": ["nothing new"]}
    answer = patrol.sweep(False, say=lambda *_: None, search=search, now=now)
    assert searched == [new] and answer["searched"] == [{"session": str(new), "summary": ["nothing new"]}]
    searched.clear()
    patrol.sweep(True, say=lambda *_: None, search=search, now=now)
    assert searched == [old, new]


def test_a_dry_run_sweep_only_lists_what_it_would_search(tmp_path, monkeypatch):
    import datetime
    import reference
    from test_reference import measured
    monkeypatch.setattr(config, "DATA", tmp_path)
    measured(tmp_path, "20261001-220000", 17.6)
    reference.make("M31")
    new = measured(tmp_path, "20261020-221500", 17.4)
    searched = []
    answer = patrol.sweep(False, say=lambda *_: None, search=searched.append,
                          now=datetime.datetime(2026, 10, 21, 9, 0), dry_run=True)
    assert searched == [] and answer["would_search"] == [str(new)]


def test_one_session_failing_does_not_stop_the_sweep(tmp_path, monkeypatch):
    import datetime
    import reference
    from test_reference import measured
    monkeypatch.setattr(config, "DATA", tmp_path)
    measured(tmp_path, "20261001-220000", 17.6)
    reference.make("M31")
    bad = measured(tmp_path, "20261019-220000", 17.2)
    measured(tmp_path, "20261020-221500", 17.4)

    def search(session):
        if session == bad:
            raise ValueError("too many values to unpack")
        return {"summary": ["nothing new"]}
    answer = patrol.sweep(True, say=lambda *_: None, search=search, now=datetime.datetime(2026, 10, 21))
    assert [s["summary"] for s in answer["searched"]] == [["stopped: ValueError: too many values to unpack"],
                                                          ["nothing new"]]


def test_a_stack_too_shallow_is_not_searched(tmp_path):
    session = tmp_path / "frames" / "M31" / "20261004-015524"
    session.mkdir(parents=True)
    ran = []
    chain = {"depth": lambda: {"zeropoint": 21.6, "completeness": {"all": {"mag_50": 15.72}}},
             "difference": lambda: ran.append("difference"), "vet": lambda: ran.append("vet")}
    answer = patrol.analyse(session, say=lambda *_: None, chain=chain)
    assert ran == [] and answer["difference"]["message"].startswith("too shallow to search: half")
    assert any(line.startswith("Stopped at difference: too shallow") for line in answer["summary"])


def test_a_subtraction_that_did_not_line_up_is_not_vetted_or_alerted(tmp_path):
    """18 October 2026: M33 lined up to 1.75 px and 16 star leftovers, beside
    33 fading peaks, went to the phone as candidates."""
    session = tmp_path / "frames" / "M33" / "20261019-002602"
    session.mkdir(parents=True)
    for found, why in (({"candidates": [{}] * 48, "alignment_residual_px": 1.75, "fading_peaks": 33}, "did not line up"),
                       ({"candidates": [{}] * 20, "alignment_residual_px": 0.3, "fading_peaks": 15}, "dark leftovers")):
        ran = []
        chain = {"depth": lambda: {"zeropoint": 21.6, "completeness": {"all": {"mag_50": 17.3}}},
                 "difference": lambda f=found: f, "vet": lambda: ran.append("vet")}
        answer = patrol.analyse(session, say=lambda *_: None, chain=chain)
        assert ran == [] and why in answer["vet"]["message"] and "nothing reported" in answer["vet"]["message"]
        assert not patrol.unexplained(answer)
    good = {"candidates": [{}] * 2, "alignment_residual_px": 0.28, "fading_peaks": 1}
    assert patrol.misaligned(good) is None


def test_a_miss_with_no_limit_says_so_rather_than_none():
    lines = patrol.summary({"followed": [{"id": "M31-1", "seen_on": 1, "of": 2,
                                          "tonight": {"seen": False, "limit": None}}]})
    assert "None" not in lines[0] and "no limit there" in lines[0]


def test_a_session_of_a_few_frames_is_not_searched(tmp_path):
    session = tmp_path / "frames" / "M31" / "20261014-020539"
    session.mkdir(parents=True)
    ran = []
    chain = {"frames": lambda: 4, "depth": lambda: ran.append("depth"), "difference": lambda: ran.append("d"),
             "vet": lambda: ran.append("v")}
    answer = patrol.analyse(session, say=lambda *_: None, chain=chain)
    assert ran == [] and "too few frames to search: 4" in answer["summary"][-1]
    assert (session / "patrol.json").exists()


UNEXPLAINED = {"ra": 10.6, "dec": 41.2, "score": 6.1, "mag": 17.4, "halves": [4.4, 4.6], "clues": [],
               "verdict": "unexplained"}


def test_an_unexplained_candidate_is_alerted_with_its_packet():
    made, sent = [], []
    result = {"vet": {"candidates": [UNEXPLAINED, dict(UNEXPLAINED, ra=10.0, verdict="asteroid")]},
              "followed": [{"id": "M31-20261020-213000-001", "ra": 10.6, "dec": 41.2, "seen_on": 1, "of": 1}],
              "pictures": ["patrol-1.png"]}
    ids = patrol.alert("M31", "frames/M31/20261020-213000", result, say=lambda *_: None, packet=made.append,
                       send=lambda text, pictures, say: sent.append((text, pictures)) or 1)
    assert ids == made == ["M31-20261020-213000-001"]
    text, pictures = sent[0]
    assert "1 unexplained candidate in 20261020-213000" in text and "M31-20261020-213000-001" in text
    assert "claim" in text and pictures == [("patrol-1.png", "M31 candidate 1: the night, the reference, the difference")]


def test_nothing_unexplained_sends_nothing():
    assert patrol.alert("M31", "s", {"vet": {"candidates": []}}, say=lambda *_: None,
                        send=lambda *a, **k: pytest.fail("sent")) == []


def test_a_second_look_takes_more_frames_without_a_goto_and_searches_them(tmp_path, monkeypatch):
    import types
    ran = []
    monkeypatch.setattr(patrol, "newest_session", lambda name, after: tmp_path)
    p = {"exposure": 16, "gain": 1500, "both_halves": True}
    result = patrol.second_look(p, "M31", say=lambda *_: None,
                                run_command=lambda c: ran.append(c) or types.SimpleNamespace(returncode=0),
                                search=lambda s: {"session": str(s)})
    assert result == {"session": str(tmp_path)}
    assert [Path(c).name for c in ran[0][1:3]] == ["shoot.py", "M31"] and "goto" not in ran[0]
    assert ran[0][ran[0].index("--frames") + 1] == str(round(60 * patrol.CONFIRM_MINUTES / 16))
    assert "--dither-first" in ran[0]      # the candidate falls on other pixels the second time


def test_a_mosaic_moves_to_the_next_panel_while_the_last_is_still_searched(tmp_path, monkeypatch):
    """18 October 2026: each panel kept the mount waiting about a minute and
    a half for its final picture and its search. Now the next GoTo goes first,
    and a panel with something unexplained is gone back to for a second look."""
    import threading
    import restack
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(mount, "LOCK_FILE", tmp_path / "unlocked")
    monkeypatch.setattr(patrol, "fields", lambda p: ["M31-P1", "M31-P2"])
    monkeypatch.setattr(patrol, "priorities", lambda p, names, *a: [{"field": n, "minutes": 5} for n in names])
    monkeypatch.setattr(patrol, "night_left", lambda p, site: 600)
    monkeypatch.setattr(patrol, "fit", lambda rows, left: [
        {"field": n, "priority": 1.0, "novae_reported": 1, "share_of_novae": 0.3, "expected_mag_50": 17.0,
         "days_unwatched": 1, "minutes": 5} for n in ("M31-P1", "M31-P2")])
    monkeypatch.setattr(patrol, "readiness", lambda p: [])
    monkeypatch.setattr(patrol, "first_goto", lambda name: None)
    monkeypatch.setattr(config, "load", config.example)
    events, release = [], threading.Event()

    def run_command(cmd, **kw):
        events.append(" ".join(Path(c).name for c in cmd[1:4]) + (" --no-restack" if "--no-restack" in cmd else ""))
        if events[-1] == "mount.py goto M31-P2":
            release.set()              # P1's search may end only once the mount has moved on
        return type("Done", (), {"returncode": 0})()
    monkeypatch.setattr(patrol.subprocess, "run", run_command)
    monkeypatch.setattr(patrol, "newest_session", lambda name, after: tmp_path / name)
    monkeypatch.setattr(restack, "run", lambda session, **k: events.append(f"picture {Path(session).name}"))

    def analyse(session, say, both_halves=True):
        if session.name == "M31-P1":
            release.wait(5)            # still searching P1 while P2 is imaged
        events.append(f"searched {session.name}")
        return {"unexplained": 1 if session.name == "M31-P1" else 0}
    monkeypatch.setattr(patrol, "analyse", analyse)
    monkeypatch.setattr(patrol, "unexplained", lambda result: result["unexplained"])
    monkeypatch.setattr(patrol, "first_reference", lambda *a, **k: None)
    monkeypatch.setattr(patrol, "second_look", lambda p, name, say: events.append(f"second look {name}") or {})
    import stitch
    monkeypatch.setattr(stitch, "later", lambda name: events.append(f"stitch {name}") or "log")
    args = argparse.Namespace(programme="m31-panels", analyse=None, minutes=None, plan=False, dry_run=False)
    answer = patrol.run(args, say=lambda *_: None)
    assert events.index("mount.py goto M31-P2") < events.index("searched M31-P1")
    assert "shoot.py M31-P1 --frames --no-restack" in events
    assert events[-3:] == ["mount.py goto M31-P1", "second look M31-P1", "stitch M31"]   # then the whole picture
    assert [f["field"] for f in answer["fields"]] == ["M31-P1", "M31-P2"]


def test_a_panel_imaged_without_the_patrol_still_becomes_its_first_reference(tmp_path, monkeypatch):
    """18 October 2026: panel 8, imaged by shoot.py alone, was searched but
    left with no reference of its own, so the next night had nothing to
    compare it with."""
    made = []
    monkeypatch.setattr(patrol, "analyse", lambda session, say: {"depth": 16.8})
    monkeypatch.setattr(patrol, "first_reference", lambda name, session, say=print: made.append((name, session)))
    session = tmp_path / "frames" / "M31-P8" / "20261018-232611"
    args = argparse.Namespace(programme=None, analyse=str(session), minutes=None, plan=False, dry_run=False)
    assert patrol.run(args, say=lambda *_: None) == {"depth": 16.8}
    assert made == [("M31-P8", session)]


def test_a_panel_with_no_reference_at_all_is_still_searched(tmp_path, monkeypatch):
    import reference
    session = tmp_path / "M31-P9" / "20261018-232611"
    session.mkdir(parents=True)
    (session / "final.fits").write_bytes(b"")
    monkeypatch.setattr(reference, "for_field", lambda field: (None, None))
    monkeypatch.setattr(reference, "newest", lambda field: None)
    assert patrol.searchable(session)
    other = tmp_path / "NGC7000" / "20261018-232611"
    other.mkdir(parents=True)
    (other / "final.fits").write_bytes(b"")
    assert not patrol.searchable(other)       # a field nobody patrols is left alone
