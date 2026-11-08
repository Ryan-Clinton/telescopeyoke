#!/usr/bin/env python3
"""The guide camera: an Altair GPCAM MT9M034M (mono, 1280 x 960, 3.75 um).

    ./guidecam.py                       find it and say what it is
    ./guidecam.py snap --exposure 0.5   one frame, kept in frames/guide/
    ./guidecam.py install               fetch the library it needs
    ./guidecam.py pulse [--seconds 5]   test the ST4 lead to the mount: a
                                        pulse each way, the handset read
                                        around each (--dry-run first)
    ./guidecam.py star [--count 30]     find a guide star and follow it,
                                        no pulses: how much it wanders
    ./guidecam.py calibrate             pulse each way in steps and learn
                                        what each does (--dry-run first)
    ./guidecam.py guide [--minutes M]   guide: the kept calibration checked
                                        and reused, or a new one, then the
                                        loop (--dry-run first)

Guiding is guider.py's; docs/autoguiding.md is its specification.

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
import os
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
DUPLICATES = 3        # the same frame again this many times running: a camera fault
# How guiding opens the camera: 640 x 480 (the library's size 1, 2 x 2
# binning) at USB speed 0. At full size, at any speed, it sends one 2 s
# frame in 13 to 18 s; this way it sent 149 of 150 in 5 minutes
# (6 November 2026, docs/guide-camera-fault.md). guider.BIN must match.
GUIDE_SIZE = 1
GUIDE_SPEED = 0


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
        self.pull_error = None  # the last code from PullImage that was not "no frame yet"
        self.events = []        # (time.monotonic(), code) for every event the library sends

    def _event(self, kind, ctx):
        # Runs on the library's own thread: a note and nothing more.
        self.events.append((time.monotonic(), kind))

    def cameras(self):
        found = (self._Device * 16)()
        n = self.lib.Altaircam_EnumV2(found)
        return [(d.model.contents.name.decode(), d.id) for d in found[:n]]

    def open(self, ident, size=None, raw=False):
        """Open and start the stream. `size` is the library's resolution
        index (0 is the full 1280 x 960); `raw` takes the sensor's data
        without the library's conversion. Both can only be set before the
        stream starts, so a start or a setting the library refuses is a
        refusal here, with its code."""
        handle = self.lib.Altaircam_Open(ident)
        if not handle:
            refuse("The guide camera is listed but would not open: unplug it and plug it in again.")
        handle = ctypes.c_void_p(handle)
        if size is not None:
            self.lib.Altaircam_get_ResolutionNumber.argtypes = [ctypes.c_void_p]
            sizes = self.lib.Altaircam_get_ResolutionNumber(handle)
            self.lib.Altaircam_put_eSize.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            self._checked(handle, f"size {size} (of {sizes})", self.lib.Altaircam_put_eSize(handle, size))
        if raw:
            self.lib.Altaircam_put_Option.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int]
            self._checked(handle, "raw mode", self.lib.Altaircam_put_Option(handle, 0x04, 1))
        width, height = ctypes.c_int(), ctypes.c_int()
        self.lib.Altaircam_get_Size(handle, ctypes.byref(width), ctypes.byref(height))
        self.buffer = ctypes.create_string_buffer(width.value * height.value * 3)
        self.lib.Altaircam_put_AutoExpoEnable(handle, 0)
        self._callback = ctypes.CFUNCTYPE(None, ctypes.c_uint, ctypes.c_void_p)(self._event)
        self._checked(handle, "starting the stream",
                      self.lib.Altaircam_StartPullModeWithCallback(handle, self._callback, None))
        return handle, (width.value, height.value)

    def _checked(self, handle, what, hr):
        if hr < 0:
            self.lib.Altaircam_Close(handle)
            refuse(f"The guide camera's library refused {what}: {hresult(hr)}.")
        return hr

    def exposure(self, handle, seconds):
        """Set the exposure; the library's answer (below zero is a refusal)."""
        return self.lib.Altaircam_put_ExpoTime(handle, ctypes.c_uint(int(round(seconds * 1e6))))

    def gain(self, handle, percent):
        self.lib.Altaircam_put_ExpoAGain(handle, ctypes.c_ushort(int(percent)))

    def pull(self, handle):
        """The next frame as (width, height, bytes), or None if none is ready.
        This legacy library answers E_FAIL, not E_PENDING, while no frame is
        ready (6 November 2026: 585 E_FAIL to 2 S_OK in 6 s at 2 s, binned),
        so E_FAIL is not an error here. Any other code is kept in
        `pull_error` for the refusal when no frame comes."""
        width, height = ctypes.c_uint(), ctypes.c_uint()
        hr = self.lib.Altaircam_PullImage(handle, self.buffer, 8, ctypes.byref(width), ctypes.byref(height))
        if hr != 0:
            if hr & 0xFFFFFFFF not in (NOT_READY, PENDING):
                self.pull_error = hr
            return None
        return width.value, height.value, self.buffer.raw[:width.value * height.value]

    def triggered(self, handle, on):
        """Software trigger mode (option 0x0b = 1): one frame per trigger(),
        of exactly the exposure set, instead of a video stream."""
        self.lib.Altaircam_put_Option.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int]
        return self.lib.Altaircam_put_Option(handle, 0x0b, 1 if on else 0)

    def trigger(self, handle):
        self.lib.Altaircam_Trigger.argtypes = [ctypes.c_void_p, ctypes.c_ushort]
        return self.lib.Altaircam_Trigger(handle, 1)

    def speed(self, handle, value=None):
        """The camera's USB speed setting (0 is slowest); set it if given.
        Returns (speed, the most it can be)."""
        if value is not None:
            self.lib.Altaircam_put_Speed.argtypes = [ctypes.c_void_p, ctypes.c_ushort]
            self.lib.Altaircam_put_Speed(handle, value)
        now = ctypes.c_ushort()
        self.lib.Altaircam_get_Speed(handle, ctypes.byref(now))
        self.lib.Altaircam_get_MaxSpeed.argtypes = [ctypes.c_void_p]
        return now.value, self.lib.Altaircam_get_MaxSpeed(handle)

    def exposure_range(self, handle):
        """(shortest, longest) exposure in seconds the library allows."""
        lo, hi, default = ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint()
        self.lib.Altaircam_get_ExpTimeRange(handle, ctypes.byref(lo), ctypes.byref(hi), ctypes.byref(default))
        return lo.value / 1e6, hi.value / 1e6

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


