#!/usr/bin/env python3
"""Find the camera settings that suit this setup, by trying them.

    ./camera_test.py --capabilities     what the camera and its driver offer
    ./camera_test.py --throughput       time every way of getting frames off the camera
    ./camera_test.py --gain-sweep       try a range of gains on tonight's sky
    ./camera_test.py --gain-sweep --gains 300 900 1500 2500 --exposure 2
    ./camera_test.py --timing           does a frame take as long as the exposure asked for?
    ./camera_test.py --trail            how long is the shutter really open? From a star's trail
    ./camera_test.py --cooldown --note "3 m lead, port 2-4"   cap on, outside: do the stripes grow as it cools?

With [camera] backend = "altair" the camera is read through Altair's own
library: --capabilities then shows the model, versions and how it is
connected, and --throughput times each readout speed and measures its grain.

Through INDI, --throughput takes a few frames in each mode the driver offers (readout
speeds, smaller resolutions, binning, back-to-back "fast" exposures, native
transfer) and reports how long a frame takes in each and what share of the
time the shutter is open. It puts the camera back as it found it. Nothing
here moves the mount; the cap can be on.

--gain-sweep takes a frame of the sky at each gain and reports the sky level
and grain, how many pixels are burnt out, how many stars it can find and how
strongly they stand out. High gain lowers the camera's own noise but burns
out bright stars sooner; the best setting finds the most stars without
burning many pixels. The gain numbers are this camera's own and do not match
other makes'.

--timing asks for exposures from 0.1 s to 15 s and times how long each frame
takes to arrive. A frame cannot arrive before its shutter has closed, so if
each second asked for adds less than a second to the frame, the camera is
exposing for less than it was asked. The cap can be on.

--trail measures the exposure itself, which timing cannot. It stops the
mount following the sky for one frame, so every star draws a line whose
length is the sky's rate times the time the shutter was open, and starts it
following again. It needs stars, and the mount tracking a field well away
from the pole.
"""
import argparse
import json
import math
from pathlib import Path
import time
from xml.sax.saxutils import quoteattr

import numpy as np

import config
import interface
import records
import stacking
from camera import BACKEND, WHITE, Camera, luminance

SDK = BACKEND == "altair"   # frames come through Altair's library, not INDI

GAINS = (300, 600, 900, 1200, 1500, 1800)
ASKED = (0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 15.0)     # seconds, for --timing
# What --timing and --trail found, for `ty characterise` and for whoever fixes it.
from camera import TIMING_FILE
SIDEREAL = 15.041       # arcseconds of sky a second, at the celestial equator


def measure(mosaic):
    lum = luminance(mosaic)
    stars = stacking.find_stars(lum)
    q = stacking.quality(lum, stars)
    q["burnt"] = float((mosaic >= WHITE - 1).mean())
    # How far the typical star stands above the sky's grain.
    q["signal"] = float(np.median(stars[:, 2]) / q["noise"]) if len(stars) else 0.0
    return q


def recommend(results):
    """The gain that finds the most stars while burning out under 0.02% of
    pixels; None if no gain found any."""
    usable = [(q["stars"], gain) for gain, q in results if q["burnt"] < 0.0002 and q["stars"]]
    return max(usable)[1] if usable else None


def capabilities(cam):
    """What the driver offers, read from its own description of itself."""
    c, name = cam.client, cam.name
    out = {"camera": name, "controls": {}, "resolutions": [], "options": {}}
    controls = c.get(name, "CCD_CONTROLS") or {}
    for element, value in controls.items():
        out["controls"][element] = {"value": float(value), "range": c.limits(name, "CCD_CONTROLS", element)}
    for mode, state in (c.get(name, "CCD_RESOLUTION") or {}).items():
        out["resolutions"].append({"mode": mode, "current": state == "On"})
    out["binning"] = {"value": (c.get(name, "CCD_BINNING") or {}).get("HOR_BIN"),
                      "range": c.limits(name, "CCD_BINNING", "HOR_BIN")}
    for prop in ("CCD_BINNING_MODE", "CCD_CAPTURE_FORMAT", "CCD_TRANSFER_FORMAT", "CCD_FAST_TOGGLE",
                 "CCD_COMPRESSION", "CCD_VIDEO_STREAM"):
        items = c.get(name, prop)
        if items:
            out["options"][prop] = {"choices": list(items),
                                    "current": next((k for k, v in items.items() if v == "On"), None)}
    return out


