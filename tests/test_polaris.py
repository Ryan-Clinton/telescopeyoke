"""Finding Polaris by day and setting the polar axis from it, on the simulated
mount with a made-up daytime sky: nothing here can move a real telescope.

The pretend camera is worked out in three dimensions from where the mount's
axes are, how the mount is set up wrongly, and how the camera sits in the
focuser, so the flat arithmetic in polaris.py is checked against the real
geometry and not against itself."""
import argparse
import json
import math
import time

import numpy as np
import pytest

import config
import focus
import interface
import landmark
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
    bright = 1600.0         # how far Polaris stands above the sky at its middle
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
            sky = sky + cls.bright * np.exp(-((xx - where[0]) ** 2 + (yy - where[1]) ** 2) / (2 * 4.0 ** 2))
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
    # One frame a look, so a search is quick; adding frames up has its own test.
    monkeypatch.setattr(polaris, "FRAMES", 1)
    monkeypatch.setattr(polaris, "SCENE_FOCUS", tmp_path / "cache" / "focus_scene.json")
    monkeypatch.setattr(focus, "FOCUS_FILE", tmp_path / "cache" / "focus.json")
    monkeypatch.setattr(landmark, "FOLDER", tmp_path / "landmarks")
    monkeypatch.setattr(polaris, "RUNS", tmp_path / "polaris-runs")
    Sky.east, Sky.high, Sky.roll, Sky.mirrored, Sky.bright = 0.0, 0.0, 25.0, False, 1600.0
    Sky.dust, Sky.cloud, Sky.night, Sky.frames = True, False, False, 0
    Sky.scope = mount.Mount(handset=SimulatedHandset(slew_seconds=0))
    return Sky.scope


def test_the_search_covers_the_ground_with_one_sweep_of_the_ra_axis_for_each_part():
    looks = polaris.spots(3.0, 0.37)
    assert looks[0] == (mount.HOME_RA_AXIS, mount.HOME_DEC_AXIS)
    assert all(abs(ra) <= polaris.REACH and abs(90 - dec) <= 3.0 + 0.37 for ra, dec in looks)
    assert len(set(looks)) == len(looks)
    # Every direction within the radius is within half the real camera's short
    # side (0.67° by 1.0°) of some look, with room for where the tube stops.
    centres = np.array([polaris.aimed(*spot) for spot in looks])
    rng = np.random.default_rng(1)
    for _ in range(600):
        distance, angle = 3.0 * math.sqrt(rng.uniform()), rng.uniform(0, 360)
        gap = np.linalg.norm(centres - distance * polaris.outward(angle), axis=1).min()
        assert gap < 0.335 - polaris.DEC_NEAR_ENOUGH + 0.03
    # The near part comes first, and in each part the RA axis only ever goes
    # one way: across for the near part and back for the rest.
    near = [spot for spot in looks[1:] if abs(90 - spot[1]) <= 1.2 + 0.37]
    assert looks[1:1 + len(near)] == near
    rest = looks[1 + len(near):]
    assert all(b[0] >= a[0] for a, b in zip(near, near[1:]))
    assert all(b[0] <= a[0] for a, b in zip(rest, rest[1:]))
    # So the RA axis turns far less than going round the pole ring by ring would have it.
    assert sum(abs(b[0] - a[0]) for a, b in zip(looks, looks[1:])) <= 5 * polaris.REACH + 1     # out to one side, across, and back
    # Both sides of the pole are used, and the readings mean what the mount means by them.
    assert polaris.axes_for(1.0, -90) == (0, 89.0) and polaris.axes_for(1.0, 90) == (0, 91.0)
    assert polaris.aimed(0, 89.0) == pytest.approx(-polaris.aimed(0, 91.0))


def on_polaris(off=0.1):
    """Readings that put Polaris `off` degrees from the middle of the picture."""
    hour_angle, dec, _ = mount.where(polaris.POLARIS, SITE)
    return polaris.axes_for(90 - dec + off, hour_angle)


