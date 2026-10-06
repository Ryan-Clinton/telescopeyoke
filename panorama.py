#!/usr/bin/env python3
"""The skyline from a phone panorama: what blocks the sky, without moving the mount.

    ./panorama.py use garden.jpg             find the skyline in a panorama
    ./panorama.py mark 0.31 0.42 137 24      that point in it is at bearing 137°, 24° up
    ./panorama.py mark 0.31 0.42 --landmark chimney     ...is a landmark landmark.py remembers
    ./panorama.py mark 0.31 0.42 --telescope            ...is what the telescope points at now
    ./panorama.py move 0.50,0.38 0.52,0.36   put the skyline right where it was found wrongly
    ./panorama.py also higher.jpg            a second panorama, from another height
    ./panorama.py show                       where things stand, and the picture marked up
    ./panorama.py save                       keep the skyline for the planner
    ./panorama.py unmark 2  |  ./panorama.py clear

Stand where the telescope stands, hold the phone at the height of the tube,
and take a panorama of the skyline: tilted up enough that the sky is above
everything, and round as much of the compass as you can. Nothing here moves
the mount, and it takes a few minutes.

"use" finds the skyline: sky is grown outwards from what is surely sky (blue,
or the brightest smooth parts) and stops at edges, and the line under it is
the one that bends least. It is a first try. A pale smooth wall can pass for
sky, so look at the picture it writes and put right what is wrong with
"move", or by drawing over it on the application's Horizon screen.

The picture says how high things are in pixels; two marks tie it to the
compass. A mark is a point in the picture whose bearing and height are
known: best, something the telescope is pointing at (--telescope reads the
mount; nothing moves), or a landmark already remembered. Marks less than
half a turn apart, please, and the further apart the better. A panorama is
taken as a strip round a cylinder: bearing runs evenly across it, and height
follows from the same scale. With three marks or more it says how well they
agree.

A point is given as a share of the picture, 0 to 1 across and 0 to 1 down
from the top, or in pixels of the picture as it was given.

Things close by sit differently against the sky from another height. "also"
takes a second and third panorama, from above and below the tube; each needs
its own two marks (--picture 2). Where their skylines differ from the first
one's, that much doubt is added there. The first picture is the one that
counts: make it the one taken nearest the height of the tube.

The pictures are kept in horizon/ beside the other data, never in the
repository: they show the garden.
"""
import argparse
import json
import math
import time

import numpy as np
from PIL import Image, ImageDraw

import config
import horizon
import interface

FOLDER = config.DATA / "horizon"
STATE = FOLDER / "panorama.json"
MARKED = FOLDER / "skyline.jpg"     # the picture in use with its skyline drawn on
KEPT_WIDTH = 2400       # pixels across the copy that is kept and shown
WORK_WIDTH = 1200       # and across the one the skyline is looked for in
POINTS = 120            # points the skyline is kept as, across the picture
EDGE = 7.0              # a change of this much from one pixel to the next is not sky (of 255)
BLUE = 1.15             # blue over red that only sky has
STIFF = 2.0             # what a pixel's step up or down costs the line, in pixels wrongly called
MOST = 3                # pictures: the one that counts and two from other heights
DOUBT = 10.0            # degrees: the most doubt another height's picture may add


# --- finding the skyline in a picture --------------------------------------------

def sky_in(rgb):
    """Which pixels are sky, True or False. Sky is smooth, so the picture is
    cut up along its edges; a smooth piece is sky if most of it is blue or
    among the brightest tenth of the picture. A wall is smooth too, but the
    roof's edge parts it from the sky and it is neither."""
    from scipy import ndimage
    soft = np.dstack([ndimage.gaussian_filter(rgb[..., i].astype(np.float32), 1.0) for i in range(3)])
    lum = soft.mean(axis=2)
    slope = np.sqrt(sum(ndimage.sobel(soft[..., i], axis) ** 2 for i in range(3) for axis in (0, 1))) / 8
    calm = slope < EDGE
    sure = calm & ((soft[..., 2] / np.maximum(soft[..., 0], 1) > BLUE) | (lum > np.percentile(lum, 92)))
    pieces, count = ndimage.label(calm)
    if not count:
        return np.zeros(lum.shape, bool)
    size = ndimage.sum(np.ones_like(lum), pieces, range(1, count + 1))
    hits = ndimage.sum(sure, pieces, range(1, count + 1))
    keep = np.zeros(count + 1, bool)
    keep[1:] = (hits > 0.5 * size) & (size > 50)
    return ndimage.binary_closing(keep[pieces], iterations=2)


