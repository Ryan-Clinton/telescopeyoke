#!/usr/bin/env python3
"""The guide camera: an Altair GPCAM MT9M034M (mono, 1280 x 960, 3.75 um).

    ./guidecam.py                       find it and say what it is
    ./guidecam.py snap --exposure 0.5   one frame, kept in frames/guide/
    ./guidecam.py install               fetch the library it needs
    ./guidecam.py pulse [--seconds 5]   test the ST4 lead to the mount: a
                                        pulse each way, the handset read
                                        around each (--dry-run first)

This early GPCAM (USB 16d0:0b2a) is no longer opened by Altair's current
library, on Linux or Windows, nor by ToupTek's: on 2 November 2026 versions
from 2018 to 2026 all listed no camera. The oaCapture project's
libaltaircamlegacy 1.24.11330, kept for cameras the SDK dropped, opens it:
1280 x 960 frames, the level rising with the exposure. It is used here for
the guide camera only; the main camera stays on the current library
(altair.py). Frames are kept under frames/guide/ and never shown on the
status page. Linux only: the Windows library does not open it either.
"""
import argparse
import ctypes
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import numpy as np

import config
import interface

VENDOR = config.ROOT / "vendor" / "altair-legacy"
LIBRARY = VENDOR / "libaltaircamlegacy.so.1.24.11330"
PACKAGE = ("http://www.openastroproject.org/wp-content/uploads/2020/12/ubuntu-20.04-amd64/"
           "libaltaircamlegacy_1.24.11330-2_amd64.deb")
MODEL = "GPCAMMT9M034M"
USB_ID = "16d0:0b2a"
FOLDER = config.DATA / "frames" / "guide"
WAIT_S = 5.0          # beyond the exposure, how long a frame may take to come


def refuse(why):
    raise interface.Refusal("CAMERA_NOT_CONNECTED", why)


class Driver:
    """The legacy library through ctypes, as plain Python calls. The tests
    stand in their own object with the same methods."""

    class _Model(ctypes.Structure):
        _fields_ = [("name", ctypes.c_char_p)]

    class _Device(ctypes.Structure):
        pass

    _Device._fields_ = [("displayname", ctypes.c_char * 64), ("id", ctypes.c_char * 64),
                        ("model", ctypes.POINTER(_Model))]

    def __init__(self, path=LIBRARY):
        if sys.platform != "linux":
            refuse("The guide camera's library is for Linux only: no Altair library opens this "
                   "early GPCAM on Windows.")
        if not Path(path).exists():
            refuse(f"The guide camera's library is not installed: ./guidecam.py install puts it in {VENDOR}.")
        self.lib = ctypes.CDLL(str(path))          # its own copy: the main camera's library is untouched
        self.lib.Altaircam_EnumV2.restype = ctypes.c_uint
        self.lib.Altaircam_Open.restype = ctypes.c_void_p
        self.lib.Altaircam_Open.argtypes = [ctypes.c_char_p]
        self.buffer = None

    def cameras(self):
        found = (self._Device * 16)()
        n = self.lib.Altaircam_EnumV2(found)
        return [(d.model.contents.name.decode(), d.id) for d in found[:n]]

    def open(self, ident):
        handle = self.lib.Altaircam_Open(ident)
        if not handle:
            refuse("The guide camera is listed but would not open: unplug it and plug it in again.")
        handle = ctypes.c_void_p(handle)
        width, height = ctypes.c_int(), ctypes.c_int()
        self.lib.Altaircam_get_Size(handle, ctypes.byref(width), ctypes.byref(height))
        self.buffer = ctypes.create_string_buffer(width.value * height.value * 3)
        self.lib.Altaircam_put_AutoExpoEnable(handle, 0)
        self._callback = ctypes.CFUNCTYPE(None, ctypes.c_uint, ctypes.c_void_p)(lambda kind, ctx: None)
        self.lib.Altaircam_StartPullModeWithCallback(handle, self._callback, None)
        return handle, (width.value, height.value)

    def exposure(self, handle, seconds):
        self.lib.Altaircam_put_ExpoTime(handle, ctypes.c_uint(int(round(seconds * 1e6))))

    def gain(self, handle, percent):
        self.lib.Altaircam_put_ExpoAGain(handle, ctypes.c_ushort(int(percent)))

    def pull(self, handle):
        """The next frame as (width, height, bytes), or None if none is ready."""
        width, height = ctypes.c_uint(), ctypes.c_uint()
        if self.lib.Altaircam_PullImage(handle, self.buffer, 8, ctypes.byref(width), ctypes.byref(height)) != 0:
            return None
        return width.value, height.value, self.buffer.raw[:width.value * height.value]

    def st4(self, handle, direction, ms):
        """A guiding pulse out of the camera's ST4 port: 0 north, 1 south,
        2 east, 3 west, 4 stop. Below zero is a refusal."""
        self.lib.Altaircam_ST4PlusGuide.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint]
        return self.lib.Altaircam_ST4PlusGuide(handle, direction, ms)

    def st4_busy(self, handle):
        self.lib.Altaircam_ST4PlusGuideState.argtypes = [ctypes.c_void_p]
        return self.lib.Altaircam_ST4PlusGuideState(handle) == 0     # S_OK while a pulse is going

    def close(self, handle):
        self.lib.Altaircam_Close(handle)


