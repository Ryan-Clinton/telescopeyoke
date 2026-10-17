#!/usr/bin/env python3
"""Turn a stacked picture into a cleaner image for viewing.

    ./process.py M27                 newest frames/M27-*.fits -> web/M27-processed.jpg
    ./process.py M27 --crop 600      also a close-up of the middle, 600 pixels wide

shoot.py's own preview is stretched hard so faint things show while the stack
builds, which also shows every bit of grain. This evens out the background,
smooths the colour noise (the eye forgives soft colour far more than soft
detail), and uses a gentler stretch with a properly dark sky.
"""
import argparse
from pathlib import Path

import config

import numpy as np
from astropy.io import fits
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

import stacking

ROOT = Path(__file__).parent


def process(rgb, detail=0.8, colour=5.0, stretch=None, background=2, saturation=1.25):
    """rgb: float array (rows, cols, 3) from a stack. Returns 8-bit RGB."""
    rgb = rgb.astype(np.float32)
    # Level each channel: take out the sky glow and its gradient, then match
    # the channels' scales on the stars so the sky is neutral grey.
    # Take out the sky glow with a smooth surface fitted to the sky alone:
    # a tilt, or a gentle bowl at order 2. Anything finer would remove the
    # nebula along with the sky. At order 0 only a level is taken off, and
    # that from the darkest tenth of the picture: for something that fills
    # the frame there is no sky to fit a surface to, and a bowl fitted to
    # the fainter half took most of M31's disc away with it.
    rows, cols = rgb.shape[:2]
    yy, xx = np.mgrid[0:rows:64, 0:cols:64]
    terms = lambda y, x: ([np.ones_like(y)] + ([y, x] if background else [])
                          + ([y * y, x * x, y * x] if background == 2 else []))
    ys, xs = yy.ravel() / rows, xx.ravel() / cols
    design = np.column_stack(terms(ys, xs))
    full_y, full_x = np.mgrid[0:rows, 0:cols]
    full = [t.astype(np.float32) for t in terms(full_y / rows, full_x / cols)]
    for c in range(3):
        samples = ndimage.median_filter(rgb[::64, ::64, c], 3).ravel()
        # Sky only: leave out stars, nebula and the empty edges of a stack.
        filled = samples[samples != 0]
        keep = (samples < np.percentile(filled if len(filled) else samples, 60 if background else 10)) \
            & (samples != 0)
        fit, *_ = np.linalg.lstsq(design[keep], samples[keep], rcond=None)
        rgb[..., c] -= sum(k * t for k, t in zip(fit, full))
    # Colour balance: the average star is white. Stars are the pixels far
    # above the sky in every channel.
    grey = rgb.mean(axis=2)
    # The grain and the stars are judged against the sky they sit on. With a
    # surface taken off that is zero; with a level only, the object's own
    # glow is still there, and is taken off here for the judging alone.
    glow = ndimage.gaussian_filter(grey, 8) if background == 0 else 0.0
    spread = 1.4826 * np.median(np.abs(grey - glow))
    stars = (grey - glow > 15 * spread) & (grey < 0.5 * grey.max())
    if stars.sum() > 200:
        balance = rgb[stars].mean(axis=0)
        if background == 0:
            # Each colour's own glow under the stars, not the average of the
            # three: before balancing, green is much the strongest, and
            # taking the average off left the galaxy and the sky magenta.
            balance = balance - np.array([ndimage.gaussian_filter(rgb[..., c], 8)[stars].mean()
                                          for c in range(3)])
        rgb *= balance.mean() / balance
    if background == 0:
        # With the colours scaled, what was left of the sky is no longer the
        # same in each: make the darkest tenth of the picture grey again.
        small = ndimage.median_filter(rgb[::64, ::64], (3, 3, 1)).reshape(-1, 3)
        level = small.mean(axis=1)
        dark = small[(level != 0) & (level <= np.percentile(level[level != 0], 10))] if (level != 0).any() else small
        rgb -= dark.mean(axis=0) - dark.mean()
    grey = rgb.mean(axis=2)
    glow = ndimage.gaussian_filter(grey, 8) if background == 0 else 0.0
    rgb /= 1.4826 * np.median(np.abs(grey - glow))   # in units of the sky noise

    # Smooth brightness a little and colour a lot.
    brightness = rgb.mean(axis=2)
    tint = rgb - brightness[..., None]
    brightness = ndimage.gaussian_filter(brightness, detail)
    tint = ndimage.gaussian_filter(tint, (colour, colour, 0))
    rgb = brightness[..., None] + tint

    # Sky just above black; stretch so faint glow shows without lifting grain.
    softness = 1.0 / np.sqrt(1 + detail ** 2 * 12)   # noise left after smoothing
    black, white = -2.0 * softness, np.percentile(brightness, 99.995)
    scaled = np.clip((rgb - black) / (white - black), 0, 1)
    if stretch is None:
        stretch = auto_stretch((FAINT - black) / (white - black))
    out = np.arcsinh(stretch * scaled) / np.arcsinh(stretch)
    # A little more colour, pushed out from each pixel's own grey level.
    grey = out.mean(axis=2, keepdims=True)
    out = grey + saturation * (out - grey)
    return (255 * np.clip(out, 0, 1)).astype(np.uint8)


