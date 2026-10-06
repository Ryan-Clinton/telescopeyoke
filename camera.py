"""The telescope camera (Altair Hypercam 183C) through its INDI driver, or,
with [camera] backend = "altair" in config.toml, through Altair's own library
(altair.py), which is the only route on Windows.

    with Camera() as cam:
        data, header = cam.frame(2.0)      # raw 12-bit Bayer mosaic

Frames are slow on this driver over USB 2: about 4 s plus five times the
exposure length, so a 2 s exposure takes roughly 14 s to arrive. On USB 3 a
1 s exposure arrives in about 1.5 s.
"""
import io
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
        c.set(self.name, "CCD_CAPTURE_FORMAT", INDI_RAW="On")
        if (c.get(self.name, "CCD_TRANSFER_FORMAT") or {}).get("FORMAT_FITS", "On") != "On":
            # Left on native transfer (camera_test.py did, when its trial of
            # it timed out), every frame arrives as something that is not FITS.
            c.set(self.name, "CCD_TRANSFER_FORMAT", FORMAT_FITS="On")
        c.set(self.name, "CCD_CONTROLS", Gain=self.gain)
        c.pump(1)

    def frame(self, seconds):
        """One exposure as (uint16 Bayer mosaic, FITS header). If the driver
        stops delivering and manage_server is on, it is restarted once and
        the exposure retried."""
        wait = 12 + 6 * seconds
        for attempt in range(2):
            try:
                _, raw = self.client.expose(self.name, seconds, timeout=wait, attempts=2)
                with fits.open(io.BytesIO(raw)) as hdul:
                    return hdul[0].data, hdul[0].header
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