def test_a_star_is_told_from_dust_and_from_nothing(scope):
    jump(scope, *on_polaris())
    with_star = Sky.view()
    jump(scope, 40, 88.0)
    blank = Sky.view()
    # By itself the speck of dust is the brightest point in either frame.
    alone = polaris.star(blank)
    assert alone and math.hypot(alone[0] - 300, alone[1] - 200) < 3
    # Against a frame from elsewhere the dust goes, and only the star is left.
    assert polaris.star(blank, with_star) is None
    found = polaris.star(with_star, blank)
    jump(scope, *on_polaris())
    assert found and math.hypot(found[0] - Sky.polaris()[0], found[1] - Sky.polaris()[1]) < 1.5
    seen = polaris.brightest(with_star, blank)
    assert seen["roundness"] > 0.8 and 5 < seen["width_px"] < 40        # a round point, not a streak
    # The middle of several looks is a flat with no star in it, though one of them had the star.
    others = []
    for ra_axis in (10, 30, 50, 70):
        jump(scope, ra_axis, 88.0)
        others.append(Sky.view())
    flat = polaris.middle_of(others[:2] + [with_star] + others[2:])
    assert polaris.star(with_star, flat) and polaris.star(others[0], flat) is None


def test_adding_frames_up_brings_out_a_faint_star(scope):
    Sky.bright = 70.0
    cam = Camera()
    jump(scope, 40, 88.0)
    flat = polaris.look(cam, frames=8)[0]
    jump(scope, *on_polaris())
    one = polaris.brightest(polaris.look(cam, frames=1)[0], flat)["stands_out"]
    eight = polaris.brightest(polaris.look(cam, frames=8)[0], flat)["stands_out"]
    assert one < polaris.STANDS_OUT < eight and eight > 1.8 * one       # one frame misses it; eight find it


def test_a_point_that_does_not_move_with_the_sky_is_not_a_star(scope):
    cam = Camera()
    # Blank sky and a speck of dust, with no flat to take it out: it is there
    # twice running, but it stays put when the tube is tipped.
    jump(scope, 40, 88.0)
    speck = polaris.brightest(Sky.view())
    note = polaris.verified(scope, cam, speck, None, 0.002, jump)
    assert note["repeated"] and note["confidence"] == "none" and note["dither_moved_deg"] < 0.01
    assert scope.axes() == pytest.approx([40, 88.0])           # the tube was put back
    # The star moves by what the tube did.
    flat = Sky.view()
    jump(scope, *on_polaris())
    note = polaris.verified(scope, cam, polaris.brightest(Sky.view(), flat), flat, 0.002, jump)
    assert note["confidence"] == "high" and note["dither_match"] == pytest.approx(1.0, abs=0.1)
    # Slack in the gears: the tube turns less than the readout says, and the star with it.
    def slack(scope, ra_axis, dec_axis):
        jump(scope, ra_axis, dec_axis)
        Sky.slack = 0.04 if abs(dec_axis - on_it[1]) > 1e-6 else 0.0
    on_it = on_polaris()
    real = Sky.polaris
    try:
        def held_back():
            scope.s.dec_axis -= Sky.slack * (1 if scope.s.dec_axis > on_it[1] else -1)
            try:
                return real()
            finally:
                scope.s.dec_axis += Sky.slack * (1 if scope.s.dec_axis > on_it[1] else -1)
        Sky.slack, Sky.polaris = 0.0, staticmethod(held_back)
        note = polaris.verified(scope, cam, polaris.brightest(Sky.view(), flat), flat, 0.002, slack)
        assert note["confidence"] == "medium" and 0.4 < note["dither_match"] < 0.85
    finally:
        Sky.polaris = real


@pytest.mark.parametrize("east, high", [(0.0, 0.0), (1.6, -0.9), (-2.2, 1.1)])
def test_polaris_is_found_and_the_axis_measured(scope, east, high):
    Sky.east, Sky.high = east, high
    found = polaris.find(scope, SITE, radius=3.0, cam_class=Camera, aim=jump, exact=jump)
    assert found["found"] and polaris.FOUND.exists() and polaris.VIEW.exists()
    here = Sky.polaris()
    assert math.hypot(found["x"] - here[0], found["y"] - here[1]) < 2
    assert found["off_centre_deg"] < 0.1           # it was brought to the middle of the picture
    assert found["confidence"] == "high" and found["dither_match"] == pytest.approx(1.0, abs=0.15)
    assert not scope.s.tracking

    azimuth, altitude, how = polaris.align(scope, SITE, cam_class=Camera, aim=jump)
    assert azimuth == pytest.approx(east, abs=0.05) and altitude == pytest.approx(high, abs=0.05)
    assert how["sightings"] == 5 and how["used"] == 5 and how["misfit_arcmin"] < 1
    assert all(miss < 1 for miss in how["misses_arcmin"])
    # It ends on the middle sighting: where it began.
    assert scope.axes() == pytest.approx([found["ra_axis_deg"] % 360, found["dec_axis_deg"]], abs=1e-3)


