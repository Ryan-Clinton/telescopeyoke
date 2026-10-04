"""The mount without its handset: straight to the motor board, through the
SynScan Wi-Fi adapter or an EQDIR lead.

The handset is a small computer that knows the sky: it takes "go to this RA
and Dec" and works the motors itself. The Wi-Fi adapter and the EQDIR lead
plug in where the handset would and reach the motor board directly. The board
knows nothing about the sky. It counts motor steps on each axis and takes
orders such as "turn this axis that many steps" or "turn at this rate".

mount.py is written for the handset. Rather than write the mount logic twice,
DirectHandset stands where the handset's serial port would and answers the
same handset commands, doing the handset's sums itself and passing the result
to the motor board. So the limits, home, GoTo, drift and plate-solve
correction in mount.py are the same code on either link.

Two things the handset knew that this has to be told:

- **Where home is.** The board's counts start from a fixed number when it is
  switched on, and another program may have changed them. `./mount.py sethome`
  records the counts with the mount at its home position.
- **Which way the Dec motor turns.** Counting up tips the tube one way or the
  other depending on the mount. Until `./mount.py directions` has found out,
  with a person watching, a GoTo is refused: the wrong way round would send
  the tube to the mirror-image side of the pole.

    link = Udp("192.168.4.1")           # or Udp.find(), or Serial(port)
    board = Board(link)
    board.position(RA)                  # motor counts; moves nothing

Proven on a real adapter so far: finding it, and the questions that read
(version, gearing, position, status). Nothing here has moved a real mount.
"""
import json
import socket
import time
from pathlib import Path

from interface import Refusal

ROOT = Path(__file__).parent
STATE_FILE = ROOT / "cache" / "direct_mount.json"
PORT = 11880                 # the Wi-Fi adapter listens here, on UDP
ADAPTER = "192.168.4.1"      # its address on the network it makes itself
RA, DEC = "1", "2"           # the board's names for the axes
POWER_ON = 0x800000          # what both counts read when the board is switched on

SIDEREAL = 360 / 86164.0905  # degrees per second
# The handset's fixed slew rates 1 to 9, in degrees per second.
RATES = {0: 0, 1: 0.002, 2: 0.004, 3: 0.008, 4: 0.07, 5: 0.13, 6: 0.27, 7: 1.0, 8: 2.5, 9: 3.4}
FAST = 128 * SIDEREAL        # above this the motors need their high-speed mode
LONG_WAY = 2.5               # degrees: a GoTo longer than this goes at high speed


# --- reaching the board ----------------------------------------------------------

class Udp:
    """The SynScan Wi-Fi adapter. One question, one answer, each in a packet.
    Packets can be lost, so a question is asked again before giving up."""

    def __init__(self, address, port=PORT, timeout=1.0):
        self.where, self.timeout = (address, port), timeout
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def name(self):
        return f"Wi-Fi adapter at {self.where[0]}"

    def exchange(self, message):
        self.sock.setblocking(False)
        try:
            while True:
                self.sock.recv(256)     # an answer that came late to an earlier question
        except OSError:
            pass
        self.sock.settimeout(self.timeout)
        for _ in range(3):
            self.sock.sendto(message, self.where)
            try:
                return self.sock.recv(256)
            except socket.timeout:
                continue
        raise Refusal("HANDSET_NOT_ANSWERING", f"The mount's {self.name()} is not answering. "
                      "Is the mount switched on, and this computer on the same network?")

    def close(self):
        self.sock.close()

    @staticmethod
    def find(wait=1.5):
        """Addresses of the adapters that answer on this network, by asking
        everyone for the motor board's version. Asking moves nothing."""
        found = []
        for target in ("255.255.255.255", ADAPTER):
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.settimeout(wait)
            try:
                s.sendto(b":e1\r", (target, PORT))
                while True:
                    reply, who = s.recvfrom(256)
                    if reply.startswith(b"=") and who[0] not in found:
                        found.append(who[0])
            except OSError:
                pass
            finally:
                s.close()
        return found


class Serial:
    """An EQDIR lead: the same conversation over a serial port."""

    def __init__(self, port, baud=9600):
        import serial
        self.port = serial.Serial(port, baud, timeout=1.0)

    def name(self):
        return f"EQDIR lead on {self.port.port}"

    def exchange(self, message):
        self.port.reset_input_buffer()
        self.port.write(message)
        reply = self.port.read_until(b"\r", 32)
        if not reply:
            raise Refusal("HANDSET_NOT_ANSWERING", f"The mount's {self.name()} is not answering. "
                          "Is the mount switched on?")
        return reply

    def close(self):
        self.port.close()


