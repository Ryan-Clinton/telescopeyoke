"""The telescope camera through Altair's own library, with no INDI server.

    with AltairCamera(gain=300) as cam:
        data, header = cam.frame(2.0)      # raw 12-bit Bayer mosaic

camera.Camera hands out one of these when config.toml says
[camera] backend = "altair", which is the default on Windows, where INDI does
not run. It gives its callers what the INDI route gives them and nothing else
changes above it.

The library and its Python wrapper belong to Altair and are not part of this
project. Put altaircam.py, and on Windows the 64-bit altaircam.dll beside it,
in vendor/altair/. On Windows the camera's driver comes with AltairCapture.
"""
import ctypes
import struct
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from astropy.io import fits

import config
import host
from indi import IndiError as CameraError   # one error for both routes
from interface import Refusal

ROOT = Path(__file__).parent
VENDOR = ROOT / "vendor" / "altair"
SETTINGS = config.hardware()
WHITE = 2 ** SETTINGS["camera"]["bit_depth"] - 1  # brightest raw value
FLUSH_BOTH = 3      # ALTAIRCAM_OPTION_FLUSH: 1 the camera's memory, 2 the library's, 3 both
USB3_ON_USB2 = 0x100   # ALTAIRCAM_FLAG_USB30_OVER_USB20


def wait_for(seconds):
    """Longest wait for a frame. It is the INDI route's figure, kept as the
    upper limit until the SDK's real timing has been measured."""
    return 12 + 6 * seconds


def sdk():
    """Altair's Python wrapper, from vendor/altair/."""
    if "altaircam" not in sys.modules:
        if not (VENDOR / "altaircam.py").exists():
            raise Refusal("CAMERA_NOT_CONNECTED",
                          f"Altair's SDK is not installed: put altaircam.py"
                          f"{' and the 64-bit altaircam.dll' if host.WINDOWS else ''} from the "
                          f"SDK zip in {VENDOR}.")
        sys.path.insert(0, str(VENDOR))
    import altaircam
    return altaircam


def cameras(lib):
    """The cameras plugged in, as the library lists them."""
    return list(lib.Altaircam.EnumV2())


def _serial(lib, device):
    """A camera's serial number, which needs it opened for a moment."""
    handle = lib.Altaircam.Open(device.id)
    if handle is None:
        return ""
    try:
        return handle.SerialNumber()
    finally:
        handle.Close()


def choose(lib, wanted=None):
    """The one camera to use. None plugged in is a refusal; so are several,
    unless config.toml names one by its serial number. Never the first of
    several: the wrong camera would give frames that look plausible."""
    found = cameras(lib)
    if not found:
        raise Refusal("CAMERA_NOT_CONNECTED", "No camera found. Is it plugged in?" + (
            " On Windows its driver comes with AltairCapture: install that, check the "
            "camera shows a picture in it, then close it." if host.WINDOWS else ""))
    if len(found) == 1 and not wanted:
        return found[0]
    serials = {device.id: _serial(lib, device) for device in found}
    if wanted:
        for device in found:
            if serials[device.id] == wanted:
                return device
    listed = "; ".join(f"{d.displayname} (serial {serials[d.id] or 'unreadable'})" for d in found)
    if wanted:
        raise Refusal("CAMERA_NOT_CONNECTED",
                      f"No camera has the serial number {wanted} named in config.toml. Found: {listed}.")
    raise Refusal("CAMERA_NOT_CONNECTED",
                  f"{len(found)} cameras are plugged in: {listed}. Name the one to use with "
                  "serial = \"...\" under [camera] in config.toml.")


