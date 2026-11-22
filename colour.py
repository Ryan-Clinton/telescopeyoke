#!/usr/bin/env python3
"""One colour picture from a mono camera's stacks in L, R, G and B, or in narrowband.

    ./colour.py "NGC 281"              the deepest stack in each filter -> web/NGC281-colour.jpg
    ./colour.py "NGC 281" --night 20261104      only that night's sessions
    ./colour.py "NGC 281" --saturation 1.6      stronger colour
    ./colour.py "NGC 281" --palette SHO         the Hubble palette -> web/NGC281-SHO.jpg
    ./colour.py "NGC 281" --palette HOO         Ha red, OIII green and blue -> web/NGC281-HOO.jpg

The 183M takes one filter at a time (shoot.py --filter, --blocks), and each
filter's session is stacked on its own: stacking never mixes filters. This
lines the R, G and B stacks up on the L stack by their stars (stacking.py's
own star matching), makes the colour from R, G and B, balanced on the stars
so the sky comes out grey (process.py), and takes the detail from L: the
colour picture's brightness is replaced by L's. L is the deepest and, at one
focus for the parfocal set, the sharpest, so a softer B (4 November 2026: HFR
2.32 against L's 1.92) blurs only the colour, which the eye forgives.

Without L, the R, G and B stacks make the picture alone; without all three of
R, G and B, there is no colour and it says so. Filters that frame different
sky (sharing under 75% of the frame) are refused, as the target would be cut
off (--any-coverage makes it anyway). Nothing is moved or exposed.

Narrowband (--palette): SHO puts SII in red, Ha in green and OIII in blue
(the Hubble palette); HOO puts Ha in red and OIII in both green and blue,
the nebula's own colours more or less, and needs no SII. Every filter is
lined up on the Ha stack, which has the most stars, and the balance is made
on the stars as for R, G and B, so the stars come out near white and the
nebula takes the palette's colours. There is no L to take the detail from.
The filters are mixed while still linear, their star widths matched, with one
stretch at the end (--stretched: the earlier method). The linear colour is
kept beside the picture as NAME-PALETTE-linear.fits, a picture product and not
for measurement. A stack not calibrated makes a picture called a preview.
"""
import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path

import numpy as np
from astropy.io import fits
from PIL import Image
from scipy import ndimage, signal

import config
import interface
import process
import records
import stacking
import storage

COLOURS = ("R", "G", "B")
# palette: (the filter in red, in green, in blue), the filter lined up on,
# the filter giving the detail (None: the colour's own brightness)
PALETTES = {"LRGB": (COLOURS, "L", "L"),
            "SHO": (("SII", "Ha", "OIII"), "Ha", None),
            "HOO": (("Ha", "OIII", "OIII"), "Ha", None),
            "HSS": (("Ha", "SII", "SII"), "Ha", None)}   # no OIII yet: Ha red, SII green and blue


def holds(session):
    """The names of the sessions in a stack: its own, or a combination's."""
    if not session.name.startswith("combined-"):
        return {session.name}
    try:
        kept = json.loads((session / "restack.json").read_text(encoding="utf-8"))["summary"]["sessions"]
    except (OSError, ValueError, KeyError, TypeError):
        return set()
    return {Path(s).name for s in kept}


def sessions(name, night=None, say=None):
    """{filter: the deepest stack} for this object: each session's own, and
    restack.py's combinations of several (combined-FILTER), the one with the
    most exposure winning. 5 November 2026: the newest won, so a 28-frame
    restart of M33 in L would have stood in for the 126-frame stack. With a
    night, a combination counts only if all it holds is from that night.
    Sessions left out of the stack chosen are said, not added: whether they
    belong together is restack's to judge (21 November 2026: NGC 2174's 16 s
    Ha mixed with its 120 s lost most of the deep frames)."""
    folder = config.DATA / "frames" / stacking.folder_name(name)
    found, dated = {}, {}
    for session in sorted(p for p in folder.glob("*") if p.is_dir()):
        combined = session.name.startswith("combined-")
        if not (combined or session.name[:8].isdigit()):
            continue
        if night and not (all(s.startswith(night) for s in holds(session)) and holds(session)):
            continue
        stack = next((session / f for f in ("final.fits", "live.fits") if (session / f).exists()), None)
        if stack is None:
            continue
        if combined:
            band = session.name.split("-", 1)[1]
        else:
            light = next(iter(sorted(session.glob("light-*.fits"))), None)
            if light is None:
                continue
            band = stacking.load_light(light)[1].get("FILTER")   # in the compressed image's header, not the primary
        if not band:
            continue
        if not combined:
            dated.setdefault(str(band), []).append(session.name)
        depth = float(fits.getheader(stack).get("EXPTIME") or 0)
        if depth >= found.get(str(band), (0.0, None))[0]:
            found[str(band)] = (depth, stack)
    if say:
        for band, (_, stack) in sorted(found.items()):
            left = [s for s in dated.get(band, []) if s not in holds(stack.parent)]
            if left:
                say(f"  {band}: not in the stack used: {', '.join(left)} (./restack.py can combine them)")
    return {band: stack for band, (_, stack) in found.items()}


def brightness(path):
    """A stack as one brightness image (a mono stack keeps three equal planes)."""
    data = fits.getdata(path).astype(np.float32)
    return data.mean(axis=0) if data.ndim == 3 else data


def covered(image):
    """Where a stack has data. Stack.result() writes zero where no frame
    reached, so a zero region joined to the frame's edge is empty; a lone
    zero inside the picture is a real value."""
    return ndimage.binary_fill_holes(np.nan_to_num(image) != 0)


def fits_well(info):
    """Enough stars matched, and they landed where they should."""
    return (stacking.lined_up(info["matched"]) and info["residual"] is not None
            and info["residual"] <= stacking.FLIP_RESIDUAL)


