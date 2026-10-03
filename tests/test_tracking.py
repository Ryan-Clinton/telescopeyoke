"""Drift prediction and compensation: the arithmetic, checked against a
mount modelled from first principles."""
import math

import numpy as np
import pytest

import polaralign
import tracking

LATITUDE = 55.07


def axis_vector(azimuth, altitude_error):
    """Where a misaligned polar axis points, in polaralign's Earth-fixed frame."""
    a, z, l = (math.radians(v) for v in (LATITUDE + altitude_error, azimuth, LATITUDE))
    up, north, east = math.sin(a), math.cos(a) * math.cos(z), math.cos(a) * math.sin(z)
    return np.array([up * math.cos(l) - north * math.sin(l), -east,
                     up * math.sin(l) + north * math.cos(l)])


def simulated_drift(azimuth, altitude_error, hour_angle, dec, seconds=120.0):
    """Dec drift in arcsec/s of a mount turning about its own axis while the
    sky turns about the pole, found by actually rotating the vectors."""
    def rotate(v, axis, angle):
        axis = axis / np.linalg.norm(axis)
        return (v * math.cos(angle) + np.cross(axis, v) * math.sin(angle)
                + axis * axis.dot(v) * (1 - math.cos(angle)))
    turn = math.radians(tracking.SIDEREAL * seconds / 3600)
    start = polaralign.vector(hour_angle, dec)
    pointing = rotate(start, axis_vector(azimuth, altitude_error), turn)
    star = rotate(start, np.array([0.0, 0.0, 1.0]), turn)
    drift = math.degrees(math.asin(pointing[2])) - math.degrees(math.asin(star[2]))
    return drift * 3600 / seconds


@pytest.mark.parametrize("azimuth, altitude", [(3.0, 0.0), (0.0, -2.0), (-2.0, 1.5)])
@pytest.mark.parametrize("hour_angle, dec", [(-60, 20), (0, 45), (40, 33), (75, 60)])
def test_the_drift_formula_matches_a_mount_modelled_from_first_principles(azimuth, altitude,
                                                                         hour_angle, dec):
    terms = tracking.polar_terms(azimuth, altitude, LATITUDE)
    expected = simulated_drift(azimuth, altitude, hour_angle, dec)
    assert tracking.drift_at(terms, hour_angle) == pytest.approx(expected, abs=0.03)


@pytest.mark.parametrize("hour_angle, dec", [(-60, 20), (0, 45), (40, 33), (75, 60)])
def test_for_a_very_rough_alignment_the_formula_is_close_but_not_exact(hour_angle, dec):
    # Nearly ten degrees out, as on the first night. The formula treats the
    # error as small, so it is off by up to a deadband or so here; measured
    # drift is what settles the creep, and this only has to start it close.
    terms = tracking.polar_terms(-9.4, 1.5, LATITUDE)
    expected = simulated_drift(-9.4, 1.5, hour_angle, dec)
    assert tracking.drift_at(terms, hour_angle) == pytest.approx(expected, abs=0.25)


def test_polar_error_and_drift_terms_convert_both_ways():
    terms = tracking.polar_terms(-9.4, 1.5, LATITUDE)
    assert tracking.polar_error(*terms, LATITUDE) == pytest.approx((-9.4, 1.5))


def test_tonights_drift_implies_an_axis_about_nine_degrees_off():
    # 1.4 arcsec/s near the meridian, if it were all azimuth error.
    azimuth, _ = tracking.polar_error(-1.4, 0.0, LATITUDE)
    assert azimuth == pytest.approx(-9.3, abs=0.2)


def test_drift_terms_are_learned_from_measurements_at_different_hour_angles():
    truth = tracking.polar_terms(4.0, -1.0, LATITUDE)
    observations = [{"ha": h, "rate": tracking.drift_at(truth, h), "sigma": 0.05}
                    for h in (-40, 5, 50)]
    assert tracking.fit_terms(observations) == pytest.approx(truth, abs=1e-6)


def test_a_line_fit_gives_the_drift_and_how_sure_it_is():
    times = [0, 30, 60, 90]
    slope, sigma = tracking.line_fit(times, [10.0, 40.0, 70.0, 100.0])
    assert slope == pytest.approx(1.0) and sigma == pytest.approx(0, abs=1e-9)
    slope, sigma = tracking.line_fit(times, [10.0, 43.0, 68.0, 101.0])
    assert slope == pytest.approx(1.0, abs=0.05) and 0.01 < sigma < 0.1
    assert tracking.line_fit([0, 45], [0.0, 45.0]) == (pytest.approx(1.0), None)


