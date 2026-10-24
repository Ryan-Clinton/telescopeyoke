#!/usr/bin/env python3
"""Lucky imaging of the Moon (or the Sun, or a planet): a fast video, the
sharpest frames kept, and a multi-point stack that undoes the seeing.

    ./lucky.py capture Moon --frames 600 --exposure 0.02 --gain 100
    ./lucky.py stack frames/lucky/Moon-20261024-0210.ser --keep 20

`capture` takes the frames back to back in the camera's video mode and
writes them as one SER file, the format every planetary stacker reads.
`stack` ranks each frame by its sharpness, keeps the best share, and lines
each one up with the reference twice: as a whole, then in small patches
(alignment points) across the surface, so a frame bent by the air is put
straight piece by piece before it is added. A deep-sky stack cannot do
that: it moves each frame as a whole. The result is sharpened and kept
beside the video as FITS and a picture, and shown on the status page.

The colour camera's raw frame is read as one grey picture at the full
resolution (each colour's pixels scaled to the green's level), since the
Moon has next to no colour and the 2x2 colour picture would halve the
detail. 24 October 2026: the Moon through the deep-sky stacker at one frame
a second; this is the method the planetary stackers use.
"""
import argparse
import struct
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy import ndimage

import activity
import config

OUT = config.DATA / "frames" / "lucky"
PREVIEW = config.DATA / "web" / "stack.jpg"
SER_HEADER = 178
SER_RGGB = 8         # SER's colour ID for an RGGB Bayer mosaic
BOX = 96             # alignment point size, pixels
STEP = 64            # alignment point spacing
PUBLISH_S = 3.0      # seconds between frames shown on the page during a video
SEARCH = 24         # furthest a patch is looked for from where the whole-frame shift puts it


# --- SER files -----------------------------------------------------------------

def ser_header(width, height, frames, depth=12, colour=SER_RGGB, instrument="", when=None):
    when = when or datetime.now(timezone.utc)
    # SER's dates are .NET ticks: 100 ns since 1 January of year 1.
    ticks = int((when - datetime(1, 1, 1, tzinfo=timezone.utc)).total_seconds() * 1e7)
    return (b"LUCAM-RECORDER" + struct.pack("<7i", 0, colour, 0, width, height, depth, frames)
            + b"telescopeyoke".ljust(40, b"\0") + instrument.encode()[:40].ljust(40, b"\0")
            + b"Sky-Watcher 150P".ljust(40, b"\0") + struct.pack("<2q", ticks, ticks))


class SerWriter:
    """Frames written one at a time; the count in the header is put right
    when it is closed."""

    def __init__(self, path, width, height, instrument=""):
        self.path, self.width, self.height, self.count = Path(path), width, height, 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = open(self.path, "wb")
        self.file.write(ser_header(width, height, 0, instrument=instrument))

    def add(self, mosaic):
        if mosaic.shape != (self.height, self.width):
            raise ValueError(f"frame {mosaic.shape[::-1]} is not the video's {self.width}x{self.height}")
        self.file.write(np.ascontiguousarray(mosaic, dtype="<u2").tobytes())
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
    _, colour, little, width, height, depth, frames = struct.unpack("<7i", head[14:42])
    dtype = np.dtype("<u2" if depth > 8 else "u1")
    if depth > 8 and not little:
        # The spec's flag is read both ways by different programs; ours writes 0 for little-endian.
        dtype = np.dtype("<u2")
    data = np.memmap(path, dtype=dtype, mode="r", offset=SER_HEADER, shape=(frames, height, width))
    return data, colour


# --- turning a frame into one grey picture --------------------------------------

def balance(mosaic):
    """Gains that bring the red and blue pixels of an RGGB mosaic to the
    green's level, from the frame itself."""
    m = mosaic.astype(np.float32)
    g = (m[0::2, 1::2].mean() + m[1::2, 0::2].mean()) / 2
    return g / max(m[0::2, 0::2].mean(), 1e-6), g / max(m[1::2, 1::2].mean(), 1e-6)