NOT_READY = 0x80004005     # E_FAIL: this legacy library's answer while no frame is ready
PENDING = 0x8000000A       # E_PENDING: the newer libraries' answer for the same

# The library's events (altaircam.h), as the probe names them.
EVENTS = {0x0001: "exposure changed", 0x0004: "image", 0x0005: "still image", 0x0007: "trigger failed",
          0x0080: "error", 0x0081: "disconnected", 0x0082: "no frame timeout", 0x0085: "no packet timeout"}


def hresult(hr):
    """A library return code as its hex and name."""
    names = {0: "S_OK", 1: "S_FALSE", 0x8000FFFF: "E_UNEXPECTED", 0x80004001: "E_NOTIMPL",
             0x80070057: "E_INVALIDARG", 0x80004005: "E_FAIL", 0x8000000A: "E_PENDING",
             0x8001010E: "E_WRONG_THREAD", 0x80004003: "E_POINTER", 0x80070005: "E_ACCESSDENIED", 0x8007000E: "E_OUTOFMEMORY",
             0x800700AA: "E_BUSY", 0x8001011F: "E_TIMEOUT"}
    code = hr & 0xFFFFFFFF
    return f"0x{code:08x}" + (f" {names[code]}" if code in names else "")


DIRECTIONS = {"north": 0, "south": 1, "east": 2, "west": 3}
STOP = 4


