#!/usr/bin/env python3
"""Drive the mount through the SynScan handset's serial port.

    ./mount.py status     where it is pointing, and whether it is moving
    ./mount.py nudge      from home, tip the tube 5° and bring it back: the
                          smallest move there is, for someone standing beside
                          the mount to see that it really turns
    ./mount.py settime    give the handset this computer's date, time and the
                          site's position, so they need not be typed on its
                          keypad: press ENTER through its start-up screens to
                          the main menu first. Moves nothing.
    ./mount.py zenith     point straight up and hold there (tracking off)
    ./mount.py goto M81   point at a catalogue object and track it
    ./mount.py goto M81 --solve   ...then photograph the sky, work out the real
                          aim, and correct it until the object is centred
    ./mount.py point 225 10   point at compass bearing 225°, 10° up, and hold
    ./mount.py drift      measure how fast the aim is sliding in Dec and set
                          the Dec motor creeping the other way to cancel it
    ./mount.py compensate measure the polar axis, say how to fix it, and
                          meanwhile cancel the drift it causes. After this,
                          every GoTo starts with the creep its part of the sky
                          needs. It slews about 25° twice to take its measure.
    ./mount.py pointing   go to eight hour angles, four each side of the
                          meridian, plate-solve at each and say how far out
                          the aim is: is one correction for each side enough?
                          The tube swings over the pole once.
    ./mount.py findhome   after polar alignment: plate-solve at eight hour angles,
                          four each side of the meridian, in one run, and work
                          out from them where the home position really is.
                          The tube swings over the pole once.
    ./mount.py truehome   drive to the home position findhome has just found,
                          for the two joints to be marked there. Then switch
                          the handset off and on with the mount on its marks,
                          and run findhome again to see what is left. Without
                          a handset it records that place as home itself.
    ./mount.py sync       photograph the sky where it is now, work out the real
                          aim, and remember the error for later GoTos. Do this
                          once after setting up, on any patch of stars.
    ./mount.py home       back to the home position (pointing at the pole)
    ./mount.py stop       stop all motion now

The handset must be switched on and past its start-up screens. "Home" means
where the mount sat when the handset was powered on, which the handset reads
as RA axis 0° and Dec 90°.

Until you have logged out and back in since being added to the dialout group,
run it as:  sudo -u $USER -g dialout ./mount.py zenith

Add --demo to any command to try it against a simulated mount with nothing
plugged in:  ./mount.py --demo goto M27
"""
import argparse
import contextlib
import os
import json
import math
import signal
import sys
import threading
import time
from pathlib import Path

import serial

import activity
import config
import records
import host
import tracking
from interface import Refusal, emit, run as answer
from watch import Watching

ROOT = Path(__file__).parent
# How far the handset's idea of sidereal time is from the true one, in degrees.
# Its clock and location are wrong, so every GoTo is corrected by this. It
# holds until the handset is switched off.
CLOCK_FILE = config.DATA / "cache" / "handset_clock.json"
MIN_ALTITUDE = 20
# Furthest from the meridian a GoTo may point, in hours. Beyond 6 h the
# counterweight is above the tube, which is normal for this kind of mount;
# what matters is where the tube, the camera and its lead meet a tripod leg.
# It was 5.75 h from 3 October 2026, the first night, after a collision whose
# cause was the handset clipped to the wrong leg, and was never measured. On
# 2 November 2026 the clearance test (point --clearance-test), the person
# beside the mount, went to 6.0, 6.5, 7.0 and 7.5 h each side at Dec +40°
# (32° down to 21° up): the camera, its lead and the counterweights stayed
# clear of the legs at every step, the counterweights 22 cm away at the
# closest. With the 20° floor, nothing further round is any lower. It stays
# here in the code, never a setting (AGENTS.md).
# Not the only place the tube can meet a leg: on 12 November 2026 the back
# of the tube (183M, wheel) caught the north leg at Dec +40°, east of the
# pier, between hour angles -2 and -1 h, the tube half an inch too far back
# in its rings, and the RA clutch slipped about 50° unnoticed
# (docs/nights/2026-11-11/mount-collision.md).
MAX_HOUR_ANGLE = 7.5
# The clearance test may go this far, and no further, to find where it is.
CLEARANCE_TEST_HOURS = 8.0
# While this file exists, nothing that moves the mount will run. Its contents
# say why. Delete it only once the cause has been dealt with.
LOCK_FILE = ROOT / "MOTION_LOCKED"
# Pointing error found by plate solving, carried into later GoTos.
POINTING_FILE = config.DATA / "cache" / "pointing.json"
CENTRED = 2 / 60  # degrees; close enough to stop correcting
LAST_SOLVE = config.DATA / "cache" / "last_solve.json"


