#!/usr/bin/env python3
"""Map which parts of the sky the telescope can see from where it stands.

    ./horizon.py --trace         follow the top of whatever is in the way right round
    ./horizon.py --trace --daylight      the same by day: bright, even and sky-coloured means sky
    ./horizon.py --trace --fresh         start again, not from the skyline already measured
    ./horizon.py                 the older way: look on a fixed grid and report what is blocked
    ./horizon.py --step 20       degrees of bearing between the first looks
    ./horizon.py --show          the skyline now in use, as the planner sees it
    ./horizon.py --forget        throw the measured skyline away
    ./horizon.py --dry-run       say where it would look, without moving

The quick way to get a skyline is a phone panorama (./panorama.py): no
motors, a few minutes. This survey is the telescope measuring for itself, or
checking a panorama's answer: when a skyline has already been measured, from
either, --trace starts each bearing at the height that skyline gives and only
looks further where the two disagree.

The mount looks in a direction and the camera takes a short frame. At night,
stars in the frame mean open sky and none means a house, hedge or tree. It
needs a clear night: cloud looks the same as a wall. By day (--daylight) the
frame is cut into small squares and each is judged against a frame of sky
taken high up: bright enough, smooth, and about the same colour means sky.
Colour only tips the balance, since cloud is grey and walls can be blue.
Either way a frame can show the top itself, part sky and part not, and then
that one frame gives the height.

--trace starts 30 degrees apart and adds bearings only where the skyline
needs them: where neighbours differ, and where a top sits off the straight
line between its neighbours. It checks itself: sky must be seen high up
before it starts, there must be sky well above each top it found, and at the
end it goes back to the first bearing to see the same thing again.

What it measures is kept in cache/horizon.json and the planner uses it from
then on, raised by `margin` under [horizon] in config.toml, because one
branch is enough to spoil a frame. Every look's small picture, marked with
what was taken for sky, is kept in horizon/looks/ to check a wrong answer by.

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
LOOKS = config.DATA / "horizon" / "looks"     # each look's picture, marked up
ALTITUDES = (25, 40, 55, 70)
ENOUGH_STARS = 8
STEADY = 5      # seconds for the tube to stop shaking before a frame of stars
# By day a blurred rooftop will do, so the frame is taken as soon as two
# running agree; this is only the longest it waits for that.
STEADY_DAY = 5
# Tracing the top of what is in the way.
FINE = 3        # degrees: how closely a top is pinned down
TOP = 75        # the highest look
START = 30      # degrees between the first bearings
FINEST = 7.5    # and the closest that two bearings are put
JUMP = 6        # neighbouring tops further apart than this get a look in between
BENT = 3        # so does a top this far off the straight line between its neighbours
MOST = 48       # bearings at most, however ragged the skyline
CLEARANCE = 15  # there must be sky this far above a top, or the top is doubted
# Telling sky from wall by day, square by square, against a frame of sky taken high up.
SKY_LEVEL = 0.4     # sky is at least this bright next to the high sky
SKY_SCORE = 0.65    # brightness counts 0.4, smoothness 0.4, colour 0.2: this much makes sky
MOSTLY = 0.85       # this share of a frame one way makes it all sky, or all blocked


# --- the skyline as the planner uses it ------------------------------------------
#
# A skyline is a list of points round the compass, {"az", "alt"}: the view is
# blocked up to `alt` at bearing `az`, and in between it runs straight from
# one point to the next. A point may also carry "open" (sky was seen down to
# `alt`; the top is somewhere below), "least" (blocked at least this high: the
# top was out of the picture) and "extra" (degrees of doubt, added when used).

def measured():
    """What the last survey or panorama kept: {"skyline": [...], "source",
    "saved", ...}, or {} if nothing has been measured."""
    try:
        saved = json.loads(RESULTS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return saved if isinstance(saved.get("skyline"), list) and saved["skyline"] \
        and "alt" in saved["skyline"][0] else {}


def limit(skyline, az, margin=0.0):
    """How high the view is blocked at each bearing in `az` (an array), with
    the margin and each point's own doubt added. Nothing is added to a point
    where the sky was open as low as was looked."""
    az = np.asarray(az, dtype=float)
    if not skyline:
        return np.zeros_like(az)
    points = sorted(skyline, key=lambda p: p["az"])
    tops = [p["alt"] if p.get("open") else min(p["alt"] + p.get("extra", 0) + margin, 90) for p in points]
    return np.interp(az % 360, [p["az"] for p in points], tops, period=360)


def in_the_way(settings, az, margin=None):
    """How high the view is blocked at one bearing, in degrees, from the
    settings' [horizon]: the blocked list and the measured skyline together.
    0 where nothing is known to be in the way."""
    top = 0.0
    for block in settings.get("blocked", []):
        lo, hi = block["from"] % 360, block["to"] % 360
        if (lo <= az % 360 <= hi) if lo <= hi else (az % 360 >= lo or az % 360 <= hi):
            top = max(top, float(block["altitude"]))
    if settings.get("skyline"):
        margin = settings.get("margin", 0) if margin is None else margin
        top = max(top, float(limit(settings["skyline"], np.array([az]), margin)[0]))
    return top


def keep(skyline, source, **more):
    """Save a skyline for the planner. The looks and warnings that led to it
    go in with it."""
    saved = dict({"saved": time.time(), "source": source,
                  "skyline": sorted(skyline, key=lambda p: p["az"])}, **more)
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(saved, indent=1), encoding="utf-8")
    return saved


def picture_of(skyline, low, margin=0.0):
    """The skyline as text, a line every 15 degrees."""
    lines = []
    for az in range(0, 360, 15):
        top, usable = float(limit(skyline, [az])[0]), float(limit(skyline, [az], margin)[0])
        bar = "#" * max(math.ceil((top - low) / 3), 0)
        lines.append(f"{az:>4}° {bar:<24} " + (f"open down to {low:g}° or lower" if usable <= low else
                                                f"blocked to {top:.0f}°, usable from {max(usable, low):.0f}°"))
    return "\n".join(lines)


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


def blocks(mosaic, side=64):
    """Averages over 64-pixel squares: dust specks, noise and the colour
    pattern drop out."""
    small = mosaic[:mosaic.shape[0] // side * side, :mosaic.shape[1] // side * side].astype(np.float32)
    return small.reshape(small.shape[0] // side, side, small.shape[1] // side, side).mean(axis=(1, 3))


def squares(mosaic):
    """What each 64-pixel square of a raw frame is like: (brightness, grain,
    blue over red), three arrays. Grain is how much the brightness varies
    inside the square, as a share of it: sky has none but the sensor's own."""
    lum = mosaic[0::2, 0::2].astype(np.float32) + mosaic[0::2, 1::2] + mosaic[1::2, 0::2] + mosaic[1::2, 1::2]
    rows, cols = lum.shape[0] // 32, lum.shape[1] // 32
    cells = lum[:rows * 32, :cols * 32].reshape(rows, 32, cols, 32)
    level = cells.mean(axis=(1, 3)) / 4
    grain = cells.std(axis=(1, 3)) / np.maximum(cells.mean(axis=(1, 3)), 1.0)
    red, blue = blocks(mosaic[0::2, 0::2], 32), blocks(mosaic[1::2, 1::2], 32)
    return level, grain, blue / np.maximum(red, 1.0)


