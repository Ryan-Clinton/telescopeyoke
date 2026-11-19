#!/usr/bin/env python3
"""The mount through ASCOM Alpaca: whatever drives it on another computer
(EQMOD, Green Swamp Server, Sky-Watcher's SynScan driver, any ASCOM driver
behind ASCOM Remote, or a mount that speaks Alpaca itself).

ASCOM is the Windows standard almost every mount, camera, focuser and filter
wheel has a driver for; Alpaca is the same interface over the network, plain
HTTP, so it is reached from Linux as well as Windows. The driver knows the
sky, as a SynScan handset does: it takes "go to this RA and Dec" and works the
motors itself.

mount.py is written for the handset. As direct.py does for the motor board,
AlpacaHandset stands where the handset's serial port would and answers the
same handset commands, passing each to the driver. So the motion lock, the
limits, the dry runs and the plate-solve correction in mount.py are the same
code on this link too: [mount] link = "alpaca", address = "HOST:PORT", and
device (0 unless the server has several telescopes).

    ./alpaca.py find            the Alpaca servers on this network, and their devices
    ./alpaca.py status          what the configured telescope says; moves nothing

What the driver cannot tell mount.py, and is worked out here:

- **The axis angles.** The handset reads its raw axes; Alpaca gives only the
  sky position and the side of the pier. The axes are worked out from those
  and this computer's sidereal time, the handset's way round (counterweight
  down and the tube to the pole is RA axis 0°, Dec axis 90°).
- **Home.** The driver's own (FindHome), or its park position.

Tried against ASCOM's own Alpaca telescope simulator (OmniSim 0.4.0), not
yet on a real mount. Which way a positive MoveAxis turns the Dec axis is the
driver's choice ([mount] alpaca_dec_sign, -1 as the simulator): mount.py's
small Dec moves (the drift creep, the photometric hold) take it from there,
and are unproven on any real driver. Home is the driver's, which need not be
the handset's (OmniSim's is not), so the nudge, which starts from the
handset's home, may refuse.
"""
import argparse
import itertools
import json
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from interface import Refusal

DISCOVERY_PORT = 32227
CLIENT_ID = 4242            # any number: says which client a request came from
RA, DEC = 1, 2              # the handset's axis numbers in mount.py
RATES = {0: 0, 1: 0.002, 2: 0.004, 3: 0.008, 4: 0.07, 5: 0.13, 6: 0.27, 7: 1.0, 8: 2.5, 9: 3.4}
SYSTEMS = {0: "other", 1: "JNow (topocentric)", 2: "J2000", 3: "J2050", 4: "B1950"}


class DriverError(Exception):
    """The driver refused, with ASCOM's error number."""

    def __init__(self, number, message):
        super().__init__(f"{message} (ASCOM error {number:#x})")
        self.number = number


