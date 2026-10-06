#!/usr/bin/env python3
"""Measure how far the mount's polar axis is from the pole, by plate solving.

    ./polaralign.py              measure, and say which way to move the mount
    ./polaralign.py --dry-run    say what it would do; nothing moves
    ./polaralign.py --step 10    smaller turns, to stay between a house and a tree
    ./polaralign.py --json       the answer as data

Start with the mount tracking a target well away from the pole, such as
after ./mount.py goto NAME --solve.

Photographs the sky at three positions that differ only by turning the RA
axis. The three aim points lie on a circle around wherever that axis really
points; the centre of the circle is the axis. Comparing it with the true pole
gives the correction, reported as how far to move the mount's azimuth
(left-right) and altitude (up-down) adjusters. Adjust, then run it again.

It slews the mount about 25° twice, staying on the side of the meridian it
is already on, and ends back where it started. Before anything moves, all
three positions are checked against the same limits as any other move, and
the motion lock is respected.
"""
import argparse
import json
import math
import time

import numpy as np

import config
import interface
import mount

STEP = 25.0  # degrees of RA-axis rotation between the three photographs
# The least a person may ask for. The solves are good to arcseconds, so a
# small turn still finds the axis; it is never more than STEP, which is as
# far as the positions have been tried on the real mount.
LEAST = 5.0
# Seconds to wait after each turn before photographing. A GoTo elsewhere
# waits mount.SETTLE for the stars to stop creeping, so that they land where
# they were sent; here it does not matter where on its circle a photograph
# lands, only that it is on it, and a one-second frame does not streak.
SETTLE = 5
CLEAR = 3.0   # degrees a photograph must be above anything known to be in the way


def vector(hour_angle, dec):
    """Unit vector in the Earth-fixed frame: z to the pole, x to the meridian."""
    h, d = math.radians(hour_angle), math.radians(dec)
    return np.array([math.cos(d) * math.cos(h), math.cos(d) * math.sin(h), math.sin(d)])


def axis_of(points):
    """The direction every one of three (hour angle, Dec) points is the same
    angle from, on the northern side: the axis they were turned about."""
    a, b, c = (vector(*p) for p in points)
    n = np.cross(b - a, c - a)
    n /= np.linalg.norm(n)
    return n if n[2] > 0 else -n


def to_altaz(v, latitude):
    """(altitude, azimuth east of north) in degrees of an Earth-fixed vector."""
    lat = math.radians(latitude)
    # Rotate from pole-and-meridian axes to up/north/east.
    up = v[2] * math.sin(lat) + v[0] * math.cos(lat)
    north = v[2] * math.cos(lat) - v[0] * math.sin(lat)
    east = -v[1]
    return math.degrees(math.asin(up)), math.degrees(math.atan2(east, north))


def positions(start_ha, dec, west, site, step=STEP, skyline=None):
    """The three (hour angle, Dec) positions to photograph, checked against
    the limits every aimed move must pass, and against what is known to be
    in the way (`skyline`, the settings' [horizon]). Raises a Refusal, before
    anything has moved, if any of them is out of bounds or behind something:
    on the first night out the third photograph was of a house, and then of
    a tree."""
    if dec > 75:
        raise interface.Refusal("INVALID_REQUEST",
                                "The telescope is pointing too near the pole for this: turning the RA "
                                "axis hardly moves the view. Go to a target lower down first, such as "
                                "./mount.py goto NAME --solve.")
    direction = 1 if west else -1
    spots = [(start_ha + direction * step * i, dec) for i in range(3)]
    for hour_angle, _ in spots:
        if abs(hour_angle) > mount.MAX_HOUR_ANGLE * 15:
            raise interface.Refusal("TARGET_BEYOND_HOUR_ANGLE_LIMIT",
                                    f"Turning {2 * step:.0f}° from here would reach {abs(hour_angle) / 15:.1f} h "
                                    f"from the meridian, beyond the {mount.MAX_HOUR_ANGLE} h limit. Start "
                                    "from a target nearer the meridian.")
        altitude = to_altaz(vector(hour_angle, dec), site["latitude"])[0]
        if altitude < mount.MIN_ALTITUDE:
            raise interface.Refusal("TARGET_BELOW_ALTITUDE_LIMIT",
                                    f"One of the three positions would be only {altitude:.0f}° up. Start "
                                    "from a higher target.")
        if skyline:
            import horizon
            azimuth = to_altaz(vector(hour_angle, dec), site["latitude"])[1] % 360
            top = horizon.in_the_way(skyline, azimuth)
            if altitude < top + CLEAR:
                turned = abs(hour_angle - start_ha)
                raise interface.Refusal("INVALID_REQUEST",
                                        f"After turning {turned:.0f}° the telescope would look at bearing "
                                        f"{azimuth:.0f}°, {altitude:.0f}° up, where the view is blocked up to "
                                        f"{top:.0f}°. Use a smaller --step, or start from a star on the other "
                                        "side of the meridian.")
    return spots