def sky_reference(mosaic):
    """What today's sky looks like, from a frame of it taken high up."""
    level, grain, blue = squares(mosaic)
    return {"level": float(np.median(level)), "grain": float(np.median(grain)), "blue": float(np.median(blue))}


def towards_sky(mask):
    """For a frame that is part sky: how far the edge lies from the middle of
    the frame, as a share of the frame's height, positive when the edge is
    on the sky's side of the middle. Which way is up in the frame is not
    known on this mount, so the sky's side is taken for up."""
    rows, cols = np.indices(mask.shape)
    way = np.array([rows[mask].mean() - rows[~mask].mean(), cols[mask].mean() - cols[~mask].mean()])
    way /= max(float(np.hypot(*way)), 1e-6)
    # The frame's reach along that line, in frame heights.
    reach = abs(way[0]) + abs(way[1]) * mask.shape[1] / mask.shape[0]
    return (0.5 - float(mask.mean())) * reach


def read_day(mosaic, reference):
    """What a daytime frame shows. The telescope is focused on the stars, so
    anything nearby is a blur: a wall is a darker frame, and the top of one a
    frame shading from dark to bright. Each square is scored for brightness
    next to the high sky, smoothness, and colour next to the high sky's;
    colour alone never decides. Returns {"view": "sky", "edge" or "blocked",
    "share" of the frame that is sky, "level", "offset" (see towards_sky; only
    for an edge), "mask"}. `reference` is sky_reference()'s answer, or just
    the high sky's brightness."""
    if not isinstance(reference, dict):
        reference = {"level": float(reference), "grain": 0.0, "blue": None}
    level, grain, blue = squares(mosaic)
    level = level / max(reference["level"], 1.0)
    bright = np.clip((level - SKY_LEVEL / 2) / (SKY_LEVEL / 2), 0, 1)
    rough = 3 * reference["grain"] + 0.01          # the sensor's own grain, with room
    smooth = np.clip(2 - grain / rough, 0, 1)
    if reference["blue"]:
        # The sky is whiter low down and bluer away from the Sun: twice or
        # half the high sky's colour is as far as it goes.
        same = np.clip(1 - np.abs(np.log(np.maximum(blue, 0.01) / reference["blue"])) / math.log(2), 0, 1)
    else:
        same = np.ones_like(level)
    mask = 0.4 * bright + 0.4 * smooth + 0.2 * same >= SKY_SCORE
    # A square unlike all its neighbours is a dust speck or a bird, not a roof.
    from scipy import ndimage
    mask = ndimage.median_filter(mask.astype(np.uint8), 3, mode="nearest").astype(bool)
    share = float(mask.mean())
    seen = {"view": "sky" if share >= MOSTLY else "blocked" if share <= 1 - MOSTLY else "edge",
            "share": round(share, 2), "level": round(float(np.median(level)), 2), "mask": mask}
    if seen["view"] == "edge":
        seen["offset"] = round(towards_sky(mask), 2)
    return seen


