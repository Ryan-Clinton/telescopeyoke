"""The camera's two routes, INDI and Altair's own library, held to one
contract: nothing above camera.Camera can tell which one it has. Neither
needs a camera: the INDI route talks to a made-up INDI client and the SDK
route to a made-up copy of Altair's wrapper."""
import ctypes
import io
import threading
import time
import types
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from astropy.io import fits

import altair
import camera
from indi import IndiError
from interface import Refusal

WIDTH, HEIGHT = 64, 48
WHITE = camera.WHITE


class World:
    """What the made-up camera does. The tests turn its knobs."""

    def __init__(self):
        self.cameras = [("Altair ALTAIRH183C", "SN-A")]   # (name, serial) of each one plugged in
        self.delay = 0.0          # seconds from trigger to the frame arriving
        self.delays = []          # ...or one figure per exposure, used up in turn
        self.silent = False       # never deliver a frame
        self.shifted = False      # hand the 12 bits over at the top of the 16
        self.obeys_cancel = True  # a cancelled exposure delivers nothing
        self.unplug = False       # report a disconnect instead of a frame
        self.level = 1000         # value the next frame is filled with
        self.stamps = True        # frames carry the camera's clock; False: always 0
        self.clock_rate = 1.0     # how fast that clock runs against the real one
        self.triggers = 0


def frame_of(level):
    data = np.full((HEIGHT, WIDTH), level, dtype=np.uint16)
    data[::2, ::2] += 1    # a real frame is never all one value
    return data


# --- a made-up copy of Altair's Python wrapper -------------------------------------

def fake_sdk(world):
    lib = types.ModuleType("altaircam")
    lib.ALTAIRCAM_EVENT_IMAGE, lib.ALTAIRCAM_EVENT_TRIGGERFAIL = 0x0004, 0x0007
    lib.ALTAIRCAM_EVENT_ERROR, lib.ALTAIRCAM_EVENT_DISCONNECTED = 0x0080, 0x0081
    lib.ALTAIRCAM_OPTION_RAW, lib.ALTAIRCAM_OPTION_BITDEPTH = 0x04, 0x06
    lib.ALTAIRCAM_OPTION_TRIGGER, lib.ALTAIRCAM_OPTION_BINNING = 0x0b, 0x17
    lib.ALTAIRCAM_OPTION_FLUSH = 0x3d

    class AltaircamFrameInfoV3:
        seq = timestamp = 0

    class HRESULTException(Exception):
        def __init__(self, hr):
            super().__init__(hex(hr))
            self.hr = hr

    class Handle:
        def __init__(self, serial):
            self.serial, self.held, self.cancelled, self.closed = serial, [], set(), 0
            self.options, self.speed = {}, 1

        def put_Option(self, option, value):
            self.options[option] = value
            if option == lib.ALTAIRCAM_OPTION_FLUSH:
                self.held.clear()

        def put_AutoExpoEnable(self, on): pass
        def put_eSize(self, index): pass
        def put_ExpoTime(self, microseconds): self.exposure = microseconds
        def put_ExpoAGain(self, gain): self.gain = gain
        def put_Speed(self, level): self.speed = level
        def get_Speed(self): return self.speed
        def MaxSpeed(self): return 2
        def get_Size(self): return WIDTH, HEIGHT
        def get_RawFormat(self): return int.from_bytes(b"RGGB", "little"), 12
        def SerialNumber(self): return self.serial
        def FwVersion(self): return "1.0"

        def StartPullModeWithCallback(self, callback, context):
            self.callback, self.context = callback, context

        def Trigger(self, number):
            if number == 0:
                self.cancelled.add(world.triggers)
                return
            world.triggers += 1
            mine, level = world.triggers, world.level
            taken = time.monotonic() + self.exposure / 1e6    # when the shutter closes
            delay = world.delays.pop(0) if world.delays else world.delay
            delay = max(delay, self.exposure / 1e6)   # the shutter has to close first
            if world.silent:
                return

            def deliver():
                time.sleep(delay)
                if world.unplug:
                    self.callback(lib.ALTAIRCAM_EVENT_DISCONNECTED, self.context)
                elif self.closed or (mine in self.cancelled and world.obeys_cancel):
                    return
                else:
                    # Stamped by the camera's own clock, which starts somewhere arbitrary.
                    stamp = round((1234.5 + taken * world.clock_rate) * 1e6) if world.stamps else 0
                    self.held.append((frame_of(level) << (4 if world.shifted else 0), mine, stamp))
                    self.callback(lib.ALTAIRCAM_EVENT_IMAGE, self.context)
            threading.Thread(target=deliver, daemon=True).start()

        def PullImageV3(self, buffer, still, bits, pitch, info):
            if not self.held:
                raise HRESULTException(0x80004005)
            # As the real wrapper: the buffer is declared a C string pointer,
            # and anything else is refused before the library is reached.
            if not isinstance(buffer, (bytes, ctypes.c_char_p)):
                raise ctypes.ArgumentError("argument 2: TypeError: wrong type")
            data, seq, stamp = self.held.pop(0)
            ctypes.memmove(buffer, data.tobytes(), data.nbytes)
            if info is not None:
                info.seq, info.timestamp = seq, stamp

        def Stop(self): pass
        def Close(self): self.closed += 1

    class Altaircam:
        opened = []

        @staticmethod
        def EnumV2():
            return [types.SimpleNamespace(displayname=name, id=serial, model=types.SimpleNamespace(flag=0))
                    for name, serial in world.cameras]

        @staticmethod
        def Open(camera_id):
            Altaircam.opened.append(Handle(camera_id))
            return Altaircam.opened[-1]

        @staticmethod
        def Version():
            return "fake"

    lib.HRESULTException, lib.Altaircam = HRESULTException, Altaircam
    lib.AltaircamFrameInfoV3 = AltaircamFrameInfoV3
    return lib


