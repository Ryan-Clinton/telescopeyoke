#!/usr/bin/env python3
"""Test mode: nothing goes out on the stream while darks, flats or tests run.

    ./testmode.py on [--hours 6] [--why "hub test"]    until then, or until `off`
    ./testmode.py off                                  back to normal
    ./testmode.py status                               on or off, and why

While it is on, stream.py's watcher stays off air: no YouTube or Twitch, no
sign-in codes and no YouTube alerts to the phone. A stream already on air
stops. `on` always has an end, so a test forgotten about cannot silently
keep a real night off the air. Darks, flats (calibrate.py) and darktest.py
hold it for as long as they run, by themselves (`during`).

23 November 2026: frames from an indoor video test put the stream on air and
sent YouTube sign-in alerts to the owner's phone.
"""
import argparse
import contextlib
import os
import time

import config
import host

FOLDER = config.DATA / "cache" / "test-mode"
MANUAL = FOLDER / "manual"
HOURS = 6.0


def active(now=None):
    """Why test mode is on, or None."""
    now = now or time.time()
    try:
        until, why = MANUAL.read_text(encoding="utf-8").split("\n", 1)
        if now < float(until):
            return why.strip() or "testing"
        MANUAL.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass
    try:
        held = [p for p in FOLDER.iterdir() if p.name.isdigit()]
    except OSError:
        return None
    for path in held:
        try:
            if host.alive(int(path.name)):
                return path.read_text(encoding="utf-8").strip() or "testing"
            path.unlink(missing_ok=True)        # its command has gone
        except OSError:
            continue
    return None


def on(hours=HOURS, why="testing", now=None):
    FOLDER.mkdir(parents=True, exist_ok=True)
    MANUAL.write_text(f"{(now or time.time()) + hours * 3600}\n{why}\n", encoding="utf-8")


def off():
    """Ends the mode set by `on`; a command holding it still holds it to its end."""
    MANUAL.unlink(missing_ok=True)


@contextlib.contextmanager
def during(why):
    """Test mode for as long as this command runs, however it ends."""
    FOLDER.mkdir(parents=True, exist_ok=True)
    path = FOLDER / str(os.getpid())
    path.write_text(why, encoding="utf-8")
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["on", "off", "status"])
    ap.add_argument("--hours", type=float, default=HOURS, help=f"with on: how long (default {HOURS:g})")
    ap.add_argument("--why", default="testing", help="with on: what is being tested")
    args = ap.parse_args()
    if args.action == "on":
        if args.hours <= 0:
            ap.error("--hours must be more than 0")
        on(args.hours, args.why)
    elif args.action == "off":
        off()
    why = active()
    print(f"Test mode is on ({why}): the stream stays off air." if why else "Test mode is off.")


if __name__ == "__main__":
    main()