class GuideCamera:
    """The guide camera opened: frame(seconds) gives one 8-bit frame taken
    wholly at that exposure. The first frame after a change of exposure was
    still taken at the old one (2 November 2026: at 10 ms the first read 17,
    as at 1 ms, the next 151), so frames that began before the change are
    let go."""

    def __init__(self, driver=None, clock=time.monotonic, sleep=time.sleep, role="use", run=None, size=None, raw=False,
                 speed=None):
        import guider
        # The guide camera's lock, taken before it is opened and let go only
        # after it is closed: no two commands ever use it, or its ST4 port, at once.
        self.owned = guider.Ownership(run, role).__enter__()
        try:
            self.driver = driver or Driver()
            self.clock, self.sleep = clock, sleep
            found = [c for c in self.driver.cameras() if c[0] == MODEL]
            if not found:
                refuse(f"No guide camera ({MODEL}, USB {USB_ID}) found. Is it plugged in?")
            opened = {k: v for k, v in (("size", size), ("raw", raw)) if v}
            self.handle, self.size = self.driver.open(found[0][1], **opened)
            if speed is not None:
                self.driver.speed(self.handle, speed)
            self.seconds = None
        except BaseException:
            self.owned.__exit__(None, None, None)
            raise

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
                last = getattr(self.driver, "pull_error", None)
                refuse(f"The guide camera sent no frame within {seconds + WAIT_S:.0f} s"
                       + (f" (the library last said {hresult(last)})." if last is not None else "."))
            if not got:
                self.sleep(0.02)

    def timed_frame(self, seconds, gain=None, wall=time.time):
        """One frame from the video stream and its times (UTC seconds): its
        exposure's start, midpoint and arrival, taking the readout as
        instant. frame() lets go of any frame that began before it was
        asked for, so a frame never mixes in a pulse sent before it. The
        stream, not software trigger mode: at 2 x 2 binning and USB speed 0
        it sent 149 of 150 2 s frames in 5 minutes (6 November 2026);
        trigger mode was not tried that way. A frame identical to the one
        before is let go."""
        repeats = 0
        for _ in range(DUPLICATES + 1):
            frame = self.frame(seconds, gain)
            arrived = wall()
            digest = hash(frame.tobytes())
            if digest != getattr(self, "_last_digest", None):
                self._last_digest = digest
                return frame, {"start": arrived - seconds, "mid": arrived - seconds / 2, "arrived": arrived}
            repeats += 1
        # The library has no frame number to tell a stale buffer from a new
        # frame; the same bytes this many times running is a camera fault.
        refuse(f"The guide camera sent the same frame {repeats + 1} times running.")

    def pulse(self, direction, seconds):
        """One ST4 pulse, waited out: the call returns only once the camera
        says it has ended. Still going 1 s past its length is a fault."""
        if self.driver.st4(self.handle, DIRECTIONS[direction], int(round(seconds * 1000))) < 0:
            refuse("The guide camera refused to send an ST4 pulse.")
        end = self.clock() + seconds + 1
        self.sleep(seconds)
        while self.driver.st4_busy(self.handle):
            if self.clock() > end:
                self.stop_pulse()
                refuse(f"The guide camera's ST4 pulse {direction} did not end 1 s after its {seconds:.2f} s.")
            self.sleep(0.02)

    def stop_pulse(self):
        self.driver.st4(self.handle, STOP, 0)

    def close(self):
        try:
            self.driver.close(self.handle)
        finally:
            self.owned.__exit__(None, None, None)

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