def test_creep_cancels_drift_on_either_side_of_the_mount():
    for west in (True, False):
        creep = tracking.creep_for(-1.4, west)
        assert -1.4 + tracking.creep_effect(creep, west) == pytest.approx(0)


def test_small_or_uncertain_leftover_drift_is_left_alone():
    assert tracking.next_creep(-1.4, 0.10, 0.03, True) == (-1.4, "within the deadband; left alone")
    creep, why = tracking.next_creep(-1.4, 0.30, 0.20, True)
    assert creep == -1.4 and "not clearly" in why


def test_only_part_of_an_error_is_corrected_at_a_time():
    creep, why = tracking.next_creep(0.0, -1.4, 0.05, True)
    assert creep == pytest.approx(-0.98) and why == "adjusted"
    creep, _ = tracking.next_creep(creep, -0.42, 0.05, True)
    assert creep == pytest.approx(-1.274)


def test_a_slight_overshoot_stops_the_motor_rather_than_reversing_it():
    creep, why = tracking.next_creep(-0.2, +0.4, 0.05, True)
    assert creep == 0.0 and "stopped rather than reversed" in why
    creep, why = tracking.next_creep(-0.2, +2.0, 0.05, True)
    assert creep > 0 and "reversed" in why


def test_exposure_limit_follows_the_leftover_drift():
    assert tracking.exposure_limit(1.0) == 2.0
    assert tracking.exposure_limit(0.4) == 5.0
    assert tracking.exposure_limit(0.05) == 10.0   # the gears' own error takes over


def test_the_model_predicts_from_the_polar_error_then_from_what_it_learns(tmp_path):
    model = tracking.Model(tmp_path / "model.json", latitude=LATITUDE)
    assert model.predict(10) is None
    model.set_polar(-9.4, 0.0)
    assert model.predict(0) == pytest.approx(-1.41, abs=0.02)
    assert model.predict(60) == pytest.approx(-0.70, abs=0.02)
    # Two real measurements well apart outrank the polar estimate.
    truth = tracking.polar_terms(-8.0, 2.0, LATITUDE)
    for h in (5, 45):
        model.observe(h, 30, tracking.drift_at(truth, h), 0.05)
    assert model.predict(70) == pytest.approx(tracking.drift_at(truth, 70), abs=1e-6)
    # And it survives being reloaded.
    again = tracking.Model(tmp_path / "model.json", latitude=LATITUDE)
    assert again.predict(70) == pytest.approx(model.predict(70))


def test_one_measurement_only_speaks_for_nearby_sky(tmp_path):
    model = tracking.Model(tmp_path / "model.json", latitude=LATITUDE)
    model.observe(30, 22, -1.2, 0.05)
    assert model.predict(40) == -1.2
    assert model.predict(-50) is None
    model.forget()
    assert model.predict(40) is None and not (tmp_path / "model.json").exists()


def test_drift_is_read_from_how_far_frames_had_to_be_shifted():
    # A camera turned 30 degrees on the sky, 1.32 arcsec per pixel.
    scale, angle = 1.32 / 3600, math.radians(30)
    cd = [[-scale * math.cos(angle), scale * math.sin(angle)],
          [scale * math.sin(angle), scale * math.cos(angle)]]
    # The aim slides north at 1.4 arcsec/s: find the pixel shifts that makes.
    times = np.arange(0, 150, 10.0)
    dec_offset = 1.4 * times / 3600                      # degrees
    shifts = np.linalg.solve(np.array(cd), np.vstack([np.zeros_like(times), dec_offset])).T
    rate, sigma = tracking.drift_from_shifts(times, shifts, cd)
    assert rate == pytest.approx(1.4, abs=1e-6) and sigma < 1e-6
    noisy = shifts + np.random.default_rng(5).normal(0, 0.3, shifts.shape)
    rate, sigma = tracking.drift_from_shifts(times, noisy, cd)
    assert rate == pytest.approx(1.4, abs=3 * sigma) and sigma < 0.01
