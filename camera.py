"""The telescope camera (Altair Hypercam 183C) through its INDI driver, or,
with [camera] backend = "altair" in config.toml, through Altair's own library
(altair.py), which is the only route on Windows.

    with Camera() as cam:
        data, header = cam.frame(2.0)      # raw 12-bit Bayer mosaic

Frames are slow on this driver over USB 2: about 4 s plus five times the
exposure length, so a 2 s exposure takes roughly 14 s to arrive. On USB 3 a
1 s exposure arrives in about 1.5 s.

    cam.use("focus_fast")                  # quick frames for focusing: binned 2x2 if the camera will
    cam.use("imaging")                     # the full sensor again
"""
import io
import json
import subprocess
import time

import numpy as np
from astropy.io import fits

import config
from indi import Indi, IndiError
from interface import Refusal

SETTINGS = config.hardware()
DRIVER = SETTINGS["camera"]["driver"]
PORT = SETTINGS["indi"]["port"]
# Whether this project may start and restart the INDI server itself. Leave it
# off if other equipment (a guider, focuser, filter wheel) shares the server:
# restarting would cut them all off.
MANAGE_SERVER = SETTINGS["indi"]["manage_server"]
# Extra waiting time the driver allows per exposure. At its default of 1.2
# most exposures over a second time out on USB 2.
TIMEOUT_FACTOR = 10
WHITE = 2 ** SETTINGS["camera"]["bit_depth"] - 1  # brightest raw value


BACKEND = SETTINGS["camera"]["backend"]   # "indi", or "altair" for Altair's own library

# What a caller wants its frames for, and the binning that asks of the
# camera. A caller names the purpose with cam.use(); only this layer and the
# routes under it know a camera's own settings. Focusing judges brightness
# alone, so its quick frames may be binned whatever that does to the colour
# pattern. Imaging is never binned: the darks, the colour and the plate
# scale all assume the full sensor.
PROFILES = {"imaging": 1, "focus_fine": 1, "focus_fast": 2}


# What camera_test.py --trail measured: how long the shutter was really open.
TIMING_FILE = config.DATA / "cache" / "camera_timing.json"


def shutter_share(speed):
    """The share of the time asked for which the shutter is really open at
    this readout speed, as camera_test.py --trail measured it from star
    trails; 1 when it has not been measured at this speed, or the figure
    is not to be believed.

    The 183C through Altair's library 1.53 times its exposures by a clock
    that changes with the driver's Speed control and is right at none of
    its settings: on 13 October 2026 each second asked for added 1.25 s to
    a frame at Speed 0, 0.86 s at Speed 1 and 0.63 s at Speed 2, the
    driver's own choice, where a 10 s frame's trails showed 6.4 s."""
    try:
        found = json.loads(TIMING_FILE.read_text(encoding="utf-8"))["trail"]
        share = float(found["share_of_asked"])
    except (OSError, ValueError, KeyError, TypeError):
        return 1.0
    if found.get("speed") != speed or not 0.3 <= share <= 1.5 or abs(share - 1) < 0.05:
        return 1.0
    return share


