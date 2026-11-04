"""What each observation got (docs/observing-plan-spec.md, Phase 1): made-up
sessions shaped like the night of 3 to 4 November 2026, read back as ran,
searchable, worth it and desired, with what limited them."""
import json
from datetime import date

import pytest

import config
import outcome

PANELS = {"searchable_frames": 8, "worth_depth": 16.5, "desired_frames": 24}


def session(data, field, name, asked=19, frames=(), stacked=None, depth=None, patrol=None, exposure=16.0):
    """A session folder as the run, the stack and the search leave it.
    `frames` is (seconds after the first, accepted, reason) for each frame."""
    folder = data / "frames" / field / name
    folder.mkdir(parents=True)
    (folder / "session.json").write_text(json.dumps({"name": field, "frames": asked, "exposure": exposure}))
    start = 1_793_763_000.0
    (folder / "frames.jsonl").write_text("".join(
        json.dumps({"index": i + 1, "taken": start + t, "accepted": ok, "reason": why}) + "\n"
        for i, (t, ok, why) in enumerate(frames)))
    if stacked is not None:
        (folder / "restack.json").write_text(json.dumps({"summary": {
            "captured": len(frames), "stacked": stacked, "total_exposure_s": stacked * exposure}}))
    if depth is not None:
        (folder / "depth.json").write_text(json.dumps({"completeness": {"all": {"mag_50": depth}}}))
    if patrol is not None:
        (folder / "patrol.json").write_text(json.dumps({"summary": patrol}))
    return folder


def steady(n, gap=21.6, ok=True, why=""):
    return [(i * gap, ok, why) for i in range(n)]


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(outcome, "programme_for",
                        lambda field: ("m31-panels", PANELS) if field.startswith("M31-P") else (None, {}))
    return tmp_path


def test_a_panel_that_stalls_is_not_searchable_and_says_why(data):
    """M31-P6 on 4 Nov: 8 frames in 5.5 minutes, most of the gaps stalls."""
    times = [0, 60, 115, 170, 192, 250, 300, 322]
    folder = session(data, "M31-P6", "20261104-035835", frames=[(t, True, "") for t in times], stacked=7,
                     patrol=["Stopped at depth: too few frames to search: 7, and checking each half of the night needs 8"])
    r = outcome.of_session(folder)
    assert (r["requested"], r["captured"], r["accepted"], r["stacked"]) == (19, 8, 8, 7)
    assert (r["ran"], r["searchable"], r["worth_it"]) == ("met", "short", "short")
    # Measured against the exposure and the camera's pace, not the session's own median gap,
    # which here is itself a stall.
    # Gaps of 60, 55, 55 and 58 s against 16 + 5.6 s usual: 38.4 + 33.4 + 33.4 + 36.4 s lost.
    assert r["stalls"] == 4 and r["stall_minutes"] == pytest.approx(2.4, abs=0.05)
    assert any("7 stacked, under the 8 the search needs" in s for s in r["limited_by"])


def test_searchable_but_too_shallow_is_not_worth_it(data):
    """M31-P1's second stack on 4 Nov: searchable in frames, but G 15.66 through cloud."""
    frames = steady(23) + [(500 + i * 21.6, False, "too few stars (cloud?)") for i in range(24)]
    folder = session(data, "M31-P1", "20261104-041633", asked=38, frames=frames, stacked=14, depth=15.66,
                     patrol=["Depth: half of planted stars found at G 15.66",
                             "Stopped at difference: too shallow to search: half of planted stars found at G 15.66"])
    r = outcome.of_session(folder)
    assert r["accepted"] == 23 and r["rejected"]["cloud"] == 24
    assert (r["searchable"], r["worth_it"], r["desired"]) == ("short", "short", "short")
    assert any(s.startswith("shallow: G 15.66") for s in r["limited_by"])
    assert any(s.startswith("cloud: 24 frames") for s in r["limited_by"])


