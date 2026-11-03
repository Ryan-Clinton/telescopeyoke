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


def galaxy_night(xy, flux, pedestal, seed, extra=None):
    """A night on a galaxy: sky of 100 counts and a broad glow up to 300
    more, with photon noise from both (variance equal to the light), all
    shifted by `pedestal`, the level a bias frame left behind."""
    rng = np.random.default_rng(seed)
    yy, xx = np.indices(SHAPE, dtype=np.float32)
    light = 100.0 + 300.0 * np.exp(-((xx - 400) ** 2 + (yy - 300) ** 2) / (2 * 250.0 ** 2))
    light = light + render(SHAPE, xy, 10 * flux, fwhm=4.5)
    if extra is not None:
        light += render(SHAPE, extra[0], extra[1], fwhm=4.5)
    return (light + rng.normal(0, 1, SHAPE) * np.sqrt(light) + pedestal).astype(np.float32)


def test_the_sky_scale_is_measured_whatever_the_bias_left(field):
    """1 November 2026: the master bias was above the night's camera offset
    and M31's sky sat at -55. The light that doubles the sky's variance is
    the same with the sky at +100 or below zero, and the variance stays
    positive and grows with the glow."""
    xy, flux = field
    scales = []
    for pedestal in (0.0, -155.0):
        image = galaxy_night(xy, flux, pedestal, seed=11)
        light = difference.glow(image)
        scales.append(difference.sky_scale(image, light))
        var = difference.variance(image - light, light, difference.sky_noise(image - light), scales[-1])
        assert (var > 0).all() and var[300, 400] > 3 * var[20, 20]
    # The variance there is the light there: the scale is the glow at the
    # sky's level, the faintest twentieth of the picture.
    sky = np.percentile(difference.glow(galaxy_night(xy, flux, 0.0, seed=11)), 5)
    assert scales[0] == pytest.approx(sky, rel=0.25) and scales[1] == pytest.approx(scales[0], rel=0.05)
    # With no rise to measure, the sky's noise alone.
    flat = np.random.default_rng(12).normal(0, 3, (256, 256)).astype(np.float32)
    assert difference.sky_scale(flat, np.zeros_like(flat)) is None
    assert np.allclose(difference.variance(flat, np.zeros_like(flat), 3.0, None), 9.0)


def test_a_galaxy_with_its_sky_below_zero_is_searched_on_its_photon_noise(field):
    xy, flux = field
    ref = galaxy_night(xy, flux, 0.0, seed=13)
    new = galaxy_night(xy, flux, -155.0, seed=14, extra=(np.array([[390.3, 325.6]]), np.array([3000.0])))
    record, _ = difference.subtract(new, ref)
    assert record["sky_scale_new"] > 0 and record["sky_scale_ref"] > 0
    assert any(abs(c["x"] - 390) <= 1 and abs(c["y"] - 326) <= 1 for c in record["candidates"])
    # With the variance scaled by a sky below zero, the same pair of nights
    # gave a false candidate and a fading peak as well as the star.
    assert len(record["candidates"]) == 1 and record["fading_peaks"] == 0


def spiky_stars(centres, angle, peak=60000.0, length=120, noise=3.0, seed=16):
    """Bright stars with the four diffraction spikes of a spider at `angle`
    degrees, on a flat sky with grain."""
    rng = np.random.default_rng(seed)
    image = rng.normal(0, noise, SHAPE).astype(np.float32)
    yy, xx = np.indices(SHAPE, dtype=np.float32)
    for x, y in centres:
        image += render(SHAPE, [(x, y)], [peak * 2 * np.pi * 2.0 ** 2], fwhm=4.7)
        for k in range(4):
            a = np.radians(angle + 90 * k)
            along = (xx - x) * np.cos(a) + (yy - y) * np.sin(a)
            side = -(xx - x) * np.sin(a) + (yy - y) * np.cos(a)
            arm = (along > 0) & (along < length)
            image += np.where(arm, 30.0 * np.exp(-side ** 2 / 2.0) * np.exp(-along / 60.0), 0)
    return image


def test_diffraction_spikes_are_found_at_each_nights_angle_and_left_out():
    """1 November 2026: M31's spikes were at 23.5 degrees, the reference's
    at 9, and every bright star left a bright and a dark cross."""
    centres = [(150, 150), (600, 140), (400, 300), (170, 450), (620, 460)]
    new, ref = spiky_stars(centres, 23.5), spiky_stars(centres, 9.0, seed=17)
    for image, angle in ((new, 23.5), (ref, 9.0)):
        found = difference.bright_centres(image, difference.BRIGHT * np.percentile(image, 99.99))
        assert len(found) == 5
        assert difference.spike_angle(image, found, 4.7) == pytest.approx(angle, abs=1.0)
    mask = difference.spikes(new, ref, 4.7)
    for angle in (23.5, 9.0):
        a = np.radians(angle)
        assert mask[round(300 + 60 * np.sin(a)), round(400 + 60 * np.cos(a))]
    # Between the spikes the picture is kept.
    a = np.radians(60)
    assert not mask[round(300 + 60 * np.sin(a)), round(400 + 60 * np.cos(a))]
    assert mask.mean() < 0.15
    # A night without spikes leaves nothing out.
    plain = np.random.default_rng(18).normal(0, 3, SHAPE).astype(np.float32)
    assert not difference.spikes(plain, plain, 4.7).any()


def test_fading_peaks_on_stars_are_counted_apart():
    stars = np.array([[100.0, 100.0, 1e4, 4.8, 1.0], [300.0, 200.0, 1e4, 4.8, 1.0]])
    x, y = np.array([101, 302, 500]), np.array([99, 203, 400])
    assert difference.fading_on_stars(x, y, stars, 4.8) == 2
    assert difference.fading_on_stars(np.array([], int), np.array([], int), stars, 4.8) == 0