# --- a made-up INDI client -----------------------------------------------------------

def fake_indi(world):
    class Client:
        def __init__(self, port=None):
            self.props = {}

        def devices(self):
            return [name for name, _ in world.cameras]

        def get(self, device, name):
            return {"CCD_EXPOSURE_VALUE": "0"} if name == "CCD_EXPOSURE" else None

        def set(self, device, name, **values):
            if name == "CCD_CONTROLS":
                self.gain = values["Gain"]

        def connect(self, device): pass
        def pump(self, seconds): pass
        def close(self): pass

        def expose(self, device, seconds, timeout, attempts=1):
            world.triggers += 1
            if world.silent:
                raise IndiError("no frame")
            started = datetime.now(timezone.utc)
            time.sleep(world.delay)
            header = fits.Header({"EXPTIME": seconds, "GAIN": float(self.gain), "BAYERPAT": "RGGB",
                                  "DATE-OBS": started.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]})
            out = io.BytesIO()
            fits.PrimaryHDU(frame_of(world.level), header).writeto(out)
            return ".fits", out.getvalue()
    return Client


# --- both routes ------------------------------------------------------------------------

@pytest.fixture
def world():
    return World()


@pytest.fixture(params=["indi", "altair"])
def route(request, world, monkeypatch):
    """camera.Camera wired to one made-up route or the other."""
    monkeypatch.setattr(camera, "BACKEND", request.param)
    monkeypatch.setattr(camera, "MANAGE_SERVER", False)
    monkeypatch.setattr(camera, "Indi", fake_indi(world))
    monkeypatch.setattr(altair, "wait_for", lambda seconds: 0.3)
    use_sdk(world, monkeypatch)
    return request.param


def use_sdk(world, monkeypatch, **settings):
    lib = fake_sdk(world)
    monkeypatch.setattr(altair, "sdk", lambda: lib)
    monkeypatch.setattr(altair, "SETTINGS", {"camera": {"bit_depth": 12, **settings}})
    return lib


@pytest.fixture
def sdk(world, monkeypatch):
    monkeypatch.setattr(altair, "wait_for", lambda seconds: 0.3)
    return use_sdk(world, monkeypatch)


def test_a_frame_is_the_whole_sensor_in_raw_12_bit(route, world):
    world.level = WHITE - 1
    with camera.Camera(gain=300) as cam:
        data, header = cam.frame(0.01)
    assert data.dtype == np.uint16 and data.shape == (HEIGHT, WIDTH)
    assert 0 <= data.min() and data.max() == WHITE


def test_the_header_says_what_was_asked_for(route, world):
    with camera.Camera(gain=1500) as cam:
        data, header = cam.frame(0.25)
    assert header["EXPTIME"] == pytest.approx(0.25, abs=0.001)
    assert header["GAIN"] == 1500
    assert header["BAYERPAT"] == "RGGB"
    assert "DATE-OBS" in header


