"""The telescope camera through Altair's own library, with no INDI server.

    with AltairCamera(gain=300) as cam:
        data, header = cam.frame(2.0)      # raw 12-bit Bayer mosaic, or plain grey from a mono camera

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
from collections import deque
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
USB3 = 0x40            # ALTAIRCAM_FLAG_USB30
FAN = 0x10000          # ALTAIRCAM_FLAG_FAN
MONO = 0x10            # ALTAIRCAM_FLAG_MONO: no colour filters on the sensor (the 183M)
TEC = 0x80             # ALTAIRCAM_FLAG_TEC: a cooler with a target temperature
# The cooler (docs/mono-upgrade.md, item 2), on a camera with a TEC only.
ON_TARGET = 0.5        # °C: a frame further than this from the target is kept but flagged (TY_ONTGT)
TEC_READY = 1.0        # °C: a run keeps no frames until the sensor is this close to its target
COOL_WAIT_S = 900      # the longest a run waits for the sensor to get there, after the ramp's own time
# Cooling slowly, from the camera's owner (years with it): never below -5 °C,
# where this sensor gains nothing, and down a step at a time, never one jump,
# or the sensor's window can frost: 0.5 °C every 30 s, 1 °C a minute, so
# about 20 minutes from a sensor at 15 °C to -5 °C.
TEC_LOWEST = -5.0
RAMP_STEP_C, RAMP_EVERY_S = 0.5, 30.0
COOL_POLL_S = 5.0
FULL_POWER = 0.95      # a share of the cooler's most voltage taken as all it has
STUCK_S = 180          # at full power this long with the sensor no colder: it cannot reach the target
WARM_STEP_C, WARM_EVERY_S, WARM_STEPS_MOST = 3.0, 60.0, 15   # the warm-up at the end of a run
WARM_MOST_S = 600      # the longest the warm-up takes, however it ends: then the cooler goes off regardless
BUFFER = 0x1000000     # ALTAIRCAM_FLAG_BUFFER: a frame buffer of some size in the camera
DDR = 0x2000000        # ALTAIRCAM_FLAG_DDR: one big enough for a whole frame
# Settings that could stop long frames while short ones arrive: a low-power
# mode the camera enters above a set exposure, and the library's own
# give-ups when no packet or no frame comes in time (0: off).
WATCHED = (("low_power", "LOW_POWERCONSUMPTION"), ("low_power_above_ms", "LOW_POWER_EXPOTIME"),
           ("no_packet_timeout_ms", "NOPACKET_TIMEOUT"), ("no_frame_timeout_ms", "NOFRAME_TIMEOUT"))


def wait_for(seconds):
    """Longest wait for a frame. Measured through the SDK: a 16 s frame
    comes back after about 20.5 s, and speed 0 in the fault gathers for
    1.27 times the time asked (docs/camera-fault.md), so 10 s more than
    half again the exposure is ample. It was the INDI route's 12 + 6 x
    the exposure, 108 s for 16 s: on 1 November 2026 a jam took about seven
    minutes over four tries to be said, while the person waited outside."""
    return 10 + 1.5 * seconds


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


REPLUG_WAIT = 15.0        # seconds for the camera to come back after the library's replug


def replug(lib, device, wait=REPLUG_WAIT, sleep=time.sleep):
    """The library's replug: the camera dropped from USB and found again, as
    if its lead were pulled and pushed back. On 30 October 2026, behind a
    hub, a lost frame left the camera refusing its first setting (0x8000ffff)
    at every speed, until it was replugged. True once a camera is back."""
    try:
        if lib.Altaircam.Replug(device.id) <= 0:
            return False
    except (AttributeError, lib.HRESULTException):
        return False
    end = time.monotonic() + wait
    while time.monotonic() < end:
        if cameras(lib):
            return True
        sleep(0.5)
    return False


def choose(lib, wanted=None, profile=None):
    """The one camera to use. None plugged in is a refusal; so are several,
    unless config.toml names one by its serial number, or `profile` (a
    camera profile asked for by --camera or [imaging] camera) matches just
    one of them. Never the first of several: the wrong camera would give
    frames that look plausible."""
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
    if profile and "cameras" in SETTINGS:
        fits_it = [d for d in found if config.match_camera(d.displayname, serials[d.id], SETTINGS) == profile]
        if len(fits_it) == 1:
            return fits_it[0]
        raise Refusal("CAMERA_NOT_CONNECTED",
                      f"The {profile} profile was asked for, and {'none' if not fits_it else 'more than one'} "
                      f"of the cameras plugged in matches it: {listed}.")
    raise Refusal("CAMERA_NOT_CONNECTED",
                  f"{len(found)} cameras are plugged in: {listed}. Name the one to use with "
                  + ("--camera NAME (ty --camera 183m ...) or camera = \"NAME\" under [imaging], or "
                     if "cameras" in SETTINGS else "")
                  + "serial = \"...\" under [camera] in config.toml.")


def matched_profile(device, serial):
    """The camera profile the opened camera is (config.match_camera), with
    what to do about it: (name, profile settings). Refused, never guessed,
    when it matches no profile, or is not the camera asked for. A camera
    other than the one this command started with is remembered for the
    next command and refused for this one, whose figures (focal length,
    darks, focus) were worked out for the other."""
    using = SETTINGS["camera"]
    if "cameras" not in SETTINGS:          # settings made by hand (the tests): one camera, as it was
        return using.get("name", config.LEGACY_CAMERA), using
    found = config.match_camera(device.displayname, serial, SETTINGS)
    if found is None:
        raise Refusal("CAMERA_NOT_CONNECTED",
                      f"{device.displayname} (serial {serial or 'unreadable'}) is not a camera with a profile "
                      f"in config.toml, which has: {', '.join(sorted(SETTINGS['cameras']))}. Add a "
                      "[cameras.NAME] table for it (model = part of the name above).")
    if found != using["name"]:
        chosen = using.get("chosen_by", "default")
        if chosen in ("--camera", "setting"):
            raise Refusal("CAMERA_NOT_CONNECTED",
                          f"The {using['name']} was asked for (by {'--camera' if chosen == '--camera' else '[imaging] camera'}), "
                          f"but the camera plugged in is {device.displayname}, the {found}.")
        remember(found)
        raise Refusal("CAMERA_NOT_CONNECTED",
                      f"The {found} is plugged in, not the {using['name']} this command started with. The {found} "
                      "is remembered now: run the command again.")
    if len(SETTINGS["cameras"]) > 1:
        remember(found)
    return found, using


def remember(name):
    """Keep which profile the camera Altair's library opened matched, for the
    commands that run before it opens (config.remembered_camera)."""
    if config.remembered_camera() == name:
        return
    import records
    records.write(config.DATA / config.REMEMBERED_CAMERA, {"camera": name, "when": time.time()})


def _terminated(signum, frame):
    raise KeyboardInterrupt(f"stopped by signal {signum}")


def stop_on_terminate():
    """A plain kill (SIGTERM) ends a command the way Ctrl-C does, so the
    camera is closed and the mount stopped on the way out. Without this a
    kill ends Python at once and nothing is tidied up. Only from the main
    thread, and never over a handler the command set itself."""
    import signal
    if threading.current_thread() is not threading.main_thread() or not hasattr(signal, "SIGTERM"):
        return
    if signal.getsignal(signal.SIGTERM) in (signal.SIG_DFL, None):
        signal.signal(signal.SIGTERM, _terminated)


class AltairCamera:
    def __init__(self, gain=300):
        self.gain = gain
        self.lib = sdk()
        self.handle = None
        # What the library's own thread tells us, and what we are waiting for.
        self._changed = threading.Condition()
        self._waiting = False     # an exposure has been triggered and not yet collected
        self._ready = 0           # frames that have arrived for it and not been pulled
        self._failure = None      # or the camera said why it will not
        self._shifted = None      # whether the 12 bits arrive at the top of the 16, once certain
        self.exposures = 0        # how many have been triggered
        self.binning = 1          # what the frames now arriving are binned by
        self.refuses_binning = False     # asked once and it failed: not asked again
        self.probed = False       # camera_probe.py has run on this camera (once is enough)
        self._forget_clock()
        # One command at a time, and a second one told which (cameralock.py).
        from cameralock import CameraLock
        self.lock = CameraLock()
        stop_on_terminate()
        try:
            self._open()
        except BaseException:
            self.lock.release()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        self.lock.release()

    # --- opening and closing ---------------------------------------------------

    def _forget_clock(self):
        self.clock = None             # True once the camera's frame stamps have proved usable
        self._last = None             # (stamp, arrival) of the last good frame
        self._offsets = deque(maxlen=20)   # arrival minus stamp, for recent good frames

    def _open(self, replugged=False):
        lib, camera = self.lib, SETTINGS["camera"]
        asked = camera.get("name") if camera.get("chosen_by") in ("--camera", "setting") else None
        device = choose(lib, camera.get("serial"), asked)
        self.name = device.displayname
        handle = lib.Altaircam.Open(device.id)
        if handle is None:
            raise Refusal("CAMERA_NOT_CONNECTED",
                          f"{self.name} would not open. Only one program can use the camera: "
                          "close AltairCapture, SharpCap or anything else that has it.")
        self.handle = handle
        try:
            serial = handle.SerialNumber()
        except Exception:
            serial = ""
        try:
            self.profile_name, self.profile = matched_profile(device, serial)
        except Refusal:
            self.close()
            raise
        camera = self.profile
        try:
            handle.put_AutoExpoEnable(0)
            handle.put_Option(lib.ALTAIRCAM_OPTION_RAW, 1)        # only settable before starting
            # The sensor's full depth, not its 8-bit mode. Each value still
            # arrives in a 16-bit number, whatever the depth.
            handle.put_Option(lib.ALTAIRCAM_OPTION_BITDEPTH, 1)
            handle.put_eSize(0)                                   # the first size listed is the full sensor
            handle.put_Option(lib.ALTAIRCAM_OPTION_BINNING, 1)
            self.binning = 1
            if camera.get("readout_speed") is not None:
                handle.put_Speed(int(camera["readout_speed"]))
            # The black level and fan from this camera's settings, every time it
            # opens: the camera does not keep them (4 November 2026: the 183M's
            # offset of 80 was not in its darks, which sat at the default 17).
            if camera.get("offset") is not None:
                handle.put_Option(lib.ALTAIRCAM_OPTION_BLACKLEVEL, int(camera["offset"]))
            if camera.get("fan") in ("on", "off") and hasattr(lib, "ALTAIRCAM_OPTION_FAN"):
                handle.put_Option(lib.ALTAIRCAM_OPTION_FAN, -1 if camera["fan"] == "on" else 0)
            handle.put_Option(lib.ALTAIRCAM_OPTION_TRIGGER, 1)    # one exposure per request
            self.width, self.height = self._size()
            fourcc, self.bits = handle.get_RawFormat()
            self.pattern = struct.pack("<I", fourcc).decode("ascii", "replace")
            # A mono sensor's raw format is "YYYY" and its model says MONO:
            # its frames have no colour pattern and carry no BAYERPAT.
            self.flags = int(getattr(getattr(device, "model", None), "flag", 0) or 0)
            self.mono = self.pattern.upper() == "YYYY" or bool(self.flags & MONO)
            # A camera opened again to recover a lost frame keeps any cooling
            # already under way (set from config, or by cool() as a test does):
            # 4 November 2026, a reopen mid-test left no target, so the warm-up
            # had nothing to do and the cooler went off cold.
            cooling = self.target if getattr(self, "target", None) is not None else camera.get("tec_target")
            self.target = None
            if not hasattr(self, "ambient"):
                # Before the cooler starts, the first time only (not when opened
                # again after a jam): what warm_up() brings the sensor back to.
                self.ambient = self.temperature()
            if cooling is not None and self.flags & TEC:
                # A cooler that will not take its target, or a sensor whose
                # temperature cannot be read back, stops here: frames at a
                # temperature nobody knows match no dark (docs/calibration.md).
                try:
                    self.cool(cooling)
                except lib.HRESULTException as problem:
                    self.close()
                    raise CameraError(f"the cooler would not be set to {float(cooling):g} °C: "
                                      f"{_reason(problem)}. No frames are kept at a temperature no dark matches.")
                except CameraError:
                    self.close()
                    raise
            handle.put_ExpoAGain(self.gain)
            # The library keeps only a pointer to the callback. Holding it on
            # this object keeps it alive for as long as the camera can call it.
            self._callback = self._event
            handle.StartPullModeWithCallback(self._callback, self)
        except lib.HRESULTException as problem:
            self.close()
            if not replugged and replug(lib, device):
                return self._open(replugged=True)
            raise CameraError(f"the camera would not be set up: {_reason(problem)}"
                              + (" (even after a replug by the library)" if replugged else ""))

    def _size(self):
        """(width, height) of the frames the camera will now send. With
        binning on, that is the library's "final" size, not the sensor's."""
        return getattr(self.handle, "get_FinalSize", self.handle.get_Size)()

    def use(self, profile):
        """Set the camera up for what its frames are for (a name in
        camera.PROFILES) and return the binning now in effect. A camera that
        will not bin stays on the full sensor and the answer is 1."""
        from camera import PROFILES
        lib, handle, wanted = self.lib, self.handle, PROFILES[profile]
        if wanted == self.binning or (wanted > 1 and self.refuses_binning):
            return self.binning
        try:
            # The frame's size changes, so the stream is stopped around it.
            handle.Stop()
            handle.put_Option(lib.ALTAIRCAM_OPTION_BINNING, wanted)   # 2: each 2x2 block added up
            size = self._size()
            if wanted > 1 and size == (self.width, self.height):
                raise CameraError("the frame's size did not change")
            self.width, self.height = size
            self.binning = wanted
            handle.StartPullModeWithCallback(self._callback, self)
        except (CameraError, lib.HRESULTException):
            self.refuses_binning = True
            self.close()
            self._open()      # on the full sensor, as it always was
        return self.binning

    def _cycles_power(self):
        return bool(SETTINGS["camera"].get("power_cycle_on_jam")) and not host.WINDOWS

    def _power_cycle(self):
        """Cut the closed camera's power at the hub and give it back. True
        once it is on USB again; False when that is not set up or not
        possible, said, so the caller opens it again as before."""
        if not self._cycles_power():
            return False
        import usbpower
        say = lambda line: print(f"camera: {line}", file=sys.stderr, flush=True)
        try:
            return usbpower.cycle(say=say)["back"]
        except usbpower.PowerError as problem:
            say(f"could not cut its power: {problem}")
            return False

    def close(self):
        handle, self.handle = self.handle, None
        if handle is None:
            return
        for step in (lambda: handle.Trigger(0), handle.Stop, handle.Close):
            try:
                step()
            except Exception:
                pass   # it is being closed whatever it says

    def settings(self, fan=None, offset=None, speed=None):
        """As camera.Camera.settings: the fan ("on" or "off"), the black
        level and the readout speed; None leaves each as it is. 23 October
        2026: 2 s frames arrived at speeds 0 and 1 and never at 2."""
        lib, handle = self.lib, self.handle
        if speed is not None:
            handle.put_Speed(int(speed))
        if fan in ("on", "off"):
            handle.put_Option(lib.ALTAIRCAM_OPTION_FAN, -1 if fan == "on" else 0)   # -1: its usual speed
        if offset is not None:
            handle.put_Option(lib.ALTAIRCAM_OPTION_BLACKLEVEL, int(offset))

    def cool(self, degrees, clock=time.monotonic):
        """Turn the cooler on and start the slow way down to the sensor's
        target, in °C: never one jump, which can frost the sensor's window
        (the camera's owner, who has used it for years). The set point starts
        RAMP_STEP_C below the sensor's own temperature now and ramp() takes
        it down a step every RAMP_EVERY_S (1 °C a minute, so about 20 minutes
        from a warm sensor); a camera opened again with its sensor already
        near the target (a re-centre, a jam) gets there in a step or two, not
        a fresh 20 minutes. Never below TEC_LOWEST. Nothing on a camera
        without a cooler (the 183C), so one config.toml suits both."""
        if not self.flags & TEC:
            return False
        degrees = float(degrees)
        if degrees < TEC_LOWEST:
            raise CameraError(f"a cooler target of {degrees:g} °C is below {TEC_LOWEST:g} °C, the lowest this "
                              "sensor is ever set to (no gain below it): set tec_target to -5 or warmer")
        lib, handle = self.lib, self.handle
        option = getattr(lib, "ALTAIRCAM_OPTION_TEC", None)
        if option is not None:
            handle.put_Option(option, 1)
        now = self.temperature()
        if now is None:
            raise CameraError("the cooler is on but the sensor's temperature cannot be read, so no dark could be "
                              "matched to the frames")
        if getattr(self, "ambient", None) is None:
            # The camera may not say its temperature the moment it opens: then
            # the sensor's temperature as cooling starts is what warm_up()
            # brings it back to (4 November 2026: with none, the warm-up was
            # skipped and the cooler went off at -0.7 °C).
            self.ambient = now
        level = degrees if now - degrees <= RAMP_STEP_C else now - RAMP_STEP_C
        self._set_point(level)
        self.target, self.level, self._stepped = degrees, level, clock()
        return True

    def _set_point(self, degrees):
        """The cooler's set point now, read back where the library can say it
        (ALTAIRCAM_OPTION_TECTARGET): a set point the camera does not hold
        stops the run."""
        lib, handle = self.lib, self.handle
        tenths = int(round(float(degrees) * 10))      # the library counts tenths of a degree
        handle.put_Temperature(tenths)
        readback = getattr(lib, "ALTAIRCAM_OPTION_TECTARGET", None)
        if readback is not None:
            held = handle.get_Option(readback)
            if held != tenths:
                raise CameraError(f"the cooler was set to {tenths / 10:g} °C and says its target is "
                                  f"{held / 10:g} °C")

    def ramp(self, clock=time.monotonic):
        """One step further down towards the target when RAMP_EVERY_S has
        passed since the last; True once the set point is the target."""
        if self.target is None or not self.flags & TEC:
            return True
        if self.level > self.target and clock() - self._stepped >= RAMP_EVERY_S:
            level = max(self.target, self.level - RAMP_STEP_C)
            try:
                self._set_point(level)
            except self.lib.HRESULTException as problem:
                raise CameraError(f"the cooler would not take its next step to {level:g} °C: {_reason(problem)}")
            self.level, self._stepped = level, clock()
        return self.level <= self.target

    def temperature(self):
        """The sensor's temperature in °C as the camera reports it; None on a
        camera without a cooler, or when it will not say."""
        if not self.flags & TEC or not hasattr(self.handle, "get_Temperature"):
            return None
        try:
            return self.handle.get_Temperature() / 10
        except Exception:
            return None

    def tec_power(self):
        """How hard the cooler is working: (volts, share of its most) from the
        library's ALTAIRCAM_OPTION_TEC_VOLTAGE and _TEC_VOLTAGE_MAX, both in
        tenths of a volt. None without a cooler, or when it will not say."""
        lib = self.lib
        now, most = (getattr(lib, f"ALTAIRCAM_OPTION_TEC_VOLTAGE{s}", None) for s in ("", "_MAX"))
        if not self.flags & TEC or now is None or most is None:
            return None
        try:
            volts, top = self.handle.get_Option(now) / 10, self.handle.get_Option(most) / 10
        except Exception:
            return None
        return volts, (volts / top if top > 0 else None)

    def settle(self, say=print, sleep=time.sleep, clock=time.monotonic, wait=None):
        """Take the cooler's set point down its ramp (cool(), ramp()) and wait
        until the ramp has reached the target and the sensor is within
        TEC_READY of it, so a run keeps no frame at the wrong temperature (its
        darks would not match). At once on a camera with no cooler or no
        target: the 183C. A cooler at full power whose sensor has stopped
        getting colder once the ramp is done, one not there within `wait`
        seconds (the ramp's own time plus COOL_WAIT_S), or a sensor whose
        temperature cannot be read, says so with the figures and stops the
        run (CameraError): never frames at a temperature no dark suits."""
        if self.target is None or not self.flags & TEC:
            return True
        if wait is None:
            wait = (self.level - self.target) / RAMP_STEP_C * RAMP_EVERY_S + COOL_WAIT_S
        end, said, best, since = clock() + wait, None, None, clock()
        self._stepped = clock()          # the step cool() set counts from here, on this clock
        while True:
            ramped = self.ramp(clock)
            degrees, power = self.temperature(), self.tec_power()
            if degrees is None:
                raise CameraError(f"the sensor's temperature cannot be read while cooling to {self.target:g} °C: "
                                  "no frames are kept at a temperature no dark matches")
            share = power[1] if power and power[1] is not None else None
            if ramped and abs(degrees - self.target) <= TEC_READY:
                say(f"camera: sensor at {degrees:.1f} °C, its target {self.target:g} °C")
                return True
            if not ramped or best is None or degrees < best - 0.2:
                best, since = degrees, clock()
            usage = f", cooler at {100 * share:.0f}% of its power" if share is not None else ""
            if ramped and share is not None and share >= FULL_POWER and clock() - since >= STUCK_S:
                raise CameraError(f"the cooler is at full power and the sensor has stayed at {degrees:.1f} °C, "
                                  f"{degrees - self.target:.1f} °C above its target of {self.target:g} °C: it cannot "
                                  "reach it tonight. Set a warmer tec_target for this camera, and take darks at it.")
            if clock() >= end:
                raise CameraError(f"the sensor did not reach {self.target:g} °C within {wait / 60:.0f} min: "
                                  f"it is at {degrees:.1f} °C{usage}")
            if said is None or clock() - said >= 60:
                step = "" if ramped else f", set point {self.level:g} °C stepping down {RAMP_STEP_C:g} °C every {RAMP_EVERY_S:g} s"
                say(f"camera: cooling, sensor at {degrees:.1f} °C, target {self.target:g} °C{step}{usage}; "
                    "no frames kept until it is within 1 °C")
                said = clock()
            sleep(COOL_POLL_S)

    def warm_up(self, say=print, sleep=time.sleep, clock=time.monotonic, most=None):
        """At the end of a run: step the cooler's target up WARM_STEP_C every
        WARM_EVERY_S towards the temperature the sensor had before it was
        cooled, then turn the cooler off, rather than cutting it cold (the
        camera stops its cooler when it is closed), to spare the sensor the
        shock and the window condensation. Nothing on a camera with no cooler
        or no target, or a sensor already within a step of where it began.
        Bounded: after `most` seconds (WARM_MOST_S), a step the camera
        refuses, or any failure part way, the cooler is turned off regardless.
        Never raises, so a run that failed can warm on its way out without its
        own error being hidden."""
        if self.target is None or not self.flags & TEC or self.handle is None:
            return False
        lib, handle = self.lib, self.handle
        most = WARM_MOST_S if most is None else most
        began = clock()
        try:
            degrees = self.temperature()
            if degrees is None or self.ambient is None:
                say(f"camera: the warm-up cannot tell the sensor's temperature "
                    f"({'now' if degrees is None else 'from before cooling'}); the cooler goes off now")
            if degrees is not None and self.ambient is not None and degrees < self.ambient - WARM_STEP_C:
                level = max(self.level, degrees)
                say(f"camera: warming the sensor from {degrees:.1f} °C to {self.ambient:.1f} °C, "
                    f"{WARM_STEP_C:g} °C a minute, before the cooler is turned off")
                for _ in range(WARM_STEPS_MOST):
                    if level >= self.ambient:
                        break
                    if clock() - began + WARM_EVERY_S > most:
                        say(f"camera: the warm-up has had its {most / 60:g} minutes; the cooler goes off with the "
                            f"sensor near {level:.1f} °C")
                        break
                    level = min(self.ambient, level + WARM_STEP_C)
                    try:
                        handle.put_Temperature(int(round(level * 10)))
                    except lib.HRESULTException:
                        break
                    sleep(WARM_EVERY_S)
        except Exception as problem:             # a failing camera still has its cooler turned off
            say(f"camera: the warm-up stopped ({problem}); the cooler goes off now")
        finally:
            option = getattr(lib, "ALTAIRCAM_OPTION_TEC", None)
            if option is not None:
                try:
                    handle.put_Option(option, 0)
                except Exception:
                    pass
            self.target = None
        return True

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
                    self._ready += 1
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

    def _expose(self, seconds, wait=None, set_time=True):
        lib, handle = self.lib, self.handle
        if set_time:        # False only for camera_probe.order_test: the time is set before the speed there
            handle.put_ExpoTime(max(1, round(seconds * 1e6)))
        handle.put_ExpoAGain(self.gain)
        with self._changed:
            self._waiting, self._ready, self._failure = False, 0, None
        self._discard()
        with self._changed:
            self.exposures += 1
            self._waiting = True
        started, began = datetime.now(timezone.utc), time.perf_counter()
        self.triggered = began      # for timing a light against the trigger (camera_probe.pulsed)
        handle.Trigger(1)
        give_up = began + (wait or wait_for(seconds))
        self.early = []         # seconds after the trigger of each frame too soon to be this one
        self.early_frame = None  # the last of them, kept to be looked at, never returned
        self.back_s = None      # seconds from the trigger to the frame kept
        while True:
            with self._changed:
                arrived = self._changed.wait_for(lambda: self._ready or self._failure,
                                                 timeout=max(0, give_up - time.perf_counter()))
                failure = self._failure
                if arrived and not failure:
                    self._ready -= 1      # one frame is there to be pulled
            if failure or not arrived:
                break
            # Is it ours? No exposure can be back before its shutter has
            # closed, and the camera's own clock says when a frame was taken.
            # A late frame from an earlier exposure is taken out of the way
            # and the wait goes on for ours.
            landed = time.perf_counter()
            data, info = self._pull()
            # (The 50 ms is slack for timing; a focusing exposure is shorter.)
            older = self._older(info, began)
            if landed - began >= 0.9 * seconds - 0.05 and not older:
                self._learn(info, landed)
                self.back_s = round(landed - began, 2)
                break
            if not older:
                # 31 October 2026: in the fault, a 16 s frame came back after
                # 10.3 s instead of the usual 20.5, at speeds 1 and 2 only, and
                # was turned away here; it is named, not taken, and kept aside
                # so its light can be measured against a good frame's.
                self.early.append(round(landed - began, 1))
                self.early_frame = data
        with self._changed:
            self._waiting = False
        if failure or not arrived:
            # Cancel it and empty the pipes, so a frame that turns up late
            # cannot be taken for the next one.
            try:
                handle.Trigger(0)
            except lib.HRESULTException:
                pass
            self._discard()
            soon = (f"; one came back after {self.early[0]:g} s, too soon to be it"
                    if self.early else "")
            raise CameraError(failure or f"no frame within {wait or wait_for(seconds):.0f} s "
                                         f"of a {seconds:g} s exposure{soon}")
        return self._normalise(data), started

    def _pull(self):
        """The frame the library is holding, as it gave it, and what the
        camera says about it (its sequence number and timestamp)."""
        data = np.empty((self.height, self.width), dtype=np.uint16)
        # The wrapper declares the buffer as a C string pointer, so the array's
        # own memory is handed over as one, by its address; the library writes
        # the frame into it. Not ctypes.cast, whose result and source refer to
        # each other: every frame then waits for the garbage collector, and on
        # 30 October 2026 a Moon video's 24 MB frames piled up to 18.5 GB in
        # 1018 frames before the system killed it.
        buffer = ctypes.c_char_p(data.ctypes.data)
        info = self.lib.AltaircamFrameInfoV3()
        self.handle.PullImageV3(buffer, 0, 16, -1, info)   # -1: rows packed with no padding
        return data, info

    # The camera stamps each frame with its own clock, in microseconds from a
    # start nobody documents. Three things make it usable. The gap between
    # two frames' stamps must match the gap between their arrivals here, or
    # it is not a clock we understand and it is never used. The smallest
    # (arrival - stamp) seen ties the camera's clock to this computer's. And
    # a stamp lower than the last good one means the clock has started again,
    # so what was learned is dropped.

    def _learn(self, info, landed):
        """Note a frame known to be good, to tie the camera's clock to ours."""
        stamp = getattr(info, "timestamp", 0) / 1e6
        if not stamp or self.clock is False:
            return
        if self._last and stamp < self._last[0]:
            self._forget_clock()
        if self._last:
            gap, real = stamp - self._last[0], landed - self._last[1]
            if real >= 1.5:      # closer together than this, the two gaps say nothing
                if abs(gap - real) > 1 + 0.1 * real:
                    self.clock = False      # leave it out for good
                    return
                self.clock = True
        self._last = (stamp, landed)
        # From recent frames only, so two clocks that drift apart over a
        # long night never make a good frame look old.
        self._offsets.append(landed - stamp)

    def _older(self, info, began):
        """True if the camera's clock says this frame was taken before the
        exposure now being waited for was even asked for."""
        stamp = getattr(info, "timestamp", 0) / 1e6
        if not self.clock or not stamp or stamp < self._last[0]:
            return False
        # The estimate can only be late, by the quickest delivery seen, so a
        # frame it puts before the trigger really was taken before it.
        return stamp + min(self._offsets) < began - 0.05

    def _normalise(self, data):
        """Values from 0 to WHITE. The library may hand the sensor's 12 bits
        over at the top of each 16-bit number; then the bottom four bits of
        every value are empty, which never happens in a real frame otherwise."""
        spare = 16 - self.bits
        if spare <= 0:
            return data
        shifted = self._shifted
        if shifted is None:
            # Two things settle it for good: a value above WHITE can only be
            # shifted up, and a value using the bottom bits cannot be. A dark
            # frame may show neither; it is judged by itself, by its empty
            # bottom bits, and the question stays open for the next frame.
            if data.max() > WHITE:
                shifted = self._shifted = True
            elif np.bitwise_or.reduce(data, axis=None) & ((1 << spare) - 1):
                shifted = self._shifted = False
            else:
                shifted = bool(data.any())
        if shifted:
            data >>= spare
        return data

    def frame(self, seconds):
        """One exposure as (uint16 Bayer mosaic, FITS header). An exposure
        that fails is tried once more, then twice more with the camera closed
        and opened again. With [camera] probe_on_loss, the first frame
        lost is followed at once by camera_probe.py's look at the camera
        in that state, before it can clear (31 October 2026: the fault
        comes and goes, and hours spent making it happen found nothing);
        the speed is not changed for the frames that follow.

        With [camera] power_cycle_on_jam, the camera is not just opened again
        the second time: its power is cut at the hub's port and given back
        first (usbpower.py), as the hub's button does, and so too when it
        drops off USB. The jam clears only that way (1 November 2026: twice
        in an hour at speeds 0 and 2), and until then it took a walk outside."""
        lib = self.lib
        asked_at = time.monotonic()
        for attempt in range(4):        # the 4th: the first frame after opening again is often lost
            try:
                data, started = self._expose(seconds)
                break
            except (CameraError, lib.HRESULTException) as problem:
                if isinstance(problem, lib.HRESULTException):
                    problem = CameraError(_reason(problem))
                unplugged = "unplugged" in str(problem)
                if attempt == 3 or (unplugged and not self._cycles_power()):
                    raise problem
                # Said, never silent: on 31 October 2026 a run's first frame was
                # lost twice and kept on the third try, and its count said 720 of 720.
                print(f"camera: {problem}; trying again", file=sys.stderr, flush=True)
                if attempt == 0 and SETTINGS["camera"].get("probe_on_loss") and not self.probed:
                    self.probed = True
                    try:
                        import camera_probe
                        camera_probe.after_loss(self, seconds, problem,
                                                say=lambda line: print(line, file=sys.stderr, flush=True))
                    except Exception as failed:
                        print(f"camera: the probe failed: {failed}", file=sys.stderr, flush=True)
                if attempt == 1 or unplugged:
                    self.close()
                    if not self._power_cycle() and unplugged:
                        raise problem
                    self._open()
        header = fits.Header()
        header["EXPTIME"] = (float(seconds), "seconds")
        header["GAIN"] = (self.gain, "camera gain, percent")
        # When the exposure started, not when the frame arrived.
        header["DATE-OBS"] = (started.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3], "UTC, start of exposure")
        if not self.mono:
            header["BAYERPAT"] = self.pattern
        else:
            header["TY_MONO"] = (True, "mono sensor: no colour pattern")
        degrees = self.temperature()
        if degrees is not None:
            header["CCD-TEMP"] = (round(degrees, 1), "sensor temperature, C")
        if self.target is not None:
            header["SET-TEMP"] = (self.target, "cooler target, C")
            power = self.tec_power()
            if power is not None:
                header["TY_TECV"] = (round(power[0], 1), "cooler voltage, V")
                if power[1] is not None:
                    header["TY_TECP"] = (round(100 * power[1]), "cooler power, % of its most")
            if degrees is not None:
                # Kept either way; one off target is left out of science stacks.
                header["TY_ONTGT"] = (abs(degrees - self.target) <= ON_TARGET,
                                      f"sensor within {ON_TARGET:g} C of SET-TEMP")
        from camera import identify
        identify(header, SETTINGS, model=self.name)
        try:
            header["READSPD"] = (int(self.handle.get_Speed()), "readout speed")
        except self.lib.HRESULTException:
            pass
        # What a matched dark is chosen by besides exposure, gain, speed and
        # set temperature (stacking.MatchedCalibration).
        header["XBINNING"] = (int(self.binning), "binning the camera applied")
        level = getattr(self.lib, "ALTAIRCAM_OPTION_BLACKLEVEL", None)
        if level is not None:
            try:
                header["OFFSET"] = (int(self.handle.get_Option(level)), "black level (offset)")
            except self.lib.HRESULTException:
                pass
        # How long after the trigger the frame came back. 31 October 2026:
        # at speed 2 a 16 s frame comes back after 20.5 s when healthy and
        # 10.3 s in the fault, so a run shows when the camera changes state.
        if getattr(self, "back_s", None) is not None:
            header["TY_BACK"] = (self.back_s, "s from trigger to the frame arriving")
        # What getting this frame cost the camera layer: how many tries failed
        # first and the seconds from the first try to this frame. A recorded
        # stall, as against a gap between frames inferred afterwards
        # (outcome.py; 4 November 2026).
        header["TY_RETRY"] = (attempt, "failed tries before this frame")
        header["TY_GOT_S"] = (round(time.monotonic() - asked_at, 1), "s from the first try to this frame")
        return data, header

    def video(self, seconds, count, roi=None, timeout=5.0):
        """`count` frames as fast as the camera sends them, in its video mode
        rather than one triggered exposure at a time, for lucky imaging
        (lucky.py): yields (uint16 Bayer mosaic, seconds since the first, the camera's frame number).
        `roi` is (x, y, width, height) on the sensor, rounded to even numbers
        so the Bayer pattern stays the same. The camera is put back as it
        was afterwards, however the loop ends."""
        lib, handle = self.lib, self.handle
        full = (self.width, self.height)
        handle.Stop()
        try:
            handle.put_Option(lib.ALTAIRCAM_OPTION_TRIGGER, 0)     # 0: video, frames back to back
            if roi:
                x, y, w, h = (max(8, int(v)) // 2 * 2 for v in roi)
                handle.put_Roi(x, y, w, h)
                self.width, self.height = w, h
            handle.put_ExpoTime(max(1, round(seconds * 1e6)))
            handle.put_ExpoAGain(self.gain)
            with self._changed:
                self._ready, self._failure, self._waiting = 0, None, True
            handle.StartPullModeWithCallback(self._callback, self)
            first = None
            for _ in range(count):
                with self._changed:
                    arrived = self._changed.wait_for(lambda: self._ready or self._failure, timeout=timeout)
                    if self._failure or not arrived:
                        raise CameraError(self._failure or f"no video frame within {timeout:g} s")
                    self._ready -= 1
                data, info = self._pull()
                now = time.perf_counter()
                first = first if first is not None else now
                yield self._normalise(data), now - first, int(getattr(info, "seq", 0))
        finally:
            with self._changed:
                self._waiting = False
            for step in (handle.Stop, lambda: handle.put_Roi(0, 0, 0, 0),
                         lambda: handle.put_Option(lib.ALTAIRCAM_OPTION_TRIGGER, 1)):
                try:
                    step()
                except Exception:
                    pass   # put back as far as it will go
            self.width, self.height = full
            handle.StartPullModeWithCallback(self._callback, self)

    # --- what the camera is, for camera_test.py and the doctor ----------------------

    def details(self):
        """What the library knows of the camera: the camera's part of the
        Diagnose File Altair's support ask for from AltairCapture, which
        reads it through this same library."""
        lib, handle = self.lib, self.handle
        device = next((d for d in cameras(lib) if d.displayname == self.name), None)
        flags = device.model.flag if device else 0
        asked = lambda name: getattr(handle, name)() if hasattr(handle, name) else None   # not in older wrappers
        return {
            "model": self.name, "serial": handle.SerialNumber(),
            "sdk_version": lib.Altaircam.Version(), "firmware": handle.FwVersion(),
            "hardware": asked("HwVersion"), "fpga": asked("FpgaVersion"),
            "production_date": asked("ProductionDate"), "revision": asked("Revision"),
            "pixel_um": getattr(device.model, "xpixsz", None) if device else None,
            "fan": bool(flags & FAN),
            # Without one, each row goes down the lead as it is read, so
            # anything that holds the link up meets the readout.
            "frame_buffer": "whole frame" if flags & DDR else "part of a frame" if flags & BUFFER else "none",
            "usb3_camera": bool(flags & USB3),
            "flags": hex(flags), "usb3_camera_on_usb2_port": bool(flags & USB3_ON_USB2),
            "size": [self.width, self.height], "bit_depth": self.bits, "bayer": self.pattern,
            "mono": self.mono, "cooler": bool(flags & TEC), "sensor_c": self.temperature(),
            "cooler_target_c": self.target,
            "readout_speed": handle.get_Speed(), "max_readout_speed": handle.MaxSpeed(),
            # None until two frames have been taken; False if the camera's
            # frame stamps turned out not to keep time.
            "frame_clock_usable": self.clock,
            "values_shifted_up": self._shifted,
            "watched": self.watched(),
        }

    def watched(self):
        """The camera's WATCHED settings as it reports them; None for one
        this library or this camera does not have."""
        found = {}
        for key, option in WATCHED:
            number = getattr(self.lib, "ALTAIRCAM_OPTION_" + option, None)
            try:
                found[key] = self.handle.get_Option(number) if number is not None else None
            except Exception:
                found[key] = None     # a 2017 firmware may not know it
        return found


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
    try:
        # The same choice frame-taking makes, so this names the camera that
        # will really be used when config.toml picks one of several.
        out.append((OK, f"camera: {choose(lib, SETTINGS['camera'].get('serial')).displayname}"))
    except Refusal as refusal:
        out.append((FAIL, refusal.message))
    return out