class Camera:
    def __new__(cls, port=PORT, gain=300):
        # With the SDK backend the caller gets altair.py's camera instead. It
        # is not a Camera, so the INDI set-up below never runs for it.
        if cls is Camera and config.DEMO:
            # The demo's pretend camera and sky.
            from simulator import SimulatedCamera
            return SimulatedCamera(port, gain)
        if cls is Camera and BACKEND == "altair":
            from altair import AltairCamera
            return AltairCamera(gain=gain)
        return super().__new__(cls)

    def __init__(self, port=PORT, gain=300):
        self.port, self.gain = port, gain
        self.binning = 1                 # what the frames now arriving are binned by
        self.refuses_binning = False     # asked once and it failed: not asked again
        self._open()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        self.client.close()

    def _open(self):
        try:
            self.client = Indi(port=self.port)
        except OSError:
            if not MANAGE_SERVER:
                raise SystemExit(
                    f"No INDI server on port {self.port}. Start one with "
                    f"'indiserver {DRIVER}', or set manage_server = true under "
                    "[indi] in config.toml to have it started for you.")
            start_driver(self.port)
            self.client = Indi(port=self.port)
        c = self.client
        self.name = next((d for d in c.devices() if c.get(d, "CCD_EXPOSURE")
                          or "Altair" in d), None)
        if self.name is None:
            raise Refusal("CAMERA_NOT_CONNECTED", "No camera found. Is it plugged in?")
        c.connect(self.name)
        # The next two exist only on Altair/ToupTek drivers.
        if c.get(self.name, "CCD_AUTO_EXPOSURE"):
            c.set(self.name, "CCD_AUTO_EXPOSURE", TC_AUTO_EXPOSURE_OFF="On")
        if c.get(self.name, "TIMEOUT_FACTOR"):
            c.set(self.name, "TIMEOUT_FACTOR", VALUE=TIMEOUT_FACTOR)
        modes = c.get(self.name, "CCD_RESOLUTION")
        if modes and next(iter(modes.values())) != "On":
            # The first mode listed is the full sensor. Something (a test, a
            # crash) left a smaller one selected.
            c.set(self.name, "CCD_RESOLUTION", **{next(iter(modes)): "On"})
        c.set(self.name, "CCD_BINNING", HOR_BIN=1, VER_BIN=1)
        self.binning = 1
        c.set(self.name, "CCD_CAPTURE_FORMAT", INDI_RAW="On")
        if (c.get(self.name, "CCD_TRANSFER_FORMAT") or {}).get("FORMAT_FITS", "On") != "On":
            # Left on native transfer (camera_test.py did, when its trial of
            # it timed out), every frame arrives as something that is not FITS.
            c.set(self.name, "CCD_TRANSFER_FORMAT", FORMAT_FITS="On")
        c.set(self.name, "CCD_CONTROLS", Gain=self.gain)
        # Set every time the camera is opened, so a restart of the driver
        # cannot put them back to its own defaults (17 October 2026: after
        # one, broad stripes crossed every frame).
        self.settings(SETTINGS["camera"].get("fan"), SETTINGS["camera"].get("offset"))
        c.pump(1)
        # The readout speed the driver is using, and so how much longer to
        # ask for than is wanted: see shutter_share().
        try:
            self.speed = int(float((c.get(self.name, "CCD_CONTROLS") or {})["Speed"]))
        except (KeyError, TypeError, ValueError):
            self.speed = None
        self.shutter = shutter_share(self.speed)

    def settings(self, fan=None, offset=None, speed=None):
        """The cooling fan ("on" or "off"), the black level (offset) and the
        readout speed, on drivers that have them; None leaves each as it is.
        A new speed changes the shutter's share (shutter_share), so it is
        read again."""
        c = self.client
        if speed is not None:
            c.set(self.name, "CCD_CONTROLS", Speed=int(speed))
            c.pump(1)
            self.speed = int(speed)
            self.shutter = shutter_share(self.speed)
        if fan in ("on", "off") and c.get(self.name, "TC_FAN_CONTROL"):
            c.set(self.name, "TC_FAN_CONTROL", **{f"TC_FAN_{fan.upper()}": "On"})
        if offset is not None and c.get(self.name, "CCD_OFFSET"):
            c.set(self.name, "CCD_OFFSET", OFFSET=int(offset))

    def use(self, profile):
        """Set the camera up for what its frames are for (a name in PROFILES)
        and return the binning now in effect. A camera that will not bin
        stays on the full sensor and the answer is 1; frame() then gives
        what it always gave."""
        wanted = PROFILES[profile]
        if wanted == self.binning or (wanted > 1 and self.refuses_binning):
            return self.binning
        try:
            self.client.set(self.name, "CCD_BINNING", HOR_BIN=wanted, VER_BIN=wanted)
            self.binning = wanted
        except (IndiError, OSError):
            # On 6 October 2026 asking the open camera for 2x2 once ended
            # with the connection to the server broken. Open it afresh, on
            # the full sensor, and do not ask this camera again.
            self.refuses_binning = True
            self.close()
            self._open()
        return self.binning

    def frame(self, seconds):
        """One exposure as (uint16 Bayer mosaic, FITS header). If the driver
        stops delivering and manage_server is on, it is restarted once and
        the exposure retried.

        `seconds` is how long the shutter is to be open. The driver is asked
        for more or less than that where the camera is known to keep its
        own time (shutter_share), and the frame's EXPTIME says `seconds`."""
        ask = seconds / self.shutter
        wait = 12 + 6 * ask
        for attempt in range(2):
            try:
                _, raw = self.client.expose(self.name, ask, timeout=wait, attempts=2)
                with fits.open(io.BytesIO(raw)) as hdul:
                    data, header = hdul[0].data, hdul[0].header
                if ask != seconds:
                    header["EXPTIME"] = (seconds, "shutter open, s (trail-measured share applied)")
                    header["TY_ASKED"] = (round(ask, 4), "exposure asked of the driver, s")
                # The frame itself says how it was binned, whatever was asked for.
                self.binning = int(header.get("XBINNING", self.binning))
                return data, header
            except (IndiError, OSError):
                if attempt or not MANAGE_SERVER:
                    raise
                start_driver(self.port)
                self._open()


def start_driver(port=PORT):
    """(Re)start the INDI server with the camera driver. This stops any INDI
    server already running, so it is only used when manage_server is on."""
    subprocess.run(["pkill", "-x", "indiserver"])
    subprocess.run(["pkill", "-x", DRIVER])
    time.sleep(2)
    subprocess.Popen(["indiserver", "-p", str(port), DRIVER],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    time.sleep(4)


def luminance(mosaic):
    """Brightness image at half resolution: each 2x2 colour cell summed."""
    m = mosaic.astype(np.float32)
    return m[0::2, 0::2] + m[0::2, 1::2] + m[1::2, 0::2] + m[1::2, 1::2]


def colour(mosaic):
    """Half-resolution RGB image, shape (rows, cols, 3), from an RGGB mosaic."""
    m = mosaic.astype(np.float32)
    green = (m[0::2, 1::2] + m[1::2, 0::2]) / 2
    return np.dstack([m[0::2, 0::2], green, m[1::2, 1::2]])


def stretch(image):
    """Map an image to 8 bits, pulling faint detail up from the background.
    Works per colour channel, which also evens out the sensor's colour cast."""
    image = image.astype(np.float32)
    axes = (0, 1)
    lo, hi = np.percentile(image[::4, ::4], (0.5, 99.9), axis=axes, keepdims=True)
    scaled = np.clip((image - lo) / np.maximum(hi - lo, 1e-6), 0, 1)
    return (255 * np.arcsinh(10 * scaled) / np.arcsinh(10)).astype(np.uint8)