def line_under(sky, stiff=STIFF):
    """The row the skyline is at in each column: sky above it, not below, and
    as few steps up and down as that allows. 0 means nothing but obstruction,
    right to the top of the picture."""
    chance = np.clip(sky.astype(np.float32), 0.02, 0.98)
    rows, cols = chance.shape
    nothing = np.zeros((1, cols), np.float32)
    # What it costs to put the line at each row: not-sky above it, sky below.
    cost = np.vstack([nothing, np.cumsum(1 - chance, axis=0)]) + \
        np.vstack([np.cumsum(chance[::-1], axis=0)[::-1], nothing])
    best, came = cost[:, 0].copy(), np.zeros((rows + 1, cols), np.int32)
    steps = np.arange(rows + 1)
    for c in range(1, cols):
        # The cheapest way to each row from the column before, a step at a time.
        reach, source = best.copy(), steps.copy()
        for r in range(1, rows + 1):
            if reach[r - 1] + stiff < reach[r]:
                reach[r], source[r] = reach[r - 1] + stiff, source[r - 1]
        for r in range(rows - 1, -1, -1):
            if reach[r + 1] + stiff < reach[r]:
                reach[r], source[r] = reach[r + 1] + stiff, source[r + 1]
        came[:, c], best = source, reach + cost[:, c]
    line = np.zeros(cols, np.int32)
    line[-1] = int(np.argmin(best))
    for c in range(cols - 1, 0, -1):
        line[c - 1] = came[line[c], c]
    return line


def skyline_in(image, points=POINTS):
    """The skyline of a picture as points [across, down], each a share of the
    picture from 0 to 1. Each point speaks for a strip of the picture and
    takes the highest thing in it."""
    small = image.convert("RGB")
    small.thumbnail((WORK_WIDTH, WORK_WIDTH))
    line = line_under(sky_in(np.asarray(small)))
    strips = np.array_split(np.arange(small.width), min(points, small.width))
    return [[round(float(s.mean() + 0.5) / small.width, 4), round(float(line[s].min()) / small.height, 4)]
            for s in strips]


# --- tying a picture to the compass ----------------------------------------------

def fit(marks, width, height):
    """How a picture's points turn into bearings and heights, from its marks.
    Returns {"per_pixel", "az0", "row0", "worst"}: degrees of bearing per pixel
    across, the bearing at the left edge, the row the true horizon is at, and
    how far the worst mark's height is from where the others put it."""
    if len(marks) < 2:
        raise interface.Refusal("INVALID_REQUEST", "It takes two marks to tie a picture to the compass: "
                                f"this one has {len(marks)}.")
    xs = np.array([m["x"] * width for m in marks])
    # Bearings as they run across the picture, each the short way from the first.
    turns = np.array([(m["az"] - marks[0]["az"] + 180) % 360 - 180 for m in marks])
    if np.ptp(xs) < 0.02 * width:
        raise interface.Refusal("INVALID_REQUEST", "The marks are almost above one another: they say how "
                                "high things are but not how wide the picture is. Mark something further along.")
    per_pixel, at_left = np.polyfit(xs, turns, 1)
    if abs(per_pixel) * width < 20 or abs(per_pixel) * width > 400:
        raise interface.Refusal("INVALID_REQUEST", f"By these marks the picture is {abs(per_pixel) * width:.0f}° "
                                "wide, which no panorama is. Check their bearings.")
    # Round a cylinder: the same scale up and down as across, through a tangent.
    radius = 1 / math.radians(abs(per_pixel))
    rows = [m["y"] * height + radius * math.tan(math.radians(m["alt"])) for m in marks]
    row0 = float(np.mean(rows))
    worst = max(abs(m["alt"] - math.degrees(math.atan((row0 - m["y"] * height) / radius))) for m in marks)
    return {"per_pixel": float(per_pixel), "az0": float(marks[0]["az"] + at_left) % 360, "row0": row0,
            "worst": round(worst, 1)}


