#!/usr/bin/env python3
"""What is new in a stack: proper image subtraction against a reference.

    ./difference.py M31                       the newest M31 night against M31's kept reference
    ./difference.py NEW --reference REF       candidates brighter in NEW than in REF
    ./difference.py frames/M31/20261014-021118 --reference frames/M31/20261013-232632
    ./difference.py NEW --reference REF --plant 200   also plant fake transients and count those found
    ./difference.py NEW --reference REF --json

NEW and REF are stacks: a FITS file, a session folder (its final.fits) or an
object (its newest session). Both are plate-solved and the new one is laid
onto the reference's pixels by their two solves, then lined up to a
fraction of a pixel on the stars they share, so a different framing, a turn
of the camera or a flip at the meridian does not matter.

Subtracting one picture from another leaves rings round every star when the
two nights' stars are not the same size, and they never are. This uses
proper image subtraction (ZOGY: Zackay, Ofek and Gal-Yam 2016, the method
ZTF uses): each image is blurred by the other's star shape, weighted by its
own noise, so the difference is pure noise where nothing changed. Its
matched-filter image scores each point by how likely a new star is there;
the score is divided by its expected spread at each point, from each
pixel's photon noise (the light that doubles the sky's variance measured
from each stack, not read off its level, which the bias can leave below
zero), so the brighter, noisier glow of a galaxy's core is judged against
its own noise. The diffraction spikes of bright stars, which turn with the
camera, are left out. Points scoring above 5 are the candidates, kept as
candidates.json beside the new stack with the score image as
difference.fits.

The candidates are not vetted here: hot pixels, asteroids, variable stars
and known transients are for vet.py (docs/discovery.md, phase 1). Nothing
here moves the mount or uses the camera.
"""
import argparse
import json
import math

import numpy as np
from astropy.io import fits
from scipy import ndimage
from scipy.spatial import cKDTree

import config
import depth
import interface
import records
import stacking

THRESHOLD = 5.0       # a candidate scores at least this many times the local spread
LOCAL = 64            # pixels: the square the local spread of the score is taken over
# The score's spread round a point this many times what the noise model
# expects: there the subtraction, not the sky, limits the search. M31-P8's
# false candidates of 4 November 2026 sat where it was 1.3 to 1.9
# (docs/nights/2026-11-04/p8-false-candidates.md).
OUT_OF_LINE = 1.3
EDGE = 24             # pixels: candidates this near the edge of the shared area are not trusted
BRIGHT = 0.03         # of the brightest star: pixels this bright, and round them, are left out


# --- laying one stack onto another ---------------------------------------------

def onto(new, new_wcs, ref_shape, ref_wcs):
    """The new image resampled onto the reference's pixels, by the two plate
    solves. Pixels the new image did not cover are NaN."""
    yy, xx = np.indices(ref_shape, dtype=np.float64)
    ra, dec = ref_wcs.pixel_to_world_values(xx.ravel(), yy.ravel())
    nx, ny = new_wcs.world_to_pixel_values(ra, dec)
    # A gap in the new stack is filled before resampling, or the smooth
    # resampling rings at its edge; where it was is marked afterwards.
    covered = np.isfinite(new)
    filled = np.where(covered, new, np.median(new[covered]))
    out = ndimage.map_coordinates(filled, [ny, nx], order=3, mode="constant", cval=np.nan)
    there = ndimage.map_coordinates(covered.astype(np.float32), [ny, nx], order=1, mode="constant", cval=0)
    out[there < 0.999] = np.nan
    return out.reshape(ref_shape).astype(np.float32)


def refine(new, ref, finder=None):
    """Line the resampled new image up on the reference to a fraction of a
    pixel, on the stars they share: a plate solve is good to a pixel or so,
    and a subtraction needs better. Returns (new image, matched stars,
    residual in pixels)."""
    finder = finder or (lambda image: stacking.find_stars(np.nan_to_num(image), limit=2000))
    a, b = finder(new), finder(ref)
    if len(a) < 8 or len(b) < 8:
        return new, 0, None
    i, j = stacking.pair_up(a[:, :2], b[:, :2], 3.0)
    if len(i) < 8:
        return new, int(len(i)), None
    r, t = stacking.fit_rigid(a[i, :2], b[j, :2])
    moved = a[i, :2] @ r.T + t
    residual = float(np.median(np.hypot(*(moved - b[j, :2]).T)))
    plane = stacking.warp(np.nan_to_num(new, nan=0.0)[..., None], r, t)[..., 0]
    covered = stacking.warp(np.isfinite(new).astype(np.float32)[..., None], r, t)[..., 0]
    plane[~(covered > 0.99)] = np.nan
    return plane, int(len(i)), residual


