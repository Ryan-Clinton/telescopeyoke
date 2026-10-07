"""Setting the azimuth from a remembered landmark, on the simulated mount with
a made-up view: nothing here can move a real telescope."""
import argparse
import json

import numpy as np
import pytest
from scipy import ndimage

import config
import interface
import landmark
import mount
from simulator import SimulatedHandset

SITE = config.example()["site"]
SHAPE = (1100, 1300)       # the half-size picture


class Scene:
    """A view of rooftops: a big made-up picture the camera looks at part of.
    `turned` is how far the mount has been swung since, in pixels of view."""
    world = ndimage.gaussian_filter(np.random.default_rng(5).uniform(200, 3000, (1500, 1900)), 6) \
        + 400 * (np.random.default_rng(6).uniform(size=(1500, 1900)) > 0.995)
    turned = (0, 0)        # (right, down)
    dark = False

    @classmethod
    def view(cls):
        x, y = 300 + cls.turned[0], 200 + cls.turned[1]
        view = cls.world[y:y + SHAPE[0], x:x + SHAPE[1]]
        if cls.dark:
            return np.random.default_rng(9).uniform(200, 260, SHAPE)
        return view


class Camera:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def frame(self, seconds):
        lum = Scene.view() * min(seconds / 0.002, 1.0)
        return np.repeat(np.repeat(lum / 4, 2, axis=0), 2, axis=1).astype(np.uint16), {}


@pytest.fixture
def scope(tmp_path, monkeypatch):
    for name in ("CLOCK_FILE", "POINTING_FILE", "DRIFT_FILE"):
        monkeypatch.setattr(mount, name, tmp_path / f"{name}.json")
    monkeypatch.setattr(mount, "LOCK_FILE", tmp_path / "MOTION_LOCKED")
    monkeypatch.setattr(landmark, "FOLDER", tmp_path / "landmarks")
    monkeypatch.setattr(landmark, "VIEW", tmp_path / "web" / "landmark.jpg")
    Scene.turned, Scene.dark = (0, 0), False
    return mount.Mount(handset=SimulatedHandset(slew_seconds=0))


def kept(name, ra_axis=20.0, dec_axis=70.0):
    """A landmark as if remembered earlier, without turning the pretend mount
    there first (it turns at a real mount's pace)."""
    azimuth, altitude = landmark.altaz(ra_axis, dec_axis, SITE["latitude"])
    landmark.FOLDER.mkdir(parents=True, exist_ok=True)
    np.save(landmark.FOLDER / f"{name}.npy", Scene.view().astype(np.float32))
    note = {"name": name, "ra_axis_deg": ra_axis, "dec_axis_deg": dec_axis, "bearing_deg": azimuth,
            "height_deg": altitude, "exposure_s": 0.002, "remembered": 0, "polar_when_remembered": None}
    landmark.place(name).write_text(json.dumps(note), encoding="utf-8")
    return note


def test_how_far_a_view_has_moved_is_measured_and_doubt_is_admitted():
    Scene.turned, Scene.dark = (0, 0), False
    before = Scene.view().copy()
    Scene.turned = (37, -12)          # the camera has swung right and up: the rooftops move left and down
    dx, dy, sure = landmark.shift_between(before, Scene.view())
    assert (dx, dy) == (-37.0, 12.0) and sure > landmark.SURE
    Scene.dark = True                 # nothing in common
    assert landmark.shift_between(before, Scene.view())[2] < landmark.SURE


def test_a_landmark_is_remembered_and_found_again(scope, tmp_path):
    # Turned a little way from home by hand, as it would be to a rooftop.
    scope.seek(mount.DEC, 75.0)
    scope.seek(mount.RA, 15.0)
    note = landmark.remember("Chimney", scope, SITE, cam_class=Camera)
    assert note["name"] == "chimney" and note["dec_axis_deg"] == pytest.approx(75.0, abs=0.05)
    assert (tmp_path / "landmarks" / "chimney.jpg").exists()
    assert note["polar_when_remembered"] is None       # the stars have not been asked yet

    # Packed away and set up again: the mount is at home, and faces a little to one side.
    scope.home()
    assert scope.at_home()
    Scene.turned = (-55, 0)           # swung left, so the chimney is to the right of where it was
    found = landmark.check("chimney", scope, SITE, cam_class=Camera)
    assert scope.axes() == pytest.approx([note["ra_axis_deg"], note["dec_axis_deg"]], abs=0.05)
    assert not scope.s.tracking       # held still on it
    assert found["matched"] and found["right_px"] == 55.0 and found["down_px"] == 0.0
    assert found["right_deg"] == pytest.approx(55 * landmark.scale(), abs=0.001)
    assert (tmp_path / "web" / "landmark.jpg").exists()

    # The bolts are turned while it watches: the last look has it back on the cross.
    looks = iter([(-20, 0), (0, 0)])
    real = landmark.look

    def turning(*args):
        Scene.turned = next(looks)
        return real(*args)
    import unittest.mock
    with unittest.mock.patch.object(landmark, "look", turning):
        found = landmark.check("chimney", scope, SITE, watch=2, cam_class=Camera, pause=0)
    assert found["looks"] == 2 and found["right_px"] == 0.0 and found["off_deg"] == 0.0


def test_a_view_it_cannot_match_is_left_to_the_eye(scope):
    note = kept("mast", ra_axis=5.0, dec_axis=84.0)
    Scene.dark = True                 # by night, say, with the mast unlit
    seen = landmark.look("mast", scope, Camera(), note, np.load(landmark.FOLDER / "mast.npy"))
    assert seen["matched"] is False and seen["off_deg"] is None


def test_it_refuses_before_moving(scope, monkeypatch):
    kept("mast")
    for bad in ("", "../etc", "a" * 60):
        with pytest.raises(interface.Refusal):
            landmark.name_ok(bad)
    with pytest.raises(interface.Refusal) as refusal:
        landmark.check("steeple", scope, SITE, cam_class=Camera)
    assert "No landmark called steeple" in refusal.value.message and "mast" in refusal.value.message
    assert scope.at_home()
    # Locked: the command refuses before the mount is opened.
    mount.LOCK_FILE.write_text("testing", encoding="utf-8")
    monkeypatch.setattr(mount, "Mount", lambda *a, **k: pytest.fail("the mount was opened"))
    args = argparse.Namespace(command="check", name="mast", watch=0, dry_run=False, json=False)
    with pytest.raises(interface.Refusal) as refusal:
        landmark.run(args)
    assert refusal.value.code_name == "MOTION_LOCKED"
    with pytest.raises(interface.Refusal) as refusal:
        landmark.plan("mast", SITE)
    assert refusal.value.code_name == "MOTION_LOCKED" and scope.at_home()


def test_a_landmark_beyond_the_meridian_limit_is_refused(scope):
    # Low and due east from home is six hours from the meridian: outside the limit.
    kept("gable", ra_axis=0.0, dec_axis=12.0)
    with pytest.raises(interface.Refusal) as refusal:
        landmark.check("gable", scope, SITE, cam_class=Camera)
    # In the morning the Sun is low in the east too, and is refused first.
    assert refusal.value.code_name in ("TARGET_BEYOND_HOUR_ANGLE_LIMIT", "TARGET_NEAR_SUN") and scope.at_home()
