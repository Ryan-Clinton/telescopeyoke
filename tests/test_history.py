"""What observing really costs, measured from the nights kept: made-up
sessions with known gaps, moves and rejections, read back as spreads."""
import json

import pytest

import config
import history


def session(data, field, name, exposure, gaps, start, reasons=(), stacked=None):
    """A session whose frames came `gaps` seconds apart after `start`."""
    folder = data / "frames" / field / name
    folder.mkdir(parents=True)
    (folder / "session.json").write_text(json.dumps({"frames": len(gaps) + 1, "exposure": exposure}))
    times = [start]
    for g in gaps:
        times.append(times[-1] + g)
    lines = []
    for i, t in enumerate(times):
        why = reasons[i] if i < len(reasons) else ""
        lines.append(json.dumps({"index": i + 1, "taken": t, "accepted": not why, "reason": why}))
    (folder / "frames.jsonl").write_text("\n".join(lines) + "\n")
    if stacked is not None:
        (folder / "restack.json").write_text(json.dumps({"summary": {"stacked": stacked}}))
    return folder


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    return tmp_path


def test_the_spread_is_median_and_the_tenth_and_ninetieth():
    s = history.spread(list(range(1, 11)))
    assert s == {"median": 5.5, "p10": 2, "p90": 9, "n": 10}
    assert history.spread([]) is None


def test_frames_moves_and_long_gaps_are_measured_apart(data):
    # 16 s frames 21 s apart (5 s beyond), one 81 s gap (a stall of about 60 s).
    first = session(data, "M31-P1", "20261104-031500", 16.0, [21] * 9 + [81] + [21] * 9, 1_000_000.0,
                    stacked=17)
    last = 1_000_000.0 + 21 * 18 + 81
    # The next panel starts 150 s after the last frame, beyond its own exposure.
    session(data, "M31-P2", "20261104-032500", 16.0, [21] * 19, last + 150 + 16, stacked=20)
    c = history.costs(data=data)
    assert c["frame_gap_s_by_exposure"]["16"]["median"] == 5
    assert c["move_s"] == {"median": 150, "p10": 150, "p90": 150, "n": 1}
    assert c["long_gaps"]["seconds_each"]["median"] == 60.0
    assert c["long_gaps"]["kind"].startswith("inferred")
    assert c["camera_retries"] is None                 # nothing recorded by the camera layer yet
    assert c["stacked_share"]["median"] == pytest.approx(0.925, abs=0.01)   # 17 of 20, 20 of 20
    assert first.exists()


def test_a_long_pause_between_sessions_is_a_wait_not_a_move(data):
    session(data, "M33", "20261104-011700", 16.0, [21] * 5, 1_000_000.0)
    session(data, "M31", "20261104-024100", 16.0, [21] * 5, 1_000_000.0 + 105 + 3600)
    assert history.costs(data=data)["move_s"] is None


def test_rejections_are_shared_by_cause_and_deferred_is_not_one(data):
    reasons = ["", "too few stars (cloud?)", "stars trailed (wind or a knock?)",
               "live stack behind; kept for the quality pass", ""]
    session(data, "M33", "20261104-011700", 16.0, [21] * 4, 1_000_000.0, reasons=reasons)
    share = history.costs(data=data)["rejections"]["share"]
    assert share == {"accepted": 0.4, "cloud": 0.2, "deferred": 0.2, "trailed": 0.2}


def test_nights_before_since_are_left_out(data):
    from datetime import date
    session(data, "M33", "20261019-002600", 16.0, [21] * 3, 900_000.0)
    session(data, "M33", "20261104-011700", 16.0, [21] * 3, 1_000_000.0)
    assert history.costs(date(2026, 11, 3), data)["sessions"] == 1


def test_a_replay_s_costs_come_only_from_the_nights_before_it(data):
    from datetime import date
    session(data, "M33", "20261019-002600", 16.0, [21] * 3, 900_000.0)
    session(data, "M33", "20261104-011700", 16.0, [60] * 3, 1_000_000.0)
    c = history.costs(data=data, before=date(2026, 11, 3))
    assert c["sessions"] == 1 and c["before"] == "2026-11-03"
    assert c["frame_gap_s"]["median"] == 5.0      # 3 November's 44 s gaps are not in it


def test_how_searches_ended_is_counted_by_kind(data):
    from datetime import date
    stopped = "Stopped at vet: the subtraction left as many dark leftovers as bright ones (7 fading, 4 brightening)"
    for name, summary in (("20261019-002600", ["Unexplained: 0"]), ("20261020-002600", [stopped]),
                          ("20261021-002600", ["Stopped at depth: too few frames to search: 4"])):
        folder = session(data, "M31-P2", name, 16.0, [21] * 3, 900_000.0)
        (folder / "patrol.json").write_text(json.dumps({"summary": summary}))
    counts = history.costs(data=data, before=date(2026, 11, 3))["search_outcomes"]
    assert counts == {"searched": 1, "subtraction": 1}       # too few frames is the replay's own to work out
