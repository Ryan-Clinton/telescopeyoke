#!/usr/bin/env python3
"""Polar alignment before dark, from Polaris alone.

    ./polaris.py check             is it worth trying now? Sky, Sun, focus. Moves nothing
    ./polaris.py find              look around the home position until Polaris is in view
    ./polaris.py find --radius 4   look further out (degrees from where the axis points)
    ./polaris.py find --record     keep every frame and measurement of the search
    ./polaris.py align             with Polaris in view: say which way to move the mount
    ./polaris.py align --watch 60  then keep looking while you turn the bolts
    ./polaris.py find --dry-run    say what it would do; nothing moves

Polaris is bright enough to photograph in daylight, and nothing else near the
pole is: a single bright point in a frame taken there is Polaris. The plate
solver cannot work by day (it needs a field of stars), so this goes by that
one star. The order of work is: get the focus near, see whether the sky is
good enough ("check"), look over the smallest patch that could hold the star
("find"), measure ("align"), turn the bolts with it watching, and measure
again.

"check" takes a few frames where the telescope is and says how bright, how
blue, how even and how steady the sky is, where the Sun is, when it will be
better, and whether the focus has been checked today. A star far out of focus
is too faint against a bright sky, so "find" will not start on an unchecked
focus unless told to with --anyway.

"find" starts from the home position, where the tube lies along the polar
axis. It looks over the nearest part first and then further out, each part in
one slow sweep of the RA axis with the tube stepping up and down at each
stop, since near the pole it is the RA axis that has furthest to turn. Each
look is a few short frames added up and divided by the middle of the last
few looks, which shows the same dust and shading and a different piece of
sky. A point that stands out is looked at again, and then the tube is tipped
a twentieth of a degree twice: a star moves by just that much, and nothing
on the sensor moves at all. If a landmark was checked in the last few hours
(./landmark.py check) the mount is known to face the right way, and only a
small patch is searched.

"align" turns the RA axis to five readings with Polaris in view. The camera
turns with the axis, so the star swings round the one point in the picture
that the axis aims at. Where that point is from Polaris, set against where
the true pole is from Polaris at the moment of the sighting, is the mount's
error, given as how far to move the azimuth (left-right) and altitude
(up-down) adjusters. Which way is up in the picture comes from the home
position, so it is as good as the home position was set: a rough answer,
good to a few tenths of a degree. ./polaralign.py after dark is the fine one.
With --watch it then stays on the star and says, look by look, how far there
is still to go, without turning the RA axis again. That lasts while the star
is in the picture: turning the bolts moves it as far as the mount moves, so
an error of more than a few tenths of a degree is taken out in stages, with
"find" and "align" again in between.

The air lifts Polaris and the pole by the same amount, near enough, so what
is measured is the axis against the pole as it appears, which is also what
plate solving near the pole gives.

"find" and "align" move the mount. "find" turns the RA axis from 88° one side
of home to 88° the other, once for each part: the counterweight bar swings
level both ways, and the tube tips a few degrees either side of the pole,
over it. "align" tips the tube a tenth of a degree and turns the RA axis by
up to 25° a step, then goes back to the middle sighting. The Sun, the
altitude limit and the motion lock are checked before anything moves.
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
RUNS = config.DATA / "polaris-runs"               # what --record keeps
SCENE_FOCUS = config.DATA / "cache" / "focus_scene.json"     # written by ./focus.py --scene
# J2000 position in degrees. Its own motion since is about an arcsecond.
POLARIS = {"id": "Polaris", "ra": 37.95456, "dec": 89.26411}
REACH = 88.0        # the RA axis is kept within this of home: the bar never passes level
RADIUS = 3.0        # how far from the home position to look, in degrees
NEAR = 1.2          # the part looked over first, in degrees from home
NARROW = 0.8        # how far to look when a landmark says the mount faces the right way
ALIGNED_FRESH = 14  # days a night-time polar alignment is taken to hold, if the tripod has stood since
FROM_POLE = 0.75    # degrees: Polaris's distance from the pole, rounded up
HOME_SLACK = 0.5    # degrees allowed for a home position set by eye
STANDS_OUT = 12.0   # how far a point must stand above the unevenness of the sky to count
SAME_PLACE = 0.02   # degrees: a second look must show it this close to the first
DITHER = 0.05       # degrees the tube is tipped, twice, to see a candidate move with the sky
DARK = 0.25         # seconds: a sky needing a longer exposure than this is a night sky
BLUE = 1.2          # blue over red in the raw frame. On this camera clear sky read 1.9 with the Sun 14° up
                    # and 1.6 with it 3° up; cloud lit by the setting Sun read 0.55
PATIENCE = 120      # seconds to wait at one place for cloud to clear before giving up
NEAR_ENOUGH = 1.5   # degrees of RA axis: close enough for a look, this near the pole
DEC_NEAR_ENOUGH = 0.07  # degrees of Dec axis: close enough for a look
FRAMES = 3          # short frames added up for each look
FLATS = 5           # looks whose middle makes the flat for the next
FOCUS_FRESH = 12    # hours a focus check counts for
LANDMARK_FRESH = 6  # hours a landmark check counts for


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


def aimed(ra_axis, dec_axis):
    """Where a pair of readings aims, from where the polar axis points: a
    flat map of the sky at the pole, in degrees."""
    return (90 - dec_axis) * outward(ra_axis - 90)


def part(inner, outer, step, rising):
    """The looks covering the sky between `inner` and `outer` degrees from the
    axis, ordered for the motors: the RA axis goes across once, stopping at
    columns close enough together at the outer edge, and at each stop the tube
    steps through the distances, up one column and down the next. Nearer in,
    the columns are closer than they need be, so some are passed over."""
    distances = [k * step for k in range(1, math.ceil(outer / step - 1e-9) + 1) if k * step > inner + 1e-9]
    if not distances:
        return []
    columns = max(2, math.ceil(2 * REACH / math.degrees(step / distances[-1])) + 1)
    looks, upward = [], True
    order = range(columns) if rising else range(columns - 1, -1, -1)
    for column in order:
        ra_axis = -REACH + 2 * REACH * column / (columns - 1)
        here = []
        for distance in distances:
            every = max(1, int(distances[-1] / distance))
            if column % every == 0 or column == columns - 1:
                # Tipped below 90° it aims one way from the axis, above 90° the opposite way.
                here += [(ra_axis, 90 - distance), (ra_axis, 90 + distance)]
        here.sort(key=lambda spot: spot[1], reverse=not upward)
        if here:
            looks += here
            upward = not upward
    return looks


def spots(radius, step, near=NEAR):
    """Where to look, in order: home, then the part within `near` degrees,
    then the rest out to `radius`. The RA axis crosses once for each part,
    out and back."""
    near = min(math.ceil(min(near, radius) / step - 1e-9) * step, radius)     # a whole number of steps
    return ([(mount.HOME_RA_AXIS, mount.HOME_DEC_AXIS)] + part(0.0, near, step, rising=True)
            + part(near, radius, step, rising=False))


def brightest(lum, flat=None):
    """The brightest small point in a half-size frame, measured whether or not
    it is worth anything: {"x", "y", "stands_out", "width_px", "roundness"}.

    `flat` is a frame of another piece of sky. By day it shows the same
    shading and the same dust as this one, so dividing by it leaves only what
    is in the sky: a speck of dust stays where it is in every frame, and would
    pass for a star without this. The sky's slow shading is taken out as
    well, so a point is small against the 100-pixel shading it is measured
    over, whether sharp or a little out of focus."""
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
    y0, x0 = max(y - 30, 0), max(x - 30, 0)
    box = np.clip(smooth[y0:y0 + 60, x0:x0 + 60] - 0.3 * smooth[y, x], 0, None)
    by, bx = ndimage.center_of_mass(box)
    # How wide and how round: the spread of its light along its long and short ways.
    yy, xx = np.indices(box.shape)
    weight = box / max(float(box.sum()), 1e-9)
    spread = np.array([[float((weight * (xx - bx) ** 2).sum()), float((weight * (xx - bx) * (yy - by)).sum())],
                       [float((weight * (xx - bx) * (yy - by)).sum()), float((weight * (yy - by) ** 2).sum())]])
    short, long = np.sqrt(np.clip(np.linalg.eigvalsh(spread), 1e-9, None))
    return {"x": float(4 * (x0 + bx) + 2), "y": float(4 * (y0 + by) + 2),
            "stands_out": float(smooth[y, x]) / max(noise, 1e-6),
            "width_px": float(4 * 2.355 * math.sqrt(short * long)), "roundness": float(short / long)}


def star(lum, flat=None):
    """The brightest small point as (x, y, how far it stands out), or None if
    nothing stands out enough to be a star."""
    seen = brightest(lum, flat)
    return (seen["x"], seen["y"], seen["stands_out"]) if seen["stands_out"] >= STANDS_OUT else None


def look(cam, exposure=0.002, frames=None):
    """One look: `frames` short frames added up, exposed for the sky as it is:
    (half-size brightness image, the exposure used, blue over red). Adding
    frames steadies the grain of the light, so a faint point stands out
    further. The camera sees colour, and clear sky is much bluer than cloud.
    Refuses once the sky is dark: then every frame has stars in it and one
    bright point no longer means Polaris."""
    from camera import luminance
    from landmark import exposed
    lum, exposure, mosaic = exposed(cam, start=exposure)
    if exposure > DARK:
        raise interface.Refusal("INVALID_REQUEST", "The sky is dark enough for the stars now, so a point of "
                                "light need not be Polaris. Use ./mount.py goto NAME --solve and "
                                "./polaralign.py, which go by the whole field.")
    blue = float(np.median(mosaic[1::2, 1::2][::4, ::4])) / max(float(np.median(mosaic[0::2, 0::2][::4, ::4])), 1.0)
    frames = max(1, FRAMES if frames is None else frames)
    lum = lum.astype(np.float32)
    for _ in range(frames - 1):
        lum += luminance(cam.frame(exposure)[0])
    return lum / frames, exposure, blue


def clear_look(cam, exposure, patience=PATIENCE, pause=time.sleep):
    """A look at clear sky: (image, exposure, blue over red), waiting up to
    `patience` seconds for cloud to move off, or None if it does not. Polaris
    does not show through cloud, and a place is only looked at once."""
    began, told = time.monotonic(), False
    while True:
        lum, exposure, blue = look(cam, exposure)
        if blue >= BLUE:
            return lum, exposure, blue
        if time.monotonic() - began >= patience:
            return None
        if not told:
            print(f"  cloud here (blue over red {blue:.2f}); waiting for it to clear", flush=True)
            told = True
        pause(5)


def middle_of(frames):
    """The flat made from several looks at different pieces of sky: the
    middle value at each pixel, each look first brought to the same
    brightness. A star is in a different place in each, or in only one, and
    drops out; dust and shading are in the same place in all and stay."""
    if len(frames) == 1:
        return frames[0]
    level = [float(np.median(frame[::8, ::8])) for frame in frames]
    return np.median([frame * (level[0] / max(lv, 1e-6)) for frame, lv in zip(frames, level)], axis=0)


def aim(scope, ra_axis, dec_axis):
    """Turn to a pair of axis readings by the readouts, as home is found."""
    scope.seek(mount.DEC, dec_axis)
    scope.seek(mount.RA, ra_axis)


def aim_roughly(scope, ra_axis, dec_axis):
    """The same, for the search: each axis only near enough for a look. A few
    degrees from the pole a degree of RA axis is a few hundredths of a degree
    of sky, and creeping the last of the way at the slow rates took most of
    each look. Where it really stopped is read back afterwards."""
    stages = mount.STAGES
    try:
        mount.STAGES = ((8, 1.0), (6, DEC_NEAR_ENOUGH))
        scope.seek(mount.DEC, dec_axis)
        mount.STAGES = ((8, NEAR_ENOUGH),)
        scope.seek(mount.RA, ra_axis)
    finally:
        mount.STAGES = stages


# --- is it worth trying ---------------------------------------------------------

def sun_now(site, when=None):
    """(the Sun's height, its distance from the pole) in degrees."""
    import sky  # noqa: F401  (configures astropy to stay offline)
    from astropy import units as u
    from astropy.coordinates import AltAz, SkyCoord, get_sun
    from astropy.time import Time
    when = when or Time.now()
    frame = AltAz(obstime=when, location=mount.location(site))
    sun = get_sun(when).transform_to(frame)
    pole = SkyCoord(az=0 * u.deg, alt=site["latitude"] * u.deg, frame=frame)
    return float(sun.alt.deg), float(sun.separation(pole).deg)


def rating(sun_height):
    """How likely the star is to show, by the Sun's height alone. These steps
    are a first guess, to be set from real attempts as they are recorded."""
    if sun_height > 25:
        return "poor"
    if sun_height > 12:
        return "fair"
    if sun_height > 3:
        return "good"
    return "very good"


def focus_checked():
    """The newest focus check as {"how", "hours_ago"}, or None if there is
    none recent enough to count."""
    import focus
    found = []
    for how, path in (("on stars", focus.FOCUS_FILE), ("on a daytime view", SCENE_FOCUS)):
        if path.exists():
            try:
                saved = json.loads(path.read_text(encoding="utf-8")).get("saved")
            except ValueError:
                continue
            if saved:
                found.append({"how": how, "hours_ago": round((time.time() - saved) / 3600, 1)})
    found = [f for f in found if f["hours_ago"] <= FOCUS_FRESH]
    return min(found, key=lambda f: f["hours_ago"]) if found else None


def aligned_says():
    """How far to look when ./polaralign.py measured the axis in the last
    fortnight: {"radius", "total_deg", "days_ago"}, or None. The star is then
    its own distance from the pole, plus twice what the axis was out, plus
    something for a home position set by eye, from where the tube lies."""
    import polaralign
    try:
        last = json.loads(polaralign.POLAR_FILE.read_text(encoding="utf-8"))
        days = (time.time() - last["measured"]) / 86400
        radius = round(FROM_POLE + 2 * last["total_deg"] + HOME_SLACK, 1)
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if days > ALIGNED_FRESH or radius >= RADIUS:
        return None
    return {"radius": radius, "total_deg": last["total_deg"], "days_ago": round(days, 1)}


def landmark_says():
    """The landmark check that says the mount faces the right way, if one was
    made in the last few hours and found the landmark where it belongs."""
    import landmark
    path = landmark.FOLDER / "last check.json"
    if not path.exists():
        return None
    try:
        last = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    fresh = time.time() - last.get("checked", 0) <= LANDMARK_FRESH * 3600
    if fresh and last.get("matched") and abs(last.get("right_deg") or 9) <= 0.3:
        return last
    return None


def check(site, cam_class=None, frames=10):
    """Whether it is worth looking for Polaris now, from a few frames where
    the telescope is and from where the Sun is. Moves nothing."""
    from astropy import units as u
    from astropy.time import Time
    from camera import WHITE, Camera, luminance
    from landmark import exposed
    with (cam_class or Camera)() as cam:
        lum, exposure, mosaic = exposed(cam)
        blue = float(np.median(mosaic[1::2, 1::2][::4, ::4])) / max(float(np.median(mosaic[0::2, 0::2][::4, ::4])), 1.0)
        burnt = float((mosaic[::4, ::4] >= 0.98 * WHITE).mean())
        taken = [lum.astype(np.float32)] + [luminance(cam.frame(exposure)[0]) for _ in range(frames - 1)]
    stack = np.mean(taken, axis=0)
    h, w = stack.shape
    centre = float(np.median(stack[h // 2 - 100:h // 2 + 100, w // 2 - 100:w // 2 + 100]))
    corners = float(np.median([np.median(stack[:200, :200]), np.median(stack[:200, -200:]),
                               np.median(stack[-200:, :200]), np.median(stack[-200:, -200:])]))
    # The grain of the light, from two frames a moment apart; and how much
    # the sky itself changed between the first and the last, in patches:
    # blue sky does not, cloud drifting through does.
    grain = float(np.std((taken[1] - taken[0])[::4, ::4])) / math.sqrt(2)
    def patches(frame):
        cut = frame[:h // 8 * 8, :w // 8 * 8].reshape(8, h // 8, 8, w // 8).mean(axis=(1, 3))
        return cut / cut.mean()
    drift = float(np.abs(patches(taken[-1]) - patches(taken[0])).max())
    point = brightest(stack)
    sun_height, sun_from_pole = sun_now(site)
    sky_dark = exposure > DARK
    clear = blue >= BLUE and drift < 0.03
    focus = focus_checked()
    later = []
    for minutes in (30, 60, 90):
        height = sun_now(site, Time.now() + minutes * u.min)[0]
        if height > -4:
            later.append({"in_minutes": minutes, "sun_height_deg": round(height, 1), "rating": rating(height)})
    if sky_dark:
        verdict = "dark"
    elif not clear:
        verdict = "poor"
    else:
        verdict = rating(sun_height)
    found = {"exposure_ms": round(exposure * 1000, 2), "background": round(centre / (4 * WHITE), 2),
             "grain_adu": round(grain, 1), "blue_over_red": round(blue, 2), "clear": bool(clear),
             "corner_shading": round(1 - corners / max(centre, 1e-6), 3), "sky_drift": round(drift, 3),
             "burnt_out": round(burnt, 4), "brightest_point_stands_out": round(point["stands_out"], 1),
             "sun_height_deg": round(sun_height, 1), "sun_from_pole_deg": round(sun_from_pole, 1),
             "focus": focus, "landmark": landmark_says(), "rating": verdict, "later": later,
             "frames": frames, "checked": time.time()}
    print(f"Sky where the telescope is: {found['background']:.0%} of full at {found['exposure_ms']:g} ms, "
          f"blue over red {blue:.2f} ({'clear' if blue >= BLUE else 'grey: cloud or haze'}), "
          f"{'steady' if drift < 0.03 else 'changing: cloud passing'}.")
    print(f"Sun {sun_height:.0f}° up, {sun_from_pole:.0f}° from the pole.")
    if sky_dark:
        print("It is dark enough for the stars: use the plate solver instead (./polaralign.py).")
    else:
        print(f"Polaris by day: {verdict.upper()}."
              + ("".join(f" In {l['in_minutes']} min: {l['rating']}." for l in later
                         if l["rating"] != verdict)))
    print("Focus: " + (f"checked {focus['how']} {focus['hours_ago']:g} h ago." if focus else
                       "NOT CHECKED today. A star out of focus will not show against a bright sky: run "
                       "./focus.py --scene on the most distant thing in view, or ./focus.py on a star."))
    return found


# --- the search -----------------------------------------------------------------

def plan(site, radius=RADIUS):
    """What the search would do, checked before anything moves: the motion
    lock, the Sun, and how low the furthest look would reach."""
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
    # Looks close enough that nowhere is further from one than half the
    # picture's short side, whichever way up the camera is, with a little
    # to spare for where the tube really stops.
    step = 0.55 * config.field_height()
    looks = spots(radius, step)
    reach = min(math.ceil(min(NEAR, radius) / step - 1e-9) * step, radius)       # as spots() rounds it
    near = sum(1 for spot in looks if abs(90 - spot[1]) <= reach + 1e-9)
    return {"would_move": True, "safe": True, "looks": len(looks), "looks_near": near, "radius_deg": radius,
            "step_deg": round(step, 3),
            "warnings": [f"The RA axis turns from {REACH:.0f}° one side of home to {REACH:.0f}° the other, once "
                         "for the near part and once back for the rest: the counterweight bar swings level "
                         "both ways.",
                         f"The tube tips up to {radius:g}° either side of the pole, over it."]}


def picture(lum, x, y, note, target=None):
    """The view as a picture with a cross on the star, and a ring where the
    star belongs if that is known."""
    from landmark import picture as marked
    from PIL import ImageDraw
    VIEW.parent.mkdir(parents=True, exist_ok=True)
    image = marked(lum, cross=(x, y), note=note)
    if target is not None:
        ImageDraw.Draw(image).ellipse([target[0] - 40, target[1] - 40, target[0] + 40, target[1] + 40],
                                      outline=(90, 220, 120), width=3)
    image.save(VIEW.with_suffix(".part.jpg"), quality=88)
    VIEW.with_suffix(".part.jpg").replace(VIEW)


class Record:
    """What --record keeps of a search: every look as a small picture and as
    numbers, and every point of light that was considered, kept or not. A
    search that finds nothing is then something to learn from."""

    def __init__(self, folder=None):
        self.folder, self.looks, self.candidates = folder, [], []
        if folder:
            folder.mkdir(parents=True, exist_ok=True)

    def look(self, i, spot, axes, exposure, blue, seen, lum, flat):
        note = {"look": i + 1, "asked": [round(v, 3) for v in spot], "axes": [round(v, 4) for v in axes],
                "exposure_s": exposure, "blue_over_red": round(blue, 3), "time": time.time(),
                "brightest": None if seen is None else {k: round(v, 2) for k, v in seen.items()}}
        self.looks.append(note)
        if not self.folder:
            return
        from PIL import Image
        shown = lum if flat is None else lum / np.maximum(flat, 1.0) * float(np.median(flat))
        rows, cols = shown.shape[0] // 4 * 4, shown.shape[1] // 4 * 4
        small = shown[:rows, :cols].reshape(rows // 4, 4, cols // 4, 4).mean(axis=(1, 3))
        np.save(self.folder / f"look-{i + 1:03d}.npy", small.astype(np.float32))
        lo, hi = np.percentile(small, (0.5, 99.9))
        Image.fromarray((255 * np.clip((small - lo) / max(hi - lo, 1e-6), 0, 1)).astype(np.uint8)).save(
            self.folder / f"look-{i + 1:03d}.jpg", quality=85)
        self.write()

    def candidate(self, note):
        self.candidates.append(note)
        self.write()

    def write(self, **more):
        if not self.folder:
            return
        (self.folder / "search.json").write_text(json.dumps(dict(more, looks=self.looks), indent=1), encoding="utf-8")
        (self.folder / "candidates.json").write_text(json.dumps(self.candidates, indent=1), encoding="utf-8")


def verified(scope, cam, first, flat, exposure, aim=aim):
    """Whether a point of light is a star, as a note of what was seen:
    {"confidence": "high" | "medium" | "none", ...} with x, y and the frame
    when it is one.

    It must be in the same place in a second look: a bird or a cloud's edge
    has moved on. Then the tube is tipped a twentieth of a degree, twice, and
    a star moves across the picture as far as the readout says the tube
    turned (or somewhat less, where slack in the gears took up part of it).
    A hot pixel or a speck of dust does not move at all. The tube is put
    back afterwards."""
    per_pixel = scale()
    note = {"x": round(first["x"], 1), "y": round(first["y"], 1), "stands_out": round(first["stands_out"], 1),
            "width_px": round(first["width_px"], 1), "roundness": round(first["roundness"], 2),
            "repeated": False, "dither_match": None, "confidence": "none"}
    again = look(cam, exposure)[0]
    second = star(again, flat)
    if not second or math.hypot(second[0] - first["x"], second[1] - first["y"]) * per_pixel > SAME_PLACE:
        return note
    note["repeated"] = True
    ra_axis, dec_axis = scope.axes()
    ra_axis = mount.wrap(ra_axis)
    try:
        for sign in (1, -1):
            last = None
            for step in (1, 2):
                aim(scope, ra_axis, dec_axis + sign * step * DITHER)
                last = star(look(cam, exposure)[0], flat)
                if not last:
                    break
            if last:
                turned_by = abs(scope.axes()[1] - dec_axis)
                moved = math.hypot(last[0] - first["x"], last[1] - first["y"]) * per_pixel
                if turned_by > DITHER / 2:
                    note["dither_match"] = round(moved / turned_by, 2)
                    note["dither_moved_deg"] = round(moved, 4)
                break
    finally:
        aim(scope, ra_axis, dec_axis)
    # A star moves as far as the tube did, or a little less where slack in
    # the gears took up part of the turn. Something on the sensor does not
    # move; something in the air does not move to order.
    match = note["dither_match"]
    if match is None or note["dither_moved_deg"] < 0.01 or match > 1.3:
        return note
    back = look(cam, exposure)[0]
    seen = star(back, flat)
    if not seen:
        return note
    note["confidence"] = "high" if abs(match - 1) <= 0.15 and seen[2] >= 1.5 * STANDS_OUT else "medium"
    return dict(note, x=seen[0], y=seen[1], stands_out=round(seen[2], 1), frame=back)


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
            for share in (1, -1, 0.5, -0.5, 0.25, -0.25):
                target = list(here)
                target[axis] += share * size
                if abs(target[0]) > REACH + 0.5:      # the half degree is for a reading a hair past the reach
                    continue
                aim(scope, *target)
                now = star(look(cam, exposure)[0], flat)
                turned_by = mount.wrap(scope.axes()[axis] - here[axis])
                if now and abs(turned_by) > abs(share) * size / 2:
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


def find(scope, site, radius=RADIUS, cam_class=None, aim=aim_roughly, patience=PATIENCE, exact=aim, record=None):
    """Look around the home position until Polaris is in view, and stop there."""
    from camera import Camera
    planned = plan(site, radius)                # refuses here, before anything moves
    looks = spots(radius, planned["step_deg"])
    kept = Record(record)
    print(f"Looking for Polaris in up to {len(looks)} places within {radius:g}° of the home position, "
          f"the nearest {planned['looks_near']} first.", flush=True)
    scope.tracking(False)       # it hardly moves in a minute; tracking would turn the view instead
    scope.dec_creep(0)
    exposure, recent, found, clouded, flat = 0.002, [], None, False, None
    with (cam_class or Camera)() as cam, scope.watching():
        for i, spot in enumerate(looks):
            if i and i % 20 == 0:
                print(f"  nothing yet after {i} looks; now {abs(90 - spot[1]):.1f}° out", flush=True)
            aim(scope, *spot)
            sky = clear_look(cam, exposure, patience)
            if sky is None:
                clouded = True
                break
            lum, exposure, blue = sky
            # The flat is the middle of the last few looks. The very first
            # look has none, so it is judged when the second arrives, each
            # against the other.
            waiting = []
            if recent:
                flat = middle_of([frame for _, frame in recent])
                waiting.append((spot, lum, flat, brightest(lum, flat)))
                if i == 1:
                    waiting.append((recent[0][0], recent[0][1], lum, brightest(recent[0][1], lum)))
            kept.look(i, spot, scope.axes(), exposure, blue, waiting[0][3] if waiting else None, lum, flat)
            for where, frame, against, seen in waiting:
                number = i + 1 if where is spot else 1
                if where is not spot:       # the first look, judged now that there is a flat for it
                    kept.looks[0]["brightest"] = {k: round(v, 2) for k, v in seen.items()}
                if seen["stands_out"] < STANDS_OUT:
                    continue
                if where is not spot:
                    aim(scope, *where)
                note = verified(scope, cam, seen, against, exposure, exact)
                kept.candidate({k: v for k, v in dict(note, look=number, axes=list(scope.axes())).items()
                                if k != "frame"})
                print(f"  a point of light at look {number}: stands out {seen['stands_out']:.0f}, "
                      + ("moves with the sky" if note["confidence"] != "none" else
                         "not there twice" if not note["repeated"] else "does not move with the sky: not a star"),
                      flush=True)
                if note["confidence"] != "none":
                    found, flat = note, against
                    break
                if where is not spot:
                    aim(scope, *spot)
            if found:
                break
            recent = (recent + [(spot, lum)])[-FLATS:]
        if found:
            x, y, lum = found["x"], found["y"], found["frame"]
            print("  bringing it to the middle", flush=True)
            middle = centred(scope, cam, exposure, (x, y), flat, exact)
            if middle:
                x, y, lum = middle
            ra_axis, dec_axis = scope.axes()
            h, w = lum.shape
            off = math.hypot(x - w / 2, y - h / 2) * scale()
            note = {"ra_axis_deg": round(mount.wrap(ra_axis), 4), "dec_axis_deg": round(dec_axis, 4),
                    "x": round(x, 1), "y": round(y, 1), "stands_out": found["stands_out"],
                    "confidence": found["confidence"], "dither_match": found["dither_match"],
                    "width_px": found["width_px"], "roundness": found["roundness"],
                    "from_home_deg": round(abs(90 - dec_axis), 2), "off_centre_deg": round(off, 3),
                    "exposure_s": exposure, "looks": i + 1, "found": time.time()}
            FOUND.parent.mkdir(parents=True, exist_ok=True)
            FOUND.write_text(json.dumps(note, indent=1), encoding="utf-8")
            kept.write(result=note)
            picture(lum, x, y, f"Polaris: {off:.2f} deg from the middle")
            print(f"Polaris is in view after {i + 1} look{'s' if i else ''} ({found['confidence']} confidence: "
                  f"it moved {found['dither_match']:.2f} of what the tube did): {note['from_home_deg']:.1f}° "
                  f"from the home position, {off:.2f}° from the middle of the picture. "
                  "Next: ./polaris.py align", flush=True)
            return dict(note, found=True, picture=str(VIEW))
        aim(scope, mount.HOME_RA_AXIS, mount.HOME_DEC_AXIS)
    if clouded:
        kept.write(result={"found": False, "cloud": True})
        print(f"Cloud over the pole that did not clear in {patience:.0f} s; back at home after {i} looks. "
              "Run it again when the sky there is blue.")
        return {"found": False, "looks": i, "radius_deg": radius, "cloud": True}
    best = max((l["brightest"]["stands_out"] for l in kept.looks if l["brightest"]), default=0.0)
    kept.write(result={"found": False, "best_stands_out": best})
    print(f"Nothing that looks like Polaris within {radius:g}° of the home position; back at home. The "
          f"brightest point in any look stood out {best:.1f} (a star needs {STANDS_OUT:g}). Either the focus "
          "is too far out for a star to show against the sky, the mount faces further from north than that "
          "(try --radius), or haze is in the way." + ("" if record else " Run it with --record to keep the frames."))
    return {"found": False, "looks": len(looks), "radius_deg": radius, "best_stands_out": round(best, 1)}


# --- the measurement ------------------------------------------------------------

def swing(centre, sense, points, used=None):
    """Where each sighting ought to be if all lay on one circle about
    `centre`, turned by their RA readings: the misses, in pixels, in order.
    The circle is set by the sightings in `used` (all of them if not given)."""
    cx, cy = centre
    used = points if used is None else used
    radius = float(np.mean([math.hypot(x - cx, y - cy) for _, x, y in used]))
    angles = [math.atan2(y - cy, x - cx) - math.radians(sense * a) for a, x, y in used]
    zero = math.atan2(np.mean(np.sin(angles)), np.mean(np.cos(angles)))
    return [math.hypot(cx + radius * math.cos(zero + math.radians(sense * a)) - x,
                       cy + radius * math.sin(zero + math.radians(sense * a)) - y) for a, x, y in points]


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


def fitted(points, expected=None):
    """turned(), with one bad sighting left out if there is one: (x, y, sense,
    misfit, the sightings used, each sighting's miss in pixels or None if it
    was left out). A cable snagging or a gust moves one sighting and not the
    others; with four or more there are enough to see which, by fitting
    without each in turn."""
    cx, cy, sense, misfit = turned(points, expected)
    used = list(points)
    if len(points) >= 4:
        without = [(turned(points[:i] + points[i + 1:], expected), i) for i in range(len(points))]
        (bx, by, bsense, bmisfit), worst = min(without, key=lambda trial: trial[0][3])
        if misfit > 1.5 and bmisfit < misfit / 3:
            cx, cy, sense, misfit = bx, by, bsense, bmisfit
            used = points[:worst] + points[worst + 1:]
    misses = swing((cx, cy), sense, points, used)
    return cx, cy, sense, misfit, used, [miss if point in used else None for miss, point in zip(misses, points)]


def picture_axes(sense, dec_shift):
    """The two directions in the picture that go with the mount's own: `along`
    is the way the hour angle the tube is tipped toward lies, and `across` a
    quarter turn on from it, the way hour angle rises."""
    # The tube is tipped from the axis toward hour angle (RA axis - 90°), by
    # 90° less the Dec reading. Raising the reading brings the view back
    # toward the axis, and the star goes the other way in the picture: so the
    # star's own shift is that hour angle's direction, as the picture has it.
    along = np.array(dec_shift, dtype=float)
    along /= np.linalg.norm(along)
    # The picture turns with the axis, so a star's angle in it falls as the
    # axis reading rises: hour angle runs the opposite way round the picture
    # to `sense`.
    t = math.radians(-sense * 90)
    across = np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]]) @ along
    return along, across


def axis_error(star_xy, centre, sense, dec_shift, ra_axis, site, when=None):
    """How far the polar axis is from the pole, as (degrees east of north,
    degrees too high), from one look at Polaris.

    `centre` is the point in the picture the RA axis aims at and `sense` the
    way the picture turns (both from turned()); `dec_shift` is how the star
    moved in the picture, in pixels, for a rise in the Dec axis reading;
    `ra_axis` is the RA axis reading the star was seen at, and `when` the
    moment it was seen (now, if not given)."""
    along, across = picture_axes(sense, dec_shift)
    from_axis = np.array(star_xy, dtype=float) - np.array(centre, dtype=float)
    distance = float(np.linalg.norm(from_axis)) * scale()
    hour_angle = ra_axis - 90 + math.degrees(math.atan2(from_axis @ across, from_axis @ along))
    true_ha, true_dec, _ = mount.where(POLARIS, site, when)
    # Both are Polaris: from the true pole, and from where the axis points.
    axis = (90 - true_dec) * outward(true_ha) - distance * outward(hour_angle)
    return float(-axis[1] / math.cos(math.radians(site["latitude"]))), float(axis[0])


def belongs(centre, sense, dec_shift, ra_axis, site, when=None):
    """Where in the picture Polaris will be once the axis is on the pole, with
    the RA axis at this reading: the point the bolts are turned to bring it
    to. The axis keeps its place in the picture as the mount is moved, and
    Polaris ends where the true pole has it."""
    along, across = picture_axes(sense, dec_shift)
    true_ha, true_dec, _ = mount.where(POLARIS, site, when)
    turn = math.radians(true_ha - (ra_axis - 90))
    offset = (90 - true_dec) / scale() * (math.cos(turn) * along + math.sin(turn) * across)
    return float(centre[0] + offset[0]), float(centre[1] + offset[1])


def to_go(azimuth, altitude):
    """What is left to do, in a few words fit to be spoken."""
    if math.hypot(azimuth * math.cos(math.radians(55)), altitude) < 0.15:
        return "close enough. Measure again to check"
    parts = []
    if abs(azimuth) >= 0.1:
        parts.append(f"swing the north end {abs(azimuth):.1f} {'west' if azimuth > 0 else 'east'}")
    if abs(altitude) >= 0.1:
        parts.append(f"{'lower' if altitude > 0 else 'raise'} {abs(altitude):.1f}")
    return ", ".join(parts)


def align(scope, site, cam_class=None, aim=aim, watch=0, pause=time.sleep, speak=None):
    """With Polaris in view: turn the RA axis to five readings, see what the
    star swings round, and return the polar axis's error. Ends on the middle
    sighting; with `watch`, then looks that many more times while the bolts
    are turned, saying each time what is left."""
    from astropy.time import Time
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

            # 2. Turn the RA axis to five readings and sight the star at
            #    each. The further the tube is tipped from the axis, the
            #    faster the star crosses the picture, so the turn is sized to
            #    move it about a tenth of a degree a step. Every reading is
            #    come to from a degree below, so the slack in the gears is
            #    taken up the same way each time, and the Dec axis is not
            #    touched in between.
            lever = abs(90 - dec_start) + 0.7        # degrees: the tip, plus Polaris's own distance
            turn, sightings = min(12.5, math.degrees(0.1 / lever)), []
            # Where it began, then either side, then further and nearer: a
            # star near the edge of the picture leaves it one way, so
            # whichever readings still show it are the ones used.
            for step in (0, 1, -1, 2, -2, 0.5, -0.5, 1.5, -1.5):
                target = ra_start + step * turn
                if abs(target) > REACH + 0.5 or len(sightings) == 5:
                    continue
                aim(scope, target - 1.0, dec_start)
                aim(scope, target, dec_start)
                frame = look(cam, exposure)[0]
                swung = star(frame, tipped)
                if swung:
                    sightings.append({"ra_axis": mount.wrap(scope.axes()[0]), "frame": frame, "when": Time.now(),
                                      "x": swung[0], "y": swung[1]})
            if len(sightings) < 3:
                raise lost
            sightings.sort(key=lambda s: s["ra_axis"])
            # The star is in a different place in each sighting, so the
            # middle of them all is a flat with no star in it: each is
            # measured again against that.
            flat = middle_of([s["frame"] for s in sightings] + [tipped])
            for s in sightings:
                again = star(s["frame"], flat)
                if again:
                    s["x"], s["y"] = again[:2]
        finally:
            aim(scope, ra_start - 1.0, dec_start)
            aim(scope, ra_start, dec_start)
        # Where the axis ought to be in the picture if the readings were
        # exact: back along the Dec direction from the middle, by the tube's tip.
        h, w = start.shape
        expected = np.array([w / 2, h / 2]) - (90 - dec_start) * shift
        points = [(s["ra_axis"], s["x"], s["y"]) for s in sightings]
        cx, cy, sense, misfit, used, misses = fitted(points, expected)
        if misfit * per_pixel > 0.02:
            raise interface.Refusal("INVALID_REQUEST", f"The sightings do not lie on one circle (they miss by "
                                    f"{misfit * per_pixel * 60:.1f}'): cloud, or not the same star each time. "
                                    "Run it again.")
        good = [s for s, p in zip(sightings, points) if p in used]
        middle = good[len(good) // 2]
        azimuth, altitude = axis_error((middle["x"], middle["y"]), (cx, cy), sense, shift, middle["ra_axis"],
                                       site, middle["when"])
        how = {"sightings": len(points), "used": len(used), "turn_deg": round(turn, 2),
               "misfit_arcmin": round(misfit * per_pixel * 60, 2),
               "misses_arcmin": [None if miss is None else round(miss * per_pixel * 60, 2) for miss in misses],
               "axis_from_polaris_deg": round(math.hypot(middle["x"] - cx, middle["y"] - cy) * per_pixel, 3)}
        print("Sightings (RA axis, miss from the circle): "
              + ", ".join(f"{a:+.1f}° {'left out' if miss is None else format(miss * per_pixel * 60, '.1f') + chr(39)}"
                          for (a, _, _), miss in zip(points, misses)), flush=True)

        # 3. Stay on the star while the bolts are turned. The axis keeps its
        #    place in the picture and Polaris moves toward where it belongs;
        #    the RA axis is not turned again.
        for i in range(watch):
            frame, exposure, _ = look(cam, exposure)
            seen = star(frame, flat)
            ra_now = mount.wrap(scope.axes()[0])
            target = belongs((cx, cy), sense, shift, ra_now, site)
            if seen:
                azimuth, altitude = axis_error(seen[:2], (cx, cy), sense, shift, ra_now, site)
                words = to_go(azimuth, altitude)
                picture(frame, seen[0], seen[1], f"Polaris: {words}", target)
            else:
                words = "the star has left the picture. Find it again"
                picture(frame, w / 2, h / 2, words, target)
            print(f"  {i + 1}/{watch}: {words}", flush=True)
            if speak:
                speak(words)
            if i + 1 < watch:
                pause(3)
    return azimuth, altitude, how


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["check", "find", "align"])
    ap.add_argument("--radius", type=float, metavar="DEG",
                    help=f"with find: how far from the home position to look (default {RADIUS:g}°; less "
                         f"when ./polaralign.py measured the axis in the last fortnight, and {NARROW:g}° when "
                         "a landmark check says the mount faces the right way)")
    ap.add_argument("--anyway", action="store_true", help="with find: start though the focus has not been checked")
    ap.add_argument("--record", action="store_true", help="with find: keep every look and measurement")
    ap.add_argument("--watch", type=int, default=0, metavar="N",
                    help="with align: then look N times a few seconds apart, for adjusting by")
    ap.add_argument("--quiet", action="store_true", help="with align --watch: do not speak")
    ap.add_argument("--dry-run", action="store_true", help="say what it would do; no camera, no mount")
    ap.add_argument("--json", action="store_true", help="answer in JSON at the end")
    args = ap.parse_args()
    kind = f"polaris.{args.command}" + (".dry_run" if args.dry_run else "")
    return interface.main(kind, lambda: run(args), args.json)


def run(args):
    if args.command == "check":
        if args.dry_run:
            print("Would not move the mount: takes ten frames where the telescope is.")
            return {"would_move": False, "safe": True}
        return check(config.load()["site"])
    # The lock comes first: before the settings are read or the mount opened.
    if mount.LOCK_FILE.exists():
        raise interface.Refusal("MOTION_LOCKED",
                                f"Motion is locked: {mount.LOCK_FILE.read_text(encoding='utf-8').strip()}")
    site = config.load()["site"]
    radius = args.radius
    if args.command == "find" and radius is None:
        marked, aligned = landmark_says(), aligned_says()
        radius = NARROW if marked else aligned["radius"] if aligned else RADIUS
        if marked:
            print(f"The landmark {marked['name']} was where it belongs a little while ago, so the mount faces "
                  f"the right way: looking within {NARROW:g}° only.")
        elif aligned:
            print(f"./polaralign.py put the axis {aligned['total_deg']:g}° from the pole {aligned['days_ago']:g} "
                  f"days ago. If the tripod has not been moved since, Polaris is close: looking within "
                  f"{radius:g}° only (--radius {RADIUS:g} for the full search).")
    if args.dry_run:
        if args.command == "align":
            note = ("Tips the tube about a tenth of a degree, then turns the RA axis to five readings up to "
                    "12.5° apart, photographing Polaris at each, and goes back to the middle one."
                    + (f" Then photographs it {args.watch} more times without moving." if args.watch else ""))
            print(f"Would move the mount. {note}")
            return {"would_move": True, "safe": True}, [note]
        found = plan(site, radius)
        print(f"Would move the mount: up to {found['looks']} looks within {found['radius_deg']:g}° of the "
              f"home position, the nearest {found['looks_near']} first, stopping at the first that shows Polaris.")
        for warning in found["warnings"]:
            print(f"  {warning}")
        return found, found["warnings"]
    if args.command == "find" and not args.anyway and not focus_checked():
        raise interface.Refusal("INVALID_REQUEST", "The focus has not been checked today, and a star out of "
                                "focus will not show against a bright sky: the search would most likely find "
                                "nothing. Run ./focus.py --scene on the most distant thing in view (or "
                                "./focus.py on a star), or start the search with --anyway.")
    scope = mount.Mount()
    try:
        if args.command == "find":
            folder = RUNS / time.strftime("%Y%m%d-%H%M%S") if args.record else None
            if folder:
                folder.mkdir(parents=True, exist_ok=True)
                before = check(site)
                (folder / "preflight.json").write_text(json.dumps(before, indent=1), encoding="utf-8")
                print(f"Keeping every look in {folder}")
            return find(scope, site, radius, record=folder)
        import polaralign
        speak = None
        if args.watch and not args.quiet:
            import focus
            speak = focus.say
        azimuth, altitude, how = align(scope, site, watch=args.watch, speak=speak)
        words = polaralign.describe(azimuth, altitude)
        print("\n" + words)
        print("This goes by the home position for which way is up, so take it as rough. Adjust the bolts "
              "(--watch keeps looking while you do) and run it again; ./polaralign.py after dark is the "
              "fine measurement.")
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
