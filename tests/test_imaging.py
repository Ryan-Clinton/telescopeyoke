"""Focusing, star counting, colour handling and the polar alignment
geometry. The stacking pipeline has its own tests in test_stacking.py."""
import math

import numpy as np
import pytest
from scipy import ndimage

import camera
import focus
import polaralign
import skywatch

rng = np.random.default_rng(0)


def star_field(shape=(1824, 2720), count=300, blur=1.5):
    stars = np.zeros(shape)
    ys = rng.integers(50, shape[0] - 50, count)
    xs = rng.integers(50, shape[1] - 50, count)
    stars[ys, xs] = rng.uniform(500, 5000, count)
    return ndimage.gaussian_filter(stars, blur) * 20


def test_colour_and_luminance_from_a_bayer_mosaic():
    mosaic = np.zeros((4, 4), dtype=np.uint16)
    mosaic[0::2, 0::2], mosaic[0::2, 1::2] = 10, 20   # R, G
    mosaic[1::2, 0::2], mosaic[1::2, 1::2] = 30, 40   # G, B
    assert camera.luminance(mosaic).tolist() == [[100, 100], [100, 100]]
    assert camera.colour(mosaic)[0, 0].tolist() == [10, 25, 40]


def ring(diameter, shape=(1200, 1600), at=(600, 800), flux=4e6):
    """An out-of-focus star: a ring with a dark middle."""
    yy, xx = np.indices(shape)
    r = np.hypot(yy - at[0], xx - at[1])
    image = ((r < diameter / 2) & (r > diameter / 5)).astype(float)
    return image / image.sum() * flux + rng.normal(300, 5, shape)


def test_focus_measure_shrinks_as_the_ring_shrinks():
    sizes = [focus.measure(ring(d))[2] for d in (160, 100, 60)]
    assert sizes[0] > sizes[1] > sizes[2]


def test_focus_measure_finds_where_the_star_is():
    x, y, _ = focus.measure(ring(80, at=(400, 1100)))
    assert (x, y) == pytest.approx((1100, 400), abs=8)


def test_focus_measure_reports_nothing_on_blank_sky():
    assert focus.measure(rng.normal(300, 5, (1200, 1600))) is None


def test_a_sharp_scene_scores_higher_than_a_blurred_one():
    scene = rng.uniform(100, 1000, (300, 300))
    assert focus.sharpness(scene) > 5 * focus.sharpness(ndimage.gaussian_filter(scene, 3))


def test_star_counter_tells_stars_from_cloud():
    assert skywatch.count_stars(star_field(count=200) + rng.normal(300, 5, (1824, 2720))) > 100
    assert skywatch.count_stars(rng.normal(600, 8, (1824, 2720))) < 8


def test_polar_axis_is_recovered_from_three_points():
    latitude = 55.07

    def from_altaz(alt, az):
        a, z, l = (math.radians(v) for v in (alt, az, latitude))
        up, north, east = math.sin(a), math.cos(a) * math.cos(z), math.cos(a) * math.sin(z)
        return np.array([up * math.cos(l) - north * math.sin(l), -east,
                         up * math.sin(l) + north * math.cos(l)])

    # A mount whose axis points 3° east of north and 2° too high.
    axis = from_altaz(latitude + 2.0, 3.0)
    side = np.cross(axis, [0, 1, 0])
    side /= np.linalg.norm(side)
    points = []
    for turn in (0, 25, 50):
        t = math.radians(turn)
        p = (math.cos(math.radians(60)) * axis + math.sin(math.radians(60))
             * (math.cos(t) * side + math.sin(t) * np.cross(axis, side)))
        points.append((math.degrees(math.atan2(p[1], p[0])), math.degrees(math.asin(p[2]))))
    altitude, azimuth = polaralign.to_altaz(polaralign.axis_of(points), latitude)
    assert altitude - latitude == pytest.approx(2.0, abs=0.01)
    assert azimuth == pytest.approx(3.0, abs=0.01)


def test_a_perfectly_aligned_axis_reads_as_the_pole():
    points = [(h, 40.0) for h in (10.0, 35.0, 60.0)]   # same Dec, different hour angles
    altitude, azimuth = polaralign.to_altaz(polaralign.axis_of(points), 55.07)
    assert altitude == pytest.approx(55.07, abs=0.01)
    assert azimuth == pytest.approx(0, abs=0.01)
