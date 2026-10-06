"""Mount logic, run against the simulated handset: nothing here can move a
real telescope."""
import json

import pytest

import config
import mount
import tracking
from simulator import SimulatedHandset

SITE = config.example()["site"]


@pytest.fixture
def scope(tmp_path, monkeypatch):
    # Keep the tests' measurements out of the real cache.
    monkeypatch.setattr(mount, "CLOCK_FILE", tmp_path / "clock.json")
    monkeypatch.setattr(mount, "POINTING_FILE", tmp_path / "pointing.json")
    monkeypatch.setattr(mount, "DRIFT_FILE", tmp_path / "drift.json")
    monkeypatch.setattr(mount, "LOCK_FILE", tmp_path / "MOTION_LOCKED")
    return mount.Mount(handset=SimulatedHandset(slew_seconds=0))


def test_wrap_folds_angles():
    assert mount.wrap(190) == -170
    assert mount.wrap(-190) == 170
    assert mount.wrap(45) == 45


def test_angles_are_sent_as_32_bit_hex():
    assert mount.encode(0) == "00000000"
    assert mount.encode(180) == "80000000"
    assert mount.encode(90) == "40000000"
    assert mount.encode(-90) == "C0000000"


def test_it_starts_at_home(scope):
    assert scope.at_home()
    assert scope.axes() == pytest.approx([0, 90], abs=0.01)


def test_a_handset_left_on_its_version_screen_is_refused():
    with pytest.raises(SystemExit, match="not been set up"):
        mount.Mount(handset=SimulatedHandset(year=22))


def test_zenith_puts_the_tube_on_the_meridian_at_the_sites_latitude(scope):
    scope.zenith(SITE)
    ra_axis, dec_axis = scope.axes()
    assert ra_axis == pytest.approx(90, abs=0.1)
    assert dec_axis == pytest.approx(SITE["latitude"], abs=0.1)


def test_the_handset_clock_error_is_measured_and_stored(scope):
    scope.zenith(SITE)
    offset = json.loads(mount.CLOCK_FILE.read_text(encoding="utf-8"))["offset_deg"]
    expected = mount.wrap(scope.s.sidereal() - mount.true_sidereal(SITE))
    assert offset == pytest.approx(expected, abs=0.1)


def test_the_handset_clock_reads_the_same_on_either_side_of_the_pole(scope):
    scope.zenith(SITE)
    east = scope.handset_sidereal()
    scope.goto((scope.s.sidereal() - 40) % 360, 30)   # 40° west: over the pole
    assert scope.axes()[1] > 90
    assert mount.wrap(scope.handset_sidereal() - east) == pytest.approx(0, abs=0.1)


def test_goto_lands_on_the_target(scope):
    scope.zenith(SITE)
    target = max(mount.STARS, key=lambda name: mount.where(
        mount.find_target(name), SITE)[2] if abs(mount.where(
            mount.find_target(name), SITE)[0]) < 75 else -99)
    scope.goto_target(target, SITE)
    hour_angle, dec, _ = mount.where(mount.find_target(target), SITE)
    believed = mount.wrap(scope.s.sidereal() - scope.radec()[0])
    assert believed == pytest.approx(hour_angle, abs=0.2)
    assert mount.wrap(scope.radec()[1]) == pytest.approx(dec, abs=0.1)


def test_goto_measures_the_handset_clock_itself_if_nobody_has(scope):
    assert not mount.CLOCK_FILE.exists()
    target = next(name for name in mount.STARS
                  if abs(mount.where(mount.find_target(name), SITE)[0]) < 75
                  and mount.where(mount.find_target(name), SITE)[2] > 25)
    scope.goto_target(target, SITE)
    assert mount.CLOCK_FILE.exists()
    hour_angle = mount.where(mount.find_target(target), SITE)[0]
    assert mount.wrap(scope.s.sidereal() - scope.radec()[0]) == pytest.approx(hour_angle, abs=0.2)


def test_targets_too_low_or_too_far_round_are_refused(scope, monkeypatch):
    scope.zenith(SITE)
    monkeypatch.setattr(mount, "where", lambda target, site, when=None: (30.0, 20.0, 12.0))
    with pytest.raises(SystemExit, match="only 12° up"):
        scope.goto_target("Vega", SITE)
    monkeypatch.setattr(mount, "where", lambda target, site, when=None: (100.0, 60.0, 45.0))
    with pytest.raises(SystemExit, match="beyond the 5.75 h limit"):
        scope.goto_target("Vega", SITE)
    assert scope.axes() == pytest.approx([90, SITE["latitude"]], abs=0.2)  # never moved