@pytest.mark.parametrize("roll, mirrored", [(-140.0, False), (70.0, True)])
def test_however_the_camera_sits_in_the_focuser(scope, roll, mirrored):
    Sky.east, Sky.high, Sky.roll, Sky.mirrored = 1.0, 0.7, roll, mirrored
    assert polaris.find(scope, SITE, cam_class=Camera, aim=jump, exact=jump)["found"]
    azimuth, altitude, _ = polaris.align(scope, SITE, cam_class=Camera, aim=jump)
    assert azimuth == pytest.approx(1.0, abs=0.05) and altitude == pytest.approx(0.7, abs=0.05)


def test_one_bad_sighting_in_five_is_left_out():
    centre, radius, sense = np.array([400.0, -900.0]), 1500.0, -1
    points = []
    for ra_axis in (-20.0, -10.0, 0.0, 10.0, 20.0):
        angle = math.radians(70 + sense * ra_axis)
        points.append((ra_axis, centre[0] + radius * math.cos(angle), centre[1] + radius * math.sin(angle)))
    cx, cy, found_sense, misfit, used, misses = polaris.fitted(points)
    assert (cx, cy) == pytest.approx(centre, abs=0.01) and found_sense == sense and len(used) == 5
    # A cable catches at one sighting: the star is 40 pixels from where it should be.
    knocked = list(points)
    knocked[3] = (10.0, points[3][1] + 40, points[3][2] - 10)
    cx, cy, found_sense, misfit, used, misses = polaris.fitted(knocked)
    assert (cx, cy) == pytest.approx(centre, abs=0.5) and len(used) == 4 and misses[3] is None
    assert max(miss for miss in misses if miss is not None) < 0.5
    # With only three there is nothing to tell a bad one by: all are used.
    assert len(polaris.fitted(knocked[2:])[4]) == 3


def test_it_watches_while_the_bolts_are_turned(scope):
    Sky.east, Sky.high = 0.3, 0.2
    assert polaris.find(scope, SITE, cam_class=Camera, aim=jump, exact=jump)["found"]
    said = []

    def speak(words):
        said.append(words)
        if len(said) == 2:
            Sky.east, Sky.high = 0.2, 0.2          # the azimuth bolts are turned part of the way
        if len(said) == 3:
            Sky.east, Sky.high = 0.0, 0.0          # and then the rest, and the altitude
        if len(said) == 4:
            Sky.east, Sky.high = 2.5, 0.0          # and then far too far: the star goes out of the picture
    before = scope.axes()
    azimuth, altitude, _ = polaris.align(scope, SITE, cam_class=Camera, aim=jump, watch=5,
                                         pause=lambda seconds: None, speak=speak)
    assert said[0] == "swing the north end 0.3 west, lower 0.2" and said[1] == said[0]
    assert said[2] == "swing the north end 0.2 west, lower 0.2"
    assert said[3].startswith("close enough")
    assert said[4].startswith("the star has left the picture")
    assert abs(azimuth) < 0.05 and abs(altitude) < 0.05           # the last sight of it is the answer given
    assert scope.axes() == pytest.approx(before, abs=1e-3)       # the RA axis was not turned again
    assert polaris.VIEW.exists()


def test_the_ring_is_where_polaris_belongs(scope):
    # With the axis on the pole, Polaris is already where it belongs, whichever way the picture is turned.
    for Sky.roll, Sky.mirrored in ((25.0, False), (-110.0, True)):
        jump(scope, *on_polaris(0.15))
        ra_axis, dec_axis = scope.axes()
        ra_axis = mount.wrap(ra_axis)
        here = np.array(Sky.polaris())
        # The axis in the picture and the picture's turning, found as align finds them.
        jump(scope, ra_axis, dec_axis + 0.1)
        shift = (np.array(Sky.polaris()) - here) / 0.1
        points = []
        for turn in (-10, 0, 10):
            jump(scope, ra_axis + turn, dec_axis)
            points.append((ra_axis + turn, *Sky.polaris()))
        cx, cy, sense, _ = polaris.turned(points)
        jump(scope, ra_axis, dec_axis)
        assert polaris.belongs((cx, cy), sense, shift, ra_axis, SITE) == pytest.approx(here, abs=1.5)