def read_night(places, shape):
    """What a frame of stars shows. `places` is where the stars are (row,
    column), `shape` the frame's. Enough stars is sky, too few is blocked. If
    there are enough but a strip along one side has none, and so many stars
    would hardly ever leave it empty by chance, a roof is across that strip:
    the frame holds the top."""
    stars = len(places)
    seen = {"view": "sky" if stars >= ENOUGH_STARS else "blocked", "stars": stars,
            "share": 1.0 if stars >= ENOUGH_STARS else 0.0}
    if stars < ENOUGH_STARS:
        return seen
    best = 1.0
    for axis in (0, 1):
        along = places[:, axis] / shape[axis]
        for filled in (along.max(), 1 - along.min()):     # stars reach this far from one side
            if filled ** stars < 0.01 and filled < best:
                best, reach = float(filled), 1.0 if axis == 0 else shape[1] / shape[0]
    if best <= MOSTLY:
        seen.update(view="edge", share=round(best, 2), offset=round((0.5 - best) * reach, 2))
    return seen


def marked(mosaic, mask, note):
    """A small picture of a look with what was not taken for sky shaded, to
    check a wrong answer by."""
    from PIL import Image, ImageDraw

    from camera import colour, stretch
    image = Image.fromarray(stretch(colour(mosaic)[::4, ::4]))
    if mask is not None:
        shade = Image.fromarray((~mask * 110).astype(np.uint8)).resize(image.size, Image.NEAREST)
        image.paste(Image.new("RGB", image.size, (255, 40, 90)), mask=shade)
    ImageDraw.Draw(image).text((8, 6), note, fill=(255, 190, 60))
    return image


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
    frame and returns True for open sky, False for something in the way, None
    where the mount may not go, or, when the frame shows the top itself, the
    height of that top as a float. `look.log` lists every look made."""
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
    field = config.field_height(config.hardware())    # degrees from the bottom of a frame to the top

    def by_day():
        """A frame once the tube has stopped shaking: two running that read
        the same, or the one in hand when STEADY_DAY is up."""
        began, before = time.time(), None
        while True:
            mosaic, _ = look.cam.frame(state["exposure"])
            seen = read_day(mosaic, state["reference"])
            waited = time.time() - began
            if waited >= STEADY_DAY or (before and before["view"] == seen["view"]
                                        and abs(before["share"] - seen["share"]) <= 0.05
                                        and abs(before["level"] - seen["level"]) <= 0.05 * seen["level"]):
                return mosaic, dict(seen, settled_s=round(waited, 1))
            before = seen

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
        if daylight:
            if state["reference"] is None:
                # The first look is at sky high up: it sets the exposure and
                # what sky looks like today.
                state["exposure"], _ = daylight_exposure(look.cam, state["exposure"])
                state["reference"] = sky_reference(look.cam.frame(state["exposure"])[0])
            mosaic, seen = by_day()
            detail = f"{seen['share']:.0%} sky, brightness {seen['level']:.0%} of the high sky"
        else:
            time.sleep(STEADY)   # let the tube stop shaking
            mosaic, _ = look.cam.frame(state["exposure"])
            lum = luminance(mosaic)
            seen = read_night(skywatch.star_places(lum), lum.shape)
            detail = f"{seen['stars']} stars"
        mask = seen.pop("mask", None)
        answer = seen["view"] == "sky"
        if seen["view"] == "edge":
            # The top is in the frame: this far above or below its middle.
            answer = seen["top"] = round(alt + seen["offset"] * field, 1)
            detail += f", the top in view at {answer:.1f}°"
        snap.publish(mosaic, kind="horizon sweep", quick=True,
                     detail=f"bearing {az:g}°, {alt:g}° up · {detail}")
        LOOKS.mkdir(parents=True, exist_ok=True)
        marked(mosaic, mask, f"{az:g} / {alt:g}: {seen['view']}").save(
            LOOKS / f"{len(log) + 1:03d}-az{az:g}-alt{alt:g}.jpg", quality=80)
        log.append(dict({"az": az, "alt": alt, "open": seen["view"] != "blocked"}, **seen))
        print(f"bearing {az:>5g}°, {alt:>4g}° up: {seen['view']} ({detail})", flush=True)
        return answer

    look.log = log
    try:
        with Camera(gain=gain) as cam:
            look.cam = cam
            if LOOKS.exists():
                for old in LOOKS.glob("*.jpg"):     # the last survey's pictures
                    old.unlink()
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

def top_of(look, az, guess, low, top=TOP, fine=FINE, or_else=None):
    """How high the view is blocked in one bearing. Starts at `guess` and
    closes in until sky and obstruction are within `fine` degrees of each
    other, or stops at once on a frame that shows the top itself. `or_else`
    is a second, lower guess, tried when the top is not just under the
    first: between two bearings it is usually as high as one or the other.
    Returns
    {"az", "state", "shut", "clear"}: `shut` is the highest look that was
    blocked, `clear` the lowest that saw sky; they are the same height when
    the top was seen in a frame. States: "open" (sky down to the lowest
    look), "edge" (a top was found), "blocked" (no sky up to the highest
    look), "unreachable"."""
    seen = {}

    def view(alt):
        alt = min(max(round(alt), low), top)
        if alt not in seen:
            seen[alt] = look(az, alt)
        return alt, seen[alt]

    def in_view(sky):
        return isinstance(sky, float)

    def at(height):
        return {"az": az, "state": "edge", "shut": height, "clear": height, "in_view": True}

    start, first = view(guess)
    if first is None:
        # The mount's limits often rule out one height and allow another.
        start, first = next(((alt, sky) for alt, sky in (view(h) for h in (top, low)) if sky is not None),
                            (start, None))
    shut = clear = None
    stride, jumped = fine, False
    if first is None:
        return {"az": az, "state": "unreachable", "shut": None, "clear": None}
    if in_view(first):
        return at(first)
    limit = False   # the mount's limits stopped the search
    if first:
        clear = start
        while shut is None and clear > low:
            alt, sky = view(clear - stride)
            if sky is None:
                break
            if in_view(sky):
                return at(sky)
            if sky and or_else is not None and or_else < alt - stride:
                # Not just under the first guess: straight to the second next,
                # and closely again from there.
                clear, stride, or_else, jumped = alt, alt - or_else, None, True
            elif sky:
                clear, stride, jumped = alt, fine if jumped else stride * 2, False
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
            if in_view(sky):
                return at(sky)
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
        if in_view(sky):
            return at(sky)
        if sky:
            clear = alt
        else:
            shut = alt
    return {"az": az, "state": "edge", "shut": shut, "clear": clear}


def is_sky(seen):
    """Whether a look's answer is plain open sky."""
    return seen is not None and not isinstance(seen, float) and bool(seen)


