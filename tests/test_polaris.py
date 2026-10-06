"""Finding Polaris by day and setting the polar axis from it, on the simulated
mount with a made-up daytime sky: nothing here can move a real telescope.

The pretend camera is worked out in three dimensions from where the mount's
axes are, how the mount is set up wrongly, and how the camera sits in the
focuser, so the flat arithmetic in polaris.py is checked against the real
geometry and not against itself."""
import argparse
import math

import numpy as np
import pytest

import config
import interface
import mount
import polaralign
import polaris
from simulator import SimulatedHandset

SITE = config.example()["site"]
SHAPE = (912, 1360)        # the half-size picture: a camera a quarter the real one's size


class Sky:
    """A daytime sky with Polaris in it, seen through a mount whose polar
    axis is `east` degrees east of north and `high` degrees too high."""
    east, high = 0.0, 0.0
    roll = 25.0             # how the camera is turned in the focuser, degrees
    mirrored = False        # a star diagonal would flip the picture
    dust = True             # a speck on the sensor: bright against the sky, and going nowhere
    cloud = False           # nothing but cloud
    night = False
    scope = None
    frames = 0

    @classmethod
    def polaris(cls):
        """Polaris in the picture now, in pixels, by the full geometry."""
        lat = math.radians(SITE["latitude"])
        # Up / north / east parts of a vector given in pole-and-meridian axes.
        def ground(v):
            return np.array([v[2] * math.sin(lat) + v[0] * math.cos(lat),
                             v[2] * math.cos(lat) - v[0] * math.sin(lat), -v[1]])
        hour_angle, dec, _ = mount.where(polaris.POLARIS, SITE)
        star = ground(polaralign.vector(hour_angle, dec))
        # The mount's own axes on the ground: its polar axis, the upward
        # direction square to it (the plane its bar hangs in), and west.
        alt, az = lat + math.radians(cls.high), math.radians(cls.east)
        z = np.array([math.sin(alt), math.cos(alt) * math.cos(az), math.cos(alt) * math.sin(az)])
        x = np.array([1.0, 0, 0]) - z[0] * z
        x /= np.linalg.norm(x)
        y = np.cross(z, x)
        y = y if y[2] < 0 else -y           # west: the east part is negative
        seen = np.array([star @ x, star @ y, star @ z])      # Polaris in the mount's axes
        ra_axis, dec_axis = cls.scope.axes()
        h, d = math.radians(ra_axis - 90), math.radians(dec_axis)
        tube = np.array([math.cos(d) * math.cos(h), math.cos(d) * math.sin(h), math.sin(d)])
        up_dec = np.array([-math.sin(d) * math.cos(h), -math.sin(d) * math.sin(h), math.cos(d)])
        along_ha = np.array([-math.sin(h), math.cos(h), 0.0])
        if seen @ tube < 0.99:
            return None
        right, up = math.degrees(seen @ along_ha), math.degrees(seen @ up_dec)
        if cls.mirrored:
            right = -right
        r = math.radians(cls.roll)
        px = (right * math.cos(r) - up * math.sin(r)) / polaris.scale()
        py = (right * math.sin(r) + up * math.cos(r)) / polaris.scale()
        return SHAPE[1] / 2 + px, SHAPE[0] / 2 + py

    @classmethod
    def view(cls):
        cls.frames += 1
        rng = np.random.default_rng(cls.frames)
        yy, xx = np.indices(SHAPE)
        if cls.night:
            return rng.normal(40, 3, SHAPE)
        # Bright, shaded toward the corners, with the grain of the light.
        sky = 8000 * (1 - 0.25 * ((xx - SHAPE[1] / 2) ** 2 + (yy - SHAPE[0] / 2) ** 2) / SHAPE[1] ** 2)
        if cls.dust:
            sky *= 1 + 0.06 * np.exp(-((xx - 300) ** 2 + (yy - 200) ** 2) / (2 * 9.0 ** 2))
        if cls.cloud:
            return sky + rng.normal(0, 25, SHAPE)
        where = cls.polaris()
        if where:
            sky = sky + 1600 * np.exp(-((xx - where[0]) ** 2 + (yy - where[1]) ** 2) / (2 * 4.0 ** 2))
        return sky + rng.normal(0, 25, SHAPE)


class Camera:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def frame(self, seconds):
        lum = Sky.view() * (min(seconds / 0.002, 1.0) if not Sky.night else seconds / 0.002)
        # Clear sky is blue and cloud is grey; the four colour cells still add up to the brightness.
        red, blue = (1.0, 1.0) if Sky.cloud else (0.5, 1.5)
        mosaic = np.repeat(np.repeat(lum / 4, 2, axis=0), 2, axis=1)
        mosaic[0::2, 0::2] *= red
        mosaic[1::2, 1::2] *= blue
        return mosaic.astype(np.uint16), {}