def show_capabilities(found):
    print(f"Camera: {found['camera']}\n\nResolution modes:")
    for r in found["resolutions"]:
        print(f"  {r['mode']}{'   current' if r['current'] else ''}")
    low, high = found["binning"]["range"] or ("?", "?")
    print(f"\nBinning: {found['binning']['value']} (range {low:g}-{high:g})\n\nControls:")
    for element, c in found["controls"].items():
        span = f"{c['range'][0]:g}-{c['range'][1]:g}" if c["range"] else "range not given"
        print(f"  {element:<11} {c['value']:g}   ({span})")
    print("\nOptions:")
    for prop, o in found["options"].items():
        print(f"  {prop:<20} {o['current']}   of {', '.join(o['choices'])}")


def duty(exposure, cycle):
    """Share of the time the shutter is open, as a percentage."""
    return round(100 * exposure / cycle) if cycle else 0


def timed(cam, exposure, frames):
    """Seconds per frame over a few ordinary exposures, and what came back."""
    cam.frame(exposure)   # the first frame after a change of settings is often slow
    began = time.monotonic()
    for _ in range(frames):
        mosaic, header = cam.frame(exposure)
    cycle = (time.monotonic() - began) / frames
    # The four positions of the colour pattern: if they differ, the frame is
    # still a colour mosaic; if binning merged them, they come out the same.
    cells = [float(mosaic[i::2, j::2].mean()) for i in (0, 1) for j in (0, 1)]
    return {"cycle_s": round(cycle, 2), "duty_percent": duty(exposure, cycle),
            "size": f"{mosaic.shape[1]} x {mosaic.shape[0]}", "megabytes": round(mosaic.nbytes / 1e6, 1),
            "bayer": header.get("BAYERPAT"), "pattern_means": [round(v) for v in cells]}


def timed_fast(cam, exposure, frames):
    """Back-to-back exposures sequenced by the driver itself."""
    c, name = cam.client, cam.name
    c._send(f"<enableBLOB device={quoteattr(name)}>Also</enableBLOB>")
    c.set(name, "CCD_FAST_COUNT", FRAMES=frames)
    c.set(name, "CCD_FAST_TOGGLE", INDI_ENABLED="On")
    try:
        c.blobs.clear()
        began = time.monotonic()
        c.set(name, "CCD_EXPOSURE", CCD_EXPOSURE_VALUE=exposure)
        c.wait(lambda: len(c.blobs) >= frames, frames * (12 + 6 * exposure), f"{frames} fast frames")
        cycle = (time.monotonic() - began) / frames
    finally:
        c.set(name, "CCD_FAST_TOGGLE", INDI_DISABLED="On")
        c.set(name, "CCD_FAST_COUNT", FRAMES=1)
    return {"cycle_s": round(cycle, 2), "duty_percent": duty(exposure, cycle)}


def timed_native(cam, exposure, frames):
    """Frames sent as the camera gives them, not wrapped as FITS by the driver."""
    c, name = cam.client, cam.name
    c.set(name, "CCD_TRANSFER_FORMAT", FORMAT_NATIVE="On")
    try:
        c.expose(name, exposure, timeout=12 + 6 * exposure)
        began = time.monotonic()
        for _ in range(frames):
            fmt, data = c.expose(name, exposure, timeout=12 + 6 * exposure)
        cycle = (time.monotonic() - began) / frames
    finally:
        # After a time-out the exposure is still running, and the driver
        # ignores a change of format until it is stopped.
        c.set(name, "CCD_ABORT_EXPOSURE", ABORT="On")
        c.pump(1)
        c.set(name, "CCD_TRANSFER_FORMAT", FORMAT_FITS="On")
    return {"cycle_s": round(cycle, 2), "duty_percent": duty(exposure, cycle),
            "format": fmt, "megabytes": round(len(data) / 1e6, 1)}