class Client:
    """One Alpaca device: GET reads a property, PUT sets one or acts."""

    def __init__(self, address, device=0, kind="telescope", timeout=10.0):
        self.address = address
        self.base = f"http://{address}/api/v1/{kind}/{int(device)}/"
        self.timeout = timeout
        self.ids = itertools.count(1)

    def name(self):
        return f"Alpaca {self.address}"

    def _call(self, method, what, params, timeout=None):
        params = {"ClientID": CLIENT_ID, "ClientTransactionID": next(self.ids), **params}
        form = urllib.parse.urlencode({k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()})
        url = self.base + what.lower()
        if method == "GET":
            request = urllib.request.Request(url + "?" + form)
        else:
            request = urllib.request.Request(url, data=form.encode(), method="PUT",
                                             headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as answer:
                found = json.loads(answer.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise DriverError(error.code, f"{what}: the server said {error.code} {error.reason}") from None
        except (OSError, ValueError) as error:
            raise Refusal("HANDSET_NOT_ANSWERING", f"The Alpaca server at {self.address} did not answer "
                          f"({error}). Is it running, and is this computer allowed through its firewall?") from None
        if found.get("ErrorNumber"):
            raise DriverError(found["ErrorNumber"], f"{what}: {found.get('ErrorMessage') or 'refused'}")
        return found.get("Value")

    def get(self, what, **params):
        return self._call("GET", what, params)

    def put(self, what, timeout=None, **params):
        return self._call("PUT", what, params, timeout)


def find(wait=1.5):
    """Alpaca servers answering the standard discovery question on this
    network: ["HOST:PORT", ...]. Sends only that question."""
    seen = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(0.3)
        for target in ("255.255.255.255", "127.0.0.1"):
            try:
                s.sendto(b"alpacadiscovery1", (target, DISCOVERY_PORT))
            except OSError:
                pass
        end = time.monotonic() + wait
        while time.monotonic() < end:
            try:
                data, (host, _) = s.recvfrom(1024)
                where = f"{host}:{json.loads(data)['AlpacaPort']}"
            except (socket.timeout, ValueError, KeyError):
                continue
            if where not in seen:
                seen.append(where)
    return seen


def devices(address, timeout=5.0):
    """What an Alpaca server offers: [{"type", "number", "name"}]."""
    url = f"http://{address}/management/v1/configureddevices?ClientID={CLIENT_ID}&ClientTransactionID=1"
    with urllib.request.urlopen(url, timeout=timeout) as answer:
        found = json.loads(answer.read().decode("utf-8")).get("Value") or []
    return [{"type": d.get("DeviceType"), "number": d.get("DeviceNumber"), "name": d.get("DeviceName")}
            for d in found]


def _hex(degrees):
    return f"{int(degrees % 360 / 360 * 2**32) & 0xFFFFFFFF:08X}"


class AlpacaHandset:
    """Answers mount.py's handset commands from an Alpaca telescope. Sky
    positions pass through in the handset's frame (the true equator and
    equinox of date), converted when the driver works in J2000."""

    def __init__(self, client, sidereal, dec_sign=-1):
        self.client, self.sidereal = client, sidereal
        # Which way a positive MoveAxis turns the Dec axis is the driver's
        # choice. -1: as ASCOM's own simulator (OmniSim 0.4.0, 19 November
        # 2026), where plus lowered the handset's Dec axis reading on both
        # sides of the pier. Plus on the RA axis there went with the sky, as
        # on the handset. [mount] alpaca_dec_sign = 1 for a driver the other way.
        self.dec_sign = dec_sign
        self.reply = b""
        client.put("connected", Connected=True)
        mode = client.get("alignmentmode")
        if mode != 2:
            raise Refusal("HANDSET_NOT_SUPPORTED", f"The Alpaca telescope is not a German equatorial mount "
                          f"(alignment mode {mode}): mount.py's limits and sides of the pier assume one.")
        self.system = client.get("equatorialsystem")
        if self.system not in (1, 2):
            raise Refusal("HANDSET_NOT_SUPPORTED", f"The Alpaca telescope gives its positions as "
                          f"{SYSTEMS.get(self.system, self.system)}; only JNow and J2000 are understood here.")
        self.can = {what: bool(client.get(what)) for what in
                    ("canslewasync", "canslew", "cansettracking", "canfindhome", "canpark", "canunpark")}
        self.rates = {axis: client.get("axisrates", Axis=axis) or [] for axis in (0, 1)}
        self.moving = {0: 0.0, 1: 0.0}

    # -- frames

    def _to_driver(self, ra, dec):
        """The handset's frame (of date) to the driver's."""
        if self.system == 1:
            return ra, dec
        return _precess(ra, dec, to_j2000=True)

    def _from_driver(self, ra, dec):
        if self.system == 1:
            return ra, dec
        return _precess(ra, dec, to_j2000=False)

    def pointing(self):
        ra, dec = self._from_driver(self.client.get("rightascension") * 15, self.client.get("declination"))
        return ra % 360, dec

    def looking_west(self, ra=None):
        """Whether the tube is on the west of the meridian, swung over the
        pole in the handset's terms. ASCOM's pierEast (0) is the mount on the
        east of the pier looking west; pierWest (1) looking east; unknown
        (-1) is judged from the hour angle, the handset's way."""
        side = self.client.get("sideofpier")
        if side in (0, 1):
            return side == 0
        if ra is None:
            ra, _ = self.pointing()
        return (self.sidereal() - ra + 180) % 360 - 180 > 0

    def axes(self):
        """The handset's raw axis angles, worked out from the sky position."""
        ra, dec = self.pointing()
        hour_angle = (self.sidereal() - ra + 180) % 360 - 180
        if self.looking_west(ra):
            return (hour_angle - 90) % 360, 180 - dec
        return (hour_angle + 90) % 360, dec

    # -- movement

    def _goto(self, ra, dec):
        if self.client.get("atpark"):
            if not self.can["canunpark"]:
                raise Refusal("GOTO_REFUSED", "The mount is parked and its driver cannot unpark it from here.")
            self.client.put("unpark")
        if self.can["cansettracking"]:
            self.client.put("tracking", Tracking=True)      # ASCOM refuses a slew without tracking
        ra, dec = self._to_driver(ra, dec)
        try:
            if self.can["canslewasync"]:
                self.client.put("slewtocoordinatesasync", RightAscension=ra / 15, Declination=dec)
            elif self.can["canslew"]:
                self.client.put("slewtocoordinates", timeout=300, RightAscension=ra / 15, Declination=dec)
            else:
                raise Refusal("GOTO_REFUSED", "The Alpaca telescope cannot slew to a position.")
        except DriverError as error:
            raise Refusal("GOTO_REFUSED", f"The mount's driver refused the GoTo: {error}") from None

    def _rate(self, axis, speed):
        """Turn one axis at `speed` degrees a second on top of tracking, or stop it."""
        index = 0 if axis == RA else 1
        if speed and not any(r["Minimum"] <= abs(speed) <= r["Maximum"] for r in self.rates[index]):
            allowed = ", ".join(f"{r['Minimum']:g} to {r['Maximum']:g}" for r in self.rates[index]) or "none"
            raise Refusal("INVALID_REQUEST", f"The driver cannot turn the {'RA' if axis == RA else 'Dec'} axis at "
                          f"{abs(speed):.5f}°/s (it takes {allowed}°/s).")
        if axis == DEC:
            speed *= self.dec_sign          # mount.py's plus raises the Dec axis reading
        self.client.put("moveaxis", Axis=index, Rate=speed)
        self.moving[index] = speed

    def _stop(self):
        """Every way it can be moving, stopped: a stop is never refused for
        one that failed."""
        failed = []
        for action in (lambda: self.client.put("abortslew"),
                       lambda: self.client.put("moveaxis", Axis=0, Rate=0),
                       lambda: self.client.put("moveaxis", Axis=1, Rate=0)):
            try:
                action()
            except (DriverError, Refusal) as error:
                failed.append(str(error))
        self.moving = {0: 0.0, 1: 0.0}
        if len(failed) == 3:
            raise Refusal("HANDSET_NOT_ANSWERING", "Nothing reached the mount's driver to stop it: "
                          + "; ".join(failed) + ". Switch the mount off at the mount if it is moving.")

    def go_home(self, timeout=150):
        """The driver's own home (FindHome), or its park position, then
        tracking off: where the handset's home is, counterweight down and the
        tube to the pole, on the drivers the project knows of. Waits."""
        try:
            if self.can["canfindhome"]:
                self.client.put("findhome", timeout=timeout + 30)
            elif self.can["canpark"]:
                self.client.put("park", timeout=timeout + 30)
                if self.can["canunpark"]:
                    self.client.put("unpark")
            else:
                raise Refusal("INVALID_REQUEST", "The Alpaca telescope can neither find home nor park.")
        except DriverError as error:
            raise Refusal("SLEW_TIMED_OUT", f"The mount's driver did not get home: {error}") from None
        end = time.monotonic() + timeout
        while self.client.get("slewing"):
            if time.monotonic() > end:
                self._stop()
                raise Refusal("SLEW_TIMED_OUT", "The mount did not get home in time; stopped.")
            time.sleep(0.5)
        if self.can["cansettracking"]:
            self.client.put("tracking", Tracking=False)

    def set_site(self, latitude, longitude):
        """The driver's site and clock from this computer's, so its sky and
        the limits here agree. A driver that will not take them is told
        nothing more; what it says it has is returned."""
        for what, value in (("sitelatitude", latitude), ("sitelongitude", longitude),
                            ("utcdate", time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()))):
            try:
                self.client.put(what, **{"SiteLatitude": value} if what == "sitelatitude" else
                                {"SiteLongitude": value} if what == "sitelongitude" else {"UTCDate": value})
            except DriverError:
                pass
        return self.client.get("sitelatitude"), self.client.get("sitelongitude")

    # -- the serial-port interface mount.py uses

    def reset_input_buffer(self):
        self.reply = b""

    def write(self, command):
        try:
            self.reply = self._answer(bytes(command))
        except DriverError as error:
            raise Refusal("GOTO_REFUSED", f"The mount's driver refused: {error}") from None

    def read_until(self, terminator=b"#", size=64):
        reply, self.reply = self.reply, b""
        return reply

    def close(self):
        pass

    def _answer(self, c):
        kind = c[:1]
        if kind == b"K":
            return c[1:2] + b"#" if self.client.get("connected") else b""
        if kind == b"h":
            # The driver keeps its own clock; mount.py takes a year of 22 for
            # a handset not set up, so this is today's.
            t = time.localtime()
            return bytes([t.tm_hour, t.tm_min, t.tm_sec, t.tm_mon, t.tm_mday, t.tm_year % 100, 0, 0]) + b"#"
        if kind == b"L":
            return (b"1" if self.client.get("slewing") else b"0") + b"#"
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
            if self.can["cansettracking"]:
                self.client.put("tracking", Tracking=c[1] != 0)
            return b"#"
        if kind == b"M":
            self._stop()
            return b"#"
        if kind == b"P":
            axis, order = RA if c[2] == 16 else DEC, c[3]
            if order in (36, 37):        # fixed rate, 0 to 9
                speed = RATES.get(c[4], 0)
            else:                        # 6, 7: variable, in quarter-arcseconds a second
                speed = (c[4] * 256 + c[5]) / 4 / 3600
            self._rate(axis, speed if order in (36, 6) else -speed)
            return b"#"
        return b""


def _precess(ra, dec, to_j2000):
    """Between the true equator and equinox of date and J2000, degrees."""
    import sky  # noqa: F401 - astropy's settings for offline use
    from astropy import units as u
    from astropy.coordinates import FK5, SkyCoord
    from astropy.time import Time
    now = FK5(equinox=Time.now())
    if to_j2000:
        found = SkyCoord(ra * u.deg, dec * u.deg, frame=now).transform_to(FK5(equinox="J2000"))
    else:
        found = SkyCoord(ra * u.deg, dec * u.deg, frame=FK5(equinox="J2000")).transform_to(now)
    return float(found.ra.deg), float(found.dec.deg)


def describe(client):
    """What the telescope says of itself, for the doctor and status. Reads only."""
    get = lambda what: _quiet(client, what)
    return {"link": client.name(), "name": get("name"), "driver": get("driverinfo"),
            "connected": get("connected"), "alignment": get("alignmentmode"),
            "system": SYSTEMS.get(get("equatorialsystem")), "site": [get("sitelatitude"), get("sitelongitude")],
            "at_park": get("atpark"), "tracking": get("tracking"), "slewing": get("slewing"),
            "can": {what: get(what) for what in ("canslewasync", "canfindhome", "canpark", "cansettracking")}}


def _quiet(client, what):
    try:
        return client.get(what)
    except DriverError:
        return None


def client_from(settings):
    address = settings.get("address")
    if not address:
        seen = find()
        if not seen:
            raise Refusal("MOUNT_NOT_CONNECTED", "No Alpaca server answered on this network. Start the driver's "
                          "Alpaca server (ASCOM Remote, or the driver's own), or set address = \"HOST:PORT\" "
                          "under [mount] in config.toml.")
        address = seen[0]
    return Client(address, settings.get("device", 0))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["find", "status"])
    ap.add_argument("--address", help="HOST:PORT of the Alpaca server, if not the one in config.toml")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.command == "find":
        found = []
        for where in find():
            try:
                found.append({"address": where, "devices": devices(where)})
            except (OSError, ValueError) as error:
                found.append({"address": where, "error": str(error)})
        if args.json:
            print(json.dumps(found, indent=1))
            return
        for server in found:
            print(server["address"])
            for d in server.get("devices", []):
                print(f"  {d['type']} {d['number']}: {d['name']}")
            if "error" in server:
                print(f"  could not list its devices: {server['error']}")
        if not found:
            print("No Alpaca server answered. Discovery does not cross routers; give its address with --address.")
        return
    import config
    settings = dict(config.hardware()["mount"])
    if args.address:
        settings["address"] = args.address
    seen = describe(client_from(settings))
    print(json.dumps(seen, indent=1) if args.json else "\n".join(f"{k}: {v}" for k, v in seen.items()))


if __name__ == "__main__":
    try:
        main()
    except Refusal as refusal:
        sys.exit(refusal.message)