def lined_up(image, reference):
    """`image` moved onto `reference` (a dict of its "square" and "stars").
    Stacks from either side of the meridian are half a turn apart, so a stack
    that does not match is tried turned round (21 November 2026: NGC 2174's
    Ha before the flip, its OIII and SII after). So is one that matches
    enough stars but fits them badly, which chance can do. Returns the image,
    the match, and whether it was turned."""
    # The stack's coverage moves with it, as a second plane.
    planes = np.stack([image, covered(image).astype(image.dtype)], axis=2)
    placed = lambda moved: np.where(moved[..., 1] > 0.99, moved[..., 0], np.nan)
    stars = stacking.find_stars(np.nan_to_num(image))
    moved, info = stacking.register(planes, np.nan_to_num(image), stars, reference)
    if not fits_well(info):
        turned = np.ascontiguousarray(planes[::-1, ::-1])
        clean = np.nan_to_num(turned[..., 0])
        again, second = stacking.register(turned, clean, stacking.find_stars(clean), reference)
        if fits_well(second) or (not fits_well(info) and second["matched"] > info["matched"]):
            return placed(again), second, True
    return placed(moved), info, False


def restack_plan(name):
    """For each filter, the sessions worth stacking together: those at the
    settings holding the most light, as restack.py would be told them. Every
    frame's header is read. A session with more than one set of settings is
    left out and named, as restack.py takes the first frame's for them all
    (M34's of 19 October 2026 changed gain part way). Mixing lengths lost
    NGC 2174's deep Ha frames (21 November 2026)."""
    folder = config.DATA / "frames" / stacking.folder_name(name)
    found, mixed = {}, {}
    for session in sorted(p for p in folder.glob("*") if p.is_dir() and p.name[:8].isdigit()):
        counts = {}
        for light in session.glob("light-*.fits"):
            head = stacking.load_light(light)[1]
            key = (str(head.get("FILTER") or ""), float(head.get("EXPTIME") or 0), head.get("GAIN"), head.get("OFFSET"),
                   head.get("XBINNING")) + stacking.camera_of(head)
            counts[key] = counts.get(key, 0) + 1
        bands = {k[0] for k in counts}
        if len(counts) > 1:
            for band in bands:
                mixed.setdefault(band or "no filter", []).append(str(session.relative_to(config.DATA)))
        elif counts:
            key, frames = next(iter(counts.items()))
            if key[1]:
                found.setdefault(key[0] or "no filter", {}).setdefault(key[1:], []).append((session, frames))
    plan = {}
    for band in sorted(set(mixed) - set(found)):
        plan[band] = {"exposure_s": 0.0, "gain": None, "camera": None, "frames": 0, "minutes": 0.0, "sessions": [],
                      "left_out": [], "mixed_settings": mixed[band]}
    for band, sets in sorted(found.items()):
        best = max(sets, key=lambda k: k[0] * sum(n for _, n in sets[k]))
        chosen = sets[best]
        plan[band] = {"exposure_s": best[0], "gain": best[1], "camera": best[4], "frames": sum(n for _, n in chosen),
                      "minutes": round(best[0] * sum(n for _, n in chosen) / 60, 1),
                      "sessions": [str(p.relative_to(config.DATA)) for p, _ in chosen],
                      "left_out": [str(p.relative_to(config.DATA)) for k, v in sets.items() if k != best for p, _ in v],
                      "mixed_settings": mixed.get(band, [])}
    return plan


MIN_COVERED = 0.75   # share of the frame every filter must cover for the target to be in the picture
GREEN_KEPT = 0.25    # of the green above the red and blue's average, in the Hubble palette
LINEAR_OIII = 0.55   # OIII (SII in HSS) fills two channels in HOO: mixed linearly at full strength the nebula goes grey
NARROWBAND_SATURATION = 1.8   # mixed linearly the palette is paler than separate stretches' colours
EDGE_TRIM = 0.035    # of the picture's shorter side, off every edge of a linear narrowband picture
QUIET = (0.7, 0.6, 0.5, 0.4)    # times its noise each scale needs to be fully kept: at this, on NGC 2174, 99% of the faintest stars stay, their flux within 1%
MIN_CLEAR = 0.3      # of the frame clear of nebula, or the sky is not mapped
PICTURE_VERSION = 5  # of the method below: changes what the same stacks give
EDGE_BAND = 0.25     # of the shorter side: how far in from the edge the sky map acts
CONTRAST = 0.3       # how far local contrast may lift or lower the nebula
SKY_CELLS = 5        # how smooth the sky map is, in cells of 16 pixels: far wider than any star
STAR_REACH = 18      # px each way that a star's peak is carried when making it smaller
STAR_FADE = 6.0      # px: how fast that peak fades with distance
STAR_TINT = 0.25     # of each star's colour kept: a filter's stars differ by more than the eye expects
OIII_SHARE = 0.8     # OIII fills two channels in HOO: at full strength the stars come out cyan


def star_width(plane):
    """The median width (FWHM, pixels) of a plane's brighter stars."""
    stars = stacking.find_stars(np.nan_to_num(plane))
    return float(np.median(stars[:100, 3])) if len(stars) else None


def matched_widths(planes, say=print):
    """Every filter's stars blurred to the widest filter's, flux unchanged, so
    a star is one colour across its width. 21 November 2026: NGC 2174's Ha
    stars were about 25% wider than OIII's and SII's, which left them with
    red rims and cyan cores. The widest is never sharpened."""
    widths = {b: star_width(p) for b, p in planes.items()}
    known = [w for w in widths.values() if w]
    if len(known) < len(widths):
        say("  star widths: not measured in every filter, left as they are")
        return dict(planes), widths, widths
    target = max(known)
    out = {}
    for band, plane in planes.items():
        sigma = np.sqrt(max(target ** 2 - widths[band] ** 2, 0)) / 2.355
        out[band] = ndimage.gaussian_filter(plane, sigma) if sigma > 0 else plane
    after = {b: star_width(p) for b, p in out.items()}
    say("  star widths: " + ", ".join(f"{b} {widths[b]:.2f} -> {after[b]:.2f} px" for b in planes))
    return out, widths, after


