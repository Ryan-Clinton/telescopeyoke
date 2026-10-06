#!/usr/bin/env python3
"""Find Polaris by day and set the polar axis from it, before the stars are out.

    ./polaris.py find              look around the home position until Polaris is in view
    ./polaris.py find --radius 4   look further out (degrees from where the axis points)
    ./polaris.py align             with Polaris in view: say which way to move the mount
    ./polaris.py find --dry-run    say what it would do; nothing moves

Polaris is bright enough to photograph in daylight, and nothing else near the
pole is: a single bright point in a frame taken there is Polaris. The plate
solver cannot work by day (it needs a field of stars), so this goes by that
one star.

"find" starts from the home position, where the tube lies along the polar
axis, and looks in rings around it until a point of light shows and is still
there in a second frame. It needs the focus near where stars focus: a star
far out of focus is too faint against a bright sky.

"align" turns the RA axis a little each way with Polaris in view. The camera
turns with the axis, so the star swings round the one point in the picture
that the axis aims at. Where that point is from Polaris, set against where
the true pole is from Polaris at this moment, is the mount's error, given as
how far to move the azimuth (left-right) and altitude (up-down) adjusters.
Which way is up in the picture comes from the home position, so it is as good
as the home position was set: a rough answer, good to a few tenths of a
degree. ./polaralign.py after dark is the fine one.

Both move the mount. "find" turns the RA axis up to 88° either side of home on
every ring, so the counterweight bar swings level both ways, and tips
the tube a few degrees either side of the pole, over it. "align" tips the
tube a tenth of a degree and turns the RA axis by up to 50° in three steps,
then goes back to where it began. The Sun, the altitude limit and the motion
lock are checked before anything moves.
"""
import argparse
import json
import math
import time

import numpy as np
from scipy import ndimage

import config
import interface
import mount

FOUND = config.DATA / "cache" / "polaris.json"    # where it was last seen, for "align"
VIEW = config.DATA / "web" / "polaris.jpg"        # the frame it was found in, marked
# J2000 position in degrees. Its own motion since is about an arcsecond.
POLARIS = {"id": "Polaris", "ra": 37.95456, "dec": 89.26411}
REACH = 88.0        # the RA axis is kept within this of home: the bar never passes level
RADIUS = 3.0        # how far from the home position to look, in degrees
STANDS_OUT = 12.0   # how far a point must stand above the unevenness of the sky to count
SAME_PLACE = 0.02   # degrees: a second frame must show it this close to the first
DARK = 0.25         # seconds: a sky needing a longer exposure than this is a night sky
BLUE = 1.6          # blue over red in the raw frame: clear sky is near 1.9 on this camera, cloud nearer 1.3
PATIENCE = 120      # seconds to wait at one place for cloud to clear before giving up
NEAR_ENOUGH = 1.5   # degrees of RA axis: close enough for a look, this near the pole


def scale():
    """Degrees of sky per pixel of the half-size pictures used here."""
    cfg = config.hardware()
    return math.degrees(2 * cfg["camera"]["pixel_size_um"] / 1000 / cfg["scope"]["focal_length_mm"])


def outward(hour_angle):
    """Unit vector on the sky at the pole, pointing from the pole toward an
    hour angle in degrees: (toward the zenith, toward the west)."""
    return np.array([math.cos(math.radians(hour_angle)), math.sin(math.radians(hour_angle))])


def axes_for(distance, hour_angle):
    """The (RA axis, Dec axis) readings that aim `distance` degrees from where
    the polar axis points, toward `hour_angle` degrees in the mount's own
    reckoning. East of the meridian the Dec axis reads below 90°, west of it
    above, as on the mount."""
    hour_angle = mount.wrap(hour_angle)
    if hour_angle < 0:
        return hour_angle + 90, 90 - distance
    return hour_angle - 90, 90 + distance