def jump(scope, ra_axis, dec_axis):
    """Put the pretend mount at a pair of readings at once: it turns at a
    real mount's pace, and the search makes a hundred turns."""
    scope.s.ra_axis, scope.s.dec_axis = ra_axis % 360, dec_axis


@pytest.fixture
def scope(tmp_path, monkeypatch):
    for name in ("CLOCK_FILE", "POINTING_FILE", "DRIFT_FILE"):
        monkeypatch.setattr(mount, name, tmp_path / f"{name}.json")
    monkeypatch.setattr(mount, "LOCK_FILE", tmp_path / "MOTION_LOCKED")
    monkeypatch.setattr(polaris, "FOUND", tmp_path / "cache" / "polaris.json")
    monkeypatch.setattr(polaris, "VIEW", tmp_path / "web" / "polaris.jpg")
    # The pretend camera has a quarter of the pixels and each takes in three
    # times as much sky, so a search is a hundred looks and not a thousand.
    monkeypatch.setattr(polaris, "scale", lambda: 0.0011)
    monkeypatch.setattr(config, "field_height", lambda cfg=None: SHAPE[0] * 0.0011)
    # Polaris is nowhere near the Sun; the pretend sky has no Sun to refuse over.
    monkeypatch.setattr(mount, "direction", lambda azimuth, altitude, site: (0.0, 90.0))
    Sky.east, Sky.high, Sky.roll, Sky.mirrored = 0.0, 0.0, 25.0, False
    Sky.dust, Sky.cloud, Sky.night, Sky.frames = True, False, False, 0
    Sky.scope = mount.Mount(handset=SimulatedHandset(slew_seconds=0))
    return Sky.scope


def test_the_search_stays_inside_the_reach_and_covers_the_ground():
    looks = polaris.spots(3.0, 0.4)
    assert looks[0] == (mount.HOME_RA_AXIS, mount.HOME_DEC_AXIS)
    assert all(abs(ra) <= polaris.REACH and abs(90 - dec) <= 3.0 + 0.4 for ra, dec in looks)
    # The RA axis never jumps the long way round between one look and the next.
    assert max(abs(b[0] - a[0]) for a, b in zip(looks, looks[1:])) <= 2 * polaris.REACH
    # Every direction within the radius is within half a frame of some look.
    def aimed(ra, dec):
        return (90 - dec) * polaris.outward(ra - 90)
    centres = np.array([aimed(*spot) for spot in looks])
    rng = np.random.default_rng(1)
    for _ in range(400):
        distance, angle = 3.0 * math.sqrt(rng.uniform()), rng.uniform(0, 360)
        gap = np.linalg.norm(centres - distance * polaris.outward(angle), axis=1).min()
        assert gap < 0.33      # half the short side of the real camera's 0.67° by 1.0° frame
    # Both sides of the pole are used, and the readings mean what the mount means by them.
    assert polaris.axes_for(1.0, -90) == (0, 89.0) and polaris.axes_for(1.0, 90) == (0, 91.0)


def test_a_star_is_told_from_dust_and_from_nothing(scope):
    hour_angle, dec, _ = mount.where(polaris.POLARIS, SITE)
    on_it = polaris.axes_for(90 - dec + 0.1, hour_angle)       # Polaris a tenth of a degree off the middle
    jump(scope, *on_it)
    with_star = Sky.view()
    jump(scope, 40, 88.0)
    blank = Sky.view()
    # By itself the speck of dust is the brightest point in either frame.
    alone = polaris.star(blank)
    assert alone and math.hypot(alone[0] - 300, alone[1] - 200) < 3
    # Against a frame from elsewhere the dust goes, and only the star is left.
    assert polaris.star(blank, with_star) is None
    found = polaris.star(with_star, blank)
    jump(scope, *on_it)
    assert found and math.hypot(found[0] - Sky.polaris()[0], found[1] - Sky.polaris()[1]) < 1.5


@pytest.mark.parametrize("east, high", [(0.0, 0.0), (1.6, -0.9), (-2.2, 1.1)])
def test_polaris_is_found_and_the_axis_measured(scope, east, high):
    Sky.east, Sky.high = east, high
    found = polaris.find(scope, SITE, radius=4.0, cam_class=Camera, aim=jump, exact=jump)
    assert found["found"] and polaris.FOUND.exists() and polaris.VIEW.exists()
    here = Sky.polaris()
    assert math.hypot(found["x"] - here[0], found["y"] - here[1]) < 2
    assert found["off_centre_deg"] < 0.1           # it was brought to the middle of the picture
    assert not scope.s.tracking
    before = scope.axes()

    azimuth, altitude, how = polaris.align(scope, SITE, cam_class=Camera, aim=jump)
    assert azimuth == pytest.approx(east, abs=0.05) and altitude == pytest.approx(high, abs=0.05)
    assert how["sightings"] == 3 and how["misfit_arcmin"] < 1
    assert scope.axes() == pytest.approx(before, abs=1e-6)      # it ends where it began


