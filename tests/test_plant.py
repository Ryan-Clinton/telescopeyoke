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
    out = plant.add_to_mosaic(mosaic, np.array([[150.3, 100.6]]), np.array([5000.0]), fwhm=4.0)
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
    out = plant.add_to_mosaic(mosaic, np.array([[-20.0, 10.0], [25.0, 25.0]]), np.array([1e3, 1e7]), fwhm=3.0)
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
