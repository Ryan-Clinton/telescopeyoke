#!/usr/bin/env python3
"""The Starlight Xpress USB filter wheel (7 positions), on the camera's hub.

    ./sxwheel.py status         the filter in the light path and the wheel's size
    ./sxwheel.py move Ha        turn to a filter by its name, or by its number:
    ./sxwheel.py move 3         waits until it has arrived (--timeout, seconds)

The names are [filterwheel] filters in config.toml, position 1 first. The
order there is a guess until someone has looked: move 1, then see which
filter is in the light path. shoot.py writes the filter into each frame's
header (FILTER) when the wheel answers.

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
    try:
        import hid
    except ImportError:
        raise WheelError("The Python hidapi module is missing: sudo apt-get install python3-hid "
                         "(./install.sh does it).")
    return hid


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
                raise WheelError(f"No filter named {text!r}. The wheel holds: {listed or 'nothing named'}.")
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


def current_name(hid=None):
    """The name of the filter in the light path, for a frame's header; None
    when there is no wheel, no module, it is turning, or the position has
    no name. Never raises: a run carries on without it."""
    if config.DEMO:
        return None
    try:
        with Wheel.open(hid) as wheel:
            current, _ = wheel.status()
    except Exception:
        return None
    known = names()
    return (known[current - 1] or None) if 0 < current <= len(known) else None


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
