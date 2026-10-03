#!/usr/bin/env python3
"""Drive the mount through the SynScan handset's serial port.

    ./mount.py status     where it is pointing, and whether it is moving
    ./mount.py zenith     point straight up and hold there (tracking off)
    ./mount.py goto M81   point at a catalogue object and track it
    ./mount.py goto M81 --solve   ...then photograph the sky, work out the real
                          aim, and correct it until the object is centred
    ./mount.py point 225 10   point at compass bearing 225°, 10° up, and hold
    ./mount.py drift      measure how fast the aim is sliding and set the Dec
                          motor creeping the other way to cancel it. Makes up
                          for a rough polar alignment. Repeat after a big slew.
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
import glob
import json
import math
import time
from pathlib import Path

import serial

import config
from watch import Watching

ROOT = Path(__file__).parent
# How far the handset's idea of sidereal time is from the true one, in degrees.
# Its clock and location are wrong, so every GoTo is corrected by this. It
# holds until the handset is switched off.
CLOCK_FILE = ROOT / "cache" / "handset_clock.json"
MIN_ALTITUDE = 20
# Furthest from the meridian a GoTo may point, in hours. Beyond 6 h the tube
# is under the pole and swings down towards the tripod legs.
MAX_HOUR_ANGLE = 5.75
# While this file exists, nothing that moves the mount will run. Its contents
# say why. Delete it only once the cause has been dealt with.
LOCK_FILE = ROOT / "MOTION_LOCKED"
# Pointing error found by plate solving, carried into later GoTos.
POINTING_FILE = ROOT / "cache" / "pointing.json"
CENTRED = 2 / 60  # degrees; close enough to stop correcting
# Dec motor creep rate that cancels the drift, from `mount.py drift`.
DRIFT_FILE = ROOT / "cache" / "drift.json"
SETTLE = 30       # seconds to wait after a slew before photographing

# Raw axis angles, in degrees, as the handset's "z" query reports them.
HOME_RA_AXIS = 0.0
HOME_DEC_AXIS = 90.0
# RA axis angle at which the tube is on the meridian.
MERIDIAN_RA_AXIS = 90.0

RA, DEC = 16, 17            # axis ids for fixed-rate slews
POSITIVE, NEGATIVE = 36, 37
# Fixed-rate stages for closing in on an axis angle: (rate 1-9, stop within °).
STAGES = ((8, 2.0), (6, 0.25), (4, 0.03))
SLEW_TIMEOUT = 150


class Mount:
    def __init__(self, port=None, watch=True, demo=False, handset=None):
        """`demo` drives a simulated handset; `handset` supplies one directly
        (anything with the serial port's write/read_until interface)."""
        self.demo = demo or handset is not None
        self.recording = None   # folder to keep each solve frame and message in
        # The webcam photographs the scope during every real move unless told
        # not to.
        self.watching = Watching if watch and not self.demo else contextlib.nullcontext
        if self.demo:
            from simulator import SimulatedHandset
            self.s = handset or SimulatedHandset()
        else:
            # The handset's lead is recognised by its USB adapter's name.
            match = config.hardware()["mount"]["serial_match"]
            port = port or next(iter(sorted(glob.glob(f"/dev/serial/by-id/*{match}*"))),
                                "/dev/ttyUSB0")
            self.s = serial.Serial(port, 9600, timeout=2)
        if self.ask(b"Kx") != b"x#":
            raise SystemExit("The handset is not answering. Is it on and past its "
                             "start-up screens?")
        # The handset answers even while still on its version screen, where it
        # has not read the mount's gearing and moves by the wrong amounts. Its
        # clock shows the default year 2022 until someone sets it up.
        clock = self.ask(b"h")
        if len(clock) == 9 and clock[5] == 22:
            raise SystemExit("The handset has not been set up since power-on (its "
                             "date is still the default). Press ENTER through its "
                             "start-up screens to the main menu, entering today's date.")

    def record(self, folder):
        """Keep every plate-solve frame and progress message from now on, for
        replay.py to turn into an animation."""
        self.recording = Path(folder)
        self.recording.mkdir(parents=True, exist_ok=True)
        (self.recording / "steps.json").write_text("[]")

    def say(self, text):
        """Print a progress message, and note it in the recording if any."""
        print(text, flush=True)
        if self.recording:
            steps = json.loads((self.recording / "steps.json").read_text())
            frames = len(list(self.recording.glob("frame-*.jpg")))
            steps.append({"text": text, "frame": frames, "time": time.time()})
            (self.recording / "steps.json").write_text(json.dumps(steps, indent=1))

    def ask(self, command):
        self.s.reset_input_buffer()
        self.s.write(command)
        return self.s.read_until(b"#", 64)

    def _pair(self, command):
        # The handset occasionally drops a reply while it is busy; ask again.
        for _ in range(4):
            reply = self.ask(command)
            if len(reply) == 18:
                return [int(x, 16) / 2**32 * 360 for x in reply[:-1].decode().split(",")]
            time.sleep(0.5)
        raise SystemExit("The handset stopped answering position queries.")

    def radec(self):
        """Sky position (RA, Dec) in degrees, as the handset believes it."""
        return self._pair(b"e")

    def axes(self):
        """Raw (RA axis, Dec axis) angles in degrees."""
        return self._pair(b"z")

    def slewing(self):
        return self.ask(b"L").startswith(b"1")

    def at_home(self):
        ra_axis, dec_axis = self.axes()
        return abs(wrap(HOME_RA_AXIS - ra_axis)) < 0.3 and abs(HOME_DEC_AXIS - dec_axis) < 0.3

    # --- motion -------------------------------------------------------------

    def rate(self, axis, direction, rate):
        self.ask(bytes([ord("P"), 2, axis, direction, rate, 0, 0, 0]))

    def stop(self):
        self.ask(b"M")  # cancel any GoTo
        for axis in (RA, DEC):
            self.rate(axis, POSITIVE, 0)
            self.rate(axis, NEGATIVE, 0)

    def tracking(self, on):
        # Mode 2 is equatorial tracking, 0 is off.
        self.ask(b"T" + bytes([2 if on else 0]))

    def dec_creep(self, rate):
        """Turn the Dec axis steadily at `rate` arcseconds per second
        (positive raises the axis readout); 0 stops it. The handset takes the
        rate in quarter-arcsecond steps."""
        steps = min(round(abs(rate) * 4), 0xFFFF)
        self.ask(bytes([ord("P"), 3, DEC, 6 if rate >= 0 else 7, steps >> 8, steps & 0xFF, 0, 0]))

    def apply_drift_correction(self):
        """Restart the stored Dec creep, if it was measured on this side of
        the mount since the handset was last set up."""
        if not (DRIFT_FILE.exists() and CLOCK_FILE.exists()):
            return
        saved = json.loads(DRIFT_FILE.read_text())
        if (saved["saved"] > json.loads(CLOCK_FILE.read_text())["saved"]
                and saved["west"] == (self.axes()[1] > 90)):
            self.dec_creep(saved["dec_axis_rate"])

    def measure_drift(self, site, gap=45):
        """Plate-solve twice, `gap` seconds apart, and return how fast the aim
        is sliding across the sky as (east-west, Dec) in arcseconds per
        second, or None. Zero means perfect tracking."""
        offset = json.loads(CLOCK_FILE.read_text())["offset_deg"]
        error = load_pointing_error(self.axes()[1] > 90)
        sidereal = true_sidereal(site)
        believed_ha = wrap(sidereal + offset - self.radec()[0]) + error[0]
        first = self.where_really(sidereal - believed_ha, wrap(self.radec()[1]) + error[1],
                                  radius=20)
        if not first:
            return None
        time.sleep(gap)
        second = self.where_really(first["ra"], first["dec"], radius=5)
        if not second:
            return None
        # A perfectly tracked aim keeps the same sky coordinates.
        seconds = (second["when"] - first["when"]).sec
        east_west = wrap(second["ra"] - first["ra"]) * math.cos(math.radians(first["dec"]))
        return east_west * 3600 / seconds, (second["dec"] - first["dec"]) * 3600 / seconds

    def cancel_drift(self, site):
        """Measure the drift and set the Dec motor creeping against it, then
        measure again and refine."""
        west = self.axes()[1] > 90
        rate = 0.0
        if DRIFT_FILE.exists():
            saved = json.loads(DRIFT_FILE.read_text())
            if saved["west"] == west:
                rate = saved["dec_axis_rate"]
        self.dec_creep(rate)
        for attempt in range(3):
            drift = self.measure_drift(site)
            if drift is None:
                raise SystemExit("Could not plate-solve; drift not measured.")
            print(f"drift: {drift[0]:+.2f} arcsec/s east-west, {drift[1]:+.2f} in Dec "
                  f"(Dec motor creeping at {rate:+.2f})", flush=True)
            if abs(drift[1]) < 0.15:
                break
            # With the tube over the pole (west side), raising the axis
            # readout lowers the Dec the scope points at.
            rate += drift[1] if west else -drift[1]
            self.dec_creep(rate)
            DRIFT_FILE.write_text(json.dumps(
                {"dec_axis_rate": rate, "west": west, "saved": time.time()}))
            # The Dec gears have slack, so a new rate takes a while to bite.
            time.sleep(60)

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
        time.sleep(1.5)
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
                    raise SystemExit("Axis did not arrive in time; stopped.")
            self.rate(axis, direction, 0)
            time.sleep(0.5)

    def goto(self, ra, dec):
        """Handset GoTo to a sky position in degrees; waits until it stops."""
        with self.watching():
            if self.ask(f"r{encode(ra)},{encode(dec)}".encode()) != b"#":
                raise SystemExit("The handset refused the GoTo.")
            began = time.monotonic()
            while self.slewing():
                if time.monotonic() - began > SLEW_TIMEOUT:
                    self.stop()
                    raise SystemExit("GoTo did not finish in time; stopped.")
                time.sleep(1)

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
        with self.watching():
            # Dec first, so the tube is up by the pole before the RA axis swings.
            self.seek(DEC, HOME_DEC_AXIS)
            self.seek(RA, HOME_RA_AXIS)

    def zenith(self, site):
        # The handset's GoTo picks the correct side of the mount, but only
        # behaves predictably from the home position.
        if not self.at_home():
            self.home()
        self.goto(self.handset_sidereal(), site["latitude"])
        self.tracking(False)
        self.save_clock(site)

    def save_clock(self, site):
        offset = wrap(self.handset_sidereal() - true_sidereal(site))
        CLOCK_FILE.parent.mkdir(exist_ok=True)
        CLOCK_FILE.write_text(json.dumps({"offset_deg": offset, "saved": time.time()}))

    def point(self, azimuth, altitude, site):
        """Aim at a fixed direction, e.g. a distant rooftop, and hold there."""
        if not CLOCK_FILE.exists():
            # Reading the handset's clock needs no movement, so do it now.
            self.save_clock(site)
        if not 2 <= altitude <= 89:
            raise SystemExit("Altitude must be between 2° and 89°.")
        offset = json.loads(CLOCK_FILE.read_text())["offset_deg"]
        hour_angle, dec = direction(azimuth, altitude, site)
        if abs(hour_angle) > MAX_HOUR_ANGLE * 15:
            raise SystemExit(f"That is {abs(hour_angle) / 15:.1f} h from the meridian, "
                             f"beyond the {MAX_HOUR_ANGLE} h limit; not slewing.")
        side = "west: the tube will swing over the pole" if hour_angle > 0 else "east"
        print(f"bearing {azimuth:.0f}°, {altitude:.0f}° up: hour angle "
              f"{hour_angle / 15:+.2f} h, Dec {dec:+.1f}° ({side})")
        self.goto((true_sidereal(site) + offset - hour_angle) % 360, dec)
        self.tracking(False)

    def goto_target(self, name, site, solve=False):
        if not CLOCK_FILE.exists():
            # Reading the handset's clock needs no movement, so do it now.
            self.save_clock(site)
        offset = json.loads(CLOCK_FILE.read_text())["offset_deg"]
        target = find_target(name)
        hour_angle, dec, altitude = where(target, site)
        if altitude < MIN_ALTITUDE:
            raise SystemExit(f"{target['id']} is only {altitude:.0f}° up; not slewing.")
        if abs(hour_angle) > MAX_HOUR_ANGLE * 15:
            raise SystemExit(
                f"{target['id']} is {abs(hour_angle) / 15:.1f} h from the meridian, "
                f"beyond the {MAX_HOUR_ANGLE} h limit; not slewing.")
        side = "west: the tube will swing over the pole" if hour_angle > 0 else "east"
        self.say(f"{target['id']} {target['name']}: altitude {altitude:.0f}°, "
                 f"hour angle {hour_angle / 15:+.2f} h ({side})")
        # Ask for the RA that puts the tube at the true hour angle, less the
        # pointing error measured by earlier plate solves.
        west = hour_angle > 0
        error = load_pointing_error(west)
        for attempt in range(4 if solve else 1):
            hour_angle, dec, _ = where(target, site)
            self.goto((true_sidereal(site) + offset - (hour_angle - error[0])) % 360,
                      dec - error[1])
            self.tracking(True)
            self.apply_drift_correction()
            if solve and self.demo:
                print("  (demo: no camera, so no plate solve)")
            if not solve or self.demo:
                return
            # After a slew the gears take a while to bite again and the stars
            # streak, which the solver cannot handle. Wait, and try twice.
            time.sleep(SETTLE)
            miss = self.measure_miss(target, site)
            if miss is None:
                time.sleep(SETTLE)
                miss = self.measure_miss(target, site)
            if miss is None:
                self.say("Could not plate-solve the frame; aim left uncorrected.")
                return
            self.say(f"  off by {miss[0] * 60:+.1f}' in hour angle, {miss[1] * 60:+.1f}' in Dec")
            if max(abs(miss[0]), abs(miss[1])) < CENTRED:
                self.say("  centred")
                return
            error = [error[0] + miss[0], error[1] + miss[1]]
            save_pointing_error(error, west)
        self.say("  still not centred after 4 tries")

    def where_really(self, ra_hint, dec_hint, radius=30, exposure=1.0):
        """Photograph the sky and plate-solve it. Returns the J2000 position
        of the frame centre as {"ra", "dec"} in degrees, or None."""
        import solve as solver
        from scipy import ndimage
        from camera import Camera, luminance
        import snap
        # Short exposure at high gain: after a slew the stars drift for a
        # while, and streaked stars do not solve.
        from astropy.time import Time
        with Camera(gain=2000) as cam:
            mosaic, _ = cam.frame(exposure)
        when = Time.now()
        snap.publish(mosaic)
        if self.recording:
            count = len(list(self.recording.glob("frame-*.jpg")))
            snap.publish(mosaic, self.recording / f"frame-{count + 1:02d}.jpg")
        # Hot pixels look like stars to the solver; a median filter removes them.
        image = ndimage.median_filter(luminance(mosaic), 3)
        found = solver.solve(image, ra_hint, dec_hint, radius)
        if found:
            found["when"] = when  # solving can take a while; the sky moves on
        return found

    def sync(self, site):
        """Measure the pointing error where the scope is now and store it."""
        offset = json.loads(CLOCK_FILE.read_text())["offset_deg"]
        ra_handset, dec_handset = self.radec()
        sidereal = true_sidereal(site)
        believed_ha = wrap(sidereal + offset - ra_handset)
        found = self.where_really(sidereal - believed_ha, wrap(dec_handset), radius=40)
        if not found:
            raise SystemExit("Could not plate-solve: cloud, too few stars, or out of focus.")
        actual = where(found, site, found["when"])
        error = [wrap(actual[0] - believed_ha), actual[1] - wrap(dec_handset)]
        # Dec axis past 90° means the tube is over the pole, on the west side.
        save_pointing_error(error, west=self.axes()[1] > 90)
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
        raise SystemExit("That is within 40° of the Sun; not slewing.")
    hadec = spot.transform_to(HADec(obstime=now, location=here))
    return hadec.ha.deg, hadec.dec.deg


def use_demo_cache():
    """Keep the simulated mount's measurements apart from the real one's."""
    global CLOCK_FILE, POINTING_FILE, DRIFT_FILE
    CLOCK_FILE = ROOT / "cache" / "demo_handset_clock.json"
    POINTING_FILE = ROOT / "cache" / "demo_pointing.json"
    DRIFT_FILE = ROOT / "cache" / "demo_drift.json"


def load_pointing_error(west):
    """(hour angle, Dec) error in degrees from the last plate solve, if it was
    measured since the handset's clock was. `west` says which side of the
    meridian the target is on: the error comes mostly from the home position
    being set by eye, and a Dec-axis offset reverses when the tube swings
    over the pole for the other side."""
    if POINTING_FILE.exists() and CLOCK_FILE.exists():
        saved = json.loads(POINTING_FILE.read_text())
        if saved["saved"] > json.loads(CLOCK_FILE.read_text())["saved"]:
            ha, dec = saved["error_deg"]
            return [ha, dec if saved["west"] == west else -dec]
    return [0.0, 0.0]


def save_pointing_error(error, west):
    POINTING_FILE.write_text(json.dumps(
        {"error_deg": list(error), "west": bool(west), "saved": time.time()}))


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
}


