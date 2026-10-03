"""The astronomy behind the night report."""
from datetime import date, datetime, timezone

import numpy as np
import pytest

import config
import sky


@pytest.fixture(scope="module")
def night():
    # A fixed autumn night at the example site (Greenwich).
    return sky.Night(config.example(), date(2026, 10, 3),
                     now=datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc))


def test_separation_of_known_angles():
    assert sky.separation(0, 0, 90, 0) == pytest.approx(90)
    assert sky.separation(10, 80, 190, 80) == pytest.approx(20)
    assert sky.separation(123, -45, 123, -45) == pytest.approx(0, abs=1e-4)


def test_air_mass_grows_towards_the_horizon():
    assert sky.air_mass(90) == pytest.approx(1.0)
    # The formula used for scattered moonlight sits a little under 1/sin(alt).
    assert 1.8 < sky.air_mass(30) < 2.0
    assert sky.air_mass(10) > sky.air_mass(30)


def test_compass_points():
    assert [sky.compass(a) for a in (0, 90, 180, 270, 359, 225)] == ["N", "E", "S", "W", "N", "SW"]


def test_no_moonlight_when_the_moon_is_down():
    assert sky.moonlight(0, moon_alt=-5, target_alt=60, sep=40) == 0


def test_full_moon_is_brighter_than_a_crescent():
    full = sky.moonlight(0, 40, 60, 60)
    crescent = sky.moonlight(130, 40, 60, 60)
    assert full > 10 * crescent > 0


def test_full_moon_brightens_a_dark_sky_by_several_magnitudes():
    lit = sky._to_mag(sky._to_nl(21.7) + sky.moonlight(0, 60, 90, 60))
    assert 17.5 < lit < 19.0


def test_surface_brightness_from_magnitude_and_size():
    # Andromeda: magnitude 3.4 over 178' x 70' is about 22.3 mag/arcsec².
    m31 = {"mag": 3.44, "size": 177.8, "minor": 69.7}
    assert sky.surface_brightness(m31) == pytest.approx(22.3, abs=0.1)
    assert sky.surface_brightness({"mag": None, "size": 5}) == sky.DEFAULT_SURFACE_BRIGHTNESS


def test_the_night_is_dark_for_hours_in_october(night):
    assert night.dark_level == "astronomical"
    hours = night.dark.sum() * sky.STEP_MIN / 60
    assert 7.5 < hours < 10


def test_polaris_sits_at_the_sites_latitude(night):
    alt, az = night.altaz_fixed([37.95], [89.26])
    assert alt[0].min() > 50 and alt[0].max() < 53
    assert np.all((az[0] < 3) | (az[0] > 357))


def test_blocked_directions_raise_the_horizon(night):
    night.blocked = [{"from": 150, "to": 210, "altitude": 40}]
    try:
        limits = night.horizon(np.array([100.0, 180.0, 300.0]), 20)
    finally:
        night.blocked = []
    assert list(limits) == [20, 40, 20]


def test_a_block_can_span_north(night):
    night.blocked = [{"from": 340, "to": 20, "altitude": 35}]
    try:
        limits = night.horizon(np.array([350.0, 10.0, 90.0]), 20)
    finally:
        night.blocked = []
    assert list(limits) == [35, 35, 20]


def test_a_far_southern_object_never_qualifies(night):
    target = {"id": "x", "kind": "galaxy", "mag": 8.0, "ra": 10.0, "dec": -80.0}
    n = len(night.unix)
    alt, az = night.altaz_fixed([10.0], [-80.0])
    assert night.assess(target, np.full(n, 10.0), np.full(n, -80.0), alt[0], az[0]) is None


def test_a_well_placed_bright_object_scores_high(night):
    # The Dumbbell is high in the evening sky in October.
    target = {"id": "M27", "name": "Dumbbell Nebula", "kind": "planetary nebula",
              "mag": 7.4, "size": 8.0, "minor": 5.7, "messier": True,
              "ra": 299.90, "dec": 22.72}
    n = len(night.unix)
    alt, az = night.altaz_fixed([target["ra"]], [target["dec"]])
    result = night.assess(target, np.full(n, target["ra"]), np.full(n, target["dec"]), alt[0], az[0])
    assert result is not None and result["score"] > 60
    assert result["best_alt"] > 50


def test_the_catalogue_loads_with_all_the_messier_objects():
    targets = sky.load_targets()
    messier = [t for t in targets if t["messier"]]
    assert len(messier) == 109  # M102 is a duplicate of M101
    assert all(0 <= t["ra"] < 360 and -90 <= t["dec"] <= 90 for t in targets)