def test_pointing_at_a_bearing_refuses_the_ground(scope):
    scope.zenith(SITE)
    with pytest.raises(SystemExit, match="between 2° and 89°"):
        scope.point(180, 0, SITE)


def test_the_stored_pointing_error_reverses_in_dec_across_the_pole(scope):
    mount.CLOCK_FILE.write_text(json.dumps({"offset_deg": 0, "saved": 1}), encoding="utf-8")
    mount.save_pointing_error([-10.0, -12.0], west=True)
    assert mount.load_pointing_error(west=True) == [-10.0, -12.0]
    assert mount.load_pointing_error(west=False) == [-10.0, 12.0]


def test_an_old_pointing_error_is_ignored_after_the_handset_is_restarted(scope):
    mount.save_pointing_error([-10.0, -12.0], west=True)
    saved = json.loads(mount.POINTING_FILE.read_text(encoding="utf-8"))["saved"]
    mount.CLOCK_FILE.write_text(json.dumps({"offset_deg": 0, "saved": saved + 60}), encoding="utf-8")
    assert mount.load_pointing_error(west=True) == [0.0, 0.0]


def test_catalogue_and_star_names_resolve():
    assert mount.find_target("m 27")["name"] == "Dumbbell Nebula"
    assert mount.find_target("Ring Nebula")["id"] == "M57"
    assert mount.find_target("vega")["dec"] == pytest.approx(38.78, abs=0.01)
    with pytest.raises(SystemExit):
        mount.find_target("not a real object")


def test_dec_creep_is_sent_in_quarter_arcsecond_steps(scope):
    scope.dec_creep(-1.5)
    assert scope.s.rates[17] == pytest.approx(-1.5 / 3600)
    scope.dec_creep(0)
    assert scope.s.rates[17] == 0


def test_a_centring_run_can_be_recorded(scope, tmp_path):
    scope.zenith(SITE)
    scope.record(tmp_path / "run")
    target = next(name for name in mount.STARS
                  if abs(mount.where(mount.find_target(name), SITE)[0]) < 75
                  and mount.where(mount.find_target(name), SITE)[2] > 25)
    scope.goto_target(target, SITE)
    steps = json.loads((tmp_path / "run" / "steps.json").read_text(encoding="utf-8"))
    assert steps and target in steps[0]["text"]


class FakeClock:
    """Time that only moves when something sleeps, so tests need not wait."""

    def __init__(self):
        import time
        self.t = time.time()

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


@pytest.mark.parametrize("west", [True, False])
@pytest.mark.parametrize("natural", [-1.4, 0.9])
def test_drift_cancelling_settles_on_either_side_of_the_mount(tmp_path, monkeypatch, west, natural):
    """A sky that slides in Dec at a steady rate, as with a rough polar
    alignment: the Dec creep should end up cancelling it, whichever side of
    the mount the tube is on and whichever way the drift runs."""
    from astropy.time import Time
    for name in ("CLOCK_FILE", "POINTING_FILE", "DRIFT_FILE"):
        monkeypatch.setattr(mount, name, tmp_path / f"{name}.json")
    clock = FakeClock()
    monkeypatch.setattr(mount.time, "sleep", clock.sleep)
    handset = SimulatedHandset(slew_seconds=0, clock=clock.now)
    scope = mount.Mount(handset=handset)
    scope.save_clock(SITE)
    scope.goto((handset.sidereal() - (40 if west else -40)) % 360, 30)
    scope.tracking(True)
    assert scope.west() == west
    began = clock.now()

    def sky(ra_hint, dec_hint, radius=30, exposure=1.0):
        # Where the handset thinks it points, plus what the sky has slid by.
        ra, dec = scope.radec()
        slid = natural * (clock.now() - began) / 3600
        return {"ra": ra, "dec": mount.wrap(dec) + slid, "when": Time(clock.now(), format="unix")}

    monkeypatch.setattr(scope, "where_really", sky)
    residual, sigma = scope.cancel_drift(SITE, rounds=6)
    assert abs(residual) <= 0.15
    creep = handset.rates[17] * 3600
    assert natural + tracking.creep_effect(creep, west) == pytest.approx(residual, abs=0.05)
    # What it learned is the natural drift, not the leftover.
    model = scope.drift_model(SITE)
    assert model.observations[-1]["rate"] == pytest.approx(natural, abs=0.1)
    assert model.creep == pytest.approx(creep)   # the rate really set, in quarter-arcsecond steps