def nebula_level(plane):
    """How strong a filter's nebula is, with the stars medianed away."""
    small = ndimage.median_filter(plane[::4, ::4], 5)
    return max(float(np.percentile(small, 99.5)), 1e-6)


def smoothed(plane):
    """The plane with its stars medianed away, at full size."""
    small = ndimage.median_filter(plane[::4, ::4], 9)
    return ndimage.zoom(small, (plane.shape[0] / small.shape[0], plane.shape[1] / small.shape[1]), order=1)


def star_mask(light):
    """0 to 1: where the stars are, in a linear brightness image."""
    rest = light - smoothed(light)
    spread = 1.4826 * np.median(np.abs(rest - np.median(rest))) + 1e-6
    return np.clip(ndimage.gaussian_filter((rest > 5 * spread).astype(np.float32), 2.0) * 3, 0, 1)


def sky_surface(plane, clear):
    """A gentle bowl fitted to the plane where `clear` says there is no nebula."""
    rows, cols = plane.shape
    yy, xx = np.mgrid[0:rows:16, 0:cols:16]
    sample = ndimage.median_filter(plane[::16, ::16], 5)
    use = clear[::16, ::16] & (sample != 0)
    terms = lambda y, x: [np.ones_like(y), y, x, y * y, x * x, y * x]
    design = np.column_stack([t[use] for t in terms(yy / rows, xx / cols)])
    fit, *_ = np.linalg.lstsq(design, sample[use], rcond=None)
    full_y, full_x = np.mgrid[0:rows, 0:cols]
    return sum(k * t.astype(np.float32) for k, t in zip(fit, terms(full_y / rows, full_x / cols)))


def clear_of_nebula(guide):
    """Where the sky is, from the filter showing the nebula best, judged
    after a first bowl is off: on the raw level a gradient across the frame
    counted a whole side of the sky as nebula (21 November 2026)."""
    shape = smoothed(guide)
    rest = shape - sky_surface(shape, shape < np.percentile(shape, 50))
    middle = np.median(rest)
    bright = rest >= middle + 2 * 1.4826 * np.median(np.abs(rest - middle))
    # Every bright patch is nebula, however many there are, except a smaller
    # one lying along the frame's edge: that is the glow the map must follow.
    coarse = ndimage.binary_opening(bright[::8, ::8], iterations=2)
    labels, count = ndimage.label(coarse)
    if not count:
        return ~bright
    sizes = ndimage.sum_labels(coarse, labels, range(1, count + 1))
    largest = int(np.argmax(sizes)) + 1
    edge = set(labels[0]) | set(labels[-1]) | set(labels[:, 0]) | set(labels[:, -1])
    kept = [n for n in range(1, count + 1) if n == largest or n not in edge]
    nebula = ndimage.binary_dilation(np.isin(labels, kept), iterations=3)
    full = np.repeat(np.repeat(nebula, 8, axis=0), 8, axis=1)[:guide.shape[0], :guide.shape[1]]
    return ~full


def sky_model(plane, clear):
    """The bowl, plus what it misses: a smooth map of the clear sky's
    remainder, carried across the nebula. 21 November 2026: NGC 2174's SII and
    OIII keep a bright patch at one corner of the sensor, which no bowl follows."""
    bowl = sky_surface(plane, clear)
    rest = ndimage.median_filter((plane - bowl)[::16, ::16], 5)
    weight = (clear[::16, ::16] & (plane[::16, ::16] != 0)).astype(np.float32)
    level = ndimage.gaussian_filter(rest * weight, SKY_CELLS, mode="nearest")
    share = ndimage.gaussian_filter(weight, SKY_CELLS, mode="nearest")
    extra = level / np.maximum(share, 0.05)
    # Only towards the frame's edge, where the patch is. Across the middle it
    # also took off faint nebula: planted glows lost 15 to 60% of their light.
    rows, cols = extra.shape
    yy, xx = np.ogrid[:rows, :cols]
    inward = np.minimum(np.minimum(yy, rows - 1 - yy), np.minimum(xx, cols - 1 - xx))
    extra = extra * np.clip(1 - inward / (EDGE_BAND * min(rows, cols)), 0, 1)
    return bowl + ndimage.zoom(extra, (plane.shape[0] / extra.shape[0], plane.shape[1] / extra.shape[1]), order=1)


def fine_grain(plane, clear):
    """The pixel-to-pixel grain in the clear sky."""
    fine = plane - ndimage.gaussian_filter(plane, 2)
    sky = fine[::2, ::2][clear[::2, ::2]]
    return 1.4826 * float(np.median(np.abs(sky - np.median(sky))))


def quietened(plane, clear):
    """The nebula's grain reduced, scale by scale (a starlet transform). Each
    scale's noise is measured in the clear sky; detail well above it is kept
    whole, detail at its level goes, and what is left over at the largest
    scale is never touched, so the nebula's overall light does not change."""
    smooth, out = plane, None
    details = []
    for level in range(len(QUIET)):
        kernel = np.zeros(4 * 2 ** level + 1, np.float32)
        kernel[:: 2 ** level] = np.array([1, 4, 6, 4, 1], np.float32) / 16
        wider = ndimage.convolve1d(ndimage.convolve1d(smooth, kernel, axis=0, mode="mirror"), kernel, axis=1, mode="mirror")
        details.append(smooth - wider)
        smooth = wider
    out = smooth
    for detail, strength in zip(details, QUIET):
        sky = detail[::3, ::3][clear[::3, ::3]]
        limit = strength * 1.4826 * float(np.median(np.abs(sky - np.median(sky))))
        out = out + detail * np.clip((np.abs(detail) - limit) / max(limit, 1e-6), 0, 1)
    return out


def layers(plane, star):
    """A linear plane as (nebula, stars), which add back up to it. Only the
    stars' own pixels are replaced, so the nebula keeps its fine detail."""
    nebula = star * smoothed(plane) + (1 - star) * plane
    return nebula, plane - nebula