def last_solve(cfg=None):
    """The last plate solve's record (ra, dec, rotation, scale, cd, saved)
    if it was made by the camera in use through its present light path, else
    None: a solve by the 183C at 750 mm must never give the 183M at 675 mm
    its scale or its orientation. A record from before the camera was written
    into it counts as not matching; the next solve replaces it."""
    try:
        record = json.loads(LAST_SOLVE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    camera, focal = config.light_path(cfg)
    if record.get("camera") != camera or record.get("focal_mm") != focal:
        return None
    return record
FRAME_TRIES = 3   # pictures tried for one plate solve before the camera counts as gone
# What has been learned about the drift, and the Dec creep now running.
DRIFT_FILE = config.DATA / "cache" / "drift_model.json"
# What `pointing` found, for looking at afterwards.
SURVEY_FILE = config.DATA / "cache" / "pointing_survey.json"
HOME_FILE = config.DATA / "cache" / "home_fit.json"      # what `findhome` found, for `truehome`
HOME_FRESH = 2 * 3600     # seconds a home measurement may be acted on
# Each findhome keeps its frames, messages and fit here, one folder a run,
# accepted or not, so a bad measurement can be looked at afterwards.
HOME_RUNS = config.DATA / "cache" / "findhome"
# From the last accepted findhome, the parts a new home leaves alone (the
# tube's squareness, the polar axis), for `findhome --check`. Set aside by a
# polar alignment run, which may follow a turn of the bolts.
GEOMETRY_FILE = config.DATA / "cache" / "home_geometry.json"
GEOMETRY_FRESH = 6 * 3600   # seconds: a night's session, the tripod untouched
# Hours from the meridian for `findhome --check`: two each side are enough
# for two unknowns with figures to spare (8 for 2).
CHECK_HOURS = (-3.0, -1.0, 1.0, 3.0)
# Degrees: home this close counts as right (the second findhome of 17
# October 2026 found 0.19° and 0.05°; the aim is a tenth).
HOME_RIGHT = 0.1
# How uncertain the home found would be with a random error of 1° in each
# plate solve, from the places' geometry alone (home_leverage: a figure
# for conditioning, not a bound): 0.9 with the eight places at Dec +40°,
# 1.5 with six, 2.7 with two a side, 6 with four inside an hour of the
# meridian. Past this the places cannot tell the home errors from the rest
# of the model, however well they fit it (six places at two hour angles
# fit a wrong home exactly).
HOME_LEVERAGE = 3.0
# Degrees: truehome counts as there when both axes read this close to the
# measured home. Under twice the seek's last stop (0.03°); the motor
# board's own moves land within a few counts.
ARRIVED = 0.05
# Degrees: within one side the aim's error changes smoothly from place to
# place (tan(dec) times the polar error per radian of hour angle: 0.4° an
# hour at Dec +40° with the axis 2° out). A bigger jump is a clutch
# slipping or the tube held, not geometry (12 November 2026: a 15° move
# showed 3.4°).
JUMP = 2.0
# Degrees: the model fits when the places sit this close to it. A first
# figure, from made-up solves; to be set from the first real run's residuals.
HOME_FITS = 0.15
# Degrees: leaving any one place out must not move the answer by more than
# this, or it rests on that one place.
HOME_SWAY = 0.1
# Hours from the meridian, for `pointing` and `findhome`: four each side, so
# that one place can be doubted and the answer still checked against the rest.
SURVEY_HOURS = (-4.0, -3.0, -2.0, -1.0, 1.0, 2.0, 3.0, 4.0)
SURVEY_DEC = 40.0
# A first GoTo that misses by less than this still has the target in the
# frame, which is two thirds of a degree tall on the 150P with the 183C.
ENOUGH = 0.25
SETTLE = 10       # seconds to wait after a slew before photographing: the skyline survey of
                  # 17 October 2026 found the tube steady after 2 s half the time, 26 s at worst
# The surveys (findhome, pointing) need a picture that solves, not stars
# landing to the arcsecond, so they wait only this long and then let the
# picture say whether the tube has settled (still_swinging), up to the
# worst seen: a 1 s frame at 0.73"/px trails visibly long before its
# position is wrong by anything the 0.15° fit would notice.
SETTLE_LEAST = 2
SETTLE_MOST = 26
# Median roundness of the stars below which a picture counts as trailed: a
# first figure. The 183M's settled 2 s frames of 18 November 2026 read 0.81
# to 0.94 in the middle of the frame, and one 4 s frame 0.56. A trail as
# long as a star is wide reads about 0.83, twice as long 0.59, and this is
# about 2.6 star widths (some 8" on the 183M in a 1 s frame): the tube
# still swinging, not seeing. Fewer stars than this and it is not judged.
SETTLED_ROUND = 0.5
SETTLE_STARS = 5
if config.DEMO:
    import os
    SETTLE = 0 if os.environ.get("TY_DEMO_FAST") == "1" else 2
    SETTLE_LEAST = min(SETTLE_LEAST, SETTLE)

# Raw axis angles, in degrees, as the handset's "z" query reports them.
HOME_RA_AXIS = 0.0
HOME_DEC_AXIS = 90.0
NUDGE = 5.0       # degrees the tube is tipped by `nudge`
# RA axis angle at which the tube is on the meridian.
MERIDIAN_RA_AXIS = 90.0

RA, DEC = 16, 17            # axis ids for fixed-rate slews
POSITIVE, NEGATIVE = 36, 37
# SynScan firmware from which "z" reportedly answers the precise Az/Alt, as the
# Celestron protocol and Sky-Watcher's protocol v3.3 define it, and no longer
# the raw axis angles this file reads it as (a 4.39.21 release note, seen only
# quoted: docs/research/mount-protocols-2026-10-20.md). The author's handset
# is 3.35. A newer one is refused until it has been checked.
Z_CHANGED = (4, 39, 21)
PULSE_RATE = 30.0           # arcsec/s: the fastest move of the photometric hold (twice sidereal)
PULSE_LONGEST = 10.0        # seconds: its longest; a bigger miss is re-centred by GoTo instead
# Fixed-rate stages for closing in on an axis angle: (rate 1-9, stop within °).
STAGES = ((8, 2.0), (6, 0.25), (4, 0.03))
SLEW_TIMEOUT = 150
# Commands that send the tube away from whatever it was aimed at (not to a
# named object): the stream stops naming a target (director.py).
AWAY = ("zenith", "home", "point", "pointing", "findhome", "truehome", "directions")


def handset_firmware(raw):
    """(major, minor, patch) from a handset's answer to "V" when it is the
    newer six hexadecimal digits ("042507#" for 4.37.07); None for the older
    two-byte answer (below version 4) or anything else."""
    body = raw[:-1] if raw.endswith(b"#") else raw
    if len(body) == 6:
        try:
            return tuple(int(body[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            return None
    return None


def _interrupted(number, frame):
    raise KeyboardInterrupt


def stop_on_termination():
    """From here on SIGTERM and SIGHUP stop this process as Ctrl+C does.
    A slew is a motor left turning until the process says stop; killed by
    a signal Python does not handle (Claude Code's interrupt, a closed
    terminal), it never would. As KeyboardInterrupt, every script's own
    `except BaseException: scope.stop()` runs on the way out, and nothing
    takes it for an ordinary refusal (shoot.py carries on past SystemExit).
    A handler a script set itself (guider.py, focus.py) or an ignored
    signal (nohup) is left as it is. Windows ends a process without a
    signal it can catch: there, Ctrl+C, and the console's own stop."""
    if threading.current_thread() is not threading.main_thread():
        return
    for name in ("SIGTERM", "SIGHUP"):
        number = getattr(signal, name, None)
        if number is not None and signal.getsignal(number) == signal.SIG_DFL:
            signal.signal(number, _interrupted)


class Mount:
    def __init__(self, port=None, watch=True, demo=False, handset=None):
        """`demo` drives a simulated handset; `handset` supplies one directly
        (anything with the serial port's write/read_until interface)."""
        stop_on_termination()
        self.demo = demo or handset is not None or config.DEMO
        # Read now, refused at the first move (self.may_move): stop and
        # status need no site, so a missing or example one never stops them.
        self.site_set = self.demo or own_site_set()
        self.recording = None   # folder to keep each solve frame and message in
        # A simulated mount has no camera behind it, except in the full demo,
        # which has a pretend camera and sky to solve.
        self.can_solve = not self.demo or (config.DEMO and handset is None)
        # The webcam photographs the scope during real moves only when the
        # settings turn it on ([webcam] enabled and watch_moves, both off
        # unless set: 19 October 2026). Its light comes on for each picture,
        # which is no help beside a telescope in the dark, so TY_NO_WATCH=1
        # also stops it for any script.
        watch = watch and host.webcam_on("watch_moves") and not os.environ.get("TY_NO_WATCH")
        self.watching = Watching if watch and not self.demo else contextlib.nullcontext
        if self.demo:
            import simulator
            quick = os.environ.get("TY_DEMO_FAST") == "1"
            board_at = os.environ.get("TY_DEMO_BOARD")
            if handset is None and board_at:
                # direct.py on a pretend motor board, starting at these axis
                # angles ("RA,Dec" in degrees): to try a change to the Wi-Fi
                # adapter's code before it goes near the mount.
                self.s = simulator.direct_demo(board_at, slew_seconds=0.0 if quick else 2.0)
            else:
                self.s = handset or simulator.SimulatedHandset(slew_seconds=0.0 if quick else 2.0)
            if handset is None:
                simulator.DEMO_SCOPE = self
        elif mount_settings().get("link", "handset") != "handset":
            # No handset: the Wi-Fi adapter or an EQDIR lead reaches the motor
            # board, and direct.py does the handset's part.
            import direct
            settings = mount_settings()
            # The example's site only when there is none of its own, and then
            # may_move refuses everything but stop: the clock is never used.
            site = (config.load() if self.site_set else config.example())["site"]
            self.s = direct.DirectHandset(direct.Board(direct.open_link(settings, port)),
                                          lambda: true_sidereal(site))
        else:
            # The handset's lead is recognised by its USB adapter's name.
            match = mount_settings()["serial_match"]
            asked = port
            port = port or host.serial_port(match) or host.serial_fallback()
            if not host.WINDOWS and (port is None or not Path(port).exists()):
                # Dropped off USB (15 November 2026: the hub it hangs from went
                # at 20:00): the hub port tried again from here, not by a hand.
                import usbguard
                usbguard.recover("handset", say=lambda *a, **k: print(*a, file=sys.stderr, **k))
                port = asked or host.serial_port(match) or host.serial_fallback()
            if port is None:
                seen = ", ".join(f"{device} ({name})" for device, name in host.serial_ports())
                raise Refusal("HANDSET_NOT_ANSWERING",
                              f"No serial port matches \"{match}\" (serial_match under "
                              f"[mount] in config.toml). Ports seen: {seen or 'none'}. "
                              "Plug in the handset's lead, or name the port with --port.")
            try:
                self.s = serial.Serial(port, 9600, timeout=2)
            except serial.SerialException:
                raise Refusal("MOUNT_NOT_CONNECTED", f"The handset's lead is not there ({port} cannot be "
                              "opened). Plug it in at both ends.")
        if self.ask(b"Kx") != b"x#":
            raise Refusal("HANDSET_NOT_ANSWERING", "The handset is not answering. Is it on "
                          "and past its start-up screens?")
        if not host.WINDOWS:
            try:
                import usbguard
                usbguard.remember("handset")      # where it is, for recover() if it drops later
            except Exception:      # noqa: BLE001 - keeping its place never stops the mount
                pass
        # The handset answers even while still on its version screen, where it
        # has not read the mount's gearing and moves by the wrong amounts. Its
        # clock shows the default year 2022 until someone sets it up.
        clock = self.ask(b"h")
        if len(clock) == 9 and clock[5] == 22:
            raise Refusal("HANDSET_NOT_SET_UP",
                          "The handset has not been set up since power-on (its date is "
                          "still the default). Press ENTER through its start-up screens "
                          "to the main menu, entering today's date.")
        firmware = handset_firmware(self.ask(b"V"))
        if firmware is not None and firmware >= Z_CHANGED:
            raise Refusal("HANDSET_NOT_SUPPORTED",
                          f"This handset's firmware is {'.'.join(str(v) for v in firmware)}. From "
                          f"{'.'.join(str(v) for v in Z_CHANGED)} the handset reportedly answers the "
                          "question this program reads the axis angles with (z) with altitude and "
                          "azimuth instead, which would put home and the limits in the wrong place. "
                          "Not supported until checked: see docs/mounts.md, and please report it.")

    def record(self, folder):
        """Keep every plate-solve frame and progress message from now on, for
        replay.py to turn into an animation."""
        self.recording = Path(folder)
        self.recording.mkdir(parents=True, exist_ok=True)
        (self.recording / "steps.json").write_text("[]", encoding="utf-8")

    def say(self, text):
        """Print a progress message, and note it in the recording if any."""
        print(text, flush=True)
        if self.recording:
            steps = json.loads((self.recording / "steps.json").read_text(encoding="utf-8"))
            frames = len(list(self.recording.glob("frame-*.jpg")))
            steps.append({"text": text, "frame": frames, "time": time.time()})
            records.write((self.recording / "steps.json"), steps)

    def ask(self, command):
        try:
            self.s.reset_input_buffer()
            self.s.write(command)
            return self.s.read_until(b"#", 64)
        except (OSError, serial.SerialException):
            # 7 October 2026: a lead knocked out in the middle of a move home.
            # Nothing more can be sent, a stop included.
            raise Refusal("MOUNT_NOT_CONNECTED", "The handset's lead has come out in the middle of a command. "
                          "Nothing can be sent to the mount, not even a stop: if a motor is still turning, "
                          "switch the mount off at the mount. Then plug the lead back in.")

    def _pair(self, command):
        # The handset occasionally drops a reply while it is busy; ask again.
        for _ in range(4):
            reply = self.ask(command)
            if len(reply) == 18:
                return [int(x, 16) / 2**32 * 360 for x in reply[:-1].decode().split(",")]
            time.sleep(0.5)
        raise Refusal("HANDSET_NOT_ANSWERING", "The handset stopped answering position queries.")

    def radec(self):
        """Sky position (RA, Dec) in degrees, as the handset believes it."""
        return self._pair(b"e")

    def axes(self):
        """Raw (RA axis, Dec axis) angles in degrees."""
        return self._pair(b"z")

    def slewing(self):
        return self.ask(b"L").startswith(b"1")

    def state(self):
        """'slewing', 'tracking' or 'stopped', by asking and by watching the
        RA axis for a moment: tracking turns it at the sky's rate."""
        if self.slewing():
            return "slewing"
        first = self.axes()[0]
        time.sleep(1.5)
        rate = wrap(self.axes()[0] - first) * 3600 / 1.5   # arcseconds per second
        return "tracking" if 8 < rate < 25 else "stopped"

    def at_home(self):
        ra_axis, dec_axis = self.axes()
        return abs(wrap(HOME_RA_AXIS - ra_axis)) < 0.3 and abs(HOME_DEC_AXIS - dec_axis) < 0.3

    # --- motion -------------------------------------------------------------

    def may_move(self):
        """Every movement goes through here first (rate, tracking, creep,
        pulse, GoTo, the handset's clock and place): whichever command asks,
        none moves the real mount on the example site or none, or past the
        lock file. Stopping (a zero rate, tracking off, stop) never comes here."""
        if LOCK_FILE.exists():
            raise Refusal("MOTION_LOCKED", f"Motion is locked: {LOCK_FILE.read_text(encoding='utf-8').strip()}")
        if not self.site_set:
            raise Refusal("SITE_NOT_SET", "config.toml has no location of its own (missing, unreadable or "
                                          "still the example's): set your own latitude and longitude "
                                          "before the mount is used. Stop still works.")

    def rate(self, axis, direction, rate):
        if rate:
            self.may_move()
        self.ask(bytes([ord("P"), 2, axis, direction, rate, 0, 0, 0]))

    def stop(self):
        self.ask(b"M")  # cancel any GoTo
        for axis in (RA, DEC):
            self.rate(axis, POSITIVE, 0)
            self.rate(axis, NEGATIVE, 0)
        # The Dec creep is the handset's other kind of rate (mode 3): whether
        # a fixed rate of 0 also ends it is not known, so it is ended itself,
        # as home() does before a seek. Tracking is left as it is.
        self.dec_creep(0)

    def tracking(self, on):
        # Mode 2 is equatorial tracking, 0 is off.
        if on:
            self.may_move()
        self.ask(b"T" + bytes([2 if on else 0]))

    def dec_creep(self, rate):
        """Turn the Dec axis steadily at `rate` arcseconds per second
        (positive raises the axis readout); 0 stops it. The handset takes the
        rate in quarter-arcsecond steps, so the rate actually set is returned."""
        steps = min(round(abs(rate) * 4), 0xFFFF)
        if steps:
            self.may_move()
        self.ask(bytes([ord("P"), 3, DEC, 6 if rate >= 0 else 7, steps >> 8, steps & 0xFF, 0, 0]))
        return math.copysign(steps / 4, rate) if steps else 0.0

    def pulse(self, axis, rate, seconds, creep=0.0):
        """Turn one axis at `rate` arcseconds per second (sign is direction)
        for `seconds`, then put it back: tracking on again for RA, the Dec
        creep it had for Dec. For the photometric hold's small moves
        (shoot.py --hold): at most PULSE_RATE for PULSE_LONGEST seconds.

        Whether the handset adds a variable RA rate to its tracking or
        replaces tracking with it is not known for this mount, so nothing
        relies on either: the hold measures what a pulse does to the frames
        before it uses one, and tracking is switched on again after each."""
        if LOCK_FILE.exists():
            raise Refusal("MOTION_LOCKED", f"Motion is locked: {LOCK_FILE.read_text(encoding='utf-8').strip()}")
        self.may_move()
        rate = max(-PULSE_RATE, min(PULSE_RATE, rate))
        seconds = max(0.0, min(PULSE_LONGEST, seconds))
        steps = min(round(abs(rate) * 4), 0xFFFF)
        try:
            self.ask(bytes([ord("P"), 3, axis, 6 if rate >= 0 else 7, steps >> 8, steps & 0xFF, 0, 0]))
            time.sleep(seconds)
        finally:
            if axis == RA:
                self.ask(bytes([ord("P"), 3, RA, 6, 0, 0, 0, 0]))
                self.tracking(True)
            else:
                self.dec_creep(creep)
        return rate * seconds

    def west(self):
        """True with the tube swung over the pole, as for targets west of
        the meridian (the Dec axis reads past 90°)."""
        return over_pole(self.axes()[1])

    def aim(self, hour_angle, dec, site, offset, error=None, west=None):
        """Slew to a true hour angle and Dec (degrees), corrected by the
        plate-solved pointing error of the side of the pole the tube really
        comes over. The side is first guessed from the hour angle (or given
        as `west`, with its `error`); the handset picks its own side near the
        meridian, so after the slew the axes are read, and if the tube came
        over the other side it is sent again with that side's correction.
        Returns (west, error, steady): the side it is on, the correction it
        was aimed with, and False if the side changed again on the second
        slew, when the aim cannot be trusted. 3 November 2026: with the two
        sides' corrections +15.6° and -14.3° in Dec (home not set), looks due
        south took the east correction with the tube over the west side, and
        were aimed about 30° low."""
        west = hour_angle > 0 if west is None else west
        error = load_pointing_error(west) if error is None else error
        for attempt in range(2):
            self.goto((true_sidereal(site) + offset - (hour_angle - error[0])) % 360, dec - error[1])
            came = self.west()
            if came == west:
                return west, error, True
            if attempt == 1:
                # On `came`'s side, aimed with the other side's correction:
                # said as it is, never to be added to or kept.
                return came, error, False
            if load_pointing_error(came) == list(error):
                # Both sides' corrections alike (none measured since the
                # handset was set up, both zero): the aim stands as it is.
                return came, error, True
            west, error = came, load_pointing_error(came)
            self.say(f"  the tube came over the {side_name(came)} side: aiming again with that "
                     f"side's correction ({error[1]:+.1f}° in Dec); it may swing over the pole again")

    def drift_model(self, site):
        """What has been learned about the drift since the handset was set up;
        anything older belongs to a different setting-up and is forgotten."""
        model = tracking.Model(DRIFT_FILE, latitude=site["latitude"])
        if model.path.exists() and CLOCK_FILE.exists():
            saved = json.loads(model.path.read_text(encoding="utf-8")).get("saved", 0)
            if saved < json.loads(CLOCK_FILE.read_text(encoding="utf-8"))["saved"]:
                model.forget()
        return model

    def true_hour_angle(self, site):
        """Where the mount is aimed, as an hour angle in degrees, allowing
        for the handset's clock and the pointing error found by plate solving."""
        offset = json.loads(CLOCK_FILE.read_text(encoding="utf-8"))["offset_deg"]
        error = load_pointing_error(self.west())
        return wrap(true_sidereal(site) + offset - self.radec()[0]) + error[0]

    def apply_drift_correction(self, site):
        """Start the Dec motor creeping against the drift expected where the
        mount now points, from the drift model. Does nothing if the model
        knows nothing about this part of the sky."""
        if not CLOCK_FILE.exists():
            return None
        model = self.drift_model(site)
        expected = model.predict(self.true_hour_angle(site))
        if expected is None:
            return None
        model.creep = self.dec_creep(tracking.creep_for(expected, self.west()))
        model.save()
        return expected

    def measure_drift(self, site, solves=4, gap=30):
        """Plate-solve several times, `gap` seconds apart, and fit a line
        through them. Returns how fast the aim is sliding across the sky as
        (east-west, Dec, uncertainty in Dec), in arcseconds per second, or
        None if the sky could not be solved. Zero means perfect tracking."""
        error = load_pointing_error(self.west())
        hint_ra = true_sidereal(site) - self.true_hour_angle(site)
        found = self.where_really(hint_ra, wrap(self.radec()[1]) + error[1], radius=20)
        if not found:
            return None
        fixes = [found]
        for _ in range(solves - 1):
            time.sleep(gap)
            found = self.where_really(fixes[-1]["ra"], fixes[-1]["dec"], radius=5)
            if found:   # a passing cloud costs one point, not the measurement
                fixes.append(found)
        if len(fixes) < 2:
            return None
        # A perfectly tracked aim keeps the same sky coordinates.
        seconds = [(f["when"] - fixes[0]["when"]).sec for f in fixes]
        shrink = math.cos(math.radians(fixes[0]["dec"]))
        east_west, _ = tracking.line_fit(
            seconds, [wrap(f["ra"] - fixes[0]["ra"]) * shrink * 3600 for f in fixes])
        dec, sigma = tracking.line_fit(seconds, [f["dec"] * 3600 for f in fixes])
        return east_west, dec, sigma

    def cancel_drift(self, site, rounds=3):
        """Measure the Dec drift and set the Dec motor creeping against it,
        then measure again and refine. Each measurement of the natural drift
        is added to the drift model. Returns the last (residual, uncertainty)."""
        west = self.west()
        model = self.drift_model(site)
        creep = self.dec_creep(model.creep if model.creep is not None else 0.0)
        residual = sigma = None
        for attempt in range(rounds):
            drift = self.measure_drift(site)
            if drift is None:
                raise Refusal("PLATE_SOLVE_FAILED", "Could not plate-solve; drift not measured.")
            east_west, residual, sigma = drift
            sure = "" if sigma is None else f" ±{sigma:.2f}"
            natural = residual - tracking.creep_effect(creep, west)
            model.observe(self.true_hour_angle(site), wrap(self.radec()[1]), natural, sigma)
            wanted, decided = tracking.next_creep(creep, residual, sigma, west)
            creep = self.dec_creep(wanted)
            self.say(f"Dec drift {residual:+.2f}{sure} arcsec/s (east-west {east_west:+.2f}); "
                     f"creep {creep:+.2f}: {decided}")
            model.creep = creep
            model.save()
            if "left alone" in decided:
                break
            if attempt < rounds - 1:
                # The Dec gears have slack, so a new rate takes a while to bite.
                time.sleep(60)
        return residual, sigma

    def pointing_survey(self, site, hours=SURVEY_HOURS, dec=SURVEY_DEC, skyline=None, keep=True, for_home=False,
                        check=False):
        """Go to each hour angle at one declination, as the handset believes
        them (no correction applied), plate-solve, and record how far out
        the aim really is. Returns pointing_summary()'s account, and keeps
        each side's average as that side's pointing error if `keep`
        (findhome keeps them only once its fit is accepted). Each place
        keeps how long its slew and its plate solve took."""
        spots, _ = plan_survey(site, hours, dec, skyline, for_home, check)     # refuses here, before anything moves
        if not CLOCK_FILE.exists():
            self.save_clock(site)
        offset = json.loads(CLOCK_FILE.read_text(encoding="utf-8"))["offset_deg"]
        rows, last = [], None
        for hours_out in spots:
            began = time.monotonic()
            self.goto((true_sidereal(site) + offset - hours_out * 15) % 360, dec)
            slewed = time.monotonic() - began
            self.tracking(True)
            time.sleep(SETTLE_LEAST)
            began = time.monotonic()
            west = over_pole(self.axes()[1])
            guess = load_pointing_error(west)
            sidereal = true_sidereal(site)
            ra_handset, dec_handset = self.radec()
            believed = wrap(sidereal + offset - ra_handset)
            hint = (sidereal - (believed + guess[0]), wrap(dec_handset) + guess[1])
            found = self.where_really(*hint, radius=40, wider=90,
                                      settle_until=began + SETTLE_MOST - SETTLE_LEAST)
            if not found:
                self.say(f"hour angle {hours_out:+g} h: no plate solve; left out")
                continue
            actual = where(found, site, found["when"])
            import moved
            if last and moved.solved(abs(hours_out * 15 - last[0]), abs(wrap(actual[0] - last[1])),
                                     f"pointing survey, hour angle {hours_out:+g} h"):
                self.stop()
                raise moved.refusal(f"After a move of {abs(hours_out * 15 - last[0]):.0f}° the sky is "
                                    "where it was.")
            last = (hours_out * 15, actual[0])
            row = {"hour_angle_h": hours_out, "side": side_name(west),
                   "ha_error_deg": round(wrap(actual[0] - believed), 3),
                   "dec_error_deg": round(actual[1] - wrap(dec_handset), 3),
                   "slew_s": round(slewed, 1), "settle_s": SETTLE_LEAST, "trailed_frames": found["trailed"],
                   "solve_s": round(time.monotonic() - began, 1)}
            before = next((r for r in reversed(rows) if r["side"] == row["side"]), None)
            if before:
                jump = math.hypot((row["ha_error_deg"] - before["ha_error_deg"]) * math.cos(math.radians(dec)),
                                  row["dec_error_deg"] - before["dec_error_deg"])
                if jump > JUMP:
                    # The move showed, but not as far as it was made: a clutch
                    # slipping, or the tube held. The axis readings no longer
                    # say where the tube is, so nothing more is measured.
                    self.stop()
                    raise moved.refusal(f"Between hour angles {before['hour_angle_h']:+g} h and {hours_out:+g} h "
                                        f"the aim's error jumped by {jump:.1f}°, where the geometry allows a few "
                                        "tenths: a clutch may have slipped, or something held the tube.")
            rows.append(row)
            self.say(f"hour angle {hours_out:+g} h ({rows[-1]['side']}): out by "
                     f"{rows[-1]['ha_error_deg']:+.2f}° in hour angle, {rows[-1]['dec_error_deg']:+.2f}° in Dec")
        if rows:
            # Where the time went, so that a faster survey starts from the real cost.
            self.say(f"Time over {len(rows)} places: slewing {sum(r['slew_s'] for r in rows):.0f} s, settling "
                     f"{sum(r['settle_s'] for r in rows):.0f} s, pictures and plate solves "
                     f"{sum(r['solve_s'] for r in rows):.0f} s ({sum(r['trailed_frames'] for r in rows)} pictures "
                     "taken again because the tube was still settling).")
        found = pointing_summary(rows)
        if keep:
            keep_pointing(found)
        found.update(rows=rows, dec_deg=dec, saved=time.time())
        SURVEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        records.write(SURVEY_FILE, found)
        if keep:
            self.say(found["verdict"])
        return found

    def find_home(self, site, hours=SURVEY_HOURS, dec=SURVEY_DEC, skyline=None, check=False):
        """Measure where the home position really is. One uninterrupted run
        of plate solves either side of the meridian (pointing_survey), and a
        fit of home_fit()'s model to them. Nothing remembered from earlier is
        used. Returns the fit; only one that is accepted is kept for
        true_home(), and its places as the pointing errors. `check` is
        check_home() instead."""
        if check:
            return self.check_home(site, hours, dec, skyline)
        # Whatever was measured before is not to be acted on once a new
        # measurement has begun, whether or not this one finishes.
        if HOME_FILE.exists():
            HOME_FILE.replace(HOME_FILE.with_name("home_fit.previous.json"))
        run = HOME_RUNS / time.strftime("%Y%m%d-%H%M%S")
        if not self.recording:
            self.record(run)
        survey = self.pointing_survey(site, hours, dec, skyline, keep=False, for_home=True)
        found = home_fit(survey["rows"], dec)
        link, counts = home_reference()
        found.update(saved=time.time(), dec_deg=dec, rows=survey["rows"], goes_to=home_target(found),
                     link=link, home_counts=counts)
        records.write(run / "fit.json", found)
        if found["fits"]:
            keep_pointing(survey)
            records.write(HOME_FILE, found)
            # The parts of the account that a new home leaves as they were,
            # for check_home() after truehome and the restart.
            records.write(GEOMETRY_FILE, {k: found[k] for k in (
                "tube_not_square_deg", "polar_p_deg", "polar_q_deg", "dec_deg", "saved", "link")})
        self.say(f"Home is out by {found['ra_home_error_deg']:+.2f}° on the RA axis and "
                 f"{found['dec_home_error_deg']:+.2f}° on the Dec axis"
                 + ("" if found["ra_home_sigma_deg"] is None else
                    f" (±{found['ra_home_sigma_deg']:.2f}° and ±{found['dec_home_sigma_deg']:.2f}°)")
                 + f". The {found['places']} places sit "
                 f"{found['rms_deg']:.2f}° from that account of them"
                 + ("" if found["sway_deg"] is None else
                    f", and leaving any one out moves home by at most {found['sway_deg']:.2f}°")
                 + (", which fits." if found["fits"] else
                    f". It is not acted on: {found['why_not']}. The mount will not be driven to a home "
                    "worked out from this."))
        for place in found["residuals"]:
            self.say(f"  hour angle {place['hour_angle_h']:+g} h ({place['side']}): {place['miss_deg']:.2f}° from it "
                     f"({place['ha_deg']:+.2f}° in hour angle, {place['dec_deg']:+.2f}° in Dec)")
        if found["left_out"]:
            gone = found["left_out"]
            self.say(f"  hour angle {gone['hour_angle_h']:+g} h was left out: it sits {gone['miss_deg']:.2f}° from "
                     "what the other places agree on. Look at that frame before trusting the rest.")
        if found["fits"]:
            size = math.hypot(found["ra_home_error_deg"], found["dec_home_error_deg"])
            self.say("That is close enough to mark as it stands." if size < 0.1 else
                     "Next: ./mount.py truehome --dry-run, then ./mount.py truehome, and mark both joints there.")
        return found

    def check_home(self, site, hours=None, dec=SURVEY_DEC, skyline=None):
        """After truehome (and the restart on the marks, with a handset):
        whether home is now right, from four places instead of eight. The
        tube's squareness and the polar axis are taken from the last
        accepted findhome, which a new home does not change; only the two
        home errors are found. A check, not a measurement: nothing is kept
        for truehome, and if the places do not agree with that account (the
        polar axis turned since, a bad solve) it says to run findhome."""
        geometry = load_geometry(dec)        # refuses here, before anything moves
        hours = CHECK_HOURS if hours is None or tuple(hours) == SURVEY_HOURS else hours
        run = HOME_RUNS / (time.strftime("%Y%m%d-%H%M%S") + "-check")
        if not self.recording:
            self.record(run)
        survey = self.pointing_survey(site, hours, dec, skyline, keep=False, for_home=True, check=True)
        found = home_check(survey["rows"], dec, geometry)
        found.update(saved=time.time(), dec_deg=dec, rows=survey["rows"])
        records.write(run / "check.json", found)
        self.say(f"With the tube's squareness and the polar axis from the findhome of "
                 f"{time.strftime('%H:%M', time.localtime(geometry['saved']))}, home is now out by "
                 f"{found['ra_home_error_deg']:+.2f}° on the RA axis and {found['dec_home_error_deg']:+.2f}° on "
                 f"the Dec axis; the {found['places']} places sit {found['rms_deg']:.2f}° from that account.")
        self.say(found["verdict"])
        return found

    def true_home(self):
        """Drive to the home position find_home() has just measured, by the
        axis readouts, and hold there with tracking off, for the joints to
        be marked. The handset still believes its old home until it is
        switched off and on with the mount on those marks."""
        plan = plan_true_home()          # refuses here, before anything moves
        target = plan["ra_axis_deg"], plan["dec_axis_deg"]
        # Home first, as ./mount.py home goes, then the small step from there:
        # every later setting of home by the marks is then approached the same way.
        self.home()
        with self.watching():
            if hasattr(self.s, "board"):
                # The board's own moves, as home makes: the fixed-rate seek
                # buzzed and stalled the motors on the Wi-Fi adapter.
                self.may_move()
                self.s.go_axes(*target, SLEW_TIMEOUT)
            else:
                # The seek's last stage can stop a little short or past: one
                # more try from there, then the readings decide.
                for _ in range(2):
                    self.seek(DEC, target[1])
                    self.seek(RA, target[0])
        self.tracking(False)
        ra_axis, dec_axis = self.axes()
        off = max(abs(wrap(ra_axis - target[0])), abs(dec_axis - target[1]))
        if off > ARRIVED:
            raise Refusal("SLEW_TIMED_OUT", f"The axes read RA {wrap(ra_axis):+.2f}°, Dec {dec_axis:.2f}°, "
                          f"{off:.2f}° from the measured home (RA {wrap(target[0]):+.2f}°, Dec {target[1]:.2f}°): "
                          "not there. Do not mark the joints. Run ./mount.py truehome again.")
        if hasattr(self.s, "board"):
            # Without a handset (direct.py) home is only where the motors were
            # recorded, so the measured home is recorded here and now: the
            # person asked for it (18 November 2026, after a clutch reset left
            # home 3.2° and 5.7° out and sethome had to be run by hand).
            counts = self.s.set_home()
            forget_pointing()
            self.say(f"At the measured home, and recorded as home (motor counts {counts[0]}, {counts[1]}). "
                     "The motors' counts say it is there; the sky has not yet said so (a slipping clutch "
                     "would not show in the counts). Check it with ./mount.py findhome --check (four places), "
                     "then mark both joints.")
            return
        self.say(f"At the measured home: the axes read RA {wrap(ra_axis):+.2f}°, Dec {dec_axis:.2f}°. Mark both "
                 "joints now. Then switch the handset off and on with the mount on its marks, press ENTER "
                 "through to the main menu, run ./mount.py settime, and check it with ./mount.py findhome "
                 "--check (four places): home should be within a tenth of a degree. If the tripod was moved, "
                 "polar-align and run ./mount.py findhome in full instead.")

    def compensate(self, site):
        """Wonky alignment mode: measure how far the polar axis is out, say
        how to fix it mechanically, then make the best of it as it stands by
        cancelling the drift it causes."""
        import polaralign
        self.say("Measuring the polar axis...")
        azimuth, altitude = polaralign.measure(self, site)
        model = self.drift_model(site)
        model.set_polar(azimuth, altitude)
        self.say(polaralign.describe(azimuth, altitude))
        self.say("Or leave it alone, and the drift it causes will be compensated.")
        expected = self.apply_drift_correction(site)
        self.say(f"Estimated Dec drift here: {expected:+.2f} arcsec/s. Compensating...")
        time.sleep(60)   # let the Dec gears take up their slack
        residual, sigma = self.cancel_drift(site, rounds=2)
        sure = "" if sigma is None else f" ±{sigma:.2f}"
        limit = tracking.exposure_limit(residual)
        self.say(f"Residual: {residual:+.2f}{sure} arcsec/s. Good for exposures of about "
                 f"{limit:.0f} s; the stacker's alignment deals with the slow turning "
                 "of the field that remains.")

    def seek(self, axis, target):
        """Turn one axis to a raw angle with fixed-rate slews, steering by the
        axis readout rather than trusting the handset's GoTo."""
        index = 0 if axis == RA else 1
        error = lambda: wrap(target - self.axes()[index])
        start = error()
        if abs(start) <= STAGES[-1][1]:
            return
        # Find which way reduces the error.
        direction = POSITIVE
        self.rate(axis, direction, 6)
        # Wait until the readout has actually moved: after creeping the other
        # way the gears take a moment to bite, and judging too early picks
        # the wrong direction.
        began = time.monotonic()
        while abs(error() - start) < 0.05 and time.monotonic() - began < 8:
            time.sleep(0.2)
        if abs(error()) > abs(start):
            self.rate(axis, direction, 0)
            direction = NEGATIVE
        for rate, close_enough in STAGES:
            self.rate(axis, direction, rate)
            began = time.monotonic()
            # Stop when close, when the error changes sign (overshoot), or
            # when it starts growing: the Dec readout peaks at the pole, so
            # running past it looks like moving away again.
            best = abs(start)
            while abs(e := error()) > close_enough and (e > 0) == (start > 0):
                best = min(best, abs(e))
                if abs(e) > best + 0.2:
                    break
                if time.monotonic() - began > SLEW_TIMEOUT:
                    self.rate(axis, direction, 0)
                    raise Refusal("SLEW_TIMED_OUT", "Axis did not arrive in time; stopped.")
            self.rate(axis, direction, 0)
            time.sleep(0.5)

    def goto(self, ra, dec):
        """Handset GoTo to a sky position in degrees; waits until it stops."""
        self.may_move()
        with self.watching():
            if self.ask(f"r{encode(ra)},{encode(dec)}".encode()) != b"#":
                raise Refusal("GOTO_REFUSED", "The handset refused the GoTo.")
            began = time.monotonic()
            while self.slewing():
                if time.monotonic() - began > SLEW_TIMEOUT:
                    self.stop()
                    raise Refusal("SLEW_TIMED_OUT", "GoTo did not finish in time; stopped.")
                time.sleep(1)
        if config.DEMO:
            import simulator
            simulator.recentred()    # the pretend sky is centred on wherever it was sent

    def handset_sidereal(self):
        """The handset's own sidereal time in degrees, from where it says it
        is pointing and where its RA axis actually is."""
        ra, _ = self.radec()
        ra_axis, dec_axis = self.axes()
        # RA axis angle past the meridian mark is the hour angle; with the
        # tube swung over the pole (Dec axis past 90°) it is half a turn on.
        hour_angle = ra_axis - MERIDIAN_RA_AXIS + (180 if 90 < dec_axis < 270 else 0)
        return (ra + hour_angle) % 360

    def home(self):
        self.tracking(False)
        self.dec_creep(0)   # a drift correction left running would fight the seek
        with self.watching():
            if hasattr(self.s, "board"):
                # No handset: the board's own moves, which start slowly. The
                # fixed-rate seek below starts a motor at 2.5°/s at once, and
                # on the Wi-Fi adapter (17 November 2026) the motors buzzed and
                # stalled: the RA axis turned 11° in two and a half minutes.
                self.may_move()
                self.s.go_home(SLEW_TIMEOUT)
                return
            # Dec first, so the tube is up by the pole before the RA axis swings.
            self.seek(DEC, HOME_DEC_AXIS)
            self.seek(RA, HOME_RA_AXIS)

    def direct(self):
        """The stand-in for the handset when the mount is reached without
        one, or a refusal: these commands mean nothing with a real handset."""
        if not hasattr(self.s, "board"):
            raise Refusal("INVALID_REQUEST", "That is only for a mount reached without its handset "
                          "(link = \"wifi\" or \"eqdir\" under [mount] in config.toml). The handset "
                          "knows these things itself.")
        return self.s

    def set_home(self):
        """Record that the mount is at its home position now. Moves nothing."""
        counts = self.direct().set_home()
        forget_pointing()
        print(f"Home recorded at motor counts {counts[0]}, {counts[1]}. This holds until the mount "
              "is switched off or its clutches are loosened.")

    def check_directions(self, ask=input):
        """Find out, with a person watching, which way the Dec motor turns:
        tip the tube 5° from home, ask which way it went, and put it back."""
        import direct
        hand = self.direct()
        if not self.at_home():
            raise Refusal("GOTO_REFUSED", "The direction check starts from the home position. Run "
                          "./mount.py home first (or ./mount.py sethome if it is already there).")
        board, step = hand.board, hand.board.counts(direct.DEC, 5)

        def turn(steps):
            board.ready()
            board.move(direct.DEC, steps)
            began = time.monotonic()
            while board.status(direct.DEC)["running"]:
                if time.monotonic() - began > 60:
                    board.halt(direct.DEC)
                    raise Refusal("SLEW_TIMED_OUT", "The Dec axis did not finish its 5° turn; stopped.")
                time.sleep(0.2)

        with self.watching():
            turn(step)
            try:
                said = ask("The tube has tipped 5° away from the pole. Stand behind the mount facing "
                           "north, the way the tube was pointing. Did the front of the tube tip to "
                           "your RIGHT (east) or your LEFT (west)? [e/w] ").strip().lower()[:1]
            finally:
                turn(-step)     # back to home, whatever was answered
        if said not in ("e", "w"):
            raise Refusal("INVALID_REQUEST", "Answer e or w. The tube is back at home; nothing was recorded.")
        # At home, a Dec axis reading below 90° aims east of the pole. So if
        # counting up tipped the tube east, counting up lowers the reading.
        hand.set_dec_sign(-1 if said == "e" else 1)
        print("Recorded. GoTo is now allowed on this link.")

    def nudge(self, degrees=NUDGE, hold=3):
        """From home, tip the tube `degrees` away from the pole on the Dec
        axis, hold, and bring it back. The counterweight bar does not move.
        For a person beside the mount to see and hear that it turns: the
        readout alone proves nothing (6 October 2026)."""
        if not self.at_home():
            raise Refusal("GOTO_REFUSED", "The nudge starts from the home position. Run ./mount.py home first.")
        with self.watching():
            self.seek(DEC, HOME_DEC_AXIS - degrees)
            reached = self.axes()[1]
            self.say(f"Tipped: the Dec axis reads {reached:.1f}°. Holding {hold} s, then back.")
            time.sleep(hold)
            self.seek(DEC, HOME_DEC_AXIS)
        if abs(reached - (HOME_DEC_AXIS - degrees)) > 0.5 or not self.at_home():
            raise Refusal("SLEW_TIMED_OUT", f"The Dec axis read {reached:.1f}° when tipped and "
                          f"{self.axes()[1]:.1f}° afterwards; it should have read "
                          f"{HOME_DEC_AXIS - degrees:.0f}° and {HOME_DEC_AXIS:.0f}°.")
        self.say(f"Back at home. The mount says the tube tipped {degrees:g}° and returned: did it, and did "
                 "the motor sound? If not, switch the mount off and on.")

    def zenith(self, site):
        # The handset's GoTo picks the correct side of the mount, but only
        # behaves predictably from the home position.
        if not self.at_home():
            self.home()
        self.goto(self.handset_sidereal(), site["latitude"])
        self.tracking(False)
        self.save_clock(site)

    def set_clock(self, site):
        """Give the handset this computer's date and time (as UTC, with no
        zone and no summer time, so there is nothing to get wrong) and the
        site's position, then measure its clock afresh. The handset must be
        at its main menu: this cannot press its keys. Moves nothing. Returns
        what the handset says its date and time are afterwards."""
        self.may_move()
        if hasattr(self.s, "board"):
            # No handset on this link (Wi-Fi adapter or EQDIR lead): the sums
            # use this computer's clock and site, so there is nothing to set.
            # The clock is still measured afresh, as after a handset's, so the
            # night starts from new pointing corrections either way.
            self.save_clock(site)
            self.say("No handset on this link: it uses this computer's clock and site, so there is "
                     "nothing to set. Pointing errors measured before this will be measured again.")
            return {"handset_time": None, "clock_offset_deg": 0.0, "clock_offset_before_deg": None}
        now = time.gmtime()
        if self.ask(bytes([ord("H"), now.tm_hour, now.tm_min, now.tm_sec, now.tm_mon, now.tm_mday,
                           now.tm_year % 100, 0, 0])) != b"#":
            raise Refusal("INVALID_REQUEST", "The handset did not take the date and time. Is it at its main menu?")

        def parts(angle):
            whole = round(abs(angle) * 3600)
            return [whole // 3600, whole // 60 % 60, whole % 60, 1 if angle < 0 else 0]     # south and west are 1
        if self.ask(b"W" + bytes(parts(site["latitude"]) + parts(site["longitude"]))) != b"#":
            raise Refusal("INVALID_REQUEST", "The handset took the time but not the position.")
        for _ in range(4):
            # A reply is read up to its closing "#", which is also the byte
            # for 35: at 35 minutes or seconds past, it comes back cut short.
            clock = self.ask(b"h")
            if len(clock) == 9:
                break
            time.sleep(1.1)
        else:
            raise Refusal("HANDSET_NOT_ANSWERING", "The handset took the time but would not read it back.")
        before = json.loads(CLOCK_FILE.read_text(encoding="utf-8"))["offset_deg"] if CLOCK_FILE.exists() else None
        self.save_clock(site)
        after = json.loads(CLOCK_FILE.read_text(encoding="utf-8"))["offset_deg"]
        said = f"20{clock[5]:02d}-{clock[3]:02d}-{clock[4]:02d} {clock[0]:02d}:{clock[1]:02d}:{clock[2]:02d} UTC"
        self.say(f"The handset now says {said}. Its sidereal clock is {after:+.2f}° from the true one"
                 + (f" (it was {before:+.2f}°)." if before is not None else ".")
                 + " Pointing errors measured before this no longer apply and will be measured again.")
        return {"handset_time": said, "clock_offset_deg": round(after, 3),
                "clock_offset_before_deg": None if before is None else round(before, 3)}

    def save_clock(self, site):
        offset = wrap(self.handset_sidereal() - true_sidereal(site))
        CLOCK_FILE.parent.mkdir(exist_ok=True)
        records.write(CLOCK_FILE, {"offset_deg": offset, "saved": time.time()}, indent=None)

    def point(self, azimuth, altitude, site, clearance_test=False):
        """Aim at a fixed direction, e.g. a distant rooftop, and hold there."""
        if not CLOCK_FILE.exists():
            # Reading the handset's clock needs no movement, so do it now.
            self.save_clock(site)
        plan = plan_point(azimuth, altitude, site, clearance_test)
        offset = json.loads(CLOCK_FILE.read_text(encoding="utf-8"))["offset_deg"]
        hour_angle, dec = plan["hour_angle_hours"] * 15, plan["dec_deg"]
        print(f"bearing {azimuth:.0f}°, {altitude:.0f}° up: hour angle "
              f"{hour_angle / 15:+.2f} h, Dec {dec:+.1f}° ({plan['side_note']})")
        self.goto((true_sidereal(site) + offset - hour_angle) % 360, dec)
        self.tracking(False)

    @activity.during("Moving", "to {name}")
    def goto_target(self, name, site, solve=False, aim_off=(0.0, 0.0)):
        """GoTo a catalogue object, and with `solve` centre it by plate
        solving. `aim_off` is arcminutes east and north of the object to aim
        at instead: shoot.py --dither aims a little off it between frames, so
        the camera's own pattern does not stay on the same stars."""
        if not CLOCK_FILE.exists():
            # Reading the handset's clock needs no movement, so do it now.
            self.save_clock(site)
        offset = json.loads(CLOCK_FILE.read_text(encoding="utf-8"))["offset_deg"]
        plan = plan_goto(name, site)
        import director
        # What the telescope is aimed at, for the stream (director.py): a
        # file only, never an error, and nothing about the move. A small
        # move about a target already reached (a dither, centring the Moon)
        # is not a new one.
        again = any(aim_off) and director.observing(name)
        if not again:
            director.aim(name)
        outcome = "failed"      # until the mount says it has arrived
        try:
            outcome = self._goto_target(name, site, solve, aim_off, plan, offset)
        finally:
            if not again or outcome == "failed":
                self.arrived(name, site, aim_off, outcome)
        return outcome          # "centred" only when a plate solve found the object in the middle

    def _goto_target(self, name, site, solve, aim_off, plan, offset):
        """goto_target's move: "reached" once the mount has arrived, or
        "centred" once a plate solve has found the object in the middle."""
        import director
        target = find_target(name)
        if any(aim_off):
            target = offset_target(target, *aim_off)
        if config.DEMO:
            import simulator
            simulator.set_sky(target=target["id"])     # the pretend sky shows this target's stars
        hour_angle, altitude = plan["hour_angle_hours"] * 15, plan["altitude_deg"]
        self.say(f"{target['id']} {target['name']}: altitude {altitude:.0f}°, "
                 f"hour angle {hour_angle / 15:+.2f} h ({plan['side_note']})")
        # Ask for the RA that puts the tube at the true hour angle, less the
        # pointing error measured by earlier plate solves.
        west, error = None, None
        last = None      # the miss before the last correction
        for attempt in range(4 if solve else 1):
            hour_angle, dec, _ = where(target, site)
            # Corrected by the side the tube really came over, which is the
            # side any correction found below is kept for.
            west, error, steady = self.aim(hour_angle, dec, site, offset, error, west)
            self.tracking(True)
            if not steady:
                # Its correction was for the other side: a miss measured now
                # would be added to the wrong side's and kept.
                self.say("  the tube changed sides again; aim left as it is, nothing kept")
                return "reached"
            self.apply_drift_correction(site)
            if solve and not self.can_solve:
                print("  (demo: no camera, so no plate solve)")
            if not solve or not self.can_solve:
                return "reached"
            director.mark(name, "centring")
            # After a slew the gears take a while to bite again and the stars
            # streak, which the solver cannot handle. Wait, and try twice.
            time.sleep(SETTLE)
            miss = self.measure_miss(target, site)
            if miss is None:
                time.sleep(SETTLE)
                miss = self.measure_miss(target, site)
            if miss is None:
                self.say("Could not plate-solve the frame; aim left uncorrected.")
                return "reached"
            self.say(f"  off by {miss[0] * 60:+.1f}' in hour angle, {miss[1] * 60:+.1f}' in Dec")
            if last is not None:
                import moved
                if moved.unchanged(last, miss, f"GoTo {target['id']}"):
                    self.stop()
                    raise moved.refusal(f"A correction of {math.hypot(*last) * 60:.0f}' left the target "
                                        "exactly as far off as before.")
            last = miss
            if max(abs(miss[0]), abs(miss[1])) < CENTRED:
                self.say("  centred")
                return "centred"
            error = [error[0] + miss[0], error[1] + miss[1]]
            save_pointing_error(error, west)
        self.say("  still not centred after 4 tries")
        return "reached"

    def arrived(self, name, site, aim_off, outcome):
        """Tell the stream (director.py) how a GoTo to `name` ended: an
        arrival is "reached" only if the mount's own reading of where it
        points is within director.NEAR_DEG of the object, else "off". Reads
        the mount, never moves it, and is never an error."""
        try:
            import director
            miss = None
            if outcome == "reached":
                try:
                    miss = self.distance_from(offset_target(find_target(name), *aim_off), site)
                except Exception:        # an unanswered read: the arrival stands unchecked
                    miss = None
                if miss is not None and miss > director.NEAR_DEG:
                    outcome = "off"
            director.mark(name, outcome, confirmed={"centred": "plate solve"}.get(outcome) or (
                "mount" if outcome == "reached" and miss is not None else None), miss_deg=miss)
        except Exception:                # the GoTo's own outcome, or its error, goes on regardless
            pass

    def distance_from(self, target, site):
        """Degrees on the sky between where the mount says it points (allowing
        for its clock and the plate-solved pointing error) and `target`."""
        hour_angle, dec, _ = where(target, site)
        pointing = load_pointing_error(self.west())
        here_ha, here_dec = self.true_hour_angle(site), wrap(self.radec()[1]) + pointing[1]
        return math.hypot(wrap(here_ha - hour_angle) * math.cos(math.radians(dec)), here_dec - dec)

    def where_really(self, ra_hint, dec_hint, radius=30, exposure=1.0, wider=None, settle_until=None):
        """Photograph the sky and plate-solve it. Returns the J2000 position
        of the frame centre as {"ra", "dec"} in degrees, or None. With
        `wider`, a frame that does not solve within `radius` is searched again
        out to `wider` degrees: the same picture, not a new one. With
        `settle_until` (a time.monotonic()), a frame whose stars are trailed,
        the tube still swinging from the slew, is taken again a second later
        until they are round or that time comes: the frame itself says the
        tube has settled, and no fixed wait is needed. The answer then says
        how many frames were trailed (`trailed`)."""
        began = time.monotonic()
        import solve as solver
        import numpy as np
        from scipy import ndimage
        from camera import Camera, luminance
        import snap
        # Short exposure at high gain: after a slew the stars drift for a
        # while, and streaked stars do not solve.
        from astropy.time import Time
        from indi import IndiError
        # The camera sometimes sends no frame, on both drivers (21 October
        # 2026: a polar check lost at its third picture). Open it afresh and
        # take the picture again before giving up.
        trailed = 0
        while True:
            for attempt in range(FRAME_TRIES):
                try:
                    with Camera(gain=2000) as cam:
                        mosaic, _ = cam.frame(exposure)
                    break
                except IndiError:
                    if attempt == FRAME_TRIES - 1:
                        raise
                    print(f"{time.strftime('%H:%M:%S')} the camera sent no picture; trying again", flush=True)
            if settle_until is None or time.monotonic() >= settle_until or not still_swinging(luminance(mosaic)):
                break
            trailed += 1
            print(f"{time.strftime('%H:%M:%S')} the stars are trailed: still settling; another picture", flush=True)
            time.sleep(1)
        when = Time.now()
        framed = time.monotonic()
        snap.publish(mosaic, kind="plate-solve frame", detail=f"{exposure:g} s")
        if self.recording:
            count = len(list(self.recording.glob("frame-*.jpg")))
            snap.publish(mosaic, self.recording / f"frame-{count + 1:02d}.jpg")
        # Hot pixels look like stars to the solver: only a pixel far brighter
        # than every one of its eight neighbours (which a star never is) is
        # put back to their median. A median filter over the whole frame did
        # this on 4 November 2026 and blurred the 183M's small, sharp stars so
        # far that each solve took 107 s; the same frame unfiltered took 0.3 s.
        image = luminance(mosaic).astype(np.float32)
        ring = np.ones((3, 3), bool)
        ring[1, 1] = False
        brightest = ndimage.maximum_filter(image, footprint=ring, mode="nearest")
        noise = 1.4826 * float(np.median(np.abs(image[::4, ::4] - np.median(image[::4, ::4])))) or 1.0
        hot = image > brightest + 5 * noise
        if hot.any():
            image[hot] = ndimage.median_filter(image, footprint=ring, mode="nearest")[hot]
        prepared = time.monotonic()
        found = solver.solve(image, ra_hint, dec_hint, radius)
        if not found and wider:
            found = solver.solve(image, ra_hint, dec_hint, wider)
        # Where the time went, for every plate solve (4 November 2026: a polar
        # check took minutes and nothing said which part).
        print(f"{time.strftime('%H:%M:%S')} plate solve: camera and frame {framed - began:.1f} s, "
              f"preparing {prepared - framed:.1f} s, solving {time.monotonic() - prepared:.1f} s"
              f"{'' if found else ', no solution'}", flush=True)
        if found:
            found["when"] = when  # solving can take a while; the sky moves on
            found["trailed"] = trailed
            # Kept for shoot.py's drift assist, which needs to know which way
            # up the camera is.
            (config.DATA / "cache").mkdir(exist_ok=True)
            # With the camera and light path it was made through, so a solve
            # by one camera is never read as another's scale or orientation
            # (last_solve). Read after the frame: opening the camera is what
            # tells the settings which camera is in use.
            camera, focal = config.light_path()
            records.write(LAST_SOLVE, {k: found[k] for k in ("ra", "dec", "rotation", "scale", "cd") if k in found}
                          | {"camera": camera, "focal_mm": focal, "saved": time.time()}, indent=None)
        return found

    def sync(self, site):
        """Measure the pointing error where the scope is now and store it."""
        offset = json.loads(CLOCK_FILE.read_text(encoding="utf-8"))["offset_deg"]
        ra_handset, dec_handset = self.radec()
        sidereal = true_sidereal(site)
        believed_ha = wrap(sidereal + offset - ra_handset)
        found = self.where_really(sidereal - believed_ha, wrap(dec_handset), radius=40)
        if not found:
            raise Refusal("PLATE_SOLVE_FAILED",
                          "Could not plate-solve: cloud, too few stars, or out of focus.")
        actual = where(found, site, found["when"])
        error = [wrap(actual[0] - believed_ha), actual[1] - wrap(dec_handset)]
        # Dec axis past 90° means the tube is over the pole, on the west side.
        save_pointing_error(error, west=over_pole(self.axes()[1]))
        print(f"really at RA {found['ra'] / 15:.4f} h, Dec {found['dec']:+.2f}° (J2000); "
              f"the mount was out by {error[0]:+.1f}° in hour angle, {error[1]:+.1f}° in Dec")

    def measure_miss(self, target, site):
        """Photograph the sky and return how far the real aim is from the
        target, as (hour angle, Dec) in degrees, or None if it cannot tell."""
        found = self.where_really(target["ra"], target["dec"])
        if not found:
            return None
        actual = where({"ra": found["ra"], "dec": found["dec"]}, site)
        wanted = where(target, site)
        return wrap(actual[0] - wanted[0]), actual[1] - wanted[1]


def direction(azimuth, altitude, site):
    """(hour angle, declination) in degrees for a compass bearing and height,
    refusing anything near the Sun while it is up."""
    import sky  # noqa: F401
    from astropy import units as u
    from astropy.coordinates import AltAz, HADec, SkyCoord, get_sun
    from astropy.time import Time
    now, here = Time.now(), location(site)
    frame = AltAz(obstime=now, location=here)
    spot = SkyCoord(az=azimuth * u.deg, alt=altitude * u.deg, frame=frame)
    sun = get_sun(now).transform_to(frame)
    if sun.alt.deg > -1 and spot.separation(sun).deg < 40:
        raise Refusal("TARGET_NEAR_SUN", "That is within 40° of the Sun; not slewing.")
    hadec = spot.transform_to(HADec(obstime=now, location=here))
    return hadec.ha.deg, hadec.dec.deg


NEAR_MERIDIAN = 0.33     # hours from the meridian inside which the handset's choice of side is not to be relied on


def _plan(hour_angle, dec, altitude, label, limit=None):
    """The checks every aimed move must pass, and what the move would involve.
    Raises a Refusal if it must not be made; needs no hardware. `limit` is
    the hour-angle limit for this move: only the clearance test passes one."""
    if LOCK_FILE.exists():
        raise Refusal("MOTION_LOCKED", f"Motion is locked: {LOCK_FILE.read_text(encoding='utf-8').strip()}")
    limit = MAX_HOUR_ANGLE if limit is None else limit
    if abs(hour_angle) > limit * 15:
        raise Refusal("TARGET_BEYOND_HOUR_ANGLE_LIMIT",
                      f"{label} is {abs(hour_angle) / 15:.1f} h from the meridian, beyond the "
                      f"{limit} h limit; not slewing.")
    west = hour_angle > 0
    # From the plan alone the side the mount is on now is not known: a west
    # target is a swing over the pole only from the east side (18 October
    # 2026: the warning stopped a short move on the west side).
    warnings = ["The tube goes to the west side: it swings over the pole if it is on the east side now."] if west else []
    # The handset chooses the side by its own clock and pointing, which can be
    # a couple of degrees from the truth: on 13 October 2026 a target 0.14 h
    # east of the meridian was reached with the tube swung over the pole.
    if abs(hour_angle) < NEAR_MERIDIAN * 15 and not west:
        warnings = ["This is within 20 minutes of the meridian, where the handset may choose either "
                    "side: the tube may swing over the pole."]
    return {
        "would_move": True, "safe": True,
        "altitude_deg": round(float(altitude), 1), "dec_deg": round(float(dec), 2),
        "hour_angle_hours": round(float(hour_angle) / 15, 3),
        "pier_side": "west" if west else "east",
        "side_note": "west: a swing over the pole if it is on the east side now" if west else "east",
        "warnings": warnings,
    }


def plan_goto(name, site):
    """What a GoTo to a catalogue object would do, checked against the limits,
    without moving anything."""
    target = find_target(name)
    hour_angle, dec, altitude = where(target, site)
    if altitude < MIN_ALTITUDE:
        raise Refusal("TARGET_BELOW_ALTITUDE_LIMIT",
                      f"{target['id']} is only {altitude:.0f}° up; not slewing.")
    plan = _plan(hour_angle, dec, altitude, target["id"])
    hidden = behind(hour_angle, dec, altitude, site)
    if hidden:
        plan = dict(plan, warnings=plan.get("warnings", []) + [f"{target['id']} is {hidden}"])
    return dict(plan, target=target["id"], name=target.get("name", ""))


def behind(hour_angle, dec, altitude, site):
    """What the settings say stands in front of a place in the sky, as words,
    or None. The house and the tree are noted in [horizon]; a GoTo behind one
    is allowed, since the note may be rough, but it is said first."""
    if config.DEMO or not config.FILE.exists():
        return None
    import horizon
    lat, ha, d = math.radians(site["latitude"]), math.radians(hour_angle), math.radians(dec)
    az = math.degrees(math.atan2(-math.cos(d) * math.sin(ha),
                                 math.sin(d) * math.cos(lat) - math.cos(d) * math.cos(ha) * math.sin(lat))) % 360
    top = horizon.in_the_way(config.load().get("horizon", {}), az)
    if altitude <= top:
        return (f"at bearing {az:.0f}°, {altitude:.0f}° up, where the view is noted as blocked "
                f"up to {top:.0f}°: expect no stars there.")
    return None


def plan_point(azimuth, altitude, site, clearance_test=False):
    """What pointing at a compass bearing and height would do, without moving.
    With `clearance_test`, past the hour-angle limit up to
    CLEARANCE_TEST_HOURS, to find with a person watching where the tube
    really meets the tripod; never lower than MIN_ALTITUDE then."""
    if not 2 <= altitude <= 89:
        raise Refusal("ALTITUDE_OUT_OF_RANGE", "Altitude must be between 2° and 89°.")
    if clearance_test and altitude < MIN_ALTITUDE:
        raise Refusal("TARGET_BELOW_ALTITUDE_LIMIT", f"The clearance test goes no lower than {MIN_ALTITUDE}°.")
    hour_angle, dec = direction(azimuth, altitude, site)
    plan = _plan(hour_angle, dec, altitude, "That", CLEARANCE_TEST_HOURS if clearance_test else None)
    if clearance_test and abs(hour_angle) > MAX_HOUR_ANGLE * 15:
        plan["warnings"] = plan.get("warnings", []) + [
            f"Clearance test: {abs(hour_angle) / 15:.2f} h from the meridian, past the {MAX_HOUR_ANGLE} h limit."]
    return dict(plan, azimuth_deg=azimuth)


def plan_survey(site, hours=SURVEY_HOURS, dec=SURVEY_DEC, skyline=None, for_home=False, check=False):
    """The hour angles `pointing` would go to, east side first so that the
    tube swings over the pole only once, checked against the limits, the
    Sun and what is known to be in the way. Returns (hours, notes); raises a
    Refusal if fewer than two are left on either side, or, `for_home`, if
    the places left cannot tell where home is (home_leverage). Needs no
    hardware."""
    import polaralign
    spots, notes = [], []
    if len(set(hours)) < len(hours):
        notes.append("Each hour angle is visited once: a place seen again adds nothing to the geometry.")
    for hours_out in sorted(set(hours)):
        altitude, azimuth = polaralign.to_altaz(polaralign.vector(hours_out * 15, dec), site["latitude"])
        _plan(hours_out * 15, dec, altitude, f"Hour angle {hours_out:+g} h")     # the lock and the hour-angle limit
        if altitude > 0:
            direction(azimuth % 360, altitude, site)        # refuses anywhere near the Sun while it is up
        if altitude < MIN_ALTITUDE:
            notes.append(f"Hour angle {hours_out:+g} h is only {altitude:.0f}° up there; left out.")
            continue
        if skyline:
            import horizon
            top = horizon.in_the_way(skyline, azimuth % 360)
            if altitude < top + polaralign.CLEAR:
                notes.append(f"Hour angle {hours_out:+g} h (bearing {azimuth % 360:.0f}°, {altitude:.0f}° up) is "
                             f"behind something that reaches {top:.0f}°; left out.")
                continue
        spots.append(hours_out)
    for name, side in (("east", [h for h in spots if h < 0]), ("west", [h for h in spots if h > 0])):
        if len(side) < 2:
            raise Refusal("INVALID_REQUEST", f"Fewer than two places are left to look at on the {name} side, "
                          "which is too few to say anything: " + " ".join(notes) + " Try another --dec or "
                          "other --hours.")
    if for_home:
        leverage = home_leverage([{"hour_angle_h": h, "side": "east" if h < 0 else "west"} for h in spots], dec,
                                 fixed=check)
        if leverage > HOME_LEVERAGE:
            raise Refusal("INVALID_REQUEST", f"These places cannot tell where home is: a random error of 1° in "
                          f"each plate solve would leave home uncertain by about {leverage:.1f}°, and it needs under "
                          f"{HOME_LEVERAGE:g}°. Spread them further from the meridian, or use more (the eight by "
                          "default).")
        notes.append(f"From these places, a random error of 1° in each plate solve would leave home uncertain "
                     f"by about {leverage:.1f}°.")
    if any(h > 0 for h in spots):
        notes.append("The tube will swing over the pole once, between the east side and the west.")
    return spots, notes


def pointing_summary(rows, enough=ENOUGH):
    """What a pointing survey showed, for each side of the meridian: the
    average error, how far any one place sits from that average (`spread`),
    and how the error changes with hour angle. One correction for a side is
    enough when its spread is under `enough` degrees."""
    import numpy as np
    sides = {}
    for name in ("east", "west"):
        here = [r for r in rows if r["side"] == name]
        if not here:
            continue
        ha, dec = np.array([r["ha_error_deg"] for r in here]), np.array([r["dec_error_deg"] for r in here])
        hours = np.array([r["hour_angle_h"] for r in here])
        spread = float(max(np.abs(ha - ha.mean()).max(), np.abs(dec - dec.mean()).max()))
        side = {"places": len(here), "ha_error_deg": round(float(ha.mean()), 3),
                "dec_error_deg": round(float(dec.mean()), 3), "spread_deg": round(spread, 3),
                "enough": bool(len(here) >= 2 and spread <= enough)}
        if len(here) >= 3:
            side["ha_error_per_hour"] = round(float(np.polyfit(hours, ha, 1)[0]), 3)
            side["dec_error_per_hour"] = round(float(np.polyfit(hours, dec, 1)[0]), 3)
        sides[name] = side
    judged = [s for s in sides.values() if s["places"] >= 2]
    if not judged:
        verdict = "Too few places solved to say whether one correction for each side is enough."
    elif all(s["enough"] for s in judged):
        verdict = (f"One correction for each side is enough: no place is more than {enough:g}° from its "
                   "side's average. Each side's average has been kept as its pointing error.")
    else:
        worst = max(judged, key=lambda s: s["spread_deg"])
        verdict = (f"One correction for each side is not enough: on one side the error changes by up to "
                   f"{worst['spread_deg']:.2f}° from place to place. Each side's average has been kept, "
                   "which is the best one figure can do; a correction that changes with hour angle would do better.")
    return {"sides": sides, "one_correction_per_side_is_enough": bool(judged and all(s["enough"] for s in judged)),
            "verdict": verdict}


def home_fit(rows, dec):
    """Where the home position really is, from a pointing survey's rows
    ({"hour_angle_h", "side", "ha_error_deg", "dec_error_deg"}) at one
    declination. The handset takes the place it was switched on at for home:
    RA axis 0°, Dec axis 90°. If the mount was really `a` and `e` degrees
    from there, every axis reading is out by that much ever after, and a
    plate solve at a place of hour angle h shows, in degrees,

        hour angle error =  a  +  s c / cos(dec)  -  tan(dec) (p cos h + q sin h)
        Dec error        =  s e               +  p sin h  -  q cos h

    where s is +1 on the east side and -1 on the west, with the tube swung
    over the pole: a Dec axis that reads wrong moves the aim one way on one
    side and the other way on the other. c is the tube not being square to
    the Dec axis, which also changes sides; p and q are what is left of the
    polar axis's error, which changes smoothly with hour angle. Places at
    several hour angles on both sides tell the five apart, by least squares.
    The answer is only as good as `rms_deg`, how far the places sit from it."""
    import numpy as np
    shrink, slope = math.cos(math.radians(dec)), math.tan(math.radians(dec))

    def fit(rows):
        """(the five answers, rms) for some of the rows."""
        model = home_model(rows, dec)
        seen = np.array([v for row in rows for v in (row["ha_error_deg"], row["dec_error_deg"])])
        answer = np.linalg.lstsq(model, seen, rcond=None)[0]
        return answer, float(np.sqrt(np.mean((model @ answer - seen) ** 2)))

    def miss(row, answer):
        """How far one place sits from the account: in hour angle, in Dec, and on the sky."""
        ra, dec_error, cone, p, q = answer
        s, h = (1.0 if row["side"] == "east" else -1.0), math.radians(row["hour_angle_h"] * 15)
        in_ha = row["ha_error_deg"] - (ra + s * cone / shrink - slope * (p * math.cos(h) + q * math.sin(h)))
        in_dec = row["dec_error_deg"] - (s * dec_error + p * math.sin(h) - q * math.cos(h))
        return {"hour_angle_h": row["hour_angle_h"], "side": row["side"], "ha_deg": round(float(in_ha), 3),
                "dec_deg": round(float(in_dec), 3), "miss_deg": round(float(math.hypot(in_ha * shrink, in_dec)), 3)}

    def enough(rows, limit=HOME_LEVERAGE):
        """Two different places on each side and five in all, laid out so
        that they tell home apart from the rest of the model. A place left
        out in turn needs only that they tell the five apart at all: one
        that leaves them weakly placed shows as sway (17 October 2026's
        seven places, which found home, read 3.1 without their -3 h)."""
        sides = {name: len({r["hour_angle_h"] for r in rows if r["side"] == name}) for name in ("east", "west")}
        leverage = home_leverage(rows, dec)
        return (min(sides.values()) >= 2 and len(rows) >= 5
                and math.isfinite(leverage) and leverage <= limit), sides

    ok, sides = enough(rows)
    if not ok:
        raise Refusal("PLATE_SOLVE_FAILED", f"Too few places solved to find home: {sides['east']} on the east "
                      f"side and {sides['west']} on the west. It needs two on each and five in all, spread so "
                      f"that a random 1° error in each solve would leave home uncertain by under "
                      f"{HOME_LEVERAGE:g}° (these: {home_leverage(rows, dec):.1f}°).")
    answer, rms = fit(rows)
    used, left_out = rows, None
    # One bad place (a solve on the wrong stars, a gust) can spoil an account
    # the rest agree on, and with only a few places the fit bends towards it,
    # so the rms alone may not show it. Try leaving each out in turn; take
    # the best, but only if the others then fit and that one place sits far
    # from what they say. Never more than one.
    def without_each(rows):
        """The fit with each place left out in turn: [(rms, which, answer, the rest)]."""
        trials = []
        for i in range(len(rows)):
            rest = rows[:i] + rows[i + 1:]
            if enough(rest, limit=math.inf)[0]:
                trial, trial_rms = fit(rest)
                trials.append((trial_rms, i, trial, rest))
        return trials

    trials = without_each(rows)
    if trials:
        trial_rms, i, trial, rest = min(trials, key=lambda t: t[0])
        apart = miss(rows[i], trial)
        if trial_rms <= HOME_FITS and apart["miss_deg"] > max(2 * HOME_FITS, 4 * trial_rms):
            answer, rms, used, left_out = trial, trial_rms, rest, apart
    ra, dec_error, cone, p, q = (float(v) for v in answer)
    # Does the answer stand on all the places, or on one? Leave each out and
    # see how far home moves. With too few places to try that, it cannot be
    # told, and the answer is not acted on.
    again = without_each(used)
    sway = (max(max(abs(float(t[2][0]) - ra), abs(float(t[2][1]) - dec_error)) for t in again)
            if len(again) == len(used) else None)
    # How far out home is says nothing about whether the measurement is
    # sound: home is where it is (17 October 2026, 10.7° out by eye). Only
    # the places' agreement decides.
    believable = rms <= HOME_FITS and sway is not None and sway <= HOME_SWAY
    # How sure the two home errors are: the places' scatter about the fit
    # carried through their geometry (the usual least-squares figure).
    # With no figures to spare it cannot be said.
    model, spare = home_model(used, dec), 2 * len(used) - 5
    sigma = (np.sqrt(np.diag(np.linalg.inv(model.T @ model)))[:2] * rms * math.sqrt(2 * len(used) / spare)
             if spare > 0 else None)
    return {"ra_home_error_deg": round(ra, 3), "dec_home_error_deg": round(dec_error, 3),
            "ra_home_sigma_deg": None if sigma is None else round(float(sigma[0]), 3),
            "dec_home_sigma_deg": None if sigma is None else round(float(sigma[1]), 3),
            "leverage": round(home_leverage(used, dec), 2),
            "tube_not_square_deg": round(cone, 3), "polar_error_left_deg": round(math.hypot(p, q), 3),
            "polar_p_deg": round(p, 4), "polar_q_deg": round(q, 4),
            "rms_deg": round(rms, 3), "sway_deg": None if sway is None else round(sway, 3),
            "places": len(used), "fits": bool(believable),
            "why_not": None if believable else (
                f"the places sit {rms:.2f}° from it, and it needs {HOME_FITS:g}°" if rms > HOME_FITS else
                "too few places to check it by leaving each out" if sway is None else
                f"leaving one place out moves it {sway:.2f}°, and it needs {HOME_SWAY:g}°"),
            # An rms can hide one bad place among good ones: each place's own miss, for looking at.
            "residuals": [miss(row, answer) for row in used], "left_out": left_out}


def still_swinging(lum):
    """Whether a picture's stars are trailed: the tube still moving from a
    slew. The middle 1024 pixels square only, to keep it quick; the median
    roundness of its brightest stars (1 round, falling as they trail).
    With too few stars to judge (cloud, a sparse field) it is taken as
    settled: the solve says whether the picture is any use."""
    import stacking
    h, w = lum.shape
    middle = lum[max(0, h // 2 - 512):h // 2 + 512, max(0, w // 2 - 512):w // 2 + 512]
    import numpy as np
    stars = stacking.find_stars(middle, limit=30)
    return len(stars) >= SETTLE_STARS and float(np.median(stars[:, 4])) < SETTLED_ROUND


def home_model(rows, dec):
    """home_fit()'s equations for these places, two rows each: what each of
    the five unknowns does to the hour-angle error and to the Dec error."""
    import numpy as np
    shrink, slope = math.cos(math.radians(dec)), math.tan(math.radians(dec))
    model = []
    for row in rows:
        s = 1.0 if row["side"] == "east" else -1.0
        h = math.radians(row["hour_angle_h"] * 15)
        model.append([1, 0, s / shrink, -slope * math.cos(h), -slope * math.sin(h)])
        model.append([0, s, 0, math.sin(h), -math.cos(h)])
    return np.array(model)


def home_leverage(rows, dec, fixed=False):
    """How uncertain the home found from these places would be (the larger
    of the two axes) if each plate solve had a random, independent error of
    1°: their geometry alone, before anything is measured. A figure for
    conditioning, not a bound: an error shared by every solve (the camera's
    angle, flexure, a wrong axis reading) is not in it. Infinite when the
    places cannot tell the unknowns apart at all, as six places at two hour
    angles cannot. `fixed`: only the two home errors are unknown, the rest
    taken from an earlier fit (check_home)."""
    import numpy as np
    model = home_model(rows, dec)[:, :2] if fixed else home_model(rows, dec)
    unknowns = model.shape[1]
    if len(model) < unknowns or np.linalg.matrix_rank(model) < unknowns:
        return math.inf
    return float(np.sqrt(np.diag(np.linalg.inv(model.T @ model)))[:2].max())


def home_check(rows, dec, geometry):
    """The two home errors from places measured after a new home, with the
    tube's squareness and the polar axis held at what `geometry` (an
    accepted home_fit) found; how far the places sit from that account; and
    a verdict. Agreement is judged as home_fit judges it (HOME_FITS)."""
    import numpy as np
    sides = {name: len({r["hour_angle_h"] for r in rows if r["side"] == name}) for name in ("east", "west")}
    if min(sides.values()) < 2 or not math.isfinite(home_leverage(rows, dec, fixed=True)):
        raise Refusal("PLATE_SOLVE_FAILED", f"Too few places solved to check home: {sides['east']} on the east "
                      f"side and {sides['west']} on the west. It needs two on each.")
    model = home_model(rows, dec)
    seen = np.array([v for row in rows for v in (row["ha_error_deg"], row["dec_error_deg"])])
    seen = seen - model[:, 2:] @ np.array([geometry["tube_not_square_deg"], geometry["polar_p_deg"],
                                           geometry["polar_q_deg"]])
    answer = np.linalg.lstsq(model[:, :2], seen, rcond=None)[0]
    rms = float(np.sqrt(np.mean((model[:, :2] @ answer - seen) ** 2)))
    ra, dec_error = (float(v) for v in answer)
    agrees, right = rms <= HOME_FITS, max(abs(ra), abs(dec_error)) <= HOME_RIGHT
    verdict = ("The places do not agree with the earlier account of the tube and the polar axis (the bolts "
               f"turned since, or a bad solve): {rms:.2f}° where it needs {HOME_FITS:g}°. Nothing is settled; "
               "run ./mount.py findhome." if not agrees else
               f"Home is right, within the {HOME_RIGHT:g}° aimed for." if right else
               f"Home is still more than {HOME_RIGHT:g}° out. Run ./mount.py findhome for a full measurement "
               "before moving it again.")
    return {"ra_home_error_deg": round(ra, 3), "dec_home_error_deg": round(dec_error, 3), "rms_deg": round(rms, 3),
            "places": len(rows), "agrees": agrees, "home_right": bool(agrees and right), "verdict": verdict}


def load_geometry(dec):
    """The last accepted findhome's tube and polar axis, for check_home, or a
    refusal: none, from another declination, from a different link, or
    older than a night's session."""
    try:
        geometry = json.loads(GEOMETRY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise Refusal("INVALID_REQUEST", "No accepted findhome to check against (a polar alignment since sets it "
                      "aside, as the bolts may have turned). Run ./mount.py findhome.")
    if time.time() - geometry["saved"] > GEOMETRY_FRESH or geometry["dec_deg"] != dec \
            or geometry["link"] != home_reference()[0]:
        raise Refusal("INVALID_REQUEST", f"The last accepted findhome is more than {GEOMETRY_FRESH // 3600} hours "
                      f"old, at another declination (it was at {geometry['dec_deg']:+g}°), or on another link. "
                      "Run ./mount.py findhome.")
    return geometry


def forget_home_measurement():
    """The polar axis may just have been turned: a home measured before is
    of a mount that may no longer stand that way, so it is set aside, and
    so is the account `findhome --check` would use."""
    for gone in (HOME_FILE, GEOMETRY_FILE):
        if gone.exists():
            gone.replace(gone.with_name(gone.stem + ".previous.json"))


def home_target(found):
    """The axis readings where a home measurement puts home."""
    return {"ra_axis_deg": round(wrap(HOME_RA_AXIS - found["ra_home_error_deg"]), 3),
            "dec_axis_deg": round(HOME_DEC_AXIS - found["dec_home_error_deg"], 3)}


def home_reference():
    """(the link, the motor counts home is recorded at) as they are now,
    from the files alone. A handset keeps its home to itself (None): only
    its clock being set again says it was restarted. Without one, home is
    the counts direct.py recorded, which a sethome, a truehome or the board
    switched off and on changes."""
    import os
    board = os.environ.get("TY_DEMO_BOARD") if config.DEMO else None
    if not board and (config.DEMO or mount_settings().get("link", "handset") == "handset"):
        return "handset", None
    import direct
    state = config.DATA / "cache" / "demo_direct_mount.json" if config.DEMO else direct.STATE_FILE
    try:
        return "direct", json.loads(state.read_text(encoding="utf-8")).get("home")
    except (OSError, ValueError):
        return "direct", None


def keep_pointing(survey):
    """Keep each side's average error from a pointing survey as that side's pointing error."""
    for name, side in survey["sides"].items():
        save_pointing_error([side["ha_error_deg"], side["dec_error_deg"]], west=name == "west")


def forget_pointing():
    """Home has just been recorded somewhere else (direct.py): every axis
    reading has moved by the difference, and a pointing error or home
    measured against the old one would be added to a home already moved."""
    for gone in (POINTING_FILE, HOME_FILE):
        gone.unlink(missing_ok=True)


def plan_true_home():
    """What `truehome` would do, from the home measurement in hand. Raises a
    Refusal if there is none, if it was made before the handset was last set
    up or more than two hours ago, or if its model did not fit: a move is
    only ever made on a measurement from this session. Needs no hardware."""
    if LOCK_FILE.exists():
        raise Refusal("MOTION_LOCKED", f"Motion is locked: {LOCK_FILE.read_text(encoding='utf-8').strip()}")
    try:
        found = json.loads(HOME_FILE.read_text(encoding="utf-8"))
        since = json.loads(CLOCK_FILE.read_text(encoding="utf-8"))["saved"]
    except (OSError, ValueError, KeyError):
        raise Refusal("INVALID_REQUEST", "Home has not been measured this session. Run ./mount.py findhome first.")
    age = time.time() - found["saved"]
    if found["saved"] < since or age > HOME_FRESH:
        raise Refusal("INVALID_REQUEST", "The home measurement is from before the handset was last set up, or "
                      "more than two hours old. Run ./mount.py findhome again; nothing is moved on an old one.")
    # Home as it was recorded when this was measured, or it measured a home
    # that is no longer there. A handset's own restart cannot be seen from
    # here: settime after switching it on is what says so.
    if [found.get("link"), found.get("home_counts")] != list(home_reference()):
        raise Refusal("INVALID_REQUEST", "Home has been recorded again, or the link changed, since this was "
                      "measured (a sethome, a truehome, or the motor board switched off and on). Run "
                      "./mount.py findhome again; nothing is moved on an old one.")
    if not found.get("rows"):
        raise Refusal("INVALID_REQUEST", "The home measurement has no places to check it by. Run "
                      "./mount.py findhome again.")
    # Judged again from its own places, so a measurement is held to the rules
    # as they are now, and the move is made to what that judgement found.
    refit = home_fit(found["rows"], found["dec_deg"])
    if not refit["fits"]:
        raise Refusal("INVALID_REQUEST", f"The last home measurement is not acted on: "
                      f"{refit.get('why_not') or 'it did not fit'}. Run ./mount.py findhome again.")
    goes, kept = home_target(refit), found.get("goes_to")
    changed = (max(abs(wrap(goes["ra_axis_deg"] - kept["ra_axis_deg"])),
                   abs(goes["dec_axis_deg"] - kept["dec_axis_deg"])) if kept else 0.0)
    found = dict(found, ra_home_error_deg=refit["ra_home_error_deg"], dec_home_error_deg=refit["dec_home_error_deg"])
    return {"would_move": True, "safe": True, "ra_axis_deg": goes["ra_axis_deg"], "dec_axis_deg": goes["dec_axis_deg"],
            "measured_minutes_ago": round(age / 60),
            "warnings": [f"Goes home by the axis readouts, then {abs(found['dec_home_error_deg']):.2f}° on the Dec "
                         f"axis and {abs(found['ra_home_error_deg']):.2f}° on the RA axis, to where home was "
                         "measured to be, and holds there with tracking off. If the tube is on the west side "
                         "it comes back over the pole on the way, as for ./mount.py home. Without a handset "
                         "(the Wi-Fi adapter or EQDIR) it is then recorded as home, as ./mount.py sethome does.",
                         "The readings are the motors' own, so the gears' slack (a few arcminutes) is not in "
                         "them; findhome after the restart shows what is left."]
            + ([f"Worked out again from its places, home is {changed:.2f}° from where it was kept when "
                "measured: the fit has changed since. The new answer is the one used."] if changed > 0.01 else [])}


def use_demo_cache():
    """Keep the simulated mount's measurements apart from the real one's."""
    global CLOCK_FILE, POINTING_FILE, DRIFT_FILE
    CLOCK_FILE = config.DATA / "cache" / "demo_handset_clock.json"
    POINTING_FILE = config.DATA / "cache" / "demo_pointing.json"
    DRIFT_FILE = config.DATA / "cache" / "demo_drift_model.json"


def load_pointing_error(west):
    """(hour angle, Dec) error in degrees from the last plate solve, if it was
    measured since the handset's clock was. `west` says which side of the
    meridian the target is on. Each side keeps what was last measured on it.
    A side not yet measured borrows the other's with Dec reversed: the error
    comes mostly from the home position being set by eye, and a Dec-axis
    offset reverses when the tube swings over the pole. That is only a first
    guess. On 6 October 2026, with the polar axis 0.2° from the pole, the
    real mount was 5.8° out in Dec on the east side and 0.2° on the west,
    and every first GoTo across the meridian missed by 6°."""
    if POINTING_FILE.exists() and CLOCK_FILE.exists():
        saved = json.loads(POINTING_FILE.read_text(encoding="utf-8"))
        since = json.loads(CLOCK_FILE.read_text(encoding="utf-8"))["saved"]
        here = saved.get("sides", {}).get(side_name(west))
        if here and here["saved"] > since:
            return list(here["error_deg"])
        if saved["saved"] > since:
            ha, dec = saved["error_deg"]
            return [ha, dec if saved["west"] == west else -dec]
    return [0.0, 0.0]


def pointing_measured(west):
    """Whether this side's pointing error was plate-solved on this side since
    the handset's clock was set, not borrowed from the other side's."""
    if not (POINTING_FILE.exists() and CLOCK_FILE.exists()):
        return False
    saved = json.loads(POINTING_FILE.read_text(encoding="utf-8"))
    since = json.loads(CLOCK_FILE.read_text(encoding="utf-8"))["saved"]
    here = saved.get("sides", {}).get(side_name(west))
    return bool(here) and here["saved"] > since


def over_pole(dec_axis):
    """Whether the tube is swung over the pole (the west side), from the Dec
    axis: past 90° and short of 270°. The axis reads round to 360°, so a
    target south of the equator on the east side reads, say, 357°, which is
    not over the pole (3 November 2026: M2 at Dec -1° read as the west side,
    and its GoTo took the other side's correction)."""
    return 90 < dec_axis % 360 < 270


def side_name(west):
    return "west" if west else "east"


def save_pointing_error(error, west):
    """Keep the error for this side, and leave the other side's as it was."""
    sides = {}
    if POINTING_FILE.exists():
        sides = json.loads(POINTING_FILE.read_text(encoding="utf-8")).get("sides", {})
    now = time.time()
    sides[side_name(west)] = {"error_deg": list(error), "saved": now}
    # The newest is also kept at the top, as it always was.
    records.write(POINTING_FILE, {"error_deg": list(error), "west": bool(west), "saved": now, "sides": sides},
                  indent=None)


def location(site):
    from astropy import units as u
    from astropy.coordinates import EarthLocation
    return EarthLocation(lat=site["latitude"] * u.deg, lon=site["longitude"] * u.deg,
                         height=site.get("elevation_m", 0) * u.m)


def true_sidereal(site):
    """Local apparent sidereal time in degrees, from the laptop's clock."""
    import sky  # noqa: F401  (configures astropy to stay offline)
    from astropy.time import Time
    return Time.now().sidereal_time("apparent", location(site).lon).deg


# Bright stars for focusing and alignment: J2000 RA in hours, Dec in degrees.
STARS = {
    "Vega": (18.6156, 38.7837), "Arcturus": (14.2610, 19.1825),
    "Capella": (5.2782, 45.9981), "Deneb": (20.6905, 45.2803),
    "Altair": (19.8464, 8.8683), "Aldebaran": (4.5987, 16.5092),
    "Betelgeuse": (5.9195, 7.4069), "Rigel": (5.2423, -8.2017),
    "Procyon": (7.6550, 5.2250), "Pollux": (7.7553, 28.0261),
    "Regulus": (10.1395, 11.9672), "Mizar": (13.3987, 54.9253),
    "Dubhe": (11.0621, 61.7508), "Alpheratz": (0.1398, 29.0906),
    "Mirfak": (3.4054, 49.8611),
    # Autumn's, added the night the user could name what showed through a
    # gap in the cloud and the telescope could not be sent to it.
    "Markab": (23.0794, 15.2053), "Scheat": (23.0629, 28.0828),
    "Algenib": (0.2206, 15.1836), "Mirach": (1.1622, 35.6206),
    "Hamal": (2.1196, 23.4625), "Enif": (21.7364, 9.8750),
    "Sadr": (20.3705, 40.2567), "Albireo": (19.5120, 27.9597),
}


PLANETS = ("mercury", "venus", "mars", "jupiter", "saturn", "uranus", "neptune", "moon")


def offset_target(target, east_arcmin, north_arcmin):
    """A target moved on the sky by arcminutes east and north."""
    dec = target["dec"] + north_arcmin / 60
    ra = (target["ra"] + east_arcmin / 60 / max(math.cos(math.radians(target["dec"])), 1e-3)) % 360
    return dict(target, ra=ra, dec=dec)


def find_target(name):
    import mosaic
    import sky
    panel = mosaic.find_panel(name)
    if panel:
        return panel
    wanted = name.replace(" ", "").lower()
    for star, (ra_hours, dec) in STARS.items():
        if star.lower() == wanted:
            return {"id": star, "name": "star", "ra": ra_hours * 15, "dec": dec}
    for t in sky.load_targets():
        # Its other names too (Caldwell, Sharpless, Barnard... from Gary
        # Imm's Compendium when it is here): only finding it, never where.
        if wanted in (t["id"].replace(" ", "").lower(), t["alt_id"].replace(" ", "").lower(),
                      t["name"].replace(" ", "").lower(),
                      *(a.replace(" ", "").lower() for a in t.get("aliases", ()))):
            return t
    if wanted in PLANETS:
        # A planet is where it is tonight, not where a catalogue put it. Never
        # the Sun: nothing here is to point a telescope at it.
        from astropy.coordinates import get_body
        from astropy.time import Time
        site = (config.load() if config.FILE.exists() and not config.DEMO else config.example())["site"]
        body = get_body(wanted, Time.now(), location(site))
        return {"id": wanted.capitalize(), "alt_id": "", "name": "planet",
                "ra": float(body.ra.deg), "dec": float(body.dec.deg)}
    # A transient a person chose to follow (brokers.py --follow), by its name.
    kept = config.DATA / "cache" / "transients.json"
    if kept.exists():
        for key, t in json.loads(kept.read_text(encoding="utf-8")).items():
            if key.replace(" ", "").lower() == wanted:
                # "kind": "field" marks a place kept by name that is not one star, as M81-M82.
                return {"id": key, "alt_id": t.get("alt_id", ""), "name": "transient", "kind": t.get("kind"),
                        "ra": t["ra"], "dec": t["dec"]}
    raise Refusal("TARGET_UNKNOWN", f"'{name}' is not in the catalogue.")


def where(target, site, when=None):
    """(hour angle, declination, altitude) in degrees, now or at the astropy
    Time `when`, as seen from the site with precession applied."""
    import sky  # noqa: F401
    from astropy import units as u
    from astropy.coordinates import AltAz, HADec, SkyCoord
    from astropy.time import Time
    now, here = when or Time.now(), location(site)
    coord = SkyCoord(ra=target["ra"] * u.deg, dec=target["dec"] * u.deg)
    hadec = coord.transform_to(HADec(obstime=now, location=here))
    altitude = coord.transform_to(AltAz(obstime=now, location=here)).alt.deg
    return hadec.ha.deg, hadec.dec.deg, altitude


def wrap(angle):
    """Fold an angle difference into -180..180."""
    return (angle + 180) % 360 - 180


def encode(degrees):
    return f"{int(round(degrees % 360 / 360 * 2**32)) & 0xFFFFFF00:08X}"


def snapshot(mount):
    """Where the mount is and what it is doing, as plain data."""
    ra, dec = mount.radec()
    ra_axis, dec_axis = mount.axes()
    return {"state": mount.state(), "at_home": mount.at_home(),
            "ra_hours": round(ra / 15, 4), "dec_deg": round(wrap(dec), 3),
            "ra_axis_deg": round(ra_axis, 2), "dec_axis_deg": round(dec_axis, 2),
            "pier_side": "west" if over_pole(dec_axis) else "east",
            "motion_locked": LOCK_FILE.exists()}


def report(mount):
    now = snapshot(mount)
    state = "at home" if now["at_home"] else now["state"]
    print(f"{state}: RA {now['ra_hours']:.4f} h, Dec {now['dec_deg']:+.2f}°  "
          f"(axes: RA {now['ra_axis_deg']:.2f}°, Dec {now['dec_axis_deg']:.2f}°)")
    return now


def main():
    # Each line out as it is printed, so a log being tailed (a run left in
    # the background) shows progress, not nothing until the end
    # (18 November 2026: a guiding calibration's log stayed empty for 5 min).
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["status", "settime", "nudge", "zenith", "home", "stop", "goto", "point",
                                       "sync", "drift", "compensate", "pointing",
                                       "findhome", "truehome",
                                       "sethome", "directions"])
    ap.add_argument("target", nargs="*",
                    help="object for goto (e.g. M81), or bearing and height for point")
    ap.add_argument("--port", help="serial port (default: found by the adapter name "
                                   "in config.toml)")
    ap.add_argument("--no-watch", action="store_true", help="skip the webcam pictures")
    ap.add_argument("--solve", action="store_true",
                    help="with goto: plate-solve and correct until centred")
    ap.add_argument("--demo", action="store_true",
                    help="use a simulated mount at the example site; nothing moves")
    ap.add_argument("--json", action="store_true",
                    help="answer in JSON on stdout (see schemas/)")
    ap.add_argument("--dry-run", action="store_true",
                    help="check the move against the limits and say what it would do; "
                         "nothing moves and no hardware is needed")
    ap.add_argument("--hours", type=float, nargs="+", default=list(SURVEY_HOURS), metavar="H",
                    help="with pointing and findhome: the hour angles to visit, in hours from the meridian (east is negative)")
    ap.add_argument("--dec", type=float, default=SURVEY_DEC, help="with pointing: the declination to visit them at")
    ap.add_argument("--check", action="store_true",
                    help="with findhome: after truehome, check home from four places, the tube and the polar "
                         "axis taken from the last accepted findhome; nothing is kept for truehome")
    ap.add_argument("--aim-off", type=float, nargs=2, default=[0.0, 0.0], metavar=("EAST", "NORTH"),
                    help="with goto: aim this many arcminutes east and north of the object, to centre "
                         "one plate solving cannot, such as the Moon (west and south are negative)")
    ap.add_argument("--record", metavar="FOLDER",
                    help="keep each plate-solve frame and message there, for replay.py to animate "
                         "(findhome keeps its own under cache/findhome/ unasked)")
    ap.add_argument("--clearance-test", action="store_true",
                    help=f"with point: go past the hour-angle limit, up to {CLEARANCE_TEST_HOURS:g} h and no lower "
                         f"than {MIN_ALTITUDE}°, to find with someone watching where the tube meets the tripod")
    args = ap.parse_args()
    if args.clearance_test and args.command != "point":
        ap.error("--clearance-test goes with point only")
    stop_on_termination()

    args.demo = args.demo or config.DEMO
    if args.demo and not config.DEMO:
        if args.command in ("sync", "drift", "compensate", "pointing", "findhome") and not args.dry_run:
            ap.error(f"{args.command} needs the real camera; there is no demo of it")
        if args.command in ("sethome", "directions"):
            ap.error(f"{args.command} is for a real mount reached without its handset")
        use_demo_cache()
        site = config.example()["site"]
    elif args.command in ("stop", "status") and not own_site_set():
        # Stop must work whatever state config.toml is in (missing, broken,
        # the example's); neither command needs to know where it is.
        site = config.example()["site"]
    else:
        site = config.load()["site"]
    if args.command == "goto" and not args.target:
        ap.error("goto needs a target, e.g. goto M81")
    if any(args.aim_off) and (args.command != "goto" or args.solve):
        ap.error("--aim-off goes with goto, without --solve, which centres the object itself")
    if args.command == "point" and len(args.target) != 2:
        ap.error("point needs a bearing and a height, e.g. point 225 10")

    if args.dry_run:
        sys.exit(dry_run(args, site))
    if args.json:
        from contextlib import redirect_stdout
        # The progress messages people read go to stderr, so stdout holds
        # exactly one JSON document.
        with redirect_stdout(sys.stderr):
            result = answer(f"mount.{args.command}", lambda: act(args, site))
        sys.exit(emit(result))
    act(args, site)


def dry_run(args, site):
    """Say what a command would do, as JSON or a sentence. Returns an exit code."""
    def plan():
        if args.command not in ("status", "stop") and not args.demo:
            refuse_example_site(site)
        if args.command == "goto":
            return plan_goto(" ".join(args.target), site)
        if args.command == "point":
            return plan_point(float(args.target[0]), float(args.target[1]), site, args.clearance_test)
        if args.command in ("status", "sync", "drift", "stop"):
            return {"would_move": False, "safe": True, "warnings": []}
        if args.command == "settime":
            return {"would_move": False, "safe": True,
                    "warnings": ["Sets the handset's date, time and position from this computer. The handset "
                                 "must be at its main menu. Nothing moves.",
                                 nudge_step(config.example() if args.demo else None)]}
        if args.command == "truehome":
            return plan_true_home()
        if args.command == "findhome" and args.check:
            geometry = load_geometry(args.dec)
            hours = CHECK_HOURS if tuple(args.hours) == SURVEY_HOURS else args.hours
            spots, notes = plan_survey(site, hours, args.dec, config.load().get("horizon") if not args.demo else None,
                                       for_home=True, check=True)
            return {"would_move": True, "safe": True, "hour_angles_h": spots, "dec_deg": args.dec,
                    "warnings": [f"Slews to {len(spots)} places at Dec {args.dec:+g}°, plate-solving at each, and "
                                 "finds the two home errors with the tube and the polar axis as the findhome of "
                                 f"{time.strftime('%H:%M', time.localtime(geometry['saved']))} found them."] + notes}
        if args.command in ("pointing", "findhome"):
            spots, notes = plan_survey(site, args.hours, args.dec, config.load().get("horizon") if not args.demo else None,
                                       for_home=args.command == "findhome")
            return {"would_move": True, "safe": True, "hour_angles_h": spots, "dec_deg": args.dec,
                    "warnings": [f"Slews to {len(spots)} places at Dec {args.dec:+g}°, plate-solving at each."] + notes}
        if args.command == "sethome":
            return {"would_move": False, "safe": True,
                    "warnings": ["Records where the motors are now as the home position. Only "
                                 "right if the mount really is at home."]}
        if LOCK_FILE.exists():
            raise Refusal("MOTION_LOCKED", f"Motion is locked: {LOCK_FILE.read_text(encoding='utf-8').strip()}")
        notes = {"nudge": f"From home, tips the tube {NUDGE:g}° away from the pole on the Dec axis, holds "
                          "three seconds and brings it back. The counterweight bar does not move.",
                 "home": "Returns to the home position, by the axis readouts.",
                 "zenith": "Goes home if not there, then slews to straight up.",
                 "compensate": "Slews about 25° twice on the side of the meridian it is on, "
                               "then returns.",
                 "directions": "Tips the tube 5° from home on the Dec axis, asks which way it "
                               "went, and puts it back. Someone must be watching the mount."}
        return {"would_move": True, "safe": True, "warnings": [notes[args.command]]}

    result = answer(f"mount.{args.command}.dry_run", plan)
    if result["ok"]:
        result["warnings"] = result["data"].pop("warnings", [])
        result["data"].pop("side_note", None)
    if args.json:
        return emit(result)
    if not result["ok"]:
        print(f"Would refuse: {result['errors'][0]['message']}")
        return 1
    data = result["data"]
    if "altitude_deg" in data:
        print(f"Would slew to altitude {data['altitude_deg']:.0f}°, hour angle "
              f"{data['hour_angle_hours']:+.2f} h, on the {data['pier_side']} side.")
    else:
        print("Would move the mount." if data["would_move"] else "Would not move the mount.")
    for warning in result["warnings"]:
        print(f"Note: {warning}")
    return 0


def nudge_step(cfg=None):
    """What the setup routine does after settime: the motor check (the nudge),
    or straight on to focus when it is turned off ([mount] nudge_check)."""
    if (cfg or config.hardware())["mount"].get("nudge_check", True):
        return "Next in the setup routine: the motor check, ./mount.py nudge, with someone watching."
    return ("The motor check (the nudge) is off in the settings ([mount] nudge_check): after asking where "
            "it is clear, go straight to focus.")


def is_example_site(site):
    example = config.example()["site"]
    return (site["latitude"], site["longitude"]) == (example["latitude"], example["longitude"])


def own_site_set():
    """Whether config.toml has a location of its own: there, readable, and not
    the example's. Never raises: stop and status must work without one."""
    try:
        return config.FILE.exists() and not is_example_site(config.load()["site"])
    except (Exception, SystemExit):      # noqa: BLE001 - an unreadable file (or a bad spot name) is no site, not a crash
        return False


def mount_settings():
    """[mount] from config.toml, or the example's when the file cannot be read:
    stop must reach the mount whatever state the file is in, and with no site
    of its own may_move refuses everything else."""
    try:
        return config.hardware()["mount"]
    except Exception:      # noqa: BLE001 - a broken file must not stop a stop
        return config.example()["mount"]


def refuse_example_site(site):
    """The limits (altitude, the meridian, the Sun) and the handset's time
    and place are worked out for the site: config.example.toml's, copied by
    the installer and never changed, would judge every move for Greenwich.
    The CLI says so before the port is opened; Mount.may_move holds it for
    every other command that moves the mount."""
    if is_example_site(site):
        raise Refusal("SITE_NOT_SET", "config.toml still has the example location: set your own "
                                      "latitude and longitude before the mount is used.")


def act(args, site):
    """Carry a command out on the mount (or the simulated one). Returns the
    mount's state afterwards."""
    if args.command not in ("status", "stop") and not args.demo:
        refuse_example_site(site)

    if args.command in ("nudge", "zenith", "home", "goto", "point", "compensate", "pointing", "findhome",
                        "truehome", "directions") and LOCK_FILE.exists():
        raise Refusal("MOTION_LOCKED", f"Motion is locked: {LOCK_FILE.read_text(encoding='utf-8').strip()}")

    mount = Mount(args.port, watch=not args.no_watch, demo=args.demo)
    if args.record:
        mount.record(args.record)
    if args.command in AWAY:
        import director
        director.clear()        # the telescope leaves its target: the stream names none
    try:
        if args.command == "stop":
            mount.stop()
        elif args.command != "status":
            if args.command == "settime":
                mount.set_clock(site)
            elif args.command == "nudge":
                mount.nudge()
            elif args.command == "zenith":
                mount.zenith(site)
            elif args.command == "goto":
                mount.goto_target(" ".join(args.target), site, solve=args.solve,
                                  aim_off=tuple(args.aim_off))
            elif args.command == "point":
                mount.point(float(args.target[0]), float(args.target[1]), site, args.clearance_test)
            elif args.command == "home":
                mount.home()
            elif args.command == "sync":
                mount.sync(site)
            elif args.command == "drift":
                mount.cancel_drift(site)
            elif args.command == "compensate":
                mount.compensate(site)
            elif args.command == "pointing":
                mount.pointing_survey(site, args.hours, args.dec, config.load().get("horizon"))
            elif args.command == "findhome":
                mount.find_home(site, args.hours, args.dec, config.load().get("horizon"), check=args.check)
            elif args.command == "truehome":
                mount.true_home()
            elif args.command == "sethome":
                mount.set_home()
            elif args.command == "directions":
                mount.check_directions()
    except BaseException:
        # Never leave a motor running after an error or Ctrl+C.
        mount.stop()
        raise
    return report(mount)


if __name__ == "__main__":
    main()
