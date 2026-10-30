#!/usr/bin/env python3
"""The Moon's faint colour turned up: a "mineral Moon".

    ./lucky.py mineral COLOUR.ser ... [--detail DETAIL.ser ...] [--strength standard]
    ./ty moon --mineral          takes the videos for it and runs this

The Moon's colours are real but faint, a percent or two either way.
Spacecraft maps, taken through narrow filters, show many titanium-rich
seas as bluer, and fresh ground as bluer than old. This camera's broad
colours can show some of those differences between regions, but they
cannot tell how much titanium or iron there is (Earth and Space Science,
2023, doi:10.1029/2022EA002710): what they show is enhanced colour that
goes with composition and maturity, never an abundance. Its blue and red
are the Hypercam 183C's own (the IMX183's Bayer filters, peaks near 460
and 625 nm), not Clementine's 415 and 750 nm or Galileo's filters, so its
B/R is this camera's index.

What it does, from stacked videos (lucky.py stack --colour):

- the detail from each video's sharpest stack, the colour from its largest
  share (colour needs many frames more than it needs sharpness), every
  stack lined up on the first;
- red and blue moved onto green, as low in the sky the air spreads them;
- pixels a video clipped left out of it, fading out rather than stopping;
- the colour worked out on 2x2 blocks, as log ratios of each colour to the
  three's mean, which turn a change of exposure or light into an offset;
- a slope across the disc taken off, fitted to the brighter half of the
  disc, so that a large sea's own colour is not mistaken for it. Fitting it
  to mapped highlands instead (--slope mapped, lunar.HIGHLANDS) agreed
  worse with Clementine's colour map on 30 October 2026 (rank correlation
  0.19 against 0.38): the mapped points are all central and southern, so
  the slope was carried across the north from them;
- each video's colour compared with the others': colour that does not
  repeat from video to video is turned down (more than one video needed),
  and colour that changes much when any one video is left out is marked
  less sure;
- the result turned up by a stated factor.

Beside the first colour video, NAME-mineral:

    .jpg .fits         blue against orange only: the safe picture
    -full.jpg          every colour kept: exploratory, as the camera adds a
                       green-magenta tint of its own that may not all be gone
    -balanced.jpg      the colour as it is, its three colours balanced to a
                       grey Moon, the detail sharpened (not calibrated colour)
    -ratios.fits       log B/R, R/G and B/G after calibration
    -ratio-br.jpg      log B/R as grey: brighter is bluer
    -confidence.jpg    green: robust; amber: faint, near the edge or the
                       terminator, not repeated, or changed by leaving one
                       video out; red: clipped or off the Moon
    -difference.fits   the first two videos' blue-orange, one less the other
    .json              the colour as measured, the factor it was turned up by,
                       each video's depth, white level, clipping and flat, how
                       well the videos agree (with each left out in turn),
                       whether the colour follows the Moon or the sensor, the
                       orientation and its checks, and the check against the seas

The check against the seas: the Moon's orientation (lunar.py) puts the
named seas on the picture, and spacecraft colour maps say Mare
Tranquillitatis is bluer than Mare Serenitatis and than the uplands (NASA's
Galileo colour Moon, science.nasa.gov/resource/colorful-moon). The json
says whether this picture agrees, by how much, in how many of the videos,
and whether it still holds with any one video left out. Its consistency
score (the difference over its standard error between videos) compares
nights; with two or three videos it is not a statistical significance.

The orientation is found from the picture (the terminator, then the seas
darker than the uplands), so it is checked against something else where it
can be: a plate solve of the same night with the same camera
(cache/last_solve.json), turned 180 degrees if the mount was on the other
side of the meridian.

30 October 2026: the first was made from that night's three 8-bit videos.
"""
import json
from pathlib import Path

import numpy as np
from scipy import ndimage

import config
import lucky
import lunar

STRENGTHS = {"mild": 8.0, "standard": 15.0, "strong": 25.0}    # how many times the colour is turned up
AUTO_SPREAD = 0.35        # "auto": the strongest 1 % of the colour turned up to this share of the brightness
COLOUR_BLUR = 4.0         # pixels the colour is smoothed over: its noise is far coarser than the detail's
BIN = 2                   # the colour worked out on blocks this many pixels a side
FEATHER = 12.0            # pixels over which a stack fades out towards where it clipped
CLIP_MARGIN = 0.8         # a stack's pixel counts as clipped from this share of the white level up
STEEP = 0.26              # cos 75 degrees: the Sun or our view this low over the ground is the edge
HIGHLAND_RADIUS = 8.0     # degrees of arc around each mapped highland point used for the slope
SOLVE_WITHIN = 6 * 3600   # seconds: a plate solve this close to the video checks its orientation
SOLVE_AGREES = 5.0        # degrees: the picture's own turn this close to the solve's agrees
FOLLOWS_MARGIN = 0.1      # correlation: the Moon's or the sensor's frame this much better decides it
FOLLOWS_SHIFT = 50.0      # pixels: videos closer than this on the sensor cannot tell the two apart
# the camera's colours: the IMX183's Bayer filters, quantum efficiency at the
# test wavelengths of two makers' EMVA 1288 reports (FLIR BFS-U3-200S6C,
# Baumer VCXG.2-201C): blue 61-63 % at 460-467 nm, green 68 % at 530-533 nm,
# red 43-50 % at 625-630 nm. Broad and overlapping: no full curve is published.
CAMERA_BANDS = "Hypercam 183C (IMX183 Bayer RGB): blue ~460 nm, green ~530 nm, red ~625 nm, broad"