def probe(cam, exposures, trigger=False, speed=None, window=12.0, say=print):
    """When frames arrive at each exposure: the camera's frames counted for
    `window` seconds after the exposure is set, video or triggered, at the
    given USB speed. For finding why long exposures send nothing."""
    d, h = cam.driver, cam.handle
    if speed is not None:
        d.speed(h, speed)
    now, most = d.speed(h)
    say(f"USB speed {now} of {most}; {'software trigger' if trigger else 'video'} mode; "
        f"frames {cam.size[0]} x {cam.size[1]}")
    if trigger:
        say(f"  trigger mode: {d.triggered(h, True)}")
    events = getattr(d, "events", None)
    for seconds in exposures:
        hr = d.exposure(h, seconds)
        if hr is not None and hr < 0:
            say(f"{seconds:g} s: the library refused the exposure, {hresult(hr)}")
            continue
        while d.pull(h):
            pass
        began = cam.clock()
        seen = len(events) if events is not None else 0
        arrivals, levels = [], []
        if trigger:
            say(f"  trigger: {d.trigger(h)}")
        while cam.clock() - began < window:
            got = d.pull(h)
            if got:
                arrivals.append(cam.clock() - began)
                levels.append(np.frombuffer(got[2], np.uint8).mean())
                if trigger:
                    d.trigger(h)
            else:
                cam.sleep(0.01)
        gaps = np.diff([0.0] + arrivals)
        say(f"{seconds:g} s: {len(arrivals)} frames in {window:g} s"
            + (f", at {', '.join(f'{a:.2f}' for a in arrivals[:8])} s; gaps up to {gaps.max():.2f} s, "
               f"{int((gaps[1:] > 2 * seconds).sum())} over {2 * seconds:g} s; "
               f"levels {', '.join(f'{v:.1f}' for v in levels[:8])}" if arrivals else ""))
        if events is not None:
            say_events(events[seen:], began, say)


def say_events(got, began, say):
    """What the library reported in a window: a count of each event, and
    when each one that was not an image came."""
    if not got:
        say("  library events: none")
        return
    counts = {}
    for _, kind in got:
        counts[kind] = counts.get(kind, 0) + 1
    say("  library events: " + ", ".join(f"{EVENTS.get(k, hex(k))} {n}" for k, n in sorted(counts.items())))
    other = [(t - began, k) for t, k in got if k not in (0x0001, 0x0004)]
    if other:
        say("  at " + ", ".join(f"{t:.2f} s {EVENTS.get(k, hex(k))}" for t, k in other[:20])
            + (f" (and {len(other) - 20} more)" if len(other) > 20 else ""))



