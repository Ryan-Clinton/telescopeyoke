#!/usr/bin/env python3
"""Bring back a USB lead that has dropped off, without anyone at the telescope.

    ./usbguard.py status     where the handset's lead and the filter wheel were
                             last seen on the USB tree, and whether they are there
    ./usbguard.py recover    re-enable the hub port each one hangs from, if it
                             has gone, and wait for it to come back

15 November 2026, 20:00:00: the small hub on port 3 of the 183M's own hub,
which carries the handset's lead (FTDI) and the filter wheel, dropped off
the laptop ("usb 1-5-port3: Cannot enable. Maybe the USB cable is bad?",
then "unable to enumerate"); the kernel's own retries and power cycle did
not bring it back. Writing 1 and then 0 to that port's `disable` file in
/sys did, two minutes later, with nobody touching anything. The same hub
had dropped and come back about fifteen times between 04:00 and 05:27 on
13 November. The person: they cannot be asked to replug a lead at 2 am.

So every script that finds the handset or the wheel missing calls
`recover()` before giving up (mount.py, sxwheel.py), and `remember()` keeps
where each was last seen whenever it is found. A device whose own hub has
gone is recovered by re-enabling the port that hub hung from; one whose hub
is still there, by its own port. It moves nothing: it only asks the USB
hub to try the port again. Writing to /sys needs root: `sudo -n`, which
fails at once rather than waiting for a password if it is not allowed.
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import config

USB = Path("/sys/bus/usb/devices")
KEPT = config.DATA / "cache" / "usb_seen.json"
WHEEL_ID = ("1278", "0920")          # Starlight Xpress filter wheel
NAME = re.compile(r"^\d+-\d+(\.\d+)*$")
WAIT_S = 12                          # for the device to come back after a port is re-enabled
TRIES = 3


def _usb_name(path):
    """The USB device's name (such as 1-5.3.4) among the parts of a /sys path, the deepest one."""
    names = [part for part in Path(path).parts if NAME.match(part)]
    return names[-1] if names else None


def _handset_now():
    """The USB device under the handset's serial lead now, or None."""
    import host
    try:
        port = host.serial_port(config.hardware()["mount"]["serial_match"])
    except Exception:      # noqa: BLE001 - no config or no lead: not seen
        return None
    if not port:
        return None
    tty = Path(port).resolve().name
    return _usb_name((Path("/sys/class/tty") / tty / "device").resolve())


def _wheel_now():
    for dev in USB.glob("*"):
        try:
            if ((dev / "idVendor").read_text().strip(), (dev / "idProduct").read_text().strip()) == WHEEL_ID:
                return dev.name
        except OSError:
            continue
    return None


FINDERS = {"handset": _handset_now, "wheel": _wheel_now}


def _kept():
    try:
        return json.loads(KEPT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def remember(*names):
    """Keep where each device (all of them, or those named) is on the USB tree now."""
    kept = _kept()
    for name in names or FINDERS:
        where = FINDERS[name]()
        if where:
            kept[name] = {"usb": where, "seen": time.time()}
    try:
        KEPT.parent.mkdir(parents=True, exist_ok=True)
        KEPT.write_text(json.dumps(kept, indent=1), encoding="utf-8")
    except OSError:
        pass
    return kept


def _port_for(usb):
    """The hub port to re-enable for a missing device last seen at `usb`
    (such as 1-5.3.4): the port its highest missing ancestor hung from. A
    root port (1-5) has no hub port in /sys to re-enable: None."""
    chain = []
    name = usb
    while "." in name:
        chain.append(name)
        name = name.rsplit(".", 1)[0]
    chain.append(name)                     # the root port's device, e.g. 1-5
    missing = None
    for n in reversed(chain):              # top down: the first one gone
        if not (USB / n).exists():
            missing = n
            break
    if missing is None or "." not in missing:
        return None
    hub, port = missing.rsplit(".", 1)
    return USB / hub / f"{hub}:1.0" / f"{hub}-port{port}"


def _write(path, text):
    try:
        path.write_text(text)
        return None
    except OSError:
        r = subprocess.run(["sudo", "-n", "tee", str(path)], input=text, text=True,
                           capture_output=True, timeout=10)
        return None if r.returncode == 0 else (r.stderr.strip() or f"sudo tee exit {r.returncode}")


def recover(*names, say=print):
    """Bring back each named device (all by default) that has gone from the
    USB tree, by re-enabling the port it hangs from. Returns {name: "there" |
    "recovered" | "not seen before" | why it failed}."""
    out = {}
    kept = _kept()
    for name in names or FINDERS:
        if FINDERS[name]():
            out[name] = "there"
            continue
        last = kept.get(name, {}).get("usb")
        if not last:
            out[name] = "not seen before: nothing to recover from"
            continue
        port = _port_for(last)
        if port is None or not (port / "disable").exists():
            out[name] = f"gone from {last}; no hub port to re-enable"
            continue
        why = None
        for attempt in range(1, TRIES + 1):
            say(f"usb: the {name} (last at {last}) has gone; re-enabling {port.name}, try {attempt}", flush=True)
            why = _write(port / "disable", "1") or (time.sleep(2) or _write(port / "disable", "0"))
            if why:
                break
            end = time.monotonic() + WAIT_S
            while time.monotonic() < end and not FINDERS[name]():
                time.sleep(0.5)
            if FINDERS[name]():
                break
        if FINDERS[name]():
            time.sleep(1)                  # the serial port's device file a moment after the device
            out[name] = "recovered"
            say(f"usb: the {name} is back", flush=True)
            remember(name)
        else:
            out[name] = f"still gone after re-enabling {port.name}" + (f" ({why})" if why else "")
            say(f"usb: {out[name]}", flush=True)
    return out


def status_lines():
    kept = _kept()
    lines = []
    for name, find in FINDERS.items():
        now = find()
        last = kept.get(name, {})
        when = time.strftime("%d %b %H:%M", time.localtime(last["seen"])) if last.get("seen") else "never"
        lines.append(f"{name}: " + (f"there, at {now}" if now else "NOT THERE")
                     + (f" (last kept at {last['usb']}, {when})" if last.get("usb") else ""))
    return lines


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Bring back the handset's lead or the filter wheel when it drops off USB.")
    ap.add_argument("action", choices=("status", "recover"))
    args = ap.parse_args()
    if args.action == "status":
        remember()
        print("\n".join(status_lines()))
    else:
        result = recover()
        print("\n".join(f"{k}: {v}" for k, v in result.items()))
        sys.exit(0 if all(v in ("there", "recovered") for v in result.values()) else 1)