def open_link(settings, port=None):
    """The link config.toml asks for: [mount] link = "wifi" or "eqdir"."""
    if settings.get("link") == "eqdir":
        import host
        found = port or host.serial_port(settings.get("serial_match", "FTDI"))
        if not found:
            raise Refusal("MOUNT_NOT_CONNECTED", "No EQDIR lead found. Plug it in, or name its port "
                          "with --port.")
        return Serial(found, settings.get("baud", 9600))
    address = settings.get("address")
    if not address:
        seen = Udp.find()
        if not seen:
            raise Refusal("MOUNT_NOT_CONNECTED", "No SynScan Wi-Fi adapter answered. Join its network "
                          "(SynScan_WiFi_xxxx), or put it on yours and set address under [mount] in "
                          "config.toml.")
        address = seen[0]
    return Udp(address)


# --- the motor board's language -----------------------------------------------------

def encode(value):
    """A 24-bit number as the board writes it: six hex digits, low byte first."""
    value &= 0xFFFFFF
    return f"{value & 0xFF:02X}{(value >> 8) & 0xFF:02X}{(value >> 16) & 0xFF:02X}"


def decode(text):
    return int(text[4:6] + text[2:4] + text[0:2], 16)


class Board:
    """The questions and orders the motor board understands."""

    def __init__(self, link):
        self.link = link
        self.counts_per_turn = {a: self.number("a", a) for a in (RA, DEC)}
        self.clock = {a: self.number("b", a) for a in (RA, DEC)}
        self.high_ratio = {a: int(self.ask("g", a), 16) for a in (RA, DEC)}

    def ask(self, letter, axis, data=""):
        reply = self.link.exchange(f":{letter}{axis}{data}\r".encode()).decode("ascii", "replace").strip()
        if reply.startswith("!"):
            raise Refusal("GOTO_REFUSED", f"The motor board refused '{letter}{axis}{data}' (error "
                          f"{reply[1:] or '?'}).")
        if not reply.startswith("="):
            raise Refusal("HANDSET_NOT_ANSWERING", f"The motor board's answer made no sense: {reply!r}")
        return reply[1:]

    def number(self, letter, axis):
        return decode(self.ask(letter, axis))

    # -- reading: none of these changes anything

    def version(self):
        """(mount model code, firmware) from the board. Model 3 is an EQ3."""
        text = self.ask("e", RA)
        return int(text[4:6], 16), f"{int(text[0:2], 16)}.{int(text[2:4], 16):02d}"

    def position(self, axis):
        return self.number("j", axis)

    def status(self, axis):
        a, b, c = (int(ch, 16) for ch in self.ask("f", axis)[:3])
        return {"running": bool(b & 1), "blocked": bool(b & 2), "goto": not a & 1,
                "backward": bool(a & 2), "fast": bool(a & 4), "ready": bool(c & 1)}

    def degrees(self, axis, counts):
        return 360.0 * counts / self.counts_per_turn[axis]

    def counts(self, axis, degrees):
        return round(degrees * self.counts_per_turn[axis] / 360.0)

    # -- orders

    def ready(self):
        """Switch the motors on if nothing has yet. Nothing turns."""
        for axis in (RA, DEC):
            if not self.status(axis)["ready"]:
                self.ask("F", axis)

    def halt(self, axis, wait=6.0):
        """Slow the axis to a stop and wait until it has: the board refuses a
        new kind of movement while the motor is still turning."""
        if not self.status(axis)["running"]:
            return
        self.ask("K", axis)
        end = time.monotonic() + wait
        while self.status(axis)["running"]:
            if time.monotonic() > end:
                self.ask("L", axis)     # stop dead
                break
            time.sleep(0.1)

    def turn(self, axis, rate):
        """Turn steadily at `rate` degrees per second of the counts (negative
        is counting down); 0 stops."""
        if not rate:
            return self.halt(axis)
        steps = abs(rate) * self.counts_per_turn[axis] / 360.0      # per second
        fast = abs(rate) > FAST
        period = self.clock[axis] / steps * (self.high_ratio[axis] if fast else 1)
        period = max(6, min(round(period), 0xFFFFFF))
        now = self.status(axis)
        same = now["running"] and not now["goto"] and now["fast"] == fast and now["backward"] == (rate < 0)
        if same and not fast:
            return self.ask("I", axis, encode(period))     # only the speed changes
        self.halt(axis)
        self.ask("G", axis, f"{'3' if fast else '1'}{'1' if rate < 0 else '0'}")
        self.ask("I", axis, encode(period))
        self.ask("J", axis)

    def move(self, axis, steps):
        """Turn the axis by a number of counts and stop there."""
        if not steps:
            return
        self.halt(axis)
        far = abs(steps) > self.counts(axis, LONG_WAY)
        self.ask("G", axis, f"{'0' if far else '2'}{'1' if steps < 0 else '0'}")
        self.ask("H", axis, encode(abs(steps)))
        self.ask("M", axis, encode(min(abs(steps), 3200 if far else 200)))   # where to start slowing
        self.ask("J", axis)