def throughput(exposure, frames, gain):
    """Time each way of getting frames off the camera. Returns a list of
    {"mode", ...measurements} or {"mode", "failed"}; the camera is put back
    as it was after each."""
    results = []

    def trial(mode, change, restore, measure=timed):
        """Open the camera afresh, apply a setting, measure, put it back."""
        try:
            with Camera(gain=gain) as cam:
                change(cam)
                try:
                    result = measure(cam, exposure, frames)
                finally:
                    restore(cam)
            results.append({"mode": mode, **result})
        except (Exception, SystemExit) as problem:
            results.append({"mode": mode, "failed": str(problem) or type(problem).__name__})
        row = results[-1]
        print(f"{mode:<34} " + (f"failed: {row['failed']}" if "failed" in row else
              f"{row['cycle_s']:>6.2f} s  {row['duty_percent']:>3}%  "
              f"{row.get('size', ''):<12} {row.get('bayer') or ''} {row.get('pattern_means', '')}"),
              flush=True)

    nothing = lambda cam: None
    with Camera(gain=gain) as cam:
        found = capabilities(cam)
    speed = found["controls"].get("Speed")
    full = next((r["mode"] for r in found["resolutions"] if r["current"]), None)
    print(f"{frames} frames of {exposure:g} s in each mode\n"
          f"{'mode':<34} {'cycle':>8} {'open':>4}  {'frame':<12} colour pattern")
    trial("as it is now", nothing, nothing)
    if speed and speed["range"]:
        was = speed["value"]
        for level in range(int(speed["range"][0]), int(speed["range"][1]) + 1):
            if level != was:
                trial(f"readout speed {level}",
                      lambda cam, level=level: cam.client.set(cam.name, "CCD_CONTROLS", Speed=level),
                      lambda cam: cam.client.set(cam.name, "CCD_CONTROLS", Speed=was))
    for r in found["resolutions"]:
        if not r["current"]:
            trial(f"resolution {r['mode']}",
                  lambda cam, mode=r["mode"]: cam.client.set(cam.name, "CCD_RESOLUTION", **{mode: "On"}),
                  lambda cam: cam.client.set(cam.name, "CCD_RESOLUTION", **{full: "On"}))
    for how in (found["options"].get("CCD_BINNING_MODE") or {}).get("choices", []):
        def bin2(cam, how=how):
            cam.client.set(cam.name, "CCD_BINNING_MODE", **{how: "On"})
            cam.client.set(cam.name, "CCD_BINNING", HOR_BIN=2, VER_BIN=2)
        trial(f"binned 2x2 ({how})", bin2,
              lambda cam: cam.client.set(cam.name, "CCD_BINNING", HOR_BIN=1, VER_BIN=1))
    if "CCD_FAST_TOGGLE" in found["options"]:
        trial("fast exposure (driver sequences)", nothing, nothing, timed_fast)
    if "FORMAT_NATIVE" in (found["options"].get("CCD_TRANSFER_FORMAT") or {}).get("choices", []):
        trial("native transfer (no FITS)", nothing, nothing, timed_native)
    return results


def timing_fit(rows):
    """What a run of {"asked_s", "cycle_s"} shows: the fixed time a frame
    costs (`overhead_s`) and what each second asked for adds
    (`seconds_per_second_asked`). That should be 1. Under 1, frames are
    arriving sooner than their exposures could have ended."""
    asked, cycle = np.array([r["asked_s"] for r in rows]), np.array([r["cycle_s"] for r in rows])
    per_second, overhead = np.polyfit(asked, cycle, 1)
    short = bool(per_second < 0.9)
    return {"seconds_per_second_asked": round(float(per_second), 3), "overhead_s": round(float(overhead), 2),
            "exposes_short": short,
            "verdict": (f"Each second asked for adds {per_second:.2f} s to a frame, and a frame cannot arrive "
                        f"before its shutter closes: the camera is exposing for about {per_second:.0%} of the "
                        "time asked, or less. Integration times are overstated by that much. --trail measures "
                        "the exposure itself." if short else
                        f"Each second asked for adds {per_second:.2f} s to a frame, as it should. That does "
                        "not prove the shutter is open that long; --trail measures the exposure itself.")}


def timing(gain, asked=ASKED, frames=3):
    """Time frames at each exposure asked for. Returns timing_fit()'s account
    with the rows, and keeps it."""
    rows = []
    print(f"{'asked':>7} {'frame took':>11} {'more than asked':>16}")
    with Camera(gain=gain) as cam:
        cam.shutter = 1.0            # time what the camera does with exactly what it is asked
        for seconds in asked:
            cam.frame(seconds)       # the first frame after a change is often slow
            began = time.monotonic()
            for _ in range(frames):
                cam.frame(seconds)
            cycle = (time.monotonic() - began) / frames
            rows.append({"asked_s": seconds, "cycle_s": round(cycle, 3)})
            print(f"{seconds:>6g}s {cycle:>10.2f}s {cycle - seconds:>+15.2f}s", flush=True)
    found = dict(timing_fit(rows), rows=rows, saved=time.time())
    print("\n" + found["verdict"])
    remember("timing", found)
    return found


def remember(key, found):
    kept = {}
    if TIMING_FILE.exists():
        try:
            kept = json.loads(TIMING_FILE.read_text(encoding="utf-8"))
        except ValueError:
            pass
    kept[key] = found
    TIMING_FILE.parent.mkdir(parents=True, exist_ok=True)
    records.write(TIMING_FILE, kept)


