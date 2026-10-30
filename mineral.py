#!/usr/bin/env python3
"""The Moon's faint colour turned up: a "mineral Moon".

    ./lucky.py mineral COLOUR.ser ... [--detail DETAIL.ser ...] [--strength standard]
    ./ty moon --mineral          takes the videos for it and runs this

The Moon's colours are real but faint, a percent or two either way. On
spacecraft maps the bluer seas are richer in titanium and the browner ones
poorer, and fresh ground is bluer than old: so the colours here follow the
surface's make-up and age. They are not a measurement of it. A colour
camera's three broad, overlapping filters cannot give titanium or iron
abundances (Earth and Space Science, 2023, doi:10.1029/2022EA002710): what
they show is enhanced colour that goes with composition and maturity.

What it does, from stacked videos (lucky.py stack --colour):

- the detail from each video's sharpest stack, the colour from its largest
  share (colour needs many frames more than it needs sharpness), every
  stack lined up on the first;
- red and blue moved onto green, as low in the sky the air spreads them;
- pixels a video clipped left out of it, fading out rather than stopping;
- the colour worked out on 2x2 blocks, as log ratios of each colour to the
  three's mean, which turn a change of exposure or light into an offset;
- a slope across the disc taken off, fitted to the bright uplands only, so
  that a large sea's own colour is not mistaken for it;
- each video's colour compared with the others': colour that does not
  repeat from video to video is turned down (more than one video needed);
- the result turned up by a stated factor.

Beside the first colour video, NAME-mineral:

    .jpg .fits         blue against orange only: the safe picture
    -full.jpg          every colour kept: exploratory, as the camera adds a
                       green-magenta tint of its own that may not all be gone
    -natural.jpg       the colour as it is, the detail sharpened
    -ratios.fits       log B/R, R/G and B/G after calibration
    -ratio-br.jpg      log B/R as grey: brighter is bluer
    -confidence.jpg    green: robust; amber: faint, near the edge or the
                       terminator, or not repeated; red: clipped or off the Moon
    -difference.fits   the first two videos' blue-orange, one less the other
    .json              the colour as measured, the factor it was turned up by,
                       each video's depth, white level, clipping and flat, how
                       well the videos agree, and the check against the seas

The check against the seas: the Moon's orientation (lunar.py) puts the
named seas on the picture, and spacecraft colour maps say Mare
Tranquillitatis is bluer than Mare Serenitatis and than the uplands (NASA's
Galileo colour Moon, science.nasa.gov/resource/colorful-moon). The json
says whether this picture agrees, by how much, and how sure.

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
    agree: (signal / its standard error, the videos' correlations two by
    two over `where`). With one video it cannot be told: (None, [])."""
    n = len(maps)
    if n < 2:
        return None, []
    w = np.array(weights)
    total = np.maximum(w.sum(axis=0), 1e-6)
    mean = (w * np.array(maps)).sum(axis=0) / total
    spread = np.sqrt((w * (np.array(maps) - mean) ** 2).sum(axis=0) / total)
    effective = total ** 2 / np.maximum((w ** 2).sum(axis=0), 1e-6)
    error = spread / np.sqrt(np.maximum(effective - 1, 1e-6))
    sigma = np.abs(mean) / np.maximum(error, 1e-6)
    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            both = where & (weights[i] > 0.5) & (weights[j] > 0.5)
            if both.sum() > 10:
                pairs.append(round(float(np.corrcoef(maps[i][both], maps[j][both])[0, 1]), 3))
    return sigma, pairs