def sky_for(name):
    """How much of a surface to fit to the sky behind a named object: 0, a
    level only, for one whose shorter side would fill most of the camera's
    view, and 2, a gentle bowl, for the rest and for a name not known."""
    try:
        import sky
        wanted = str(name).replace(" ", "").lower()
        target = next(t for t in sky.load_targets()
                      if wanted in (t["id"].replace(" ", "").lower(), t["alt_id"].replace(" ", "").lower()))
        across = min(target.get("size") or 0, target.get("minor") or target.get("size") or 0)
        return 0 if across >= FILLS * config.field_height() * 60 else 2
    except Exception:      # no catalogue, no settings, no such object
        return 2


def point_of(name):
    """(ra, dec, label) for a target that is one star among many, so that its
    picture needs it pointed out: a bright star, a watched star such as
    Tabby's, an exoplanet's host or a followed transient. None for a galaxy,
    nebula, cluster, planet or mosaic panel, which is plain to see, and for a
    name not known."""
    import interface
    import mount
    import starwatch
    try:
        target = mount.find_target(name)
    except interface.Refusal:      # no such object
        return None
    if target.get("name") not in ("star", "transient") and target.get("kind") != "double star":
        return None
    watched = next((s for s in starwatch.STARS.values() if s["name"].lower() == str(name).lower()), None)
    if watched:
        return watched["ra"], watched["dec"], f"{watched['aka'].split(',')[0]} ({watched['id']})"
    other = target.get("alt_id") or ""
    return target["ra"], target["dec"], f"{target['id']} ({other})" if other else target["id"]


