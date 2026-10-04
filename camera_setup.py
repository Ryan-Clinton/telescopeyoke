#!/usr/bin/env python3
"""Get the camera ready: check each thing it needs, and put right what can be.

    ./camera_setup.py                 check, fix what it can, take a test frame
    ./camera_setup.py --check         look only; change nothing
    ./camera_setup.py --sdk FILE.zip  use this copy of Altair's SDK
    ./camera_setup.py --open          open the download page if the SDK is needed
    ./camera_setup.py --json          the same as data, for programs

It goes through, in order: Python; whether the camera is plugged in and the
system has a driver for it; Altair's library files; whether the library loads
and sees the camera; and one short exposure. It stops at the first thing it
cannot put right and says what to do about it.

The one thing it cannot fetch is Altair's SDK: their site gives it only to a
logged-in visitor. Download "Altair Camera SDK" from altairastro.help (free
registration) and leave the zip in your Downloads folder; this finds it there
and takes out the two files it needs. The files are Altair's and stay out of
the repository, in vendor/altair/.

With the INDI route ([camera] backend = "indi", the default on Linux) there
are no files to fetch: it reports the doctor's checks and takes the frame.
Nothing here moves the mount.
"""
import argparse
import struct
import sys
import time
import zipfile
from pathlib import Path

import config
import host
import interface

ROOT = Path(__file__).parent
SDK_PAGE = "https://www.altairastro.help/download-category/software/"
# "warn" is something worth knowing that does not stop the camera working.
OK, FIXED, WARN, TODO, FAIL = "ok", "fixed", "warn", "todo", "fail"
MARK = {OK: "✓", FIXED: "✓", WARN: "!", TODO: "→", FAIL: "✗"}
GOOD = (OK, FIXED, WARN)


def vendor():
    import altair
    return altair.VENDOR


# The library for this system, as (file name wanted, words its folder in the
# SDK zip must have, words it must not). The zip holds one for every system.
def library():
    if host.WINDOWS:
        return "altaircam.dll", ("win", "x64"), ("arm",)
    if sys.platform == "darwin":
        return "libaltaircam.dylib", ("mac",), ()
    return "libaltaircam.so", ("linux", "x64"), ("arm",)


def needed():
    """The files vendor/altair/ must hold. The wrapper everywhere; the library
    itself on Windows, where nothing installs it system-wide."""
    return ["altaircam.py"] + ([library()[0]] if host.WINDOWS else [])


def missing():
    return [name for name in needed() if not (vendor() / name).exists()]


def find_sdk(given=None):
    """The newest copy of Altair's SDK zip: the one named, or one left in the
    Downloads folder, the project folder or vendor/."""
    if given:
        path = Path(given).expanduser()
        return path if path.exists() else None
    places = [Path.home() / "Downloads", ROOT, ROOT / "vendor", vendor()]
    found = [p for place in places if place.is_dir() for p in place.glob("altaircamsdk*.zip")]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def members(sdk):
    """Which entries of the SDK zip are the wrapper and this system's library:
    {file name: entry name}."""
    name, wanted, unwanted = library()
    chosen = {}
    with zipfile.ZipFile(sdk) as z:
        for entry in z.namelist():
            folder, _, base = entry.lower().replace("\\", "/").rpartition("/")
            parts = folder.split("/")
            if base == "altaircam.py" and "altaircam.py" not in chosen:
                chosen["altaircam.py"] = entry
            elif (base == name and all(w in parts for w in wanted)
                  and not any(u in part for u in unwanted for part in parts)):
                chosen[name] = entry
    return chosen


def install_sdk(sdk):
    """Copy the wrapper and this system's library out of the SDK zip into
    vendor/altair/. Returns the names copied."""
    chosen = members(sdk)
    lacking = [name for name in needed() if name not in chosen]
    if lacking:
        raise ValueError(f"{sdk.name} has no {' or '.join(lacking)} in it; is it Altair's camera SDK?")
    vendor().mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(sdk) as z:
        for name, entry in chosen.items():
            # Written under the name wanted, never the entry's own path.
            (vendor() / name).write_bytes(z.read(entry))
    return sorted(chosen)


class Steps:
    """The checks in order, each printed as it is done."""

    def __init__(self, quiet=False):
        self.done, self.quiet = [], quiet

    def add(self, name, status, message, **more):
        self.done.append({"step": name, "status": status, "message": message, **more})
        print(f"  {MARK[status]} {message}", flush=True)
        return status in GOOD

    def ready(self):
        return all(s["status"] in GOOD for s in self.done)


def check_files(steps, args):
    """Altair's files in vendor/altair/, fetched from the SDK zip if need be."""
    lacking = missing()
    if not lacking:
        return steps.add("files", OK, "Altair's library files are in vendor/altair/")
    sdk = find_sdk(args.sdk)
    if sdk is None or args.check:
        if args.open and not args.check:
            import webbrowser
            webbrowser.open(SDK_PAGE)
        found = f" ({sdk.name} is there to take them from; run without --check)" if sdk else ""
        return steps.add("files", TODO,
                         f"Altair's library is not here yet ({', '.join(lacking)}){found}. "
                         f"Download \"Altair Camera SDK\" from {SDK_PAGE} (their site asks you to "
                         "register and log in), leave the zip in your Downloads folder, and run "
                         "this again.", url=SDK_PAGE)
    try:
        copied = install_sdk(sdk)
    except (ValueError, OSError, zipfile.BadZipFile) as problem:
        return steps.add("files", FAIL, f"Altair's library could not be taken from {sdk}: {problem}")
    return steps.add("files", FIXED, f"copied {' and '.join(copied)} from {sdk.name} into vendor/altair/")


