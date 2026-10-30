#!/usr/bin/env python3
"""Lucky imaging of the Moon or a planet: a fast video, the sharpest moments
kept, and a multi-point stack that undoes the seeing. `./ty moon` runs the
whole Moon night through it; this is the engine underneath.

    ./lucky.py capture Moon --frames 1000 --exposure 0.01 --gain 100 --roi X Y W H
    ./lucky.py stack frames/lucky/Moon-20261024-0210.ser --keep 5 10 20 40
    ./lucky.py picture frames/lucky/Moon-*.fits    draw the stacks' pictures again
    ./lucky.py mineral frames/lucky/Moon-A.ser Moon-B.ser    the Moon's colour turned up

`capture` takes the frames back to back in the camera's video mode and
writes them as one SER file, the format every planetary stacker reads, with
what was asked and what came (frames a second, frames the camera dropped)
in a JSON file beside it.

`stack` ranks every frame by its sharpness, then works patch by patch
(alignment points, placed where the surface has detail): each patch of the
picture is built from the frames that were sharpest *there*, each moved onto
the reference as a whole and then bent straight where the air bent it. The
air is sharp in one place and blurred in another at the same moment, so the
best frames for one crater are not the best for the next. A point whose
match is weak, or disagrees with its neighbours, is left out and the bend
there is taken from the points around it. Several shares of frames are
stacked at once (the best 5, 10, 20 and 40 % by default), since how many
are worth keeping depends on the seeing; the sharpest result is shown, and
all are kept with the unsharpened stacks.

Two products. Detail (the default): the green pixels, half the sensor's,
filled in at the red and blue ones from the greens around them, so the
colour pattern never shows as detail. Natural colour (`--colour`): the
mosaic made into colour and every colour bent by the green's alignment.

24 October 2026: the Moon through the deep-sky stacker at one frame a
second; this is the method the planetary stackers use. Never the Sun:
nothing here knows whether a solar filter is fitted.
"""
import argparse
import json
import shutil
import struct
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy import ndimage

import activity
import config

OUT = config.DATA / "frames" / "lucky"
PREVIEW = config.DATA / "web" / "stack.jpg"
PROGRESS = config.DATA / "web" / "lucky.json"
SER_HEADER = 178
SER_RGGB = 8         # SER's colour ID for an RGGB Bayer mosaic
BOX = 96             # alignment point size, pixels
STEP = 48            # spacing of the grid the points are chosen from
MAX_POINTS = 600     # at most this many, the ones with most detail
MIN_PEAK = 4.0       # a match whose correlation peak stands less than this far above the rest is not trusted
NEIGHBOUR_PX = 3.0   # a point whose shift differs this much from its neighbours' is not trusted
SEARCH = 24          # furthest a patch is looked for from where the whole-frame shift puts it
KEEPS = (5, 10, 20, 40)
PUBLISH_S = 3.0      # seconds between frames shown on the page during a video


# --- progress, for the page and the stream ------------------------------------------

def progress(stage, **fields):
    """What the lucky imaging is doing now, in web/lucky.json: the stage
    (capturing, ranking, stacking, done) and its figures."""
    import records
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    records.write(PROGRESS, {"stage": stage, "at": time.time(), **fields}, indent=None)


# --- SER files -----------------------------------------------------------------

def ser_header(width, height, frames, depth=8, colour=SER_RGGB, instrument="", when=None):
    when = when or datetime.now(timezone.utc)
    # SER's dates are .NET ticks: 100 ns since 1 January of year 1.
    ticks = int((when - datetime(1, 1, 1, tzinfo=timezone.utc)).total_seconds() * 1e7)
    return (b"LUCAM-RECORDER" + struct.pack("<7i", 0, colour, 0, width, height, depth, frames)
            + b"telescopeyoke".ljust(40, b"\0") + instrument.encode()[:40].ljust(40, b"\0")
            + b"Sky-Watcher 150P".ljust(40, b"\0") + struct.pack("<2q", ticks, ticks))


class SerWriter:
    """Frames written one at a time, 8 bits (the default: half the disk, and
    the Moon is exposed well up the scale) or 16; the count in the header is
    put right when it is closed. 12-bit frames are scaled to 8 by dropping
    their bottom four bits."""

    def __init__(self, path, width, height, instrument="", depth=8, white=4095):
        self.path, self.width, self.height, self.count = Path(path), width, height, 0
        self.depth, self.shift = depth, max(0, int(white).bit_length() - 8) if depth == 8 else 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = open(self.path, "wb")
        self.file.write(ser_header(width, height, 0, depth=depth, instrument=instrument))

    def frame_bytes(self):
        return self.width * self.height * (1 if self.depth == 8 else 2)

    def add(self, mosaic):
        if mosaic.shape != (self.height, self.width):
            raise ValueError(f"frame {mosaic.shape[::-1]} is not the video's {self.width}x{self.height}")
        if self.depth == 8:
            data = np.clip(np.asarray(mosaic) >> self.shift, 0, 255).astype(np.uint8)
        else:
            data = np.ascontiguousarray(mosaic, dtype="<u2")
        self.file.write(data.tobytes())
        self.count += 1

    def close(self):
        self.file.seek(38)            # FrameCount
        self.file.write(struct.pack("<i", self.count))
        self.file.close()