def spots(radius, step):
    """Where to look, in order: home, then rings `step` degrees apart out to
    `radius`. Each ring is walked east side out and west side back, so the RA
    axis sweeps once each way and never the long way round."""
    found, forward = [(mount.HOME_RA_AXIS, mount.HOME_DEC_AXIS)], True
    rings = max(1, math.ceil(radius / step - 1e-9))
    for ring in range(1, rings + 1):
        distance = ring * step
        count = max(4, math.ceil(2 * math.pi * distance / step))
        # Hour angles of the ring's points, kept clear of the two directions
        # (due up and due down) the RA axis would have to pass level to reach;
        # the frames either side cover them.
        each = max(2, math.ceil(count / 2))
        half = [-(90 - REACH) - (2 * REACH) * i / (each - 1) for i in range(each)]
        east = sorted(axes_for(distance, h) for h in half)                  # RA axis rising
        west = sorted((axes_for(distance, -h) for h in half), reverse=True)  # and falling again
        found += (east + west) if forward else (west[::-1] + east[::-1])
        forward = not forward
    return found


def star(lum, flat=None):
    """The brightest small point in a half-size frame as (x, y, how far it
    stands out), or None.

    `flat` is a frame taken with the telescope aimed somewhere else. By day
    it shows the same shading and the same dust as this one and a different
    piece of blank sky, so dividing by it leaves only what is in the sky: a
    speck of dust stays where it is in every frame, and would pass for a
    star without this. The sky's slow shading is taken out as well, so a
    point is small against the 100-pixel shading it is measured over,
    whether sharp or a little out of focus."""
    lum = lum.astype(np.float32)
    if flat is not None:
        lum = lum / np.maximum(flat, 1.0) * float(np.median(flat))
    rows, cols = lum.shape[0] // 4 * 4, lum.shape[1] // 4 * 4
    small = lum[:rows, :cols].reshape(rows // 4, 4, cols // 4, 4).mean(axis=(1, 3))
    small = ndimage.median_filter(small, 3)                 # a hot pixel is not a star
    flatter = small - ndimage.uniform_filter(small, 100)
    smooth = ndimage.gaussian_filter(flatter, 3)
    noise = 1.4826 * float(np.median(np.abs(smooth - np.median(smooth))))
    y, x = np.unravel_index(np.argmax(smooth), smooth.shape)
    stands_out = float(smooth[y, x]) / max(noise, 1e-6)
    if stands_out < STANDS_OUT:
        return None
    y0, x0 = max(y - 30, 0), max(x - 30, 0)
    box = np.clip(smooth[y0:y0 + 60, x0:x0 + 60] - 0.3 * smooth[y, x], 0, None)
    by, bx = ndimage.center_of_mass(box)
    return 4 * (x0 + bx) + 2, 4 * (y0 + by) + 2, stands_out


def look(cam, exposure=0.002):
    """One frame, exposed for the sky as it is: (half-size brightness image,
    the exposure used, blue over red). The camera sees colour, and clear sky
    is much bluer than cloud. Refuses once the sky is dark: then every frame
    has stars in it and one bright point no longer means Polaris."""
    from landmark import exposed
    lum, exposure, mosaic = exposed(cam, start=exposure)
    if exposure > DARK:
        raise interface.Refusal("INVALID_REQUEST", "The sky is dark enough for the stars now, so a point of "
                                "light need not be Polaris. Use ./mount.py goto NAME --solve and "
                                "./polaralign.py, which go by the whole field.")
    blue = float(np.median(mosaic[1::2, 1::2][::4, ::4])) / max(float(np.median(mosaic[0::2, 0::2][::4, ::4])), 1.0)
    return lum, exposure, blue


def clear_look(cam, exposure, patience=PATIENCE, pause=time.sleep):
    """A frame of clear sky: (image, exposure), waiting up to `patience`
    seconds for cloud to move off, or None if it does not. Polaris does not
    show through cloud, and a place is only looked at once."""
    began, told = time.monotonic(), False
    while True:
        lum, exposure, blue = look(cam, exposure)
        if blue >= BLUE:
            return lum, exposure
        if time.monotonic() - began >= patience:
            return None
        if not told:
            print(f"  cloud here (blue over red {blue:.2f}); waiting for it to clear", flush=True)
            told = True
        pause(5)


def aim(scope, ra_axis, dec_axis):
    """Turn to a pair of axis readings by the readouts, as home is found."""
    scope.seek(mount.DEC, dec_axis)
    scope.seek(mount.RA, ra_axis)


def aim_roughly(scope, ra_axis, dec_axis):
    """The same, for the search: the Dec axis exactly, the RA axis only to
    within NEAR_ENOUGH. A few degrees from the pole a degree of RA axis is a
    few hundredths of a degree of sky, and creeping the last of the way at
    the slow rates took most of each look."""
    scope.seek(mount.DEC, dec_axis)
    stages, mount.STAGES = mount.STAGES, ((8, NEAR_ENOUGH),)
    try:
        scope.seek(mount.RA, ra_axis)
    finally:
        mount.STAGES = stages


def plan(site, radius=RADIUS):
    """What the search would do, checked before anything moves: the motion
    lock, the Sun, and how low the furthest ring would reach."""
    if mount.LOCK_FILE.exists():
        raise interface.Refusal("MOTION_LOCKED",
                                f"Motion is locked: {mount.LOCK_FILE.read_text(encoding='utf-8').strip()}")
    if not 0.3 <= radius <= 8:
        raise interface.Refusal("INVALID_REQUEST", "Give a radius between 0.3° and 8°.")
    if site["latitude"] - radius < mount.MIN_ALTITUDE:
        raise interface.Refusal("TARGET_BELOW_ALTITUDE_LIMIT",
                                f"The pole is only {site['latitude']:.0f}° up here; looking {radius:g}° around "
                                f"it would go below the {mount.MIN_ALTITUDE}° limit.")
    mount.direction(0, min(89.0, site["latitude"]), site)      # refuses within 40° of the Sun
    # Rings close enough that nowhere is further from a look than half the
    # picture's short side, whichever way up the camera is.
    step = 0.6 * config.field_height()
    looks = spots(radius, step)
    return {"would_move": True, "safe": True, "looks": len(looks), "radius_deg": radius,
            "ring_step_deg": round(step, 2),
            "warnings": [f"The RA axis turns up to {REACH:.0f}° either side of home on every ring: the "
                         "counterweight bar swings level both ways.",
                         f"The tube tips up to {radius:g}° either side of the pole, over it."]}


def picture(lum, x, y, note):
    from landmark import picture as marked
    VIEW.parent.mkdir(parents=True, exist_ok=True)
    marked(lum, cross=(x, y), note=note).save(VIEW.with_suffix(".part.jpg"), quality=88)
    VIEW.with_suffix(".part.jpg").replace(VIEW)


def confirmed(cam, first, flat, exposure):
    """The same point in a second frame, or None: (x, y, how far it stands
    out, that frame). A cloud's edge or a bird has moved on by then."""
    again = look(cam, exposure)[0]
    second = star(again, flat)
    if not second or math.hypot(second[0] - first[0], second[1] - first[1]) * scale() > SAME_PLACE:
        return None
    return (first[0] + second[0]) / 2, (first[1] + second[1]) / 2, min(first[2], second[2]), again


def centred(scope, cam, exposure, sighting, flat, aim=aim):
    """Bring a star to the middle of the picture: (x, y, the frame) once
    there, or None if it was lost on the way.

    Which way the picture is turned is not known yet. Tipping the tube a
    little shows which way "along the Dec axis" lies in it, and turning the
    RA axis a little shows whether the picture is mirrored. With those, where
    the star is in the picture says where it is from the axis, and the mount
    is turned to that. The Dec reading may not be quite true, so it is done
    up to three times."""
    per_pixel = scale()
    h, w = flat.shape
    middle = np.array([w / 2, h / 2])
    x, y = sighting
    frame = None
    for _ in range(3):
        if frame is not None and math.hypot(w / 2 - x, h / 2 - y) * per_pixel < 0.08:
            break
        ra_axis, dec_axis = scope.axes()
        here = [mount.wrap(ra_axis), dec_axis]
        lever = abs(90 - dec_axis) + 0.7
        probe = {}
        for axis, size in ((1, 0.1), (0, min(20.0, math.degrees(0.1 / lever)))):
            # Either way, and by less if it leaves the picture: a star found
            # at the very edge has little room, and may have it one way only.
            for part in (1, -1, 0.5, -0.5, 0.25, -0.25):
                target = list(here)
                target[axis] += part * size
                if abs(target[0]) > REACH + 0.5:      # the half degree is for a reading a hair past the reach
                    continue
                aim(scope, *target)
                now = star(look(cam, exposure)[0], flat)
                turned_by = mount.wrap(scope.axes()[axis] - here[axis])
                if now and abs(turned_by) > abs(part) * size / 2:
                    probe[axis] = (turned_by, np.array(now[:2]))
                    break
            aim(scope, *here)
            if axis not in probe:
                return None
        # The star's shift for a rise in the Dec reading is the direction, in
        # the picture, of the hour angle the tube is tipped toward.
        along = (probe[1][1] - (x, y)) / probe[1][0]
        along /= np.linalg.norm(along)

        def from_axis(across):
            """Where the star is from the polar axis, by where it is in the picture."""
            offset = (np.array([x, y]) - middle) * per_pixel
            return ((90 - here[1]) + offset @ along) * outward(here[0] - 90) + (offset @ across) * outward(here[0])

        def in_picture(place, ra_reading, across):
            """Where a star at `place` from the axis would show with the RA axis at a reading."""
            off = place - (90 - here[1]) * outward(ra_reading - 90)
            return middle + ((off @ outward(ra_reading - 90)) * along + (off @ outward(ra_reading)) * across) / per_pixel

        # A quarter turn from `along`, one way or the other: whichever says
        # rightly where the star went when the RA axis was turned.
        ways = [np.array([-along[1], along[0]]), np.array([along[1], -along[0]])]
        across = min(ways, key=lambda way: np.linalg.norm(
            in_picture(from_axis(way), here[0] + probe[0][0], way) - probe[0][1]))
        place = from_axis(across)
        ra_wanted, dec_wanted = axes_for(float(np.linalg.norm(place)), math.degrees(math.atan2(place[1], place[0])))
        aim(scope, float(np.clip(ra_wanted, -REACH, REACH)), dec_wanted)
        frame = look(cam, exposure)[0]
        now = star(frame, flat)
        if not now:
            return None
        x, y = now[:2]
    return x, y, frame


def find(scope, site, radius=RADIUS, cam_class=None, aim=aim_roughly, patience=PATIENCE, exact=aim):
    """Look around the home position until Polaris is in view, and stop there."""
    from camera import Camera
    planned = plan(site, radius)                # refuses here, before anything moves
    looks = spots(radius, planned["ring_step_deg"])
    print(f"Looking for Polaris in up to {len(looks)} places within {radius:g}° of the home position.",
          flush=True)
    scope.tracking(False)       # it hardly moves in a minute; tracking would turn the view instead
    scope.dec_creep(0)
    exposure, before, found, clouded = 0.002, None, None, False
    with (cam_class or Camera)() as cam, scope.watching():
        for i, spot in enumerate(looks):
            if i and abs(spot[1] - looks[i - 1][1]) > 1e-6 and abs(90 - spot[1]) != abs(90 - looks[i - 1][1]):
                print(f"  nothing yet after {i} looks; now {abs(90 - spot[1]):.1f}° out", flush=True)
            aim(scope, *spot)
            sky = clear_look(cam, exposure, patience)
            if sky is None:
                clouded = True
                break
            lum, exposure = sky
            if before is not None:
                # Each frame is the last one's flat, and the other way about:
                # so the very first frame is judged when the second arrives.
                here, there = star(lum, before[1]), star(before[1], lum) if i == 1 else None
                if here:
                    found, flat = confirmed(cam, here, before[1], exposure), before[1]
                elif there:
                    aim(scope, *before[0])
                    found, flat, i = confirmed(cam, there, lum, exposure), lum, i - 1
                if found:
                    break
            before = (spot, lum)
        if found:
            x, y, stands_out, lum = found
            print(f"  a point of light after {i + 1} looks; bringing it to the middle", flush=True)
            middle = centred(scope, cam, exposure, (x, y), flat, exact)
            if middle:
                x, y, lum = middle
            ra_axis, dec_axis = scope.axes()
            h, w = lum.shape
            off = math.hypot(x - w / 2, y - h / 2) * scale()
            note = {"ra_axis_deg": round(mount.wrap(ra_axis), 4), "dec_axis_deg": round(dec_axis, 4),
                    "x": round(x, 1), "y": round(y, 1), "stands_out": round(stands_out, 1),
                    "from_home_deg": round(abs(90 - dec_axis), 2), "off_centre_deg": round(off, 3),
                    "exposure_s": exposure, "looks": i + 1, "found": time.time()}
            FOUND.parent.mkdir(parents=True, exist_ok=True)
            FOUND.write_text(json.dumps(note, indent=1), encoding="utf-8")
            picture(lum, x, y, f"Polaris: {off:.2f} deg from the middle")
            print(f"Polaris is in view after {i + 1} look{'s' if i else ''}: {note['from_home_deg']:.1f}° "
                  f"from the home position, {off:.2f}° from the middle of the picture. "
                  "Next: ./polaris.py align", flush=True)
            return dict(note, found=True, picture=str(VIEW))
        aim(scope, mount.HOME_RA_AXIS, mount.HOME_DEC_AXIS)
    if clouded:
        print(f"Cloud over the pole that did not clear in {patience:.0f} s; back at home after {i} looks. "
              "Run it again when the sky there is blue.")
        return {"found": False, "looks": i, "radius_deg": radius, "cloud": True}
    print(f"Nothing that looks like Polaris within {radius:g}° of the home position; back at home. Either "
          "the focus is too far out for a star to show against the sky, the mount faces further from "
          "north than that (try --radius), or cloud is in the way.")
    return {"found": False, "looks": len(looks), "radius_deg": radius}


def turned(points, expected=None):
    """The point a star swung round, from where it was seen at several RA axis
    readings: [(RA axis in degrees, x, y), ...] gives (x, y of the centre,
    which way round the picture turns: +1 if the star's angle in the picture
    rises as the RA axis reading does, how badly the points fit in pixels).

    Turning by a known angle about an unknown centre is a straight sum for
    the centre, for either sense of turning. Over a long swing only the right
    sense fits. Over a short one both nearly do, with centres on opposite
    sides of the star's path: then the one nearer `expected`, where the
    axis ought to be in the picture by the mount's own readings, is kept."""
    fits = []
    for sense in (1, -1):
        rows, wanted = [], []
        for i, (a_i, *p_i) in enumerate(points):
            for a_j, *p_j in points[i + 1:]:
                t = math.radians(sense * (a_j - a_i))
                turn = np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])
                rows.append(np.eye(2) - turn)
                wanted.append(np.array(p_j) - turn @ np.array(p_i))
        centre = np.linalg.lstsq(np.vstack(rows), np.concatenate(wanted), rcond=None)[0]
        misfit = float(np.sqrt(np.mean((np.vstack(rows) @ centre - np.concatenate(wanted)) ** 2)))
        fits.append((float(centre[0]), float(centre[1]), sense, misfit))
    fits.sort(key=lambda fit: fit[3])
    clear = fits[1][3] > 5 * fits[0][3] + 1.0
    if expected is not None and not clear:
        fits.sort(key=lambda fit: math.hypot(fit[0] - expected[0], fit[1] - expected[1]))
    return fits[0]