def height(found, low):
    """One number for a bearing's obstruction, to compare neighbours by."""
    return {"open": low, "edge": found["clear"], "blocked": 90}.get(found["state"])


def between(a, b):
    """Degrees round from bearing a to bearing b, going clockwise."""
    return (b - a) % 360 or 360


def trace(look, bearings, low, top=TOP, fine=FINE, known=None, finest=FINEST, most=MOST):
    """Follow the top of what is in the way round the compass, starting from
    the given bearings and adding more only where the skyline needs them.
    `known` is a skyline measured before (see limit()): each bearing then
    starts at the height it gives, and bearings are added only where this
    survey and that one part company.
    Returns (one top_of() answer per bearing, in bearing order; warnings)."""
    found, warnings = {}, []

    def expected(az):
        return min(max(float(limit(known, [az])[0]), low), top)

    def measure(az, sides=()):
        """`sides` are the two bearings this one was put between."""
        tops = sorted(found[side]["clear"] for side in sides if found[side]["state"] in ("open", "edge"))
        if known:
            guess, lower = expected(az), None
        elif len(tops) == 2:
            # Between a low top and a high one it is usually one or the other.
            guess, lower = tops[1], tops[0]
        else:
            # Start where the nearest bearing already measured ended up.
            near = [f for f in found.values() if f["state"] in ("open", "edge")]
            near = min(near, key=lambda f: min((f["az"] - az) % 360, (az - f["az"]) % 360), default=None)
            guess, lower = near["clear"] if near else low, None
        found[az] = top_of(look, az, guess, low, top, fine, lower)

    def off(az):
        """What is compared between neighbours: the top itself, or how far it
        is from the skyline already known."""
        return height(found[az], low) - (expected(az) if known else 0)

    # Check 1: sky must be seen high up, or nothing after it means anything.
    high = next((az for az in bearings if is_sky(look(az, top))), None)
    if high is None:
        raise interface.Refusal("NO_SKY", f"No open sky seen even {top}° up. Is the cap off? At night "
                                "this needs a clear sky.")
    for az in bearings:
        measure(az)

    # Check 2: more bearings where the skyline is not a straight line between
    # the ones it has: a sudden change between neighbours is a corner, and a
    # top standing off the line through its neighbours is a chimney or a tree.
    while len(found) < most:
        ring = sorted(az for az in found if height(found[az], low) is not None)
        n, extra = len(ring), {}
        for i in range(n if n > 1 else 0):
            before, a, b, after = (ring[(i + k) % n] for k in (-1, 0, 1, 2))
            gap = between(a, b)

            def bent(p, q, r):
                # How far q's top is from the line from p's to r's. Beside a
                # corner every top is off that line: the corner gets the look.
                if n < 3 or abs(off(p) - off(q)) > JUMP or abs(off(q) - off(r)) > JUMP:
                    return False
                share = between(p, q) / (between(p, q) + between(q, r))
                return abs(off(q) - (off(p) + (off(r) - off(p)) * share)) > BENT
            if gap / 2 >= finest and (abs(off(a) - off(b)) > JUMP or bent(before, a, b) or bent(a, b, after)):
                extra[(a + gap / 2) % 360] = (a, b)
        extra = {az: sides for az, sides in extra.items() if az not in found}
        if not extra:
            break
        for az in sorted(extra, key=side)[:most - len(found)]:
            measure(az, extra[az])
    else:
        warnings.append(f"The skyline is ragged: it stopped adding bearings at {most}. Run it again "
                        "to carry on from this one.")

    # Check 3: sky well above each top. A bright wall can pass for sky, and
    # branches or wires can hang over a roof.
    for az in sorted(found, key=side):
        f = found[az]
        if f["state"] == "edge" and f["clear"] + CLEARANCE <= top \
                and not is_sky(above := look(az, f["clear"] + CLEARANCE)) and above is not None:
            f["doubt"] = True
            warnings.append(f"Bearing {az:g}°: sky at {f['clear']:g}° but none {CLEARANCE}° higher. "
                            "Look at that direction yourself.")

    # Check 4: back to the start. If the first bearing no longer looks the
    # same, the mount slipped or the light changed while going round.
    first = next((found[az] for az in bearings if found[az]["state"] in ("open", "edge")), None)
    if first and first.get("in_view"):
        again = look(first["az"], first["clear"])
        same = isinstance(again, float) and abs(again - first["clear"]) <= 1
    elif first:
        same = is_sky(look(first["az"], first["clear"])) and \
            (first["state"] != "edge" or look(first["az"], first["shut"]) in (False, np.False_))
    if first and not same:
        warnings.append(f"Going back to bearing {first['az']:g}° gave a different answer from "
                        "the first time. Did the mount slip, or the light change? Do not "
                        "trust this survey.")
    return [found[az] for az in sorted(found)], warnings