def test_the_real_turning_of_the_axes_is_used(scope):
    # One look away from home with the mount's own seek, not the test's jump.
    polaris.aim(scope, 4.0, 89.6)
    assert scope.axes() == pytest.approx([4.0, 89.6], abs=0.05)
    # The search's quicker turn: each axis only near enough, and where it stopped is known.
    stages = mount.STAGES
    polaris.aim_roughly(scope, 12.0, 89.2)
    ra_axis, dec_axis = scope.axes()
    assert abs(ra_axis - 12.0) <= polaris.NEAR_ENOUGH + 0.3
    assert abs(dec_axis - 89.2) <= polaris.DEC_NEAR_ENOUGH + 0.05
    assert mount.STAGES is stages


def test_cloud_finds_nothing_and_goes_home(scope, monkeypatch):
    Sky.cloud = True
    # Grey all over: it waits no longer than it is told to, and stops at the first look.
    found = polaris.find(scope, SITE, radius=1.0, cam_class=Camera, aim=jump, patience=0)
    assert found == {"found": False, "looks": 0, "radius_deg": 1.0, "cloud": True}
    assert scope.at_home() and not polaris.FOUND.exists()
    # Blue, with nothing in it (as when the focus is far out): every place is looked at.
    monkeypatch.setattr(polaris, "BLUE", 0.5)
    found = polaris.find(scope, SITE, radius=1.0, cam_class=Camera, aim=jump, exact=jump)
    assert found["found"] is False and found["looks"] > 5 and found["best_stands_out"] < polaris.STANDS_OUT
    assert scope.at_home() and not polaris.FOUND.exists()
    with pytest.raises(interface.Refusal) as refusal:
        polaris.align(scope, SITE, cam_class=Camera, aim=jump)
    assert "find first" in refusal.value.message and scope.at_home()