def axis_error(star_xy, centre, sense, dec_shift, ra_axis, site, when=None):
    """How far the polar axis is from the pole, as (degrees east of north,
    degrees too high), from one look at Polaris.

    `centre` is the point in the picture the RA axis aims at and `sense` the
    way the picture turns (both from turned()); `dec_shift` is how the star
    moved in the picture, in pixels, for a rise in the Dec axis reading;
    `ra_axis` is the RA axis reading the star was seen at."""
    per_pixel = scale()
    # The tube is tipped from the axis toward hour angle (RA axis - 90°), by
    # 90° less the Dec reading. Raising the reading brings the view back
    # toward the axis, and the star goes the other way in the picture: so the
    # star's own shift is that hour angle's direction, as the picture has it.
    along = np.array(dec_shift, dtype=float)
    along /= np.linalg.norm(along)
    # A quarter turn on from it, the way hour angle rises. The picture turns
    # with the axis, so a star's angle in it falls as the axis reading rises:
    # hour angle runs the opposite way round the picture to `sense`.
    t = math.radians(-sense * 90)
    across = np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]]) @ along
    from_axis = np.array(star_xy, dtype=float) - np.array(centre, dtype=float)
    distance = float(np.linalg.norm(from_axis)) * per_pixel
    hour_angle = ra_axis - 90 + math.degrees(math.atan2(from_axis @ across, from_axis @ along))
    true_ha, true_dec, _ = mount.where(POLARIS, site, when)
    # Both are Polaris: from the true pole, and from where the axis points.
    axis = (90 - true_dec) * outward(true_ha) - distance * outward(hour_angle)
    return float(-axis[1] / math.cos(math.radians(site["latitude"]))), float(axis[0])


