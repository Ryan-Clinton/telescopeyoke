"""The collimation check on made-up defocused stars: the secondary's shadow
in the middle of the ring, or off to one side."""
import json

import numpy as np
import pytest

import collimation


def frame(shift=(0.0, 0.0), r=30, hole=0.35, at=(200, 300), shape=(400, 600), others=()):
    """A sky with one doughnut at `at`: a ring of radius `r` whose shadow
    (radius `hole` x r) is moved by `shift` (a share of r, down and right)."""
    rng = np.random.default_rng(4)
    yy, xx = np.indices(shape)
    sky = rng.normal(100, 3, shape)
    for y, x in (at,) + tuple(others):
        disc = np.hypot(yy - y, xx - x) < r
        shadow = np.hypot(yy - (y + shift[0] * r), xx - (x + shift[1] * r)) < hole * r
        sky += np.where(disc & ~shadow, 900.0, 0.0)
    return sky.astype(np.float32)


def test_a_centred_shadow_is_fine():
    result = collimation.check(frame())
    assert result["offset"] < 0.03 and result["verdict"] == "fine"
    assert result["ring_px"] == pytest.approx(60, abs=3)


@pytest.mark.parametrize("shift, way", [((0.0, 0.2), "right"), ((-0.2, 0.0), "up")])
def test_a_shadow_off_to_one_side_says_how_far_and_which_way(shift, way):
    result = collimation.check(frame(shift))
    assert result["offset"] == pytest.approx(0.2, abs=0.04)
    assert result["towards"] == way and result["verdict"].startswith("off")


def test_the_star_nearest_the_middle_is_used():
    """Stars towards the edge are bent by coma at f/5."""
    result = collimation.check(frame(at=(200, 300), others=((60, 60),), shift=(0.0, 0.0)))
    assert result["offset"] < 0.03


def test_stars_in_focus_give_no_answer():
    assert collimation.check(frame(r=4, hole=0.0)) is None
    assert collimation.words(None).startswith("No doughnut")


def test_several_frames_give_the_median_and_every_check_is_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(collimation, "HISTORY", tmp_path / "collimation.jsonl")
    results = [collimation.check(frame((0.0, s))) for s in (0.06, 0.07, 0.3)]
    combined = collimation.combine(results + [None])
    assert combined["frames"] == 3 and combined["offset"] == pytest.approx(0.07, abs=0.03)
    assert combined["verdict"].startswith("slightly off")
    collimation.keep(combined, "test")
    kept = json.loads((tmp_path / "collimation.jsonl").read_text())
    assert kept["verdict"] == combined["verdict"] and kept["source"] == "test"