def read_ser(path):
    """A SER file's frames as a read-only (frames, height, width) array on
    disk, and its colour ID."""
    with open(path, "rb") as f:
        head = f.read(SER_HEADER)
    if head[:14] != b"LUCAM-RECORDER":
        raise ValueError(f"{path} is not a SER file")
    _, colour, _, width, height, depth, frames = struct.unpack("<7i", head[14:42])
    # The little-endian flag is read both ways by different programs; ours writes little-endian.
    dtype = np.dtype("<u2" if depth > 8 else "u1")
    # A capture cut off before it closed (30 October 2026: the laptop crashed
    # after 1018 frames) leaves the count at 0: the whole frames in the file
    # are the video.
    whole = (Path(path).stat().st_size - SER_HEADER) // (width * height * dtype.itemsize)
    if frames <= 0 or frames > whole:
        frames = whole
    data = np.memmap(path, dtype=dtype, mode="r", offset=SER_HEADER, shape=(frames, height, width))
    return data, colour


# --- a frame as a picture ---------------------------------------------------------

def _masks(shape):
    rows, cols = np.indices(shape)
    red = (rows % 2 == 0) & (cols % 2 == 0)
    blue = (rows % 2 == 1) & (cols % 2 == 1)
    return red, ~(red | blue), blue


CROSS = np.array([[0, 1, 0], [1, 4, 1], [0, 1, 0]], np.float32) / 4
BOXED = np.array([[1, 2, 1], [2, 4, 2], [1, 2, 1]], np.float32) / 4


def green(mosaic):
    """The detail picture from an RGGB mosaic: the green pixels as they are,
    and at each red or blue pixel the mean of the four greens beside it."""
    m = np.asarray(mosaic, dtype=np.float32)
    _, g, _ = _masks(m.shape)
    return ndimage.convolve(m * g, CROSS, mode="mirror")


def balanced(mosaic, gains=None):
    """Every pixel of an RGGB mosaic at full resolution, the red and blue
    ones scaled to the green's level (`gains`, or worked out from this
    mosaic). The finer of the two detail pictures where the surface is grey:
    on 24 October 2026 Tycho's rim was crisper this way than from the greens
    alone, at twice the pixel noise."""
    m = np.asarray(mosaic, dtype=np.float32)
    if gains is None:
        g = (m[0::2, 1::2].mean() + m[1::2, 0::2].mean()) / 2
        gains = (g / max(m[0::2, 0::2].mean(), 1e-6), g / max(m[1::2, 1::2].mean(), 1e-6))
    out = m.copy()
    out[0::2, 0::2] *= gains[0]
    out[1::2, 1::2] *= gains[1]
    return out


def colour(mosaic):
    """The mosaic as (height, width, 3) RGB, each colour filled in between
    its own pixels."""
    m = np.asarray(mosaic, dtype=np.float32)
    r, g, b = _masks(m.shape)
    return np.stack([ndimage.convolve(m * r, BOXED, mode="mirror"), ndimage.convolve(m * g, CROSS, mode="mirror"),
                     ndimage.convolve(m * b, BOXED, mode="mirror")], axis=-1)


def sharpness(image):
    """How sharp a picture is: the spread of its fine detail, on a lightly
    smoothed copy so that noise does not count as detail."""
    smooth = ndimage.gaussian_filter(image, 1.0)
    detail = ndimage.laplace(smooth)
    bright = smooth > 0.25 * smooth.max()
    return float(detail[bright].var() / max(smooth[bright].mean(), 1e-6) ** 2) if bright.any() else 0.0


# --- lining frames up -------------------------------------------------------------

