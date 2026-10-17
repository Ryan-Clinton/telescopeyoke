"""Fakes planted in raw frames: each comes out of the pipeline's colour
image with the light it was given, where it was put, and the score says
which were found. The whole run (plate solves and a restack) is proven on
real frames, not here."""
import numpy as np
import pytest
from astropy.wcs import WCS

import plant
from camera import colour


def test_a_planted_star_has_its_light_in_the_pipelines_colour_image():
    mosaic = np.full((400, 600), 300, np.uint16)
    out = plant.add_to_mosaic(mosaic, np.array([[150.3, 100.6]]), np.array([5000.0]), plant.round_star(4.0))
    rgb = colour(out).astype(float) - colour(mosaic).astype(float)
    assert rgb.sum() == pytest.approx(5000.0, rel=0.01)
    # Grey: the same light in red, green and blue.
    assert rgb[..., 0].sum() == pytest.approx(rgb[..., 1].sum(), rel=0.01)
    yy, xx = np.indices(rgb.shape[:2])
    lum = rgb.sum(axis=2)
    assert (lum * xx).sum() / lum.sum() == pytest.approx(150.3, abs=0.1)
    assert (lum * yy).sum() / lum.sum() == pytest.approx(100.6, abs=0.1)


def test_a_star_off_the_frame_is_not_planted_and_bright_ones_saturate_not_wrap():
    mosaic = np.full((100, 100), 65000, np.uint16)
    out = plant.add_to_mosaic(mosaic, np.array([[-20.0, 10.0], [25.0, 25.0]]), np.array([1e3, 1e7]), plant.round_star(3.0))
    assert out.dtype == np.uint16 and out.max() == 65535 and out.min() >= 65000


def test_the_score_says_which_fakes_were_found_and_which_candidates_were_not_fakes():
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval, w.wcs.crpix = [10.0, 41.0], [300.0, 200.0]
    w.wcs.cd = np.array([[-1.32 / 3600, 0], [0, 1.32 / 3600]])
    spots = np.array([[100.0, 100.0], [300.0, 150.0], [500.0, 300.0]])
    ra, dec = w.pixel_to_world_values(spots[:, 0], spots[:, 1])
    fakes = np.column_stack([ra, dec, [15.0, 15.0, 19.5]])
    candidates = [{"x": 101, "y": 99}, {"x": 300, "y": 151}, {"x": 50, "y": 50}]
    result = plant.score(fakes, w, candidates)
    assert result["found"] == [True, True, False] and result["false_candidates"] == 1


def test_a_planted_star_brings_its_own_photon_noise():
    """With the frame's counts per electron, the same fake planted many
    times varies as a real star of that brightness would."""
    mosaic = np.zeros((200, 200), np.uint16)
    totals = []
    for seed in range(40):
        out = plant.add_to_mosaic(mosaic, np.array([[50.0, 50.0]]), np.array([3000.0]), plant.round_star(4.0),
                                  gain=2.0, rng=np.random.default_rng(seed))
        totals.append(colour(out).astype(float).sum())
    # Each of the four pixels in a cell holds a third of its share in
    # counts; the electrons behind the whole star number 4/3 x 3000 / 2.
    electrons = 4 / 3 * 3000 / 2.0
    assert np.mean(totals) == pytest.approx(3000, rel=0.02)
    assert np.std(totals) == pytest.approx(3000 / np.sqrt(electrons) * np.sqrt(3 / 4), rel=0.35)
    plain = plant.add_to_mosaic(mosaic, np.array([[50.0, 50.0]]), np.array([3000.0]), plant.round_star(4.0))
    assert colour(plain).astype(float).sum() == pytest.approx(3000, rel=0.01)


def test_each_part_of_the_frame_lends_its_own_star_shape():
    """Stars stretched along x in the right-hand third of a frame give fakes
    there the same stretch; round stars elsewhere give round fakes."""
    from test_depth import render
    rng = np.random.default_rng(3)
    shape = (600, 900)
    lum = np.full(shape, 400.0) + rng.normal(0, 3, shape)
    for x, y in rng.uniform(30, (870, 570), (240, 2)):
        if x > 600:
            for dx in (-1.5, 0.0, 1.5):           # a short trail: three round stars in a row
                lum += render(shape, np.array([[x + dx, y]]), np.array([2000.0]), fwhm=3.0)
        else:
            lum += render(shape, np.array([[x, y]]), np.array([6000.0]), fwhm=3.0)
    shapes = plant.local_shapes(lum.astype(np.float32), 3.0)

    def stretch(star):
        yy, xx = np.indices(star.shape)
        c = star.shape[0] // 2
        return ((star * (xx - c) ** 2).sum()) / ((star * (yy - c) ** 2).sum())
    assert stretch(shapes[(2, 1)]) > 1.5 > stretch(shapes[(0, 1)]) > 0.7