def test_a_goto_starts_the_creep_its_part_of_the_sky_needs(scope):
    scope.zenith(SITE)
    model = scope.drift_model(SITE)
    model.set_polar(-9.4, 0.0)
    target = next(name for name in mount.STARS
                  if abs(mount.where(mount.find_target(name), SITE)[0]) < 75
                  and mount.where(mount.find_target(name), SITE)[2] > 25)
    scope.goto_target(target, SITE)
    hour_angle = mount.where(mount.find_target(target), SITE)[0]
    expected = tracking.creep_for(model.predict(hour_angle), scope.west())
    assert scope.s.rates[17] * 3600 == pytest.approx(expected, abs=0.2)


def test_with_nothing_learned_a_goto_leaves_the_dec_motor_alone(scope):
    scope.zenith(SITE)
    target = next(name for name in mount.STARS
                  if abs(mount.where(mount.find_target(name), SITE)[0]) < 75
                  and mount.where(mount.find_target(name), SITE)[2] > 25)
    scope.goto_target(target, SITE)
    assert scope.s.rates[17] == 0


def test_a_daylight_skyline_survey_on_the_simulated_mount(scope, monkeypatch, tmp_path):
    """horizon.py's eye drives the mount and reads the camera. The made-up
    camera shows sky or wall according to where the simulated mount points."""
    import numpy as np
    from astropy import units as u
    from astropy.coordinates import AltAz, HADec, SkyCoord
    from astropy.time import Time

    import camera
    import horizon
    import interface
    import snap

    wall = lambda az: 38.5 if 60 <= az <= 130 or 230 <= az <= 300 else 0

    class Camera:
        def __init__(self, gain=300):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

        def frame(self, seconds):
            offset = json.loads(mount.CLOCK_FILE.read_text(encoding="utf-8"))["offset_deg"]
            ra, dec = scope.radec()
            now, here = Time.now(), mount.location(SITE)
            spot = SkyCoord(HADec(ha=mount.wrap(mount.true_sidereal(SITE) + offset - ra) * u.deg,
                                  dec=mount.wrap(dec) * u.deg, obstime=now, location=here))
            spot = spot.transform_to(AltAz(obstime=now, location=here))
            Camera.aimed.append((spot.az.deg, spot.alt.deg))
            bright = 650000 * seconds     # in proportion to the exposure, as raw frames are
            level = bright if spot.alt.deg > wall(spot.az.deg) else bright / 6
            return np.full((640, 960), min(level, camera.WHITE), np.uint16), {}

    Camera.aimed = []
    monkeypatch.setattr(camera, "Camera", Camera)
    monkeypatch.setattr(mount, "Mount", lambda *a, **k: scope)
    monkeypatch.setattr(snap, "publish", lambda *a, **k: None)
    monkeypatch.setattr(horizon, "STEADY", 0)

    with horizon.eye(SITE, 0.002, 100, daylight=True) as look:
        found, warnings = horizon.trace(look, sorted(range(0, 360, 45), key=horizon.side), low=20)
    assert not warnings
    measured = [f for f in found if f["state"] != "unreachable"]
    assert len(measured) >= 3      # the Sun and the meridian limit rule some out, whatever the hour
    for f in measured:
        if wall(f["az"]) and f["state"] == "edge":
            # The wall's top is between the highest blocked look and the lowest
            # clear one. They close to within FINE of each other unless, at this
            # hour, the limits rule out the heights between them.
            assert f["shut"] < 38.5 < f["clear"]
        elif wall(f["az"]):
            # The limits stopped it looking low enough to meet the wall.
            assert f["state"] == "open" and f["clear"] > 38.5
        else:
            assert f["state"] == "open"
    # The mount really went where each look asked.
    asked = [(l["az"], l["alt"]) for l in look.log if l["open"] is not None]
    for (az, alt), (got_az, got_alt) in zip(asked, Camera.aimed[-len(asked):]):
        assert abs(mount.wrap(az - got_az)) < 0.5 and abs(alt - got_alt) < 0.5
    assert not scope.s.tracking    # by day it holds still on the rooftop

    # Locked: it refuses before the mount is asked for anything.
    mount.LOCK_FILE.write_text("testing", encoding="utf-8")
    before = scope.axes()
    with pytest.raises(interface.Refusal) as refusal:
        with horizon.eye(SITE, 0.002, 100, daylight=True) as look:
            horizon.trace(look, [0, 90], low=20)
    assert refusal.value.code_name == "MOTION_LOCKED" and scope.axes() == before