def align(scope, site, cam_class=None, aim=aim):
    """With Polaris in view: turn the RA axis a little each way, see what the
    star swings round, and return the polar axis's error. Ends where it began."""
    from camera import Camera
    if mount.LOCK_FILE.exists():
        raise interface.Refusal("MOTION_LOCKED",
                                f"Motion is locked: {mount.LOCK_FILE.read_text(encoding='utf-8').strip()}")
    mount.direction(0, min(89.0, site["latitude"]), site)      # refuses within 40° of the Sun
    scope.tracking(False)
    scope.dec_creep(0)
    ra_start, dec_start = scope.axes()
    ra_start = mount.wrap(ra_start)
    if abs(90 - dec_start) > 8 or abs(ra_start) > REACH + 1:
        raise interface.Refusal("INVALID_REQUEST", "The telescope is not near the pole. Run ./polaris.py find "
                                "first, and leave the mount where it stops.")
    per_pixel = scale()
    lost = interface.Refusal("INVALID_REQUEST", "Polaris is not in view, or left the picture when the mount "
                             "was turned a little. Run ./polaris.py find first.")
    with (cam_class or Camera)() as cam, scope.watching():
        try:
            # 1. Which way is "along the Dec axis" in the picture: tip the tube
            #    a little and see where the star goes. The two frames are each
            #    other's flat, so the star shows in both; if it left the
            #    picture one way, the other way is tried.
            start, exposure, _ = look(cam)
            nudge = min(0.12, 0.3 * start.shape[0] * per_pixel)
            shift = None
            for sign in (1, -1):
                aim(scope, ra_start, dec_start + sign * nudge)
                tipped, exposure, _ = look(cam, exposure)
                moved = scope.axes()[1] - dec_start
                was, now = star(start, tipped), star(tipped, start)
                if was and now and abs(moved) > 0.02 and math.hypot(now[0] - was[0], now[1] - was[1]) * per_pixel > 0.02:
                    shift = (np.array(now[:2]) - was[:2]) / moved          # pixels per degree of reading
                    break
            if shift is None:
                raise lost

            # 2. Turn the RA axis to three readings and sight the star at
            #    each. The further the tube is tipped from the axis, the
            #    faster the star crosses the picture, so the turn is sized to
            #    move it about a fifth of a degree. Every reading is come to
            #    from a degree below, so the slack in the gears is taken up
            #    the same way each time, and the Dec axis is not touched in
            #    between.
            lever = abs(90 - dec_start) + 0.7        # degrees: the tip, plus Polaris's own distance
            turn, points = min(25.0, math.degrees(0.2 / lever)), []
            # Where it began, a turn either side, then further and nearer:
            # a star found near the edge of the picture leaves it one way, so
            # whichever three readings still show it are the ones used.
            for step in (0, 1, -1, 2, -2, 0.5, -0.5, 0.25, -0.25):
                target = ra_start + step * turn
                if abs(target) > REACH + 0.5 or len(points) == 3:
                    continue
                aim(scope, target - 1.0, dec_start)
                aim(scope, target, dec_start)
                swung = star(look(cam, exposure)[0], tipped)
                if swung:
                    points.append((mount.wrap(scope.axes()[0]), swung[0], swung[1]))
            if len(points) < 3:
                raise lost
            points.sort()
        finally:
            aim(scope, ra_start, dec_start)
    # Where the axis ought to be in the picture if the readings were exact:
    # back along the Dec direction from the middle, by the tube's tip.
    h, w = start.shape
    expected = np.array([w / 2, h / 2]) - (90 - dec_start) * shift
    cx, cy, sense, misfit = turned(points, expected)
    if misfit * per_pixel > 0.02:
        raise interface.Refusal("INVALID_REQUEST", f"The three sightings do not lie on one circle (they miss by "
                                f"{misfit * per_pixel * 60:.1f}'): cloud, or not the same star each time. "
                                "Run it again.")
    ra_seen, x, y = points[1]
    azimuth, altitude = axis_error((x, y), (cx, cy), sense, shift, ra_seen, site)
    return azimuth, altitude, {"sightings": len(points), "turn_deg": round(turn, 2),
                               "misfit_arcmin": round(misfit * per_pixel * 60, 2),
                               "axis_from_polaris_deg": round(math.hypot(x - cx, y - cy) * per_pixel, 3)}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["find", "align"])
    ap.add_argument("--radius", type=float, default=RADIUS, metavar="DEG",
                    help=f"with find: how far from the home position to look (default {RADIUS:g}°)")
    ap.add_argument("--dry-run", action="store_true", help="say what it would do; no camera, no mount")
    ap.add_argument("--json", action="store_true", help="answer in JSON at the end")
    args = ap.parse_args()
    kind = f"polaris.{args.command}" + (".dry_run" if args.dry_run else "")
    return interface.main(kind, lambda: run(args), args.json)


