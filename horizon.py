#!/usr/bin/env python3
"""Map which parts of the sky the telescope can see from where it stands.

    ./horizon.py --trace         follow the top of whatever is in the way right round
    ./horizon.py --trace --daylight      the same by day: bright, even and sky-coloured means sky
    ./horizon.py --trace --fresh         start again, not from the skyline already measured
                                 (nor from a survey cut short earlier the same day)
    ./horizon.py                 the older way: look on a fixed grid and report what is blocked
    ./horizon.py --step 20       degrees of bearing between the first looks
    ./horizon.py --show          the skyline now in use, as the planner sees it
    ./horizon.py --forget        throw the measured skyline away
    ./horizon.py --use-aside FILE --checked "what you saw"
                                 keep a survey that was set aside, once its doubts are checked by eye
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
import records

ROOT = Path(__file__).parent
# Each spot in the garden has its own skyline and pictures (config.SPOT).
RESULTS = config.DATA / "cache" / (f"horizon-{config.SPOT}.json" if config.SPOT else "horizon.json")
LOOKS = config.DATA / "horizon" / (config.SPOT or "") / "looks"     # each look's picture, marked up
# A survey cut short keeps what it had measured here, after every bearing, and
# the next --trace the same day carries on from it (2 November 2026: a survey
# stopped at its first look over a camera that had jammed began again from nothing).
PARTIAL = RESULTS.with_name(RESULTS.stem + ".partial.json")
RESUME_S = 12 * 3600
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
    if RESULTS.exists():
        # The skyline it replaces is kept beside it (3 November 2026: a
        # checked one was overwritten, and only a copy set aside the day
        # before brought it back).
        import shutil
        shutil.copy2(RESULTS, RESULTS.with_name(f"{RESULTS.stem}.replaced-{time.strftime('%Y%m%d-%H%M%S')}.json"))
    records.write(RESULTS, saved)
    return saved


def set_aside(skyline, reason, **more):
    """Keep a survey that must not be used, for looking into, beside the
    skyline in use and never in its place. Returns where it went."""
    path = RESULTS.with_name(f"{RESULTS.stem}.not-used-{time.strftime('%Y%m%d-%H%M%S')}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    records.write(path, dict({"saved": time.time(), "not_used_because": reason,
                              "skyline": sorted(skyline, key=lambda p: p["az"])}, **more))
    return path


MOVED_DOUBT = 3.0     # degrees added to a skyline worked out from another spot, not measured


def distance_at(az, distances):
    """How far the things in the way are at bearing `az`, in metres, from
    [(from, to, metres), ...] (bearings clockwise, wrapping through north);
    None where no stretch covers it."""
    for lo, hi, metres in distances:
        lo, hi = lo % 360, hi % 360
        if (lo <= az % 360 <= hi) if lo <= hi else (az % 360 >= lo or az % 360 <= hi):
            return float(metres)
    return None


def moved(skyline, metres, bearing, distances, step=5, doubt=MOVED_DOUBT):
    """The skyline from another spot, `metres` away at `bearing` from where
    `skyline` was measured, worked out by geometry: each top is put at its
    distance (`distances`, from the old spot), its height kept, and seen
    again from the new place. What the old spot could not see (behind
    something nearer) cannot be known, so each point carries `doubt` and
    "moved": true until a survey from the new spot replaces it."""
    missing = [az for az in range(0, 360, 10) if distance_at(az, distances) is None]
    if missing:
        raise interface.Refusal("INVALID_REQUEST", "No distance given for bearings "
                                + ", ".join(f"{az}°" for az in missing) + ": cover the whole circle.")
    east, north = metres * math.sin(math.radians(bearing)), metres * math.cos(math.radians(bearing))
    seen = []
    for az in np.arange(0.0, 360.0, 0.5):
        alt = min(float(limit(skyline, np.array([az]))[0]), 80.0)   # straight up is a wall close by, not a roof
        d = distance_at(az, distances)
        x, y = d * math.sin(math.radians(az)) - east, d * math.cos(math.radians(az)) - north
        far = math.hypot(x, y)
        if far < 0.5:
            continue        # the new spot is at the obstacle itself
        top = d * math.tan(math.radians(alt))
        seen.append((math.degrees(math.atan2(x, y)) % 360, math.degrees(math.atan2(top, far))))
    bins = {}
    for az, alt in seen:
        b = int(round(az / step)) * step % 360
        bins[b] = max(bins.get(b, 0.0), alt)
    bearings = list(range(0, 360, step))
    known = [b for b in bearings if b in bins]
    tops = np.interp(bearings, known, [bins[b] for b in known], period=360)
    return [{"az": float(b), "alt": round(float(a), 1), "extra": doubt, "moved": True}
            for b, a in zip(bearings, tops)]


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
    burnt = burnt_share(mosaic)
    if burnt >= BURNT_DAY:
        # Burnt out is the brightest and smoothest a frame can be, so it
        # would always score as sky: on 2 November 2026 a whole survey with
        # the morning Sun low in the east read 297% of the high sky in every
        # direction, walls and all. It says only that the exposure is too
        # long for this view.
        return {"view": "burnt", "share": 0.0, "level": round(burnt, 2), "mask": None}
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
            "share": round(share, 2), "level": round(float(np.median(level)), 2), "mask": mask,
            # What the score was made from, kept with each look so the
            # weights can be tried against looks a person has labelled
            # (3 November 2026: a sunlit white wall scored as sky).
            "features": {"bright": round(float(np.median(bright)), 3), "smooth": round(float(np.median(smooth)), 3),
                         "colour": round(float(np.median(same)), 3),
                         "blue": round(float(np.median(blue)), 3) if blue is not None else None,
                         "grain": round(float(np.median(grain)), 4)}}
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


LIT = 1.5        # times the dark sky's level at which a frame counts as lit by the torch
BURNT = 0.01     # share of a frame burnt out that says a lit wall whatever else


def read_torch(seen, level, burnt, dark):
    """What a night frame shows with a torch fixed along the tube. A wall or
    a tree a few metres off is lit by it and cloud is not, which stars alone
    cannot tell apart: a frame with no stars in it was a house once on the
    first night out, and cloud the next time. `seen` is read_night()'s answer,
    `level` the frame's middle brightness, `burnt` the share of it burnt out,
    `dark` the level of the darkest frame of stars so far (None before one).

    Burnt out is blocked, whatever the star finder says: on the real camera
    a house wall three metres off read 2186 at 1 s against a sky of 51, and
    burnt out at 3 s, where 6780 "stars" were counted. Bright with no stars
    is blocked: a tree read 312 at 3 s against 61. Bright with stars is sky
    all the same, since stars do not shine through a wall: that is thin
    cloud. Dark with no stars is cloud or an unlit wall, and cannot be told:
    it is "unknown", never open sky (2 November 2026: what a survey could
    not see was taken for sky).

    The first survey on the real mount called the whole southern sky blocked
    to 75°, every look reading the same 420. The motors had stopped being
    driven part-way through, while the handset went on reporting each move
    as made: the telescope sat on one lit tree throughout. With the torch
    off the same view read 51, so the sky, cloud and all, was dark.
    overcast() is the check that stops a survey reading like that."""
    seen = dict(seen, level=round(float(level), 1))
    if burnt >= BURNT:
        return dict(seen, view="blocked", share=0.0, lit=True)
    if seen["view"] == "blocked":
        if dark and level >= LIT * dark:
            return dict(seen, share=0.0, lit=True)
        return dict(seen, view="unknown", share=0.0, cloud=True)
    return seen


HIGH = 70.0      # degrees up above which nothing in a garden is expected to stand


def overcast(alt, seen):
    """Whether a look cannot be believed: lit, not burnt out, and too high up
    to be a tree or a roof. Mist in the beam would do it, and so would a
    mount that is no longer going where it is sent."""
    return bool(alt >= HIGH and seen.get("lit") and seen.get("view") == "blocked" and seen.get("level", 0) < 1500)


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


BURNT_DAY = 0.5   # share of a daytime frame burnt out that leaves nothing to read


def burnt_share(mosaic):
    """The share of a raw frame at or near full brightness."""
    from camera import WHITE
    return float((np.asarray(mosaic) >= 0.98 * WHITE).mean())


def at_exposure(reference, metered, exposure):
    """The high sky's reference as it would read at another exposure: raw
    values go with the light and the time, so a view metered again because
    it burnt out is still compared with the same high sky."""
    return dict(reference, level=reference["level"] * exposure / metered)


LONGER = 4          # a night look with no stars is tried again this many times longer
LONGEST_S = 8.0     # but no longer than this
GLARE_MOST = 0.25
NOT_SAME = "Not repeatable:"   # check 4's warning: such a survey is set aside, never used
REFERENCE_S = 300              # by day, the high sky is looked at again this often: it changes   # share of a survey's looks too bright to read above which nothing is kept


def glare_share(log):
    """The share of a survey's looks left out as too bright to read. A survey
    that could not see most of the sky has no skyline to keep: on 2 November
    2026 one with every frame burnt out kept a skyline of nothing but sky."""
    made = [entry for entry in log if entry.get("open") is not None or entry.get("glare") or entry.get("unread")]
    blind = [entry for entry in made if (entry.get("glare") or entry.get("unread")) and not entry.get("resolved")]
    return len(blind) / len(made) if made else 0.0


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
def eye(site, exposure, gain, daylight=False, torch=False):
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
    state = {"exposure": exposure, "reference": None, "metered": exposure}
    log = []
    import moved
    watch, last = moved.Watch(daylight=daylight), []      # what the last look saw, and where it was
    field = config.field_height(config.hardware())    # degrees from the bottom of a frame to the top

    def by_day():
        """A frame once the tube has stopped shaking: two running that read
        the same, or the one in hand when STEADY_DAY is up."""
        began, before = time.time(), None
        reference = at_exposure(state["reference"], state["metered"], state["exposure"])
        while True:
            mosaic, _ = look.cam.frame(state["exposure"])
            seen = read_day(mosaic, reference)
            waited = time.time() - began
            if waited >= STEADY_DAY or (before and before["view"] == seen["view"]
                                        and abs(before["share"] - seen["share"]) <= 0.05
                                        and abs(before["level"] - seen["level"]) <= 0.05 * seen["level"]):
                return mosaic, dict(seen, settled_s=round(waited, 1))
            before = seen

    def look(az, alt):
        if daylight and state["reference"] is not None and not state.get("refreshing") \
                and time.time() - state["referenced"] > REFERENCE_S:
            # The daytime sky brightens and turns as the Sun climbs: on 2
            # November 2026 it was three times as bright minutes after the
            # first look. The high sky is looked at again, where it was first.
            state["reference"], state["refreshing"] = None, True
            try:
                look(*state["sky_at"])
            finally:
                state["refreshing"] = False
        try:
            plan = mount.plan_point(az, alt, site)
        except interface.Refusal as refusal:
            if refusal.code_name == "MOTION_LOCKED":
                raise
            log.append({"az": az, "alt": alt, "open": None})
            return None
        # Aim as goto does, with the correction of the side the tube really
        # comes over (mount.Mount.aim).
        hour_angle, dec = plan["hour_angle_hours"] * 15, plan["dec_deg"]
        west, error, steady = scope.aim(hour_angle, dec, site, offset)
        doubt = aim_doubt(steady, error, mount.pointing_measured(west), daylight)
        if doubt:
            # Nothing by day checks where it points: a look aimed by a guess is no look.
            log.append({"az": az, "alt": alt, "open": None, "unread": True, "aim": doubt})
            print(f"bearing {az:>5g}°, {alt:>4g}° up: not looked at ({doubt})", flush=True)
            return None
        # Stars need following; a rooftop needs the mount to hold still.
        scope.tracking(not daylight)
        # Where the mount says it is, and which side of the pole the tube came
        # over: by day nothing checks the pointing, and on the meridian the
        # mount may take either side, whose pointing differs by degrees
        # (6 October 2026: 5.8° in Dec on one side, 0.2° on the other).
        try:
            ra_axis, dec_axis = scope.axes()
            where = {"axes": [round(ra_axis, 2), round(dec_axis, 2)], "over": mount.over_pole(dec_axis)}
        except Exception:
            where = {}
        if daylight:
            if state["reference"] is None:
                # The first look is at sky high up: it sets the exposure and
                # what sky looks like today.
                state["exposure"], _ = daylight_exposure(look.cam, state["exposure"])
                state["reference"] = sky_reference(look.cam.frame(state["exposure"])[0])
                state["metered"] = state["exposure"]
                state["referenced"] = time.time()
                state.setdefault("sky_at", (az, alt))
            # Every look starts at the high sky's exposure; only one that
            # burns out is metered again, here.
            state["exposure"] = state["metered"]
            mosaic, seen = by_day()
            if seen["view"] == "burnt":
                try:
                    state["exposure"], _ = daylight_exposure(look.cam, state["exposure"])
                    mosaic, seen = by_day()
                except interface.Refusal:
                    pass        # too bright even at the shortest exposure: the Sun's glare
            if seen["view"] == "burnt":
                print(f"bearing {az:>5g}°, {alt:>4g}° up: too bright to tell (glare), left out", flush=True)
                log.append(dict({"az": az, "alt": alt, "open": None, "glare": True}, **where))
                return None
            detail = f"{seen['share']:.0%} sky, brightness {seen['level']:.0%} of the high sky"
            if state["exposure"] != state["metered"]:
                detail += f", metered again at {state['exposure'] * 1000:.2g} ms"
        else:
            time.sleep(STEADY)   # let the tube stop shaking
            mosaic, _ = look.cam.frame(state["exposure"])
            lum = luminance(mosaic)
            seen = read_night(skywatch.star_places(lum), lum.shape)
            detail = f"{seen['stars']} stars"
            if torch:
                from camera import WHITE
                level = float(np.median(mosaic))
                starry = seen["view"] != "blocked"
                seen = read_torch(seen, level, float((mosaic >= 0.98 * WHITE).mean()), state.get("dark"))
                if seen["view"] == "unknown" and not seen.get("lit"):
                    # Try harder first: a longer frame shows stars through
                    # thin cloud, where a wall stays starless.
                    longer = min(state["exposure"] * LONGER, LONGEST_S)
                    mosaic, _ = look.cam.frame(longer)
                    lum = luminance(mosaic)
                    again = read_night(skywatch.star_places(lum), lum.shape)
                    if again["view"] != "blocked":
                        seen = dict(again, level=round(float(np.median(mosaic)), 1), longer_s=longer)
                        detail = f"{again['stars']} stars at {longer:g} s"
                if starry and not seen.get("lit"):
                    state["dark"] = min(state.get("dark") or level, level)
                if overcast(alt, seen):
                    raise interface.Refusal(
                        "PLATE_SOLVE_FAILED",
                        f"At bearing {az:g}°, {alt:g}° up the torch lights something and there are no stars, "
                        "which is too high for a tree or a roof: mist in the beam, or the telescope is not "
                        "where the mount says it is. Nothing has been kept. Watch one move to see that the "
                        "tube turns, and try again when the sky is clear.")
                detail += (f", level {level:.0f}: lit by the torch" if seen.get("lit")
                           else f", level {level:.0f}: dark with no stars, cloud or wall" if seen.get("cloud")
                           else f", level {level:.0f}")
                if seen["view"] == "unknown":
                    print(f"bearing {az:>5g}°, {alt:>4g}° up: cannot tell ({detail}), left out", flush=True)
                    log.append(dict({"az": az, "alt": alt, "open": None, "unread": True}, **where))
                    return None
        # The handset saying it went there is not proof: the picture must change.
        turned = moved.separation(*last, az, alt) if last else 0.0
        last[:] = [az, alt]
        watch.check(luminance(mosaic), turned, f"bearing {az:g}°, {alt:g}° up")
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
        log.append(dict({"az": az, "alt": alt, "open": seen["view"] != "blocked"}, **seen, **where))
        print(f"bearing {az:>5g}°, {alt:>4g}° up: {seen['view']} ({detail})", flush=True)
        return answer

    look.log = log
    try:
        cam = Reopening(lambda: Camera(gain=gain))
        try:
            look.cam = cam
            if LOOKS.exists():
                for old in LOOKS.glob("*.jpg"):     # the last survey's pictures
                    old.unlink()
            yield look
        finally:
            cam.close()
    except BaseException:
        scope.stop()
        raise


JAM_TRIES = 4        # frames tried in a row, reopening the camera between, before a survey gives up


class Reopening:
    """The camera, reopened after a frame that never comes (the 183C's jam,
    docs/camera-fault.md) and the frame asked for again, as the imaging runs
    do. 3 November 2026: one jam ended the daylight survey, and the schedule's
    retries were all that brought it back."""

    def __init__(self, opener, say=None, tries=JAM_TRIES):
        self.opener, self.tries = opener, tries
        self.say = say or (lambda text: print(text, flush=True))
        self.cam = opener()

    def frame(self, *args, **kwargs):
        from indi import IndiError
        for attempt in range(self.tries):
            try:
                return self.cam.frame(*args, **kwargs)
            except IndiError as problem:
                if attempt == self.tries - 1:
                    raise
                self.say(f"camera: {problem}; reopening it and trying again")
                self.close()
                self.cam = self.opener()

    def close(self):
        try:
            self.cam.close()
        except Exception:
            pass          # it is being closed whatever it says

    def __getattr__(self, name):
        return getattr(self.cam, name)


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


def lone_openings(found):
    """A bearing open right down to the lowest look between neighbours whose
    tops are well up is taken as blocked to the lower of those tops, in
    doubt, and said. 2 November 2026: 97.5° and 172.5° read open to 20°
    between tops near 40°, the pictures plain blurs, and the person outside
    said neither due east nor due south is open low down: by day a lit wall
    far out of focus reads as sky. `found` maps bearing to top_of()'s answer
    and is changed in place; returns the warnings."""
    warnings = []
    ring = sorted(az for az in found if found[az]["state"] in ("open", "edge"))
    for i, az in enumerate(ring if len(ring) > 2 else ()):
        f, before, after = found[az], found[ring[i - 1]], found[ring[(i + 1) % len(ring)]]
        if f["state"] == "open" and all(n["state"] == "edge" and n["clear"] > f["clear"] + JUMP
                                        for n in (before, after)):
            lower = min(before["clear"], after["clear"])
            warnings.append(f"Bearing {az:g}°: read open down to {f['clear']:g}° between tops at "
                            f"{before['clear']:g}° ({before['az']:g}°) and {after['clear']:g}° "
                            f"({after['az']:g}°): taken as blocked to {lower:g}°, a lit wall being "
                            "likelier than a gap. Look that way yourself.")
            f.update(state="edge", shut=lower, clear=lower, doubt=True, read_open=f["clear"])
    return warnings


def off_meridian(az, margin=30):
    """At least `margin` degrees of bearing from due north and due south."""
    return min(az % 180, 180 - az % 180) >= margin


def is_sky(seen):
    """Whether a look's answer is plain open sky."""
    return seen is not None and not isinstance(seen, float) and bool(seen)


