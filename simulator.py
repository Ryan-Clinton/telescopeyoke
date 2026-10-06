"""A pretend SynScan handset and mount, for trying things without hardware.

It answers the same serial commands the real handset does and keeps a pair of
axis angles, so mount.py can be run and tested with nothing plugged in:

    ./mount.py --demo zenith
    ./mount.py --demo goto M27
"""
import time

SIDEREAL = 360 / 86164.0905  # degrees per second
# Roughly how fast each fixed slew rate (1-9) turns an axis, in degrees/second.
RATES = {0: 0, 1: 0.002, 2: 0.004, 3: 0.008, 4: 0.07, 5: 0.13, 6: 0.27,
         7: 1.0, 8: 2.5, 9: 3.5}


def _hex(degrees):
    return f"{int(round(degrees % 360 / 360 * 2**32)) & 0xFFFFFF00:08X}"


class SimulatedHandset:
    """Stands in for the serial port: write() a command, read_until() the reply.

    The geometry matches the real mount: at home the RA axis reads 0° and Dec
    90°; the tube is on the meridian with the RA axis at 90°; and targets west
    of the meridian are reached with the tube swung over the pole, where the
    Dec axis reads past 90°.
    """

    def __init__(self, slew_seconds=2.0, year=26, clock=time.time):
        self.clock = clock
        self.slew_seconds = slew_seconds
        self.year = year  # 22 imitates a handset left on its version screen
        self.ra_axis, self.dec_axis = 0.0, 90.0
        self.rates = {16: 0.0, 17: 0.0}  # degrees/second from slew commands
        self.tracking = False
        self.busy_until = 0.0
        self.updated = clock()
        self.reply = b""

    # --- the serial-port interface mount.py uses ----------------------------

    def reset_input_buffer(self):
        self.reply = b""

    def write(self, command):
        self._advance()
        self.reply = self._answer(bytes(command))

    def read_until(self, terminator=b"#", size=64):
        reply, self.reply = self.reply, b""
        return reply

    # --- the pretend mount --------------------------------------------------

    def sidereal(self):
        """The handset's own sidereal time in degrees. Like a real handset
        with a wrongly set clock, it is offset from the true one."""
        return (self.clock() * SIDEREAL + 100.0) % 360

    def _advance(self):
        now = self.clock()
        elapsed, self.updated = now - self.updated, now
        self.ra_axis = (self.ra_axis + self.rates[16] * elapsed
                        + (SIDEREAL * elapsed if self.tracking else 0)) % 360
        self.dec_axis += self.rates[17] * elapsed

    def _pointing(self):
        """(RA, Dec) in degrees that the handset believes it is aimed at."""
        if self.dec_axis <= 90:
            hour_angle, dec = self.ra_axis - 90, self.dec_axis
        else:
            hour_angle, dec = self.ra_axis + 90, 180 - self.dec_axis
        return (self.sidereal() - hour_angle) % 360, dec

    def _goto(self, ra, dec):
        hour_angle = (self.sidereal() - ra + 180) % 360 - 180
        if hour_angle <= 0.5:  # east of the meridian (and a whisker past it)
            self.ra_axis, self.dec_axis = (hour_angle + 90) % 360, dec
        else:                 # west: tube over the pole
            self.ra_axis, self.dec_axis = (hour_angle - 90) % 360, 180 - dec
        self.busy_until = self.clock() + self.slew_seconds
        self.tracking = True
        self.rates = {16: 0.0, 17: 0.0}

    def _answer(self, c):
        kind = c[:1]
        if kind == b"K":
            return c[1:2] + b"#"
        if kind == b"V":
            return bytes([2, 2]) + b"#"
        if kind == b"m":                 # the mount's model: 3 is an EQ3
            return bytes([3]) + b"#"
        if kind == b"J":
            return bytes([1]) + b"#"
        if kind == b"h":
            return bytes([20, 0, 0, 10, 3, self.year, 0, 0]) + b"#"
        if kind == b"L":
            return (b"1" if self.clock() < self.busy_until else b"0") + b"#"
        if kind == b"e":
            ra, dec = self._pointing()
            return f"{_hex(ra)},{_hex(dec)}#".encode()
        if kind == b"z":
            return f"{_hex(self.ra_axis)},{_hex(self.dec_axis)}#".encode()
        if kind == b"r":
            ra, dec = (int(x, 16) / 2**32 * 360 for x in c[1:].decode().split(","))
            self._goto(ra, dec if dec < 180 else dec - 360)
            return b"#"
        if kind == b"T":
            self.tracking = c[1] != 0
            return b"#"
        if kind == b"M":
            self.busy_until = 0.0
            return b"#"
        if kind == b"P":
            axis, command = c[2], c[3]
            if command in (36, 37):      # fixed rate, 0-9
                speed = RATES.get(c[4], 0)
            else:                        # 6, 7: variable, quarter-arcseconds/second
                speed = (c[4] * 256 + c[5]) / 4 / 3600
            self.rates[axis] = speed if command in (36, 6) else -speed
            return b"#"
        return b""