def star_gain(stars, power):
    """How much of each pixel of a star layer to keep, so that each star
    keeps its peak and loses its wings: raising a star's profile to `power`
    narrows it by the square root of that. One gain for every filter, so a
    star's colour does not change."""
    floor = 1.4826 * float(np.median(np.abs(stars - np.median(stars)))) + 1e-6
    bright = np.maximum(stars, floor)
    # Each star's peak, fading smoothly with distance. A flat window ended
    # abruptly 7 px out, which let the wing back as a ring round the star.
    reach = np.arange(-STAR_REACH, STAR_REACH + 1)
    fade = -reach.astype(np.float32) ** 2 / (2 * STAR_FADE ** 2)
    peak = ndimage.grey_dilation(np.log(bright), footprint=np.ones((1, reach.size), bool), structure=fade[None, :])
    peak = ndimage.grey_dilation(peak, footprint=np.ones((reach.size, 1), bool), structure=fade[:, None])
    return np.clip((np.maximum(stars, 0) / np.exp(peak)) ** (power - 1), 0, 1)


def sharpened(nebula, fwhm, iterations):
    """A star-free layer with a few Richardson-Lucy steps, the blur taken as
    a round Gaussian of the stars' measured width. On NGC 2174's Ha, 3 steps
    raised the fine detail by a third with the grain up 4% and the agreement
    with another night's stack almost unchanged (r 0.175 to 0.172); by 20
    steps two planted lines rang and the agreement had fallen to 0.135."""
    sigma = fwhm / 2.355
    reach = int(4 * sigma) + 1
    yy, xx = np.mgrid[-reach:reach + 1, -reach:reach + 1]
    psf = np.exp(-(yy * yy + xx * xx) / (2 * sigma * sigma))
    psf = (psf / psf.sum()).astype(np.float32)
    lift = max(0.0, -float(np.percentile(nebula, 0.1))) + 3 * 1.4826 * float(np.median(np.abs(nebula - np.median(nebula))))
    data = np.maximum(nebula + lift, 1e-3)
    estimate = data.copy()
    for _ in range(iterations):
        blurred = signal.fftconvolve(estimate, psf, mode="same")
        estimate = estimate * signal.fftconvolve(data / np.maximum(blurred, 1e-6), psf, mode="same")
    # Only where the nebula stands above the grain: on faint sky it sharpens noise.
    grain = 1.4826 * float(np.median(np.abs(nebula - ndimage.gaussian_filter(nebula, 3)))) + 1e-6
    where = np.clip(ndimage.gaussian_filter(nebula, 8) / (2 * grain), 0, 1)
    return (where * (estimate - lift) + (1 - where) * nebula).astype(np.float32)


def contrast_gain(nebula, where):
    """The nebula's ridges and lanes brought out: its structure between
    about 3 and 24 pixels across, measured on the star-free layer so no star
    gets a halo, and applied as a gain, so colours keep their ratios.
    `where` (0 to 1) keeps it off the sky. Medians, not Gaussians: beside a
    planted hard edge the dark rim was 22 px wide against 73."""
    soft = np.arcsinh(np.maximum(nebula, 0))
    wide = ndimage.median_filter(soft[::4, ::4], 13)
    wide = ndimage.zoom(wide, (soft.shape[0] / wide.shape[0], soft.shape[1] / wide.shape[1]), order=1)
    band = ndimage.gaussian_filter(ndimage.median_filter(soft, 5), 1.5) - ndimage.gaussian_filter(wide, 4)
    inside = band[where > 0.5]
    spread = 1.4826 * float(np.median(np.abs(inside - np.median(inside)))) + 1e-6 if inside.size else 1.0
    gain = 1 + CONTRAST * np.clip(band / (3 * spread), -1, 1) * where
    return gain


