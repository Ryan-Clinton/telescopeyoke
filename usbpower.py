"""Cut the camera's power at the powered hub's port, and give it back, from
the laptop: what pressing the hub's port button twice does.

The camera's jam (docs/camera-fault.md) clears only when its power is cut:
on 30 October and 1 November 2026 Altair's own replug, a software reset,
could not bring it back, five seconds without power at the hub's button
did. The hub (Realtek 0bda:0411 with its USB 2 half 0bda:5411) switches
each port's power on its own ("ppps"), so uhubctl can do the same. A USB 3
port is two ports, one on each half of the hub; both are turned off, or the
camera keeps its power through the other.

The port is found from the kernel's record of where the camera is, and
remembered, because a jammed camera can drop off USB altogether and then
nothing says where it was.
"""
import json
import os
from pathlib import Path
import subprocess
import time

import config

USB = Path("/sys/bus/usb/devices")
VENDOR = "16d0"                     # the camera's USB vendor (MCS, which Altair's cameras use)
OFF_S = 8.0                         # without power; five seconds cleared it on 1 November 2026
BACK_S = 30.0                       # for the camera to be on USB again once powered
REMEMBERED = config.DATA / "cache" / "camera-usb-port.json"


class PowerError(RuntimeError):
    pass


def find(root=USB, vendor=VENDOR):
    """The camera's place on USB as the kernel names it ("2-5.1"), or None."""
    root = Path(root)
    for here in sorted(root.iterdir()) if root.exists() else []:
        try:
            if (here / "idVendor").read_text().strip() == vendor:
                return here.name
        except OSError:
            continue
    return None


def ports(place, root=USB):
    """[(hub, port)] to switch for the camera at place: its own hub port, and
    the same socket's port on the hub's other (USB 2 or 3) half, from the
    kernel's peer link. A camera plugged straight into the laptop has no hub
    port to switch."""
    if "." not in place:
        raise PowerError(f"the camera is on the laptop's own port {place}, not behind the hub: "
                         "only the hub can cut its power")
    hub, port = place.rsplit(".", 1)
    found = [(hub, int(port))]
    peer = Path(root) / hub / f"{hub}:1.0" / f"{hub}-port{port}" / "peer"
    try:
        name = os.path.basename(os.path.realpath(peer))          # "1-5-port1"
        other, _, number = name.rpartition("-port")
        if other and number.isdigit() and other != hub:
            found.append((other, int(number)))
    except OSError:
        pass
    return found


def speed(hub, root=USB):
    """A hub's link speed in Mb/s from the kernel (5000 for a USB 3 hub's
    half, 480 for its USB 2 half), 0 where it cannot be read."""
    try:
        return int((Path(root) / hub / "speed").read_text().strip())
    except (OSError, ValueError):
        return 0


def remember(place, path=None):
    path = Path(path or REMEMBERED)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"place": place, "seen": time.strftime("%Y-%m-%d %H:%M:%S")}) + "\n",
                    encoding="utf-8")


def remembered(path=None):
    try:
        return json.loads(Path(path or REMEMBERED).read_text(encoding="utf-8"))["place"]
    except (OSError, ValueError, KeyError):
        return None


def uhubctl(hub, port, action, run=subprocess.run):
    """One uhubctl call; through sudo -n when this user cannot switch ports
    itself. A refusal is a PowerError with uhubctl's own words."""
    command = ["uhubctl", "-l", hub, "-p", str(port), "-a", action]
    if os.geteuid() != 0:
        command = ["sudo", "-n"] + command
    try:
        done = run(command, capture_output=True, text=True, timeout=20)
    except FileNotFoundError:
        raise PowerError("uhubctl is not installed (sudo apt-get install uhubctl, or ./install.sh)")
    except subprocess.TimeoutExpired:
        raise PowerError(f"uhubctl did not answer turning {action} hub {hub} port {port}")
    if done.returncode != 0:
        said = (done.stderr or done.stdout or "").strip().splitlines()
        raise PowerError(f"uhubctl could not turn {action} hub {hub} port {port}: "
                         + (said[-1] if said else f"exit {done.returncode}"))
    return done


def cycle(off=OFF_S, back=BACK_S, root=USB, run=subprocess.run, sleep=time.sleep,
          clock=time.monotonic, memory=None, say=print):
    """Cut the camera's power at the hub for off seconds, give it back, and
    wait up to back seconds for it to be on USB again. The camera must not be
    open in a program at the time. Returns what was done and whether it came
    back; a camera that does not come back is a result, not an error."""
    place = find(root)
    if place:
        remember(place, memory)
    else:
        place = remembered(memory)
        if not place:
            raise PowerError("the camera is not on USB and its hub port has not been seen yet: "
                             "press the hub's port button for it once")
        say(f"The camera is not on USB; using its last place, {place}.")
    switched = ports(place, root)
    say("Camera power off at the hub: " + ", ".join(f"{h} port {p}" for h, p in switched))
    try:
        for hub, port in switched:
            uhubctl(hub, port, "off", run)
        sleep(off)
    finally:
        # Always given back, whatever went wrong, the USB 3 half first: on
        # 1 November 2026, the USB 2 half switched on first, the camera came
        # back at 480 Mb/s on it instead of 5000.
        for hub, port in sorted(switched, key=lambda s: -speed(s[0], root)):
            try:
                uhubctl(hub, port, "on", run)
            except PowerError as problem:
                say(f"Could not give the power back: {problem}. Press the hub's port button.")
                raise
    say(f"Power back after {off:g} s; waiting for the camera.")
    began = clock()
    while clock() - began < back:
        if find(root):
            after = round(clock() - began, 1)
            say(f"Camera back on USB after {after:g} s.")
            return {"place": place, "ports": [f"{h}.{p}" for h, p in switched], "off_s": off,
                    "back": True, "back_after_s": after}
        sleep(0.5)
    say(f"The camera did not come back on USB within {back:g} s.")
    return {"place": place, "ports": [f"{h}.{p}" for h, p in switched], "off_s": off,
            "back": False, "back_after_s": None}
