"""Replaying a night under a policy: a small made-up night with its plan,
read back by the engine. What is recorded is used as recorded; the rest is
modelled and said so; a policy that keeps a step to its time leaves the
next its own."""
import json
import random
from datetime import date, datetime

import pytest

import config
import nightreplay

EVENING = date(2026, 11, 3)
COSTS = {
    "rejections": {"share": {"trailed": 0.0}},
    "long_gaps": {"per_hour": {"median": 0.0}, "seconds_each": {"median": 60.0}},
    "frame_gap_s_by_exposure": {"16": {"median": 5.0, "p10": 5.0, "p90": 5.0, "n": 1}},
    "frame_gap_s": {"median": 5.0, "p10": 5.0, "p90": 5.0, "n": 1},
    "move_s": {"median": 120.0, "p10": 120.0, "p90": 120.0, "n": 1},
    "stacked_share": {"median": 0.85, "p10": 0.8, "p90": 1.0, "n": 1},
    "depth_model": {"constant": 7.85, "time": 0.651, "fwhm": -2.5, "sky": 0.5},
    "depth_model_error": {"median": 0.0, "p10": -0.1, "p90": 0.1, "n": 1},
}


def at(hour, minute=0):
    day = 3 if hour >= 12 else 4
    return datetime(2026, 11, day, hour, minute).timestamp()


def session(data, field, start, n, gap=21.0, cloud=(), flux=100.0, depth=None):
    """A session of n 16 s frames from `start`; frames whose index is in
    `cloud` were lost to cloud."""
    name = datetime.fromtimestamp(start).strftime("%Y%m%d-%H%M%S")
    folder = data / "frames" / field / name
    folder.mkdir(parents=True)
    (folder / "session.json").write_text(json.dumps({"frames": n, "exposure": 16.0}))
    lines = []
    for i in range(n):
        lost = i in cloud
        lines.append(json.dumps({"index": i + 1, "taken": start + i * gap, "accepted": not lost,
                                 "reason": "too few stars (cloud?)" if lost else "", "flux": 5.0 if lost else flux}))
    (folder / "frames.jsonl").write_text("\n".join(lines) + "\n")
    (folder / "restack.json").write_text(json.dumps({"summary": {"stacked": int((n - len(cloud)) * 0.85)}}))
    if depth:
        (folder / "depth.json").write_text(json.dumps({"fwhm_arcsec": 6.4, "sky_mag_per_arcsec2": 17.8,
                                                       "exposure_s": 16.0 * n,
                                                       "completeness": {"all": {"mag_50": depth}}}))
    return folder


def plan(data, steps):
    folder = data / "cache" / "schedules"
    folder.mkdir(parents=True)
    (folder / f"{EVENING.isoformat()}.json").write_text(json.dumps({"steps": steps}))


@pytest.fixture
def night(tmp_path, monkeypatch):
    """Panels from 03:14 for a 45-minute step, then a supernova to 05:25."""
    monkeypatch.setattr(config, "DATA", tmp_path)
    plan(tmp_path, [
        {"label": "M31 panels", "minutes": 45, "until": None, "started": at(3, 14), "finished": at(4, 53),
         "command": ["./patrol.py", "m31-panels"]},
        {"label": "SN", "minutes": 90, "until": "05:25", "started": at(4, 53), "finished": at(5, 25),
         "command": ["./shoot.py", "NGC 3310", "--minutes", "90", "--exposure", "16", "--gain", "1500"]}])
    t = at(3, 15)
    for n in (1, 2, 3, 4, 5, 6, 7, 8):
        session(tmp_path, f"M31-P{n}", t, 16, depth=16.8)
        t += 16 * 21 + 120
    session(tmp_path, "NGC3310", at(4, 54), 75, cloud=set(range(10)))
    return nightreplay.load(EVENING, tmp_path)


def test_a_night_is_read_from_its_plan_and_its_sessions(night):
    assert [s["field"] for s in night.sessions][:2] == ["M31-P1", "M31-P2"]
    # Seven moves between the eight panels; the long wait before the supernova is not a move.
    assert len(night.frames) == 8 * 16 + 75 and len(night.moves) == 7
    assert night.start == at(3, 14)


def test_a_night_without_its_plan_is_refused(tmp_path, monkeypatch):
    import interface
    monkeypatch.setattr(config, "DATA", tmp_path)
    with pytest.raises(interface.Refusal):
        nightreplay.load(EVENING, tmp_path)


def test_the_sky_is_recorded_on_the_same_field_and_borrowed_elsewhere(night):
    cond = nightreplay.Conditions(night, COSTS, random.Random(1))
    p, same = cond.cloud(at(4, 55), "NGC3310")
    assert p > 0.5 and same                       # the supernova's cloudy start, on its own field
    p, same = cond.cloud(at(3, 16), "M33")
    assert p == 0.0 and not same                  # M31's clear sky, borrowed for a field not taken then
    # Only accepted frames lend their light to an accepted frame.
    assert cond.transparency(at(4, 55), "NGC3310") > 0.5


def test_keeping_the_panels_to_their_step_gives_the_supernova_its_time(night):
    as_run = nightreplay.replay(night, nightreplay.AS_RUN, runs=3, costs=COSTS)["measures"]
    current = nightreplay.replay(night, nightreplay.CURRENT, runs=3, costs=COSTS)["measures"]
    # Eight 5-minute panels as run; 45 minutes hold three of the 12.5 the current code plans.
    assert as_run["visits"]["median"] == 9 and current["visits"]["median"] == 4
    assert current["minutes: M31 panels"]["median"] <= 45
    # The supernova: 60 frames as it was asked then, its minutes now.
    assert as_run["minutes: SN"]["median"] < 30 < current["minutes: SN"]["median"]
    assert current["deadlines_passed"]["median"] == 0


def test_the_as_run_policy_gives_back_what_was_recorded(night):
    result = nightreplay.check(night, runs=5, costs=COSTS)
    p2 = next(r for r in result["sessions"] if r["field"] == "M31-P2")
    assert p2["recorded"]["captured"] == 16 and abs(p2["replayed"]["captured"]["median"] - 16) <= 1
    assert result["agreement"]["captured_error_share"] <= 0.1


def test_each_visit_says_how_much_of_its_sky_was_recorded(night):
    visits = nightreplay.replay(night, nightreplay.CURRENT, runs=1, costs=COSTS)["visits"]
    assert all(0.0 <= v["recorded_share"] <= 1.0 for v in visits)
    assert visits[0]["field"] == "M31-P1" and visits[0]["recorded_share"] > 0.5


def test_a_stressed_night_still_ends(night):
    for stress in ("camera-dead", "flicker", "no-frames", "depth-wrong"):
        m = nightreplay.replay(night, nightreplay.CURRENT, runs=2, stress=stress, costs=COSTS)["measures"]
        assert m["deadlines_passed"]["median"] == 0
    dead = nightreplay.replay(night, nightreplay.CURRENT, runs=2, stress="no-frames", costs=COSTS)["measures"]
    assert dead["accepted_minutes"]["median"] == 0