DIRECTIONS = {"north": 0, "south": 1, "east": 2, "west": 3}
STOP = 4


class GuideCamera:
    """The guide camera opened: frame(seconds) gives one 8-bit frame taken
    wholly at that exposure. The first frame after a change of exposure was
    still taken at the old one (2 November 2026: at 10 ms the first read 17,
    as at 1 ms, the next 151), so frames that began before the change are
    let go."""

    def __init__(self, driver=None, clock=time.monotonic, sleep=time.sleep):
        self.driver = driver or Driver()
        self.clock, self.sleep = clock, sleep
        found = [c for c in self.driver.cameras() if c[0] == MODEL]
        if not found:
            refuse(f"No guide camera ({MODEL}, USB {USB_ID}) found. Is it plugged in?")
        self.handle, self.size = self.driver.open(found[0][1])
        self.seconds = None

    def frame(self, seconds, gain=None):
        if gain is not None:
            self.driver.gain(self.handle, gain)
        if seconds != self.seconds:
            self.driver.exposure(self.handle, seconds)
            self.seconds = seconds
        asked = self.clock()
        while True:
            got = self.driver.pull(self.handle)
            now = self.clock()
            if got and now - asked >= seconds:
                width, height, data = got
                return np.frombuffer(data, np.uint8).reshape(height, width).copy()
            if now - asked > seconds + WAIT_S:
                refuse(f"The guide camera sent no frame within {seconds + WAIT_S:.0f} s.")
            if not got:
                self.sleep(0.02)

    def pulse(self, direction, seconds):
        """One ST4 pulse, waited out."""
        if self.driver.st4(self.handle, DIRECTIONS[direction], int(seconds * 1000)) < 0:
            refuse("The guide camera refused to send an ST4 pulse.")
        end = self.clock() + seconds + 2
        self.sleep(seconds)
        while self.driver.st4_busy(self.handle) and self.clock() < end:
            self.sleep(0.05)

    def stop_pulse(self):
        self.driver.st4(self.handle, STOP, 0)

    def close(self):
        self.driver.close(self.handle)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def keep(frame, seconds, gain, folder=None, now=None):
    """The frame as a FITS file under frames/guide/, with its exposure."""
    from astropy.io import fits
    folder = Path(folder or FOLDER)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"guide-{(now or datetime.now()):%Y%m%d-%H%M%S-%f}.fits"
    header = fits.Header({"EXPTIME": seconds, "INSTRUME": MODEL, "GAIN": gain if gain is not None else -1})
    fits.writeto(path, frame, header, overwrite=True)
    return path


MOVED = 4.0        # arcseconds an axis must turn beyond the still reading to count as moved