def find_target(name):
    import sky
    wanted = name.replace(" ", "").lower()
    for star, (ra_hours, dec) in STARS.items():
        if star.lower() == wanted:
            return {"id": star, "name": "star", "ra": ra_hours * 15, "dec": dec}
    for t in sky.load_targets():
        if wanted in (t["id"].replace(" ", "").lower(), t["alt_id"].replace(" ", "").lower(),
                      t["name"].replace(" ", "").lower()):
            return t
    raise SystemExit(f"'{name}' is not in the catalogue.")


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


def report(mount):
    ra, dec = mount.radec()
    ra_axis, dec_axis = mount.axes()
    state = "slewing" if mount.slewing() else "at home" if mount.at_home() else "stopped"
    print(f"{state}: RA {ra / 15:.4f} h, Dec {wrap(dec):+.2f}°  "
          f"(axes: RA {ra_axis:.2f}°, Dec {dec_axis:.2f}°)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["status", "zenith", "home", "stop", "goto", "point",
                                       "sync", "drift"])
    ap.add_argument("target", nargs="*",
                    help="object for goto (e.g. M81), or bearing and height for point")
    ap.add_argument("--port", help="serial port (default: found by the adapter name "
                                   "in config.toml)")
    ap.add_argument("--no-watch", action="store_true", help="skip the webcam pictures")
    ap.add_argument("--solve", action="store_true",
                    help="with goto: plate-solve and correct until centred")
    ap.add_argument("--demo", action="store_true",
                    help="use a simulated mount at the example site; nothing moves")
    ap.add_argument("--record", metavar="FOLDER",
                    help="with goto --solve: keep each solve frame and message there, "
                         "for replay.py to animate")
    args = ap.parse_args()

    if args.demo:
        if args.command in ("sync", "drift"):
            ap.error(f"{args.command} needs the real camera; there is no demo of it")
        use_demo_cache()
        site = config.example()["site"]
    else:
        site = config.load()["site"]

    if args.command in ("zenith", "home", "goto", "point") and LOCK_FILE.exists():
        raise SystemExit(f"Motion is locked: {LOCK_FILE.read_text().strip()}")

    mount = Mount(args.port, watch=not args.no_watch, demo=args.demo)
    if args.record:
        mount.record(args.record)
    try:
        if args.command == "stop":
            mount.stop()
        elif args.command != "status":
            if args.command == "goto" and not args.target:
                ap.error("goto needs a target, e.g. goto M81")
            if args.command == "point" and len(args.target) != 2:
                ap.error("point needs a bearing and a height, e.g. point 225 10")
            if args.command == "zenith":
                mount.zenith(site)
            elif args.command == "goto":
                mount.goto_target(" ".join(args.target), site, solve=args.solve)
            elif args.command == "point":
                mount.point(float(args.target[0]), float(args.target[1]), site)
            elif args.command == "home":
                mount.home()
            elif args.command == "sync":
                mount.sync(site)
            elif args.command == "drift":
                mount.cancel_drift(site)
    except BaseException:
        # Never leave a motor running after an error or Ctrl+C.
        mount.stop()
        raise
    report(mount)


if __name__ == "__main__":
    main()
