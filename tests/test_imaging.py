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
    latitude = 52.0

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
    altitude, azimuth = polaralign.to_altaz(polaralign.axis_of(points), 52.0)
    assert altitude == pytest.approx(52.0, abs=0.01)
    assert azimuth == pytest.approx(0, abs=0.01)


def gaussian_field(sigma, count=40, shape=(1200, 1600), seed=3):
    """Stars of a given width scattered on a noisy sky."""
    field_rng = np.random.default_rng(seed)
    image = field_rng.normal(300, 5, shape).astype(np.float32)
    reach = int(6 * sigma) + 2
    for _ in range(count):
        x, y = field_rng.uniform(60, shape[1] - 60), field_rng.uniform(60, shape[0] - 60)
        x0, y0 = int(round(x)), int(round(y))
        yy, xx = np.mgrid[y0 - reach:y0 + reach + 1, x0 - reach:x0 + reach + 1]
        spot = np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sigma ** 2))
        image[y0 - reach:y0 + reach + 1, x0 - reach:x0 + reach + 1] += \
            field_rng.uniform(3e4, 1e5) * spot / spot.sum()
    return image


def test_half_flux_radius_of_a_gaussian_star_is_what_theory_says():
    # Half the light of a Gaussian of width sigma lies within 1.177 sigma.
    for sigma in (1.5, 3.0):
        hfr, count = focus.measure_stars(gaussian_field(sigma))
        assert count >= 20
        assert hfr == pytest.approx(1.177 * sigma, rel=0.12)


def test_focus_needs_at_least_three_stars():
    assert focus.measure_stars(rng.normal(300, 5, (600, 800)).astype(np.float32)) == (None, 0)


def test_focus_talk_through_a_pass_through_focus_and_back():
    tracker = focus.FocusTracker()
    said = [tracker.feed(v) for v in (7.0, 6.2, 5.3, 4.6, 4.1, 4.0, 4.1, 4.4, 5.0, 5.6)]
    assert said[0] == "7.0"
    assert any(s.startswith("Improving") and "Best" in s for s in said[3:6])
    passed = [s for s in said if s.startswith("Minimum passed")]
    assert len(passed) == 1 and "Reverse slightly" in passed[0]
    # Coming back the other way, it says when the best has been regained.
    back = [tracker.feed(v) for v in (5.0, 4.4, 4.0, 3.9, 3.9)]
    assert any(s.startswith("Best focus") and s.endswith("Hold.") for s in back)


def test_focus_does_not_chase_the_seeing():
    tracker = focus.FocusTracker()
    jitter = np.random.default_rng(8).normal(4.0, 0.12, 30)
    said = [tracker.feed(float(v)) for v in jitter]
    assert set(said[3:]) == {"No change."}


def test_a_real_worsening_is_reported_once_not_every_frame():
    tracker = focus.FocusTracker()
    said = [tracker.feed(v) for v in (4.0, 4.0, 4.0, 6.0, 6.0, 6.0, 6.0)]
    assert sum(s.startswith("Worse") for s in said) == 1


def test_the_indi_client_keeps_each_settings_range():
    import indi
    client = indi.Indi.__new__(indi.Indi)
    client.props, client.blobs, client.messages = {}, [], []
    from xml.etree.ElementTree import fromstring
    client._handle(fromstring(
        '<defNumberVector device="Cam" name="CCD_CONTROLS" state="Ok">'
        '<defNumber name="Speed" label="Speed" min="0" max="2" step="1">2</defNumber>'
        '<defNumber name="Gain" label="Gain" min="100" max="5000" step="1">300</defNumber>'
        '</defNumberVector>'))
    assert client.limits("Cam", "CCD_CONTROLS", "Speed") == (0.0, 2.0)
    assert client.get("Cam", "CCD_CONTROLS", "Gain") == "300"
    # An update carries no range; the one from the definition is kept.
    client._handle(fromstring('<setNumberVector device="Cam" name="CCD_CONTROLS" state="Ok">'
                              '<oneNumber name="Gain">1500</oneNumber></setNumberVector>'))
    assert client.get("Cam", "CCD_CONTROLS", "Gain") == "1500"
    assert client.limits("Cam", "CCD_CONTROLS", "Gain") == (100.0, 5000.0)
    assert client.limits("Cam", "CCD_CONTROLS", "Hue") is None


def test_duty_cycle_is_the_share_of_time_the_shutter_is_open():
    import camera_test
    assert camera_test.duty(1.0, 9.0) == 11
    assert camera_test.duty(2.0, 14.0) == 14
    assert camera_test.duty(2.0, 2.5) == 80


def test_the_stretch_is_chosen_so_faint_glow_shows():
    import process
    # The fainter the glow against the brightest thing in the frame, the harder the stretch.
    gentle, hard = process.auto_stretch(0.05), process.auto_stretch(0.002)
    assert 10 <= gentle < hard <= 3000
    shown = np.arcsinh(hard * 0.002) / np.arcsinh(hard)
    assert shown == pytest.approx(process.FAINT_SHOWN, abs=0.01)
    assert process.auto_stretch(0.5) == 10.0      # already bright: no more than the gentlest


def test_polar_alignment_checks_all_three_positions_before_moving(tmp_path, monkeypatch):
    import interface
    import mount
    site = {"latitude": 55.0}
    # Near the meridian and high: the three positions step 25° away from it.
    assert polaralign.positions(-15.0, 30.0, False, site) == [(-15.0, 30.0), (-40.0, 30.0), (-65.0, 30.0)]
    assert polaralign.positions(15.0, 30.0, True, site)[2] == (65.0, 30.0)
    for start, dec, code in ((-50.0, 30.0, "TARGET_BEYOND_HOUR_ANGLE_LIMIT"),     # would end 6.7 h out
                             (-20.0, -10.0, "TARGET_BELOW_ALTITUDE_LIMIT"),       # ends too low
                             (-15.0, 85.0, "INVALID_REQUEST")):                   # at the pole: nothing to see
        with pytest.raises(interface.Refusal) as refusal:
            polaralign.positions(start, dec, False, site)
        assert refusal.value.code_name == code
    # The lock stops it before the mount is opened.
    monkeypatch.setattr(mount, "LOCK_FILE", tmp_path / "MOTION_LOCKED")
    mount.LOCK_FILE.write_text("testing", encoding="utf-8")
    monkeypatch.setattr(mount, "Mount", lambda *a, **k: pytest.fail("the mount was opened"))
    for dry in (True, False):
        with pytest.raises(interface.Refusal) as refusal:
            polaralign.run(type("Args", (), {"dry_run": dry, "json": False})())
        assert refusal.value.code_name == "MOTION_LOCKED"
