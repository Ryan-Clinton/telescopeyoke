"""runwatch.py: silence while all is well, one line per change worth acting on."""
import argparse
import json

import pytest

import interface
import runwatch

T0 = 1_800_000_000.0


def frame(i, accepted=True, flux=50000.0, reason="kept", every=20):
    return {"index": i, "taken": T0 + i * every, "accepted": accepted, "flux": flux, "reason": reason,
            "fwhm": 4.0, "stars": 200, "roundness": 0.9}


def session(tmp_path, frames):
    folder = tmp_path / "frames" / "M31" / "20261020-221500"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "session.json").write_text(json.dumps({"name": "M31", "frames": 0, "exposure": 16, "gain": 1500}))
    with (folder / "frames.jsonl").open("w") as f:
        for fr in frames:
            f.write(json.dumps(fr) + "\n")
    return folder


def test_a_good_run_says_nothing(tmp_path):
    folder = session(tmp_path, [frame(i) for i in range(60)])
    watch = runwatch.Watch(folder)
    assert watch.look(T0 + 59 * 20 + 5) == []
    assert watch.look(T0 + 59 * 20 + 30) == []


def test_frames_stopping_is_said_once_and_their_return_too(tmp_path):
    folder = session(tmp_path, [frame(i) for i in range(30)])
    watch = runwatch.Watch(folder)
    last = T0 + 29 * 20
    said = watch.look(last + runwatch.STALLED + 10)
    assert len(said) == 1 and "no frame for" in said[0]
    assert watch.look(last + runwatch.STALLED + 70) == []
    session(tmp_path, [frame(i) for i in range(40)])
    assert any("frames coming again" in s for s in watch.look(T0 + 39 * 20 + 5))


def test_frames_coming_but_none_kept_is_said(tmp_path):
    frames = [frame(i) for i in range(20)] + [frame(i, False, reason="trailed") for i in range(20, 40)]
    watch = runwatch.Watch(session(tmp_path, frames))
    said = watch.look(T0 + 39 * 20 + 5)
    assert any("no frame kept for" in s and "trailed" in s for s in said)


def test_the_share_kept_halving_is_said(tmp_path):
    frames = [frame(i) for i in range(40)] + [frame(i, i % 4 == 0, reason="soft") for i in range(40, 60)]
    said = runwatch.Watch(session(tmp_path, frames)).look(T0 + 59 * 20 + 5)
    assert any("kept 25% of the last 20" in s for s in said)


def test_dimming_stars_ask_what_the_sky_looks_like(tmp_path):
    frames = [frame(i) for i in range(30)] + [frame(i, flux=5000.0) for i in range(30, 36)]
    watch = runwatch.Watch(session(tmp_path, frames))
    said = watch.look(T0 + 35 * 20 + 5)
    assert any("dimmed" in s and "ask what the sky looks like" in s for s in said)


def test_the_end_of_a_run_ends_the_watch(tmp_path):
    folder = session(tmp_path, [frame(i) for i in range(10)])
    (folder / "frames.json").write_text("[]")
    watch = runwatch.Watch(folder)
    said = watch.look(T0 + 300)
    assert watch.ended and "run ended, 10 of 10 frames kept" in said[0]


def test_the_command_loops_until_the_end_and_prints_only_changes(tmp_path):
    folder = session(tmp_path, [frame(i) for i in range(10)])
    clock = iter([T0 + 200, T0 + 200 + runwatch.STALLED + 20, T0 + 200 + runwatch.GIVE_UP + 20])
    said = []
    answer = runwatch.run(argparse.Namespace(session=str(folder), every=60, once=False), say=said.append,
                          sleep=lambda s: None, clock=lambda: next(clock))
    assert answer["ended"] and len(said) == 2 and "watch is ending" in said[-1]


def test_no_run_at_all_is_a_refusal(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "DATA", tmp_path)
    with pytest.raises(interface.Refusal, match="No imaging run"):
        runwatch.run(argparse.Namespace(session=None, every=60, once=True))