def check_library(steps):
    """The library loads and lists the camera: the doctor's own lines."""
    import altair
    good = True
    for status, message in altair.checks()[1:]:      # the first is Python, done already
        good = steps.add("library", {host.OK: OK, host.WARN: WARN, host.FAIL: FAIL}[status],
                         message) and good
    return good


def test_frame(steps, exposure, gain):
    """One short exposure, published to the web page, with what came back."""
    import numpy as np

    import snap
    from camera import WHITE, Camera
    began = time.perf_counter()
    try:
        with Camera(gain=gain) as cam:
            opened = time.perf_counter() - began
            details = cam.details() if hasattr(cam, "details") else {"model": cam.name}
            cam.frame(exposure)      # the first frame after opening is often slow
            began = time.perf_counter()
            mosaic, header = cam.frame(exposure)
            took = time.perf_counter() - began
            details = cam.details() if hasattr(cam, "details") else details
    except (Exception, SystemExit) as problem:
        return steps.add("frame", FAIL, f"no test frame: {str(problem) or type(problem).__name__}")
    frame = {"size": [int(mosaic.shape[1]), int(mosaic.shape[0])], "seconds": round(took, 2),
             "exposure_s": exposure, "min": int(mosaic.min()), "median": float(np.median(mosaic)),
             "max": int(mosaic.max()), "bayer": header.get("BAYERPAT"), "open_s": round(opened, 2)}
    try:
        snap.publish(mosaic, kind="camera setup test frame", detail=f"{exposure:g} s")
    except Exception:
        pass      # the picture is a nicety; the numbers are the test
    if frame["max"] > WHITE:
        return steps.add("frame", FAIL, f"the test frame has values up to {frame['max']}, above the "
                                        f"sensor's {WHITE}: the bit depth is being read wrongly",
                         frame=frame, camera=details)
    if details.get("serial"):
        steps.add("camera", OK, f"serial {details['serial']}, firmware {details.get('firmware')}, "
                                f"readout speed {details.get('readout_speed')} of "
                                f"{details.get('max_readout_speed')}", camera=details)
    return steps.add("frame", OK, f"test frame: {frame['size'][0]} x {frame['size'][1]}, "
                                  f"{exposure:g} s exposure arrived in {frame['seconds']} s, values "
                                  f"{frame['min']} to {frame['max']} (median {frame['median']:.0f})",
                     frame=frame)


def run(args):
    backend = config.hardware()["camera"]["backend"]
    steps = Steps()
    print(f"Camera setup ({'Altair library' if backend == 'altair' else 'INDI driver'})\n", flush=True)

    bits = struct.calcsize("P") * 8
    version = ".".join(str(v) for v in sys.version_info[:3])
    if sys.version_info < (3, 11) or (host.WINDOWS and bits != 64):
        steps.add("python", FAIL, f"Python {version}, {bits}-bit: 64-bit Python 3.11 or newer is needed")
        return finish(steps, backend)
    steps.add("python", OK, f"Python {version}, {bits}-bit")

    match = config.hardware()["camera"].get("usb_match", "ALTAIR")
    device = host.camera_device(match)
    if device is None:
        steps.add("usb", FAIL, f"no camera named \"{match}\" is plugged in. Plug it in, into a "
                               "blue USB 3 socket if there is one, and run this again.")
        return finish(steps, backend)
    if not device["ready"]:
        steps.add("usb", TODO, f"{device['name']} is plugged in, but {device['detail']}. Install "
                               "AltairCapture from altairastro.help, which brings the driver, check "
                               "the camera shows a picture in it, close it, and run this again.",
                  device=device)
        return finish(steps, backend)
    steps.add("usb", OK, f"{device['name']} is plugged in ({device['detail']})", device=device)

    if backend == "altair":
        if not (check_files(steps, args) and check_library(steps)):
            return finish(steps, backend)
    else:
        import doctor
        good = True
        for status, message in (doctor.check_indi_server(), doctor.check_camera()):
            good = steps.add("indi", FAIL if status == doctor.FAIL else OK, message) and good
        if not good:
            return finish(steps, backend)

    if not args.check:
        test_frame(steps, args.exposure, args.gain)
    return finish(steps, backend)


def finish(steps, backend):
    ready = steps.ready()
    stuck = next((s for s in steps.done if s["status"] in (TODO, FAIL)), None)
    print("\n" + ("The camera is ready." if ready else
                  "Not ready yet: " + ("one thing for you to do, above." if stuck["status"] == TODO
                                       else "see the line marked ✗.")), flush=True)
    return {"ready": ready, "backend": backend, "steps": steps.done,
            "next": None if ready else stuck["message"]}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="look only: copy nothing, take no frame")
    ap.add_argument("--sdk", help="Altair's SDK zip, if it is not in the Downloads folder")
    ap.add_argument("--open", action="store_true",
                    help="open Altair's download page in the browser if the SDK is needed")
    ap.add_argument("--exposure", type=float, default=0.1, help="seconds, for the test frame")
    ap.add_argument("--gain", type=int, default=300)
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    result = interface.main("camera_setup", lambda: run(args), args.json)
    sys.exit(0 if result["ready"] else 1)


if __name__ == "__main__":
    main()
