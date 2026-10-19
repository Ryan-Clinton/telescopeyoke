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
        self.native = False       # INDI only: left sending frames that are not FITS
        self.binning = 1          # what the camera has been set to bin by
        self.bins = True          # False: asking it to bin fails
        self.asked_to_bin = 0     # how many times 2x2 or more was asked for


def frame_of(level, binning=1):
    data = np.full((HEIGHT // binning, WIDTH // binning), level, dtype=np.uint16)
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
            if option == lib.ALTAIRCAM_OPTION_BINNING:
                world.asked_to_bin += value > 1
                if value > 1 and not world.bins:
                    raise HRESULTException(0x80004001)
                world.binning = value
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
        def get_FinalSize(self): return WIDTH // world.binning, HEIGHT // world.binning
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
                    self.held.append((frame_of(level, world.binning) << (4 if world.shifted else 0), mine, stamp))
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
            if name == "CCD_TRANSFER_FORMAT":
                return {"FORMAT_FITS": "Off" if world.native else "On", "FORMAT_NATIVE": "On" if world.native else "Off"}
            return {"CCD_EXPOSURE_VALUE": "0"} if name == "CCD_EXPOSURE" else None

        def set(self, device, name, **values):
            if name == "CCD_CONTROLS":
                self.gain = values["Gain"]
            if name == "CCD_TRANSFER_FORMAT":
                world.native = values.get("FORMAT_FITS") != "On"
            if name == "CCD_BINNING":
                world.asked_to_bin += values["HOR_BIN"] > 1
                if values["HOR_BIN"] > 1 and not world.bins:
                    # As on 6 October 2026: the connection to the server went.
                    raise IndiError("connection lost")
                world.binning = values["HOR_BIN"]

        def connect(self, device): pass
        def pump(self, seconds): pass
        def close(self): pass

        def expose(self, device, seconds, timeout, attempts=1):
            world.triggers += 1
            world.timeouts = getattr(world, "timeouts", []) + [(seconds, timeout, attempts)]
            if world.silent:
                raise IndiError("no frame")
            if world.native:
                return ".raw", b"not FITS"
            started = datetime.now(timezone.utc)
            time.sleep(world.delay)
            header = fits.Header({"EXPTIME": seconds, "GAIN": float(self.gain), "BAYERPAT": "RGGB",
                                  "XBINNING": world.binning,
                                  "DATE-OBS": started.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]})
            out = io.BytesIO()
            fits.PrimaryHDU(frame_of(world.level, world.binning), header).writeto(out)
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


def test_quick_frames_for_focusing_are_binned_and_imaging_frames_never_are(route, world):
    with camera.Camera() as cam:
        assert cam.frame(0.01)[0].shape == (HEIGHT, WIDTH)
        assert cam.use("focus_fast") == 2
        assert cam.frame(0.01)[0].shape == (HEIGHT // 2, WIDTH // 2) and cam.binning == 2
        assert cam.use("focus_fine") == 1
        assert cam.frame(0.01)[0].shape == (HEIGHT, WIDTH)
        cam.use("focus_fast")
        assert cam.use("imaging") == 1 and cam.frame(0.01)[0].shape == (HEIGHT, WIDTH)
    assert camera.PROFILES["imaging"] == 1


def test_a_camera_that_will_not_bin_carries_on_with_the_full_sensor(route, world):
    world.bins = False
    with camera.Camera() as cam:
        assert cam.use("focus_fast") == 1                 # it failed, and the camera was opened afresh
        assert cam.frame(0.01)[0].shape == (HEIGHT, WIDTH)
        assert cam.use("focus_fast") == 1
        assert world.asked_to_bin == 1                    # and it is not asked a second time


def test_a_camera_left_binned_is_opened_on_the_full_sensor(route, world):
    world.binning = 2             # as a focusing run that was killed would leave it
    with camera.Camera() as cam:
        assert cam.frame(0.01)[0].shape == (HEIGHT, WIDTH)


def test_a_camera_left_on_native_transfer_is_put_back_to_fits(world, monkeypatch):
    # camera_test.py's trial of native transfer timed out and left it so;
    # every frame after that was unreadable until the driver was restarted.
    monkeypatch.setattr(camera, "BACKEND", "indi")
    monkeypatch.setattr(camera, "MANAGE_SERVER", False)
    monkeypatch.setattr(camera, "Indi", fake_indi(world))
    world.native = True
    with camera.Camera(gain=100) as cam:
        mosaic, _ = cam.frame(0.01)
    assert not world.native and mosaic.shape == (HEIGHT, WIDTH)


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


# --- stripes ------------------------------------------------------------------------------

def striped(strength, rng, shape=(400, 600)):
    rows = np.arange(shape[0])[:, None]
    lum = 1000 + rng.normal(0, 20, shape) + strength * np.sin(rows / 15.0)
    return np.repeat(np.repeat(lum, 2, axis=0), 2, axis=1) / 4    # a mosaic whose 2x2 cells sum to lum


def test_banding_is_near_one_without_stripes_and_large_with_them():
    import camera_test
    rng = np.random.default_rng(1)
    assert camera_test.banding(striped(0, rng)) < 2
    assert camera_test.banding(striped(8, rng)) > 5


def test_the_banding_trial_tries_each_setting_and_keeps_the_weakest(monkeypatch, tmp_path):
    import camera_test
    rng = np.random.default_rng(2)
    seen = []

    class Cam:
        fan = "on"
        def __init__(self, gain): pass
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def settings(self, fan, offset):
            Cam.fan = fan
            seen.append((fan, offset))
        def frame(self, seconds):
            return striped(8 if Cam.fan == "on" else 0, rng), {}
    saved = {}
    monkeypatch.setattr(camera_test, "Camera", Cam)
    monkeypatch.setattr(camera_test.config, "save", lambda changes: saved.update(changes))
    answer = camera_test.banding_trial(16, 1500, frames=1, keep=True, say=lambda s: None)
    assert seen == list(camera_test.BANDING_SETTINGS)
    assert answer["best"]["fan"] == "off" and saved[("camera", "fan")] == "off"


def test_a_sweep_point_gives_the_stripes_in_adu_and_against_the_grain():
    import camera_test
    rng = np.random.default_rng(3)
    calm = camera_test.sweep_point([striped(0, rng) for _ in range(3)])
    rough = camera_test.sweep_point([striped(8, rng) for _ in range(3)])
    assert calm["frames"] == 3 and rough["stripes_adu"] > 3 * calm["stripes_adu"]
    assert rough["stripes_per_grain"] == round(rough["stripes_adu"] / rough["noise"], 3)


def test_the_usb_link_is_read_from_the_kernels_record(tmp_path):
    import camera_test
    for name, product, speed in (("1-1", "Webcam", "480"), ("2-4", "ALTAIRH183C", "5000")):
        (tmp_path / name).mkdir()
        (tmp_path / name / "product").write_text(product + "\n")
        (tmp_path / name / "speed").write_text(speed + "\n")
    assert camera_test.usb_link(tmp_path) == {"port": "2-4", "mbps": 5000}
    assert camera_test.usb_link(tmp_path / "missing") is None


def test_the_cooldown_keeps_a_line_a_step_and_counts_frames_that_never_arrive(monkeypatch, tmp_path):
    import camera_test
    rng = np.random.default_rng(4)
    taken = []

    class Cam:
        def __init__(self, gain): pass
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def frame(self, seconds):
            taken.append(seconds)
            if len(taken) == 2:
                raise IndiError("timed out waiting for the image")
            return striped(4 * len(taken) // 3, rng), {}
    monkeypatch.setattr(camera_test, "Camera", Cam)
    monkeypatch.setattr(camera_test.config, "DATA", tmp_path)
    monkeypatch.setattr(camera_test, "outdoors", lambda: {"temp_c": 1.0, "dew_point_c": 0.5})
    monkeypatch.setattr(camera_test, "usb_link", lambda: {"port": "2-4", "mbps": 5000})
    monkeypatch.setattr(camera_test, "ELECTRONS_FILE", tmp_path / "none.json")
    slept = []
    answer = camera_test.cooldown(16, 1500, frames=3, every_min=5, steps=2, note="3 m lead",
                                  say=lambda s: None, sleep=slept.append)
    assert slept == [300] and taken == [16] * 6
    first, second = answer["steps"]
    assert first["failed"] == 1 and second["failed"] == 0 and first["note"] == "3 m lead"
    assert second["stripes_adu"] > first["stripes_adu"] and first["usb"]["port"] == "2-4"
    lines = (tmp_path / "cache").glob("cooldown-*.jsonl")
    assert len(next(lines).read_text().splitlines()) == 2


def test_photon_transfer_finds_the_electrons_per_adu_it_was_given():
    import camera_test
    rng = np.random.default_rng(5)
    k = 0.8                                                    # electrons per ADU
    def flat(electrons):
        return 300 + rng.poisson(electrons, (200, 300)) / k + rng.normal(0, 2, (200, 300))
    pairs = [(flat(e), flat(e)) for e in (500, 1000, 2000, 4000, 8000)]
    found, points = camera_test.photon_transfer(pairs)
    assert found == pytest.approx(k, rel=0.05) and len(points) == 5


def test_photon_transfer_refuses_frames_in_the_dark():
    import camera_test
    rng = np.random.default_rng(6)
    dark = [(300 + rng.normal(0, 3, (200, 300)), 300 + rng.normal(0, 3, (200, 300))) for _ in range(4)]
    with pytest.raises(Refusal, match="evenly lit"):
        camera_test.photon_transfer(dark)


def test_the_stripes_come_in_electrons_once_the_gain_is_measured(monkeypatch, tmp_path):
    import camera_test
    rng = np.random.default_rng(7)
    frames = [striped(8, rng) for _ in range(2)]
    monkeypatch.setattr(camera_test, "ELECTRONS_FILE", tmp_path / "e.json")
    assert camera_test.sweep_point(frames, 1500)["stripes_e"] is None
    (tmp_path / "e.json").write_text('{"1500": {"e_per_adu": 0.5}}')
    q = camera_test.sweep_point(frames, 1500)
    assert q["stripes_e"] == pytest.approx(q["stripes_adu"] * 0.5, abs=0.01)


def test_a_cooldown_record_says_what_else_was_on_usb_and_whether_on_the_charger(tmp_path):
    import camera_test
    (tmp_path / "AC").mkdir()
    (tmp_path / "AC" / "type").write_text("Mains\n")
    (tmp_path / "AC" / "online").write_text("1\n")
    assert camera_test.on_mains(tmp_path) is True
    assert camera_test.on_mains(tmp_path / "missing") is None
    for name, product in (("usb1", "xHCI Host Controller"), ("1-2", "FT232R USB UART"), ("2-4", "ALTAIRH183C")):
        (tmp_path / name).mkdir()
        (tmp_path / name / "product").write_text(product)
    assert camera_test.usb_devices(tmp_path) == ["ALTAIRH183C", "FT232R USB UART"]


def test_the_dew_margin_is_kept_with_the_air_temperature(monkeypatch):
    import camera_test
    now = __import__("time").time()
    weather = types.SimpleNamespace(weather=lambda lat, lon: {
        "time": [now - 3600, now], "temperature_2m": [5.0, 1.5], "dew_point_2m": [2.0, 0.7]})
    # The example settings, so the site's names are the real ones: on 19
    # October 2026 a made-up {"lat", "lon"} here hid that the real site says
    # latitude and longitude, and no cooldown record had the air or dew.
    monkeypatch.setattr(camera_test.config, "load", camera_test.config.example)
    assert camera_test.outdoors(weather) == {"temp_c": 1.5, "dew_point_c": 0.7, "dew_margin_c": 0.8}


def test_the_camera_sets_its_fan_and_black_level_each_time_it_opens(world, monkeypatch):
    sets = []
    Client = fake_indi(world)

    class Watching(Client):
        def get(self, device, name):
            if name in ("TC_FAN_CONTROL", "CCD_OFFSET"):
                return {"x": "1"}
            return super().get(device, name)

        def set(self, device, name, **values):
            sets.append((name, values))
            return super().set(device, name, **values)
    monkeypatch.setattr(camera, "Indi", Watching)
    monkeypatch.setattr(camera, "BACKEND", "indi")   # Windows defaults to Altair's library, which CI lacks
    monkeypatch.setitem(camera.SETTINGS["camera"], "fan", "off")
    monkeypatch.setitem(camera.SETTINGS["camera"], "offset", 50)
    with camera.Camera():
        pass
    assert ("TC_FAN_CONTROL", {"TC_FAN_OFF": "On"}) in sets and ("CCD_OFFSET", {"OFFSET": 50}) in sets


def test_stripes_new_in_each_frame_are_told_from_stripes_fixed_in_the_sensor(tmp_path):
    import camera_test
    from astropy.io import fits as afits
    rng = np.random.default_rng(3)
    rows = np.arange(400)[:, None]
    for case, fixed in (("random", False), ("fixed", True)):
        folder = tmp_path / case
        folder.mkdir()
        for i in range(5):
            phase = 0 if fixed else rng.uniform(0, 100)
            lum = 1000 + rng.normal(0, 20, (400, 600)) + 8 * np.sin((rows + phase) / 7.0)
            mosaic = np.repeat(np.repeat(lum, 2, 0), 2, 1) / 4
            afits.PrimaryHDU(mosaic.astype(np.float32)).writeto(folder / f"light-{i:04d}.fits")
        found = camera_test.stripes_in(folder, say=lambda s: None)
        assert found["fixed"] is fixed


def test_a_hung_camera_is_given_up_on_within_about_two_minutes(world, monkeypatch):
    """18 October 2026: a 16 s frame was waited for 164 s, twice, and a hang
    went unnoticed for six minutes."""
    monkeypatch.setattr(camera, "BACKEND", "indi")
    monkeypatch.setattr(camera, "MANAGE_SERVER", False)
    monkeypatch.setattr(camera, "Indi", fake_indi(world))
    with camera.Camera(gain=1500) as cam:
        cam.frame(16)
    seconds, timeout, attempts = world.timeouts[-1]
    assert timeout * attempts <= 150 and timeout >= seconds + 20


def test_the_details_are_the_camera_s_part_of_altair_s_diagnose_file(sdk, world):
    """As AltairCapture gave it for this camera on 19 October 2026, read
    through the same library."""
    handle = sdk.Altaircam.Open
    def opened(camera_id):
        h = handle(camera_id)
        h.HwVersion, h.FpgaVersion = (lambda: "1.0"), (lambda: "1.1")
        h.ProductionDate, h.Revision = (lambda: "20170607"), (lambda: 1)
        return h
    sdk.Altaircam.Open = staticmethod(opened)
    flags = 0x40 | 0x10000 | 0x100           # USB 3 camera with a fan, on a USB 2 port; no frame buffer
    sdk.Altaircam.EnumV2 = staticmethod(lambda: [types.SimpleNamespace(
        displayname=name, id=serial, model=types.SimpleNamespace(flag=flags, xpixsz=2.4))
        for name, serial in world.cameras])
    with altair.AltairCamera() as cam:
        found = cam.details()
    assert (found["hardware"], found["fpga"], found["production_date"], found["revision"]) == ("1.0", "1.1",
                                                                                               "20170607", 1)
    assert found["pixel_um"] == 2.4 and found["fan"] and found["usb3_camera"]
    assert found["frame_buffer"] == "none" and found["usb3_camera_on_usb2_port"]


def test_the_details_leave_out_what_an_older_library_cannot_say(sdk, world):
    import camera_test
    with altair.AltairCamera() as cam:
        found = cam.details()
    assert found["hardware"] is None and found["production_date"] is None and found["frame_buffer"] == "none"
    camera_test.show_details(dict(found, usb_link={"port": "2-4", "mbps": 480}))


def test_a_camera_plugged_in_after_the_server_started_is_noticed(tmp_path):
    """19 October 2026: the camera came back from another computer and the
    first frame waited two minutes on the old server's dead connection."""
    import os
    devices, procs = tmp_path / "devices", tmp_path / "proc"
    (devices / "2-1").mkdir(parents=True)
    (devices / "2-1" / "product").write_text("ALTAIRH183C\n")
    plugged = (devices / "2-1").stat().st_ctime
    tick = os.sysconf("SC_CLK_TCK")
    (procs / "4242").mkdir(parents=True)
    (procs / "4242" / "comm").write_text("indiserver\n")
    boot = 1000.0

    def server_started(at):
        fields = ["S"] + ["0"] * 18 + [str(int((at - boot) * tick))]
        (procs / "4242" / "stat").write_text("4242 (indiserver) " + " ".join(fields) + " 0 0\n")
    (procs / "stat").write_text(f"cpu 1 2 3\nbtime {boot:.0f}\n")
    server_started(plugged - 120)
    assert camera.replugged(devices, procs)
    server_started(plugged + 120)
    assert not camera.replugged(devices, procs)
    (procs / "4242" / "comm").write_text("bash\n")
    assert not camera.replugged(devices, procs)                 # no server running
    assert not camera.replugged(tmp_path / "nowhere", procs)    # nothing to read


def test_a_replugged_camera_gets_a_fresh_server_before_the_first_frame(world, monkeypatch):
    restarted = []
    monkeypatch.setattr(camera, "BACKEND", "indi")
    monkeypatch.setattr(camera, "MANAGE_SERVER", True)
    monkeypatch.setattr(camera, "Indi", fake_indi(world))
    monkeypatch.setattr(camera, "replugged", lambda: True)
    monkeypatch.setattr(camera, "start_driver", lambda port=None: restarted.append(port))
    with camera.Camera(gain=300):
        pass
    assert len(restarted) == 1


def test_a_warmer_dark_says_so_in_its_tail_and_hot_pixels():
    """The fan-cooled 183C has no thermometer: its darks are one."""
    import camera_test
    rng = np.random.default_rng(31)
    shape = (800, 1000)

    def dark(doublings):
        # Black level and read noise the same; each pixel's dark current
        # spread over a long tail, doubling with each 6 °C or so.
        current = rng.lognormal(0, 1.5, shape) * 2.0 ** doublings
        return (200 + rng.normal(0, 4, shape) + rng.poisson(current)).astype(np.uint16)

    cold, warm = camera_test.dark_current(dark(0)), camera_test.dark_current(dark(2))
    assert warm["excess_adu"] > cold["excess_adu"] > 0
    assert warm["hot_ppm"] > 2 * cold["hot_ppm"]
