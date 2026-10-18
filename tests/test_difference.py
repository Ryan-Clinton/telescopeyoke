"""What is new between two stacks: proper image subtraction finds a star
that was not there before, and leaves alone the ones that were, though the
two nights' stars differ in size, place and brightness. Made-up fields,
with every star known; nothing touches the network or a plate solver."""
import numpy as np
import pytest

import config
import difference
import interface
from test_depth import render

SHAPE = (600, 800)


def night(xy, flux, fwhm, shift=(0.0, 0.0), scale=1.0, sky=100.0, noise=4.0, seed=0, extra=None):
    """One night's stack of the field: stars of the given width, moved by
    `shift` pixels and dimmed by `scale`, on a sky with grain."""
    rng = np.random.default_rng(seed)
    image = sky + render(SHAPE, xy + shift, scale * flux, fwhm=fwhm)
    if extra is not None:
        image += render(SHAPE, extra[0] + shift, scale * extra[1], fwhm=fwhm)
    return (image + rng.normal(0, noise, SHAPE)).astype(np.float32)


@pytest.fixture(scope="module")
def field():
    rng = np.random.default_rng(4)
    xy = rng.uniform(30, (SHAPE[1] - 30, SHAPE[0] - 30), (400, 2))
    flux = 10 ** rng.uniform(2.5, 4.5, 400)
    return xy, flux


def test_a_new_star_is_found_and_the_old_ones_cancel(field):
    xy, flux = field
    new_star = (np.array([[412.3, 287.6]]), np.array([900.0]))
    ref = night(xy, flux, fwhm=4.0, seed=1)
    new = night(xy, flux, fwhm=5.2, shift=(1.4, -0.8), scale=0.85, seed=2, extra=new_star)
    record, significance = difference.subtract(new, ref)
    assert record["alignment_residual_px"] < 0.2 and record["flux_ratio"] == pytest.approx(0.85, abs=0.03)
    best = record["candidates"][0]
    # Found where it is on the reference's pixels: the new night was moved.
    assert abs(best["x"] - 412.3) <= 1 and abs(best["y"] - 287.6) <= 1
    assert best["score"] > 10 and best["as_strong_fading"] == 0
    assert len(record["candidates"]) <= 3


def test_planted_transients_are_counted_by_brightness(field):
    xy, flux = field
    ref = night(xy, flux, fwhm=4.0, seed=3)
    new = night(xy, flux, fwhm=4.5, shift=(0.6, 0.3), seed=4)
    record, _ = difference.subtract(new, ref, zeropoint=22.0, plant_count=150)
    shares = {row["mag"]: row["share"] for row in record["planted"]["curve"] if row["share"] is not None}
    assert shares[min(shares)] > 0.9 and shares[max(shares)] < 0.3
    assert record["false_candidates"] <= 3


def test_where_no_frame_reached_is_not_sky(field):
    """A stack is zero where its frames did not reach; that edge must not
    produce candidates."""
    xy, flux = field
    ref = night(xy, flux, fwhm=4.0, seed=5)
    new = night(xy, flux, fwhm=4.0, seed=6)
    new[:, 650:] = 0.0
    record, _ = difference.subtract(new, ref)
    assert all(c["x"] < 650 - difference.EDGE for c in record["candidates"])
    assert record["usable_share"] < 0.8


def test_two_stacks_that_share_no_stars_are_refused(field):
    xy, flux = field
    ref = night(xy, flux, fwhm=4.0, seed=7)
    blank = np.random.default_rng(8).normal(100, 4, SHAPE).astype(np.float32)
    with pytest.raises(interface.Refusal) as refused:
        difference.subtract(blank, ref)
    assert refused.value.code_name == "NO_STARS"


def test_a_bright_and_dark_pair_is_a_misplaced_star_not_a_new_one():
    score = np.zeros((40, 40), np.float32)
    score[20, 20], score[20, 23] = 9.0, -7.0
    assert difference.dipole(score, 20, 20)
    score[20, 23] = -2.0
    assert not difference.dipole(score, 20, 20)


def test_the_squares_cover_the_picture_once():
    covered = np.zeros((1100, 1300), int)
    for outer, inner, target in difference.tiles(covered.shape):
        covered[target] += 1
        assert outer[0].start <= target[0].start and outer[0].stop >= target[0].stop
    assert (covered == 1).all()


def test_proper_subtraction_of_a_night_from_itself_is_noise():
    rng = np.random.default_rng(9)
    psf = np.zeros((31, 31))
    psf[15, 15] = 1.0
    image = rng.normal(0, 1, (128, 128))
    d, s, _ = difference.zogy(image, image, psf, psf, 1.0, 1.0)
    assert np.abs(d).max() < 1e-6 and np.abs(s).max() < 1e-6


def test_the_demo_does_not_pretend(monkeypatch):
    monkeypatch.setattr(config, "DEMO", True)
    with pytest.raises(interface.Refusal) as refused:
        difference.run(type("Args", (), {"new": "M31", "reference": "M31"})())
    assert refused.value.code_name == "DEMO_UNSUPPORTED"


def test_a_field_without_its_own_reference_is_told_to_make_one(field, monkeypatch, tmp_path):
    # M31-P3 borrows M31's reference, which does not reach it: the answer is
    # reference.py --make, not "0 stars in common".
    import depth
    import reference
    xy, flux = field
    blank = np.random.default_rng(8).normal(100, 4, SHAPE).astype(np.float32)
    ref = night(xy, flux, fwhm=4.0, seed=7)
    stacks = {"new": tmp_path / "new" / "final.fits", "ref": tmp_path / "ref" / "final.fits"}
    monkeypatch.setattr(config, "DEMO", False)
    monkeypatch.setattr(depth, "find_stack", lambda name: stacks["new"])
    monkeypatch.setattr(reference, "for_field", lambda name: (stacks["ref"], "M31"))
    monkeypatch.setattr(reference, "sessions_used", lambda owner: [])
    monkeypatch.setattr(difference.fits, "getdata", lambda path: blank if path == stacks["new"] else ref)
    monkeypatch.setattr(depth, "brightness", lambda image: image)
    monkeypatch.setattr(depth, "plate", lambda image, name: None)
    args = type("Args", (), {"new": "M31-P3", "reference": None, "near": "M31-P3", "plant": 0})()
    with pytest.raises(interface.Refusal) as refused:
        difference.run(args, say=lambda *_: None)
    assert refused.value.code_name == "NO_SESSION"
    assert "./reference.py M31-P3 --make" in refused.value.message and "in common" not in refused.value.message