def test_a_good_panel_is_met_and_what_it_leaves_owed_is_said(data):
    folder = session(data, "M31-P8", "20261104-035115", frames=steady(16), stacked=14, depth=16.9,
                     patrol=["Depth: half of planted stars found at G 16.9", "Subtracted from the reference: 1"])
    (data / "candidates").mkdir()
    (data / "candidates" / "M31-P8.json").write_text(json.dumps({"candidates": [
        {"id": "M31-P8-20261104-035115-010", "open": True, "first": "20261104-035115", "nights": [{"seen": True}]},
        {"id": "M31-P8-20261104-035115-007", "open": False, "first": "20261104-035115", "nights": [{"seen": True}]},
        {"id": "M31-P8-20261020-004156-004", "open": True, "first": "20261020-004156", "nights": [{}, {}]}]}))
    r = outcome.of_session(folder)
    assert (r["searchable"], r["worth_it"], r["desired"]) == ("met", "met", "short")    # 14 of the 24 hoped for
    assert r["stalls"] == 0 and r["limited_by"] == []
    assert r["owed"] == ["M31-P8-20261104-035115-010"]


def test_enough_frames_but_a_failed_search_is_not_searchable(data):
    """M31-P4's second visit on 4 Nov: 14 stacked, but the subtraction did not match."""
    folder = session(data, "M31-P4", "20261104-040535", frames=steady(16), stacked=14, depth=16.75,
                     patrol=["Stopped at vet: the subtraction left as many dark leftovers on stars as bright ones"])
    r = outcome.of_session(folder)
    assert r["search"] == "stopped" and r["searchable"] == "short"


def test_what_is_still_being_worked_out_is_pending_not_short(data):
    folder = session(data, "M31-P2", "20261104-031549", frames=steady(16))
    r = outcome.of_session(folder)
    assert (r["stacked"], r["searchable"], r["worth_it"], r["search"]) == (None, "pending", "pending", "pending")


def test_a_field_no_programme_watches_is_not_judged(data):
    folder = session(data, "NGC3310", "20261104-045529", asked=60, frames=steady(55) + steady(20, ok=False,
                     why="too few stars (cloud?)"), stacked=30)
    r = outcome.of_session(folder)
    assert r["programme"] is None and (r["searchable"], r["worth_it"], r["desired"]) == (
        "not judged", "not judged", "not set")
    assert r["search"] == "none" and r["rejected"]["cloud"] == 20


def test_a_night_runs_from_noon_to_noon(data):
    for name in ("20261103-115900", "20261103-200000", "20261104-045529", "20261104-120000"):
        session(data, "M33", name, frames=steady(2))
    names = [f.name for f in outcome.night_sessions(date(2026, 11, 3), data)]
    assert names == ["20261103-200000", "20261104-045529"]


def test_the_programmes_goals_are_read_from_their_files():
    name, goals = outcome.programme_for("M31-P6")
    assert name == "m31-panels" and goals["searchable_frames"] == 8 and goals["desired_frames"] == 24
    assert outcome.programme_for("M33")[0] == "m33-novae" and outcome.programme_for("NGC3310") == (None, {})


def test_an_outcome_is_kept_beside_its_session(data):
    folder = session(data, "M31-P8", "20261104-035115", frames=steady(16), stacked=14, depth=16.9,
                     patrol=["Depth: half of planted stars found at G 16.9"])
    record = outcome.keep(folder)
    kept = json.loads((folder / "outcome.json").read_text())
    assert kept["worth_it"] == record["worth_it"] == "met" and "provenance" in kept


def test_a_steps_sessions_are_the_ones_begun_while_it_ran(data):
    from datetime import datetime
    inside = session(data, "M31-P2", "20261104-031549", frames=steady(2))
    session(data, "M31-P7", "20261104-042000", frames=steady(2))
    began = datetime(2026, 11, 4, 3, 14).timestamp()
    ended = datetime(2026, 11, 4, 4, 0).timestamp()
    assert outcome.during(began, ended, data) == [inside]