@pytest.mark.parametrize("roll, mirrored", [(-140.0, False), (70.0, True)])
def test_however_the_camera_sits_in_the_focuser(scope, roll, mirrored):
    Sky.east, Sky.high, Sky.roll, Sky.mirrored = 1.0, 0.7, roll, mirrored
    assert polaris.find(scope, SITE, cam_class=Camera, aim=jump, exact=jump)["found"]
    azimuth, altitude, _ = polaris.align(scope, SITE, cam_class=Camera, aim=jump)
    assert azimuth == pytest.approx(1.0, abs=0.05) and altitude == pytest.approx(0.7, abs=0.05)


def test_the_real_turning_of_the_axes_is_used(scope):
    # One look away from home with the mount's own seek, not the test's jump.
    polaris.aim(scope, 4.0, 89.6)
    assert scope.axes() == pytest.approx([4.0, 89.6], abs=0.05)
    # The search's quicker turn: Dec as exactly, the RA axis only near enough.
    stages = mount.STAGES
    polaris.aim_roughly(scope, 12.0, 89.2)
    ra_axis, dec_axis = scope.axes()
    assert abs(ra_axis - 12.0) <= polaris.NEAR_ENOUGH + 0.3 and dec_axis == pytest.approx(89.2, abs=0.05)
    assert mount.STAGES is stages


def test_cloud_finds_nothing_and_goes_home(scope, monkeypatch):
    Sky.cloud = True
    # Grey all over: it waits no longer than it is told to, and stops at the first look.
    found = polaris.find(scope, SITE, radius=1.0, cam_class=Camera, aim=jump, patience=0)
    assert found == {"found": False, "looks": 0, "radius_deg": 1.0, "cloud": True}
    assert scope.at_home() and not polaris.FOUND.exists()
    # Blue, with nothing in it (as when the focus is far out): every place is looked at.
    monkeypatch.setattr(polaris, "BLUE", 0.5)
    found = polaris.find(scope, SITE, radius=1.0, cam_class=Camera, aim=jump)
    assert found == {"found": False, "looks": found["looks"], "radius_deg": 1.0} and found["looks"] > 5
    assert scope.at_home() and not polaris.FOUND.exists()
    with pytest.raises(interface.Refusal) as refusal:
        polaris.align(scope, SITE, cam_class=Camera, aim=jump)
    assert "find first" in refusal.value.message and scope.at_home()


def test_by_night_it_leaves_it_to_the_plate_solver(scope):
    Sky.night = True
    with pytest.raises(interface.Refusal) as refusal:
        polaris.find(scope, SITE, cam_class=Camera, aim=jump)
    assert "dark enough" in refusal.value.message


def test_it_refuses_before_moving(scope, monkeypatch):
    with pytest.raises(interface.Refusal):
        polaris.plan(SITE, radius=20)
    with pytest.raises(interface.Refusal) as refusal:
        polaris.plan(dict(SITE, latitude=21.0), radius=3)
    assert refusal.value.code_name == "TARGET_BELOW_ALTITUDE_LIMIT"
    # Away from the pole there is nothing for align to do.
    jump(scope, 30, 40)
    with pytest.raises(interface.Refusal) as refusal:
        polaris.align(scope, SITE, cam_class=Camera, aim=jump)
    assert "not near the pole" in refusal.value.message and scope.axes() == pytest.approx([30, 40])
    # Locked: the command refuses before the mount is opened.
    mount.LOCK_FILE.write_text("testing", encoding="utf-8")
    monkeypatch.setattr(mount, "Mount", lambda *a, **k: pytest.fail("the mount was opened"))
    for command in ("find", "align"):
        args = argparse.Namespace(command=command, radius=3.0, dry_run=False, json=False)
        with pytest.raises(interface.Refusal) as refusal:
            polaris.run(args)
        assert refusal.value.code_name == "MOTION_LOCKED"
    for check in (lambda: polaris.plan(SITE), lambda: polaris.align(scope, SITE, cam_class=Camera, aim=jump)):
        with pytest.raises(interface.Refusal) as refusal:
            check()
        assert refusal.value.code_name == "MOTION_LOCKED"
    assert scope.axes() == pytest.approx([30, 40])