def linear_narrowband(rgb, channels, saturation, background=2, say=print, quiet=False, contrast=True,
                      star_power=1.0, sharpen=0, ghs=False):
    """The narrowband picture made in the light's own units: sky off, star
    widths matched, the palette mixed, and one stretch at the very end.
    Nebula and stars are balanced apart: the nebula on its own strength, so
    faint OIII and SII show, the stars on their own flux, so they stay near
    white. One scale for both turned every star cyan (21 November 2026: OIII's
    nebula is weak, so scaling it up scaled its stars up too). Brightness
    comes from the unblurred filters, so matching widths costs no sharpness.
    Returns the picture (0 to 255, unrounded), the linear colour, and what
    was done."""
    planes = {}
    for c, band in enumerate(channels):
        if band not in planes:
            # A level only: a surface is fitted once the nebula is masked.
            planes[band] = process.remove_sky(rgb[..., c, None].astype(np.float32), 0)[..., 0]
    # Where the sky is, from the filter that shows the nebula best: a weak
    # filter cannot tell its own nebula from its sky, and scaled up to match,
    # NGC 2174's SII turned the sky red (21 November 2026).
    # In HSS the SII is too faint to say: guided by it, IC 405's outer Ha was
    # fitted as sky, leaving black round the nebula (22 November 2026).
    guide = "Ha" if channels[1] == "SII" else max(planes, key=lambda b: nebula_level(planes[b]))
    clear = clear_of_nebula(planes[guide])
    open_sky = float(clear.mean())
    if open_sky >= MIN_CLEAR:
        planes = {b: p - sky_model(p, clear) for b, p in planes.items()}
        say(f"  sky fitted outside the nebula as {guide} shows it ({open_sky:.0%} of the frame is clear)")
    else:
        # A target filling the frame leaves too little sky to map: what the
        # map took off would be the target. One the catalogue calls frame-filling
        # keeps the level alone.
        if background:
            planes = {b: process.remove_sky(p[..., None].copy(), 1)[..., 0] for b, p in planes.items()}
        say(f"  only {open_sky:.0%} of the frame is clear of nebula: no sky map, "
            + ("only the tilt" if background else "only the level"))
    scale = {b: nebula_level(p) for b, p in planes.items()}
    even, before, after = matched_widths(planes, say)
    star = star_mask(np.mean([p / scale[b] for b, p in planes.items()], axis=0))
    core = star > 0.5
    nebula, stars, sharp_nebula, sharp_stars, flux, grain, untouched = {}, {}, {}, {}, {}, {}, {}
    for band in planes:
        nebula[band], stars[band] = layers(even[band], star)
        sharp_nebula[band], sharp_stars[band] = layers(planes[band], star)
        untouched[band] = sharp_nebula[band]
        if quiet:
            before_grain = fine_grain(nebula[band], clear)
            nebula[band] = quietened(nebula[band], clear)
            sharp_nebula[band] = quietened(sharp_nebula[band], clear)
            grain[band] = round(fine_grain(nebula[band], clear) / max(before_grain, 1e-6), 2)
        if sharpen and before.get(band):
            sharp_nebula[band] = sharpened(sharp_nebula[band], before[band], sharpen)
        bright = stars[band][core]
        flux[band] = max(float(bright[bright > 0].mean()) if (bright > 0).any() else 0.0, 1e-6)
    # The stars' overall brightness, as they would have had on the nebula's scales.
    level = float(np.mean([flux[b] / scale[b] for b in planes]))
    colour = np.stack([nebula[b] / scale[b] for b in channels], axis=2)
    if channels[1] == "Ha":
        total = colour.mean(axis=2)
        limit = (colour[..., 0] + colour[..., 2]) / 2
        colour[..., 1] = np.minimum(colour[..., 1], limit + GREEN_KEPT * np.maximum(colour[..., 1] - limit, 0))
        positive = np.maximum(colour.mean(axis=2), 1e-6)
        colour *= np.clip(np.where(total > 0, total / positive, 1), 1.0, 1.6)[..., None]
    else:
        colour[..., 1:] *= LINEAR_OIII
    even_stars = np.stack([stars[b] / flux[b] * level for b in channels], axis=2)
    white = even_stars.mean(axis=2, keepdims=True)
    star_colour = white + STAR_TINT * (even_stars - white)
    star_light = np.mean([sharp_stars[b] / flux[b] * level for b in channels], axis=0)
    plain_light = np.mean([sharp_nebula[b] / scale[b] for b in channels], axis=0)
    # The white point stays where the full stars put it, so the nebula's
    # stretch does not change when the stars are made smaller.
    white_level = None
    if star_power != 1:
        full = ndimage.gaussian_filter(plain_light + star_light, 0.8)
        white_level = float(np.percentile(full, 99.995))
        kept = star_gain(white[..., 0], star_power)[..., None]
        # The tint is blurred later: left at full width it rings a smaller
        # star in purple, so it is kept to the star's core.
        star_colour = white * kept + STAR_TINT * (even_stars - white) * kept ** 3
        star_light = star_light * star_gain(star_light, star_power)
    colour += star_colour
    light = plain_light + star_light
    # The stretch is set by the grain as it was: set by the reduced grain, it
    # lifted the sky's blotches along with the nebula.
    raw = np.mean([untouched[b] / scale[b] + sharp_stars[b] / flux[b] * level for b in channels], axis=0)
    sky = raw[clear & (star < 0.1)] if open_sky >= MIN_CLEAR else raw     # nebula would count as grain
    noise = 1.4826 * np.median(np.abs(sky - np.median(sky))) + 1e-6
    bright_part = ndimage.gaussian_filter((~clear).astype(np.float32), 16) if open_sky >= MIN_CLEAR else np.ones_like(light)
    # All in single precision, as the FITS keeps them, and the level
    # process.display would choose: so the file makes this picture exactly.
    colour, light, noise = colour.astype(np.float32), light.astype(np.float32), np.float32(noise)
    white_shown = np.float32(np.percentile(ndimage.gaussian_filter(light / noise, 0.8), 99.995)
                             if white_level is None else white_level / noise)
    picture = process.display(colour / noise, saturation=saturation, whole=False, light=light / noise, white=white_shown,
                              ghs=ghs)
    plain = np.mean([sharp_nebula[b] / scale[b] for b in channels], axis=0) / noise
    gain = contrast_gain(plain, bright_part).astype(np.float32) if contrast else None
    if gain is not None:
        picture = picture * gain[..., None]
    if grain:
        say("  grain in the clear sky: " + ", ".join(f"{b} x{v:.2f}" for b, v in grain.items()))
    done = {"method": "linear", "picture_version": PICTURE_VERSION, "local_contrast": contrast, "star_power": star_power, "sharpen_steps": sharpen, "ghs": ghs, "clear_sky_share": round(open_sky, 3),
            "sky_map": open_sky >= MIN_CLEAR, "sky_guide": guide, "grain_kept": grain, "nebula_scale": {b: round(v, 2) for b, v in scale.items()},
            "star_flux": {b: round(v, 2) for b, v in flux.items()},
            "star_width_px": {b: round(v, 2) for b, v in before.items() if v},
            "star_width_matched_px": {b: round(v, 2) for b, v in after.items() if v}}
    return picture, {"colour": colour, "light": light, "gain": gain, "noise": float(noise), "white": float(white_shown),
                     "saturation": float(saturation), "ghs": ghs}, done


def narrowband(rgb, channels, saturation, background=2):
    """Each filter stretched on its own, so a strong Ha does not drown the
    others (21 November 2026: NGC 2174's SHO, balanced together, was almost
    all green). In SHO, Ha is in green: most of the green the red and blue
    do not share is taken off, which leaves the palette's gold and blue."""
    stretched = {}
    for c, band in enumerate(channels):
        if band not in stretched:
            plane = np.repeat(rgb[..., c, None], 3, axis=2)
            stretched[band] = process.process(plane, saturation=1.0, background=background, whole=False)[..., 0]
    colour = np.stack([stretched[b] for b in channels], axis=2)
    if channels[1] == "Ha":
        before = colour.mean(axis=2)
        limit = (colour[..., 0] + colour[..., 2]) / 2
        calmer = np.minimum(colour[..., 1], limit + GREEN_KEPT * np.maximum(colour[..., 1] - limit, 0))
        # Stars are bright in all three and keep their green, or they turn magenta.
        star = np.clip((colour.min(axis=2) - 70) / 70, 0, 1)
        colour[..., 1] = star * colour[..., 1] + (1 - star) * calmer
        # What the green gave the nebula's brightness, put back across all three.
        colour *= np.clip(before / np.maximum(colour.mean(axis=2), 1.0), 1.0, 1.6)[..., None]
    else:
        colour[..., 1:] *= OIII_SHARE
    grey = colour.mean(axis=2, keepdims=True)
    return grey + saturation * (colour - grey)


