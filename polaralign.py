#!/usr/bin/env python3
"""Measure how far the mount's polar axis is from the pole, by plate solving.

    sudo -u $USER -g dialout ./polaralign.py

Photographs the sky at three positions that differ only by turning the RA
axis. The three aim points lie on a circle around wherever that axis really
points; the centre of the circle is the axis. Comparing it with the true pole
gives the correction, reported as how far to move the mount's azimuth
(left-right) and altitude (up-down) adjusters. Adjust, then run it again.

It slews the mount about 25° twice, staying on the side of the meridian it
is already on, and ends back where it started.
"""
import argparse
import json
import math
import time

import numpy as np

import config
import mount

STEP = 25.0  # degrees of RA-axis rotation between the three photographs


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


def measure(scope, site):
    """Photograph the sky at three RA-axis positions and return the polar
    axis's error as (degrees east of north, degrees too high). Slews about
    STEP degrees twice, away from the meridian, and returns to where it was."""
    offset = json.loads(mount.CLOCK_FILE.read_text(encoding="utf-8"))["offset_deg"]

    def believed_hour_angle():
        return mount.wrap(mount.true_sidereal(site) + offset - scope.radec()[0])

    start_ha = believed_hour_angle()
    dec_handset = mount.wrap(scope.radec()[1])
    # Step away from the meridian, on the side the tube is already on.
    direction = 1 if scope.axes()[1] > 90 else -1
    points = []
    try:
        for i in range(3):
            target_ha = start_ha + direction * STEP * i
            if i:
                scope.goto((mount.true_sidereal(site) + offset - target_ha) % 360, dec_handset)
                scope.tracking(True)
                time.sleep(mount.SETTLE)
            # Tell the solver roughly where to look, then widen if needed.
            hint_ra = mount.true_sidereal(site) - target_ha
            found = (scope.where_really(hint_ra, dec_handset, radius=40)
                     or scope.where_really(hint_ra, dec_handset, radius=90))
            if not found:
                raise SystemExit("Could not plate-solve; cloud, or too few stars here.")
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
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    site = config.load()["site"]
    scope = mount.Mount()
    azimuth, altitude = measure(scope, site)
    # Keep it: the drift it causes can now be predicted anywhere in the sky.
    scope.drift_model(site).set_polar(azimuth, altitude)
    print("\n" + describe(azimuth, altitude))
    print("Adjust and run this again, or leave it and run './mount.py drift' to "
          "cancel the drift it causes.")


if __name__ == "__main__":
    main()