# --- standing in for the handset -------------------------------------------------------

def _hex(degrees):
    return f"{int(round(degrees % 360 / 360 * 2**32)) & 0xFFFFFF00:08X}"


class DirectHandset:
    """Answers the handset's serial commands that mount.py uses, by working
    the motor board. `sidereal` gives the true local sidereal time in degrees.

    Axis angles are the handset's: at home the RA axis reads 0° and Dec 90°;
    the tube is on the meridian with the RA axis at 90°; west of the meridian
    the tube is swung over the pole and the Dec axis reads past 90°.
    """

    def __init__(self, board, sidereal, state_file=None):
        self.board, self.sidereal = board, sidereal
        self.state_file = Path(state_file or STATE_FILE)
        self.reply = b""
        self.tracking = False
        self.target = None          # (ra, dec, corrections left) while a GoTo is under way
        self.slew = {RA: 0.0, DEC: 0.0}    # degrees/second asked for by fixed-rate slews
        self.state = self._load()

    # -- what the handset knew and this has to be told

    def _load(self):
        state = {"home": None, "dec_sign": None}
        if self.state_file.exists():
            state.update(json.loads(self.state_file.read_text(encoding="utf-8")))
        now = [self.board.position(RA), self.board.position(DEC)]
        if now == [POWER_ON, POWER_ON] and state["home"] != now:
            # Just switched on, and nothing has moved it or changed its counts:
            # the mount is at home by its own convention, as the handset assumes.
            state["home"] = now
            self._save(state)
        return state

    def _save(self, state=None):
        self.state_file.parent.mkdir(exist_ok=True)
        self.state_file.write_text(json.dumps(state or self.state), encoding="utf-8")

    def set_home(self):
        """Record that the mount is at its home position now. Moves nothing."""
        self.state["home"] = [self.board.position(RA), self.board.position(DEC)]
        self._save()
        return self.state["home"]

    def set_dec_sign(self, sign):
        self.state["dec_sign"] = sign
        self._save()

    def _need_home(self):
        if self.state["home"] is None:
            raise Refusal("HANDSET_NOT_SET_UP",
                          "The mount has no handset to say where home is. Put it at its home "
                          "position (counterweight bar down, tube pointing at the pole) and run: "
                          "./mount.py sethome")

    # -- angles

    def axes(self):
        self._need_home()
        sign = self.state["dec_sign"] or 1
        ra = self.board.degrees(RA, self.board.position(RA) - self.state["home"][0])
        dec = 90 + sign * self.board.degrees(DEC, self.board.position(DEC) - self.state["home"][1])
        return ra % 360, dec

    def pointing(self):
        ra_axis, dec_axis = self.axes()
        if dec_axis <= 90:
            hour_angle, dec = ra_axis - 90, dec_axis
        else:
            hour_angle, dec = ra_axis + 90, 180 - dec_axis
        return (self.sidereal() - hour_angle) % 360, dec

    def _axes_for(self, ra, dec):
        """The axis angles that aim at a sky position, on the handset's choice of side."""
        hour_angle = (self.sidereal() - ra + 180) % 360 - 180
        if hour_angle <= 0.5:      # east of the meridian (and a whisker past it)
            return (hour_angle + 90) % 360, dec
        return (hour_angle - 90) % 360, 180 - dec     # west: the tube over the pole

    # -- movement

    def _goto(self, ra, dec, corrections=1):
        if self.state["dec_sign"] is None:
            raise Refusal("GOTO_REFUSED",
                          "Which way the Dec motor turns has not been checked on this mount, so a "
                          "GoTo could go to the wrong side of the pole. With the mount at home and "
                          "someone watching it, run: ./mount.py directions")
        self.board.ready()
        want_ra, want_dec = self._axes_for(ra, dec)
        have_ra, have_dec = self.axes()
        # Both as angles either side of home. Every aim the handset makes has
        # the RA axis within a quarter turn of home, so the axis is turned by
        # the plain difference: never the other way round, which would take
        # the counterweight bar over the top.
        signed = lambda angle: (angle + 180) % 360 - 180
        turn_ra = signed(want_ra) - signed(have_ra)
        self.tracking = False
        self.slew = {RA: 0.0, DEC: 0.0}
        self.board.move(RA, self.board.counts(RA, turn_ra))
        self.board.move(DEC, self.state["dec_sign"] * self.board.counts(DEC, want_dec - have_dec))
        self.target = (ra, dec, corrections)

    def _slewing(self):
        """Whether a GoTo is still under way. When both motors have stopped,
        the sky has moved on a little: close the gap once, then follow it."""
        if self.target is None:
            return False
        if self.board.status(RA)["running"] or self.board.status(DEC)["running"]:
            return True
        ra, dec, corrections = self.target
        self.target = None
        if corrections:
            self._goto(ra, dec, corrections - 1)
            return True
        self._track(True)
        return False

    def _track(self, on):
        self.tracking = on
        self._ra_rate()

    def _ra_rate(self):
        """Tracking and a fixed-rate slew add up on the RA axis, as on the handset."""
        self.board.turn(RA, self.slew[RA] + (SIDEREAL if self.tracking else 0))

    def _stop(self):
        self.target, self.tracking, self.slew = None, False, {RA: 0.0, DEC: 0.0}
        self.board.halt(RA)
        self.board.halt(DEC)

    # -- the serial-port interface mount.py uses

    def reset_input_buffer(self):
        self.reply = b""

    def write(self, command):
        self.reply = self._answer(bytes(command))

    def read_until(self, terminator=b"#", size=64):
        reply, self.reply = self.reply, b""
        return reply

    def close(self):
        self.board.link.close()

    def _answer(self, c):
        kind = c[:1]
        if kind == b"K":
            self.board.version()
            return c[1:2] + b"#"
        if kind == b"h":
            # The handset's clock. This link has none to set, so it is today's:
            # mount.py takes a year of 22 to mean "not set up".
            t = time.localtime()
            return bytes([t.tm_hour, t.tm_min, t.tm_sec, t.tm_mon, t.tm_mday, t.tm_year % 100, 0, 0]) + b"#"
        if kind == b"L":
            return (b"1" if self._slewing() else b"0") + b"#"
        if kind == b"e":
            ra, dec = self.pointing()
            return f"{_hex(ra)},{_hex(dec)}#".encode()
        if kind == b"z":
            ra_axis, dec_axis = self.axes()
            return f"{_hex(ra_axis)},{_hex(dec_axis)}#".encode()
        if kind == b"r":
            ra, dec = (int(x, 16) / 2**32 * 360 for x in c[1:].decode().split(","))
            self._goto(ra, dec if dec < 180 else dec - 360)
            return b"#"
        if kind == b"T":
            self._need_home()
            self.board.ready()
            self._track(c[1] != 0)
            return b"#"
        if kind == b"M":
            self._stop()
            return b"#"
        if kind == b"P":
            self._need_home()
            self.board.ready()
            axis, order = RA if c[2] == 16 else DEC, c[3]
            if order in (36, 37):        # fixed rate, 0 to 9
                speed = RATES.get(c[4], 0)
            else:                        # 6, 7: variable, in quarter-arcseconds a second
                speed = (c[4] * 256 + c[5]) / 4 / 3600
            speed = speed if order in (36, 6) else -speed
            self.target = None
            if axis == RA:
                self.slew[RA] = speed
                self._ra_rate()
            else:
                # "Positive" raises the Dec axis readout, whichever way the motor counts.
                self.slew[DEC] = speed
                self.board.turn(DEC, (self.state["dec_sign"] or 1) * speed)
            return b"#"
        return b""


def describe(link):
    """What is on the other end, for the doctor and for status. Reads only."""
    board = Board(link)
    model, firmware = board.version()
    names = {0: "EQ6", 1: "HEQ5", 2: "EQ5", 3: "EQ3", 4: "EQ8", 5: "AZ-EQ6", 6: "AZ-EQ5"}
    return {"link": link.name(), "model": names.get(model, f"model {model}"), "firmware": firmware,
            "counts_per_turn": board.counts_per_turn[RA],
            "position_counts": [board.position(RA), board.position(DEC)],
            "moving": [board.status(RA)["running"], board.status(DEC)["running"]]}