def combine(stacks, saturation=1.25, say=print, min_covered=MIN_COVERED, palette="LRGB", background=2,
            stretched=False, quiet=False, contrast=True, linear_background=None, star_power=1.0, sharpen=0,
            ghs=False):
    """The colour picture (8-bit RGB array) and what went into it."""
    channels, base, detail_band = PALETTES[palette]
    needed = tuple(dict.fromkeys(channels))
    extra = (detail_band,) if detail_band else ()
    have = [b for b in extra + needed if b in stacks]
    if not all(b in stacks for b in needed):
        missing = ", ".join(b for b in needed if b not in stacks)
        raise interface.Refusal("NO_SESSION", f"No stack in {missing}: a {palette} picture needs "
                                f"{', '.join(needed)} (have {', '.join(have) or 'none'}).")
    if base not in stacks:
        base = channels[0]
    images = {b: brightness(stacks[b]) for b in have}
    rows = min(i.shape[0] for i in images.values())
    cols = min(i.shape[1] for i in images.values())
    images = {b: i[:rows, :cols] for b, i in images.items()}
    ref_image = np.nan_to_num(images[base])
    reference = {"square": stacking.centre_square(ref_image), "stars": stacking.find_stars(ref_image)}
    images[base] = np.where(covered(images[base]), images[base], np.nan)
    used = {"palette": palette, base: {"stack": str(stacks[base]), "matched": None}}
    # A stack labelled uncalibrated is allowed, as a preview, and called one.
    raw = [b for b in have if fits.getheader(stacks[b]).get("TY_CALIB") is not True]
    used["calibrated"] = not raw
    if raw:
        say(f"  PREVIEW: {', '.join(raw)} not calibrated; this is not a finished picture")
    for band in have:
        if band == base:
            continue
        images[band], info, turned = lined_up(images[band], reference)
        used[band] = {"stack": str(stacks[band]), "matched": info["matched"],
                      "residual_px": None if info["residual"] is None else round(float(info["residual"]), 2),
                      "shift_px": [round(v, 1) for v in info["shift"]], "turned": turned}
        say(f"  {band} lined up on {base}: {info['matched']} stars matched, shift "
            f"{info['shift'][0]:+.1f}, {info['shift'][1]:+.1f} px")
        if not fits_well(info):
            raise interface.Refusal("NO_STARS", f"The {band} stack matched {info['matched']} stars of the {base} "
                                    f"stack, {info['residual'] if info['residual'] is None else round(info['residual'], 2)} "
                                    f"px apart (needs {stacking.LINED_UP} stars within {stacking.FLIP_RESIDUAL:g} px): "
                                    "the colours would not line up.")
    linear = None
    crop = [0, images[base].shape[0], 0, images[base].shape[1]]
    valid = np.all([np.isfinite(i) for i in images.values()], axis=0)
    rgb = np.stack([np.where(valid, images[b], 0) for b in channels], axis=2)
    if palette == "LRGB":
        colour = process.process(rgb, saturation=saturation, background=background, whole=False)
    elif stretched:
        colour = narrowband(rgb, channels, saturation, background)
        used["method"] = "stretched"
    else:
        colour, linear, done = linear_narrowband(rgb, channels, saturation,
                                                 background if linear_background is None else linear_background,
                                                 say, quiet, contrast, star_power, sharpen, ghs)
        used.update(done)
    if detail_band in images:
        grey = np.where(valid, images[detail_band], 0)
        detail = process.process(np.repeat(grey[..., None], 3, axis=2), saturation=1.0, background=background,
                                 whole=False)[..., 0]
        # The colour's own brightness swapped for L's: hue and saturation from
        # R, G and B, detail and depth from L.
        light = colour.mean(axis=2, keepdims=True)
        colour = colour * (detail[..., None] / np.maximum(light, 1.0))
    colour[~valid] = 0
    # Cropped to the rectangle every filter covers, not padded with black:
    # 5 November 2026, M33's filters drifted apart and three quarters of the
    # picture was black. What was cropped is said, as a share of the L frame.
    # The rows and columns nearly as full as the fullest (the overlap is a
    # slightly turned rectangle, so none is quite whole).
    by_row, by_col = valid.sum(axis=1), valid.sum(axis=0)
    rows = np.where(by_row >= 0.97 * by_row.max())[0] if by_row.max() else np.array([], int)
    cols = np.where(by_col >= 0.97 * by_col.max())[0] if by_col.max() else np.array([], int)
    if rows.size and cols.size:
        r0, r1, c0, c1 = rows[0], rows[-1], cols[0], cols[-1]
        if r1 > r0 and c1 > c0:
            colour = colour[r0:r1 + 1, c0:c1 + 1]
            crop = [int(r0), int(r1) + 1, int(c0), int(c1) + 1]
            share = float(valid[r0:r1 + 1, c0:c1 + 1].sum()) / valid.size     # pixels really covered, not the rectangle
            used["covered"] = round(float(share), 2)
            say(f"  every filter covers {share:.0%} of the frame; the picture is cropped to it")
            if share < min_covered:
                # 5 November 2026: M33's filters shared 41% of the frame, the
                # field beside the galaxy, which was cut off at its edge. A
                # crop that size is a picture of the wrong sky, not a success.
                raise interface.Refusal("FRAMES_APART", f"The filters share only {share:.0%} of the frame "
                                        f"(at least {min_covered:.0%} keeps the target, framed in the middle "
                                        "of each): the colour picture would cut it off. --any-coverage makes "
                                        "it anyway.")
    if linear is not None:
        # The stacks' outer edge is covered by only some of the frames and
        # shows as thin bright strips (21 November 2026, NGC 2174).
        trim = int(EDGE_TRIM * min(colour.shape[:2]))
        colour = colour[trim:-trim, trim:-trim]
        crop = [crop[0] + trim, crop[1] - trim, crop[2] + trim, crop[3] - trim]
        linear.update(valid=valid, crop=crop)
        used["edge_trimmed_px"] = trim
    return np.clip(colour, 0, 255).astype(np.uint8), used, linear


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("name", help="the object, as given to shoot.py")
    ap.add_argument("--night", metavar="YYYYMMDD", help="only sessions begun that date")
    ap.add_argument("--saturation", type=float, help="colour strength; 1 is as shot (default 1.25, linear narrowband 1.8)")
    ap.add_argument("--palette", choices=sorted(PALETTES), default="LRGB",
                    help="LRGB (default), SHO (SII red, Ha green, OIII blue), HOO (Ha red, OIII green and blue) "
                    "or HSS (Ha red, SII green and blue)")
    ap.add_argument("--stretched", action="store_true",
                    help="narrowband: stretch each filter before mixing (the earlier method, for comparison)")
    ap.add_argument("--noise-reduction", action="store_true",
                    help="narrowband: wavelet noise reduction (off by default: on NGC 2174 and NGC 281 it kept no more "
                         "faint detail than a plain blur)")
    ap.add_argument("--no-contrast", action="store_true", help="narrowband: leave out local contrast, for comparison")
    ap.add_argument("--star-reduction", type=bounded(float, 1.0, 3.0), default=1.0, metavar="POWER",
                    help="narrowband: smaller stars, keeping their peaks and colours (1 is none, 2 is about 25%% narrower, 3 the most)")
    ap.add_argument("--ghs", action="store_true",
                    help="narrowband: a generalised hyperbolic stretch, contrast aimed at the faint nebula")
    ap.add_argument("--sharpen", type=bounded(int, 0, 5), default=0, metavar="STEPS",
                    help="narrowband: Richardson-Lucy steps on the nebula's brightness (0 is none, 5 the most; 3 was safe on NGC 2174)")
    ap.add_argument("--any-coverage", action="store_true",
                    help="make the picture even when the filters share under 75%% of the frame")
    ap.add_argument("--plan", action="store_true",
                    help="change nothing: say which sessions of each filter to restack together, and the commands")
    ap.add_argument("--json", action="store_true", help="answer in JSON at the end")
    args = ap.parse_args()
    return interface.main("colour", lambda: show_plan(args.name) if args.plan else run(args), args.json)