def placed(picture):
    """A picture's skyline as bearings and heights: a list of {"az", "alt"},
    in the order they run across it, with "least" where the top is out of the
    picture; and how the picture was fitted."""
    width, height = picture["width"], picture["height"]
    how = fit(picture["marks"], width, height)
    radius = 1 / math.radians(abs(how["per_pixel"]))
    # The line between its points too, a few places to every degree: no
    # bearing the picture shows goes without an answer.
    across, down = zip(*picture["line"])
    places = np.linspace(across[0], across[-1], max(int(abs(how["per_pixel"]) * width * 4), len(across)))
    out = []
    for x, y in zip(places, np.interp(places, across, down)):
        point = {"az": (how["az0"] + how["per_pixel"] * x * width) % 360,
                 "alt": math.degrees(math.atan((how["row0"] - y * height) / radius))}
        if y * height < 1.5:
            point["least"] = True       # blocked to the top of the picture, and who knows how far above
        out.append(point)
    return out, how


def round_the_compass(points, step=2.0):
    """Points in the order they run across a picture, as a skyline (see
    horizon.limit): the highest in every `step` degrees of bearing, and at
    the ends of what the picture covers a point saying nothing is known
    beyond. A picture that goes more than once round overlaps itself; the
    higher answer is kept."""
    bins = {}
    for p in points:
        key = int(p["az"] // step)
        if key not in bins or p["alt"] > bins[key]["alt"]:
            bins[key] = dict(p, az=round(key * step + step / 2, 1), alt=round(max(p["alt"], 0.0), 1))
    covered = sorted(bins)
    out = [bins[key] for key in covered]
    count = round(360 / step)
    for key in covered:
        for side in (-1, 1):
            if (key + side) % count not in bins:
                # The edge of the picture. Past it nothing is known, so nothing is blocked.
                out.append({"az": round(((key + (side + 1) / 2) * step + side * 0.1) % 360, 1), "alt": 0.0,
                            "open": True, "unseen": True})
    return sorted(out, key=lambda p: p["az"])


def doubt(skyline, others):
    """Add to each point of the skyline how far the other pictures' skylines
    are from it there: things close by move against the sky with the height
    they are seen from. Returns the largest doubt added and its bearing."""
    most = (0.0, None)
    for point in skyline:
        if point.get("unseen") or point.get("least"):
            continue
        apart = 0.0
        for other in others:
            near = [p for p in other if not p.get("unseen") and not p.get("least")
                    and abs((p["az"] - point["az"] + 180) % 360 - 180) <= 1.5]
            if near:
                apart = max(apart, abs(max(p["alt"] for p in near) - point["alt"]))
        if apart >= 1:
            point["extra"] = round(min(apart, DOUBT), 1)
            most = max(most, (point["extra"], point["az"]))
    return most


# --- what is kept between commands -----------------------------------------------

def state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"pictures": []}


def keep(now):
    FOLDER.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(now, indent=1), encoding="utf-8")
    return now


def chosen(now, number):
    if not now["pictures"]:
        raise interface.Refusal("INVALID_REQUEST", "No panorama yet: ./panorama.py use PICTURE")
    if not 1 <= number <= len(now["pictures"]):
        raise interface.Refusal("INVALID_REQUEST", f"There is no picture {number}: there are {len(now['pictures'])}.")
    return now["pictures"][number - 1]


def share(value, size):
    """A place in the picture as a share of it, given as that or in pixels."""
    value = float(value)
    if not 0 <= value <= size:
        raise interface.Refusal("INVALID_REQUEST", f"{value:g} is outside the picture.")
    return value if value <= 1 else value / size


