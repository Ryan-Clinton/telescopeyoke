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

    def timed_frame(self, seconds, gain=None, wall=time.time):
        """One triggered frame and its times (UTC seconds): the trigger, the
        exposure's midpoint and when it arrived. Software trigger mode, as
        the video stream sent no frames at 1 s or longer (6 November 2026);
        each frame starts when asked, so one never mixes in a pulse sent
        before it. A frame identical to the one before is let go."""
        if not getattr(self, "_triggering", False):
            if self.driver.triggered(self.handle, True) < 0:
                refuse("The guide camera would not go into software trigger mode.")
            self._triggering = True
            self.seconds = None
        if gain is not None:
            self.driver.gain(self.handle, gain)
        if seconds != self.seconds:
            self.driver.exposure(self.handle, seconds)
            self.seconds = seconds
        while self.driver.pull(self.handle):        # anything left over from before
            pass
        repeats = 0
        for _ in range(DUPLICATES + 1):
            if self.driver.trigger(self.handle) < 0:
                refuse("The guide camera refused a trigger.")
            started = wall()
            asked = self.clock()
            while True:
                got = self.driver.pull(self.handle)
                if got:
                    break
                if self.clock() - asked > seconds + WAIT_S:
                    refuse(f"The guide camera sent no frame within {seconds + WAIT_S:.0f} s of a trigger.")
                self.sleep(0.02)
            arrived = wall()
            width, height, data = got
            frame = np.frombuffer(data, np.uint8).reshape(height, width).copy()
            digest = hash(data)
            if digest != getattr(self, "_last_digest", None):
                self._last_digest = digest
                return frame, {"start": started, "mid": started + seconds / 2, "arrived": arrived}
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


def probe(cam, exposures, trigger=False, speed=None, window=12.0, say=print):
    """When frames arrive at each exposure: the camera's frames counted for
    `window` seconds after the exposure is set, video or triggered, at the
    given USB speed. For finding why long exposures send nothing."""
    d, h = cam.driver, cam.handle
    if speed is not None:
        d.speed(h, speed)
    now, most = d.speed(h)
    say(f"USB speed {now} of {most}; {'software trigger' if trigger else 'video'} mode")
    if trigger:
        say(f"  trigger mode: {d.triggered(h, True)}")
    for seconds in exposures:
        d.exposure(h, seconds)
        while d.pull(h):
            pass
        began = cam.clock()
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
            + (f", at {', '.join(f'{a:.2f}' for a in arrivals[:8])} s; gaps up to {gaps.max():.2f} s; "
               f"levels {', '.join(f'{v:.1f}' for v in levels[:8])}" if arrivals else ""))


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


def run_guider(args):
    import guider
    if args.action == "star":
        guider.refuse_if_owned("star")
        with GuideCamera() as cam:
            shortest, longest = cam.driver.exposure_range(cam.handle)
            print(f"guide camera exposures {shortest * 1000:g} ms to {longest:g} s")
            guider.watch(cam, args.exposure, args.count, args.gain)
        return
    import uuid
    run = uuid.uuid4().hex[:8]
    # The camera is held for the whole of calibrate or guide: one guider at a time.
    with guider.Ownership(run), GuideCamera() as cam:
        dec, west = pointing(args)
        # Calibration and its check have a heartbeat too, as `calibrating`.
        beat = guider.Heartbeat({"pid": os.getpid(), "run": run, "exposure": args.exposure,
                                 "state": "calibrating"}, 3 * args.exposure + 5 + 2 * guider.CAL_LONGEST_MS / 1000
                                + guider.RETRY_S).start()
        try:
            cal = None if args.recalibrate else guider.load_calibration()
            cols, why = guider.reuse(cal, dec, west) if cal else (
                None, "a new calibration asked for" if args.recalibrate else "no calibration kept")
            if cols is not None:
                print(f"checking the calibration of {cal['made']}")
                ok, why = guider.verify(cam, args.exposure, cal, cols, west, args.gain, tick=beat.progress)
                cols = guider.reuse(cal, dec, west)[0] if ok else None
            if cols is None:
                if args.action == "guide":
                    print(f"calibrating: {why}")
                cal = guider.calibrate(cam, args.exposure, dec, west, args.gain, tick=beat.progress)
                cols, _ = guider.reuse(cal, dec, west)
        except BaseException as failure:
            beat.stop()
            cam.stop_pulse()
            beat.update(state="fault" if not isinstance(failure, KeyboardInterrupt) else "stopped",
                        reason=getattr(failure, "message", str(failure)) or type(failure).__name__)
            raise
        beat.stop()
        if args.action == "guide":
            guider.guide(cam, cols, cal, args.exposure, args.gain, args.minutes, args.dec_one_way, run_id=run)
        else:
            beat.update(state="stopped", reason="calibrated")


def show_status():
    import guider
    state = guider.read_state()
    if not state:
        print("no guider has run")
        return
    ok, why = guider.health(state)
    age = time.time() - (state.get("heartbeat") or 0)
    print(f"guider run {state.get('run')} (process {state.get('pid')}): {state.get('state')}"
          + (f" ({state.get('reason')})" if state.get("reason") else "")
          + f"; heartbeat {age:.0f} s ago; " + ("healthy" if ok else f"not healthy: {why}"))
    if state.get("rms"):
        print(f"RMS RA {state['rms']['ra']:.2f}\" Dec {state['rms']['dec']:.2f}\" total {state['rms']['total']:.2f}\"")
    if state.get("order"):
        o = state["order"]
        print(f"last order: {o.get('order')} #{o.get('n')} {o.get('outcome')}"
              + (f" ({o.get('reason')})" if o.get("reason") else ""))


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
    sub.add_parser("status", help="the guider's state, and whether it can be trusted")
    t = sub.add_parser("tell", help="an order for the running guider, waited for until done")
    t.add_argument("order", choices=("pause", "resume", "relock", "stop"))
    t.add_argument("--no-wait", action="store_true", help="send it and return")
    w = sub.add_parser("star", help="find a guide star and follow it, no pulses")
    w.add_argument("--count", type=int, default=30, help="frames to follow it through")
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
    for name in ("star", "calibrate", "guide"):
        sub.choices[name].add_argument("--exposure", type=float, default=2.0, help="guide exposure, seconds (0.5 to 4)")
        sub.choices[name].add_argument("--gain", type=int, help="the camera's gain, per cent (100 = none)")
    args = ap.parse_args(argv)
    if args.action in ("star", "calibrate", "guide") and not 0.5 <= args.exposure <= 4:
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
            number, run = guider.tell(args.order)
            print(f"order {args.order} #{number} sent to run {run}")
            if not args.no_wait:
                done = guider.wait_for(number, run, order=args.order)
                print(f"{args.order}: {done['outcome']}")
            return
        if args.action in ("star", "calibrate", "guide"):
            run_guider(args)
            return
        import guider
        guider.refuse_if_owned({"probe": "probe", "pulse": "ST4 test", "snap": "snap"}.get(args.action, "use"))
        if args.action == "probe":
            with GuideCamera() as cam:
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