def mineral(colours, details, strength="standard", blur=COLOUR_BLUR, ceilings=None, detail_ceilings=None,
            geometry=None):
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

    raw, weights, clipped = [], [], []
    for c, ceiling in zip(colours, ceilings):
        good = unclipped(c, ceiling)
        c = channels_lined_up(c)
        shift = lucky.whole_shift(base, _level(c))
        c = np.stack([_onto(c[..., k], shift) for k in range(3)], -1)
        weight = _onto(feathered(good), shift)
        raw.append(log_tint(c, lit & (weight > 0.5)))
        weights.append(weight)
        own = _level(colours[len(clipped)])
        clipped.append(round(float(1 - good[own > 0.08 * np.percentile(own, 99.9)].mean()), 4))
    total = np.sum(weights, axis=0)
    usable = lit & (total > 0.5)
    inner = ndimage.binary_erosion(usable, iterations=int(4 * blur) + 1)       # the limb's rims kept out
    uplands = inner & (base > np.median(base[inner])) if inner.any() else inner
    smooth = lambda t: np.stack([ndimage.gaussian_filter(t[..., k], blur) for k in range(3)], -1)  # noqa: E731
    tints = [smooth(flattened(t, uplands & (w > 0.5))) for t, w in zip(raw, weights)]
    mean = sum(t * w[..., None] for t, w in zip(tints, weights)) / np.maximum(total, 1e-6)[..., None]
    natural_tint = sum(smooth(t) * w[..., None] for t, w in zip(raw, weights)) / np.maximum(total, 1e-6)[..., None]
    orange = [(t[..., 0] - t[..., 2]) / 2 for t in tints]
    sigma, pairs = repeatability(orange, weights, inner)
    keep = np.ones_like(base) if sigma is None else np.clip(sigma / 2, 0, 1)     # 2 standard errors: kept whole
    edge = ndimage.gaussian_filter(inner.astype(np.float32), blur)
    tint = mean * (keep * edge)[..., None]
    safe = blue_to_orange(tint)
    gain = gain_for(strength, safe, inner)
    measured = (mean[..., 0] - mean[..., 2]) / 2
    native = {"p99_percent": round(100 * float(np.percentile(np.abs(measured[inner]), 99)), 3) if inner.any() else 0,
              "spread_percent": round(100 * float(measured[inner].std()), 3) if inner.any() else 0}

    confidence = np.full(base.shape, 2, np.uint8)
    weak = ~inner | (base < 0.25 * np.percentile(base, 99.9))
    if sigma is not None:
        weak |= sigma < 2
    if geometry is not None:
        weak |= (geometry["cos_i"] < STEEP) | (geometry["cos_e"] < STEEP)
    confidence[weak] = 1
    confidence[~usable] = 0
    ratios = {"log_b_r": (mean[..., 2] - mean[..., 0]) * usable, "log_r_g": (mean[..., 0] - mean[..., 1]) * usable,
              "log_b_g": (mean[..., 2] - mean[..., 1]) * usable}
    return {"picture": np.clip(detail[..., None] * np.exp(gain * safe), 0, None),
            "full": np.clip(detail[..., None] * np.exp(gain * tint), 0, None),
            "natural": np.clip(detail[..., None] * np.exp(natural_tint * edge[..., None]), 0, None),
            "ratios": ratios, "confidence": confidence, "orange": orange, "weights": weights, "usable": usable,
            "difference": orange[0] - orange[1] if len(orange) > 1 else None,
            "facts": {"display_gain": round(gain, 2), "strength": strength, "native_colour": native,
                      "videos": len(colours), "clipped_share": clipped, "agreement": pairs,
                      "repeatability": "measured" if sigma is not None else "one video: not measured",
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
    for name, places in (("Mare Serenitatis", [lunar.SEAS["Mare Serenitatis"]]),
                         ("the uplands", list(lunar.HIGHLANDS.values()))):
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
            if len(each) > 1 and np.std(each, ddof=1) > 0:
                check["sigma"] = round(diff / (np.std(each, ddof=1) / np.sqrt(len(each))), 1)
            check["result"] = "agrees" if diff > 0 else "disagrees"
        checks.append(check)
    return checks


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


def mineral_file(stems, details=None, strength="standard", site=None, say=print):
    """The mineral Moon from stacked videos named by their stem (the SER
    file without .ser): colour from each one's largest share, detail from
    the share each showed (from `details` when given). Writes the files the
    module's notes list beside the first. Returns (picture, facts)."""
    from astropy.io import fits
    from PIL import Image
    stems = [Path(str(s).removesuffix(".ser")) for s in stems]
    detail_stems = [Path(str(s).removesuffix(".ser")) for s in (details or stems)]
    colours, ceilings, flats = [], [], []
    for stem in stems:
        done = json.loads(stem.with_suffix(".stack.json").read_text(encoding="utf-8"))
        largest = max(done["kept"], key=float)
        colours.append(fits.getdata(stem.with_name(f"{stem.name}.best{largest}.fits")))
        ceilings.append(white_level(stem))
        flats.append(done.get("flat"))
        say(f"{stem.name}: colour from the best {largest} %, white level {ceilings[-1]:g}, "
            f"{'flat ' + Path(done['flat']).name if done.get('flat') else 'no flat'}")
    detail_images, detail_ceilings = [], []
    for stem in detail_stems:
        done = json.loads(stem.with_suffix(".stack.json").read_text(encoding="utf-8"))
        detail_images.append(fits.getdata(stem.with_name(f"{stem.name}.best{done['shown']}.fits")))
        detail_ceilings.append(white_level(stem))
    base = _level(detail_images[0])
    geometry, placed = None, {}
    disc = lunar.find_disc(base)
    when = lucky.ser_facts(Path(f"{detail_stems[0]}.ser"))[1] if Path(f"{detail_stems[0]}.ser").exists() else None
    if disc is not None and when is not None:
        try:
            site = site or config.load()["site"]
            look = lunar.view(site, when)
            turn, mirrored, score = lunar.fit_turn(base, disc, look)
            geometry = lunar.surface(disc, base.shape, look, turn, mirrored)
            placed = {"turn_deg": round(turn, 1), "mirrored": mirrored, "uplands_over_seas": round(score, 2),
                      "under_us": [round(float(v), 2) for v in look["under_us"]],
                      "under_sun": [round(float(v), 2) for v in look["under_sun"]], "time": when.isoformat()}
            say(f"the picture's up is {turn:.0f} degrees east of north{', mirrored' if mirrored else ''}; "
                f"uplands {score:.1f} times the seas' brightness")
        except Exception as error:          # no site, or no ephemeris: the picture is made without the check
            say(f"the Moon's orientation was not found ({error}): no check against the seas")
            geometry = None
    out = mineral(colours, detail_images, strength=strength, ceilings=ceilings, detail_ceilings=detail_ceilings,
                  geometry=geometry)
    facts = dict(out["facts"], colour_videos=[s.name for s in stems], detail_videos=[s.name for s in detail_stems],
                 white_levels=ceilings, flats=flats, orientation=placed or None)
    if geometry is not None:
        facts["seas"] = check_seas(out["orange"], out["weights"], out["usable"], geometry)
    stem = stems[0].with_name(stems[0].name + "-mineral")
    header = fits.Header()
    header["GAIN"] = (facts["display_gain"], "times the colour was turned up")
    header["NATIVE"] = (facts["native_colour"]["p99_percent"], "strongest 1% of colour measured, %")
    fits.PrimaryHDU(out["picture"].astype(np.float32), header=header).writeto(f"{stem}.fits", overwrite=True)
    jpg = lucky.picture(out["picture"], f"{stem}.jpg", balance=False)
    lucky.picture(out["full"], f"{stem}-full.jpg", balance=False)
    lucky.picture(out["natural"], f"{stem}-natural.jpg", balance=False)
    fits.HDUList([fits.PrimaryHDU()] + [fits.ImageHDU(v.astype(np.float32), name=k) for k, v in out["ratios"].items()]
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
            + (f", by {check['bluer_by_percent']} %" if "bluer_by_percent" in check else "")
            + (f" ({check['sigma']} sigma)" if "sigma" in check else ""))
    return jpg, facts


def run(stems, details=None, strength="standard"):
    """The command: make it, and send the picture to the person's phone."""
    jpg, facts = mineral_file(stems, details=details, strength=strength)
    import notify
    seas = "; ".join(f"{c['expected']}: {c['result']}" for c in facts.get("seas", []))
    notify.stack_ready(f"Mineral Moon from {facts['videos']} videos, colour turned up {facts['display_gain']:g} times"
                       + (f". {seas}" if seas else ""), jpg)
    return jpg, facts