def label(image, x, y, text):
    """The picture with the star at pixel (x, y) marked by two ticks, left of
    it and below it, that leave its light untouched, and named beside them."""
    image = image.copy()
    draw = ImageDraw.Draw(image)
    unit = max(image.size) / 100        # about 26 pixels on the camera's full frame
    gap, length, width = 1.0 * unit, 2.2 * unit, max(2, round(unit / 8))
    colour, edge = (255, 214, 120), (0, 0, 0)
    draw.line([(x - gap - length, y), (x - gap, y)], fill=colour, width=width)
    draw.line([(x, y + gap), (x, y + gap + length)], fill=colour, width=width)
    font = ImageFont.load_default(size=round(1.7 * unit))
    box = draw.textbbox((0, 0), text, font=font)
    w, h = box[2] - box[0], box[3] - box[1]
    # Up and to the right of the star, unless that runs off the picture.
    tx = x + gap if x + gap + w < image.width - unit else x - gap - w
    ty = y - gap - h if y - gap - h > unit else y + gap
    draw.text((tx - box[0], ty - box[1]), text, font=font, fill=colour,
              stroke_width=max(1, width // 2), stroke_fill=edge)
    return image


def mark(image, rgb, name, say=print):
    """The finished picture of a single star with that star labelled, found
    by plate solving the stack (rows, columns, colours) it was made from.
    Any other picture comes back as it was, and so does one whose stack
    will not solve or whose star is outside it."""
    point = point_of(name)
    if point is None:
        return image
    import depth
    import interface
    ra, dec, text = point
    try:
        wcs = depth.plate(np.asarray(rgb, dtype=np.float32).sum(axis=-1), name)
    except interface.Refusal:
        say(f"the stack would not plate-solve, so {text} is not labelled")
        return image
    x, y = (float(v) for v in wcs.world_to_pixel_values(ra, dec))
    if not (0 <= x < image.width and 0 <= y < image.height):
        say(f"{text} is outside the picture, so it is not labelled")
        return image
    say(f"labelled {text} at pixel ({x:.0f}, {y:.0f})")
    return label(image, x, y, text)


FILLS = 0.6          # of the view's height: an object wider than this leaves no sky to fit
FAINT = 6.0          # a glow this many times the sky's grain above the sky...
FAINT_SHOWN = 0.22   # ...is shown at this share of full brightness


def auto_stretch(faint, shown=FAINT_SHOWN, lowest=10.0, highest=3000.0):
    """How hard to stretch so that a faint glow comes out clearly visible,
    whatever the brightest thing in the frame is. `faint` is the glow's level
    as a share of the white point. Found by halving the range."""
    curve = lambda k: np.arcsinh(k * faint) / np.arcsinh(k)
    if curve(lowest) >= shown:
        return lowest
    if curve(highest) <= shown:
        return highest
    for _ in range(40):
        middle = (lowest * highest) ** 0.5
        lowest, highest = (middle, highest) if curve(middle) < shown else (lowest, middle)
    return lowest


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("name", help="object name, as given to shoot.py")
    ap.add_argument("--crop", type=int, metavar="WIDTH",
                    help="also save a close-up this many pixels wide")
    ap.add_argument("--detail", type=float, default=0.8,
                    help="brightness smoothing in pixels; more is smoother and softer")
    ap.add_argument("--saturation", type=float, default=1.25, help="colour strength; 1 is as shot")
    ap.add_argument("--stretch", type=float,
                    help="how hard faint parts are brightened (default: chosen from the "
                         "picture so faint glow shows); about 25 is gentle, 500 is hard")
    args = ap.parse_args()

    name = stacking.folder_name(args.name)
    # Newest stack for this object: a restacked session's final.fits if there
    # is one, else shoot.py's own running stack.
    stacks = sorted(list((config.DATA / "frames").glob(f"{name}-*.fits"))
                    + list((config.DATA / "frames" / name).glob("*/final.fits"))
                    + list((config.DATA / "frames" / name).glob("*/live.fits")),
                    key=lambda p: p.stat().st_mtime)
    if not stacks:
        raise SystemExit(f"No stack for {name} in frames/. Run ./shoot.py {name} first.")
    data = fits.getdata(stacks[-1])
    image = Image.fromarray(process(np.moveaxis(data, 0, 2), args.detail,
                                    colour=6 * args.detail + 1, stretch=args.stretch,
                                    saturation=args.saturation))
    out = config.DATA / "web" / f"{name}-processed.jpg"
    image.save(out, quality=93)
    print(f"{stacks[-1].relative_to(ROOT)} -> {out}")
    if args.crop:
        # shoot.py lines every frame up on the first, which was taken just
        # after centring, so the object is in the middle.
        x, y = image.width // 2, image.height // 2
        w, h = args.crop, args.crop * 2 // 3
        close = image.crop((x - w // 2, y - h // 2, x + w // 2, y + h // 2))
        close = close.resize((1350, 900), Image.LANCZOS)
        close.save(config.DATA / "web" / f"{name}-processed-closeup.jpg", quality=93)
        print(f"close-up -> web/{name}-processed-closeup.jpg")


if __name__ == "__main__":
    main()