def flux_ratio(new, ref, radius, finder=None):
    """How much brighter the same stars are in the new image than in the
    reference: the scale between their two brightness units."""
    finder = finder or (lambda image: stacking.find_stars(np.nan_to_num(image), limit=2000))
    stars = finder(ref)[:300]
    fn = depth.photometry(np.nan_to_num(new - depth.background(np.nan_to_num(new))), stars[:, :2], radius)
    fr = depth.photometry(ref - depth.background(ref), stars[:, :2], radius)
    good = np.isfinite(fn) & np.isfinite(fr) & (fr > 0) & (fn > 0)
    if good.sum() < 5:
        raise interface.Refusal("NO_STARS", "Too few stars in common to compare the two stacks' brightness.")
    return float(np.median(fn[good] / fr[good]))


# --- proper image subtraction ---------------------------------------------------

def centred(psf, shape):
    """A star shape in an array of the image's size, its middle at (0, 0) as
    the Fourier transform expects, scaled to a total of one."""
    out = np.zeros(shape)
    h = psf.shape[0] // 2
    out[:psf.shape[0], :psf.shape[1]] = psf / psf.sum()
    return np.roll(out, (-h, -h), axis=(0, 1))


def glow(image):
    """The smooth light under the stars, followed more closely than for
    measuring depth: a compact galaxy's steep core (M32 beside M31) left
    behind would subtract badly."""
    return depth.background(image, block=8, size=7)


def sky_noise(image):
    """The spread of the sky from pixel to pixel, stars and glow aside."""
    flat = image - depth.background(image)
    sample = flat[::3, ::3]
    return 1.4826 * float(np.median(np.abs(sample - np.median(sample))))


SCALE_BLOCK = 32      # pixels: the squares the sky's noise is measured in, against the glow under them