class SimulatedBoard:
    """A pretend motor board, for the link that has no handset (the Wi-Fi
    adapter or an EQDIR lead). It stands where direct.Udp would: exchange()
    takes one message and returns the board's answer.

    It keeps a count for each axis and obeys the orders direct.Board gives:
    turn at a rate, or turn by so many counts and stop. `dec_sign` is which
    way counting up turns the Dec axis on this pretend mount, so the tests
    can check that both kinds of mount are handled.
    """
    COUNTS, CLOCK, RATIO = 4576000, 35477, 16     # an EQ3's, as read from a real one

    def __init__(self, goto_seconds=0.0, clock=time.time, start=(0x800000, 0x800000)):
        self.clock, self.goto_seconds = clock, goto_seconds
        self.axes = {a: {"pos": float(start[i]), "mode": "1", "back": False, "period": 0, "steps": 0,
                         "running": False, "until": 0.0, "from": 0.0, "to": 0.0, "began": 0.0, "ready": False}
                     for i, a in enumerate("12")}
        self.updated = clock()
        self.orders = []      # every message that was not a question, for the tests to read

    def name(self):
        return "simulated motor board"

    def close(self):
        pass

    def _advance(self):
        now = self.clock()
        elapsed, self.updated = now - self.updated, now
        for a in self.axes.values():
            if not a["running"]:
                continue
            if a["mode"] in "02":                 # going to a place
                if now >= a["until"]:
                    a["pos"], a["running"] = a["to"], False
                else:
                    share = (now - a["began"]) / max(a["until"] - a["began"], 1e-9)
                    a["pos"] = a["from"] + share * (a["to"] - a["from"])
            elif a["period"]:                     # turning steadily
                rate = self.CLOCK / a["period"] * (self.RATIO if a["mode"] == "3" else 1)
                a["pos"] += (-rate if a["back"] else rate) * elapsed

    def exchange(self, message):
        self._advance()
        text = message.decode().strip()
        letter, axis, data = text[1], text[2], text[3:]
        a = self.axes[axis]
        number = lambda: int(data[4:6] + data[2:4] + data[0:2], 16)
        code = lambda v: f"{v & 0xFF:02X}{(v >> 8) & 0xFF:02X}{(v >> 16) & 0xFF:02X}"
        if letter in "FKLGHMIJE":
            self.orders.append(text)
        if letter == "e":
            return b"=010703\r"
        if letter == "a":
            return f"={code(self.COUNTS)}\r".encode()
        if letter == "b":
            return f"={code(self.CLOCK)}\r".encode()
        if letter == "g":
            return f"={self.RATIO:02X}\r".encode()
        if letter == "j":
            return f"={code(round(a['pos']))}\r".encode()
        if letter == "f":
            first = (0 if a["mode"] in "02" else 1) | (2 if a["back"] else 0) | (4 if a["mode"] in "03" else 0)
            return f"={first:X}{1 if a['running'] else 0:X}{1 if a['ready'] else 0:X}\r".encode()
        if letter == "F":
            a["ready"] = True
        elif letter in "KL":
            a["running"] = False
        elif letter in "GHIJ" and a["running"] and letter != "I":
            return b"!2\r"                         # the real board refuses these while turning
        elif letter == "G":
            a["mode"], a["back"] = data[0], data[1] == "1"
        elif letter == "H":
            a["steps"] = number()
        elif letter == "I":
            a["period"] = number()
        elif letter == "J":
            if not a["ready"]:
                return b"!4\r"                     # not switched on yet
            a["running"], a["began"] = True, self.clock()
            if a["mode"] in "02":
                a["from"] = a["pos"]
                a["to"] = a["pos"] + (-a["steps"] if a["back"] else a["steps"])
                a["until"] = a["began"] + self.goto_seconds
        elif letter == "E":
            a["pos"] = float(number())
        return b"=\r"