def trail_length(lum, most=12):
    """(length in pixels, how many trails) of the lines the brightest stars
    drew in a frame taken with the mount not following the sky. A line of
    length L spreads its light along itself with variance L²/12, on top of
    the star's own width, which is read from the line's breadth."""
    from scipy import ndimage
    work = ndimage.gaussian_filter(lum.astype(np.float32), 1.0)
    work -= ndimage.median_filter(work[::4, ::4], 25).repeat(4, axis=0).repeat(4, axis=1)[:work.shape[0], :work.shape[1]]
    noise = 1.4826 * float(np.median(np.abs(work[::4, ::4] - np.median(work[::4, ::4])))) + 1e-6
    mask = work > 6 * noise
    labels, count = ndimage.label(mask)
    if not count:
        return None, 0
    index = np.arange(1, count + 1)
    value = np.where(mask, work, 0)
    flux = ndimage.sum_labels(value, labels, index)
    area = ndimage.sum_labels(mask, labels, index)
    yy, xx = np.indices(lum.shape, dtype=np.float32)
    lengths, boxes, looked_at = [], ndimage.find_objects(labels), 0
    for label in index[np.argsort(-flux)][:3 * most]:
        if area[label - 1] < 12:
            continue
        rows, cols = boxes[label - 1]
        if rows.start == 0 or cols.start == 0 or rows.stop == lum.shape[0] or cols.stop == lum.shape[1]:
            continue     # cut off by the edge of the frame
        looked_at += 1
        weight = np.where(labels[rows, cols] == label, value[rows, cols], 0).astype(np.float64)
        total = weight.sum()
        x, y = (weight * xx[rows, cols]).sum() / total, (weight * yy[rows, cols]).sum() / total
        dx, dy = xx[rows, cols] - x, yy[rows, cols] - y
        a, b, c = (weight * dx * dx).sum() / total, (weight * dy * dy).sum() / total, (weight * dx * dy).sum() / total
        half = math.hypot((a - b) / 2, c)
        along, across = (a + b) / 2 + half, max((a + b) / 2 - half, 0.0)
        if along > 4 * max(across, 0.25):       # a line, not a blob
            lengths.append((math.sqrt(12 * (along - across)), 0.5 * math.atan2(2 * c, a - b)))
        if len(lengths) >= most:
            break
    if len(lengths) < 3:
        return None, len(lengths)
    # Every star trails the same way and as far. Two stars run together make
    # a line too, but in a direction and of a length of their own.
    turned = np.array([np.exp(2j * angle) for _, angle in lengths])
    usual = np.angle(np.median(turned.real) + 1j * np.median(turned.imag))
    along_it = [length for (length, _), t in zip(lengths, turned) if abs(np.angle(t / np.exp(1j * usual))) < math.radians(30)]
    # ...and in a frame taken with the mount stopped, most stars are lines.
    if len(along_it) < max(3, looked_at / 2):
        return None, len(along_it)
    middle = float(np.median(along_it))
    if float(np.median(np.abs(np.array(along_it) - middle))) > 0.15 * middle:
        return None, len(along_it)
    return middle, len(along_it)


def trail(asked, gain, corrected=False):
    """Stop the mount following the sky for one frame and measure the
    exposure from the stars' trails. The mount is set following again
    whatever happens."""
    import mount
    if config.DEMO:
        raise interface.Refusal("DEMO_UNSUPPORTED", "This needs real stars; the demo's sky does not turn.")
    equipment = config.hardware()
    per_pixel = 2 * 206.265 * equipment["camera"]["pixel_size_um"] / equipment["scope"]["focal_length_mm"]
    scope = mount.Mount()
    dec = mount.wrap(scope.radec()[1]) + mount.load_pointing_error(scope.axes()[1] > 90)[1]
    if abs(dec) > 70:
        raise interface.Refusal("INVALID_REQUEST", f"The telescope is at Dec {dec:+.0f}°, where the sky barely "
                                "moves. Go to a field nearer the equator first.")
    rate = SIDEREAL * math.cos(math.radians(dec))
    with Camera(gain=gain) as cam:
        if not corrected:
            cam.shutter = 1.0         # measure the camera unhelped: camera.py corrects by what is found
        speed = getattr(cam, "speed", None)
        try:
            scope.tracking(False)
            time.sleep(2)             # let the motor stop
            began = time.monotonic()
            mosaic, _ = cam.frame(asked)
            took = time.monotonic() - began
        finally:
            scope.tracking(True)
    length, count = trail_length(luminance(mosaic))
    if length is None:
        raise interface.Refusal("NO_STARS", f"Only {count} star trails could be measured; it needs three. "
                                "Go to a field with a few bright stars, or ask for a longer --exposure.")
    actual = length * per_pixel / rate
    found = {"asked_s": asked, "open_s": round(actual, 2), "share_of_asked": round(actual / asked, 3),
             "frame_took_s": round(took, 2), "trails": count, "trail_pixels": round(length, 1),
             "dec_deg": round(dec, 1), "speed": speed, "saved": time.time()}
    print(f"Asked for {asked:g} s at Dec {dec:+.0f}°, where the sky moves {rate:.1f} arcseconds a second. "
          f"{count} stars drew lines {length:.0f} pixels long ({length * per_pixel:.0f} arcseconds): the "
          f"shutter was open {actual:.1f} s, {actual / asked:.0%} of what was asked. The mount is following "
          "the sky again.")
    if corrected:
        return found                  # a check of the correction; the measurement it rests on is kept
    if abs(actual / asked - 1) >= 0.05:
        print(f"From now on the camera is asked for {asked / actual:.2f} times the exposure wanted, so the "
              "shutter is open for the time wanted.")
    remember("trail", found)
    return found


