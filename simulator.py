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