def grey(mosaic, gains):
    """The mosaic at full resolution, each pixel scaled to the green's level."""
    out = mosaic.astype(np.float32)
    out[0::2, 0::2] *= gains[0]
    out[1::2, 1::2] *= gains[1]
    return out


def sharpness(image):
    """How sharp a frame is: the spread of its fine detail, on a lightly
    smoothed copy so that noise does not count as detail."""
    smooth = ndimage.gaussian_filter(image, 1.0)
    detail = ndimage.laplace(smooth)
    bright = smooth > 0.25 * smooth.max()
    return float(detail[bright].var() / max(smooth[bright].mean(), 1e-6) ** 2) if bright.any() else 0.0


# --- lining frames up -------------------------------------------------------------

def phase_shift(reference, moved):
    """(dy, dx) by which `moved` must be shifted to lie on `reference`, to a
    fraction of a pixel, from the peak of their phase correlation."""
    window = np.outer(np.hanning(reference.shape[0]), np.hanning(reference.shape[1]))
    a = np.fft.fft2((reference - reference.mean()) * window)
    b = np.fft.fft2((moved - moved.mean()) * window)
    cross = a * np.conj(b)
    surface = np.fft.ifft2(cross / np.maximum(np.abs(cross), 1e-12)).real
    peak = np.unravel_index(np.argmax(surface), surface.shape)
    shift = []
    for axis, p in enumerate(peak):
        n = surface.shape[axis]
        before = surface[tuple((p - 1) % n if i == axis else q for i, q in enumerate(peak))]
        after = surface[tuple((p + 1) % n if i == axis else q for i, q in enumerate(peak))]
        bend = before - 2 * surface[peak] + after
        fine = 0.5 * (before - after) / bend if bend < 0 else 0.0
        shift.append(((p + n // 2) % n - n // 2) + fine)
    return float(shift[0]), float(shift[1])


def alignment_points(reference, box=BOX, step=STEP):
    """The grid of patches across the picture, and which of them are worth
    aligning on: on the bright surface and with enough detail to find.
    Returns (rows of centres, columns of centres, a mask of the good ones)."""
    h, w = reference.shape
    rows = np.arange(box // 2, h - box // 2 + 1, step)
    cols = np.arange(box // 2, w - box // 2 + 1, step)
    level = reference.max()
    good = np.zeros((len(rows), len(cols)), bool)
    for i, y in enumerate(rows):
        for j, x in enumerate(cols):
            patch = reference[y - box // 2:y + box // 2, x - box // 2:x + box // 2]
            good[i, j] = patch.mean() > 0.2 * level and patch.std() > 0.02 * patch.mean()
    return rows, cols, good


def shift_field(reference, image, points, box=BOX, search=SEARCH):
    """How far each part of `image` must move to lie on `reference`: a shift
    for every pixel, (dy, dx), from the alignment points' own shifts, spread
    smoothly between them and over the patches with nothing to align on.
    A point whose patch is not found within `search` is left out."""
    rows, cols, good = points
    h, w = reference.shape
    half = box // 2
    shifts = np.zeros((2,) + good.shape, np.float32)
    found = np.zeros(good.shape, np.float32)
    for i, j in zip(*np.nonzero(good)):
        y, x = rows[i], cols[j]
        dy, dx = phase_shift(reference[y - half:y + half, x - half:x + half],
                             image[y - half:y + half, x - half:x + half])
        if abs(dy) <= search and abs(dx) <= search:
            shifts[:, i, j] = dy, dx
            found[i, j] = 1
    if not found.any():
        return np.zeros((2, h, w), np.float32)
    # Missing points filled from their neighbours, and the whole lightly
    # smoothed so one bad patch cannot tear the picture.
    weight = ndimage.gaussian_filter(found, 1.0) + 1e-9
    smooth = np.stack([ndimage.gaussian_filter(shifts[k] * found, 1.0) / weight for k in (0, 1)])
    mean = (shifts * found).sum(axis=(1, 2)) / found.sum()
    reach = np.clip(weight / weight.max() * 3, 0, 1)
    coarse = smooth * reach + mean[:, None, None] * (1 - reach)
    # Up to every pixel: the grid's points sit at the patch centres.
    gy = np.interp(np.arange(h), rows, np.arange(len(rows)))
    gx = np.interp(np.arange(w), cols, np.arange(len(cols)))
    yy, xx = np.meshgrid(gy, gx, indexing="ij")
    return np.stack([ndimage.map_coordinates(coarse[k], [yy, xx], order=1, mode="nearest")
                     for k in (0, 1)]).astype(np.float32)


def whole_shift(reference, image, factor=4):
    """The shift that puts `image` on `reference` as a whole, found on
    copies a quarter the size: a full frame's correlation is slow, and the
    alignment points refine it."""
    small = lambda a: a[:a.shape[0] // factor * factor, :a.shape[1] // factor * factor].reshape(
        a.shape[0] // factor, factor, a.shape[1] // factor, factor).mean(axis=(1, 3))
    dy, dx = (v * factor for v in phase_shift(small(reference), small(image)))
    return dy, dx


def warp(image, field):
    h, w = image.shape
    rows, cols = np.indices((h, w), dtype=np.float32)
    return ndimage.map_coordinates(image, [rows - field[0], cols - field[1]], order=1, mode="nearest")


def sharpen(image, amounts=((1.0, 1.2), (2.0, 0.6), (4.0, 0.2))):
    """Detail at a few scales brought up, like a planetary stacker's
    wavelets: (blur in pixels, how much of that scale's detail to add)."""
    out = image.astype(np.float32).copy()
    previous = image.astype(np.float32)
    for sigma, gain in amounts:
        blurred = ndimage.gaussian_filter(image.astype(np.float32), sigma)
        out += gain * (previous - blurred)
        previous = blurred
    return out


# --- the stack ------------------------------------------------------------------

def stack(frames, keep=20.0, points=True, progress=print, box=BOX, step=STEP):
    """The best `keep` per cent of `frames` (Bayer mosaics, or grey
    pictures if 2-D floats are given), lined up and averaged. Returns the
    stacked grey picture and what was done."""
    total = len(frames)
    gains = balance(np.asarray(frames[total // 2]))
    scores = []
    for i in range(total):
        scores.append(sharpness(grey(np.asarray(frames[i]), gains)))
        if progress and (i + 1) % 100 == 0:
            progress(f"ranked {i + 1} of {total}")
    order = np.argsort(scores)[::-1]
    chosen = order[:max(1, round(total * keep / 100))]
    best = grey(np.asarray(frames[chosen[0]]), gains)
    # The reference: the kept frames, each moved as a whole onto the best,
    # averaged. The air bends each frame a different way, so their average
    # has the surface's true shape, which no single frame has.
    few = chosen[:50]
    reference = np.zeros_like(best)
    for i in few:
        image = grey(np.asarray(frames[i]), gains)
        reference += ndimage.shift(image, whole_shift(best, image), order=1, mode="nearest")
    reference /= len(few)
    aps = alignment_points(reference, box, step) if points else None
    total_image = np.zeros_like(reference)
    for n, i in enumerate(chosen, 1):
        image = grey(np.asarray(frames[i]), gains)
        image = ndimage.shift(image, whole_shift(reference, image), order=1, mode="nearest")
        if aps is not None:
            image = warp(image, shift_field(reference, image, aps, box))
        total_image += image
        if progress and n % 25 == 0:
            progress(f"stacked {n} of {len(chosen)}")
    result = total_image / len(chosen)
    return result, {"frames": total, "kept": int(len(chosen)), "alignment_points": int(aps[2].sum()) if aps is not None else 0,
                    "best_sharpness": round(float(scores[order[0]]), 6),
                    "kept_sharpness_from": round(float(scores[chosen[-1]]), 6)}


def picture(image, path):
    """An 8-bit picture of the stack, black to the brightest surface."""
    from PIL import Image
    low, high = np.percentile(image, [0.5, 99.95])
    scaled = np.clip((image - low) / max(high - low, 1e-6), 0, 1) ** (1 / 1.4)
    out = Image.fromarray((scaled * 255).astype(np.uint8))
    if out.width > 1600:
        out = out.resize((1600, round(out.height * 1600 / out.width)), Image.LANCZOS)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.save(path, quality=92)
    return path


@activity.during("Stacking the lucky frames", "{path}")
def stack_file(path, keep=20.0, publish=True):
    from astropy.io import fits
    path = Path(path)
    frames, colour = read_ser(path)
    if colour != SER_RGGB:
        raise SystemExit(f"{path}: only RGGB colour videos are read (colour ID {colour})")
    print(f"{path.name}: {len(frames)} frames of {frames.shape[2]}x{frames.shape[1]}; keeping the best {keep:g}%",
          flush=True)
    image, done = stack(frames, keep=keep, progress=lambda line: print(line, flush=True))
    final = sharpen(image)
    fits.PrimaryHDU(image.astype(np.float32)).writeto(path.with_suffix(".stack.fits"), overwrite=True)
    fits.PrimaryHDU(final.astype(np.float32)).writeto(path.with_suffix(".sharp.fits"), overwrite=True)
    shown = picture(final, path.with_suffix(".jpg"))
    if publish:
        import shutil
        import snap
        shutil.copyfile(shown, PREVIEW)
        snap.label("lucky stack", f"best {done['kept']} of {done['frames']} frames, "
                   f"{done['alignment_points']} alignment points", name="stack")
    print(f"kept {done['kept']} of {done['frames']}, {done['alignment_points']} alignment points; "
          f"saved {shown}", flush=True)
    return done


# --- taking the video -------------------------------------------------------------

@activity.during("Taking a lucky-imaging video", "{target}")
def capture(target, frames, exposure, gain, roi=None):
    import shoot
    from camera import Camera
    _rig = shoot.hold_the_rig(f"{target} video")
    stamp = datetime.now()
    path = OUT / f"{target.replace(' ', '')}-{stamp:%Y%m%d-%H%M%S}.ser"
    cam = Camera(gain=gain)
    if not hasattr(cam, "video"):
        raise SystemExit("lucky imaging needs the camera through Altair's library ([camera] backend = \"altair\")")
    import snap
    writer = None
    began = shown = time.perf_counter()
    try:
        for n, (mosaic, _) in enumerate(cam.video(exposure, frames, roi=roi), 1):
            if writer is None:
                writer = SerWriter(path, mosaic.shape[1], mosaic.shape[0], instrument=cam.name)
            writer.add(mosaic)
            # The page and the stream show the video as it is taken, not
            # the last picture from before it (24 October 2026).
            if n == 1 or time.perf_counter() - shown >= PUBLISH_S:
                snap.publish(mosaic, kind="lucky-imaging video", detail=f"frame {n} of {frames}", quick=True)
                shown = time.perf_counter()
            if n % 100 == 0:
                print(f"{n} frames, {n / (time.perf_counter() - began):.1f} a second", flush=True)
    finally:
        if writer:
            writer.close()
        cam.close()
    took = time.perf_counter() - began
    print(f"{writer.count if writer else 0} frames in {took:.0f} s "
          f"({(writer.count if writer else 0) / max(took, 1e-6):.1f} a second): {path}", flush=True)
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["capture", "stack"])
    ap.add_argument("target", help="capture: the object's name; stack: the SER file")
    ap.add_argument("--frames", type=int, default=600, help="capture: frames in the video")
    ap.add_argument("--exposure", type=float, default=0.02, help="capture: seconds a frame")
    ap.add_argument("--gain", type=int, default=100)
    ap.add_argument("--roi", type=int, nargs=4, metavar=("X", "Y", "W", "H"),
                    help="capture: only this part of the sensor, for a faster video")
    ap.add_argument("--keep", type=float, default=20.0, help="stack: the best per cent of frames to keep")
    ap.add_argument("--then-stack", action="store_true", help="capture: stack it straight after")
    args = ap.parse_args()
    if args.command == "capture":
        path = capture(args.target, args.frames, args.exposure, args.gain, roi=args.roi)
        if args.then_stack:
            stack_file(path, keep=args.keep)
    else:
        stack_file(args.target, keep=args.keep)


if __name__ == "__main__":
    sys.exit(main())