class AltairCamera:
    def __init__(self, gain=300):
        self.gain = gain
        self.lib = sdk()
        self.handle = None
        # What the library's own thread tells us, and what we are waiting for.
        self._changed = threading.Condition()
        self._waiting = False     # an exposure has been triggered and not yet collected
        self._ready = False       # its frame has arrived
        self._failure = None      # or the camera said why it will not
        self._shifted = None      # whether the 12 bits arrive at the top of the 16
        self.exposures = 0        # how many have been triggered
        self._open()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # --- opening and closing ---------------------------------------------------

    def _open(self):
        lib, camera = self.lib, SETTINGS["camera"]
        device = choose(lib, camera.get("serial"))
        self.name = device.displayname
        handle = lib.Altaircam.Open(device.id)
        if handle is None:
            raise Refusal("CAMERA_NOT_CONNECTED",
                          f"{self.name} would not open. Only one program can use the camera: "
                          "close AltairCapture, SharpCap or anything else that has it.")
        self.handle = handle
        try:
            handle.put_AutoExpoEnable(0)
            handle.put_Option(lib.ALTAIRCAM_OPTION_RAW, 1)        # only settable before starting
            # The sensor's full depth, not its 8-bit mode. Each value still
            # arrives in a 16-bit number, whatever the depth.
            handle.put_Option(lib.ALTAIRCAM_OPTION_BITDEPTH, 1)
            handle.put_eSize(0)                                   # the first size listed is the full sensor
            handle.put_Option(lib.ALTAIRCAM_OPTION_BINNING, 1)
            if camera.get("readout_speed") is not None:
                handle.put_Speed(int(camera["readout_speed"]))
            handle.put_Option(lib.ALTAIRCAM_OPTION_TRIGGER, 1)    # one exposure per request
            self.width, self.height = handle.get_Size()
            fourcc, self.bits = handle.get_RawFormat()
            self.pattern = struct.pack("<I", fourcc).decode("ascii", "replace")
            handle.put_ExpoAGain(self.gain)
            # The library keeps only a pointer to the callback. Holding it on
            # this object keeps it alive for as long as the camera can call it.
            self._callback = self._event
            handle.StartPullModeWithCallback(self._callback, self)
        except lib.HRESULTException as problem:
            self.close()
            raise CameraError(f"the camera would not be set up: {_reason(problem)}")

    def close(self):
        handle, self.handle = self.handle, None
        if handle is None:
            return
        for step in (lambda: handle.Trigger(0), handle.Stop, handle.Close):
            try:
                step()
            except Exception:
                pass   # it is being closed whatever it says

    # --- the library's thread ----------------------------------------------------

    @staticmethod
    def _event(event, self):
        """Called by the library on its own thread. It only notes what
        happened and wakes frame(); the frame is pulled by the caller."""
        lib = self.lib
        with self._changed:
            if event == lib.ALTAIRCAM_EVENT_IMAGE:
                # A frame nobody is waiting for is a late one from an exposure
                # that timed out. It must never answer the next request, so it
                # is not remembered; frame() discards it before it triggers.
                if self._waiting:
                    self._ready = True
            elif event == lib.ALTAIRCAM_EVENT_DISCONNECTED:
                self._failure = "the camera was unplugged"
            elif event == lib.ALTAIRCAM_EVENT_ERROR:
                self._failure = "the camera reported an error"
            elif event == lib.ALTAIRCAM_EVENT_TRIGGERFAIL:
                self._failure = "the camera could not take the exposure"
            else:
                return
            self._changed.notify_all()

    # --- taking a frame ------------------------------------------------------------

    def _discard(self):
        """Throw away any frame left in the camera or the library."""
        try:
            self.handle.put_Option(self.lib.ALTAIRCAM_OPTION_FLUSH, FLUSH_BOTH)
        except self.lib.HRESULTException:
            pass   # nothing to discard, or not supported: the count below still guards

    def _expose(self, seconds):
        lib, handle = self.lib, self.handle
        handle.put_ExpoTime(max(1, round(seconds * 1e6)))
        handle.put_ExpoAGain(self.gain)
        with self._changed:
            self._waiting = self._ready = False
            self._failure = None
        self._discard()
        with self._changed:
            self.exposures += 1
            self._waiting = True
        started, began = datetime.now(timezone.utc), time.monotonic()
        handle.Trigger(1)
        give_up = began + wait_for(seconds)
        while True:
            with self._changed:
                arrived = self._changed.wait_for(lambda: self._ready or self._failure,
                                                 timeout=max(0, give_up - time.monotonic()))
                failure = self._failure
                early = arrived and not failure and time.monotonic() - began < 0.9 * seconds
                if early:
                    self._ready = False
                else:
                    self._waiting = False
            if not early:
                break
            # No exposure can be back before its shutter has closed: this is
            # a late frame from an earlier one. Take it out of the way and
            # keep waiting for ours.
            self._pull()
        if failure or not arrived:
            # Cancel it and empty the pipes, so a frame that turns up late
            # cannot be taken for the next one.
            try:
                handle.Trigger(0)
            except lib.HRESULTException:
                pass
            self._discard()
            raise CameraError(failure or f"no frame within {wait_for(seconds):.0f} s "
                                         f"of a {seconds:g} s exposure")
        return self._normalise(self._pull()), started

    def _pull(self):
        """The frame the library is holding, as it gave it."""
        data = np.empty((self.height, self.width), dtype=np.uint16)
        buffer = (ctypes.c_ubyte * data.nbytes).from_buffer(data)
        self.handle.PullImageV3(buffer, 0, 16, -1, None)   # -1: rows packed with no padding
        return data

    def _normalise(self, data):
        """Values from 0 to WHITE. The library may hand the sensor's 12 bits
        over at the top of each 16-bit number; then the bottom four bits of
        every value are empty, which never happens in a real frame otherwise."""
        spare = 16 - self.bits
        if spare <= 0:
            return data
        if self._shifted is None and data.any():
            self._shifted = not (np.bitwise_or.reduce(data, axis=None) & ((1 << spare) - 1))
        if self._shifted:
            data >>= spare
        return data

    def frame(self, seconds):
        """One exposure as (uint16 Bayer mosaic, FITS header). An exposure
        that fails is tried once more, then once more with the camera closed
        and opened again."""
        lib = self.lib
        for attempt in range(3):
            try:
                data, started = self._expose(seconds)
                break
            except (CameraError, lib.HRESULTException) as problem:
                if isinstance(problem, lib.HRESULTException):
                    problem = CameraError(_reason(problem))
                if attempt == 2 or "unplugged" in str(problem):
                    raise problem
                if attempt == 1:
                    self.close()
                    self._open()
        header = fits.Header()
        header["EXPTIME"] = (float(seconds), "seconds")
        header["GAIN"] = (self.gain, "camera gain, percent")
        # When the exposure started, not when the frame arrived.
        header["DATE-OBS"] = (started.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3], "UTC, start of exposure")
        header["BAYERPAT"] = self.pattern
        header["INSTRUME"] = self.name
        return data, header

    # --- what the camera is, for camera_test.py and the doctor ----------------------

    def details(self):
        lib, handle = self.lib, self.handle
        device = next((d for d in cameras(lib) if d.displayname == self.name), None)
        flags = device.model.flag if device else 0
        return {
            "model": self.name, "serial": handle.SerialNumber(),
            "sdk_version": lib.Altaircam.Version(), "firmware": handle.FwVersion(),
            "flags": hex(flags), "usb3_camera_on_usb2_port": bool(flags & USB3_ON_USB2),
            "size": [self.width, self.height], "bit_depth": self.bits, "bayer": self.pattern,
            "readout_speed": handle.get_Speed(), "max_readout_speed": handle.MaxSpeed(),
        }