def take(path, now):
    """Bring a picture in: a copy for showing, and its skyline as first found."""
    try:
        image = Image.open(path)
        image.load()
    except (OSError, ValueError) as problem:
        raise interface.Refusal("INVALID_REQUEST", f"{path} could not be read as a picture: {problem}")
    if image.width < 3 * image.height / 2:
        print("This picture is not much wider than it is tall. A panorama covers more of the "
              "skyline; a single photograph still works for the part it shows.")
    number = len(now["pictures"]) + 1
    kept = image.convert("RGB")
    kept.thumbnail((KEPT_WIDTH, KEPT_WIDTH))
    FOLDER.mkdir(parents=True, exist_ok=True)
    kept.save(FOLDER / f"panorama-{number}.jpg", quality=88)
    picture = {"file": f"panorama-{number}.jpg", "width": image.width, "height": image.height,
               "taken": time.time(), "line": skyline_in(kept), "found": None, "marks": []}
    picture["found"] = [y for _, y in picture["line"]]      # as first found, to tell what a person changed
    now["pictures"].append(picture)
    return picture


def drawn(now, number=1):
    """Write the picture with its skyline and marks on, and return where."""
    picture = chosen(now, number)
    image = Image.open(FOLDER / picture["file"]).convert("RGB")
    draw, (w, h) = ImageDraw.Draw(image), image.size
    draw.line([(x * w, y * h) for x, y in picture["line"]], fill=(255, 40, 90), width=3)
    for i, mark in enumerate(picture["marks"], 1):
        x, y = mark["x"] * w, mark["y"] * h
        draw.ellipse([x - 7, y - 7, x + 7, y + 7], outline=(255, 190, 60), width=3)
        draw.text((x + 10, y - 6), f"{i}: {mark['az']:.0f}° / {mark['alt']:.0f}°", fill=(255, 190, 60))
    try:
        how = fit(picture["marks"], w, h)
    except interface.Refusal:
        how = None      # too few marks yet, or marks that make no sense: the line alone
    if how:
        for az in range(0, 360, 15):
            x = ((az - how["az0"] + 180) % 360 - 180) / how["per_pixel"]
            x = x if 0 <= x < w else x + 360 / abs(how["per_pixel"]) * (1 if x < 0 else -1)
            if 0 <= x < w:
                draw.line([(x, h - 18), (x, h)], fill=(255, 255, 255), width=2)
                draw.text((x + 3, h - 14), f"{az}°", fill=(255, 255, 255))
    image.save(MARKED, quality=88)
    return MARKED


def describe(now):
    """Where things stand, as data for the application and as words."""
    pictures = []
    for number, picture in enumerate(now["pictures"], 1):
        entry = {"number": number, "file": picture["file"], "taken": picture["taken"],
                 "line": picture["line"], "marks": picture["marks"],
                 "changed": sum(1 for (_, y), was in zip(picture["line"], picture["found"]) if y != was),
                 "above_picture": sum(1 for _, y in picture["line"] if y * picture["height"] < 1.5),
                 "fit": None}
        if len(picture["marks"]) >= 2:
            try:
                how = fit(picture["marks"], picture["width"], picture["height"])
                entry["fit"] = {"degrees_wide": round(abs(how["per_pixel"]) * picture["width"], 1),
                                "worst_deg": how["worst"]}
            except interface.Refusal as refusal:
                entry["fit"] = {"problem": refusal.message}
        pictures.append(entry)
    return {"pictures": pictures, "ready": bool(pictures) and bool(pictures[0]["fit"])
            and "problem" not in pictures[0]["fit"]}


def say(told):
    if not told["pictures"]:
        print("No panorama yet: ./panorama.py use PICTURE")
    for p in told["pictures"]:
        role = "the one that counts" if p["number"] == 1 else "from another height"
        print(f"Picture {p['number']} ({role}): skyline found, {p['changed']} of {len(p['line'])} points "
              f"put right by hand, {len(p['marks'])} mark{'s' if len(p['marks']) != 1 else ''}.")
        for i, mark in enumerate(p["marks"], 1):
            print(f"   mark {i}: {mark['x']:.3f} across, {mark['y']:.3f} down = bearing {mark['az']:.1f}°, "
                  f"{mark['alt']:.1f}° up ({mark['from']})")
        if p["above_picture"]:
            print(f"   In {p['above_picture']} places the top is above the picture: only \"at least this "
                  "high\" can be said there.")
        if p["fit"] and "problem" in p["fit"]:
            print(f"   {p['fit']['problem']}")
        elif p["fit"]:
            print(f"   By its marks it is {p['fit']['degrees_wide']:g}° wide"
                  + (f"; the marks agree on height to within {p['fit']['worst_deg']:g}°."
                     if len(p["marks"]) > 2 else "."))
        else:
            print(f"   It needs {2 - len(p['marks'])} more mark{'s' if len(p['marks']) == 0 else ''} "
                  "before it can be used.")


