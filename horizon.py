#!/usr/bin/env python3
"""Map which parts of the sky the telescope can see from where it stands.

    ./horizon.py                 sweep the sky and report what is blocked
    ./horizon.py --step 20       a finer sweep (degrees of bearing between looks)
    ./horizon.py --trace         find the top of whatever is in the way and follow
                                 it right round, instead of looking on a fixed grid
    ./horizon.py --daylight      work by day: bright and even means sky
    ./horizon.py --dry-run       list where it would look, without moving

The mount looks in each direction in turn and the camera takes a short frame.
Stars in the frame mean open sky; none means a house, hedge or tree is in the
way. It needs a clear night: cloud looks the same as a wall. At the end it
prints the lines to put under [horizon] in config.toml, so the planner stops
suggesting targets behind the house.

By day there are no stars, so --daylight goes by brightness instead: sky is
bright and even across the frame, a wall or hedge is darker or shades across
it. Cloud does not matter then, since overcast is still sky. The Sun's side of
the sky is left out; fill it in at night.

--trace takes fewer looks and gives a finer answer. In each bearing it starts
from the height the last bearing's obstruction reached and closes in on the
top of this one to within a few degrees. It then checks itself: sky must be
seen high up before it starts, there must be sky well above each top it
found, a sudden change between neighbouring bearings gets a look in between,
and at the end it goes back to the first bearing to see the same thing again.

This moves the mount all over the sky, over the pole and back, for about a
minute per look. Keep clear of it while it runs.
"""
import argparse
import json
import math
import time
from contextlib import contextmanager
from pathlib import Path

import numpy as np

import config
import interface

ROOT = Path(__file__).parent
RESULTS = config.DATA / "cache" / "horizon.json"
ALTITUDES = (25, 40, 55, 70)
ENOUGH_STARS = 8
STEADY = 5      # seconds for the tube to stop shaking before a frame
# Tracing the top of what is in the way.
FINE = 3        # degrees: how closely a top is pinned down
TOP = 75        # the highest look
JUMP = 12       # neighbouring tops further apart than this get a look in between
CLEARANCE = 15  # there must be sky this far above a top, or the top is doubted
# Telling sky from wall by day, against a frame of sky taken high up.
SKY_LEVEL = 0.4     # sky is at least this bright next to the high sky
SKY_EVEN = 0.75     # and its darkest part is at least this share of its brightest


def looks(step, altitudes=ALTITUDES):
    """Every (bearing, height) to try, in degrees."""
    return [(az, alt) for az in range(0, 360, step) for alt in altitudes]


def blocked(results):
    """Turn looks into config.toml's blocked list. `results` is a list of
    {"az", "alt", "open"} with open True, False or None (could not look).
    In each bearing the sky counts as blocked up to halfway between the
    highest look that saw nothing and the next one above it that saw stars."""
    bearings = sorted({r["az"] for r in results})
    step = bearings[1] - bearings[0] if len(bearings) > 1 else 360
    heights = {}
    for az in bearings:
        column = sorted((r["alt"], r["open"]) for r in results if r["az"] == az and r["open"] is not None)
        shut = [alt for alt, clear in column if not clear]
        if not shut:
            continue
        above = [alt for alt, clear in column if clear and alt > max(shut)]
        heights[az] = round((max(shut) + min(above)) / 2) if above else 90
    out = []
    for az in bearings:
        if az not in heights:
            continue
        start, end = (az - step / 2) % 360, (az + step / 2) % 360
        if out and out[-1]["to"] == start and out[-1]["altitude"] == heights[az]:
            out[-1]["to"] = end   # the same obstacle carries on into this bearing
        else:
            out.append({"from": start, "to": end, "altitude": heights[az]})
    return out


def chart(results):
    """A small text map: bearings across, heights down."""
    bearings = sorted({r["az"] for r in results})
    mark = {True: " * ", False: " # ", None: " . "}
    lines = ["     " + "".join(f"{az:>3}" for az in bearings) + "   (* stars, # blocked, . not reachable)"]
    for alt in sorted({r["alt"] for r in results}, reverse=True):
        row = {r["az"]: r["open"] for r in results if r["alt"] == alt}
        lines.append(f"{alt:>3}° " + "".join(mark[row.get(az)] for az in bearings))
    return "\n".join(lines)


