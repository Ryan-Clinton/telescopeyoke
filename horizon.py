#!/usr/bin/env python3
"""Map which parts of the sky the telescope can see from where it stands.

    ./horizon.py                 sweep the sky and report what is blocked
    ./horizon.py --step 20       a finer sweep (degrees of bearing between looks)
    ./horizon.py --dry-run       list where it would look, without moving

The mount looks in each direction in turn and the camera takes a short frame.
Stars in the frame mean open sky; none means a house, hedge or tree is in the
way. It needs a clear night: cloud looks the same as a wall. At the end it
prints the lines to put under [horizon] in config.toml, so the planner stops
suggesting targets behind the house.

This moves the mount all over the sky, over the pole and back, for about a
minute per look. Keep clear of it while it runs.
"""
import argparse
import json
import time
from pathlib import Path

import config
import interface

ROOT = Path(__file__).parent
RESULTS = ROOT / "cache" / "horizon.json"
ALTITUDES = (25, 40, 55, 70)
ENOUGH_STARS = 8


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


def sweep(site, step, exposure, gain):
    """Look in every direction the mount is allowed to reach."""
    import mount
    import skywatch
    import snap
    from camera import Camera, luminance

    plans = []
    for az, alt in looks(step):
        try:
            plans.append((az, alt, mount.plan_point(az, alt, site)))
        except interface.Refusal as refusal:
            if refusal.code == "MOTION_LOCKED":
                raise
            plans.append((az, alt, None))
    # One side of the mount at a time, so the tube crosses the pole once.
    plans.sort(key=lambda p: (p[2] is None, p[2] and p[2]["pier_side"], p[0], p[1]))
    scope = mount.Mount()
    if not mount.CLOCK_FILE.exists():
        scope.save_clock(site)
    offset = json.loads(mount.CLOCK_FILE.read_text(encoding="utf-8"))["offset_deg"]
    results = []
    try:
        with Camera(gain=gain) as cam:
            for az, alt, plan in plans:
                if plan is None:
                    results.append({"az": az, "alt": alt, "open": None})
                    continue
                # Aim as goto does: allow for the pointing error found by plate solving.
                hour_angle, dec = plan["hour_angle_hours"] * 15, plan["dec_deg"]
                error = mount.load_pointing_error(hour_angle > 0)
                scope.goto((mount.true_sidereal(site) + offset - (hour_angle - error[0])) % 360,
                           dec - error[1])
                scope.tracking(True)
                time.sleep(5)   # let the tube stop shaking
                mosaic, _ = cam.frame(exposure)
                stars = skywatch.count_stars(luminance(mosaic))
                snap.publish(mosaic, kind="horizon sweep", quick=True,
                             detail=f"bearing {az}°, {alt}° up · {stars} stars")
                results.append({"az": az, "alt": alt, "open": stars >= ENOUGH_STARS, "stars": stars})
                print(f"bearing {az:>3}°, {alt}° up: "
                      f"{f'{stars} stars' if stars >= ENOUGH_STARS else 'blocked'}", flush=True)
    except BaseException:
        scope.stop()
        raise
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--step", type=int, default=30, help="degrees of bearing between looks")
    ap.add_argument("--exposure", type=float, default=1.0)
    ap.add_argument("--gain", type=int, default=2000)
    ap.add_argument("--dry-run", action="store_true", help="list the looks; no camera, no mount")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    return interface.main("horizon.dry_run" if args.dry_run else "horizon", lambda: run(args), args.json)


def run(args):
    site = (config.load() if config.FILE.exists() else config.example())["site"]
    if args.dry_run:
        import mount
        reachable = 0
        for az, alt in looks(args.step):
            try:
                mount.plan_point(az, alt, site)
                reachable += 1
            except interface.Refusal as refusal:
                if refusal.code == "MOTION_LOCKED":
                    raise
        total = len(looks(args.step))
        print(f"Would look in {reachable} of {total} directions (the rest are outside the "
              f"mount's limits), about {reachable} minutes.")
        return {"would_move": True, "looks": total, "reachable": reachable, "minutes": reachable}
    results = sweep(site, args.step, args.exposure, args.gain)
    found = blocked(results)
    RESULTS.parent.mkdir(exist_ok=True)
    RESULTS.write_text(json.dumps({"saved": time.time(), "looks": results, "blocked": found}, indent=1), encoding="utf-8")
    print("\n" + chart(results))
    if found:
        print("\nPut this under [horizon] in config.toml:\nblocked = [")
        for b in found:
            print(f"  {{ from = {b['from']:g}, to = {b['to']:g}, altitude = {b['altitude']} }},")
        print("]")
    else:
        print("\nNothing in the way in any direction looked at.")
    return {"looks": results, "blocked": found}


if __name__ == "__main__":
    main()