# --- a pretend camera and sky, for the demo --------------------------------------
#
# The demo runs the real focusing aid, the real imaging run and the real
# plate-solve corrections on frames made here: a field of stars that drifts,
# blurs, clouds over or stops arriving as the demo is told to. It imitates no
# particular camera; it is there so that every screen can be used, and
# tested, with nothing plugged in.

SHAPE = (1100, 1300)              # half-size frame, in pixels: rows, columns
BEST_FOCUS = 1.5                  # star width in pixels at best focus
HOME_ERROR = (1.5, -1.0)          # how far a home position set by eye leaves the aim off: hour angle, Dec (degrees)
POLAR_ERROR = (1.4, 0.8)          # the pretend mount's polar axis: degrees east of north, degrees too high
SKY = {"focus": 4, "cloud": False, "unplugged": False, "drift": True, "offset": [0.0, 0.0], "frames": 0}
DEMO_SCOPE = None                 # the simulated mount in this program, if one has been opened


def _sky_file():
    import config
    return config.DATA / "cache" / "demo_sky.json"


def sky():
    """What the pretend sky and camera are doing: how far the focuser is from
    best focus (in turns of the knob), cloud, the lead pulled out, drift."""
    import json
    path = _sky_file()
    state = dict(SKY)
    if path.exists():
        try:
            state.update(json.loads(path.read_text(encoding="utf-8")))
        except ValueError:
            pass
    return state


def set_sky(**changes):
    import json
    state = dict(sky(), **changes)
    state["focus"] = max(-12, min(12, int(state["focus"])))
    path = _sky_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".part")
    partial.write_text(json.dumps(state), encoding="utf-8")
    partial.replace(path)
    return state


def recentred():
    """The mount has just been aimed afresh: the target is back in the middle."""
    set_sky(offset=[0.0, 0.0])


def star_field(name, count=140):
    """The same made-up stars every time for the same target."""
    import zlib

    import numpy as np
    rng = np.random.default_rng(zlib.crc32(str(name).encode()))
    xy = np.column_stack([rng.uniform(40, SHAPE[1] - 40, count), rng.uniform(40, SHAPE[0] - 40, count)])
    return xy, rng.uniform(2e4, 2e5, count)


def render(xy, flux, sigma, sky_level=300.0, noise=4.0, seed=0):
    """A brightness image with a round star at each (x, y)."""
    import numpy as np
    image = np.zeros(SHAPE, np.float32)
    reach = int(6 * sigma) + 1
    for (x, y), f in zip(xy, flux):
        x0, y0 = int(round(x)), int(round(y))
        if not (reach < x0 < SHAPE[1] - reach and reach < y0 < SHAPE[0] - reach):
            continue
        yy, xx = np.mgrid[y0 - reach:y0 + reach + 1, x0 - reach:x0 + reach + 1]
        spot = np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sigma ** 2))
        image[y0 - reach:y0 + reach + 1, x0 - reach:x0 + reach + 1] += f * spot / spot.sum()
    return image + sky_level + np.random.default_rng(seed).normal(0, noise, SHAPE).astype(np.float32)