def sky_scale(image, light, block=SCALE_BLOCK):
    """How much more glow, in counts, doubles the variance of the sky: the
    sky's own light as photon noise sees it. Measured, not read off the sky
    level: the level carries whatever the bias left (on 1 November 2026 the
    master bias was above that night's camera offset and M31's sky sat at
    -55, so a variance scaled by the level went negative over the galaxy
    and the new stack's photon noise dropped out). Each square's spread is
    set against the glow under it and a straight line fitted through the
    medians. Where no rise can be measured, the sky's level if it is above
    zero, or None."""
    flat = image - light
    h, w = image.shape[0] // block * block, image.shape[1] // block * block
    if h == 0 or w == 0:
        return None
    pixels = flat[:h, :w].reshape(h // block, block, w // block, block).transpose(0, 2, 1, 3).reshape(-1, block * block)
    under = light[:h, :w].reshape(h // block, block, w // block, block).mean(axis=(1, 3)).ravel()
    spread = (1.4826 * np.median(np.abs(pixels - np.median(pixels, axis=1, keepdims=True)), axis=1)) ** 2
    above = under - np.percentile(light, 5)
    edges = np.unique(np.percentile(above, np.linspace(0, 99.5, 21)))
    rows = [(np.median(above[inside]), np.median(spread[inside]))
            for inside in ((above >= lo) & (above < hi) for lo, hi in zip(edges[:-1], edges[1:])) if inside.sum() >= 5]
    rows = np.array(rows).reshape(-1, 2)
    if len(rows) >= 3 and np.ptp(rows[:, 0]) > 0:
        slope, at_sky = np.polyfit(rows[:, 0], rows[:, 1], 1)
        # Only a glow spanning several times the sky's own noise can show
        # a rise: in a field of stars on an even sky, the squares with more
        # stars have both a little more "glow" and a wider spread, and the
        # line through them means nothing. A rise of a tenth is a rise.
        if (slope > 0 and at_sky > 0 and np.ptp(rows[:, 0]) > 5 * math.sqrt(at_sky)
                and slope * np.ptp(rows[:, 0]) > 0.1 * at_sky):
            return float(at_sky / slope)
    # A picture with too little glow to measure a rise against (a field of
    # stars on an even sky): the sky's level, when the bias left it above
    # zero, as before the measurement.
    level = float(np.percentile(light, 5))
    return level if level > 0 else None


def variance(flat, light, noise, scale):
    """Each pixel's variance: the sky's, measured, raised where there is more
    light, glow or star, to bring photon noise of its own. `scale` is the
    light that doubles it (sky_scale); with none, the sky's alone."""
    if not scale:
        return np.full(flat.shape, noise ** 2, np.float32)
    more = np.maximum(light - np.percentile(light, 5), 0) + np.maximum(flat, 0)
    return (noise ** 2 * (1 + more / scale)).astype(np.float32)


def convolve(image, kernel_hat):
    return np.real(np.fft.ifft2(np.fft.fft2(image) * kernel_hat))


def zogy(new, ref, psf_new, psf_ref, noise_new, noise_ref, scale_new=1.0, scale_ref=1.0,
         var_new=None, var_ref=None, astrometric=0.0, photometric=0.0):
    """Proper image subtraction (Zackay, Ofek and Gal-Yam 2016). Returns
    (difference, score, corrected): the difference image, whose noise is
    even where nothing changed; the matched-filter score, whose peaks are
    where a new point of light most likely is (their equations 13 to 17);
    and that score divided by its own expected spread at each point
    (section 3.3), which counts the stars' own photon noise from the
    per-pixel variances var_new and var_ref, and the error of lining the
    two images up, `astrometric` pixels on each axis, and the error of the
    brightness scale between them, `photometric` as a share. Without the
    variances `corrected` is None."""
    shape = new.shape
    pn, pr = np.fft.fft2(centred(psf_new, shape)), np.fft.fft2(centred(psf_ref, shape))
    n, r = np.fft.fft2(new), np.fft.fft2(ref)
    both = np.sqrt(noise_new ** 2 * scale_ref ** 2 * np.abs(pr) ** 2
                   + noise_ref ** 2 * scale_new ** 2 * np.abs(pn) ** 2) + 1e-12
    d_hat = (scale_ref * pr * n - scale_new * pn * r) / both
    scale_d = scale_ref * scale_new / math.sqrt(noise_new ** 2 * scale_ref ** 2 + noise_ref ** 2 * scale_new ** 2)
    pd_hat = scale_ref * scale_new * pr * pn / (scale_d * both)
    difference = np.real(np.fft.ifft2(d_hat))
    # The score is the new image's part less the reference's part, each a
    # convolution with its own kernel.
    kn_hat = scale_d * scale_ref * pr * np.conj(pd_hat) / both
    kr_hat = scale_d * scale_new * pn * np.conj(pd_hat) / both
    from_new, from_ref = np.real(np.fft.ifft2(kn_hat * n)), np.real(np.fft.ifft2(kr_hat * r))
    score = from_new - from_ref
    corrected = None
    if var_new is not None and var_ref is not None:
        kn, kr = np.real(np.fft.ifft2(kn_hat)), np.real(np.fft.ifft2(kr_hat))
        variance = (convolve(var_new, np.fft.fft2(kn ** 2)) + convolve(var_ref, np.fft.fft2(kr ** 2)))
        extra = np.zeros(shape)
        if astrometric:
            for part in (from_new, from_ref):
                gy, gx = np.gradient(part)
                extra += astrometric ** 2 * (gx ** 2 + gy ** 2)
        if photometric:
            extra += (photometric * from_ref) ** 2
        # The slope of a star is nil at its very centre; spread the error
        # over the star, or a misplaced star scores a spike there.
        variance += ndimage.gaussian_filter(extra, 1.5)
        corrected = (score / np.sqrt(np.maximum(variance, 1e-12))).astype(np.float32)
    return difference.astype(np.float32), score.astype(np.float32), corrected


PHOTOMETRIC = 0.03    # the brightness scale between two nights is good to about this share
TILE = 512            # pixels: the subtraction is done in squares this size, each with its own star shapes
OVERLAP = 48          # pixels each square reaches into its neighbours, so no star is cut at a seam


def tiles(shape, size=TILE, overlap=OVERLAP):
    """Squares covering the image, as (outer, inner) slice pairs: the outer
    square is subtracted, and the inner part of it kept."""
    out = []
    for y0 in range(0, shape[0], size):
        for x0 in range(0, shape[1], size):
            y1, x1 = min(y0 + size, shape[0]), min(x0 + size, shape[1])
            oy0, ox0 = max(y0 - overlap, 0), max(x0 - overlap, 0)
            oy1, ox1 = min(y1 + overlap, shape[0]), min(x1 + overlap, shape[1])
            out.append(((slice(oy0, oy1), slice(ox0, ox1)),
                        (slice(y0 - oy0, y1 - oy0), slice(x0 - ox0, x1 - ox0)),
                        (slice(y0, y1), slice(x0, x1))))
    return out


def subtract_in_tiles(new_flat, ref_flat, stars_new, stars_ref, radius, scale, psf_new, psf_ref,
                      var_new=None, var_ref=None, astrometric=0.0, photometric=0.0):
    """Proper subtraction square by square. A Newtonian with no coma
    corrector makes stars longer towards the corners, so one star shape for
    the whole picture leaves a ring round every star where it does not fit;
    each square uses the shapes of its own stars, and the whole picture's
    where it has too few. Each also takes its own brightness scale from its
    own stars: with no flat frames, and the two nights on opposite sides of
    the meridian, the vignetting falls on different stars each night."""
    noise_new, noise_ref = sky_noise(new_flat), sky_noise(ref_flat)
    # The brightness scale is taken from stars bright enough to measure
    # well and faint enough not to be flattened at the top.
    dim, saturated = np.percentile(stars_ref[:, 2], [70, 97])
    difference = np.zeros(new_flat.shape, np.float32)
    score = np.zeros(new_flat.shape, np.float32)
    for outer, inner, target in tiles(new_flat.shape):
        oy, ox = outer[0].start, outer[1].start
        local = []
        for stars in (stars_new, stars_ref):
            inside = ((stars[:, 0] >= outer[1].start) & (stars[:, 0] < outer[1].stop)
                      & (stars[:, 1] >= outer[0].start) & (stars[:, 1] < outer[0].stop))
            moved = stars[inside].copy()
            moved[:, 0] -= ox
            moved[:, 1] -= oy
            local.append(moved)
        n, r = new_flat[outer], ref_flat[outer]
        pn = depth.psf(n, local[0][:, :2], radius) if len(local[0]) >= 8 else None
        pr = depth.psf(r, local[1][:, :2], radius) if len(local[1]) >= 8 else None
        local_scale = tile_ratio(n, r, local[1][(local[1][:, 2] > dim) & (local[1][:, 2] < saturated)],
                                 radius) or scale
        d, s, c = zogy(n, r, pn if pn is not None else psf_new, pr if pr is not None else psf_ref,
                       noise_new, noise_ref, scale_new=local_scale, scale_ref=1.0,
                       var_new=None if var_new is None else var_new[outer],
                       var_ref=None if var_ref is None else var_ref[outer], astrometric=astrometric,
                       photometric=photometric)
        difference[target] = d[inner]
        score[target] = (s if c is None else c)[inner]
    return difference, score, noise_new, noise_ref


def tile_ratio(n, r, stars, radius, least=8):
    """The new-to-reference brightness scale from the stars in one square,
    or None with too few."""
    if len(stars) < least:
        return None
    fn = depth.photometry(n, stars[:100, :2], radius)
    fr = depth.photometry(r, stars[:100, :2], radius)
    good = np.isfinite(fn) & np.isfinite(fr) & (fr > 0) & (fn > 0)
    return float(np.median(fn[good] / fr[good])) if good.sum() >= least else None


def local_spread(score, size=LOCAL):
    """The spread of the score round each point, from the median of its
    absolute value: a few bright candidates do not inflate it."""
    small = ndimage.median_filter(np.abs(score[::4, ::4]), size // 4, mode="nearest") * 1.4826
    full = ndimage.zoom(small, (score.shape[0] / small.shape[0], score.shape[1] / small.shape[1]), order=1)
    return np.maximum(full[:score.shape[0], :score.shape[1]], 1e-12)


def peaks(significance, usable, threshold=THRESHOLD):
    """Local maxima of the significance above the threshold, where usable."""
    top = ndimage.maximum_filter(significance, size=7)
    hit = (significance == top) & (significance > threshold) & usable
    y, x = np.nonzero(hit)
    order = np.argsort(-significance[y, x])
    return x[order], y[order]


DIPOLE_REACH = 6      # pixels round a candidate searched for a dark partner
DIPOLE_SHARE = 0.5    # a dark lobe this deep, as a share of the bright one, makes it a pair


def dipole(significance, x, y, reach=DIPOLE_REACH, share=DIPOLE_SHARE):
    """Whether a peak has a dark partner beside it: a misplaced star, not a
    new one."""
    near = significance[max(y - reach, 0):y + reach + 1, max(x - reach, 0):x + reach + 1]
    return bool(near.min() < -share * significance[y, x])


HALO = (2.0, 4.0)     # star widths left out round bright stars, and round the brightest

def usable_area(new, ref, edge=EDGE, bright=BRIGHT, fwhm=4.8):
    """Where a candidate can be trusted: covered by both stacks, away from
    the edge of that area and away from the brightest stars, whose cores
    saturate and never subtract cleanly. How far round a star is left out
    goes with the stars' width: a fixed 20 pixels was right on this rig's
    stacks and, on ZTF's sharper images, hid a real nova 17 pixels from a
    bright star (AT2024koe)."""
    covered = np.isfinite(new) & np.isfinite(ref)
    inside = ndimage.binary_erosion(covered, iterations=edge)
    flat = np.nan_to_num(ref - depth.background(np.nan_to_num(ref)))
    # A bright star's halo reaches well past its core: the area left out
    # grows with how bright it is.
    peak = np.nanpercentile(flat, 99.99)
    out = np.zeros(ref.shape, bool)
    for level, widths in ((bright, HALO[0]), (10 * bright, HALO[1])):
        out |= ndimage.binary_dilation(flat > level * peak, iterations=max(2, round(widths * fwhm)))
    return inside & ~out


SPIKE_REACH = 250     # pixels: the longest diffraction spike looked for
SPIKE_LEVEL = 0.3     # of the sky's noise: an arm brighter than its surroundings by this still leaves leftovers
SPIKE_CLEAR = 5.0     # the spikes' angle is trusted when it stands this many spreads above the other angles
SPIKE_MOST = 20       # the brightest stars measured for spikes


def bright_centres(flat, level, most=SPIKE_MOST):
    """The middles of the stars bright enough to be left out of the search
    (usable_area's level), brightest first."""
    labels, count = ndimage.label(flat > level)
    if not count:
        return np.zeros((0, 2))
    index = np.arange(1, count + 1)
    total = ndimage.sum_labels(flat, labels, index)
    where = np.array(ndimage.center_of_mass(np.maximum(flat, 0), labels, index))[:, ::-1]
    return where[np.argsort(-total)][:most]


def _arms(flat, x, y, angle, radii, across=(0.0,)):
    """The image sampled along the four arms of a cross at `angle` degrees
    round (x, y): an array of (arm, offset across, radius)."""
    out = []
    for k in range(4):
        a = math.radians(angle + 90 * k)
        c, s = math.cos(a), math.sin(a)
        for off in across:
            xs, ys = x + radii * c - off * s, y + radii * s + off * c
            out.append(ndimage.map_coordinates(flat, [ys, xs], order=1, mode="constant", cval=np.nan))
    return np.array(out).reshape(4, len(across), len(radii))


def spike_angle(flat, centres, fwhm, clear=SPIKE_CLEAR):
    """The angle, in degrees from 0 to 90, of the diffraction spikes the
    secondary's spider puts on bright stars, or None if none show. All four
    arms of each star are followed out at every angle, the median along them
    taken (a spike runs the whole way; a neighbouring star is a blip in it),
    and the spikes are where that stands out from the other angles on the
    brightest stars together."""
    if len(centres) < 3:
        return None
    angles = np.arange(0.0, 90.0, 0.5)
    radii = np.arange(4 * fwhm, 25 * fwhm, 1.0)
    rows = []
    for x, y in centres:
        light = np.array([np.nanmedian(np.nanmean(_arms(flat, x, y, a, radii), axis=(0, 1))) for a in angles])
        if not np.isfinite(light).all():
            continue
        spread = 1.4826 * np.median(np.abs(light - np.median(light))) + 1e-12
        rows.append((light - np.median(light)) / spread)
    if len(rows) < 3:
        return None
    together = np.mean(rows, axis=0)
    together = (together - np.median(together)) / (1.4826 * np.median(np.abs(together - np.median(together))) + 1e-12)
    best = int(np.argmax(together))
    return float(angles[best]) if together[best] > clear else None


def spike_mask(flat, centres, angle, fwhm, noise, reach=SPIKE_REACH, level=SPIKE_LEVEL):
    """The diffraction spikes round each bright star, as a mask: each arm is
    followed out as far as it is brighter than the sky beside it (the light
    at 45 degrees to the spikes) by `level` times the sky's noise, and
    covered a star and a half wide on each side."""
    mask = np.zeros(flat.shape, bool)
    if angle is None:
        return mask
    radii = np.arange(2 * fwhm, reach, 1.0)
    across = (-1.0, 0.0, 1.0)
    half = 1.5 * fwhm
    yy, xx = np.indices(flat.shape)
    for x, y in centres:
        arm = np.nanmean(_arms(flat, x, y, angle, radii, across), axis=(0, 1))
        beside = np.nanmean(_arms(flat, x, y, angle + 45, radii, across), axis=(0, 1))
        above = ndimage.uniform_filter1d(np.nan_to_num(arm - beside), 9)
        # From where it first stands out (a saturated core is as bright at
        # every angle) out to where it fades into the sky: a star further
        # along an arm is not more spike.
        lit = above > level * noise
        if not lit.any():
            continue
        start = int(np.argmax(lit))
        faded = np.nonzero(~lit[start:])[0]
        reached = start + (faded[0] if len(faded) else len(radii) - start)
        length = radii[reached - 1] + 2 * fwhm
        x0, x1 = int(max(x - length - half, 0)), int(min(x + length + half + 1, flat.shape[1]))
        y0, y1 = int(max(y - length - half, 0)), int(min(y + length + half + 1, flat.shape[0]))
        dx, dy = xx[y0:y1, x0:x1] - x, yy[y0:y1, x0:x1] - y
        a = math.radians(angle)
        along, side = dx * math.cos(a) + dy * math.sin(a), -dx * math.sin(a) + dy * math.cos(a)
        mask[y0:y1, x0:x1] |= ((np.abs(along) <= length) & (np.abs(side) <= half)) | \
                              ((np.abs(side) <= length) & (np.abs(along) <= half))
    return mask


def spikes(new_flat, ref_flat, fwhm, bright=BRIGHT):
    """Where either night's diffraction spikes fall. The spider's spikes turn
    with the camera: on 1 November 2026 M31's were at a different angle from
    the reference's, every bright star left a bright and a dark cross, and
    those crosses made most of the night's candidates and fading peaks.
    Each night's spikes are found at their own angle and left out."""
    mask = np.zeros(ref_flat.shape, bool)
    for flat in (new_flat, ref_flat):
        flat = np.nan_to_num(flat)
        centres = bright_centres(flat, bright * np.percentile(flat, 99.99))
        mask |= spike_mask(flat, centres, spike_angle(flat, centres, fwhm), fwhm, sky_noise(flat))
    return mask


# --- putting it together ---------------------------------------------------------

def subtract(new, ref, new_wcs=None, ref_wcs=None, zeropoint=None, plant_count=0, seed=3, finder=None,
             workings=None):
    """Lay the new image on the reference, subtract properly, and list what
    is brighter now. With plant_count, fake new stars of known brightness
    are added to the new image first and counted when found. A dict as
    `workings` is given the working images and where the fakes went, for
    realbogus.py to learn from."""
    finder = finder or (lambda image: stacking.find_stars(np.nan_to_num(image), limit=10 ** 6))
    # A stack is exactly zero where no frame reached: that is not sky.
    new = np.where(new == 0, np.nan, new).astype(np.float32)
    ref_covered = ref != 0
    ref = np.where(ref_covered, ref, np.median(ref[ref_covered])).astype(np.float32)
    if new_wcs is not None and ref_wcs is not None:
        new = onto(new, new_wcs, ref.shape, ref_wcs)
    new, matched, residual = refine(new, ref)
    if residual is None:
        raise interface.Refusal("NO_STARS", f"Only {matched} stars in common: the stacks do not overlap "
                                "enough to subtract.")
    stars_ref = finder(ref)
    fwhm = float(np.median(stars_ref[:200, 3]))
    radius = max(fwhm, 2.0)
    # The brightness scale needs all of each star's light, whichever night
    # had the wider stars: an aperture as wide as the stars would take less
    # of the wider ones.
    stars_new = finder(new)
    fwhm_new = float(np.median(stars_new[:200, 3])) if len(stars_new) else fwhm
    whole = 2.5 * max(fwhm, fwhm_new)
    scale = flux_ratio(new, ref, whole)
    # Both glows go: the subtraction is of points of light, and a gradient
    # that differs between nights is not news.
    usable = usable_area(new, np.where(ref_covered, ref, np.nan), fwhm=fwhm)
    filled = np.where(np.isfinite(new), new, np.nanmedian(new))
    glow_new, glow_ref = glow(filled), glow(ref)
    new_flat, ref_flat = filled - glow_new, ref - glow_ref
    usable &= ~spikes(new_flat, ref_flat, fwhm)
    psf_ref = shape_of(ref_flat, stars_ref, radius)
    psf_new = shape_of(new_flat, finder(new_flat), radius)
    planted = None
    if plant_count:
        rng = np.random.default_rng(seed)
        spots = depth.places(ref.shape, plant_count, rng, edge=EDGE + depth.PSF_HALF + 2)
        spots = spots[usable[np.rint(spots[:, 1]).astype(int), np.rint(spots[:, 0]).astype(int)]]
        mags = rng.choice(depth.MAGNITUDES, len(spots))
        zp = zeropoint if zeropoint is not None else 22.0
        flux = 10 ** (-0.4 * (mags - zp))
        new_flat = depth.plant(new_flat, psf_new, spots, flux)
        planted = (spots, mags)
    # Each pixel's variance: the sky's, measured, scaled up where there is
    # more light (glow or star) to bring photon noise of its own.
    noise_new, noise_ref = sky_noise(new_flat), sky_noise(ref_flat)
    scale_new, scale_ref = sky_scale(filled, glow_new), sky_scale(ref, glow_ref)
    var_new = variance(new_flat, glow_new, noise_new, scale_new)
    var_ref = variance(ref_flat, glow_ref, noise_ref, scale_ref)
    # The median distance between matched stars is 1.18 times the error on
    # each axis, for errors that are round and Gaussian.
    difference, score, noise_new, noise_ref = subtract_in_tiles(
        new_flat, ref_flat, finder(new_flat), stars_ref, whole, scale, psf_new, psf_ref,
        var_new, var_ref, astrometric=residual / 1.18, photometric=PHOTOMETRIC)
    # The resampling makes neighbouring pixels share noise, which the
    # variances do not know: the corrected score's own spread is taken out.
    sample = score[usable][::7]
    significance = score / (1.4826 * float(np.median(np.abs(sample - np.median(sample)))) + 1e-12)
    # Dividing it further by its own spread round each point (local_spread),
    # tried on 2 November 2026 on M31's stacks of 1 November and the two of
    # 17 October, took their candidates from 7, 3 and 7 to 5, 1 and 1 but lost a
    # tenth of the planted G 17 to 17.5 stars in the corner of 17 October's
    # stack that fewer frames reached: those candidates are marked instead
    # by how many fading peaks are as strong (as_strong_fading).
    x, y = peaks(significance, usable)
    # Where the subtraction is the limit: kept as a share of the field, and
    # each candidate's score against its own surroundings, for the plan to
    # weigh (docs/observing-plan-spec.md, Phases 2 and 4). It marks; it
    # silences nothing.
    around = local_spread(significance)
    out_of_line = round(float((around[usable] > OUT_OF_LINE).mean()), 3) if usable.any() else None
    # A star a fraction of a pixel out of place leaves a bright and a dark
    # lobe side by side; a new star has no dark partner.
    keep = [not dipole(significance, cx, cy) for cx, cy in zip(x, y)]
    dipoles = int(len(x) - sum(keep))
    x, y = x[keep], y[keep]
    # The same search on the fading side finds what noise and imperfect
    # subtraction alone produce: how many fading peaks reach a candidate's
    # score says how many false ones that strong to expect.
    fx, fy = peaks(-significance, usable)
    fading = np.sort(-significance[fy, fx])
    # A star out of place leaves its dark leftover on the star itself; the
    # leftovers of a galaxy's own structure, or of noise, fall anywhere.
    on_stars = fading_on_stars(fx, fy, stars_ref, fwhm)
    candidates = []
    for cx, cy in zip(x, y):
        c = {"x": int(cx), "y": int(cy), "score": round(float(significance[cy, cx]), 1),
             "local_score": round(float(significance[cy, cx] / around[cy, cx]), 1)}
        c["as_strong_fading"] = int(len(fading) - np.searchsorted(fading, significance[cy, cx]))
        if ref_wcs is not None:
            ra, dec = ref_wcs.pixel_to_world_values(float(cx), float(cy))
            c.update(ra=round(float(ra), 6), dec=round(float(dec), 6))
        # Brightness of what is new, in the new stack's units, through the
        # same aperture as the zero point.
        extra = depth.photometry(new_flat - scale * ref_flat, np.array([[cx, cy]], float), radius)[0]
        if zeropoint is not None and extra > 0:
            c["mag"] = round(zeropoint - 2.5 * math.log10(extra), 2)
        candidates.append(c)
    record = {"candidates": candidates, "matched_stars": matched,
              "alignment_residual_px": round(residual, 3), "flux_ratio": round(scale, 4),
              "fwhm_px": round(fwhm, 2), "noise_new": round(noise_new, 3), "noise_ref": round(noise_ref, 3),
              "usable_share": round(float(usable.mean()), 3), "threshold": THRESHOLD,
              "out_of_line_share": out_of_line,
              "fading_peaks": int(len(fading)), "fading_on_stars": on_stars, "dipoles_left_out": dipoles,
              "sky_scale_new": None if scale_new is None else round(scale_new, 1),
              "sky_scale_ref": None if scale_ref is None else round(scale_ref, 1)}
    if workings is not None:
        workings.update(significance=significance, usable=usable, ref=ref_flat, fwhm=fwhm,
                    planted=planted, wcs=ref_wcs)
    if planted is not None:
        spots, mags = planted
        found = np.zeros(len(spots), bool)
        if candidates:
            d, _ = cKDTree([[c["x"], c["y"]] for c in candidates]).query(spots, distance_upper_bound=2.5)
            found = np.isfinite(d)
        record["planted"] = curve(mags, found)
        record["false_candidates"] = int(len(candidates) - found.sum())
    return record, significance


def fading_on_stars(x, y, stars, fwhm):
    """How many fading peaks sit within a star's width of a star of the
    reference: the dark half of what a misaligned star leaves."""
    if not len(x) or not len(stars):
        return 0
    distance, _ = cKDTree(stars[:, :2]).query(np.c_[x, y], distance_upper_bound=fwhm)
    return int(np.isfinite(distance).sum())


def shape_of(flat, stars, radius):
    """The star shape of an image, or a round one of its width if too few
    clean stars can be copied."""
    shape = depth.psf(flat, stars[:, :2], radius)
    if shape is not None:
        return shape
    s = max(float(np.median(stars[:50, 3])), 2.0) / 2.355
    yy, xx = np.mgrid[-depth.PSF_HALF:depth.PSF_HALF + 1, -depth.PSF_HALF:depth.PSF_HALF + 1]
    g = np.exp(-(xx ** 2 + yy ** 2) / (2 * s * s))
    return (g / g.sum()).astype(np.float32)


def curve(mags, found):
    """Share of the planted transients found at each magnitude, with the
    faintest at which half are."""
    rows, shares = [], []
    for m in depth.MAGNITUDES:
        at = mags == m
        share = float(found[at].mean()) if at.sum() >= 3 else None
        shares.append(share)
        rows.append({"mag": float(m), "planted": int(at.sum()), "found": int(found[at].sum()),
                     "share": None if share is None else round(share, 3)})
    return {"curve": rows, "mag_50": depth.crossing(depth.MAGNITUDES, shares, 0.5),
            "mag_90": depth.crossing(depth.MAGNITUDES, shares, 0.9)}


def run(args, say=print):
    if config.DEMO:
        raise interface.Refusal("DEMO_UNSUPPORTED", "A difference needs two real stacks.")
    import reference
    new_path = depth.find_stack(args.new)
    name = args.near or depth.object_name(new_path)
    owner = None
    if args.reference:
        ref_path = depth.find_stack(args.reference)
    else:
        ref_path, owner = reference.for_field(name)
        if ref_path is None:
            raise interface.Refusal("NO_SESSION", f"No reference kept for {name}: ./reference.py {name} --make, "
                                    "or name one with --reference.")
        if owner != name:
            say(f"no reference of {name}'s own yet: {owner}'s, where they overlap")
        if new_path.parent.resolve() in reference.sessions_used(owner):
            raise interface.Refusal("INVALID_REQUEST", f"{new_path.parent} made {name}'s reference: a night "
                                    "is never compared with itself.")
    new = depth.brightness(fits.getdata(new_path))
    ref = depth.brightness(fits.getdata(ref_path))
    say(f"new {new_path}, reference {ref_path}")
    new_wcs, ref_wcs = depth.plate(new, name), depth.plate(ref, name)
    kept = depth.record_path(new_path)
    zeropoint = json.loads(kept.read_text(encoding="utf-8"))["zeropoint"] if kept.exists() else None
    try:
        record, significance = subtract(new, ref, new_wcs, ref_wcs, zeropoint, args.plant)
    except interface.Refusal as refused:
        # A borrowed reference that does not reach this field: the cure is the
        # field's own reference, not a count of stars in common.
        if refused.code_name != "NO_STARS" or owner in (None, name):
            raise
        raise interface.Refusal("NO_SESSION", f"{name} has no reference of its own, and {owner}'s does not "
                                f"overlap it enough: ./reference.py {name} --make.") from None
    record.update(new=str(new_path), reference=str(ref_path), object=name,
                  band="unfiltered, calibrated approximately to Gaia G" if zeropoint else None)
    folder = new_path.parent
    records.write(folder / "candidates.json", record, schema="difference", stamp=True)
    fits.PrimaryHDU(significance, ref_wcs.to_header()).writeto(folder / "difference.fits", overwrite=True)
    say(f"lined up on {record['matched_stars']} stars to {record['alignment_residual_px']:.2f} px; "
        f"new is {record['flux_ratio']:.3f} x the reference's brightness")
    say(f"{len(record['candidates'])} candidates above {THRESHOLD:g} sigma on "
        f"{100 * record['usable_share']:.0f}% of the picture")
    for c in record["candidates"][:20]:
        where = f"RA {c['ra']:.5f} Dec {c['dec']:+.5f}" if "ra" in c else f"x {c['x']} y {c['y']}"
        say(f"  {c['score']:6.1f} sigma  {where}" + (f"  G~{c['mag']:.1f}" if "mag" in c else ""))
    if "planted" in record:
        p = record["planted"]
        say(f"planted transients: half found to {p['mag_50']}, 90% to {p['mag_90']}; "
            f"{record['false_candidates']} candidates that were not planted")
    say(f"kept as {folder / 'candidates.json'} and difference.fits")
    return record


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("new", help="the new stack: an object, a session folder or a FITS file")
    ap.add_argument("--reference", help="the reference stack, given the same ways (default: the field's "
                                         "newest kept reference, reference.py)")
    ap.add_argument("--plant", type=int, default=0, metavar="N",
                    help="plant N fake transients in the new stack and count how many are found")
    ap.add_argument("--near", help="the object to plate-solve near, if the folder does not say")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("difference", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