def measure(scope, site, step=STEP, skyline=None):
    """Photograph the sky at three RA-axis positions and return the polar
    axis's error as (degrees east of north, degrees too high). Slews about
    step degrees twice, away from the meridian, and returns to where it was."""
    offset = json.loads(mount.CLOCK_FILE.read_text(encoding="utf-8"))["offset_deg"]

    def believed_hour_angle():
        return mount.wrap(mount.true_sidereal(site) + offset - scope.radec()[0])

    start_ha = believed_hour_angle()
    dec_handset = mount.wrap(scope.radec()[1])
    # Step away from the meridian, on the side the tube is already on. All
    # three positions are checked before the first move.
    planned = positions(start_ha, dec_handset, scope.axes()[1] > 90, site, step, skyline)
    points = []
    try:
        for i, (target_ha, _) in enumerate(planned):
            if i:
                scope.goto((mount.true_sidereal(site) + offset - target_ha) % 360, dec_handset)
                scope.tracking(True)
                time.sleep(min(mount.SETTLE, SETTLE))
            # Tell the solver roughly where to look, then widen if needed:
            # where the handset believes it is, put right by the pointing
            # error last measured on this side. Without that the search
            # began 6° out on the real mount and one solve took a minute.
            error = mount.load_pointing_error(scope.axes()[1] > 90)
            hint_ra = mount.true_sidereal(site) - (target_ha + error[0])
            hint_dec = dec_handset + error[1]
            found = (scope.where_really(hint_ra, hint_dec, radius=40)
                     or scope.where_really(hint_ra, hint_dec, radius=90))
            if not found:
                if i:
                    # Not left pointing at whatever hid the stars.
                    scope.say("no stars here; going back to where it started")
                    scope.goto((mount.true_sidereal(site) + offset - start_ha) % 360, dec_handset)
                    scope.tracking(True)
                raise interface.Refusal("PLATE_SOLVE_FAILED",
                                        f"Could not plate-solve at position {i + 1}: cloud, or something in the "
                                        "way. Nothing was measured"
                                        + ("; the telescope is back where it started." if i else "."))
            ha, dec, alt = mount.where(found, site, found["when"])
            points.append((ha, dec))
            scope.say(f"position {i + 1}: hour angle {ha / 15:+.3f} h, Dec {dec:+.2f}°, "
                      f"altitude {alt:.0f}°")
        # Back to where it started.
        scope.goto((mount.true_sidereal(site) + offset - start_ha) % 360, dec_handset)
        scope.tracking(True)
    except BaseException:
        scope.stop()
        raise
    altitude, azimuth = to_altaz(axis_of(points), site["latitude"])
    return azimuth, altitude - site["latitude"]


def describe(azimuth, altitude):
    """The polar error in words, with what to do to the mount about it."""
    total = math.hypot(azimuth * math.cos(math.radians(55)), altitude)
    return (f"The polar axis is about {total:.1f}° from the pole.\n"
            f"  left-right: it points {abs(azimuth):.1f}° too far "
            f"{'east' if azimuth > 0 else 'west'} of north; swing the mount's north end "
            f"{abs(azimuth):.1f}° to the {'west' if azimuth > 0 else 'east'}\n"
            f"  up-down:    it points {abs(altitude):.1f}° too {'high' if altitude > 0 else 'low'}; "
            f"{'lower' if altitude > 0 else 'raise'} the axis by {abs(altitude):.1f}°")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="say what it would do; no camera, no mount")
    ap.add_argument("--json", action="store_true", help="answer in JSON at the end")
    ap.add_argument("--step", type=float, default=STEP, metavar="DEG",
                    help=f"degrees to turn between photographs, {LEAST:.0f} to {STEP:.0f} (default {STEP:.0f}): "
                         "less when a house or a tree is in the way of the third")
    args = ap.parse_args()
    return interface.main("polaralign.dry_run" if args.dry_run else "polaralign", lambda: run(args), args.json)


def run(args):
    if mount.LOCK_FILE.exists():
        raise interface.Refusal("MOTION_LOCKED",
                                f"Motion is locked: {mount.LOCK_FILE.read_text(encoding='utf-8').strip()}")
    step = getattr(args, "step", STEP)
    if not LEAST <= step <= STEP:
        raise interface.Refusal("INVALID_REQUEST", f"--step is from {LEAST:.0f} to {STEP:.0f} degrees.")
    if args.dry_run:
        note = (f"Photographs the sky where the telescope is, slews {step:.0f}° away from the meridian and "
                f"photographs again, then another {step:.0f}°, and returns to where it started. The three "
                "positions are checked against the altitude and meridian limits before the first move.")
        print(f"Would move the mount. {note}")
        return {"would_move": True, "safe": True, "step_deg": step}, [note]
    settings = config.load()
    site = settings["site"]
    scope = mount.Mount()
    if not mount.CLOCK_FILE.exists():
        scope.save_clock(site)      # reading the handset's clock moves nothing
    azimuth, altitude = measure(scope, site, step, settings.get("horizon"))
    # Keep it: the drift it causes can now be predicted anywhere in the sky.
    scope.drift_model(site).set_polar(azimuth, altitude)
    words = describe(azimuth, altitude)
    print("\n" + words)
    print("Adjust and run this again, or leave it and run './mount.py drift' to "
          "cancel the drift it causes.")
    total = math.hypot(azimuth * math.cos(math.radians(site["latitude"])), altitude)
    return {"azimuth_deg": round(azimuth, 2), "altitude_deg": round(altitude, 2), "total_deg": round(total, 2),
            "east_of_north": azimuth > 0, "too_high": altitude > 0, "advice": words, "measured": time.time()}


if __name__ == "__main__":
    main()