def wheel_test(cam, wheel, minutes=10.0, seconds=2.0, every=15.0, say=print):
    """The guide camera and the filter wheel together (autoguiding.md,
    hardware step 1): guide frames for `minutes` while the wheel turns to
    the next filter every `every` seconds, round all of them. Passes with
    at least 90 % of the frames, no gap over twice the exposure, no error
    from the camera's library, and every turn of the wheel arriving.
    True if it passed."""
    import threading
    import sxwheel
    d, h = cam.driver, cam.handle
    d.exposure(h, seconds)
    while d.pull(h):
        pass
    window = minutes * 60
    began = cam.clock()
    seen = len(getattr(d, "events", []))
    moves, stop = [], threading.Event()

    def turn():
        _, total = wheel.status()
        filt = 0
        while not stop.wait(every):
            filt = filt % max(total, 1) + 1
            t = cam.clock() - began
            try:
                wheel.move(filt)
                moves.append((t, filt, cam.clock() - began - t, None))
            except sxwheel.WheelError as e:
                moves.append((t, filt, None, str(e)))

    arrivals = []
    mover = threading.Thread(target=turn, daemon=True)
    mover.start()
    last_said = 0
    try:
        while cam.clock() - began < window:
            if d.pull(h):
                arrivals.append(cam.clock() - began)
            else:
                cam.sleep(0.01)
            if cam.clock() - began - last_said >= 60:
                last_said = cam.clock() - began
                say(f"  {last_said / 60:.0f} min: {len(arrivals)} frames, {sum(1 for m in moves if not m[3])} "
                    f"turns arrived, {sum(1 for m in moves if m[3])} failed")
    finally:
        stop.set()
        mover.join(timeout=every + sxwheel.TIMEOUT)
    expected = int(window // seconds)
    gaps = np.diff([0.0] + arrivals) if arrivals else np.array([window])
    long_gaps = int((gaps[1:] > 2 * seconds).sum()) if len(gaps) > 1 else 0
    errors = [k for _, k in getattr(d, "events", [])[seen:] if k >= 0x0080]
    failed = [m for m in moves if m[3]]
    visited = {m[1] for m in moves if not m[3]}
    say(f"guide camera: {len(arrivals)} of {expected} {seconds:g} s frames in {minutes:g} min "
        f"({100 * len(arrivals) / max(expected, 1):.0f} %), gaps up to {gaps.max():.2f} s, "
        f"{long_gaps} over {2 * seconds:g} s; library errors: {len(errors)}")
    say(f"filter wheel: {len(moves) - len(failed)} of {len(moves)} turns arrived, filters reached "
        f"{sorted(visited)}" + (f"; slowest {max(m[2] for m in moves if not m[3]):.1f} s" if visited else ""))
    for t, filt, _, why in failed[:10]:
        say(f"  at {t:.0f} s, to filter {filt}: {why}")
    passed = (len(arrivals) >= 0.9 * expected and long_gaps == 0 and not errors and not failed
              and len(visited) >= 7)
    say("PASSED" if passed else "FAILED")
    return passed


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


def pointing(args):
    """(Dec, west of the pier), read once from the handset, which must say
    the mount is tracking: always asked, whatever is given. --dec and --side
    override only the coordinates, never that check."""
    import mount
    try:
        scope = mount.Mount(watch=False)
        state = scope.state()
        dec, west = scope.radec()[1], scope.west()
    except (OSError, SystemExit) as why:
        raise interface.Refusal("INVALID_REQUEST", f"The handset could not be read ({why}): not guiding a "
                                "mount whose state is not known.")
    if state != "tracking":
        raise interface.Refusal("INVALID_REQUEST", f"The mount is {state}, not tracking: guide only while it tracks.")
    return (args.dec if args.dec is not None else dec), (args.side == "west" if args.side else west)


def guide_dry_run(args):
    import guider
    guider.motion_check()
    if args.recalibrate:
        dec = args.dec if args.dec is not None else 0.0
        ra_step, dec_step = guider.step_seconds(dec)
        print(f"would: find a guide star in {args.exposure:g} s frames; at Dec {dec:+.1f} pulse west in steps of "
              f"{ra_step * 1000:.0f} ms until it has moved {guider.CAL_DISTANCE} px or "
              f"{guider.CAL_MOST_STEPS} steps, east back the same; north until the Dec slack is taken up, "
              f"then north in {dec_step * 1000:.0f} ms steps the same way, south back, and "
              f"{guider.CAL_REVERSAL_STEPS} steps north and south to measure the slack again; keep it in "
              f"{guider.CAL_FILE}")
    if args.action == "guide":
        if not args.recalibrate:
            cal = guider.load_calibration()
            if not cal:
                cols, why = None, "no calibration kept"
            elif args.dec is None or not args.side:
                print("would: read the target's Dec and side of the pier from the handset")
                cols, why = cal["columns"], ""
            else:
                cols, why = guider.reuse(cal, args.dec, args.side == "west")
            print(f"would: reuse the calibration of {cal['made']} after a check of {guider.VERIFY_STEPS} steps "
                  "each way, recalibrating if it fails" if cols is not None else f"would: calibrate first ({why})")
        print(f"would: lock on the star and guide every {args.exposure:g} s"
              + (f" for {args.minutes:g} minutes" if args.minutes else " until Ctrl-C")
              + f"; pulses at most {guider.LONGEST_PULSE} s an axis, RA then Dec; the motion lock checked "
              "before each; stop on a fault")


def focus_aid(cam, seconds, minutes, gain=None, say=print, speak=None):
    """Hand focus of the guide scope: the guide star's size each frame, said
    aloud as a number (one decimal) and nothing else but "no stars"; printed
    with the best so far. A star under the guider's SNR to find one is not
    measured (cloud or haze gives a wrong size). The same star is followed
    while it can be; lost, the brightest is found again, and the change is
    printed. The size is guider.measure's: twice the flux-weighted mean
    radius, within about 7 % of the true half-flux diameter for a round
    star. Nothing moves but the person's hand on the focuser."""
    import guider
    if speak is None:
        from host import speak
    end, best, where = time.monotonic() + 60 * minutes, None, None
    say(f"guide scope focus: {seconds:g} s frames for {minutes:g} min; a smaller number is better")
    while time.monotonic() < end:
        frame = cam.frame(seconds, gain)
        star, why = guider.follow(frame, where) if where else (None, "")
        if star is None:
            star, why = guider.find_star(frame)
        if star is not None and star.snr < guider.SNR_FIND:
            # Too faint to measure truly (cloud, haze): no number rather than a wrong one.
            star, why = None, f"the star's SNR is {star.snr:.1f}, under {guider.SNR_FIND}"
        if star is None:
            where = None
            say(f"{time.strftime('%H:%M:%S')}  no stars: {why}")
            speak("no stars")
            continue
        if where and abs(star.x - where[0]) + abs(star.y - where[1]) > 10:
            say(f"{time.strftime('%H:%M:%S')}  another star, at {star.x:.0f}, {star.y:.0f}")
        where = (star.x, star.y)
        trend = "" if best is None else ("best" if star.hfd < best else "worse" if star.hfd > best * 1.1 else "steady")
        best = star.hfd if best is None else min(best, star.hfd)
        say(f"{time.strftime('%H:%M:%S')}  HFD {star.hfd:.1f} px  SNR {star.snr:.0f}  peak {star.peak:.0f}  "
            f"best {best:.1f}  {trend}")
        speak(f"{star.hfd:.1f}")
    say(f"best HFD {best:.1f} px" if best is not None else "no star measured")


def run_guider(args):
    import guider
    if args.action == "star":
        with GuideCamera(role="star", size=GUIDE_SIZE, speed=GUIDE_SPEED) as cam:
            shortest, longest = cam.driver.exposure_range(cam.handle)
            print(f"guide camera exposures {shortest * 1000:g} ms to {longest:g} s")
            guider.watch(cam, args.exposure, args.count, args.gain)
        return
    import uuid
    run = uuid.uuid4().hex[:8]
    desk = guider.OrderDesk(run)
    stop_order, beat = None, None
    try:
        # The camera, and its lock, held for the whole of calibrate or guide.
        with GuideCamera(role="guider", run=run, size=GUIDE_SIZE, speed=GUIDE_SPEED) as cam:
            dec, west = pointing(args)
            # Calibration and its check have a heartbeat too, as `calibrating`,
            # and take a stop before every pulse.
            beat = guider.Heartbeat({"pid": os.getpid(), "pid_start": guider.process_start(os.getpid()),
                                     "run": run, "exposure": args.exposure,
                                     "state": "calibrating", "camera_held": True},
                                    3 * args.exposure + 5 + 2 * guider.CAL_LONGEST_MS / 1000 + guider.RETRY_S).start()

            def tick():
                beat.progress()
                desk.between_pulses()
            try:
                cal = None if args.recalibrate else guider.load_calibration()
                cols, why = guider.reuse(cal, dec, west) if cal else (
                    None, "a new calibration asked for" if args.recalibrate else "no calibration kept")
                if cols is not None:
                    print(f"checking the calibration of {cal['made']}")
                    ok, why = guider.verify(cam, args.exposure, cal, cols, west, args.gain, tick=tick)
                    cols = guider.reuse(cal, dec, west)[0] if ok else None
                if cols is None:
                    if args.action == "guide":
                        print(f"calibrating: {why}")
                    cal = guider.calibrate(cam, args.exposure, dec, west, args.gain, tick=tick)
                    cols, _ = guider.reuse(cal, dec, west)
            except guider.StopRequested as stop:
                beat.stop()
                cam.stop_pulse()
                stop_order = stop.order
                beat.update(state="stopped", reason="a stop order during calibration")
            except BaseException as failure:
                beat.stop()
                cam.stop_pulse()
                beat.update(state="fault" if not isinstance(failure, KeyboardInterrupt) else "stopped",
                            reason=getattr(failure, "message", str(failure)) or type(failure).__name__)
                raise
            else:
                beat.stop()
                if args.action == "guide":
                    _, stop_order = guider.guide(cam, cols, cal, args.exposure, args.gain, args.minutes,
                                                 args.dec_one_way, run_id=run, desk=desk)
                else:
                    beat.update(state="stopped", reason="calibrated")
    finally:
        # The camera is closed and its lock let go by here: only now is a
        # stop done, and the state says the camera is no longer held.
        state = guider.read_state()
        if state and state.get("run") == run:
            state["camera_held"] = False
            guider.write_state(state)
        if stop_order:
            desk.answer(stop_order, True, "pulses stopped and the guide camera let go")
        desk.close()            # anything still waiting is answered: the guider has stopped


def show_status():
    import guider
    state = guider.read_state()
    if not state:
        held = guider.owner()
        print("no guider has run; guide camera: " + (f"held by {held.get('role')} (process {held.get('pid')})"
                                                     if held else "free"))
        return
    ok, why = guider.health(state)
    age = time.time() - (state.get("heartbeat") or 0)
    print(f"guider run {state.get('run')} (process {state.get('pid')}): {state.get('state')}"
          + (f" ({state.get('reason')})" if state.get("reason") else "")
          + f"; heartbeat {age:.0f} s ago; " + ("healthy" if ok else f"not healthy: {why}"))
    if state.get("rms"):
        print(f"RMS RA {state['rms']['ra']:.2f}\" Dec {state['rms']['dec']:.2f}\" total {state['rms']['total']:.2f}\"")
    held = guider.owner()
    print("guide camera: " + (f"held by {held.get('role')} (process {held.get('pid')}, run {held.get('run')})"
                              if held else "free"))
    if state.get("camera_held") and not held:
        print("  (the state says held, but no process holds the camera's lock: that guider has ended)")


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
    q = sub.add_parser("probe", help="when frames arrive at each exposure, video or triggered")
    q.add_argument("--exposures", default="0.1,0.5,1,2", help="seconds, comma-separated")
    q.add_argument("--trigger", action="store_true", help="software trigger mode instead of video")
    q.add_argument("--speed", type=int, help="the camera's USB speed setting (0 is slowest)")
    q.add_argument("--window", type=float, default=12.0, help="seconds to count frames at each exposure")
    q.add_argument("--size", type=int, help="the library's resolution index (0 is 1280 x 960; higher is smaller)")
    q.add_argument("--raw", action="store_true", help="the sensor's raw data, not the library's converted frames")
    k = sub.add_parser("wheeltest", help="the guide camera and the filter wheel together: frames while the wheel turns")
    k.add_argument("--minutes", type=float, default=10.0, help="how long (default 10)")
    k.add_argument("--every", type=float, default=15.0, help="seconds between turns of the wheel")
    sub.add_parser("status", help="the guider's state, and whether it can be trusted")
    t = sub.add_parser("tell", help="an order for the running guider, waited for until done")
    t.add_argument("order", choices=("pause", "resume", "relock", "stop"))
    t.add_argument("--no-wait", action="store_true", help="send it and return")
    w = sub.add_parser("star", help="find a guide star and follow it, no pulses")
    w.add_argument("--count", type=int, default=30, help="frames to follow it through")
    f = sub.add_parser("focus", help="hand focus of the guide scope: the guide star's size said aloud each frame")
    f.add_argument("--minutes", type=float, default=10.0, help="how long (default 10)")
    for name, helptext in (("calibrate", "pulse each way in steps and learn what each does"),
                           ("guide", "guide, reusing the kept calibration once checked")):
        g = sub.add_parser(name, help=helptext)
        g.add_argument("--dec", type=float, help="the target's Dec, in place of the handset's (the handset is still asked that the mount tracks)")
        g.add_argument("--side", choices=("east", "west"), help="side of the pier, in place of the handset's")
        g.add_argument("--dry-run", action="store_true", help="say what it would do, open nothing")
        if name == "guide":
            g.add_argument("--minutes", type=float, help="stop after this long (default: until Ctrl-C)")
            g.add_argument("--recalibrate", action="store_true", help="calibrate again first")
            g.add_argument("--dec-one-way", choices=("north", "south"),
                           help="correct Dec only this way, the way the polar drift pushes")
    for name in ("star", "calibrate", "guide", "focus"):
        sub.choices[name].add_argument("--exposure", type=float, default=2.0, help="guide exposure, seconds (0.5 to 4)")
        sub.choices[name].add_argument("--gain", type=int, help="the camera's gain, per cent (100 = none)")
    args = ap.parse_args(argv)
    if args.action in ("star", "calibrate", "guide", "focus") and not 0.5 <= args.exposure <= 4:
        sys.exit("The guide exposure is 0.5 to 4 s.")
    if args.action == "calibrate":
        args.recalibrate, args.minutes, args.dec_one_way = True, None, None
    try:
        if args.action == "install":
            install()
            return
        if args.action in ("calibrate", "guide") and args.dry_run:
            guide_dry_run(args)
            return
        if args.action == "status":
            show_status()
            return
        if args.action == "tell":
            import guider
            ident, run = guider.tell(args.order)
            print(f"order {args.order} {ident[:8]} sent to run {run}")
            if not args.no_wait:
                done = guider.wait_for(ident, run, order=args.order)
                print(f"{args.order}: {done['outcome']}" + (f" ({done['reason']})" if done.get("reason") else ""))
            return
        if args.action == "focus":
            with GuideCamera(role="focus", size=GUIDE_SIZE, speed=GUIDE_SPEED) as cam:
                focus_aid(cam, args.exposure, args.minutes, args.gain)
            return
        if args.action in ("star", "calibrate", "guide"):
            run_guider(args)
            return
        if args.action == "wheeltest":
            import sxwheel
            try:
                wheel = sxwheel.Wheel.open()
            except sxwheel.WheelError as e:
                refuse(str(e))
            with wheel, \
                    GuideCamera(role="wheel test", size=GUIDE_SIZE, speed=GUIDE_SPEED) as cam:
                print(f"guide camera {cam.size[0]} x {cam.size[1]}, wheel {wheel.status()}; "
                      f"{args.minutes:g} min, a turn every {args.every:g} s")
                ok = wheel_test(cam, wheel, args.minutes, every=args.every)
            sys.exit(0 if ok else 1)
        if args.action == "probe":
            with GuideCamera(role="probe", size=args.size, raw=args.raw) as cam:
                probe(cam, [float(e) for e in args.exposures.split(",")], args.trigger, args.speed, args.window)
            return
        if args.action == "pulse" and args.dry_run:
            print(f"would: read the handset, wait {args.seconds:g} s still, then pulse north, south, east, "
                  f"west for {args.seconds:g} s each through the guide camera's ST4 port, reading the handset "
                  "around each; tracking on for the test if it was off, and off again after")
            return
        if args.action == "pulse":
            import mount
            scope = mount.Mount(watch=False)
            with GuideCamera(role="ST4 test") as cam:
                cable_test(cam, scope, args.seconds)
            return
        with GuideCamera(role=args.action or "find") as cam:
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