def _level(a):
    a = np.asarray(a, dtype=np.float32)
    return a.mean(axis=-1) if a.ndim == 3 else a


def _onto(a, shift):
    return ndimage.shift(a, shift, order=1, mode="nearest")


def _middle(image, size=1024):
    """The middle of a picture, where the Moon is, for lining things up."""
    h, w = image.shape[:2]
    y, x = max(0, (h - size) // 2), max(0, (w - size) // 2)
    return image[y:y + size, x:x + size]


def channels_lined_up(rgb):
    """Red and blue moved onto green: low in the sky the air spreads the
    colours a pixel or two apart, which turned up shows as coloured rims."""
    rgb = np.asarray(rgb, dtype=np.float32)
    out = rgb.copy()
    for c in (0, 2):
        out[..., c] = _onto(rgb[..., c], lucky.phase_shift(_middle(rgb[..., 1]), _middle(rgb[..., c])))
    return out


def unclipped(image, ceiling=None, margin=CLIP_MARGIN):
    """Where no colour of a stack came near the camera's white level
    (`ceiling`; none given, nothing counts as clipped): a clipped green turns
    the colour magenta when it is turned up (30 October 2026: the 01:55
    video was overexposed, every colour at 255 over the bright side). Well
    short of the top, as a stack averages frames that clipped with ones the
    seeing blurred below it: that video's brightest crater stacked to 237
    of 255 at half its true brightness."""
    brightest = np.asarray(image, dtype=np.float32)
    brightest = brightest.max(axis=-1) if brightest.ndim == 3 else brightest
    return np.ones(brightest.shape, bool) if ceiling is None else brightest < margin * ceiling


def feathered(good, width=FEATHER):
    """A 0-1 weight from `good`, fading to nothing a little inside its edge:
    a hard edge left blotches where one stack dropped out and the others,
    a touch darker or brighter, took over (30 October 2026)."""
    if good.all():
        return good.astype(np.float32)
    inside = ndimage.binary_erosion(good, iterations=int(width), border_value=1)
    return ndimage.gaussian_filter(inside.astype(np.float32), width / 2, mode="nearest")


def log_tint(rgb, where, bin=BIN):
    """Each colour's log ratio to the three's mean, (h, w, 3), each colour
    first set to 1 over `where` (the camera's own balance taken out). Worked
    out on `bin` x `bin` blocks and spread back: the colour is coarse, and
    four pixels averaged have half the noise of one."""
    rgb = np.asarray(rgb, dtype=np.float32)
    h, w = rgb.shape[:2]
    if not where.any():           # nothing usable in this stack: its own bright part balances it
        where = rgb.mean(axis=-1) > 0.08 * np.percentile(rgb.mean(axis=-1), 99.9)
    norm = rgb / np.maximum([np.median(rgb[..., k][where]) for k in range(3)], 1e-6)
    hb, wb = h // bin, w // bin
    small = norm[:hb * bin, :wb * bin].reshape(hb, bin, wb, bin, 3).mean(axis=(1, 3))
    logs = np.log(np.maximum(small, 1e-6))
    logs -= logs.mean(axis=-1, keepdims=True)
    big = ndimage.zoom(logs, (bin, bin, 1), order=1)
    return np.pad(big, ((0, h - big.shape[0]), (0, w - big.shape[1]), (0, 0)), mode="edge")


def flattened(tint, where):
    """`tint` with a flat slope across the disc taken off each colour, the
    slope fitted only `where` (the uplands): on 30 October 2026 red against
    green rose 2.3 % from the terminator to the limb in all the videos
    alike, five times the minerals' own 0.5 %, and turned up it painted one
    side green and the other magenta. Fitted to every pixel, a great sea's
    own colour would be taken for part of the slope."""
    if where.sum() < 3:
        return tint
    yy, xx = np.indices(where.shape)
    rows = np.c_[np.ones(where.sum()), xx[where], yy[where]]
    out = tint.copy()
    for k in range(tint.shape[-1]):
        a, bx, by = np.linalg.lstsq(rows, tint[..., k][where], rcond=None)[0]
        out[..., k] = tint[..., k] - (a + bx * xx + by * yy)
    return out


def blue_to_orange(tint):
    """Only the part of `tint` running from blue to orange (red against
    blue), where the Moon's colour mostly shows. Green against magenta is
    mostly this camera's: its greens fill in from twice the pixels and clip
    first, and on 30 October 2026 that axis, turned up, painted the uplands
    magenta and the seas green. The -full picture keeps it."""
    half = (tint[..., 0] - tint[..., 2]) / 2
    return np.stack([half, np.zeros_like(half), -half], -1)


def gain_for(strength, safe, where):
    """How many times the colour is turned up: a named strength, a number,
    or "auto" (the strongest 1 % of the colour to AUTO_SPREAD)."""
    if isinstance(strength, (int, float)) or str(strength).replace(".", "", 1).isdigit():
        return float(strength)
    if strength == "auto":
        reach = float(np.percentile(np.abs(safe[..., 0][where]), 99)) if where.any() else 0.0
        return AUTO_SPREAD / reach if reach > 1e-6 else 1.0
    if strength not in STRENGTHS:
        raise SystemExit(f"--strength: {strength} is not one of {', '.join(STRENGTHS)}, auto or a number")
    return STRENGTHS[strength]


def repeatability(maps, weights, where):
    """How far each pixel's blue-orange can be trusted from how the videos
    agree: (a consistency score, the signal over its standard error between
    videos; the videos' correlations two by two over `where`). With two or
    three videos, smoothed and sharing the optics and the air, the score is
    a measure of agreement, not a statistical significance. With one video
    it cannot be told: (None, [])."""
    n = len(maps)
    if n < 2:
        return None, []
    w = np.array(weights)
    total = np.maximum(w.sum(axis=0), 1e-6)
    mean = (w * np.array(maps)).sum(axis=0) / total
    spread = np.sqrt((w * (np.array(maps) - mean) ** 2).sum(axis=0) / total)
    effective = total ** 2 / np.maximum((w ** 2).sum(axis=0), 1e-6)
    error = spread / np.sqrt(np.maximum(effective - 1, 1e-6))
    score = np.abs(mean) / np.maximum(error, 1e-6)
    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            both = where & (weights[i] > 0.5) & (weights[j] > 0.5)
            if both.sum() > 10:
                pairs.append(round(float(np.corrcoef(maps[i][both], maps[j][both])[0, 1]), 3))
    return score, pairs


def left_out(maps, weights, where):
    """What changes when each video is left out in turn: (where the colour
    changes sign, or by more than half, without some one video, among
    pixels with more than the typical colour; per video, the share of
    `where` it changes and the correlation of the rest's map with all's).
    A feature that goes when one video goes is that video's, not the
    Moon's. With one video: (None, [])."""
    n = len(maps)
    if n < 2:
        return None, []
    w, m = np.array(weights), np.array(maps)
    total = w.sum(axis=0)
    summed = (w * m).sum(axis=0)
    mean = summed / np.maximum(total, 1e-6)
    floor = float(np.median(np.abs(mean[where]))) if where.any() else 0.0
    unstable, each = np.zeros(mean.shape, bool), []
    for i in range(n):
        rest_w = total - w[i]
        rest = (summed - w[i] * m[i]) / np.maximum(rest_w, 1e-6)
        covered = rest_w > 0.5
        moved = covered & (np.abs(mean) > floor) & ((np.sign(rest) != np.sign(mean))
                                                    | (np.abs(rest - mean) > 0.5 * np.abs(mean)))
        unstable |= moved
        seen = where & covered
        each.append({"left_out": i + 1,
                     "changed_share": round(float(moved[seen].mean()), 3) if seen.any() else None,
                     "r_with_all": round(float(np.corrcoef(rest[seen], mean[seen])[0, 1]), 3) if seen.sum() > 10 else None})
    return unstable, each


def follows(maps, weights, shifts, where, margin=FOLLOWS_MARGIN, least=FOLLOWS_SHIFT):
    """Whether the colour follows the Moon or the sensor: each pair of
    videos' maps compared as lined up on the Moon (as made) and as lined up
    on the sensor (one moved back by the difference of where each put the
    disc). A pattern of the camera's repeats on the sensor, the Moon's on
    the Moon. Only pairs whose discs sat at least `least` pixels apart count."""
    moon, sensor, apart = [], [], []
    for i in range(len(maps)):
        for j in range(i + 1, len(maps)):
            d = np.subtract(shifts[i], shifts[j])
            if np.hypot(*d) < least:
                continue
            back, back_w = _onto(maps[j], d), _onto(weights[j], d)
            both = where & (weights[i] > 0.5) & (weights[j] > 0.5) & (back_w > 0.5)
            if both.sum() < 100:
                continue
            moon.append(float(np.corrcoef(maps[i][both], maps[j][both])[0, 1]))
            sensor.append(float(np.corrcoef(maps[i][both], back[both])[0, 1]))
            apart.append(round(float(np.hypot(*d)), 1))
    if not moon:
        return {"verdict": f"not measured: no two videos {least:g} pixels apart on the sensor"}
    r_moon, r_sensor = float(np.mean(moon)), float(np.mean(sensor))
    verdict = ("the Moon" if r_moon > r_sensor + margin else "the sensor" if r_sensor > r_moon + margin
               else "cannot tell")
    return {"verdict": verdict, "r_on_the_moon": round(r_moon, 3), "r_on_the_sensor": round(r_sensor, 3),
            "pixels_apart": apart}


def slope_ground(base, inner, geometry, radius=HIGHLAND_RADIUS, on="mapped"):
    """Where the slope across the disc is fitted, and what it is: the mapped
    highlands (lunar.HIGHLANDS) lit well enough, when the orientation is
    known and they spread over a quarter of the disc each way; else the
    brighter half of the disc, which takes in bright rays and lit seas too."""
    bright = inner & (base > np.median(base[inner])) if inner.any() else inner
    if on == "bright":
        return bright, "the brighter half of the disc"
    if geometry is None or not inner.any():
        return bright, "the brighter half of the disc (orientation not known)"
    lit = inner & (geometry["cos_i"] > STEEP)
    parts = [p for p in (lunar.near(geometry, la, lo, radius) & lit for la, lo in lunar.HIGHLANDS.values())
             if p.sum() > 50]
    if len(parts) >= 2:
        mapped = np.any(parts, axis=0)
        ys, xs = np.nonzero(mapped)
        across = 2 * np.sqrt(inner.sum() / np.pi)
        if np.ptp(xs) > 0.25 * across and np.ptp(ys) > 0.25 * across:
            return mapped, f"mapped highlands ({len(parts)} places)"
    return bright, "the brighter half of the disc (too few mapped highlands lit)"


def mineral(colours, details, strength="standard", blur=COLOUR_BLUR, ceilings=None, detail_ceilings=None,
            geometry=None, slope="bright"):
    """The mineral Moon from `colours` (RGB stacks) and `details` (stacks,
    one colour or three), all lined up on the first detail. `ceilings` are
    each stack's white level (None: never clipped). `geometry` is the
    picture's place on the Moon (lunar.surface) when known, for the
    confidence map. Returns a dict of the pictures, maps and facts."""
    ceilings = list(ceilings or [None] * len(colours))
    detail_ceilings = list(detail_ceilings or [None] * len(details))
    base = _level(details[0])
    lit = base > 0.08 * np.percentile(base, 99.9)
    detail, counted, brightest = np.zeros_like(base), np.zeros_like(base), np.zeros_like(base)
    for d, ceiling in zip(details, detail_ceilings):
        good = unclipped(d, ceiling)
        d = _level(d)
        d = d / max(np.median(d[lit & good]) if (lit & good).any() else d.mean(), 1e-6)
        shift = lucky.whole_shift(base, d)
        weight = _onto(feathered(good), shift)
        moved = _onto(d, shift)
        detail += moved * weight
        counted += weight
        brightest = np.maximum(brightest, moved)
    # where every stack clipped, the brightest of them is the nearest the
    # truth: their average sat a grey blob in the brightest craters
    blend = np.clip(counted, 0, 1)
    detail = lucky.sharpen(blend * detail / np.maximum(counted, 1e-6) + (1 - blend) * brightest)

    raw, weights, clipped, shifts = [], [], [], []
    for c, ceiling in zip(colours, ceilings):
        good = unclipped(c, ceiling)
        c = channels_lined_up(c)
        shift = lucky.whole_shift(base, _level(c))
        shifts.append(tuple(float(v) for v in shift))
        c = np.stack([_onto(c[..., k], shift) for k in range(3)], -1)
        weight = _onto(feathered(good), shift)
        raw.append(log_tint(c, lit & (weight > 0.5)))
        weights.append(weight)
        own = _level(colours[len(clipped)])
        clipped.append(round(float(1 - good[own > 0.08 * np.percentile(own, 99.9)].mean()), 4))
    total = np.sum(weights, axis=0)
    usable = lit & (total > 0.5)
    inner = ndimage.binary_erosion(usable, iterations=int(4 * blur) + 1)       # the limb's rims kept out
    uplands, fitted_on = slope_ground(base, inner, geometry, on=slope)
    smooth = lambda t: np.stack([ndimage.gaussian_filter(t[..., k], blur) for k in range(3)], -1)  # noqa: E731
    tints = [smooth(flattened(t, uplands & (w > 0.5))) for t, w in zip(raw, weights)]
    mean = sum(t * w[..., None] for t, w in zip(tints, weights)) / np.maximum(total, 1e-6)[..., None]
    balanced_tint = sum(smooth(t) * w[..., None] for t, w in zip(raw, weights)) / np.maximum(total, 1e-6)[..., None]
    orange = [(t[..., 0] - t[..., 2]) / 2 for t in tints]
    score, pairs = repeatability(orange, weights, inner)
    keep = np.ones_like(base) if score is None else np.clip(score / 2, 0, 1)     # a score of 2: kept whole
    unstable, without = left_out(orange, weights, inner)
    follow = follows(orange, weights, shifts, inner)
    edge = ndimage.gaussian_filter(inner.astype(np.float32), blur)
    tint = mean * (keep * edge)[..., None]
    safe = blue_to_orange(tint)
    gain = gain_for(strength, safe, inner)
    measured = (mean[..., 0] - mean[..., 2]) / 2
    native = {"p99_percent": round(100 * float(np.percentile(np.abs(measured[inner]), 99)), 3) if inner.any() else 0,
              "spread_percent": round(100 * float(measured[inner].std()), 3) if inner.any() else 0}

    confidence = np.full(base.shape, 2, np.uint8)
    weak = ~inner | (base < 0.25 * np.percentile(base, 99.9))
    if score is not None:
        weak |= (score < 2) | unstable
    if geometry is not None:
        weak |= (geometry["cos_i"] < STEEP) | (geometry["cos_e"] < STEEP)
    confidence[weak] = 1
    confidence[~usable] = 0
    ratios = {"log_b_r": (mean[..., 2] - mean[..., 0]) * usable, "log_r_g": (mean[..., 0] - mean[..., 1]) * usable,
              "log_b_g": (mean[..., 2] - mean[..., 1]) * usable}
    return {"picture": np.clip(detail[..., None] * np.exp(gain * safe), 0, None),
            "full": np.clip(detail[..., None] * np.exp(gain * tint), 0, None),
            "balanced": np.clip(detail[..., None] * np.exp(balanced_tint * edge[..., None]), 0, None),
            "ratios": ratios, "confidence": confidence, "orange": orange, "weights": weights, "usable": usable,
            "difference": orange[0] - orange[1] if len(orange) > 1 else None,
            "facts": {"display_gain": round(gain, 2), "strength": strength, "native_colour": native,
                      "videos": len(colours), "clipped_share": clipped, "agreement": pairs,
                      "repeatability": ("measured: a consistency score between videos, not a significance"
                                        if score is not None else "one video: not measured"),
                      "left_out": without, "follows": follow, "disc_shifts_px": [[round(v, 1) for v in s] for s in shifts],
                      "slope_fitted_on": fitted_on, "bands": CAMERA_BANDS,
                      "confident_share": round(float((confidence == 2)[usable].mean()), 3) if usable.any() else 0}}


def check_seas(orange, weights, usable, geometry, radius=4.0):
    """Whether the blue against orange agrees with the spacecraft maps:
    Mare Tranquillitatis bluer than Mare Serenitatis, and than the uplands.
    Each video's own difference gives the uncertainty. A list of checks."""
    lit = usable & (geometry["cos_i"] > 0.05) & (geometry["cos_e"] > STEEP)      # near the terminator still counts: the confidence map marks it

    def region(m, w, places):
        values = [m[near] for near in (lunar.near(geometry, la, lo, radius) & lit & (w > 0.5)
                                       for la, lo in places) if near.sum() > 20]
        return float(np.mean([v.mean() for v in values])) if values else None
    checks = []
    tranq = [lunar.SEAS["Mare Tranquillitatis"]]
    others = {"Mare Serenitatis": [lunar.SEAS["Mare Serenitatis"]],
              "the uplands": [p for k, p in lunar.HIGHLANDS.items() if k.startswith("southern")]}
    for name, places in others.items():
        each = []
        for m, w in zip(orange, weights):
            t, other = region(m, w, tranq), region(m, w, places)
            if t is not None and other is not None:
                each.append(other - t)        # positive: Tranquillitatis bluer
        check = {"expected": f"Mare Tranquillitatis bluer than {name}"}
        if not each:
            check["result"] = "not seen: dark, clipped or on the far side tonight"
        else:
            diff = float(np.mean(each))
            check["bluer_by_percent"] = round(100 * diff, 3)
            check["videos_agreeing"] = f"{sum(e > 0 for e in each)} of {len(each)}"
            if len(each) > 1:
                check["holds_without_any_one_video"] = bool(all(np.mean(each[:i] + each[i + 1:]) > 0
                                                                for i in range(len(each))))
            if len(each) > 1 and np.std(each, ddof=1) > 0:
                check["consistency_score"] = round(diff / (np.std(each, ddof=1) / np.sqrt(len(each))), 1)
            check["result"] = "agrees" if diff > 0 else "disagrees"
        checks.append(check)
    return checks


REFERENCE = config.DATA / "cache" / "moon-colour-reference.npz"
REFERENCE_BLOCK = 38      # source pixels a side averaged into one reference cell (about 0.25 degrees)
REFERENCE_CELL = 2.0      # degrees: our map and the reference compared in cells this size, nearer independent


def reference_from(tif, out=None, block=REFERENCE_BLOCK, say=print):
    """A spacecraft colour map made small enough to keep: USGS's Clementine
    UVVIS warped colour-ratio mosaic (planetarymaps.usgs.gov, 200 m a pixel,
    public domain: red 750/415 nm, green 750/950, blue 415/750, simple
    cylindrical from 180 W and 90 N), uncompressed with each colour a plane
    of one-row strips, so it is read through a memory map, never whole.
    Kept as the blue less the red of each cell (bluer is higher, its own
    stretch, so it is compared by rank) and the green. Returns the path."""
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    out = Path(out or REFERENCE)
    with Image.open(tif) as im:
        width, height = im.size
        tiles = im.tile
        planar = im.tag_v2.get(284)
    if planar != 2 or len(tiles) != 3 * height or any(t.codec_name != "raw" for t in tiles[:: height]):
        raise SystemExit(f"{tif}: not the layout expected (three uncompressed planes of one-row strips)")
    starts = [tiles[k * height].offset for k in range(3)]
    if any(tiles[k * height + height - 1].offset != starts[k] + (height - 1) * width for k in range(3)):
        raise SystemExit(f"{tif}: a colour's rows are not stored one after another")
    h, w = height // block, width // block
    cells = np.zeros((3, h, w), np.float32)
    for k in range(3):
        plane = np.memmap(tif, np.uint8, "r", starts[k], (height, width))
        for row in range(h):
            part = np.asarray(plane[row * block:(row + 1) * block, :w * block], dtype=np.float32)
            cells[k, row] = part.reshape(block, w, block).mean(axis=(0, 2))
        say(f"colour {'RGB'[k]} read")
    empty = cells.sum(axis=0) == 0
    blue = np.where(empty, np.nan, cells[2] - cells[0])
    green = np.where(empty, np.nan, cells[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, blue_less_red=blue, green=green, cell_deg=block * 360.0 / width,
                        source=str(Path(tif).name))
    say(f"kept {w} x {h} cells of {block * 360.0 / width:.3f} degrees: {out}")
    return out


def compare_reference(b_r, where, geometry, reference=None, cell=REFERENCE_CELL):
    """Our blue against red set beside the spacecraft map's: each pixel in
    `where` looked up on the map by its latitude and longitude, both averaged
    over cells of `cell` degrees, then compared by rank (Spearman), as the
    two measure blue differently. Also the named seas put in order by each.
    None when no reference has been made (./ty lucky reference FILE)."""
    from scipy.stats import spearmanr
    path = Path(reference or REFERENCE)
    if geometry is None or not path.exists():
        return None
    ref = np.load(path)
    blue, size = ref["blue_less_red"], float(ref["cell_deg"])
    lat, lon = geometry["lat"][where], geometry["lon"][where]
    rows = np.clip(((90 - lat) / size).astype(int), 0, blue.shape[0] - 1)
    cols = np.clip(((lon + 180) / size).astype(int), 0, blue.shape[1] - 1)
    theirs, ours = blue[rows, cols], b_r[where]
    keys = np.floor(lat / cell) * 1000 + np.floor(lon / cell)
    groups = {}
    for key, a, b in zip(keys, ours, theirs):
        if np.isfinite(b):
            groups.setdefault(key, []).append((a, b))
    pairs = np.array([np.mean(v, axis=0) for v in groups.values() if len(v) >= 20])
    out = {"source": str(ref["source"]), "cells": int(len(pairs))}
    if len(pairs) >= 10:
        out["rank_correlation"] = round(float(spearmanr(pairs[:, 0], pairs[:, 1])[0]), 3)
        out["correlation"] = round(float(np.corrcoef(pairs[:, 0], pairs[:, 1])[0, 1]), 3)
    seas = {}
    for name, (la, lo) in lunar.SEAS.items():
        near = lunar.near(geometry, la, lo, 4.0) & where
        r, c = int((90 - la) / size), int((lo + 180) / size)
        if near.sum() > 20 and np.isfinite(blue[r, c]):
            seas[name] = (float(b_r[near].mean()), float(np.nanmean(blue[max(r - 8, 0):r + 9, max(c - 8, 0):c + 9])))
    if len(seas) >= 3:
        names = list(seas)
        values = np.array([seas[n] for n in names])
        out["seas_rank_correlation"] = round(float(spearmanr(values[:, 0], values[:, 1])[0]), 3)
        order = lambda k: [names[i] for i in np.argsort(-values[:, k])]       # noqa: E731
        out["seas_bluest_first"] = {"ours": order(0), "spacecraft": order(1)}
    return out


def white_level(stem):
    """A stacked video's white level: from its stack's record, else its SER
    header's depth (12 for 12-bit values in 16-bit words). An old 16-bit
    video says 16 but holds the camera's own bits: its top is the camera's."""
    done = json.loads(Path(f"{stem}.stack.json").read_text(encoding="utf-8"))
    if done.get("white_level"):
        return float(done["white_level"])
    ser = Path(f"{stem}.ser")
    depth = lucky.ser_facts(ser)[0] if ser.exists() else 8
    if depth >= 16:
        depth = config.hardware()["camera"]["bit_depth"]
    return float(2 ** depth - 1)


def _picture_of(values, path, low=None, high=None):
    from PIL import Image
    low = np.percentile(values, 1) if low is None else low
    high = np.percentile(values, 99) if high is None else high
    Image.fromarray((np.clip((values - low) / max(high - low, 1e-9), 0, 1) * 255).astype(np.uint8)).save(path, quality=92)
    return path


def solved_turn(site, when, look, path=None):
    """The picture's (turn, mirrored) from the night's plate solve, or None:
    the last solve (cache/last_solve.json) if it was within SOLVE_WITHIN of
    `when`, turned 180 degrees if the mount was on the other side of the
    meridian for the Moon. Assumes the camera was not turned in between."""
    path = Path(path or config.DATA / "cache" / "last_solve.json")
    try:
        solve = json.loads(path.read_text(encoding="utf-8"))
        cd, saved, ra = solve["cd"], float(solve["saved"]), float(solve["ra"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if abs(saved - when.timestamp()) > SOLVE_WITHIN:
        return None
    from datetime import datetime, timezone
    solved_at = datetime.fromtimestamp(saved, timezone.utc)
    moon_ra = float(np.degrees(np.arctan2(-look["toward"][1], -look["toward"][0]))) % 360
    flipped = (lunar.hour_angle(site, solved_at, ra) < 0) != (lunar.hour_angle(site, when, moon_ra) < 0)
    turn, mirrored = lunar.turn_from_solve(cd, flipped)
    return {"turn_deg": round(turn, 1), "mirrored": mirrored, "flipped_across_meridian": bool(flipped),
            "solved_at": solved_at.isoformat()}


def mineral_file(stems, details=None, strength="standard", site=None, say=print, slope="bright"):
    """The mineral Moon from stacked videos named by their stem (the SER
    file without .ser): colour from each one's largest share, detail from
    the share each showed (from `details` when given). Writes the files the
    module's notes list beside the first. Returns (picture, facts)."""
    stems = [Path(str(s).removesuffix(".ser")) for s in stems]
    detail_stems = [Path(str(s).removesuffix(".ser")) for s in (details or stems)]
    from astropy.io import fits
    colours, ceilings, flats = [], [], []
    for stem in stems:
        done = json.loads(stem.with_suffix(".stack.json").read_text(encoding="utf-8"))
        largest = max(done["kept"], key=float)
        colours.append(fits.getdata(stem.with_name(f"{stem.name}.best{largest}.fits")))
        ceilings.append(white_level(stem))
        flats.append(done.get("flat"))
        say(f"{stem.name}: colour from the best {largest} %, white level {ceilings[-1]:g}, "
            f"{'flat ' + Path(done['flat']).name if done.get('flat') else 'no flat'}")
    detail_images, detail_ceilings = _details(detail_stems)
    geometry, placed = placed_on_moon(_level(detail_images[0]), detail_stems[0], site, say)
    out = mineral(colours, detail_images, strength=strength, ceilings=ceilings, detail_ceilings=detail_ceilings,
                  geometry=geometry, slope=slope)
    facts = dict(out["facts"], colour_videos=[s.name for s in stems], detail_videos=[s.name for s in detail_stems],
                 white_levels=ceilings, flats=flats, orientation=placed or None)
    return _written(out, facts, stems, geometry, placed, strength, say)


def _details(stems):
    """Each stacked video's detail (the share it showed) and its white level."""
    from astropy.io import fits
    images, ceilings = [], []
    for stem in stems:
        done = json.loads(stem.with_suffix(".stack.json").read_text(encoding="utf-8"))
        images.append(fits.getdata(stem.with_name(f"{stem.name}.best{done['shown']}.fits")))
        ceilings.append(white_level(stem))
    return images, ceilings


def compare_flats(sers, flats, details=None, share=40, site=None, say=print):
    """The colour of the same videos stacked again with each flat in `flats`
    ("none", "master" for this camera setup's, or a FITS file), and how well
    the videos then agree. A right flat makes the Moon's colour repeat
    better from video to video; a wrong one adds a pattern of its own that
    stays on the sensor as the disc moves. Writes NAME-mineral-flats.json
    beside the first video. Returns a row for each flat."""
    stems = [Path(str(s).removesuffix(".ser")) for s in sers]
    detail_stems = [Path(str(s).removesuffix(".ser")) for s in (details or sers)]
    detail_images, detail_ceilings = _details(detail_stems)
    geometry, _ = placed_on_moon(_level(detail_images[0]), detail_stems[0], site, say)
    rows = []
    for choice in flats:
        colours, ceilings = [], []
        for stem in stems:
            frames, _ = lucky.read_ser(Path(f"{stem}.ser"))
            if choice != "none":
                cut, _ = lucky.flat_for(Path(f"{stem}.ser"), frames.shape[1:],
                                        where=None if choice == "master" else choice)
                if cut is None:
                    raise SystemExit(f"no flat {choice}: ./calibrate.py flat makes this setup's master")
                frames = lucky.Flattened(frames, cut)
            results, _ = lucky.stack(frames, keeps=(share,), in_colour=True, report=lambda line: None)
            colours.append(next(iter(results.values())))
            ceilings.append(white_level(stem))
        out = mineral(colours, detail_images, ceilings=ceilings, detail_ceilings=detail_ceilings, geometry=geometry)
        f = out["facts"]
        row = {"flat": choice, "agreement": f["agreement"], "confident_share": f["confident_share"],
               "follows": f["follows"], "left_out": f["left_out"]}
        if geometry is not None:
            row["seas"] = check_seas(out["orange"], out["weights"], out["usable"], geometry)
        rows.append(row)
        say(f"{choice}: the videos agree at r {', '.join(f'{r:.2f}' for r in f['agreement']) or 'not measured'}; "
            f"{f['confident_share']:.0%} of the disc sure; the colour follows {f['follows']['verdict']}")
    Path(f"{stems[0]}-mineral-flats.json").write_text(json.dumps(rows, indent=1, default=str), encoding="utf-8")
    measured = [r for r in rows if r["agreement"]]
    if measured:
        best = max(measured, key=lambda r: float(np.mean(r["agreement"])))
        say(f"the videos agree best with: {best['flat']}")
    return rows


def placed_on_moon(base, stem, site=None, say=print):
    """(geometry, facts) of a picture of the Moon from the video `stem`'s
    time: where each pixel is on the Moon, found from the picture and checked
    against the night's plate solve; (None, {}) without a time or a site."""
    geometry, placed = None, {}
    disc = lunar.find_disc(base)
    when = lucky.ser_facts(Path(f"{stem}.ser"))[1] if Path(f"{stem}.ser").exists() else None
    if disc is not None and when is not None:
        try:
            site = site or config.load()["site"]
            look = lunar.view(site, when)
            turn, mirrored, score, other = lunar.fit_turn(base, disc, look)
            geometry = lunar.surface(disc, base.shape, look, turn, mirrored)
            placed = {"turn_deg": round(turn, 1), "mirrored": mirrored, "uplands_over_seas": round(score, 2),
                      "other_way_round": round(other, 2), "margin": round(score / other, 2) if other else None,
                      "under_us": [round(float(v), 2) for v in look["under_us"]],
                      "under_sun": [round(float(v), 2) for v in look["under_sun"]], "time": when.isoformat()}
            say(f"the picture's up is {turn:.0f} degrees east of north{', mirrored' if mirrored else ''}; "
                f"uplands {score:.1f} times the seas' brightness ({other:.1f} the other way round)")
            solved = solved_turn(site, when, look)
            if solved:
                off = abs((solved["turn_deg"] - turn + 180) % 360 - 180)
                solved["differs_by_deg"] = round(off, 1)
                solved["agrees"] = off < SOLVE_AGREES and solved["mirrored"] == mirrored
                placed["plate_solve"] = solved
                say(f"the night's plate solve gives {solved['turn_deg']:.1f} degrees"
                    f"{', mirrored' if solved['mirrored'] else ''}: "
                    + ("agrees" if solved["agrees"] else f"DISAGREES by {off:.0f} degrees"))
            # a solve that agrees settles it; without one, the seas must choose clearly
            placed["sure"] = bool(solved["agrees"] if solved else (placed["margin"] or 0) > 1.1)
        except Exception as error:          # no site, or no ephemeris: the picture is made without the check
            say(f"the Moon's orientation was not found ({error}): no check against the seas")
            geometry, placed = None, {}
    return geometry, placed


def _written(out, facts, stems, geometry, placed, strength, say):
    """The mineral Moon's files beside the first colour video, and what it says."""
    from astropy.io import fits
    from PIL import Image
    if geometry is not None:
        facts["seas"] = check_seas(out["orange"], out["weights"], out["usable"], geometry)
        facts["reference"] = compare_reference(out["ratios"]["log_b_r"], out["confidence"] == 2, geometry)
    for each in facts["left_out"]:
        each["video"] = stems[each["left_out"] - 1].name
    stem = stems[0].with_name(stems[0].name + "-mineral")
    header = fits.Header()
    header["GAIN"] = (facts["display_gain"], "times the colour was turned up")
    header["NATIVE"] = (facts["native_colour"]["p99_percent"], "strongest 1% of colour measured, %")
    header["BANDS"] = ("Hypercam 183C Bayer RGB", "this camera's broad colours, not spacecraft filters")
    fits.PrimaryHDU(out["picture"].astype(np.float32), header=header).writeto(f"{stem}.fits", overwrite=True)
    jpg = lucky.picture(out["picture"], f"{stem}.jpg", balance=False)
    lucky.picture(out["picture"], f"{stem}-fullsize.jpg", balance=False, largest=None)
    lucky.picture(out["full"], f"{stem}-full.jpg", balance=False)
    lucky.picture(out["balanced"], f"{stem}-balanced.jpg", balance=False)
    fits.HDUList([fits.PrimaryHDU(header=fits.Header([("BANDS", "Hypercam 183C Bayer RGB",
                                                       "this camera's B/R index, not Clementine's")]))]
                 + [fits.ImageHDU(v.astype(np.float32), name=k) for k, v in out["ratios"].items()]
                 ).writeto(f"{stem}-ratios.fits", overwrite=True)
    br = out["ratios"]["log_b_r"]
    _picture_of(br, f"{stem}-ratio-br.jpg", *np.percentile(br[out["usable"]], [1, 99]) if out["usable"].any() else (None, None))
    colours_of = np.array([[200, 40, 40], [230, 160, 30], [40, 170, 60]], np.uint8)
    Image.fromarray(colours_of[out["confidence"]]).save(f"{stem}-confidence.jpg", quality=90)
    if out["difference"] is not None:
        fits.PrimaryHDU(out["difference"].astype(np.float32)).writeto(f"{stem}-difference.fits", overwrite=True)
    Path(f"{stem}.json").write_text(json.dumps(facts, indent=1, default=str), encoding="utf-8")
    say(f"colour as measured: the strongest 1 % at {facts['native_colour']['p99_percent']} %; "
        f"turned up {facts['display_gain']:g} times ({strength}): {jpg}")
    for check in facts.get("seas", []):
        say(f"  {check['expected']}: {check['result']}"
            + (f", by {check['bluer_by_percent']} %, in {check['videos_agreeing']} videos"
               if "bluer_by_percent" in check else "")
            + ("" if check.get("holds_without_any_one_video", True) else "; not without every video")
            + (f" (consistency score {check['consistency_score']})" if "consistency_score" in check else ""))
    if placed and not placed["sure"]:
        say("  the orientation is not sure, so neither is the check above")
    f = facts["follows"]
    say(f"the colour follows {f['verdict']}" + (f": r {f['r_on_the_moon']} lined up on the Moon, "
                                                 f"{f['r_on_the_sensor']} on the sensor" if "r_on_the_moon" in f else ""))
    say(f"the slope was fitted on {facts['slope_fitted_on']}")
    ref = facts.get("reference")
    if ref and "rank_correlation" in ref:
        say(f"against the spacecraft map ({ref['source']}): rank correlation {ref['rank_correlation']} over "
            f"{ref['cells']} cells of {REFERENCE_CELL:g} degrees"
            + (f"; the seas in order {ref['seas_rank_correlation']}" if "seas_rank_correlation" in ref else ""))
    elif geometry is not None and ref is None:
        say("no spacecraft map to compare with: ./ty lucky reference FILE.tif makes one")
    return jpg, facts


def run(stems, details=None, strength="standard", slope="bright", send=True):
    """The command: make it, and send the picture to the person's phone
    (not with `send` off, for a run made only to compare)."""
    jpg, facts = mineral_file(stems, details=details, strength=strength, slope=slope)
    if not send:
        return jpg, facts
    import notify
    seas = "; ".join(f"{c['expected']}: {c['result']}" for c in facts.get("seas", []))
    notify.stack_ready(f"Mineral Moon from {facts['videos']} videos, colour turned up {facts['display_gain']:g} times"
                       + (f". {seas}" if seas else ""), jpg, full=jpg.with_name(jpg.stem + "-fullsize.jpg"))
    return jpg, facts

