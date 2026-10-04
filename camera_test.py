#!/usr/bin/env python3
"""Find the camera settings that suit this setup, by trying them.

    ./camera_test.py --capabilities     what the camera and its driver offer
    ./camera_test.py --throughput       time every way of getting frames off the camera
    ./camera_test.py --gain-sweep       try a range of gains on tonight's sky
    ./camera_test.py --gain-sweep --gains 300 900 1500 2500 --exposure 2

--throughput takes a few frames in each mode the driver offers (readout
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
"""
import argparse
import time
from xml.sax.saxutils import quoteattr

import numpy as np

import interface
import stacking
from camera import WHITE, Camera, luminance

GAINS = (300, 600, 900, 1200, 1500, 1800)


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


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    what = ap.add_mutually_exclusive_group(required=True)
    what.add_argument("--capabilities", action="store_true")
    what.add_argument("--throughput", action="store_true")
    what.add_argument("--gain-sweep", action="store_true")
    ap.add_argument("--gains", type=int, nargs="+", default=list(GAINS))
    ap.add_argument("--exposure", type=float, help="seconds (default 2 for gains, 1 for throughput)")
    ap.add_argument("--frames", type=int, default=4, help="frames per mode, for --throughput")
    ap.add_argument("--gain", type=int, default=1500)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    return interface.main("camera_test", lambda: run(args), args.json)


def run(args):
    if args.capabilities:
        with Camera(gain=args.gain) as cam:
            found = capabilities(cam)
        show_capabilities(found)
        return found
    if args.throughput:
        results = throughput(args.exposure or 1.0, args.frames, args.gain)
        good = [r for r in results if "failed" not in r]
        if good:
            best = min(good, key=lambda r: r["cycle_s"])
            print(f"\nQuickest: {best['mode']} at {best['cycle_s']} s a frame. A smaller or binned "
                  "frame only helps if its colour pattern survives: check the pattern means differ.")
        return {"results": results}
    exposure = args.exposure or 2.0
    results = []
    print(f"{'gain':>5} {'sky':>6} {'grain':>6} {'burnt':>7} {'stars':>6} {'signal':>7} {'FWHM':>5}")
    for gain in args.gains:
        with Camera(gain=gain) as cam:
            mosaic, _ = cam.frame(exposure)
        q = measure(mosaic)
        results.append((gain, q))
        fwhm = "" if q["fwhm"] is None else f"{q['fwhm']:.1f}"
        print(f"{gain:>5} {q['background']:>6.0f} {q['noise']:>6.1f} {q['burnt']:>7.3%} "
              f"{q['stars']:>6} {q['signal']:>7.0f} {fwhm:>5}", flush=True)
    best = recommend(results)
    print(f"\nSuggested gain: {best}" if best else "\nNo stars found at any gain.")
    return {"suggested_gain": best, "results": [dict(q, gain=gain) for gain, q in results]}


if __name__ == "__main__":
    main()