class SimulatedCamera:
    """Stands where camera.Camera would: frame(seconds) gives a raw Bayer
    mosaic and a header, as the real one does."""
    name = "simulated camera"
    DRIFT = (1.4, -0.8)        # pixels the stars move between frames while the drift is on

    def __init__(self, port=None, gain=300, wait=None):
        import os
        # TY_DEMO_FAST skips the waiting, for the tests.
        self.gain, self.wait = gain, os.environ.get("TY_DEMO_FAST") != "1" if wait is None else wait

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    close = __exit__

    def frame(self, seconds):
        import numpy as np

        from indi import IndiError
        state = sky()
        if state["unplugged"]:
            raise IndiError("the camera was unplugged (the demo's pretend camera: plug it back in on the Demo screen)")
        if self.wait:
            time.sleep(min(seconds, 4.0) + 0.4)      # a frame takes its exposure and a little more
        n = state["frames"] + 1
        offset = state["offset"]
        if state["drift"]:
            offset = [offset[0] + self.DRIFT[0], offset[1] + self.DRIFT[1]]
        set_sky(frames=n, offset=offset)
        xy, flux = star_field(state.get("target", "demo"))
        sigma = BEST_FOCUS + 0.45 * abs(state["focus"])
        light = min(seconds, 4.0) / 2 * (0.25 if state["cloud"] else 1.0)
        lum = render(xy + offset, flux * light, sigma, seed=n)
        mosaic = np.repeat(np.repeat(lum / 4, 2, axis=0), 2, axis=1)
        header = {"EXPTIME": float(seconds), "GAIN": float(self.gain), "BAYERPAT": "RGGB",
                  "DATE-OBS": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())}
        return np.clip(mosaic, 0, 4095).astype(np.uint16), header


def tilted(hour_angle, dec, latitude):
    """Where a mount whose polar axis is out by POLAR_ERROR really points
    when its axes say (hour angle, Dec): the whole sky as the mount sees it,
    turned so that its pole lands where its axis actually aims."""
    import math

    import numpy as np
    h, d, lat = math.radians(hour_angle), math.radians(dec), math.radians(latitude)
    believed = np.array([math.cos(d) * math.cos(h), math.cos(d) * math.sin(h), math.sin(d)])
    # The axis as a vector, pole-and-meridian axes: from its height and bearing.
    alt, az = math.radians(latitude + POLAR_ERROR[1]), math.radians(POLAR_ERROR[0])
    up, north, east = math.sin(alt), math.cos(alt) * math.cos(az), math.cos(alt) * math.sin(az)
    axis = np.array([up * math.cos(lat) - north * math.sin(lat), -east, up * math.sin(lat) + north * math.cos(lat)])
    pole = np.array([0.0, 0.0, 1.0])
    about = np.cross(pole, axis)
    sine, cosine = np.linalg.norm(about), float(pole @ axis)
    if sine < 1e-12:
        return hour_angle, dec
    k = about / sine
    real = believed * cosine + np.cross(k, believed) * sine + k * (k @ believed) * (1 - cosine)
    return math.degrees(math.atan2(real[1], real[0])), math.degrees(math.asin(max(-1.0, min(1.0, real[2]))))


def solve(image, ra_hint=None, dec_hint=None, radius=30, **_):
    """A pretend plate solve: where the simulated mount is really aimed,
    which is where its handset believes plus the error a home position set by
    eye leaves. So a GoTo with centring has something real to correct."""
    if sky()["cloud"]:
        return None                      # no stars through cloud, as for real
    scale = 1.32
    answer = {"rotation": 0.0, "scale": scale, "seconds": 0.4,
              "cd": [[-scale / 3600, 0.0], [0.0, scale / 3600]]}
    scope = DEMO_SCOPE
    if scope is None:
        if ra_hint is None:
            return None
        return dict(answer, ra=ra_hint % 360, dec=dec_hint)
    import json

    from astropy import units as u
    from astropy.coordinates import HADec, ICRS, SkyCoord
    from astropy.time import Time

    import config
    import mount
    site = config.load()["site"]
    offset = json.loads(mount.CLOCK_FILE.read_text(encoding="utf-8"))["offset_deg"] if mount.CLOCK_FILE.exists() else 0.0
    ra_handset, dec_handset = scope.radec()
    hour_angle = mount.wrap(mount.true_sidereal(site) + offset - ra_handset) + HOME_ERROR[0]
    hour_angle, dec = tilted(hour_angle, mount.wrap(dec_handset) + HOME_ERROR[1], site["latitude"])
    spot = SkyCoord(HADec(ha=hour_angle * u.deg, dec=dec * u.deg,
                          obstime=Time.now(), location=mount.location(site))).transform_to(ICRS())
    return dict(answer, ra=spot.ra.deg, dec=spot.dec.deg)