# --- the commands ------------------------------------------------------------------

def use(args):
    now = {"pictures": []}
    take(args.values[0], now)
    for extra in args.values[1:MOST]:
        take(extra, now)
    keep(now)
    print(f"Skyline found. Look at {drawn(now)}: put right what is wrong (move), then give it two marks.")
    return describe(now)


def also(args):
    now = state()
    chosen(now, 1)
    if len(now["pictures"]) >= MOST:
        raise interface.Refusal("INVALID_REQUEST", f"There are {MOST} pictures already: the one that counts "
                                "and two from other heights.")
    take(args.values[0], now)
    keep(now)
    print(f"Picture {len(now['pictures'])} taken in. It needs its own two marks: add --picture "
          f"{len(now['pictures'])} to mark and move.")
    return describe(now)


def mark(args):
    now = state()
    picture = chosen(now, args.picture)
    if len(args.values) < 2:
        raise interface.Refusal("INVALID_REQUEST", "Say where in the picture: how far across and how far down.")
    x, y = share(args.values[0], picture["width"]), share(args.values[1], picture["height"])
    if args.telescope:
        import landmark
        import mount
        cfg = config.load() if config.FILE.exists() else config.example()
        scope = mount.Mount()
        az, alt = landmark.altaz(*scope.axes(), cfg["site"]["latitude"])
        where = "where the telescope pointed"
    elif args.landmark:
        import landmark
        note = landmark.saved(landmark.name_ok(args.landmark))
        az, alt, where = note["bearing_deg"], note["height_deg"], f"the landmark {note['name']}"
    elif len(args.values) == 4:
        az, alt, where = float(args.values[2]), float(args.values[3]), "typed in"
    else:
        raise interface.Refusal("INVALID_REQUEST", "Say what is there: a bearing and a height, "
                                "--landmark NAME, or --telescope.")
    if not (0 <= az <= 360 and -10 <= alt <= 89):
        raise interface.Refusal("INVALID_REQUEST", "A bearing is 0 to 360 and a height -10 to 89 degrees.")
    picture["marks"].append({"x": round(x, 4), "y": round(y, 4), "az": round(float(az) % 360, 2),
                             "alt": round(float(alt), 2), "from": where})
    keep(now)
    drawn(now, args.picture)
    print(f"Marked: bearing {az:.1f}°, {alt:.1f}° up ({where}).")
    told = describe(now)
    say(told)
    return told


def unmark(args):
    now = state()
    picture = chosen(now, args.picture)
    which = int(args.values[0]) if args.values else 0
    if not 1 <= which <= len(picture["marks"]):
        raise interface.Refusal("INVALID_REQUEST", f"There is no mark {which}.")
    picture["marks"].pop(which - 1)
    keep(now)
    drawn(now, args.picture)
    return describe(now)


def move(args):
    """Put the skyline right: at each place given, the nearest point of it
    goes to that height."""
    now = state()
    picture = chosen(now, args.picture)
    if not args.values:
        raise interface.Refusal("INVALID_REQUEST", "Say where the skyline really is: ACROSS,DOWN, as many as you like.")
    for pair in args.values:
        try:
            x, y = pair.split(",")
        except ValueError:
            raise interface.Refusal("INVALID_REQUEST", f"{pair} is not ACROSS,DOWN.")
        x, y = share(x, picture["width"]), share(y, picture["height"])
        nearest = min(range(len(picture["line"])), key=lambda i: abs(picture["line"][i][0] - x))
        picture["line"][nearest][1] = round(y, 4)
    keep(now)
    print(f"{len(args.values)} point{'s' if len(args.values) != 1 else ''} of the skyline moved. "
          f"See {drawn(now, args.picture)}.")
    return describe(now)


