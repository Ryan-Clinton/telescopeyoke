#!/usr/bin/env python3
"""The focuser's motor: a 28BYJ-48 stepper driven by an Arduino Nano.

    ./focuser.py flash         load firmware/focuser onto the Nano
    ./focuser.py test          a quarter turn one way, then back
    ./focuser.py move 200      that many half-steps (4096 to a turn): plus takes the
                               drawtube out on the 150P, minus brings it in

Building and wiring it: docs/focuser.md. `./focus.py --motor` uses it to
bring the stars to focus with nobody touching the telescope.
"""
import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

import config
import host

ROOT = Path(__file__).parent
SKETCH = ROOT / "firmware" / "focuser"
MATCH = "1a86"              # the CH340 chip on a Nano clone, as /dev/serial/by-id names it
TURN = 4096                 # half-steps to one turn of the motor's shaft
MOST = 10 * TURN            # the firmware refuses more in one order
STEP_SECONDS = 0.010       # as the firmware's STEP_MS
# A Nano clone usually has the old bootloader; a genuine one the new.
BOARDS = ("arduino:avr:nano:cpu=atmega328old", "arduino:avr:nano:cpu=atmega328")


def find_port(port=None):
    """The Nano's port: the one named, or the one whose USB adapter matches.
    Never a guess, since the handset's lead is a serial port too."""
    match = config.hardware().get("focuser", {}).get("serial_match", MATCH)
    found = port or host.serial_port(match)
    if not found:
        seen = ", ".join(f"{device} ({name})" for device, name in host.serial_ports())
        sys.exit(f"No serial port matches \"{match}\". Ports seen: {seen or 'none'}. "
                 "Plug in the Nano, or name its port with --port.")
    return found


class Focuser:
    """The Nano, once it runs firmware/focuser."""

    def __init__(self, link):
        self.link = link

    @classmethod
    def open(cls, port=None):
        import serial
        link = serial.Serial(find_port(port), 9600, timeout=1)
        time.sleep(2)               # opening the port restarts a Nano; let it come up
        link.reset_input_buffer()
        focuser = cls(link)
        if focuser.ask(":?", 2) != "TY focuser 1":
            link.close()
            sys.exit("The Nano did not answer as a focuser. Load the firmware with ./focuser.py flash")
        return focuser

    def ask(self, order, wait):
        self.link.write(order.encode() + b"\n")
        until = time.monotonic() + wait
        reply = b""
        while time.monotonic() < until and not reply.endswith(b"\n"):
            reply += self.link.read(1)
        return reply.decode(errors="replace").strip()

    def move(self, steps):
        """Turn the motor by `steps` half-steps and wait for it to finish."""
        if not steps or abs(steps) > MOST:
            raise ValueError(f"a move is 1 to {MOST} half-steps, not {steps}")
        reply = self.ask(f":M{steps:+d}", abs(steps) * STEP_SECONDS + 3)
        if reply != f"OK {steps}":
            raise RuntimeError(f"the focuser answered {reply!r} to a move of {steps}")

    def close(self):
        self.link.close()


def flash(port=None):
    """Compile firmware/focuser and load it, trying each kind of Nano."""
    cli = shutil.which("arduino-cli") or shutil.which("arduino-cli", path=str(Path.home() / ".local" / "bin"))
    if not cli:
        sys.exit("arduino-cli is not installed: see docs/focuser.md")
    port = find_port(port)
    for board in BOARDS:
        subprocess.run([cli, "compile", "-b", board, str(SKETCH)], check=True, stdout=subprocess.DEVNULL)
        try:
            loaded = subprocess.run([cli, "upload", "-b", board, "-p", port, str(SKETCH)],
                                    capture_output=True, timeout=60).returncode == 0
        except subprocess.TimeoutExpired:       # the uploader waits for ever on a port that has gone
            sys.exit(f"Loading the firmware stalled: is the Nano still plugged in at {port}?")
        if loaded:
            print(f"firmware loaded on {port} ({board})")
            return
    sys.exit(f"Could not load the firmware on {port} as either kind of Nano.")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["flash", "test", "move"])
    ap.add_argument("steps", nargs="?", type=int, help="for move: half-steps, minus for the other way")
    ap.add_argument("--port", help="the Nano's serial port, if it is not found by name")
    args = ap.parse_args(argv)

    if args.command == "flash":
        return flash(args.port)
    if args.command == "move" and not args.steps:
        ap.error("move needs a number of half-steps")
    focuser = Focuser.open(args.port)
    try:
        for steps in ([TURN // 4, -TURN // 4] if args.command == "test" else [args.steps]):
            focuser.move(steps)
            print(f"moved {steps:+d} half-steps")
    finally:
        focuser.close()
    if args.command == "test":
        print("The shaft should have made a quarter turn and come back. The Nano cannot "
              "tell whether it did: a motor that only buzzes has two signal wires swapped.")


if __name__ == "__main__":
    main()