def test_date_obs_is_when_the_exposure_started_not_when_it_arrived(route, world):
    world.delay = 0.2
    before = datetime.now(timezone.utc)
    with camera.Camera() as cam:
        data, header = cam.frame(0.01)
    taken = datetime.strptime(header["DATE-OBS"], "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=timezone.utc)
    assert before - timedelta(seconds=0.05) <= taken <= before + timedelta(seconds=0.15)


def test_no_camera_is_refused_with_its_code(route, world):
    world.cameras = []
    with pytest.raises(Refusal) as refusal:
        camera.Camera()
    assert refusal.value.code_name == "CAMERA_NOT_CONNECTED"


def test_a_frame_that_never_comes_raises_the_same_error_on_both_routes(route, world):
    with camera.Camera() as cam:
        world.silent = True
        with pytest.raises(IndiError):
            cam.frame(0.01)


def test_closing_twice_does_no_harm(route, world):
    cam = camera.Camera()
    cam.frame(0.01)
    cam.close()
    cam.close()


# --- the SDK route's own hazards -----------------------------------------------------------

def test_values_handed_over_at_the_top_of_16_bits_are_brought_down(sdk, world):
    world.shifted, world.level = True, 4000
    with altair.AltairCamera() as cam:
        data, _ = cam.frame(0.01)
        again, _ = cam.frame(0.01)
    assert data.max() == 4001 and again.max() == 4001


def test_values_already_at_the_bottom_are_left_alone(sdk, world):
    world.level = 4000
    with altair.AltairCamera() as cam:
        data, _ = cam.frame(0.01)
    assert data.max() == 4001


def test_a_late_frame_never_answers_the_next_request(sdk, world):
    """The first exposure times out and its frame turns up during the second,
    from a camera that ignores the cancel. The second must still get its own."""
    world.obeys_cancel = False
    with altair.AltairCamera() as cam:
        # The first try and its retry both time out; their frames arrive 0.2
        # and 0.5 s into the 1 s exposure that follows.
        world.delays, world.level = [0.8, 0.8, 0.8], 111
        with pytest.raises(IndiError):
            cam.frame(0.01)
        altair.wait_for = lambda seconds: 3.0
        world.delays, world.level = [1.0], 222
        data, _ = cam.frame(1.0)
    assert data.max() == 223


def late_frame_lands_near_the_end_of_the_next_exposure(cam, world):
    """An exposure fails, and its frame, from a camera that ignores the
    cancel, turns up 1.9 s into the 2 s exposure that follows: too late for
    "it came back before the shutter could have closed" to catch."""
    world.obeys_cancel = False
    world.delays, world.level = [99, 99, 2.2], 111     # the third try's frame is the late one
    with pytest.raises(IndiError):
        cam.frame(0.01)
    altair.wait_for = lambda seconds: 6.0
    world.delays, world.level = [2.1], 222
    return cam.frame(2.0)[0]


def test_without_the_cameras_clock_that_late_frame_would_get_through(sdk, world):
    """What the clock is for: this is the failure the test below guards."""
    world.stamps = False
    with altair.AltairCamera() as cam:
        cam.frame(0.01)
        time.sleep(1.6)
        cam.frame(0.01)
        data = late_frame_lands_near_the_end_of_the_next_exposure(cam, world)
    assert data.max() == 112


def test_a_late_frame_arriving_near_the_end_of_the_next_exposure_is_refused(sdk, world):
    with altair.AltairCamera() as cam:
        cam.frame(0.01)
        time.sleep(1.6)       # two frames far enough apart to check the camera's clock
        cam.frame(0.01)
        data = late_frame_lands_near_the_end_of_the_next_exposure(cam, world)
        assert cam.clock is True
    assert data.max() == 223


def test_the_cameras_clock_is_only_trusted_once_it_has_kept_time(sdk, world):
    world.clock_rate = 0.001      # stamps that barely advance: not a clock we understand
    with altair.AltairCamera() as cam:
        for _ in range(3):
            time.sleep(2.2)
            data, _ = cam.frame(0.01)
            assert data.shape == (HEIGHT, WIDTH)      # good frames are never turned away
        assert cam.clock is False


def test_frames_with_no_stamp_are_still_accepted(sdk, world):
    world.stamps = False
    with altair.AltairCamera() as cam:
        for _ in range(3):
            assert cam.frame(0.01)[0].shape == (HEIGHT, WIDTH)
        assert cam.clock is None


def test_a_dark_first_frame_does_not_settle_how_values_are_aligned(sdk, world):
    """Low-aligned values that happen to be multiples of 16: nothing certain
    can be said, so the question stays open and a later frame settles it."""
    with altair.AltairCamera() as cam:
        cam.handle.Trigger = None     # frames are handed over directly below
        dark = np.full((HEIGHT, WIDTH), 32, dtype=np.uint16)
        cam._normalise(dark.copy())
        assert cam._shifted is None
        ordinary = np.full((HEIGHT, WIDTH), 1001, dtype=np.uint16)
        assert cam._normalise(ordinary.copy()).max() == 1001 and cam._shifted is False
        assert cam._normalise(dark.copy()).max() == 32


def test_a_value_above_white_settles_that_values_are_shifted_up(sdk, world):
    with altair.AltairCamera() as cam:
        bright = np.full((HEIGHT, WIDTH), 4000 << 4, dtype=np.uint16)
        assert cam._normalise(bright).max() == 4000 and cam._shifted is True


def test_a_frame_nobody_asked_for_is_not_kept(sdk, world):
    with altair.AltairCamera() as cam:
        handle = sdk.Altaircam.opened[-1]
        handle.held.append((frame_of(111), 0, 0))
        handle.callback(sdk.ALTAIRCAM_EVENT_IMAGE, handle.context)   # out of the blue
        world.level = 222
        data, _ = cam.frame(0.01)
    assert data.max() == 223


def test_the_camera_still_works_after_a_time_out(sdk, world):
    with altair.AltairCamera() as cam:
        world.silent = True
        with pytest.raises(IndiError):
            cam.frame(0.01)
        world.silent = False
        data, _ = cam.frame(0.01)
    assert data.shape == (HEIGHT, WIDTH)


def test_an_unplugged_camera_fails_at_once_not_after_the_wait(sdk, world, monkeypatch):
    monkeypatch.setattr(altair, "wait_for", lambda seconds: 30.0)
    with altair.AltairCamera() as cam:
        world.unplug = True
        began = time.monotonic()
        with pytest.raises(IndiError, match="unplugged"):
            cam.frame(0.01)
    assert time.monotonic() - began < 5 and world.triggers == 1


def test_two_cameras_are_refused_and_both_are_named(sdk, world):
    world.cameras = [("Altair ALTAIRH183C", "SN-A"), ("Altair GPCAM", "SN-B")]
    with pytest.raises(Refusal) as refusal:
        altair.AltairCamera()
    assert refusal.value.code_name == "CAMERA_NOT_CONNECTED"
    assert "SN-A" in refusal.value.message and "SN-B" in refusal.value.message


def test_two_cameras_and_a_serial_number_picks_that_one(world, monkeypatch):
    world.cameras = [("Altair ALTAIRH183C", "SN-A"), ("Altair GPCAM", "SN-B")]
    use_sdk(world, monkeypatch, serial="SN-B")
    with altair.AltairCamera() as cam:
        assert cam.name == "Altair GPCAM"


def test_the_callback_is_held_for_as_long_as_the_camera_is_open(sdk, world):
    with altair.AltairCamera() as cam:
        handle = sdk.Altaircam.opened[-1]
        assert handle.callback is cam._callback and handle.context is cam


def test_raw_mode_and_single_exposures_are_set_before_starting(sdk, world):
    with altair.AltairCamera():
        options = sdk.Altaircam.opened[-1].options
    assert options[sdk.ALTAIRCAM_OPTION_RAW] == 1 and options[sdk.ALTAIRCAM_OPTION_TRIGGER] == 1
    assert options[sdk.ALTAIRCAM_OPTION_BITDEPTH] == 1


def test_the_readout_speed_is_left_alone_unless_config_names_one(world, monkeypatch):
    lib = use_sdk(world, monkeypatch)
    with altair.AltairCamera():
        assert lib.Altaircam.opened[-1].speed == 1
    lib = use_sdk(world, monkeypatch, readout_speed=0)
    with altair.AltairCamera():
        assert lib.Altaircam.opened[-1].speed == 0


def test_the_doctor_names_the_camera_that_config_picks(world, monkeypatch, tmp_path):
    world.cameras = [("Altair ALTAIRH183C", "SN-A"), ("Altair GPCAM", "SN-B")]
    (tmp_path / "altaircam.py").write_text("", encoding="utf-8")
    (tmp_path / "altaircam.dll").write_text("", encoding="utf-8")
    monkeypatch.setattr(altair, "VENDOR", tmp_path)
    use_sdk(world, monkeypatch, serial="SN-B")
    assert altair.checks()[-1] == ("ok", "camera: Altair GPCAM")
    use_sdk(world, monkeypatch)
    status, message = altair.checks()[-1]
    assert status == "fail" and "SN-A" in message and "SN-B" in message


def test_the_doctor_says_which_sdk_file_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(altair, "VENDOR", tmp_path)
    lines = altair.checks()
    assert lines[-1][0] == "fail" and "altaircam.py" in lines[-1][1]