def show_details(found):
    """What Altair's library says about the camera and how it is connected."""
    for label, key in (("Camera", "model"), ("Serial number", "serial"), ("SDK version", "sdk_version"),
                       ("Firmware", "firmware"), ("Flags", "flags"), ("Bit depth", "bit_depth"),
                       ("Colour pattern", "bayer")):
        print(f"{label + ':':<16}{found[key]}")
    print(f"{'Frame:':<16}{found['size'][0]} x {found['size'][1]}")
    print(f"{'Readout speed:':<16}{found['readout_speed']} (range 0-{found['max_readout_speed']})")
    print(f"{'USB:':<16}" + ("a USB 3 camera on a USB 2 port: frames will be slow"
                             if found["usb3_camera_on_usb2_port"] else "not held back by a USB 2 port"))


def throughput_sdk(exposure, frames, gain):
    """Through Altair's library: time a frame at each readout speed, and
    measure the grain, so a faster level is only chosen if it costs nothing.
    Put the cap on for the grain figure to mean anything."""
    results = []
    with Camera(gain=gain) as cam:
        was, top = cam.handle.get_Speed(), cam.handle.MaxSpeed()
        print(f"{frames} frames of {exposure:g} s at each readout speed (now {was})\n"
              f"{'mode':<18} {'exposure':>8} {'frame':>8} {'overhead':>9} {'open':>5} {'grain':>7}")
        try:
            for level in range(top + 1):
                mode = f"readout speed {level}"
                try:
                    cam.handle.put_Speed(level)
                    row = timed(cam, exposure, frames)
                    mosaic, _ = cam.frame(exposure)
                    # Grain from the difference of neighbouring same-colour
                    # pixels, so a gradient across the frame does not count.
                    cell = mosaic[0::2, 0::2].astype(np.float32)
                    row["noise"] = round(float(np.std(cell[:, 1:] - cell[:, :-1])) / 2 ** 0.5, 2)
                    row["overhead_s"] = round(row["cycle_s"] - exposure, 2)
                    results.append({"mode": mode, "exposure_s": exposure, **row})
                    print(f"{mode:<18} {exposure:>7g}s {row['cycle_s']:>7.2f}s {row['overhead_s']:>8.2f}s "
                          f"{row['duty_percent']:>4}% {row['noise']:>7.2f}", flush=True)
                except Exception as problem:
                    results.append({"mode": mode, "failed": str(problem) or type(problem).__name__})
                    print(f"{mode:<18} failed: {results[-1]['failed']}", flush=True)
        finally:
            cam.handle.put_Speed(was)
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    what = ap.add_mutually_exclusive_group(required=True)
    what.add_argument("--capabilities", action="store_true")
    what.add_argument("--throughput", action="store_true")
    what.add_argument("--gain-sweep", action="store_true")
    what.add_argument("--timing", action="store_true")
    what.add_argument("--trail", action="store_true")
    what.add_argument("--stripes", metavar="SESSION",
                      help="whether a run's stripes are fixed in the sensor or new each frame, from its saved frames")
    what.add_argument("--banding", action="store_true",
                      help="how strong the horizontal stripes are with the fan on and off and at two black levels")
    what.add_argument("--cooldown", action="store_true",
                      help="cap on: the stripes, failed frames and timing every few minutes as the camera cools, "
                           "with the air temperature, dew point and USB port")
    ap.add_argument("--every", type=float, default=10.0, help="with --cooldown: minutes between sets")
    ap.add_argument("--steps", type=int, default=12, help="with --cooldown: how many sets")
    ap.add_argument("--note", default="", help="with --cooldown: what is different in this run (cable, port, heater)")
    ap.add_argument("--keep-best", action="store_true",
                    help="with --banding: keep the setting with the weakest stripes in config.toml")
    ap.add_argument("--corrected", action="store_true",
                    help="with --trail: leave camera.py's correction on, to check it; nothing is remembered")
    ap.add_argument("--gains", type=int, nargs="+", default=list(GAINS))
    ap.add_argument("--speeds", type=int, nargs="+",
                    help="with --gain-sweep: each at each of these readout speeds (Speed 2 is put back after)")
    ap.add_argument("--exposures", type=float, nargs="+",
                    help="with --gain-sweep: each gain at each of these exposures, seconds")
    ap.add_argument("--exposure", type=float,
                    help="seconds (default 2 for gains, 1 for throughput, 10 for --trail)")
    ap.add_argument("--frames", type=int,
                    help="frames per mode for --throughput (default 4), per set for --cooldown (20), "
                         "per setting for --gain-sweep (1)")
    ap.add_argument("--gain", type=int, default=1500)
    ap.add_argument("--dry-run", action="store_true", help="say what it would do; no camera, no mount")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    return interface.main("camera_test.dry_run" if args.dry_run else "camera_test", lambda: run(args), args.json)