def _reason(problem):
    hr = getattr(problem, "hr", None)
    return f"SDK error 0x{hr & 0xffffffff:08x}" if isinstance(hr, int) else str(problem)


def checks():
    """Four lines for the doctor: Python, the wrapper, the library, a camera."""
    OK, WARN, FAIL = host.OK, host.WARN, host.FAIL
    bits = struct.calcsize("P") * 8
    if host.WINDOWS and bits != 64:
        return [(FAIL, f"Python is {bits}-bit; the camera needs 64-bit Python and the 64-bit DLL")]
    out = [(OK, f"Python is {bits}-bit")]
    if not (VENDOR / "altaircam.py").exists():
        return out + [(FAIL, f"Altair SDK wrapper not found: copy altaircam.py from the SDK "
                             f"zip's python folder to {VENDOR}")]
    out.append((OK, "Altair SDK wrapper (vendor/altair/altaircam.py)"))
    if host.WINDOWS and not (VENDOR / "altaircam.dll").exists():
        return out + [(FAIL, f"Altair SDK library not found: copy altaircam.dll from the SDK "
                             f"zip's win/x64 folder to {VENDOR}")]
    try:
        lib = sdk()
        found = cameras(lib)
        version = lib.Altaircam.Version()
    except OSError as problem:
        if getattr(problem, "winerror", None) == 193:
            return out + [(FAIL, "Altair SDK library is the 32-bit one: copy altaircam.dll "
                                 "from the SDK zip's win/x64 folder instead")]
        return out + [(FAIL, f"Altair SDK library would not load: {problem}")]
    except Exception as problem:
        return out + [(FAIL, f"Altair SDK would not start: {type(problem).__name__}: {problem}")]
    out.append((OK, f"Altair SDK library, version {version}"))
    if not found:
        advice = (": install AltairCapture for the driver and check the camera shows in it"
                  if host.WINDOWS else " (is it plugged in?)")
        return out + [(FAIL, "no camera found" + advice)]
    slow = [d.displayname for d in found if d.model.flag & USB3_ON_USB2]
    if slow:
        out.append((WARN, f"{slow[0]} is a USB 3 camera on a USB 2 port; frames will be slow"))
    if len(found) > 1 and not SETTINGS["camera"].get("serial"):
        out.append((FAIL, f"{len(found)} cameras found; name one with serial under [camera] in config.toml"))
    else:
        out.append((OK, f"camera: {found[0].displayname}"))
    return out