def skyline_from(found, low, known=None):
    """A trace as a skyline (see limit()). With a skyline known before, its
    points are kept, each moved by what this survey found near it, so the
    detail a panorama gave survives a check by the telescope."""
    points = []
    for f in found:
        top = height(f, low)
        if top is None:
            continue
        point = {"az": f["az"], "alt": top}
        if f["state"] == "open":
            point.update(alt=f["clear"], open=True)
        if f.get("doubt"):
            point["extra"] = CLEARANCE
        points.append(point)
    # Where neighbours differ by a corner's worth, the corner is somewhere
    # between them: count the whole gap as blocked to the higher of the two.
    for a, b in zip(list(points), points[1:] + points[:1]):
        if len(points) > 1 and abs(a["alt"] - b["alt"]) > JUMP:
            lower, at = (a, a["az"] + 0.1) if a["alt"] < b["alt"] else (b, b["az"] - 0.1)
            points.append({"az": round(at % 360, 1), "alt": max(a["alt"], b["alt"])})
    if known and points:
        # How far each measured top is from the known skyline; open bearings
        # say only that it is no higher than was looked.
        shifts = []
        for p in points:
            shift = p["alt"] - float(limit(known, [p["az"]])[0])
            shifts.append({"az": p["az"], "alt": min(shift, 0) if p.get("open") else shift})
        near = lambda az: min(min(between(az, p["az"]), between(p["az"], az)) % 360 for p in points) < FINEST / 2
        looked = list(points)
        for p in known:
            if p.get("unseen"):
                # Past the edge of a panorama only the telescope has looked.
                points.append({"az": p["az"], "alt": round(float(limit(looked, [p["az"]])[0]), 1)})
            elif not near(p["az"]):
                points.append(dict(p, alt=round(p["alt"] + float(limit(shifts, [p["az"]])[0]), 1)))
    return sorted(points, key=lambda p: p["az"])


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
        words = {"open": f"open down to {f['clear']:g}°", "edge": f"blocked up to {f['clear']:g}°",
                 "blocked": "blocked as far up as it looked", "unreachable": "not reachable"}[f["state"]]
        bar = "#" * math.ceil((h - low) / 3) if h is not None else ""
        lines.append(f"{f['az']:>6g}° {bar:<24} {words}{'  (in doubt)' if f.get('doubt') else ''}")
    return "\n".join(lines)