def cable_test(cam, scope, seconds=5.0, say=print, sleep=time.sleep):
    """Whether the ST4 lead from the guide camera to the mount works: the
    handset's axis readings across a still wait, then across a pulse each
    way. North and south should turn the Dec axis opposite ways, east and
    west the RA axis (against the tracking seen in the still wait). The
    mount tracks for the test, and is left as it was found."""
    import mount
    if mount.LOCK_FILE.exists():
        raise interface.Refusal("MOTION_LOCKED", "Motion is locked: "
                                + mount.LOCK_FILE.read_text(encoding="utf-8").strip())
    was = scope.state()
    if was == "slewing":
        refuse("The mount is slewing: test the ST4 lead once it has stopped.")
    if was == "stopped":
        scope.tracking(True)

    def turn(during):
        ra0, dec0 = scope.axes()
        during()
        ra1, dec1 = scope.axes()
        return mount.wrap(ra1 - ra0) * 3600, mount.wrap(dec1 - dec0) * 3600

    results = {}
    try:
        still = turn(lambda: sleep(seconds))
        say(f"still {seconds:g} s: RA axis {still[0]:+.1f}\", Dec axis {still[1]:+.1f}\"")
        for name in DIRECTIONS:
            ra, dec = turn(lambda: cam.pulse(name, seconds))
            axis = 1 if name in ("north", "south") else 0
            moved = (ra, dec)[axis] - still[axis]
            results[name] = moved
            say(f"{name:5} {seconds:g} s: RA axis {ra:+.1f}\", Dec axis {dec:+.1f}\"  -> "
                f"{'Dec' if axis else 'RA'} {moved:+.1f}\" beyond still: "
                f"{'moved' if abs(moved) >= MOVED else 'NO MOVE'}")
    finally:
        cam.stop_pulse()
        if was == "stopped":
            scope.tracking(False)
    pairs = {"Dec (north/south)": ("north", "south"), "RA (east/west)": ("east", "west")}
    for label, (a, b) in pairs.items():
        ok = abs(results[a]) >= MOVED and abs(results[b]) >= MOVED and results[a] * results[b] < 0
        say(f"{label}: {'works' if ok else 'NOT WORKING'}")
    return results


def install(say=print, fetch=None, run=subprocess.run):
    """The legacy library fetched from the oaCapture project and unpacked into vendor/."""
    if LIBRARY.exists():
        say(f"already installed: {LIBRARY}")
        return LIBRARY
    import requests
    fetch = fetch or (lambda url: requests.get(url, timeout=60).content)
    VENDOR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as scratch:
        deb = Path(scratch) / "legacy.deb"
        deb.write_bytes(fetch(PACKAGE))
        run(["dpkg-deb", "-x", str(deb), scratch], check=True)
        found = next(Path(scratch).rglob(LIBRARY.name), None)
        if found is None:
            refuse(f"The package from {PACKAGE} did not hold {LIBRARY.name}.")
        LIBRARY.write_bytes(found.read_bytes())
    say(f"installed {LIBRARY}")
    return LIBRARY


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="action")
    sub.add_parser("install", help="fetch the library this camera needs")
    s = sub.add_parser("snap", help="one frame, kept under frames/guide/")
    s.add_argument("--exposure", type=float, default=0.5, help="seconds")
    s.add_argument("--gain", type=int, help="the camera's gain, per cent (100 = none)")
    s.add_argument("--count", type=int, default=1, help="frames one after another, each kept")
    p = sub.add_parser("pulse", help="test the ST4 lead to the mount: a pulse each way, the handset read around each")
    p.add_argument("--seconds", type=float, default=5.0, help="length of each pulse")
    p.add_argument("--dry-run", action="store_true", help="say what it would do, open nothing")
    args = ap.parse_args(argv)
    try:
        if args.action == "install":
            install()
            return
        if args.action == "pulse" and args.dry_run:
            print(f"would: read the handset, wait {args.seconds:g} s still, then pulse north, south, east, "
                  f"west for {args.seconds:g} s each through the guide camera's ST4 port, reading the handset "
                  "around each; tracking on for the test if it was off, and off again after")
            return
        if args.action == "pulse":
            import mount
            scope = mount.Mount(watch=False)
            with GuideCamera() as cam:
                cable_test(cam, scope, args.seconds)
            return
        with GuideCamera() as cam:
            width, height = cam.size
            print(f"guide camera: {MODEL}, {width} x {height}")
            for n in range(args.count if args.action == "snap" else 0):
                frame = cam.frame(args.exposure, args.gain)
                path = keep(frame, args.exposure, args.gain, now=datetime.now())
                print(f"{args.exposure:g} s: level {frame.mean():.1f} of 255 (lowest {frame.min()}, "
                      f"highest {frame.max()}); kept as {path.name}")
    except interface.Refusal as refusal:
        sys.exit(str(refusal))


if __name__ == "__main__":
    main()