def test_a_search_can_be_kept_to_learn_from(scope, tmp_path):
    Sky.east = 0.8
    folder = tmp_path / "polaris-runs" / "one"
    found = polaris.find(scope, SITE, radius=2.0, cam_class=Camera, aim=jump, exact=jump, record=folder)
    kept = json.loads((folder / "search.json").read_text(encoding="utf-8"))
    assert found["found"] and kept["result"]["confidence"] == "high" and len(kept["looks"]) == found["looks"]
    first, last = kept["looks"][0], kept["looks"][-1]
    assert first["axes"] == pytest.approx([0, 90]) and last["blue_over_red"] > polaris.BLUE
    # Every look is there with its brightest point, the first judged once the second gave it a flat;
    # the one with the star in it stands far out, and the others do not.
    standing = [look["brightest"]["stands_out"] for look in kept["looks"]]
    assert max(standing) > 5 * polaris.STANDS_OUT and sorted(standing)[-2] < polaris.STANDS_OUT
    for i in range(found["looks"]):
        small = np.load(folder / f"look-{i + 1:03d}.npy")
        assert small.shape == (SHAPE[0] // 4, SHAPE[1] // 4) and (folder / f"look-{i + 1:03d}.jpg").exists()
    candidates = json.loads((folder / "candidates.json").read_text(encoding="utf-8"))
    assert candidates[-1]["confidence"] == "high" and candidates[-1]["dither_match"] == pytest.approx(1.0, abs=0.15)
    # A search that finds nothing says how near it came.
    Sky.bright, folder = 0.0, tmp_path / "polaris-runs" / "two"
    assert polaris.find(scope, SITE, radius=0.8, cam_class=Camera, aim=jump, exact=jump, record=folder)["found"] is False
    kept = json.loads((folder / "search.json").read_text(encoding="utf-8"))
    assert kept["result"]["found"] is False and 0 < kept["result"]["best_stands_out"] < polaris.STANDS_OUT


def test_whether_it_is_worth_trying_is_said_first(scope, monkeypatch, capsys):
    found = polaris.check(SITE, cam_class=Camera, frames=4)
    assert found["clear"] and found["blue_over_red"] == pytest.approx(3.0, abs=0.1) and found["burnt_out"] == 0
    assert 0.3 < found["background"] < 0.8 and found["sky_drift"] < 0.03 and found["corner_shading"] > 0.05
    assert found["rating"] in ("poor", "fair", "good", "very good") and found["focus"] is None
    assert -90 <= found["sun_height_deg"] <= 90 and 50 < found["sun_from_pole_deg"] < 130
    assert "NOT CHECKED" in capsys.readouterr().out
    assert scope.at_home()
    assert [polaris.rating(height) for height in (40, 20, 8, -2)] == ["poor", "fair", "good", "very good"]
    # Grey sky is said to be poor whatever the Sun is doing.
    Sky.cloud = True
    assert polaris.check(SITE, cam_class=Camera, frames=4)["rating"] == "poor"
    Sky.cloud = False

    # The search will not start on a focus nobody has checked, unless told to.
    monkeypatch.setattr(config, "load", lambda: {"site": SITE})
    monkeypatch.setattr(mount, "Mount", lambda *a, **k: pytest.fail("the mount was opened"))
    args = argparse.Namespace(command="find", radius=None, anyway=False, record=False, watch=0, quiet=True,
                              dry_run=False, json=False)
    with pytest.raises(interface.Refusal) as refusal:
        polaris.run(args)
    assert "focus has not been checked" in refusal.value.message
    # A daytime focus check this afternoon counts; one from yesterday does not.
    polaris.SCENE_FOCUS.parent.mkdir(parents=True, exist_ok=True)
    polaris.SCENE_FOCUS.write_text(json.dumps({"sharpness": 9.0, "saved": time.time() - 3600}), encoding="utf-8")
    assert polaris.focus_checked() == {"how": "on a daytime view", "hours_ago": 1.0}
    assert polaris.check(SITE, cam_class=Camera, frames=4)["focus"]["hours_ago"] == 1.0
    polaris.SCENE_FOCUS.write_text(json.dumps({"sharpness": 9.0, "saved": time.time() - 30 * 3600}), encoding="utf-8")
    assert polaris.focus_checked() is None


def test_a_landmark_check_narrows_the_search(scope, monkeypatch):
    monkeypatch.setattr(config, "load", lambda: {"site": SITE})
    args = argparse.Namespace(command="find", radius=None, anyway=False, record=False, watch=0, quiet=True,
                              dry_run=True, json=False)
    assert polaris.run(args)[0]["radius_deg"] == polaris.RADIUS
    landmark.FOLDER.mkdir(parents=True, exist_ok=True)
    last = {"name": "chimney", "matched": True, "right_deg": 0.08, "down_deg": 0.0, "checked": time.time() - 600}
    (landmark.FOLDER / "last check.json").write_text(json.dumps(last), encoding="utf-8")
    assert polaris.landmark_says()["name"] == "chimney"
    narrow = polaris.run(args)[0]
    assert narrow["radius_deg"] == polaris.NARROW and narrow["looks"] < 60
    assert polaris.run(argparse.Namespace(**dict(vars(args), radius=2.0)))[0]["radius_deg"] == 2.0     # asked for outright
    # Not if the landmark was off, could not be matched, or was checked this morning.
    for change in ({"right_deg": 0.9}, {"matched": False, "right_deg": None}, {"checked": time.time() - 9 * 3600}):
        (landmark.FOLDER / "last check.json").write_text(json.dumps(dict(last, **change)), encoding="utf-8")
        assert polaris.landmark_says() is None
    assert landmark.listed() == []          # the note of the last check is not itself a landmark


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
        args = argparse.Namespace(command=command, radius=3.0, anyway=True, record=False, watch=0, quiet=True,
                                  dry_run=False, json=False)
        with pytest.raises(interface.Refusal) as refusal:
            polaris.run(args)
        assert refusal.value.code_name == "MOTION_LOCKED"
    for check in (lambda: polaris.plan(SITE), lambda: polaris.align(scope, SITE, cam_class=Camera, aim=jump)):
        with pytest.raises(interface.Refusal) as refusal:
            check()
        assert refusal.value.code_name == "MOTION_LOCKED"
    assert scope.axes() == pytest.approx([30, 40])