def blocks(mosaic):
    """Averages over 64-pixel squares: dust specks, noise and the colour
    pattern drop out."""
    small = mosaic[:mosaic.shape[0] // 64 * 64, :mosaic.shape[1] // 64 * 64].astype(np.float32)
    return small.reshape(small.shape[0] // 64, 64, small.shape[1] // 64, 64).mean(axis=(1, 3))


def is_sky(mosaic, reference):
    """Whether a daytime frame shows open sky. The telescope is focused on the
    stars, so anything nearby is a blur: a wall is a darker frame, and the top
    of one is a frame shading from dark to bright. Returns (sky?, brightness
    next to the high sky, darkest part over brightest)."""
    patches = blocks(mosaic)
    dark, bright = np.percentile(patches, (5, 95))
    level, even = float(np.median(patches)) / reference, float(dark / max(bright, 1.0))
    return level >= SKY_LEVEL and even >= SKY_EVEN, round(level, 2), round(even, 2)


def daylight_exposure(cam, exposure=0.002):
    """An exposure that puts the sky near a third of full brightness, and that
    brightness. Called with the telescope looking at sky high up."""
    from camera import WHITE
    for _ in range(8):
        mosaic, _ = cam.frame(exposure)
        level = float(np.median(blocks(mosaic))) / WHITE
        if 0.15 <= level <= 0.5:
            return exposure, level * WHITE
        if level > 0.5 and exposure <= 0.0001:
            break
        # Raw values are in proportion to the light, so one step usually does it.
        exposure = min(max(exposure * 0.33 / max(level, 0.02), 0.0001), 2.0)
    raise interface.Refusal("NO_SKY", "Could not find an exposure for the daytime sky: the last "
                            f"frame was at {level:.0%} of full brightness.")


@contextmanager
def eye(site, exposure, gain, daylight=False):
    """The mount and camera as one function: look(az, alt) aims there, takes a
    frame and returns True for open sky, False for something in the way, or
    None where the mount may not go. `look.log` lists every look made."""
    import mount
    import skywatch
    import snap
    from camera import Camera, luminance

    scope = mount.Mount()
    if not mount.CLOCK_FILE.exists():
        scope.save_clock(site)
    offset = json.loads(mount.CLOCK_FILE.read_text(encoding="utf-8"))["offset_deg"]
    state = {"exposure": exposure, "reference": None}
    log = []

    def look(az, alt):
        try:
            plan = mount.plan_point(az, alt, site)
        except interface.Refusal as refusal:
            if refusal.code_name == "MOTION_LOCKED":
                raise
            log.append({"az": az, "alt": alt, "open": None})
            return None
        # Aim as goto does: allow for the pointing error found by plate solving.
        hour_angle, dec = plan["hour_angle_hours"] * 15, plan["dec_deg"]
        error = mount.load_pointing_error(hour_angle > 0)
        scope.goto((mount.true_sidereal(site) + offset - (hour_angle - error[0])) % 360,
                   dec - error[1])
        # Stars need following; a rooftop needs the mount to hold still.
        scope.tracking(not daylight)
        time.sleep(STEADY)   # let the tube stop shaking
        if daylight and state["reference"] is None:
            # The first look is at sky high up: it sets the exposure and what
            # sky looks like today.
            state["exposure"], state["reference"] = daylight_exposure(look.cam, state["exposure"])
        mosaic, _ = look.cam.frame(state["exposure"])
        if daylight:
            clear, level, even = is_sky(mosaic, state["reference"])
            seen = {"level": level, "even": even}
            detail = f"brightness {level:.0%} of the high sky, evenness {even:.0%}"
        else:
            stars = skywatch.count_stars(luminance(mosaic))
            clear, seen, detail = stars >= ENOUGH_STARS, {"stars": stars}, f"{stars} stars"
        snap.publish(mosaic, kind="horizon sweep", quick=True,
                     detail=f"bearing {az:g}°, {alt:g}° up · {detail}")
        log.append(dict({"az": az, "alt": alt, "open": bool(clear)}, **seen))
        print(f"bearing {az:>5g}°, {alt:>4g}° up: {'sky' if clear else 'blocked'} ({detail})", flush=True)
        return bool(clear)

    look.log = log
    try:
        with Camera(gain=gain) as cam:
            look.cam = cam
            yield look
    except BaseException:
        scope.stop()
        raise


def side(az):
    """Bearings east of the meridian first, then west, each in order: the
    tube crosses the pole once."""
    return (az >= 180, az)


def sweep(look, step):
    """Look in every direction on the grid that the mount is allowed to reach."""
    for az, alt in sorted(looks(step), key=lambda p: (side(p[0]), p[1])):
        look(az, alt)
    return look.log


# --- following the top of what is in the way -------------------------------------

def top_of(look, az, guess, low, top=TOP, fine=FINE):
    """How high the view is blocked in one bearing. Starts at `guess` and
    closes in until sky and obstruction are within `fine` degrees of each
    other. Returns {"az", "state", "shut", "clear"}: `shut` is the highest
    look that was blocked, `clear` the lowest that saw sky. States: "open"
    (sky down to the lowest look), "edge" (a top was found), "blocked" (no sky
    up to the highest look), "unreachable"."""
    seen = {}

    def view(alt):
        alt = min(max(round(alt), low), top)
        if alt not in seen:
            seen[alt] = look(az, alt)
        return alt, seen[alt]

    start, first = view(guess)
    if first is None:
        # The mount's limits often rule out one height and allow another.
        start, first = next(((alt, sky) for alt, sky in (view(h) for h in (top, low)) if sky is not None),
                            (start, None))
    shut = clear = None
    stride = fine
    if first is None:
        return {"az": az, "state": "unreachable", "shut": None, "clear": None}
    limit = False   # the mount's limits stopped the search
    if first:
        clear = start
        while shut is None and clear > low:
            alt, sky = view(clear - stride)
            if sky is None:
                break
            if sky:
                clear, stride = alt, stride * 2
            else:
                shut = alt
        if shut is None:
            return {"az": az, "state": "open", "shut": None, "clear": clear}
    else:
        shut = start
        while clear is None and shut < top:
            alt, sky = view(shut + stride)
            if sky is None:
                limit = True
                break
            if sky:
                clear = alt
            else:
                shut, stride = alt, stride * 2
        if clear is None:
            # Blocked as far as the mount may look is not the same as blocked to the top.
            return {"az": az, "state": "unreachable" if limit else "blocked", "shut": shut, "clear": None}
    while clear - shut > fine:
        alt, sky = view((clear + shut) / 2)
        if sky is None:
            break
        if sky:
            clear = alt
        else:
            shut = alt
    return {"az": az, "state": "edge", "shut": shut, "clear": clear}


def height(found, low):
    """One number for a bearing's obstruction, to compare neighbours by."""
    return {"open": low, "edge": found["clear"], "blocked": 90}.get(found["state"])


def trace(look, bearings, low, top=TOP, fine=FINE):
    """Follow the top of what is in the way round the given bearings.
    Returns (one top_of() answer per bearing, in bearing order; warnings)."""
    found, warnings = {}, []

    def measure(az):
        # Start where the nearest bearing already measured ended up.
        known = [f for f in found.values() if f["state"] in ("open", "edge")]
        near = min(known, key=lambda f: min((f["az"] - az) % 360, (az - f["az"]) % 360), default=None)
        found[az] = top_of(look, az, near["clear"] if near else low, low, top, fine)

    # Check 1: sky must be seen high up, or nothing after it means anything.
    high = next((az for az in bearings if look(az, top)), None)
    if high is None:
        raise interface.Refusal("NO_SKY", f"No open sky seen even {top}° up. Is the cap off? At night "
                                "this needs a clear sky.")
    for az in bearings:
        measure(az)

    # Check 2: a sudden change between neighbours is a corner; look in between.
    ring = sorted(found)
    extra = []
    for a, b in zip(ring, ring[1:] + ring[:1]):
        ha, hb, gap = height(found[a], low), height(found[b], low), (b - a) % 360
        if ha is not None and hb is not None and abs(ha - hb) > JUMP and gap >= 4:
            extra.append((a + gap / 2) % 360)
    for az in sorted(extra, key=side):
        measure(az)

    # Check 3: sky well above each top. A bright wall can pass for sky, and
    # branches or wires can hang over a roof.
    for az in sorted(found, key=side):
        f = found[az]
        if f["state"] == "edge" and f["clear"] + CLEARANCE <= top \
                and look(az, f["clear"] + CLEARANCE) is False:
            f["doubt"] = True
            warnings.append(f"Bearing {az:g}°: sky at {f['clear']}° but none {CLEARANCE}° higher. "
                            "Look at that direction yourself.")

    # Check 4: back to the start. If the first bearing no longer looks the
    # same, the mount slipped or the light changed while going round.
    first = next((found[az] for az in bearings if found[az]["state"] in ("open", "edge")), None)
    if first:
        again = [look(first["az"], first["clear"]) is True]
        if first["state"] == "edge":
            again.append(look(first["az"], first["shut"]) is False)
        if not all(again):
            warnings.append(f"Going back to bearing {first['az']:g}° gave a different answer from "
                            "the first time. Did the mount slip, or the light change? Do not "
                            "trust this survey.")
    return [found[az] for az in sorted(found)], warnings


def skyline_blocked(found):
    """Turn a trace into config.toml's blocked list. Each bearing speaks for
    the ground halfway to its neighbours, and is blocked up to the lowest
    height at which sky was seen."""
    out = []
    for before, this, after in zip(found[-1:] + found[:-1], found, found[1:] + found[:1]):
        top = {"edge": this["clear"], "blocked": 90}.get(this["state"])
        if top is None:
            continue
        start = (this["az"] - ((this["az"] - before["az"]) % 360 or 360) / 2) % 360
        end = (this["az"] + ((after["az"] - this["az"]) % 360 or 360) / 2) % 360
        if out and out[-1]["to"] == start and out[-1]["altitude"] == top:
            out[-1]["to"] = end
        else:
            out.append({"from": start, "to": end, "altitude": top})
    return out


def profile(found, low):
    """The skyline as a row of bars, one bearing per line."""
    lines = []
    for f in found:
        h = height(f, low)
        words = {"open": f"open down to {f['clear']}°", "edge": f"blocked up to {f['clear']}°",
                 "blocked": "blocked as far up as it looked", "unreachable": "not reachable"}[f["state"]]
        bar = "#" * math.ceil((h - low) / 3) if h is not None else ""
        lines.append(f"{f['az']:>6g}° {bar:<24} {words}{'  (in doubt)' if f.get('doubt') else ''}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--step", type=int, help="degrees of bearing between looks "
                    "(default 30, or 15 with --trace)")
    ap.add_argument("--trace", action="store_true", help="follow the top of what is in the way")
    ap.add_argument("--daylight", action="store_true", help="tell sky from wall by brightness, not stars")
    ap.add_argument("--exposure", type=float, help="seconds (default 1; by day it is found from the sky)")
    ap.add_argument("--gain", type=int, help="default 2000, or 100 by day")
    ap.add_argument("--dry-run", action="store_true", help="list the looks; no camera, no mount")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    return interface.main("horizon.dry_run" if args.dry_run else "horizon", lambda: run(args), args.json)


def run(args):
    cfg = config.load() if config.FILE.exists() else config.example()
    site, low = cfg["site"], cfg["horizon"]["min_altitude"]
    step = args.step or (15 if args.trace else 30)
    bearings = sorted(range(0, 360, step), key=side)
    if args.dry_run:
        import mount
        wanted = [(az, alt) for az in bearings for alt in (low, TOP)] if args.trace else looks(step)
        reachable, within = 0, set()
        for az, alt in wanted:
            try:
                mount.plan_point(az, alt, site)
                reachable += 1
                within.add(az)
            except interface.Refusal as refusal:
                if refusal.code_name == "MOTION_LOCKED":
                    raise
        total = len(wanted)
        if args.trace:
            # One look where the view is open, two or three where a top is followed.
            minutes = round(len(bearings) * 2.5)
            print(f"Would follow the skyline round {len(bearings)} bearings, from {low}° up to {TOP}°. "
                  f"{reachable} of the {total} lowest and highest looks are within the mount's "
                  f"limits just now. Roughly {minutes} minutes, more if much is in the way.")
            out = sorted(set(bearings) - within)
            if out:
                print("Out of reach altogether just now (the Sun, or too far from the meridian): "
                      + ", ".join(f"{az}°" for az in out))
        else:
            minutes = reachable
            print(f"Would look in {reachable} of {total} directions (the rest are outside the "
                  f"mount's limits), about {reachable} minutes.")
        return {"would_move": True, "looks": total, "reachable": reachable, "minutes": minutes}
    exposure = args.exposure or (0.002 if args.daylight else 1.0)
    gain = args.gain or (100 if args.daylight else 2000)
    warnings = []
    with eye(site, exposure, gain, args.daylight) as look:
        if args.trace:
            skyline, warnings = trace(look, bearings, low)
        else:
            if args.daylight:
                # Sky high up first, so the exposure is set on sky and not on a wall.
                if not any(look(az, TOP) for az in bearings):
                    raise interface.Refusal("NO_SKY", f"No open sky seen {TOP}° up. Is the cap off?")
            sweep(look, step)
        results = look.log
    found = skyline_blocked(skyline) if args.trace else blocked(results)
    saved = {"saved": time.time(), "looks": results, "blocked": found, "warnings": warnings}
    if args.trace:
        saved["skyline"] = skyline
    RESULTS.parent.mkdir(exist_ok=True)
    RESULTS.write_text(json.dumps(saved, indent=1), encoding="utf-8")
    print("\n" + (profile(skyline, low) if args.trace else chart(results)))
    for warning in warnings:
        print(f"\nCHECK: {warning}")
    if found:
        print("\nPut this under [horizon] in config.toml:\nblocked = [")
        for b in found:
            print(f"  {{ from = {b['from']:g}, to = {b['to']:g}, altitude = {b['altitude']} }},")
        print("]")
    else:
        print("\nNothing in the way in any direction looked at.")
    return {k: v for k, v in saved.items() if k != "saved"}, warnings


if __name__ == "__main__":
    main()