def usable(skyline, low, margin):
    """The skyline with the margin on: what the planner keeps targets above."""
    return [{"az": p["az"], "alt": round(max(float(limit(skyline, [p["az"]], margin)[0]), low), 1)}
            for p in sorted(skyline, key=lambda p: p["az"])]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--step", type=int, help="degrees of bearing between the first looks (default 30)")
    ap.add_argument("--trace", action="store_true", help="follow the top of what is in the way")
    ap.add_argument("--daylight", action="store_true", help="tell sky from wall by the look of it, not by stars")
    ap.add_argument("--fresh", action="store_true", help="with --trace: do not start from the skyline already measured")
    ap.add_argument("--show", action="store_true", help="print the skyline in use; nothing moves")
    ap.add_argument("--forget", action="store_true", help="throw the measured skyline away; nothing moves")
    ap.add_argument("--exposure", type=float, help="seconds (default 1; by day it is found from the sky)")
    ap.add_argument("--gain", type=int, help="default 2000, or 100 by day")
    ap.add_argument("--dry-run", action="store_true", help="say where it would look; no camera, no mount")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    name = "horizon.show" if args.show else "horizon.forget" if args.forget else \
        "horizon.dry_run" if args.dry_run else "horizon"
    return interface.main(name, lambda: run(args), args.json)