BANDING_SETTINGS = (("on", 0), ("off", 0), ("on", 50), ("off", 50))   # (fan, offset)


def banding(mosaic):
    """How strong the horizontal stripes are: the spread of each row's
    median brightness once the slow gradient down the frame is taken out,
    in units of what the pixels' own noise would give a row (1 is none
    to speak of). Stars barely move a row's median."""
    from scipy import ndimage
    lum = luminance(mosaic).astype(np.float64)
    rows = np.median(lum, axis=1)
    smooth = ndimage.median_filter(rows, size=301, mode="nearest")
    noise = 1.4826 * np.median(np.abs(lum - np.median(lum, axis=1, keepdims=True))) / np.sqrt(lum.shape[1])
    return round(float(np.std(rows - smooth) / max(noise, 1e-9)), 1)


def row_stripes(mosaic):
    """Each row's median brightness less the slow gradient down the frame:
    the stripes alone, row by row."""
    from scipy import ndimage
    rows = np.median(luminance(mosaic).astype(np.float64), axis=1)
    return rows - ndimage.median_filter(rows, size=301, mode="nearest")


def stripes_picture(mosaic, path, size=(900, 600)):
    """A middle piece of one frame's brightness, scaled by its own noise
    the same way for every frame (sky at grey, -3 to +6 times the noise),
    so one night's stripes can be set beside another's fairly."""
    from PIL import Image
    lum = luminance(mosaic).astype(np.float64)
    h, w = lum.shape
    y0, x0 = (h - size[1]) // 2, (w - size[0]) // 2
    piece = lum[y0:y0 + size[1], x0:x0 + size[0]]
    sky = np.median(piece)
    noise = 1.4826 * np.median(np.abs(piece - sky)) + 1e-9
    scaled = np.clip((piece - sky) / noise, -3, 6)
    Image.fromarray(((scaled + 3) / 9 * 255).astype(np.uint8)).save(path, quality=90)
    return str(path)


def stripes_in(session, most=12, say=print):
    """Whether a run's stripes are fixed in the sensor or new in each frame,
    from its saved frames (the camera is not used): how alike the stripes
    of one frame are to another's, and how big they are in one frame and in
    the average of all. Alike and as big averaged means dark frames take
    them out; unalike and shrinking means stacking and dithering do."""
    from astropy.io import fits
    files = sorted(Path(session).glob("light-*.fits"))[:most]
    if len(files) < 3:
        raise interface.Refusal("NO_SESSION", f"Fewer than three saved frames in {session}.")
    found = []
    for f in files:
        with fits.open(f) as h:
            found.append(row_stripes(next(x.data for x in h if x.data is not None)))
    stripes = np.array(found)
    alike = np.corrcoef(stripes)[~np.eye(len(files), dtype=bool)]
    answer = {"session": str(session), "frames": len(files), "alike": round(float(np.median(alike)), 2),
              "one_frame_adu": round(float(np.std(stripes, axis=1).mean()), 1),
              "averaged_adu": round(float(np.std(stripes.mean(axis=0))), 1)}
    answer["fixed"] = answer["alike"] > 0.5
    with fits.open(files[0]) as h:
        first = next(x.data for x in h if x.data is not None)
    picture = config.DATA / "web" / f"stripes-{Path(session).parent.name}-{Path(session).name}.jpg"
    picture.parent.mkdir(parents=True, exist_ok=True)
    answer["picture"] = stripes_picture(first, picture)
    say(f"{Path(session).parent.name} {Path(session).name}: stripes alike from frame to frame {answer['alike']:g} "
        f"(1 the same, 0 unrelated); {answer['one_frame_adu']:g} ADU in one frame, {answer['averaged_adu']:g} in "
        f"the average of {len(files)}: " + ("fixed in the sensor, for dark frames to take out" if answer["fixed"]
                                            else "new in each frame, for stacking and dithering to spread"))
    return answer