def phase_match(reference, moved):
    """(dy, dx, peak): the shift that puts `moved` on `reference`, to a
    fraction of a pixel, and how far the correlation's peak stands above the
    rest of it (in standard deviations): a weak match has a low peak."""
    window = np.outer(np.hanning(reference.shape[0]), np.hanning(reference.shape[1]))
    a = np.fft.fft2((reference - reference.mean()) * window)
    b = np.fft.fft2((moved - moved.mean()) * window)
    cross = a * np.conj(b)
    surface = np.fft.ifft2(cross / np.maximum(np.abs(cross), 1e-12)).real
    peak = np.unravel_index(np.argmax(surface), surface.shape)
    strength = float((surface[peak] - surface.mean()) / max(surface.std(), 1e-12))
    shift = []
    for axis, p in enumerate(peak):
        n = surface.shape[axis]
        before = surface[tuple((p - 1) % n if i == axis else q for i, q in enumerate(peak))]
        after = surface[tuple((p + 1) % n if i == axis else q for i, q in enumerate(peak))]
        bend = before - 2 * surface[peak] + after
        fine = 0.5 * (before - after) / bend if bend < 0 else 0.0
        shift.append(((p + n // 2) % n - n // 2) + fine)
    return float(shift[0]), float(shift[1]), strength


def phase_shift(reference, moved):
    """(dy, dx) by which `moved` must be shifted to lie on `reference`."""
    return phase_match(reference, moved)[:2]


def _small(a, factor):
    return a[:a.shape[0] // factor * factor, :a.shape[1] // factor * factor].reshape(
        a.shape[0] // factor, factor, a.shape[1] // factor, factor).mean(axis=(1, 3))


def whole_shift(reference, image, factor=4):
    """The shift that puts `image` on `reference` as a whole, found on copies
    a quarter the size: a full frame's correlation is slow, and the alignment
    points refine it."""
    dy, dx = phase_shift(_small(reference, factor), _small(image, factor))
    return dy * factor, dx * factor


def alignment_points(reference, box=BOX, step=STEP, most=MAX_POINTS):
    """Where to align: the grid of patch centres, and which of them are used.
    A patch is used when it is on the bright surface and has detail; when
    more qualify than `most`, those with the most detail are kept, so smooth
    maria and black sky cost nothing. Returns (rows, cols, used mask)."""
    h, w = reference.shape
    rows = np.arange(box // 2, h - box // 2 + 1, step)
    cols = np.arange(box // 2, w - box // 2 + 1, step)
    level = reference.max()
    detail = np.zeros((len(rows), len(cols)), np.float32)
    for i, y in enumerate(rows):
        for j, x in enumerate(cols):
            patch = reference[y - box // 2:y + box // 2, x - box // 2:x + box // 2]
            if patch.mean() > 0.2 * level:
                detail[i, j] = ndimage.laplace(ndimage.gaussian_filter(patch, 1.0)).std() / max(patch.mean(), 1e-6)
    used = detail > 0.5 * np.median(detail[detail > 0]) if (detail > 0).any() else detail > 0
    if used.sum() > most:
        used &= detail >= np.sort(detail[used])[-most]
    return rows, cols, used


def spread(values, found, rows, cols, shape):
    """Values known at some grid points filled in at the others from their
    neighbours, then carried to every pixel. The grid's points sit at the
    patch centres."""
    weight = ndimage.gaussian_filter(found, 1.0) + 1e-9
    smooth = ndimage.gaussian_filter(values * found, 1.0) / weight
    mean = (values * found).sum() / max(found.sum(), 1e-9)
    reach = np.clip(weight / weight.max() * 3, 0, 1)
    coarse = smooth * reach + mean * (1 - reach)
    gy = np.interp(np.arange(shape[0]), rows, np.arange(len(rows)))
    gx = np.interp(np.arange(shape[1]), cols, np.arange(len(cols)))
    yy, xx = np.meshgrid(gy, gx, indexing="ij")
    return ndimage.map_coordinates(coarse, [yy, xx], order=1, mode="nearest").astype(np.float32)


def shift_field(reference, image, points, box=BOX, search=SEARCH):
    """How far each part of `image` must move to lie on `reference`, (dy, dx)
    at every pixel. A point is trusted only when its correlation peak is
    strong, its shift within `search`, and its shift close to its trusted
    neighbours'; the others take the bend of the points around them."""
    rows, cols, used = points
    half = box // 2
    shifts = np.zeros((2,) + used.shape, np.float32)
    found = np.zeros(used.shape, np.float32)
    for i, j in zip(*np.nonzero(used)):
        y, x = rows[i], cols[j]
        dy, dx, peak = phase_match(reference[y - half:y + half, x - half:x + half],
                                   image[y - half:y + half, x - half:x + half])
        if peak >= MIN_PEAK and abs(dy) <= search and abs(dx) <= search:
            shifts[:, i, j] = dy, dx
            found[i, j] = 1
    if found.any():
        # Against the median of each point's trusted neighbours: an outlier
        # would pull the picture like a rubber sheet.
        for k in (0, 1):
            masked = np.where(found > 0, shifts[k], np.nan)
            padded = np.pad(masked, 1, constant_values=np.nan)
            stack = np.stack([padded[1 + di:1 + di + used.shape[0], 1 + dj:1 + dj + used.shape[1]]
                              for di in (-1, 0, 1) for dj in (-1, 0, 1) if di or dj])
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)     # a point with no trusted neighbour
                around = np.nanmedian(stack, axis=0)
            far = (found > 0) & np.isfinite(around) & (np.abs(shifts[k] - around) > NEIGHBOUR_PX)
            found[far] = 0
    if not found.any():
        return np.zeros((2,) + reference.shape, np.float32)
    return np.stack([spread(shifts[k], found, rows, cols, reference.shape) for k in (0, 1)])


def warp(image, field):
    h, w = image.shape[:2]
    rows, cols = np.indices((h, w), dtype=np.float32)
    where = [rows - field[0], cols - field[1]]
    if image.ndim == 3:
        return np.stack([ndimage.map_coordinates(image[..., c], where, order=1, mode="nearest")
                         for c in range(image.shape[2])], axis=-1)
    return ndimage.map_coordinates(image, where, order=1, mode="nearest")


def sharpen(image, amounts=((1.0, 1.2), (2.0, 0.6), (4.0, 0.2))):
    """Detail at a few scales brought up, like a planetary stacker's
    wavelets: (blur in pixels, how much of that scale's detail to add)."""
    blur = (lambda a, s: ndimage.gaussian_filter(a, (s, s, 0))) if image.ndim == 3 else ndimage.gaussian_filter
    out = image.astype(np.float32).copy()
    previous = image.astype(np.float32)
    for sigma, gain in amounts:
        blurred = blur(image.astype(np.float32), sigma)
        out += gain * (previous - blurred)
        previous = blurred
    return out


# --- the stack ------------------------------------------------------------------

def local_sharpness(image, points, box=BOX, shift=(0.0, 0.0)):
    """Sharpness of each alignment point's patch, on the grid (0 where
    unused). `shift` is the frame's whole-frame shift onto the reference:
    the patch is read where that puts the point, without moving the frame."""
    rows, cols, used = points
    half = box // 2
    dy, dx = int(round(shift[0])), int(round(shift[1]))
    h, w = image.shape
    out = np.zeros(used.shape, np.float32)
    for i, j in zip(*np.nonzero(used)):
        y = min(max(rows[i] - dy, half), h - half)
        x = min(max(cols[j] - dx, half), w - half)
        patch = image[y - half:y + half, x - half:x + half]
        out[i, j] = ndimage.laplace(ndimage.gaussian_filter(patch, 1.0)).var() / max(patch.mean(), 1e-6) ** 2
    return out


def stack(frames, keeps=KEEPS, points=True, local=True, in_colour=False, report=print, box=BOX, step=STEP,
          pixels="green"):
    """`frames` (Bayer mosaics) stacked for each share in `keeps` (per cent
    of all frames). Returns ({share: picture}, what was done).

    Ranked by whole-frame sharpness first; the best max(keeps) % are the
    pool. With `local`, every alignment point then takes its own best share
    of the pool, by the sharpness of its own patch, and a frame adds to each
    part of the picture as much as it was chosen there. `pixels` is the
    detail picture: "green" (the greens filled in) or "all" (balanced())."""
    say = report or (lambda line: None)
    total = len(frames)
    look = green
    if pixels == "all":
        middle = np.asarray(frames[total // 2], dtype=np.float32)
        g = (middle[0::2, 1::2].mean() + middle[1::2, 0::2].mean()) / 2
        gains = (g / max(middle[0::2, 0::2].mean(), 1e-6), g / max(middle[1::2, 1::2].mean(), 1e-6))
        look = lambda mosaic: balanced(mosaic, gains)      # noqa: E731 - the detail picture for this stack
    keeps = sorted({float(k) for k in keeps})
    scores = []
    for i in range(total):
        scores.append(sharpness(look(frames[i])))
        if (i + 1) % 100 == 0:
            say(f"ranked {i + 1} of {total}")
            progress("ranking", done=i + 1, frames=total)
    order = np.argsort(scores)[::-1]
    pool = order[:max(1, round(total * keeps[-1] / 100))]
    best = look(frames[pool[0]])
    # The reference: the best frames, each moved as a whole onto the best,
    # averaged. The air bends each frame a different way, so their average
    # has the surface's true shape, which no single frame has.
    few = pool[:max(1, min(50, round(total * keeps[0] / 100) or 1))]
    reference = np.zeros_like(best)
    for i in few:
        image = look(frames[i])
        reference += ndimage.shift(image, whole_shift(best, image), order=1, mode="nearest")
    reference /= len(few)
    aps = alignment_points(reference, box, step) if points else None
    shifts = {}
    choose = {k: None for k in keeps}
    if local and aps is not None and aps[2].any():
        # Every frame's sharpness at every point, then each point's own
        # ranking: a frame middling overall but sharp in one part is chosen
        # there. Only frames chosen somewhere are then lined up and added.
        quality = np.zeros((total,) + aps[2].shape, np.float32)
        for i in range(total):
            image = look(frames[i])
            shifts[i] = whole_shift(reference, image)
            quality[i] = local_sharpness(image, aps, box, shifts[i])
            if (i + 1) % 100 == 0:
                say(f"measured {i + 1} of {total} part by part")
                progress("ranking", done=i + 1, frames=total)
        rank = np.argsort(np.argsort(-quality, axis=0), axis=0)
        for k in keeps:
            choose[k] = rank < max(1, round(total * k / 100))
        pool = np.nonzero(choose[keeps[-1]].any(axis=(1, 2)))[0]
    sums = {k: None for k in keeps}
    weights = {k: None for k in keeps}
    for n, i in enumerate(pool):
        image = look(frames[i])
        shift = shifts.get(i) or whole_shift(reference, image)
        moved = ndimage.shift(image, shift, order=1, mode="nearest")
        field = shift_field(reference, moved, aps, box) if aps is not None else None
        picture = colour(frames[i]) if in_colour else image
        if in_colour:
            picture = np.stack([ndimage.shift(picture[..., c], shift, order=1, mode="nearest")
                                for c in range(3)], axis=-1)
        else:
            picture = moved
        if field is not None:
            picture = warp(picture, field)
        for k in keeps:
            if choose[k] is not None:
                part = choose[k][i].astype(np.float32)
                if not part.any():
                    continue
                weight = np.clip(spread(part, aps[2].astype(np.float32), aps[0], aps[1], reference.shape), 0, 1)
            elif n < round(total * k / 100) or n == 0:
                weight = np.ones(reference.shape, np.float32)
            else:
                continue
            w = weight[..., None] if in_colour else weight
            sums[k] = picture * w if sums[k] is None else sums[k] + picture * w
            weights[k] = w if weights[k] is None else weights[k] + w
        if (n + 1) % 25 == 0:
            say(f"stacked {n + 1} of {len(pool)}")
            progress("stacking", done=n + 1, frames=len(pool), points=int(aps[2].sum()) if aps is not None else 0)
    results = {k: sums[k] / np.maximum(weights[k], 1e-6) for k in keeps if sums[k] is not None}
    done = {"frames": total, "pool": int(len(pool)),
            "kept": {f"{k:g}": int(max(1, round(total * k / 100))) for k in keeps},
            "alignment_points": int(aps[2].sum()) if aps is not None else 0, "local": bool(choose[keeps[0]] is not None),
            "sharpness": {f"{k:g}": float(f"{sharpness(results[k] if results[k].ndim == 2 else results[k].mean(axis=2)):.4g}")
                          for k in results}}
    return results, done


def grey_moon(image):
    """A colour stack with its three colours brought to one level over the
    lit surface, which is near enough grey: the camera's green pixels take
    in more light than its red and blue, so unbalanced the Moon came out
    green (30 October 2026: red 116, green 147, blue 93 on the disc).
    A one-colour picture is returned as it is."""
    image = np.asarray(image, dtype=np.float32)
    if image.ndim != 3:
        return image
    level = image.mean(axis=-1)
    lit = level > 0.25 * np.percentile(level, 99.9)
    means = np.array([np.median(image[..., c][lit]) if lit.any() else image[..., c].mean() for c in range(3)])
    return image * (means.mean() / np.maximum(means, 1e-6))


def picture(image, path, balance=True):
    """An 8-bit picture of a stack, black to the brightest surface, a colour
    one balanced to a grey Moon unless `balance` is off."""
    from PIL import Image
    image = grey_moon(image) if balance else np.asarray(image, dtype=np.float32)
    low, high = np.percentile(image, [0.5, 99.95])
    scaled = np.clip((image - low) / max(high - low, 1e-6), 0, 1) ** (1 / 1.4)
    out = Image.fromarray((scaled * 255).astype(np.uint8))
    if out.width > 1600:
        out = out.resize((1600, round(out.height * 1600 / out.width)), Image.LANCZOS)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.save(path, quality=92)
    return path


MINERAL_SPREAD = 0.35     # the strongest colour on the disc after turning it up, as a share of the brightness
COLOUR_BLUR = 4.0         # pixels the colour is smoothed over: its noise is far coarser than the detail's


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
        out[..., c] = ndimage.shift(rgb[..., c], phase_shift(_middle(rgb[..., 1]), _middle(rgb[..., c])),
                                    order=1, mode="nearest")
    return out


def unclipped(image, ceiling=None, margin=0.8):
    """Where no colour of a stack came near the top of the camera's range
    (`ceiling`; none given, nothing counts as clipped): a clipped green turns
    the colour magenta when it is turned up (30 October 2026: the 01:55
    video was overexposed, every colour at 255 over the bright side). Well
    short of the top, as a stack averages frames that clipped with ones the
    seeing blurred below it: that video's brightest crater stacked to 237
    of 255 at half its true brightness."""
    image = np.asarray(image, dtype=np.float32)
    brightest = image.max(axis=-1) if image.ndim == 3 else image
    return np.ones(brightest.shape, bool) if ceiling is None else brightest < margin * ceiling


def flattened(tint, where):
    """`tint` with a flat slope across the disc taken off each colour: on 30
    October 2026 red against green rose 2.3 % from the terminator to the limb
    in both videos alike, five times the minerals' own 0.5 %, and turned up
    it painted one side green and the other magenta."""
    yy, xx = np.indices(where.shape)
    if where.sum() < 3:
        return tint
    rows = np.c_[np.ones(where.sum()), xx[where], yy[where]]
    out = tint.copy()
    for k in range(tint.shape[-1]):
        a, bx, by = np.linalg.lstsq(rows, tint[..., k][where], rcond=None)[0]
        out[..., k] = tint[..., k] - (a + bx * xx + by * yy)
    return out


def blue_to_orange(tint):
    """Only the part of `tint` running from blue to orange (red against
    blue), where the Moon's minerals show: the titanium-rich seas bluer,
    the iron-rich ones browner. Green against magenta is this camera's, not
    the Moon's: its greens fill in from twice the pixels and clip first, and
    on 30 October 2026 that axis, turned up, painted the highlands magenta
    and the seas green."""
    half = (tint[..., 0] - tint[..., 2]) / 2
    return np.stack([half, np.zeros_like(half), -half], -1)


FEATHER = 12.0            # pixels over which a stack fades out towards where it clipped


def feathered(good, width=FEATHER):
    """A 0-1 weight from `good`, fading to nothing a little inside its edge:
    a hard edge left blotches where one stack dropped out and the others,
    a touch darker or brighter, took over (30 October 2026)."""
    if good.all():
        return good.astype(np.float32)
    inside = ndimage.binary_erosion(good, iterations=int(width), border_value=1)
    return ndimage.gaussian_filter(inside.astype(np.float32), width / 2, mode="nearest")


def mineral(colours, details, spread=MINERAL_SPREAD, blur=COLOUR_BLUR, ceiling=None):
    """A "mineral Moon": the detail of `details` (stacks, any number,
    averaged then sharpened) coloured by `colours` (RGB stacks, averaged)
    with the Moon's faint colour turned up until its strongest reaches
    `spread` of the brightness. Pixels a stack clipped are left out of it.
    Everything is lined up on the first detail picture. Returns (picture,
    how far the colour was turned up)."""
    def level(a):
        return np.asarray(a, dtype=np.float32).mean(axis=-1) if np.ndim(a) == 3 else np.asarray(a, np.float32)

    def onto(a, shift):
        return ndimage.shift(a, shift, order=1, mode="nearest")
    base = level(details[0])
    lit = base > 0.08 * np.percentile(base, 99.9)
    detail, counted, brightest = np.zeros_like(base), np.zeros_like(base), np.zeros_like(base)
    for d in details:
        good = unclipped(d, ceiling)
        d = level(d)
        d = d / max(np.median(d[lit & good]) if (lit & good).any() else d.mean(), 1e-6)
        shift = whole_shift(base, d)
        weight = onto(feathered(good), shift)
        moved = onto(d, shift)
        detail += moved * weight
        counted += weight
        brightest = np.maximum(brightest, moved)
    # where every stack clipped, the brightest of them is the nearest the
    # truth: their average sat a grey blob in the brightest craters
    blend = np.clip(counted, 0, 1)
    detail = sharpen(blend * detail / np.maximum(counted, 1e-6) + (1 - blend) * brightest)
    colour_sum, weights = np.zeros(base.shape + (3,), np.float32), np.zeros_like(base)
    for c in colours:
        good = unclipped(c, ceiling)
        c = channels_lined_up(np.asarray(c, dtype=np.float32))
        means = np.array([np.median(c[..., k][lit & good]) for k in range(3)])
        c = c / np.maximum(means, 1e-6)
        shift = whole_shift(base, level(c))
        weight = onto(feathered(good), shift)
        colour_sum += np.stack([onto(c[..., k], shift) for k in range(3)], -1) * weight[..., None]
        weights += weight
    grey = colour_sum.mean(axis=-1, keepdims=True)
    tint = np.where(weights[..., None] > 0.5, colour_sum / np.maximum(grey, 1e-6) - 1, 0)
    tint = blue_to_orange(flattened(tint, lit & (weights > 0.5)))
    tint = np.stack([ndimage.gaussian_filter(tint[..., k], blur) for k in range(3)], -1)
    inner = ndimage.binary_erosion(lit & (weights > 0.5), iterations=int(4 * blur) + 1)    # rims kept out
    tint *= ndimage.gaussian_filter(inner.astype(np.float32), blur)[..., None]
    reach = float(np.percentile(np.abs(tint[inner]), 99)) if inner.any() else 0.0
    gain = spread / reach if reach > 1e-6 else 1.0
    return np.clip(detail[..., None] * (1 + gain * tint), 0, None), gain


def mineral_file(stems, out=None):
    """The mineral Moon from lucky stacks named by their stem (the SER file
    without .ser): colour from each one's largest share, detail from the
    share it showed. Writes STEM-mineral.fits and .jpg beside the first."""
    from astropy.io import fits
    colours, details = [], []
    for stem in stems:
        stem = Path(str(stem).removesuffix(".ser"))
        done = json.loads(stem.with_suffix(".stack.json").read_text(encoding="utf-8"))
        largest = max(done["kept"], key=float)
        colours.append(fits.getdata(stem.with_name(f"{stem.name}.best{largest}.fits")))
        details.append(fits.getdata(stem.with_name(f"{stem.name}.best{done['shown']}.fits")))
        print(f"{stem.name}: colour from the best {largest} %, detail from the best {done['shown']} %", flush=True)
    ceiling = 255.0 if max(float(np.max(c)) for c in colours) <= 255.5 else 65535.0    # 8- or 16-bit videos
    image, gain = mineral(colours, details, ceiling=ceiling)
    out = Path(out or Path(str(stems[0]).removesuffix(".ser")).with_name(Path(str(stems[0])).name.removesuffix(".ser")
                                                                         + "-mineral.fits"))
    fits.PrimaryHDU(image.astype(np.float32)).writeto(out, overwrite=True)
    jpg = picture(image, out.with_suffix(".jpg"), balance=False)
    print(f"colour turned up {gain:.0f} times: {jpg}", flush=True)
    return jpg, gain


@activity.during("Stacking the lucky frames", "{path}")
def stack_file(path, keeps=KEEPS, in_colour=False, publish=True, pixels="green"):
    """Stack a SER file for each share in `keeps`, keep every result beside
    it (unsharpened and sharpened, FITS and a picture), and show the sharpest
    on the status page. Returns what was done, with the share shown."""
    from astropy.io import fits
    path = Path(path)
    frames, code = read_ser(path)
    if code != SER_RGGB:
        raise SystemExit(f"{path}: only RGGB colour videos are read (colour ID {code})")
    print(f"{path.name}: {len(frames)} frames of {frames.shape[2]}x{frames.shape[1]}; "
          f"stacking the best {', '.join(f'{k:g}' for k in keeps)} %", flush=True)
    results, done = stack(frames, keeps=keeps, in_colour=in_colour, report=lambda line: print(line, flush=True),
                          pixels=pixels)
    shown = max(done["sharpness"], key=done["sharpness"].get)
    for share, image in results.items():
        stem = path.with_suffix("").name + f".best{share:g}"
        fits.PrimaryHDU(image.astype(np.float32)).writeto(path.with_name(stem + ".fits"), overwrite=True)
        final = sharpen(image)
        fits.PrimaryHDU(final.astype(np.float32)).writeto(path.with_name(stem + ".sharp.fits"), overwrite=True)
        picture(image, path.with_name(stem + ".jpg"))
        jpg = picture(final, path.with_name(stem + ".sharp.jpg"))
        print(f"best {share:g} %: {done['kept'][f'{share:g}']} frames, sharpness {done['sharpness'][f'{share:g}']}"
              + ("  <- shown" if f"{share:g}" == shown else ""), flush=True)
        if publish and f"{share:g}" == shown:
            import snap
            shutil.copyfile(jpg, PREVIEW)
            snap.label("lucky stack", f"best {done['kept'][shown]} of {done['frames']} frames, "
                       f"{done['alignment_points']} alignment points", name="stack")
    done["shown"] = shown
    (path.with_suffix(".stack.json")).write_text(json.dumps(done, indent=1), encoding="utf-8")
    progress("done", frames=done["frames"], kept=done["kept"][shown], points=done["alignment_points"], share=shown)
    if publish:
        import notify
        notify.stack_ready(f"{path.with_suffix('').name}, the best {done['kept'][shown]} of {done['frames']} frames"
                           + (" in colour" if in_colour else ""),
                           path.with_name(path.with_suffix("").name + f".best{shown}.sharp.jpg"))
    return done


# --- taking the video -------------------------------------------------------------

def capture_into(cam, path, frames, exposure, roi=None, depth=8, writer=None, publish=True):
    """`frames` frames of video from an open camera into a SER file (a new
    one, or `writer` to carry one on). Returns (writer, what came)."""
    import snap
    white = 2 ** config.hardware()["camera"]["bit_depth"] - 1
    shown = began = time.perf_counter()
    last_seq, dropped, n = None, 0, 0
    for n, (mosaic, _, seq) in enumerate(cam.video(exposure, frames, roi=roi), 1):
        if writer is None:
            writer = SerWriter(path, mosaic.shape[1], mosaic.shape[0], instrument=cam.name, depth=depth, white=white)
        writer.add(mosaic)
        if seq and last_seq and seq > last_seq + 1:
            dropped += seq - last_seq - 1
        last_seq = seq or last_seq
        # The page and the stream show the video as it is taken, not the
        # last picture from before it (24 October 2026).
        if publish and (n == 1 or time.perf_counter() - shown >= PUBLISH_S):
            snap.publish(mosaic, kind="lucky-imaging video", detail=f"frame {n} of {frames}", quick=True)
            rate = n / max(time.perf_counter() - began, 1e-6)
            progress("capturing", done=writer.count, frames=frames, fps=round(rate, 1), exposure=exposure)
            shown = time.perf_counter()
    took = time.perf_counter() - began
    return writer, {"frames": n, "seconds": round(took, 1), "fps": round(n / max(took, 1e-6), 1),
                    "dropped": dropped, "last": mosaic if n else None}


def write_notes(path, notes):
    path = Path(path)
    path.with_suffix(".json").write_text(json.dumps(notes, indent=1, default=str), encoding="utf-8")


@activity.during("Taking a lucky-imaging video", "{target}")
def capture(target, frames, exposure, gain, roi=None, depth=8):
    import shoot
    from camera import Camera
    _rig = shoot.hold_the_rig(f"{target} video")
    path = OUT / f"{target.replace(' ', '')}-{datetime.now():%Y%m%d-%H%M%S}.ser"
    cam = Camera(gain=gain)
    if not hasattr(cam, "video"):
        raise SystemExit("lucky imaging needs the camera through Altair's library ([camera] backend = \"altair\")")
    writer = None
    try:
        writer, came = capture_into(cam, path, frames, exposure, roi=roi, depth=depth)
    finally:
        if writer:
            writer.close()
        cam.close()
    came.pop("last", None)
    write_notes(path, {"target": target, "exposure": exposure, "gain": gain, "roi": roi, "depth": depth, **came})
    print(f"{came['frames']} frames in {came['seconds']:.0f} s ({came['fps']} a second, {came['dropped']} dropped "
          f"by the camera): {path}", flush=True)
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["capture", "stack", "picture", "mineral"])
    ap.add_argument("target", nargs="+",
                    help="capture: the object's name; stack: the SER file; picture: stacks' FITS files to draw again; "
                         "mineral: the stacked SER files to combine")
    ap.add_argument("--frames", type=int, default=1000, help="capture: frames in the video")
    ap.add_argument("--exposure", type=float, default=0.01, help="capture: seconds a frame")
    ap.add_argument("--gain", type=int, default=100)
    ap.add_argument("--roi", type=int, nargs=4, metavar=("X", "Y", "W", "H"),
                    help="capture: only this part of the sensor, for a faster video")
    ap.add_argument("--depth", type=int, choices=(8, 16), default=8, help="capture: bits a pixel in the SER file")
    ap.add_argument("--keep", type=float, nargs="+", default=list(KEEPS),
                    help="stack: the shares of frames to stack, in per cent")
    ap.add_argument("--colour", action="store_true", help="stack: natural colour rather than green detail")
    ap.add_argument("--pixels", choices=("green", "all"), default="green",
                    help="stack: the detail picture from the greens filled in, or every pixel balanced")
    ap.add_argument("--then-stack", action="store_true", help="capture: stack it straight after")
    args = ap.parse_args()
    if args.command == "picture":
        from astropy.io import fits
        for name in args.target:
            print(picture(fits.getdata(name), Path(name).with_suffix(".jpg")))
        return
    if args.command == "mineral":
        jpg, gain = mineral_file(args.target)
        import notify
        notify.stack_ready(f"Mineral Moon from {len(args.target)} videos, colour turned up {gain:.0f} times", jpg)
        return
    args.target = args.target[0]
    if args.command == "capture":
        path = capture(args.target, args.frames, args.exposure, args.gain, roi=args.roi, depth=args.depth)
        if args.then_stack:
            stack_file(path, keeps=args.keep, in_colour=args.colour, pixels=args.pixels)
    else:
        stack_file(args.target, keeps=args.keep, in_colour=args.colour, pixels=args.pixels)


if __name__ == "__main__":
    sys.exit(main())
