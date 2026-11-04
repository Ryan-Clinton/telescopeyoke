#!/usr/bin/env python3
"""The Starlight Xpress USB filter wheel (7 positions), on the camera's hub.

    ./sxwheel.py status         the filter in the light path and the wheel's size
    ./sxwheel.py move Ha        turn to a filter by its name, or by its number:
    ./sxwheel.py move 3         waits until it has arrived (--timeout, seconds)

The names are [filterwheel] filters in config.toml, position 1 first; with
none set the positions go by number. Set them only once someone has looked:
move 1, then see which filter is in the light path, and so on round. When
the light path (train) has the wheel in it, shoot.py asks the wheel where it
is and writes that into each frame (FILTPOS, and FILTER the name): only a
position the wheel has confirmed, never one assumed.

The wheel is a USB HID device, 1278:0920. Its protocol, as INDI's driver
speaks it (indilib/indi-3rdparty, indi-sx/sxwheel.cpp): every command is
two bytes written, and two bytes read back, always (current filter, number
of filters). (0, 0) only asks. (f, 0) turns to filter f one way round;
(f + 0x80, 0) the shorter way, which is used here. While it turns the
current filter reads 0, and the number reads 0 until the wheel has finished
the turn it makes on power-up (it ends on filter 1).
"""
import argparse
import sys
import time

import config

VENDOR, PRODUCT = 0x1278, 0x0920
SHORTER_WAY = 0x80          # added to the filter number: INDI's "bidirectional" move
POLL = 0.25                 # seconds between questions while it turns, as INDI
TIMEOUT = 20.0              # a whole turn of a 7-position wheel takes a few seconds
READ_MS = 500


class WheelError(Exception):
    pass


def names(cfg=None):
    """The filters' names by position, from [filterwheel] filters; "" for a gap."""
    text = (cfg or config.hardware()).get("filterwheel", {}).get("filters", "")
    return [name.strip() for name in str(text).split(",")]


def _hid():
    """The hidapi module that opens /dev/hidraw, which the udev rule makes
    readable. Debian's python3-hid ships two: `hidraw` (the hidraw backend)
    and `hid` (libusb, which needs the USB device node itself and failed to
    open the wheel on 4 November 2026 with the rule in place). `hidraw`
    first; `hid` where only it exists (pip's hidapi on other systems)."""
    for name in ("hidraw", "hid"):
        try:
            return __import__(name)
        except ImportError:
            continue
    raise WheelError("The Python hidapi module is missing: sudo apt-get install python3-hid "
                     "(./install.sh does it).")


class Wheel:
    def __init__(self, device):
        self.device = device

    @classmethod
    def open(cls, hid=None):
        hid = hid or _hid()
        device = hid.device()
        try:
            device.open(VENDOR, PRODUCT)
        except (OSError, IOError):
            if hid.enumerate(VENDOR, PRODUCT):
                raise WheelError("The filter wheel is plugged in but may not be opened: its /dev/hidraw is "
                                 "root's alone. ./install.sh adds the udev rule (/etc/udev/rules.d/99-sxwheel.rules); "
                                 "then unplug and replug the camera's lead.")
            raise WheelError("No Starlight Xpress filter wheel found (USB 1278:0920). Is it plugged "
                             "into the camera's hub, and the camera powered?")
        return cls(device)

    def close(self):
        try:
            self.device.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _say(self, a, b=0):
        """Two bytes out, and the wheel's (current, total) back. Written
        as INDI writes them, with no report number in front."""
        if self.device.write([a, b]) < 0:
            raise WheelError("the filter wheel would not take a command")
        reply = self.device.read(2, READ_MS)
        if len(reply) < 2:
            raise WheelError("the filter wheel did not answer")
        return int(reply[0]), int(reply[1])

    def status(self):
        """(current filter, number of filters); current 0 while turning."""
        return self._say(0, 0)

    def position(self, wanted, total, known=None):
        """A filter number from a name or a number, checked against the wheel."""
        known = names() if known is None else known
        text = str(wanted).strip()
        if text.isdigit():
            number = int(text)
        else:
            found = [i + 1 for i, name in enumerate(known[:total]) if name and name.lower() == text.lower()]
            if not found:
                listed = ", ".join(f"{i + 1} {n}" for i, n in enumerate(known[:total]) if n)
                raise WheelError(f"No filter named {text!r}. The wheel holds: {listed}." if listed else
                                 f"No filter named {text!r}: the positions have no names yet ([filterwheel] "
                                 "filters); move by number, 1 to the wheel's size.")
            number = found[0]
        if not 1 <= number <= total:
            raise WheelError(f"Filter {number} is not on a {total}-position wheel.")
        return number

    def move(self, wanted, timeout=TIMEOUT, sleep=time.sleep, clock=time.monotonic):
        """Turn to a filter and wait until it is there; its number."""
        end = clock() + timeout
        current, total = self.status()
        while not total:                      # still making its power-up turn
            if clock() > end:
                raise WheelError("the filter wheel never said how many filters it has: is it still turning?")
            sleep(POLL)
            current, total = self.status()
        number = self.position(wanted, total)
        if current == number:
            return number
        self._say(number + SHORTER_WAY, 0)
        while True:
            sleep(POLL)
            current, total = self.status()
            if current == number:
                return number
            if clock() > end:
                raise WheelError(f"the filter wheel did not reach filter {number} within {timeout:g} s "
                                 f"(it says {current or 'still turning'})")


def label(number, known=None):
    known = names() if known is None else known
    name = known[number - 1] if 0 < number <= len(known) else ""
    return f"{number} ({name})" if name else str(number)


def confirmed(hid=None, say=None):
    """(position, name) of the filter in the light path as the wheel itself
    has just said it, for a frame's header: FILTPOS the position, FILTER its
    name, or "position N" while the positions have no names. None when there
    is no wheel, no module, or it is turning: then an imaging run keeps no
    frame at all (shoot.in_the_path) rather than one the wheel did not
    confirm. Never raises; `say` hears why there is none."""
    if config.DEMO:
        return None
    try:
        with Wheel.open(hid) as wheel:
            current, total = wheel.status()
    except Exception as problem:
        if say:
            say(f"the filter wheel did not answer ({problem})")
        return None
    if not current or not total:
        if say:
            say("the filter wheel is turning, or still on its power-up turn")
        return None
    known = names()
    name = known[current - 1] if current <= len(known) else ""
    return current, name or f"position {current}"


def cards(header, found):
    """Write a confirmed (position, name) into a frame's header."""
    if found:
        header["FILTPOS"], header["FILTER"] = found     # plain values: some cameras give a dict
    return header


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["status", "move"])
    ap.add_argument("filter", nargs="?", help="for move: a filter's name (as in config.toml) or number")
    ap.add_argument("--timeout", type=float, default=TIMEOUT, help="for move: seconds to wait for it to arrive")
    args = ap.parse_args(argv)
    if args.command == "move" and not args.filter:
        ap.error("move needs a filter's name or number")
    try:
        with Wheel.open() as wheel:
            if args.command == "status":
                current, total = wheel.status()
                if not total:
                    print("The wheel is still making its power-up turn.")
                elif not current:
                    print(f"Turning; a {total}-position wheel.")
                else:
                    print(f"Filter {label(current)} of {total}.")
                return 0
            number = wheel.move(args.filter, timeout=args.timeout)
            print(f"At filter {label(number)}.")
            return 0
    except WheelError as problem:
        print(f"sxwheel: {problem}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