def save(args):
    now = state()
    first, how = placed(chosen(now, 1))
    skyline = round_the_compass(first)
    warnings, others = [], []
    for number, picture in enumerate(now["pictures"][1:], 2):
        if len(picture["marks"]) < 2:
            warnings.append(f"Picture {number} has fewer than two marks, so it was left out.")
            continue
        others.append(round_the_compass(placed(picture)[0]))
    most, where = doubt(skyline, others)
    seen = [p for p in skyline if not p.get("unseen")]
    wide = abs(how["per_pixel"]) * now["pictures"][0]["width"]
    print(f"The picture covers {min(wide, 360):.0f}° of the compass; the skyline in it runs from "
          f"{min(p['alt'] for p in seen):.0f}° to {max(p['alt'] for p in seen):.0f}° up.")
    if len(now["pictures"][0]["marks"]) > 2 and how["worst"] > 2:
        warnings.append(f"The marks disagree on height by {how['worst']:g}°. One of them is in the wrong "
                        "place, or the panorama is bent; the skyline is no truer than that.")
    if wide < 350:
        warnings.append(f"{360 - wide:.0f}° of the compass is not in the picture. Nothing is known there, "
                        "so nothing is counted as blocked there.")
    above = [p["az"] for p in seen if p.get("least")]
    if above:
        warnings.append(f"Around bearing {above[len(above) // 2]:.0f}° the top is above the picture in "
                        f"{len(above)} places: the skyline there is at least what is kept. A panorama tilted "
                        "higher, or ./horizon.py --trace, finds the real top.")
    if others:
        print(f"From the other height{'s' if len(others) > 1 else ''} the skyline sits up to {most:g}° "
              f"differently (near bearing {where:.0f}°): that much doubt is added there." if where is not None
              else "From the other heights the skyline sits the same to within a degree.")
    cfg = config.load() if config.FILE.exists() else config.example()
    low, margin = cfg["horizon"]["min_altitude"], cfg["horizon"]["margin"]
    kept = horizon.keep(skyline, "panorama", warnings=warnings,
                        fit={"degrees_wide": round(wide, 1), "worst_deg": how["worst"]})
    print("\n" + horizon.picture_of(skyline, low, margin))
    for warning in warnings:
        print(f"\nCHECK: {warning}")
    print(f"\nKept. The planner uses this skyline from now on, raised by a margin of {margin:g}° "
          "(margin under [horizon] in config.toml). To have the telescope check it: ./horizon.py --trace")
    return {"skyline": kept["skyline"], "usable": horizon.usable(skyline, low, margin), "source": "panorama",
            "margin": margin, "degrees_wide": round(wide, 1)}, warnings


def show(args):
    now = state()
    told = describe(now)
    say(told)
    if told["pictures"]:
        print(f"Marked up: {drawn(now, args.picture)}")
    return told


def clear(args):
    for old in FOLDER.glob("panorama-*.jpg") if FOLDER.exists() else ():
        old.unlink()
    for old in (STATE, MARKED):
        if old.exists():
            old.unlink()
    print("The panoramas are cleared away. A skyline already kept from them stays: "
          "./horizon.py --forget throws that away.")
    return {"pictures": [], "ready": False}


COMMANDS = {"use": use, "also": also, "mark": mark, "unmark": unmark, "move": move, "save": save,
            "show": show, "clear": clear}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=list(COMMANDS))
    ap.add_argument("values", nargs="*", help="pictures for use and also; ACROSS DOWN [BEARING HEIGHT] for "
                    "mark; ACROSS,DOWN ... for move; a mark's number for unmark")
    ap.add_argument("--picture", type=int, default=1, help="which picture mark, unmark, move and show mean (default 1)")
    ap.add_argument("--landmark", metavar="NAME", help="with mark: the point is this remembered landmark")
    ap.add_argument("--telescope", action="store_true", help="with mark: the point is what the telescope "
                    "points at now (reads the mount; nothing moves)")
    ap.add_argument("--dry-run", action="store_true", help="nothing here moves the mount; this says so and stops")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if args.command in ("use", "also") and not args.values:
        ap.error(f"{args.command} needs a picture")
    if args.dry_run:
        return interface.main(f"panorama.{args.command}.dry_run", lambda: {"would_move": False}, args.json)
    return interface.main(f"panorama.{args.command}", lambda: COMMANDS[args.command](args), args.json)


if __name__ == "__main__":
    main()