def banding_trial(exposure, gain, frames=2, keep=False, settings=BANDING_SETTINGS, say=print):
    """Frames at each (fan, offset) in turn, and how striped each is. The
    mount is not touched. With `keep`, the weakest is kept in config.toml."""
    rows = []
    with Camera(gain=gain) as cam:
        for fan, offset in settings:
            cam.settings(fan, offset)
            cam.frame(1.0)                      # one frame to let the change take
            scores = [banding(cam.frame(exposure)[0]) for _ in range(frames)]
            rows.append({"fan": fan, "offset": offset, "banding": round(float(np.median(scores)), 1)})
            say(f"  fan {fan:3s} offset {offset:3d}: stripes {rows[-1]['banding']:g} (1 is none)")
    best = min(rows, key=lambda r: r["banding"])
    say(f"Weakest stripes: fan {best['fan']}, offset {best['offset']}.")
    if keep:
        config.save({("camera", "fan"): best["fan"], ("camera", "offset"): best["offset"]})
        say("Kept in config.toml: the camera is set so every time it is opened.")
    return {"exposure_s": exposure, "gain": gain, "settings": rows, "best": best, "kept": keep}


def sweep_point(mosaics):
    """One gain, exposure and speed of a sweep, from one or more frames: the
    first frame's sky, grain, burnt pixels and stars, and the stripes as the
    median over all of them in three ways. `stripes` is against what the
    pixels' noise would give a row (1 is none); `stripes_adu` is the raw
    row-to-row spread; `stripes_per_grain` is that spread over one pixel's
    sky grain. ADU are not comparable between gains (a higher gain gives more
    ADU for the same electrons), so a sweep is judged on the two ratios and
    on what it finds; electrons would need the camera's electrons per ADU at
    each gain, which has not been measured."""
    q = measure(mosaics[0])
    q["stripes"] = round(float(np.median([banding(m) for m in mosaics])), 1)
    q["stripes_adu"] = round(float(np.median([np.std(row_stripes(m)) for m in mosaics])), 2)
    q["stripes_per_grain"] = round(q["stripes_adu"] / max(q["noise"], 1e-9), 3)
    q["frames"] = len(mosaics)
    return q


def usb_link(devices=Path("/sys/bus/usb/devices")):
    """Which USB port the Altair camera is on and how fast it is linked, from
    the kernel's own record ({"port": "2-4", "mbps": 5000}); 480 is USB 2.
    None where there is no such record (Windows) or no camera."""
    try:
        for d in sorted(devices.iterdir()):
            product = d / "product"
            if product.exists() and product.read_text().strip().upper().startswith("ALTAIR"):
                return {"port": d.name, "mbps": int((d / "speed").read_text().strip())}
    except OSError:
        pass
    return None


def outdoors(source=None):
    """The forecast's temperature and dew point for this hour at the site,
    {"temp_c", "dew_point_c"}; None without a site or a forecast."""
    import feeds
    try:
        site = config.load()["site"]
        w = (source or feeds).weather(site["lat"], site["lon"])
    except Exception:
        return None
    now = time.time()
    i = min(range(len(w["time"])), key=lambda k: abs(w["time"][k] - now))
    return {"temp_c": w["temperature_2m"][i], "dew_point_c": w["dew_point_2m"][i]}


def camera_temperature(cam):
    """The camera's own thermometer in °C, where its library reports one."""
    try:
        return round(cam.handle.get_Temperature() / 10, 1)
    except Exception:
        return None


def cooldown_step(cam, exposure, frames):
    """Capped frames at one moment: the row stripes in ADU (one frame's, the
    median of them) and against the pixels' noise (1 is none), how long each
    frame took against the exposure asked, and how many never arrived."""
    adu, scores, cycles, failed = [], [], [], 0
    for _ in range(frames):
        start = time.monotonic()
        try:
            mosaic, _ = cam.frame(exposure)
        except (Exception, SystemExit):
            failed += 1
            continue
        cycles.append(time.monotonic() - start)
        adu.append(float(np.std(row_stripes(mosaic))))
        scores.append(banding(mosaic))
    pick = lambda v, places: round(float(np.median(v)), places) if v else None
    return {"frames": frames, "failed": failed, "stripes_adu": pick(adu, 2), "stripes": pick(scores, 1),
            "frame_s": pick(cycles, 2)}