def run(args):
    # The lock comes first: before the settings are read or the mount opened.
    if mount.LOCK_FILE.exists():
        raise interface.Refusal("MOTION_LOCKED",
                                f"Motion is locked: {mount.LOCK_FILE.read_text(encoding='utf-8').strip()}")
    site = config.load()["site"]
    if args.dry_run:
        if args.command == "align":
            note = ("Tips the tube about a tenth of a degree and back, then turns the RA axis to three "
                    "readings up to 25° apart, photographing Polaris at each. Ends where it began.")
            print(f"Would move the mount. {note}")
            return {"would_move": True, "safe": True}, [note]
        found = plan(site, args.radius)
        print(f"Would move the mount: up to {found['looks']} looks within {found['radius_deg']:g}° of the "
              "home position, stopping at the first that shows Polaris.")
        for warning in found["warnings"]:
            print(f"  {warning}")
        return found, found["warnings"]
    scope = mount.Mount()
    try:
        if args.command == "find":
            return find(scope, site, args.radius)
        import polaralign
        azimuth, altitude, how = align(scope, site)
        words = polaralign.describe(azimuth, altitude)
        print("\n" + words)
        print("This goes by the home position for which way is up, so take it as rough. Adjust the bolts "
              "and run it again (find first if the star has left the picture); ./polaralign.py after dark "
              "is the fine measurement.")
        total = math.hypot(azimuth * math.cos(math.radians(site["latitude"])), altitude)
        return dict(how, azimuth_deg=round(azimuth, 2), altitude_deg=round(altitude, 2),
                    total_deg=round(total, 2), east_of_north=azimuth > 0, too_high=altitude > 0,
                    advice=words, measured=time.time())
    except BaseException:
        scope.stop()     # never leave a motor running after an error or Ctrl+C
        scope.tracking(False)    # on the real handset, stopping a slew leaves it following the sky
        raise


if __name__ == "__main__":
    main()
