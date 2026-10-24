"""./ty moon against a made-up mount and camera: the disc is found in the
picture, the first moves measure the picture's directions, the Moon is
centred, exposed and cut to a region, the video is taken in bursts with the
Moon put back between them, and the video is stacked."""
import json

import numpy as np
import pytest

import config
import lucky
import moon
import shoot
import snap

SHAPE = (300, 400)
PER_ARCMIN = np.array([[0.5, -12.0], [12.0, 0.4]])    # picture pixels (down, right) per arcminute (east, north)
START = np.array([90.0, 120.0])                         # where the disc lands with no aim-off
RADIUS = 50


class Sky:
    """The made-up Moon: where it is in the picture follows the aim, plus
    the Moon's own drift as frames are taken."""

    def __init__(self, drift=(0.0, 0.0)):
        self.aim = np.zeros(2)
        self.drift = np.array(drift)
        self.frames = 0
        self.gotos = []

    def centre(self):
        return START + PER_ARCMIN @ self.aim + self.drift * self.frames

    def picture(self, exposure, gain, region=None):
        self.frames += 1
        yy, xx = np.indices(SHAPE)
        cy, cx = self.centre()
        disc = np.hypot(yy - cy, xx - cx) < RADIUS
        level = min(4095, 742 * exposure / 0.005 * gain / 100)
        image = np.where(disc, level, 40).astype(np.uint16)
        if region:
            x, y, w, h = region
            image = image[y:y + h, x:x + w]
        return image


class Scope:
    def __init__(self, sky):
        self.sky = sky

    def goto_target(self, name, site, solve=False, aim_off=(0.0, 0.0)):
        self.sky.aim = np.array(aim_off, float)
        self.sky.gotos.append((name, tuple(aim_off)))

    def west(self):
        return True


class Cam:
    name = "fake"

    def __init__(self, sky):
        self.sky, self.gain, self.closed = sky, 100, False

    def frame(self, exposure):
        return self.sky.picture(exposure, self.gain), {}

    def video(self, exposure, count, roi=None):
        for n in range(count):
            yield self.sky.picture(exposure, self.gain, roi), n * 0.01, n + 1

    def close(self):
        self.closed = True


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setattr(moon, "CALIBRATION", tmp_path / "moon_calibration.json")
    monkeypatch.setattr(lucky, "OUT", tmp_path)
    monkeypatch.setattr(shoot, "RUN_LOCK", tmp_path / "imaging.lock")
    monkeypatch.setattr(snap, "publish", lambda *a, **k: None)
    stacked = []
    monkeypatch.setattr(lucky, "stack_file", lambda path, keeps, in_colour, pixels: stacked.append(path) or {"shown": "20"})
    return stacked


def test_the_moon_is_found_centred_exposed_and_taken_in_bursts(rig):
    sky = Sky()
    cam = Cam(sky)
    out = moon.run(moon.parse(["--frames", "60", "--bursts", "3"]), Scope(sky), cam, config.example()["site"],
                   say=lambda line: None)
    # Centred from the picture alone, and held in the middle of the region read.
    x, y, w, h = out["roi"]
    assert np.hypot(*(sky.centre() - (np.array([y + h / 2, x + w / 2]) - 0.5))) < 0.04 * RADIUS + 2
    # The two test moves measured the directions, and they were kept for next time.
    kept = json.loads(moon.CALIBRATION.read_text())["west"]["matrix"]
    assert np.allclose(kept, PER_ARCMIN, atol=0.5)
    # Exposed up the scale without clipping, and only the region round the disc read.
    assert 0.72 * 4095 * 0.85 < 742 * out["exposure"] / 0.005 < 4095
    assert w == h and 2 * RADIUS < w < SHAPE[0]
    assert out["frames"] == 60 and [b["frames"] for b in out["bursts"]] == [20, 20, 20]
    data, _ = lucky.read_ser(out["video"])
    assert data.shape == (60, h, w)
    assert rig == [moon.Path(out["video"])] and cam.closed


def test_the_moon_is_put_back_between_bursts_as_it_drifts(rig):
    sky = Sky(drift=(0.0, -1.5))           # the Moon slides left a pixel and a half a frame
    out = moon.run(moon.parse(["--frames", "60", "--bursts", "3", "--no-stack"]), Scope(sky), Cam(sky),
                   config.example()["site"], say=lambda line: None)
    holds = [entry for entry in out["centring"] if "hold" in entry]
    assert len(holds) == 2 and all(entry["right"] < -15 for entry in holds)
    assert rig == []


def test_with_the_directions_known_the_test_moves_are_skipped(rig):
    moon.save_calibration("west", PER_ARCMIN)
    sky = Sky()
    moon.run(moon.parse(["--frames", "20", "--bursts", "1", "--no-stack"]), Scope(sky), Cam(sky),
             config.example()["site"], say=lambda line: None)
    assert all(aim != (5.0, 0.0) for _, aim in sky.gotos[:3])


def test_no_moon_in_the_frame_stops_with_what_to_do(rig):
    sky = Sky()
    sky.picture = lambda *a, **k: np.full(SHAPE, 40, np.uint16)
    with pytest.raises(SystemExit, match="No Moon in the frame"):
        moon.run(moon.parse([]), Scope(sky), Cam(sky), config.example()["site"], say=lambda line: None)


def test_frames_are_cut_to_what_fits_on_the_disk():
    assert moon.frames_that_fit(1000, 10_000_000, moon.HEADROOM + 2_000_000_000) == 200
    assert moon.frames_that_fit(1000, 10_000_000, 1) == 0


def test_the_dry_run_says_what_it_would_do(monkeypatch, capsys):
    import mount
    monkeypatch.setattr(mount, "plan_goto", lambda name, site: {"would_move": True, "safe": True, "warnings": []})
    monkeypatch.setattr(moon, "free_disk", lambda path=None: 200e9)
    out = moon.plan(moon.parse(["--frames", "1000"]), config.example()["site"])
    assert out["frames"] == 1000 and out["region_px"] > 2000 and 0 <= out["moon"]["illumination"] <= 100