def keep_replaced(out):
    """A copy in colour-runs/ of the picture and record at `out`, before a new
    run replaces them, named by the picture's own contents so that nothing
    kept is ever written over (21 November 2026: a trial run replaced M33's
    record, and how that picture was made was lost)."""
    if not out.exists():
        return None
    digest = hashlib.sha256(out.read_bytes()).hexdigest()[:12]
    copy = out.parent / "colour-runs" / f"{out.stem}-replaced-{digest}.jpg"
    copy.parent.mkdir(exist_ok=True)
    if not copy.exists():
        shutil.copy2(out, copy)
    # The old FITS stays by a second name: a new run swaps the usual name to a new file.
    old_linear = out.with_name(out.stem + "-linear.fits")
    kept_linear = copy.with_name(copy.stem + "-linear.fits")
    if old_linear.exists() and old_linear.stat().st_nlink == 1 and not kept_linear.exists():
        os.link(old_linear, kept_linear)
    record = out.with_suffix(".json")
    if record.exists() and not copy.with_suffix(".json").exists():
        old = json.loads(record.read_text(encoding="utf-8"))
        old.update(picture=str(copy), replaced_from=str(out))
        if kept_linear.exists():
            old["linear"] = str(kept_linear)
        records.write(copy.with_suffix(".json"), old)
    return copy


def bounded(kind, low, high):
    """An argparse type: a number within what has been tried."""
    def read(text):
        value = kind(text)
        if not low <= value <= high:
            raise argparse.ArgumentTypeError(f"must be from {low} to {high}")
        return value
    return read


def write_linear(path, linear, palette):
    """Everything the finished picture is made from, in one FITS file, read
    back by picture_from. A picture product, never for measurement."""
    head = fits.Header()
    head["PALETTE"] = palette
    head["TY_PICT"] = (True, "picture product, not for measurement")
    head["NOISE"] = (linear["noise"], "sky noise the picture is scaled by")
    head["WHITE"] = (linear["white"], "level shown white, in units of NOISE")
    head["SATUR"] = (linear["saturation"], "colour strength")
    head["GHS"] = (bool(linear.get("ghs")), "generalised hyperbolic stretch")
    for key, value in zip(("CROPTOP", "CROPBOT", "CROPLEFT", "CROPRITE"), linear["crop"]):
        head[key] = value
    parts = [fits.PrimaryHDU(np.moveaxis(linear["colour"].astype(np.float32), 2, 0), head),
             fits.ImageHDU(linear["light"].astype(np.float32), name="LIGHT"),
             fits.ImageHDU(linear["valid"].astype(np.uint8), name="VALID")]
    if linear["gain"] is not None:
        parts.append(fits.ImageHDU(linear["gain"].astype(np.float32), name="GAIN"))
    fits.HDUList(parts).writeto(path)
    os.chmod(path, 0o444)