def height(found, low):
    """One number for a bearing's obstruction, to compare neighbours by."""
    return {"open": low, "edge": found["clear"], "blocked": 90}.get(found["state"])


def between(a, b):
    """Degrees round from bearing a to bearing b, going clockwise."""
    return (b - a) % 360 or 360


def trace(look, bearings, low, top=TOP, fine=FINE, known=None, finest=FINEST, most=MOST,
          done=None, checkpoint=None, fill=True):
    """Follow the top of what is in the way round the compass, starting from
    the given bearings and adding more only where the skyline needs them.
    `known` is a skyline measured before (see limit()): each bearing then
    starts at the height it gives, and bearings are added only where this
    survey and that one part company.
    `done` are bearings already measured by a survey cut short (their
    top_of() answers), not measured again; `checkpoint(found)` is called
    after every bearing, so a survey stopped now can carry on later.
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
        if checkpoint:
            checkpoint(found)

    def off(az):
        """What is compared between neighbours: the top itself, or how far it
        is from the skyline already known."""
        return height(found[az], low) - (expected(az) if known else 0)

    # Check 1: sky must be seen high up, or nothing after it means anything.
    high = next((az for az in bearings if is_sky(look(az, top))), None)
    if high is None:
        raise interface.Refusal("NO_SKY", f"No open sky seen even {top}° up. Is the cap off? At night "
                                "this needs a clear sky.")
    found.update({f["az"]: f for f in done or ()})
    for az in bearings:
        if az not in found:
            measure(az)

    # Check 2: more bearings where the skyline is not a straight line between
    # the ones it has: a sudden change between neighbours is a corner, and a
    # top standing off the line through its neighbours is a chimney or a tree.
    while fill and len(found) < most:
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
        if fill:
            warnings.append(f"The skyline is ragged: it stopped adding bearings at {most}. Run it again "
                            "to carry on from this one.")

    # Check 2b: where a look could not be read (glare, or dark with no
    # stars), look again once the rest is done. Cloud drifts and the Sun
    # moves on; a wall is still there.
    log = getattr(look, "log", [])
    unread = {e["az"] for e in log if e.get("glare") or e.get("unread")} & set(found)
    first = len(log)
    for az in sorted(unread, key=side):
        measure(az)
    still = sorted({e["az"] for e in log[first:] if e.get("glare") or e.get("unread")})
    for e in log[:first]:
        if (e.get("glare") or e.get("unread")) and e["az"] not in still:
            e["resolved"] = True        # read the second time: not counted against the survey
    if unread:
        warnings.append(f"Looked again where it could not tell ({len(unread)} bearing(s)); "
                        + (f"still unread at {', '.join(f'{az:g}°' for az in still)}: kept as not measured."
                           if still else "all read the second time."))

    warnings += lone_openings(found)

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
    # A bearing well off the meridian: on it the mount may come at the same
    # place from either side of the pole, and the two sides point degrees
    # apart (2 November 2026: due north read blocked at 72° and later sky).
    measured = [az for az in bearings if found[az]["state"] in ("open", "edge") and "read_open" not in found[az]]
    first = next((found[az] for az in measured if off_meridian(az)),
                 found[measured[0]] if measured else None)
    if first and first.get("in_view"):
        again = look(first["az"], first["clear"])
        same = isinstance(again, float) and abs(again - first["clear"]) <= 1
    elif first:
        again = look(first["az"], first["clear"])
        if isinstance(again, float):
            # The top in view this time: the same answer if it lies where the
            # first time put it, between the highest blocked look and the
            # lowest clear one (3 November 2026: "sky at 33°, blocked at 30°"
            # and then "the top at 32.7°" were called different, at 165°
            # and twice at 30°).
            same = (first.get("shut") or first["clear"] - 1) - 1 <= again <= first["clear"] + 1
        else:
            same = is_sky(again) and \
                (first["state"] != "edge" or look(first["az"], first["shut"]) in (False, np.False_))
    if first and not same and not slipped(log, first["az"]):
        # The mount's axes came back alike: no slip seen, though that proves
        # the mechanics, not the optics. That bearing, unrepeatable, keeps what
        # the skyline in use says; the rest stands (3 November 2026: one
        # recheck at 30°, an edge then sky with the axes alike, set a whole
        # survey of 136 looks aside).
        f = found[first["az"]]
        f.update(state="unreachable", unrepeatable=True)
        warnings.append(f"Bearing {first['az']:g}° read differently the second time, with the mount's axes "
                        "alike (no slip seen; the light, or the reading of a top at the look's own height): "
                        "unrepeatable, left as the skyline in use has it.")
    elif first and not same:
        sides = {e.get("over") for e in log if e["az"] == first["az"] and "over" in e}
        why = (" The tube came at it from the other side of the pole the second time, and the mount's "
               "pointing differs between the sides." if len(sides) > 1 else
               " Did the mount slip, or the light change?")
        warnings.append(f"{NOT_SAME} Going back to bearing {first['az']:g}° gave a different answer "
                        "from the first time." + why)
    return [found[az] for az in sorted(found)], warnings


SLIP_DEG = 1.0      # axes this far apart for one bearing and height: the mount is not where it was


def slipped(log, az):
    """Whether the mount's axes disagree between two looks at one bearing and
    height (the first look and the recheck), or cannot say (not recorded)."""
    looks = [e for e in log if e["az"] == az and e.get("axes")]
    if len(looks) < 2:
        return True
    last = looks[-1]
    same = [e for e in looks[:-1] if abs(e["alt"] - last["alt"]) <= 1]
    if not same:
        return True
    a, b = same[0]["axes"], last["axes"]
    return any(abs((x - y + 180) % 360 - 180) > SLIP_DEG for x, y in zip(a, b))


def resumable(daylight, path=None, now=None):
    """What a survey cut short today had measured: (its top_of() answers,
    its looks), or None. Only the same kind of survey, within RESUME_S."""
    try:
        saved = json.loads(Path(path or PARTIAL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if saved.get("daylight") != daylight or (now or time.time()) - saved.get("saved", 0) > RESUME_S:
        return None
    return saved.get("found") or None, saved.get("looks", [])


def keep_partial(found, looks, daylight, path=None):
    records.write(Path(path or PARTIAL), {"saved": time.time(), "daylight": daylight,
                                          "found": list(found.values()), "looks": looks},
                  default=lambda o: o.item() if hasattr(o, "item") else str(o))


TRUSTED_GUESS = 2.0     # degrees: a correction borrowed from the other side is trusted by day up to this


def aim_doubt(steady, error, measured, daylight):
    """Why a look's aim cannot be trusted, or None. By day nothing checks the
    pointing, so a correction never plate-solved on the side the tube is on
    (borrowed from the other side, reversed) is a guess, trusted only when
    small; and a tube that changed sides again is not where it was sent."""
    if not steady:
        return "the tube changed sides twice; aim not trusted"
    if daylight and not measured and abs(error[1]) > TRUSTED_GUESS:
        return (f"this side's pointing correction ({error[1]:+.1f}° in Dec) was never plate-solved "
                "on this side; aim not trusted")
    return None


def skyline_from(found, low, known=None):
    """A trace as a skyline (see limit()). With a skyline known before, its
    points are kept, each moved by what this survey found near it, so the
    detail a panorama gave survives a check by the telescope."""
    points, unmeasured = [], []
    for f in found:
        top = height(f, low)
        if top is None:
            # Not measured (out of the mount's reach, or the Sun's glare) is
            # not open: left out, it took its neighbours' height, so a
            # bearing nobody saw read as clear sky. What an earlier skyline
            # says of it stands, marked not rechecked; with none, blocked.
            unmeasured.append(f["az"])
            continue
        point = {"az": f["az"], "alt": top, "by": "telescope"}
        if f["state"] == "open":
            point.update(alt=f["clear"], open=True)
        if "read_open" in f:
            # Already put at its neighbours' lower top: no further margin.
            point["by"] = f"telescope: read open to {f['read_open']:g}°, put at its neighbours' lower top"
        elif f.get("doubt"):
            point["extra"] = CLEARANCE
        points.append(point)
    if not known:
        points += [{"az": az, "alt": 90.0, "unmeasured": True, "by": "nothing: not measured"} for az in unmeasured]
        points.sort(key=lambda p: p["az"])
    # Where neighbours differ by a corner's worth, the corner is somewhere
    # between them: count the whole gap as blocked to the higher of the two.
    for a, b in zip(list(points), points[1:] + points[:1]):
        if len(points) > 1 and abs(a["alt"] - b["alt"]) > JUMP:
            lower, at = (a, a["az"] + 0.1) if a["alt"] < b["alt"] else (b, b["az"] - 0.1)
            corner = {"az": round(at % 360, 1), "alt": max(a["alt"], b["alt"]),
                      "by": "a corner between two looks, put at the higher"}
            # Between two open bearings nothing was seen at all: they differ
            # only in how low the limits let each look (on 19 October 2026,
            # 20° at 180° and 30° at 225° before 17:00 UTC), and a corner
            # there marked blocked made up a wall at 30°.
            if a.get("open") and b.get("open"):
                corner["open"] = True
            points.append(corner)
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
                points.append({"az": p["az"], "alt": round(float(limit(looked, [p["az"]])[0]), 1),
                               "by": "telescope, between looks"})
            elif not near(p["az"]):
                moved_by = float(limit(shifts, [p["az"]])[0])
                points.append(dict(p, alt=round(p["alt"] + moved_by, 1),
                                   by=f"earlier skyline, moved {moved_by:+.1f}° by the looks nearby"))
        for az in unmeasured:
            here = [p for p in known if min(between(az, p["az"]), between(p["az"], az)) % 360 < FINEST]
            if here and not any(p.get("unseen") for p in here):
                points.append({"az": az, "alt": round(float(limit(known, [az])[0]), 1),
                               "by": "earlier skyline, not rechecked"})
            else:
                points.append({"az": az, "alt": 90.0, "unmeasured": True, "by": "nothing: not measured"})
    return sorted(points, key=lambda p: p["az"])


EYE_DOUBT = JUMP     # degrees above a skyline a person checked by eye before a survey is doubted


TRUST = {"inferred": 1, "telescope": 2, "eye": 3}


def in_spans(az, spans):
    """Whether a bearing lies in one of the spans a person checked by eye."""
    return any(within(az, (s["from"], s["to"])) for s in spans or [])


def trust(point, spans=None):
    """How much stands behind one skyline point: "eye" inside a span a person
    checked, else the point's own "trust" as kept with it: "telescope" for a
    top the telescope looked at, "inferred" for anything put there from
    other points. Only a point saved before trust was kept is judged from
    its description."""
    if in_spans(point["az"], spans):
        return "eye"
    if point.get("trust") in TRUST:
        return point["trust"]
    by = str(point.get("by", "telescope"))
    if by.startswith("telescope") and not by.startswith("telescope, between"):
        return "telescope"
    return "inferred"


def trust_at(old, az, spans=None):
    """The trust behind the skyline's height at a bearing: a point there, or
    the weaker of the two points the height is drawn between. Trust is not
    drawn between points as height is (an inferred corner next to a measured
    top does not borrow the top's)."""
    if in_spans(az, spans):
        return "eye"
    points = sorted(old, key=lambda q: q["az"])
    here = [q for q in points if abs((q["az"] - az + 180) % 360 - 180) < 0.05]
    if here:
        return trust(here[0])
    before = max((q for q in points if q["az"] < az), key=lambda q: q["az"], default=points[-1])
    after = min((q for q in points if q["az"] > az), key=lambda q: q["az"], default=points[0])
    return min(trust(before), trust(after), key=TRUST.get)


READINGS_KEPT = 5     # a point's last readings, kept to settle a disagreement


def altitudes(readings):
    """A point's readings as (altitude, survey) pairs, the last from each
    survey only: readings from one survey are not independent of each
    other. Plain numbers (kept before surveys were named) count apart."""
    pairs = [(r["alt"], r.get("survey")) if isinstance(r, dict) else (float(r), None) for r in readings or []]
    last = {}
    for i, (alt, survey) in enumerate(pairs):
        last[survey if survey is not None else f"#{i}"] = (i, alt)
    return [alt for _, alt in sorted(last.values())]


def settle(readings, by=EYE_DOUBT):
    """(estimate, agreed): the reading most of a point's readings agree with
    (within `by`), the newest of the largest group on a tie, and whether two
    or more agree on it and outnumber any other group. One reading per
    survey counts (altitudes())."""
    readings = altitudes(readings)
    groups = [[r for r in readings if abs(r - x) <= by] for x in readings]
    sizes = [len(g) for g in groups]
    best = max(range(len(readings)), key=lambda i: (sizes[i], i))
    others = max((sizes[i] for i in range(len(readings)) if abs(readings[i] - readings[best]) > by), default=0)
    return round(float(np.median(groups[best])), 1), sizes[best] >= 2 and sizes[best] > others


def reconcile(skyline, kept, by=EYE_DOUBT, survey=None):
    """(skyline, differ): a new survey's points weighed against the skyline
    in use, point by point, never replaced wholesale. Less trust never
    replaces more (an inferred point never moves a measured one, a survey
    never overrules a person's eye); more replaces less. Two alike keep
    their readings: within `by` the newer is used; further apart, the
    planner gets the higher, the safe one, until two readings agree with
    each other and outnumber the rest, and then those win, so a wrong top
    is overturned by later surveys rather than kept for good. Each point
    keeps "alt" (what the planner uses), "estimate" (the best guess at the
    real top), its last "readings" and its "trust". `differ` lists the
    points more than `by` apart ({"az", "read", "was", "kept"}).
    3 November 2026: glare due south read a wall above 75°, and at midday a
    sunlit white wall in the west read as sky down to 20°."""
    old = (kept or {}).get("skyline") or []
    spans = (kept or {}).get("checked_spans") or []
    if not old:
        return [dict(q, trust=trust(q), estimate=q["alt"], readings=[{"alt": q["alt"], "survey": survey}])
                for q in skyline], []
    out, differ = [], []
    for q in skyline:
        was = round(float(limit(old, [q["az"]])[0]), 1)
        theirs_name = trust_at(old, q["az"], spans)
        mine, theirs = TRUST[trust(q)], TRUST[theirs_name]
        here = [p for p in old if abs((p["az"] - q["az"] + 180) % 360 - 180) < 0.05]
        # Readings build up on the nearest point within half a step: a
        # survey that adds bearings where the skyline bends lands a little
        # differently each time (3 November 2026: corners at 44.9° and 52.4°).
        close = sorted((p for p in old if abs((p["az"] - q["az"] + 180) % 360 - 180) <= FINEST / 2),
                       key=lambda p: abs((p["az"] - q["az"] + 180) % 360 - 180))
        before = list((close[0].get("readings") if close else None) or [{"alt": was, "survey": None}])
        reading = {"alt": q["alt"], "survey": survey}
        apart = abs(q["alt"] - was) > by
        if mine < theirs:
            point = dict(here[0]) if here else {"az": q["az"], "alt": was, "estimate": was, "readings": before}
            point.update(trust=theirs_name, by=f"kept ({theirs_name}); this survey read {q['alt']:g}°")
            kept_as = "the one in use"
        elif mine > theirs or not apart:
            readings = ([reading] if mine > theirs else before + [reading])[-READINGS_KEPT:]
            point = dict(q, trust=trust(q), estimate=settle(readings, by)[0], readings=readings)
            kept_as = "this survey's"
        else:
            readings = (before + [reading])[-READINGS_KEPT:]
            estimate, agreed = settle(readings, by)
            safe = estimate if agreed else max(was, q["alt"])
            point = dict(q, alt=safe, estimate=estimate, readings=readings, trust=trust(q),
                         by=f"telescope: readings {', '.join(f'{r:g}' for r in altitudes(readings))}; "
                            + ("settled" if agreed else "not settled, the higher used"))
            point.pop("open", None) if safe != q["alt"] else None
            kept_as = "settled" if agreed else "the higher"
        out.append(point)
        if apart:
            differ.append({"az": q["az"], "read": q["alt"], "was": was, "kept": kept_as})
    return out, differ


def compare(before, after, low, margin, step=FINEST):
    """Rows (bearing, usable from before, after) wherever what the planner
    may use changes by more than half a degree."""
    rows = []
    for az in np.arange(0, 360, step / 2):
        a = round(max(float(limit(before, [az], margin)[0]), low), 1)
        b = round(max(float(limit(after, [az], margin)[0]), low), 1)
        if abs(a - b) > 0.5:
            rows.append((float(az), a, b))
    return rows


def print_compare(rows):
    if not rows:
        print("The planner's usable skyline does not change.")
        return
    print("Where the planner's usable skyline changes (usable from, before -> after):")
    for az, a, b in rows:
        print(f"  {az:>6g}°  {a:>5.1f}° -> {b:>5.1f}°  {'lower' if b < a else 'higher'}")


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
        # Only the words for this bearing's state: a bearing blocked as far
        # up as it looked has no top to print.
        words = (f"open down to {f['clear']:g}°" if f["state"] == "open" else
                 f"blocked up to {f['clear']:g}°" if f["state"] == "edge" else
                 "blocked as far up as it looked" if f["state"] == "blocked" else "not reachable")
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
    ap.add_argument("--torch", action="store_true",
                    help="by night, with a torch fixed along the tube: what it lights is in the way; "
                         "a dark frame with no stars cannot be told and is left out")
    ap.add_argument("--fresh", action="store_true", help="with --trace: do not start from the skyline already measured")
    ap.add_argument("--show", action="store_true", help="print the skyline in use; nothing moves")
    ap.add_argument("--move-from", metavar="SPOT",
                    help="work this spot's skyline out from SPOT's measured one, until it is surveyed; nothing moves")
    ap.add_argument("--offset", nargs=2, type=float, metavar=("METRES", "BEARING"),
                    help="with --move-from: where this spot is from SPOT")
    ap.add_argument("--distances", nargs="+", metavar="FROM-TO:METRES",
                    help="with --move-from: how far the things in the way are from SPOT, by bearing, "
                         "e.g. 270-330:4 330-60:12 60-200:15 200-270:20")
    ap.add_argument("--forget", action="store_true", help="throw the measured skyline away; nothing moves")
    ap.add_argument("--use-aside", metavar="FILE",
                    help="keep a survey that was set aside, once a person has checked what it doubted; nothing moves")
    ap.add_argument("--only", metavar="AZ,AZ,...",
                    help="with --trace: look again at these bearings only, adding none, and change the skyline "
                         "in use only there")
    ap.add_argument("--check-span", action="store_true",
                    help="with --bearings and --checked: mark the skyline in use there as checked by eye, "
                         "so no survey replaces it there; nothing moves")
    ap.add_argument("--bearings", metavar="FROM-TO",
                    help="with --use-aside: take only these bearings (clockwise, as 225-262.5) from the "
                         "set-aside survey into the skyline in use")
    ap.add_argument("--checked", metavar="WHAT",
                    help="with --use-aside: what the person saw, in their words (kept with the skyline)")
    ap.add_argument("--exposure", type=float, help="seconds (default 1; by day it is found from the sky)")
    ap.add_argument("--gain", type=int, help="default 2000, or 100 by day")
    ap.add_argument("--dry-run", action="store_true", help="say where it would look; no camera, no mount")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    name = "horizon.show" if args.show else "horizon.forget" if args.forget else \
        "horizon.use_aside" if args.use_aside else \
        "horizon.move" if args.move_from else \
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


def span(text):
    """(from, to) bearings from "FROM-TO", or None."""
    if not text:
        return None
    try:
        a, b = (float(v) for v in text.split("-"))
    except ValueError:
        raise interface.Refusal("INVALID_REQUEST", f"--bearings takes FROM-TO in degrees, as 225-262.5, not {text!r}.")
    return a % 360, b % 360


def within(az, bearings):
    a, b = bearings
    return (az - a) % 360 <= (b - a) % 360


def edges(old, taken, bearings):
    """Points just outside each end of a span taken into a skyline, at the
    higher of the two tops meeting there, so the join opens no gap that
    neither skyline saw (as a corner between two looks is put)."""
    out = []
    for end, outward in ((bearings[0], -0.1), (bearings[1], 0.1)):
        inside = float(limit(taken, [end])[0])
        outside = float(limit(old, [(end + outward) % 360])[0])
        out.append({"az": round((end + outward) % 360, 1), "alt": round(max(inside, outside), 1),
                    "by": "a corner where a taken span meets the skyline in use, put at the higher",
                    "trust": "inferred"})
    return out


def check_span(bearings, checked, low, margin):
    """Mark the skyline in use between two bearings as checked by a
    person's eye, as it stands: no survey replaces it there."""
    current = measured()
    if not current or not bearings or not checked:
        raise interface.Refusal("INVALID_REQUEST", "--check-span needs a skyline in use, --bearings FROM-TO "
                                "and --checked \"what you saw\".")
    spans = list(current.get("checked_spans") or []) + [{"from": bearings[0], "to": bearings[1], "words": checked}]
    current["checked_spans"] = spans
    records.write(RESULTS, current)
    print(f"{bearings[0]:g}-{bearings[1]:g}° marked as checked by eye: {checked}.")
    return {"checked_spans": spans}


def use_aside(path, checked, low, margin, bearings=None, dry_run=False):
    """Keep a survey that was set aside, now that a person has looked at
    what it doubted. Its first answer at each bearing stands, and a lone
    opening is put at its neighbours' lower top as a survey now would.
    2 November 2026: the afternoon survey's repeat look at due north read
    sky where its first had read blocked; the person outside said the house
    is due north, and that due east and due south are not open low down."""
    if not checked:
        raise interface.Refusal("INVALID_REQUEST", "Say what was checked by eye, with --checked \"...\": a set-aside "
                                "survey is only kept on a person's word about what it doubted.")
    if not path.exists():
        path = RESULTS.parent / path.name
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        found = {f["az"]: f for f in saved["trace"]}
    except (OSError, ValueError, KeyError, TypeError):
        raise interface.Refusal("INVALID_REQUEST", f"{path} is not a survey set aside by ./horizon.py --trace.")
    warnings = list(saved.get("warnings", [])) + lone_openings(found)
    trace_now = [found[az] for az in sorted(found)]
    skyline = skyline_from(trace_now, low)
    if bearings:
        # Only those bearings, on the person's word; the rest as it is in use.
        current = measured()
        if not current:
            raise interface.Refusal("INVALID_REQUEST", "No skyline is in use to take bearings into.")
        taken = [dict(p, trust="eye", by=f"{p.get('by', 'telescope')}; taken from {path.name} on the word: {checked}")
                 for p in skyline if within(p["az"], bearings)]
        if not taken:
            raise interface.Refusal("INVALID_REQUEST", f"{path.name} has nothing between {bearings[0]:g}° and "
                                    f"{bearings[1]:g}°.")
        skyline = sorted([p for p in current["skyline"] if not within(p["az"], bearings)] + taken
                         + edges(current["skyline"], taken, bearings), key=lambda p: p["az"])
        spans = list(current.get("checked_spans") or []) + [{"from": bearings[0], "to": bearings[1], "words": checked}]
        print_compare(compare(current["skyline"], skyline, low, margin))
        if dry_run:
            print("Dry run: nothing kept.")
            return {"would_take": len(taken), "changes": compare(current["skyline"], skyline, low, margin)}
        words = "; ".join(w for w in (current.get("checked_by_eye"), f"{bearings[0]:g}-{bearings[1]:g}°: {checked}") if w)
        kept = keep(skyline, current.get("source", "telescope"), looks=current.get("looks", []),
                    warnings=current.get("warnings", []), trace=current.get("trace", []),
                    blocked=current.get("blocked", []), checked_by_eye=words, checked_spans=spans)
        print(f"Took {len(taken)} point(s) at {bearings[0]:g}-{bearings[1]:g}° from {path.name}, on the word: "
              f"{checked}. The rest of the skyline in use is unchanged.")
        return dict({k: v for k, v in kept.items() if k not in ("saved", "looks", "trace")},
                    usable=usable(skyline, low, margin))
    kept = keep(skyline, "telescope", looks=saved.get("looks", []), warnings=warnings, trace=trace_now,
                blocked=skyline_blocked(trace_now), checked_by_eye=checked, was_set_aside=path.name,
                set_aside_because=saved.get("not_used_because"))
    print("\n" + profile(trace_now, low))
    for warning in warnings:
        print(f"\nCHECK: {warning}")
    print(f"\nKept from {path.name}, on the word: {checked}. The planner uses it from now on, raised by "
          f"{margin:g}°.")
    return dict({k: v for k, v in kept.items() if k not in ("saved", "looks")}, usable=usable(skyline, low, margin))


def move_from(spot, offset, distances, low, margin):
    """This spot's skyline from another spot's, by `moved`, kept for the
    planner until a survey from here replaces it."""
    if not config.SPOT or spot == config.SPOT:
        raise interface.Refusal("INVALID_REQUEST", "Name where the telescope stands first (./ty spot NAME), "
                                                   "and move from a different spot.")
    if not offset or not distances:
        raise interface.Refusal("INVALID_REQUEST", "--move-from needs --offset METRES BEARING and --distances.")
    source = config.DATA / "cache" / f"horizon-{spot}.json"
    try:
        old = json.loads(source.read_text(encoding="utf-8"))["skyline"]
    except (OSError, ValueError, KeyError):
        raise interface.Refusal("INVALID_REQUEST", f"{spot} has no measured skyline to move from.")
    stretches = []
    for text in distances:
        try:
            span, metres = text.split(":")
            lo, hi = span.split("-")
            stretches.append((float(lo), float(hi), float(metres)))
        except ValueError:
            raise interface.Refusal("INVALID_REQUEST", f"A distance is FROM-TO:METRES, e.g. 270-330:4: not {text!r}.")
    skyline = moved(old, offset[0], offset[1], stretches)
    warning = (f"Worked out from {spot}'s skyline, {offset[0]:g} m away at {offset[1]:g}°, with distances "
               f"guessed by eye; {MOVED_DOUBT:g}° of doubt added. Survey from here by daylight to replace it.")
    keep(skyline, f"moved from {spot}", warnings=[warning], offset_m=offset[0], offset_bearing=offset[1],
         distances=[{"from": a, "to": b, "metres": m} for a, b, m in stretches])
    print(f"{config.SPOT}: skyline worked out from {spot}'s.\n\n{picture_of(skyline, low, margin)}\n\nCHECK: {warning}")
    return {"spot": config.SPOT, "from": spot, "skyline": skyline, "usable": usable(skyline, low, margin)}


def run(args):
    cfg = config.load() if config.FILE.exists() else config.example()
    site, low, margin = cfg["site"], cfg["horizon"]["min_altitude"], cfg["horizon"]["margin"]
    if args.show:
        return show(low, margin, cfg["horizon"]["use_survey"])
    if args.move_from:
        return move_from(args.move_from, args.offset, args.distances, low, margin)
    if args.use_aside:
        return use_aside(Path(args.use_aside), args.checked, low, margin, span(args.bearings), args.dry_run)
    if args.check_span:
        return check_span(span(args.bearings), args.checked, low, margin)
    if args.forget:
        had = bool(measured())
        if RESULTS.exists():
            RESULTS.unlink()
        print("The measured skyline is forgotten." if had else "There was no measured skyline.")
        return {"forgotten": had}
    step = args.step or 30
    bearings = sorted(range(0, 360, step), key=side)
    if args.only:
        if not args.trace:
            raise interface.Refusal("INVALID_REQUEST", "--only goes with --trace.")
        try:
            bearings = sorted({float(v) % 360 for v in args.only.split(",")}, key=side)
        except ValueError:
            raise interface.Refusal("INVALID_REQUEST", f"--only takes bearings in degrees, as 30,45,165: not {args.only!r}.")
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
    earlier = None if args.fresh or args.only else resumable(args.daylight) if args.trace else None
    if args.only and not known:
        raise interface.Refusal("INVALID_REQUEST", "--only looks again at bearings of a skyline in use; there is none.")
    if args.fresh and PARTIAL.exists():
        PARTIAL.unlink()
    with eye(site, exposure, gain, args.daylight, args.torch and not args.daylight) as look:
        if args.trace:
            done = None
            if earlier and earlier[0]:
                done, looked = earlier
                look.log[:0] = looked
                print(f"Carrying on from the survey cut short earlier today: {len(done)} bearing(s) "
                      "already measured are not looked at again (--fresh starts over).", flush=True)
            import activity
            # Says so, so the stream stays off air for it (director.py).
            with activity.doing("Surveying the skyline", "by daylight" if args.daylight else "by night"):
                found, warnings = trace(look, bearings, low, known=known, done=done,
                                        checkpoint=lambda found: keep_partial(found, look.log, args.daylight),
                                        fill=not args.only)
            if PARTIAL.exists():
                PARTIAL.unlink()        # finished: nothing to carry on from
        else:
            if args.daylight:
                # Sky high up first, so the exposure is set on sky and not on a wall.
                if not any(look(az, TOP) for az in bearings):
                    raise interface.Refusal("NO_SKY", f"No open sky seen {TOP}° up. Is the cap off?")
            sweep(look, step)
        results = look.log
    if args.trace:
        blind = glare_share(results)
        unrepeatable = [w for w in warnings if w.startswith(NOT_SAME)]
        if blind > GLARE_MOST or unrepeatable:
            # Kept for looking into, never in place of the skyline in use.
            aside = set_aside(skyline_from(found, low, known), unrepeatable[0] if unrepeatable else
                              f"{blind:.0%} of looks unread", looks=results, warnings=warnings, trace=found)
            if unrepeatable:
                raise interface.Refusal(
                    "PLATE_SOLVE_FAILED", f"{unrepeatable[0]} Nothing has replaced the skyline in use; this "
                    f"survey is in {aside.name} to look into.")
            raise interface.Refusal(
                "NO_SKY", f"(kept to look into as {aside.name}) {blind:.0%} of the looks could not be read (the Sun's glare by day, cloud or an "
                "unlit wall by night): nothing has been kept. By day, survey with the Sun higher and behind "
                "the telescope or under an even overcast; by night, on a clear one.")
        to_top = [f["az"] for f in found if f["state"] == "blocked" and (f.get("shut") or 0) >= TOP]
        if to_top:
            warnings.append("Blocked as far up as it looked at " + ", ".join(f"{az:g}°" for az in to_top)
                            + f": a wall to {TOP}° is possible, but so is a telescope aimed somewhere else. "
                            "Look that way yourself.")
        measured_now = skyline_from(found, low, known)
        survey = time.strftime("%Y%m%d-%H%M")
        if args.only:
            # Only the bearings looked at, as the telescope measured them;
            # everything else stays exactly as it is in use.
            looked = [float(b) for b in bearings]
            near = lambda az: any(abs((az - b + 180) % 360 - 180) <= FINEST / 2 for b in looked)
            measured_now = [q for q in measured_now if near(q["az"]) and trust(q) == "telescope"]
            redone, differ = reconcile(measured_now, kept, survey=survey)
            skyline = sorted([p for p in known if not any(abs((p["az"] - q["az"] + 180) % 360 - 180) < 0.05
                                                           for q in redone)] + redone, key=lambda p: p["az"])
        else:
            skyline, differ = reconcile(measured_now, kept, survey=survey)
        more = {k: kept[k] for k in ("checked_by_eye", "checked_spans") if kept.get(k)}
        if differ:
            # The whole survey kept aside too, so a bearing a person has
            # looked at can be taken from it (--use-aside FILE --bearings).
            aside = set_aside(measured_now, f"differs from the skyline in use at {len(differ)} point(s)",
                              looks=results, warnings=warnings, trace=found, differ=differ)
            more.update(differ=differ, survey_file=aside.name)
            warnings.append(
                f"More than {EYE_DOUBT:g}° from the skyline in use at "
                + ", ".join(f"{d['az']:g}° (read {d['read']:g}°, was {d['was']:g}°: {d['kept']} kept)" for d in differ)
                + f". Once you have looked, take bearings from it with ./horizon.py --use-aside {aside.name} "
                "--bearings FROM-TO --checked \"what you saw\" (--dry-run first shows the change).")
        source = "telescope" if not known or kept["source"] == "telescope" else "panorama+telescope"
        saved = keep(skyline, source, looks=results, warnings=warnings, trace=found,
                     blocked=skyline_blocked(found), **more)
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
    records.write(RESULTS, saved)
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