def show(low, margin, in_use=True):
    kept = measured()
    if not kept:
        print("No skyline has been measured. ./panorama.py makes one from a phone panorama; "
              "./horizon.py --trace has the telescope measure it.")
        return {"skyline": None}
    how = {"panorama": "a phone panorama", "telescope": "the telescope's own survey",
           "panorama+telescope": "a phone panorama, checked by the telescope"}.get(kept["source"], kept["source"])
    print(f"Measured {time.strftime('%d %B %Y', time.localtime(kept['saved']))} from {how}. "
          f"Margin {margin:g}°.\n\n{picture_of(kept['skyline'], low, margin)}")
    for warning in kept.get("warnings", []):
        print(f"\nCHECK: {warning}")
    if not in_use:
        print("\nThe planner is not using it: use_survey is off under [horizon] in config.toml.")
    return {"skyline": kept["skyline"], "usable": usable(kept["skyline"], low, margin), "source": kept["source"],
            "saved": kept["saved"], "margin": margin, "in_use": in_use}


def run(args):
    cfg = config.load() if config.FILE.exists() else config.example()
    site, low, margin = cfg["site"], cfg["horizon"]["min_altitude"], cfg["horizon"]["margin"]
    if args.show:
        return show(low, margin, cfg["horizon"]["use_survey"])
    if args.forget:
        had = bool(measured())
        if RESULTS.exists():
            RESULTS.unlink()
        print("The measured skyline is forgotten." if had else "There was no measured skyline.")
        return {"forgotten": had}
    step = args.step or 30
    bearings = sorted(range(0, 360, step), key=side)
    kept = measured() if args.trace and not args.fresh else {}
    known = kept.get("skyline")
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
            # A look or two where the top is where it was expected or the view
            # is open, three or four where it has to be found, one above each
            # top to check it, and bearings added at corners.
            n = len(bearings)
            least, most = n + 3, 5 * n + 12
            minutes = 2 * n + 6 if known else 3 * n + 6
            print(f"Would follow the skyline from {n} bearings, adding more where it bends, from {low}° "
                  f"up to {TOP}°. {reachable} of the {total} lowest and highest looks are within the "
                  f"mount's limits just now. At about a minute a look: {least} minutes if the view is "
                  f"open all round, perhaps {most} if much is in the way.")
            print(f"It would start from the skyline measured on "
                  f"{time.strftime('%d %B', time.localtime(kept['saved']))} and look further only where "
                  f"that is wrong: about {minutes} minutes." if known else
                  "No skyline has been measured yet, so every top has to be found. A phone panorama "
                  "first (./panorama.py) makes this a check instead of a search.")
            out = sorted(set(bearings) - within)
            if out:
                print("Out of reach altogether just now (the Sun, or too far from the meridian): "
                      + ", ".join(f"{az}°" for az in out))
        else:
            minutes = reachable
            print(f"Would look in {reachable} of {total} directions (the rest are outside the "
                  f"mount's limits), about {reachable} minutes.")
        return {"would_move": True, "looks": total, "reachable": reachable, "minutes": minutes,
                "from_known_skyline": bool(known)}
    exposure = args.exposure or (0.002 if args.daylight else 1.0)
    gain = args.gain or (100 if args.daylight else 2000)
    warnings = []
    with eye(site, exposure, gain, args.daylight) as look:
        if args.trace:
            found, warnings = trace(look, bearings, low, known=known)
        else:
            if args.daylight:
                # Sky high up first, so the exposure is set on sky and not on a wall.
                if not any(look(az, TOP) for az in bearings):
                    raise interface.Refusal("NO_SKY", f"No open sky seen {TOP}° up. Is the cap off?")
            sweep(look, step)
        results = look.log
    if args.trace:
        skyline = skyline_from(found, low, known)
        source = "telescope" if not known or kept["source"] == "telescope" else "panorama+telescope"
        saved = keep(skyline, source, looks=results, warnings=warnings, trace=found,
                     blocked=skyline_blocked(found))
        print("\n" + profile(found, low))
        for warning in warnings:
            print(f"\nCHECK: {warning}")
        waits = [l["settled_s"] for l in results if "settled_s" in l]
        if waits:
            print(f"\nThe tube was steady {sorted(waits)[len(waits) // 2]:g} s after a slew, half the "
                  f"time; {max(waits):g} s at the longest.")
        print(f"\nKept, with every look's picture in {LOOKS}. The planner uses this skyline from now on, "
              f"raised by a margin of {margin:g}° (margin under [horizon] in config.toml). "
              "./horizon.py --show prints it.")
        return dict({k: v for k, v in saved.items() if k != "saved"}, usable=usable(skyline, low, margin)), warnings
    found = blocked(results)
    # A grid says less than a skyline: it is kept beside one, not over it.
    saved = dict(json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else {},
                 looks=results, blocked=found, warnings=warnings)
    saved.setdefault("saved", time.time())
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(saved, indent=1), encoding="utf-8")
    print("\n" + chart(results))
    if found:
        print("\nPut this under [horizon] in config.toml:\nblocked = [")
        for b in found:
            print(f"  {{ from = {b['from']:g}, to = {b['to']:g}, altitude = {b['altitude']} }},")
        print("]")
    else:
        print("\nNothing in the way in any direction looked at.")
    return {"looks": results, "blocked": found, "warnings": warnings}, warnings


if __name__ == "__main__":
    main()