def cooldown(exposure, gain, frames=20, every_min=10.0, steps=12, note="", say=print, sleep=time.sleep):
    """The cap-on test of whether the stripes grow as the camera cools: the
    same frames every `every_min` minutes, each set with the outdoor
    temperature and dew point, the camera's own temperature where it has
    one, and the USB port and speed. Change one thing at a time between
    runs (cable, port, hub, heater) and say which in `note`. Kept, a line a
    step, in config.DATA/cache/cooldown-DATE.jsonl."""
    log = config.DATA / "cache" / f"cooldown-{time.strftime('%Y%m%d')}.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    say(f"{steps} sets of {frames} capped frames of {exposure:g} s at gain {gain}, every {every_min:g} min"
        + (f" ({note})" if note else ""))
    with Camera(gain=gain) as cam:
        for step in range(steps):
            if step:
                sleep(every_min * 60)
            row = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "note": note, "exposure_s": exposure, "gain": gain,
                   "camera_c": camera_temperature(cam), "usb": usb_link(), "outdoors": outdoors(),
                   **cooldown_step(cam, exposure, frames)}
            rows.append(row)
            with open(log, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
            air = row["outdoors"] or {}
            say(f"  {row['time'][11:16]}  stripes {row['stripes_adu']} ADU ({row['stripes']})  "
                f"frame {row['frame_s']} s  failed {row['failed']}/{frames}  "
                f"air {air.get('temp_c', '?')}°C dew {air.get('dew_point_c', '?')}°C  "
                f"camera {row['camera_c'] if row['camera_c'] is not None else '?'}°C  "
                f"usb {(row['usb'] or {}).get('port', '?')} {(row['usb'] or {}).get('mbps', '?')} Mb/s")
    return {"log": str(log), "steps": rows}


def run(args):
    if getattr(args, "stripes", None):      # saved frames only: nothing to dry-run
        return stripes_in(args.stripes)
    if getattr(args, "dry_run", False):
        note = ("Stops the mount following the sky for one frame of "
                f"{args.exposure or 10.0:g} s, so the stars trail, and starts it following again. Nothing is slewed."
                if args.trail else "Takes frames; the mount is not touched.")
        print(("Would stop the mount's tracking for one frame. " if args.trail else "Would not move the mount. ") + note)
        return {"would_move": False, "safe": True, "tracking_interrupted": bool(args.trail)}, [note]
    if args.capabilities:
        with Camera(gain=args.gain) as cam:
            found = cam.details() if SDK else capabilities(cam)
        (show_details if SDK else show_capabilities)(found)
        return found
    if args.timing:
        return timing(args.gain, frames=min(args.frames or 3, 3))
    if args.trail:
        return trail(args.exposure or 10.0, args.gain, args.corrected)
    if args.stripes:
        return stripes_in(args.stripes)
    if args.banding:
        return banding_trial(args.exposure or 16.0, args.gain, min(args.frames or 2, 2), args.keep_best)
    if args.cooldown:
        return cooldown(args.exposure or 16.0, args.gain, args.frames or 20, args.every, args.steps, args.note)
    if args.throughput:
        results = (throughput_sdk if SDK else throughput)(args.exposure or 1.0, args.frames or 4, args.gain)
        good = [r for r in results if "failed" not in r]
        if good:
            best = min(good, key=lambda r: r["cycle_s"])
            print(f"\nQuickest: {best['mode']} at {best['cycle_s']} s a frame. A smaller or binned "
                  "frame only helps if its colour pattern survives: check the pattern means differ.")
        return {"results": results}
    exposures = args.exposures or [args.exposure or 2.0]
    results, rows = [], []
    print(f"{'gain':>5} {'exp':>5} {'sky':>6} {'grain':>6} {'burnt':>7} {'stars':>6} {'signal':>7} {'FWHM':>5} "
          f"{'round':>5} {'stripes':>7} {'ADU':>5} {'/grain':>6}")
    for exposure in exposures:
        for speed in (args.speeds or [None]):
            for gain in args.gains:
                with Camera(gain=gain) as cam:
                    if speed is not None:
                        cam.settings(speed=speed)
                        cam.frame(1.0)                  # one frame to let the change take
                    mosaics = [cam.frame(exposure)[0] for _ in range(args.frames or 1)]
                q = sweep_point(mosaics)
                if exposure == exposures[0]:
                    results.append((gain, q))
                rows.append(dict(q, gain=gain, exposure_s=exposure, speed=speed))
                fwhm = "" if q["fwhm"] is None else f"{q['fwhm']:.1f}"
                print(f"{gain:>5} {exposure:>5g} {'' if speed is None else 'speed ' + str(speed)} {q['background']:>6.0f} {q['noise']:>6.1f} {q['burnt']:>7.3%} "
                      f"{q['stars']:>6} {q['signal']:>7.0f} {fwhm:>5} {q.get('roundness') or 0:>5.2f} "
                      f"{q['stripes']:>7.1f} {q['stripes_adu']:>5.2f} {q['stripes_per_grain']:>6.3f}", flush=True)
    best = recommend(results)
    print(f"\nSuggested gain: {best}" if best else "\nNo stars found at any gain.")
    calm = min(rows, key=lambda r: r["stripes"])
    print(f"Weakest stripes: gain {calm['gain']}, {calm['exposure_s']:g} s ({calm['stripes']:g}).")
    return {"suggested_gain": best, "results": rows, "weakest_stripes": {k: calm[k] for k in ("gain", "exposure_s",
                                                                                             "stripes")}}


if __name__ == "__main__":
    main()
