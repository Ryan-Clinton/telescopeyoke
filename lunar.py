"""The Moon in a picture and in the sky: where its disc is in a frame, how
bright it is, the part of the sensor that holds it, and tonight's Moon (its
phase, age, distance and size, from sky.py). moon.py uses these.

The disc is found from the Moon itself, not from stars: the bright region,
then a circle fitted to its edge. The terminator lies inside the true
circle, so the fit is repeated on the edge points on or outside the last
circle until only the sunlit limb is left. A crescent's centre is found as
well as a full Moon's.
"""
import math

import numpy as np
from scipy import ndimage

TARGET_LEVEL = 0.72           # the bright surface this far up the scale: room below clipping
CLIPPED_SHARE = 0.001         # at most this share of the disc at the top of the scale


def _fit_circle(y, x):
    """Least-squares circle through points: (cy, cx, r)."""
    a = np.column_stack([x, y, np.ones_like(x)])
    b = x ** 2 + y ** 2
    (c0, c1, c2), *_ = np.linalg.lstsq(a, b, rcond=None)
    cx, cy = c0 / 2, c1 / 2
    return cy, cx, math.sqrt(max(c2 + cx ** 2 + cy ** 2, 0.0))


def find_disc(image, shrink=4):
    """The Moon's disc in a picture (a 2-D brightness array): a dict with its
    centre (cy, cx) and radius r in the picture's pixels, the bounding box of
    the lit part (top, left, bottom, right), the brightness of its bright
    surface, and the level only CLIPPED_SHARE of it is above. None when no
    disc is found."""
    a = np.asarray(image, dtype=np.float32)
    small = a[:a.shape[0] // shrink * shrink, :a.shape[1] // shrink * shrink].reshape(
        a.shape[0] // shrink, shrink, a.shape[1] // shrink, shrink).mean(axis=(1, 3))
    top = np.percentile(small, 99.5)
    floor = np.median(small)
    if top <= floor * 1.5 + 1e-6:
        return None
    lit = small > floor + 0.35 * (top - floor)
    labels, count = ndimage.label(lit)
    if not count:
        return None
    sizes = ndimage.sum(lit, labels, range(1, count + 1))
    disc = labels == 1 + int(np.argmax(sizes))
    if disc.sum() < 50:
        return None
    disc = ndimage.binary_fill_holes(disc)
    edge = disc & ~ndimage.binary_erosion(disc)
    # Points on the frame's border are where the frame cuts the disc, not its limb.
    edge[0, :] = edge[-1, :] = edge[:, 0] = edge[:, -1] = False
    ys, xs = np.nonzero(edge)
    if len(ys) < 10:
        return None
    ys, xs = ys.astype(float), xs.astype(float)
    cy, cx, r = _fit_circle(ys, xs)
    for _ in range(6):
        outside = np.hypot(ys - cy, xs - cx) >= r - 1.5
        if outside.sum() < 10:
            break
        cy, cx, r = _fit_circle(ys[outside], xs[outside])
    rows, cols = np.nonzero(disc)
    inside = np.zeros(a.shape, bool)
    big = np.repeat(np.repeat(disc, shrink, 0), shrink, 1)
    inside[:big.shape[0], :big.shape[1]] = big
    surface = a[inside]
    return {"cy": (cy + 0.5) * shrink - 0.5, "cx": (cx + 0.5) * shrink - 0.5, "r": r * shrink,
            "box": (int(rows.min() * shrink), int(cols.min() * shrink),
                    int((rows.max() + 1) * shrink), int((cols.max() + 1) * shrink)),
            "level": float(np.percentile(surface, 99)) if surface.size else 0.0,
            "peak": float(np.percentile(surface, 100 * (1 - CLIPPED_SHARE))) if surface.size else 0.0}


def offset(disc, shape):
    """How far the disc's centre is from the frame's middle, in pixels
    (down, right)."""
    return disc["cy"] - (shape[0] - 1) / 2, disc["cx"] - (shape[1] - 1) / 2


def roi(disc, shape, margin=0.08, step=16):
    """The part of the sensor that holds the whole disc with `margin` (a
    share of its diameter) around it, as (x, y, width, height) rounded to
    `step` pixels so the colour pattern and the camera's own rounding agree."""
    r = disc["r"] * (1 + 2 * margin)
    size = int(math.ceil(2 * r / step) * step)
    w, h = min(size, shape[1] // step * step), min(size, shape[0] // step * step)
    x = int(round((disc["cx"] - w / 2) / step) * step)
    y = int(round((disc["cy"] - h / 2) / step) * step)
    return (max(0, min(x, shape[1] - w)), max(0, min(y, shape[0] - h)), w, h)


def exposure_for(disc, exposure, white, gain=100, longest=0.03, most_gain=400):
    """(exposure, gain) that put the bright surface at TARGET_LEVEL of the
    scale: the shortest exposure that does, since a short one freezes the
    air. Gain rises only once the exposure would pass `longest`."""
    level = max(disc["level"], 1.0)
    if disc["peak"] >= 0.98 * white:
        level = max(level, white) * 2          # clipped: the true level is unknown, so halve
    wanted = exposure * TARGET_LEVEL * white / level
    if wanted <= longest:
        return max(wanted, 0.0002), gain
    raised = min(most_gain, gain * wanted / longest)
    return wanted * gain / raised, int(round(raised))


def calibration(moves):
    """The 2x2 matrix that turns a move on the sky (arcminutes east, north)
    into a move of the picture (pixels down, right), from two or more
    measured moves: [((east, north), (down, right)), ...]."""
    sky = np.array([m[0] for m in moves], float)
    picture = np.array([m[1] for m in moves], float)
    solved, *_ = np.linalg.lstsq(sky, picture, rcond=None)
    return solved.T          # picture = M @ sky


def correction(matrix, down, right):
    """Arcminutes (east, north) to add to the aim to bring a disc that is
    (down, right) pixels off the middle back to it."""
    east, north = np.linalg.solve(np.asarray(matrix, float), -np.array([down, right], float))
    return float(east), float(north)


def state(site, when=None):
    """Tonight's Moon at the site (sky.moon_state: per cent lit, waxing or
    waning, age, distance, size and altitude)."""
    import sky
    return sky.moon_state(site, when)


# --- where on the Moon each pixel is ----------------------------------------------
#
# For the mineral Moon's check against the known seas and its confidence map
# (mineral.py): the Moon's orientation from the IAU working group's model
# (Archinal et al. 2011, Celestial Mechanics and Dynamical Astronomy 109,
# 101-135, table 2: the Moon's pole and prime meridian, mean Earth axes),
# good to a fraction of a degree, far finer than a sea.

SEAS = {      # selenographic latitude, longitude (east +), degrees: the IAU's named centres
    "Mare Tranquillitatis": (8.5, 31.4),
    "Mare Serenitatis": (28.0, 17.5),
    "Mare Imbrium": (32.8, -15.6),
    "Mare Crisium": (17.0, 59.1),
    "Mare Fecunditatis": (-7.8, 51.3),
    "Mare Nectaris": (-15.2, 35.5),
    "Mare Nubium": (-21.3, -16.6),
    "Oceanus Procellarum": (18.4, -57.4),
}
HIGHLANDS = {     # points in the bright uplands, well away from any sea
    "southern highlands (30S 10E)": (-30.0, 10.0),
    "southern highlands (45S 20E)": (-45.0, 20.0),
    "southern highlands (50S 15W)": (-50.0, -15.0),
    "southern highlands (30S 32E)": (-30.0, 32.0),
    "Descartes highlands, Apollo 16 (9S 15E)": (-9.0, 15.5),
    "south-western highlands near Wilhelm (43S 20W)": (-43.0, -20.0),
}


def orientation(when):
    """The Moon's pole (right ascension, declination) and prime meridian W,
    degrees, at `when` (a datetime or astropy Time)."""
    from astropy.time import Time
    t = Time(when)
    d = float(t.tdb.jd - 2451545.0)
    centuries = d / 36525
    e = [math.radians(x % 360) for x in (
        125.045 - 0.0529921 * d, 250.089 - 0.1059842 * d, 260.008 + 13.0120009 * d,
        176.625 + 13.3407154 * d, 357.529 + 0.9856003 * d, 311.589 + 26.4057084 * d,
        134.963 + 13.0649930 * d, 276.617 + 0.3287146 * d, 34.226 + 1.7484877 * d,
        15.134 - 0.1589763 * d, 119.743 + 0.0036096 * d, 239.961 + 0.1643573 * d,
        25.053 + 12.9590088 * d)]
    s, c = [math.sin(x) for x in e], [math.cos(x) for x in e]
    ra = (269.9949 + 0.0031 * centuries - 3.8787 * s[0] - 0.1204 * s[1] + 0.0700 * s[2] - 0.0172 * s[3]
          + 0.0072 * s[5] - 0.0052 * s[9] + 0.0043 * s[12])
    dec = (66.5392 + 0.0130 * centuries + 1.5419 * c[0] + 0.0239 * c[1] - 0.0278 * c[2] + 0.0068 * c[3]
           - 0.0029 * c[5] + 0.0009 * c[6] + 0.0008 * c[9] - 0.0009 * c[12])
    w = (38.3213 + 13.17635815 * d - 1.4e-12 * d * d + 3.5610 * s[0] + 0.1208 * s[1] - 0.0642 * s[2]
         + 0.0158 * s[3] + 0.0252 * s[4] - 0.0066 * s[5] - 0.0047 * s[6] - 0.0046 * s[7] + 0.0028 * s[8]
         + 0.0052 * s[9] + 0.0040 * s[10] + 0.0019 * s[11] - 0.0044 * s[12])
    return ra % 360, dec, w % 360


def _unit(ra, dec):
    ra, dec = math.radians(ra), math.radians(dec)
    return np.array([math.cos(dec) * math.cos(ra), math.cos(dec) * math.sin(ra), math.sin(dec)])


def body_axes(ra, dec, w):
    """The Moon's own x (towards longitude 0), y (90 E) and z (north pole)
    as unit vectors on the sky's axes."""
    z = _unit(ra, dec)
    node = np.array([-math.sin(math.radians(ra)), math.cos(math.radians(ra)), 0.0])
    across = np.cross(z, node)
    w = math.radians(w)
    x = math.cos(w) * node + math.sin(w) * across
    return x, np.cross(z, x), z


def view(site, when):
    """How the Moon faces the site at `when`: the sky's east, north and
    towards-us directions at the Moon, the Sun's direction from it, and its
    own axes (all unit vectors on the sky's axes); with the point under us
    and the point under the Sun (latitude, longitude)."""
    import astropy.units as u
    from astropy.coordinates import EarthLocation, get_body
    from astropy.time import Time
    t = Time(when)
    location = EarthLocation(lat=site["latitude"] * u.deg, lon=site["longitude"] * u.deg,
                             height=site.get("elevation_m", 0) * u.m)
    moon, sun = get_body("moon", t, location), get_body("sun", t, location)
    m = moon.cartesian.xyz.to(u.km).value
    s = sun.cartesian.xyz.to(u.km).value
    to_moon = m / np.linalg.norm(m)
    ra, dec = math.radians(moon.ra.deg), math.radians(moon.dec.deg)
    east = np.array([-math.sin(ra), math.cos(ra), 0.0])
    north = np.array([-math.sin(dec) * math.cos(ra), -math.sin(dec) * math.sin(ra), math.cos(dec)])
    sunward = (s - m) / np.linalg.norm(s - m)
    axes = body_axes(*orientation(t))
    out = {"east": east, "north": north, "toward": -to_moon, "sun": sunward, "axes": axes}
    out["under_us"] = selenographic(-to_moon, axes)
    out["under_sun"] = selenographic(sunward, axes)
    return out


def selenographic(p, axes):
    """(latitude, longitude east) of the Moon's surface along unit vector(s) `p`."""
    x, y, z = axes
    p = np.asarray(p, dtype=np.float64)
    lat = np.degrees(np.arcsin(np.clip(p @ z, -1, 1)))
    lon = np.degrees(np.arctan2(p @ y, p @ x))
    return lat, lon


def surface(disc, shape, look, turn, mirrored):
    """Each pixel's place on the Moon, for a picture whose up points `turn`
    degrees east of north on the sky (mirrored or not): a dict of the
    on-disc mask, latitude, longitude, and the cosines of the Sun's angle
    from overhead (incidence) and of ours (emission)."""
    yy, xx = np.indices(shape, dtype=np.float64)
    right = (xx - disc["cx"]) / disc["r"]
    up = (disc["cy"] - yy) / disc["r"]
    if mirrored:
        right = -right
    t = math.radians(turn)
    east_part = up * math.sin(t) - right * math.cos(t)
    north_part = up * math.cos(t) + right * math.sin(t)
    rho2 = east_part ** 2 + north_part ** 2
    inside = rho2 < 1
    depth = np.sqrt(np.clip(1 - rho2, 0, None))
    p = (east_part[..., None] * look["east"] + north_part[..., None] * look["north"]
         + depth[..., None] * look["toward"])
    lat, lon = selenographic(p, look["axes"])
    return {"inside": inside, "lat": lat, "lon": lon, "cos_i": p @ look["sun"], "cos_e": p @ look["toward"]}


def near(geometry, lat, lon, radius=4.0):
    """The pixels within `radius` degrees of arc of (lat, lon) on the Moon,
    on the side facing us."""
    la, lo = np.radians(geometry["lat"]), np.radians(geometry["lon"])
    a, b = math.radians(lat), math.radians(lon)
    cos_d = np.sin(la) * math.sin(a) + np.cos(la) * math.cos(a) * np.cos(lo - b)
    return geometry["inside"] & (cos_d > math.cos(math.radians(radius)))


def _seas_score(level, geometry):
    """How much brighter the uplands are than the seas once the light's
    angle is allowed for (Lommel-Seeliger): high when the map is the right
    way round."""
    lit = geometry["inside"] & (geometry["cos_i"] > 0.15)
    shade = np.where(lit, geometry["cos_i"] / np.maximum(geometry["cos_i"] + geometry["cos_e"], 1e-6), 0)
    albedo = np.where(lit, level / np.maximum(shade, 1e-6), 0)

    def mean_at(places):
        values = [albedo[near(geometry, la, lo, 5.0) & lit] for la, lo in places.values()]
        values = [v.mean() for v in values if v.size > 20]
        return float(np.mean(values)) if values else None
    seas, uplands = mean_at(SEAS), mean_at(HIGHLANDS)
    return uplands / seas if seas and uplands else 0.0


def fit_turn(image, disc, look, shrink=8):
    """(turn, mirrored, score, other): how the picture lies on the sky, found
    from the picture alone. The turn puts the predicted sunlit side on the
    lit part of the picture; which way round it is comes from the seas,
    which must be darker than the uplands. `other` is the best score the
    other way round: near `score`, which way round is not sure."""
    a = np.asarray(image, dtype=np.float32)
    h, w = a.shape[0] // shrink, a.shape[1] // shrink
    small = a[:h * shrink, :w * shrink].reshape(h, shrink, w, shrink).mean(axis=(1, 3))
    sd = {"cy": (disc["cy"] + 0.5) / shrink - 0.5, "cx": (disc["cx"] + 0.5) / shrink - 0.5, "r": disc["r"] / shrink}
    seen = small > 0.15 * np.percentile(small, 99.5)
    best, each = None, {}
    for mirrored in (False, True):
        scores = []
        for turn in range(0, 360, 2):
            g = surface(sd, small.shape, look, turn, mirrored)
            scores.append((float(((g["inside"] & (g["cos_i"] > 0)) == seen)[g["inside"] | seen].mean()), turn))
        _, coarse = max(scores)
        for turn in np.arange(coarse - 3, coarse + 3.01, 0.5):
            g = surface(sd, small.shape, look, turn, mirrored)
            lit = float(((g["inside"] & (g["cos_i"] > 0)) == seen)[g["inside"] | seen].mean())
            score = _seas_score(small, g)
            each[mirrored] = max(each.get(mirrored, 0.0), score)
            if best is None or (score, lit) > (best[2], best[3]):
                best = (float(turn % 360), mirrored, score, lit)
    return best[0], best[1], best[2], each[not best[1]]


def turn_from_solve(cd, flipped):
    """(turn, mirrored) of a picture from a plate solve's CD matrix (FITS
    pixels, rows counted down the picture as the camera sends them), for
    the same camera on the same night: `flipped` when the mount was on the
    other side of the meridian, which turns the camera 180 degrees on the
    sky. On 30 October 2026 M34's solve at 02:52 (west of the meridian)
    gave 32.9 degrees, so the Moon (east of it) 212.9; the Moon's picture
    alone gave 213."""
    (a, b), (c, d) = cd
    turn = math.degrees(math.atan2(-b, -d))         # up the picture is down the rows: (0, -1)
    t = math.radians(turn)
    mirrored = (a * -math.cos(t) + c * math.sin(t)) < 0
    return (turn + (180.0 if flipped else 0.0)) % 360, bool(mirrored)


def hour_angle(site, when, ra):
    """Hours west of the meridian (-12 to 12) of right ascension `ra`
    (degrees) at `when`: below 0 the mount sits west of the pier."""
    import astropy.units as u
    from astropy.time import Time
    lst = Time(when).sidereal_time("apparent", longitude=site["longitude"] * u.deg).deg
    return ((lst - ra + 180) % 360 - 180) / 15
