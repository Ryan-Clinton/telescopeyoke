"""The guide camera, with a stand-in for its library: no camera is needed."""
import numpy as np
import pytest
from astropy.io import fits

import guidecam
import interface


class Fake:
    """The legacy library as guidecam.Driver gives it: a frame is ready
    every `every` seconds of the test's own clock."""

    def __init__(self, cameras=(("GPCAMMT9M034M", b"id1"),), every=0.1, level=17):
        self.found, self.every, self.level = list(cameras), every, level
        self.now, self.exposures, self.closed = 0.0, [], False

    def cameras(self):
        return self.found

    def open(self, ident):
        return "handle", (8, 6)

    def exposure(self, handle, seconds):
        self.exposures.append(seconds)

    def gain(self, handle, percent):
        self.gained = percent

    def pull(self, handle):
        return 8, 6, bytes([self.level]) * 48

    def close(self, handle):
        self.closed = True


def camera(fake):
    clock = {"t": 0.0}

    def tick(seconds):
        clock["t"] += seconds
    return guidecam.GuideCamera(fake, clock=lambda: clock["t"], sleep=tick), clock, tick


def test_a_frame_is_taken_wholly_at_its_exposure_and_shaped_as_the_sensor():
    fake = Fake()
    cam, clock, tick = camera(fake)
    # Frames come at once from this stand-in; only one arriving after the
    # exposure has run counts (the first after a change is the old one's).
    fake.pull = lambda h: (tick(0.05), (8, 6, bytes([151]) * 48))[1]
    frame = cam.frame(0.1, gain=200)
    assert frame.shape == (6, 8) and frame.dtype == np.uint8 and frame.mean() == 151
    assert clock["t"] >= 0.1 and fake.exposures == [0.1] and fake.gained == 200
    cam.frame(0.1)
    assert fake.exposures == [0.1]                  # the same exposure is not set again


def test_no_camera_and_no_frame_are_said_plainly():
    with pytest.raises(interface.Refusal, match="No guide camera"):
        camera(Fake(cameras=[("ALTAIR183C", b"x")]))
    fake = Fake()
    cam, _, _ = camera(fake)
    fake.pull = lambda h: None
    with pytest.raises(interface.Refusal, match="sent no frame within"):
        cam.frame(0.5)


def test_the_camera_is_closed_after_use_and_a_frame_is_kept_with_its_exposure(tmp_path):
    fake = Fake()
    with guidecam.GuideCamera(fake, clock=iter(np.arange(0, 100, 0.2)).__next__, sleep=lambda s: None) as cam:
        frame = cam.frame(0.1)
    assert fake.closed
    path = guidecam.keep(frame, 0.1, None, folder=tmp_path)
    header = fits.getheader(path)
    assert path.parent == tmp_path and header["EXPTIME"] == 0.1 and header["INSTRUME"] == "GPCAMMT9M034M"


def test_install_unpacks_the_library_from_its_package(tmp_path, monkeypatch):
    monkeypatch.setattr(guidecam, "VENDOR", tmp_path / "vendor")
    monkeypatch.setattr(guidecam, "LIBRARY", tmp_path / "vendor" / "libaltaircamlegacy.so.1.24.11330")

    def dpkg(command, check):
        out = __import__("pathlib").Path(command[-1]) / "usr" / "lib"
        out.mkdir(parents=True)
        (out / "libaltaircamlegacy.so.1.24.11330").write_bytes(b"ELF")
    said = []
    path = guidecam.install(say=said.append, fetch=lambda url: b"deb", run=dpkg)
    assert path.read_bytes() == b"ELF" and said == [f"installed {path}"]
    assert guidecam.install(say=said.append) == path and said[-1].startswith("already installed")