def picture_from(path):
    """The finished 8-bit picture, made again from a -linear.fits file."""
    with fits.open(path) as hdus:
        head = hdus[0].header
        colour = np.moveaxis(hdus[0].data, 0, 2).astype(np.float32)
        light = hdus["LIGHT"].data.astype(np.float32)
        valid = hdus["VALID"].data.astype(bool)
        gain = hdus["GAIN"].data.astype(np.float32) if "GAIN" in hdus else None
    # Single precision, as they were when the picture was made.
    noise, white = np.float32(head["NOISE"]), np.float32(head["WHITE"])
    picture = process.display(colour / noise, saturation=head["SATUR"], whole=False, light=light / noise, white=white,
                              ghs=bool(head.get("GHS")))
    if gain is not None:
        picture = picture * gain[..., None]
    picture[~valid] = 0
    picture = picture[head["CROPTOP"]:head["CROPBOT"], head["CROPLEFT"]:head["CROPRITE"]]
    return np.clip(picture, 0, 255).astype(np.uint8)


def show_plan(name):
    plan = restack_plan(name)
    for band, p in plan.items():
        print(f"{band}: {p['minutes']:g} min, {p['frames']} frames of {p['exposure_s']:g} s, {len(p['sessions'])} sessions")
        if p["mixed_settings"]:
            print(f"  left out, settings change inside: {', '.join(Path(x).name for x in p['mixed_settings'])}")
        if p["left_out"]:
            print(f"  left out, another length: {', '.join(Path(x).name for x in p['left_out'])}")
        if p["sessions"]:
            print("  ./restack.py " + " ".join(p["sessions"]))
    return {"name": name, "plan": plan}


def run(args):
    # At least a tilt: a level alone left NGC 2174's sky teal on one side and red on
    # the other (21 November 2026), and a flat plane cannot take a nebula away.
    stacks = sessions(args.name, args.night, say=print)
    print("stacks: " + (", ".join(f"{b} {p.parent.name}" for b, p in sorted(stacks.items())) or "none"))
    linear_mix = args.palette != "LRGB" and not args.stretched
    saturation = args.saturation or (NARROWBAND_SATURATION if linear_mix else 1.25)
    background = max(process.sky_for(args.name), 1)
    picture, used, linear = combine(stacks, saturation, min_covered=0.0 if args.any_coverage else MIN_COVERED,
                            palette=args.palette, background=background,
                            stretched=args.stretched, quiet=args.noise_reduction,
                            contrast=not args.no_contrast, linear_background=process.sky_for(args.name),
                            star_power=args.star_reduction, sharpen=args.sharpen, ghs=args.ghs)
    suffix = "colour" if args.palette == "LRGB" else args.palette
    # A comparison keeps its own files, so it never replaces the picture.
    if args.stretched:
        suffix += "-stretched"
    if args.noise_reduction:
        suffix += "-quiet"
    if args.no_contrast:
        suffix += "-nocontrast"
    if args.star_reduction != 1:
        suffix += f"-stars{args.star_reduction:g}"
    if args.sharpen:
        suffix += f"-sharp{args.sharpen}"
    if args.ghs:
        suffix += "-ghs"
    if args.saturation:
        suffix += f"-sat{args.saturation:g}"
    # A picture of part of the data, or of filters barely overlapping, is not
    # the target's usual picture.
    if args.night:
        suffix += f"-{args.night}"
    if args.any_coverage:
        suffix += "-anycoverage"
    out = config.DATA / "web" / f"{stacking.folder_name(args.name)}-{suffix}.jpg"
    out.parent.mkdir(exist_ok=True)
    keep_replaced(out)
    Image.fromarray(picture).save(out, quality=93)
    print(f"saved {out}")
    settings = {"saturation": saturation, "background": background, "stretched": args.stretched,
                "noise_reduction": args.noise_reduction, "local_contrast": not args.no_contrast, "star_power": args.star_reduction, "ghs": args.ghs, "sharpen_steps": args.sharpen, "night": args.night,
                "any_coverage": args.any_coverage}
    if linear_mix:
        settings.update(green_kept=GREEN_KEPT, linear_oiii=LINEAR_OIII, star_tint=STAR_TINT, edge_trim=EDGE_TRIM,
                        sky_cells=SKY_CELLS, min_clear=MIN_CLEAR, contrast=CONTRAST, quiet=list(QUIET))
    for band, stack in stacks.items():
        if isinstance(used.get(band), dict):
            used[band]["sha256"] = storage.digest(stack)
    # The usual name is always the latest. Each different make is kept too,
    # identified by its method, settings, stacks, code and the picture itself,
    # and never written over.
    stamp = records.provenance()
    made = json.dumps([PICTURE_VERSION, args.palette, settings, stamp.get("git_commit"), stamp.get("uncommitted_changes"), sorted(
        (b, v["sha256"]) for b, v in used.items() if isinstance(v, dict) and "sha256" in v)], sort_keys=True)
    run_id = hashlib.sha256(made.encode() + out.read_bytes()).hexdigest()[:12]
    copy = out.parent / "colour-runs" / f"{out.stem}-{run_id}.jpg"
    copy.parent.mkdir(exist_ok=True)
    new_make = not copy.exists()
    if new_make:
        shutil.copy2(out, copy)
    result = {"name": args.name, "palette": args.palette, "picture": str(out), "run_id": run_id,
              "kept_copy": str(copy), "settings": settings, "filters": used}
    kept_result = {**result, "picture": str(copy)}
    if linear is not None:
        # For processing again without restacking. A picture product: every
        # measurement keeps reading the filters' own final.fits.
        kept = out.with_name(out.stem + "-linear.fits")
        kept_linear = copy.with_name(copy.stem + "-linear.fits")
        if not kept_linear.exists():
            write_linear(kept_linear, linear, args.palette)
        swap = kept.with_name(kept.name + ".new")
        swap.unlink(missing_ok=True)
        os.link(kept_linear, swap)
        os.replace(swap, kept)
        result["linear"] = str(kept)
        kept_result["linear"] = str(kept_linear)
    if new_make:
        records.write(copy.with_suffix(".json"), kept_result, schema="colour", stamp=True)
    return records.write(out.with_suffix(".json"), result, schema="colour", stamp=True)

if __name__ == "__main__":
    main()
