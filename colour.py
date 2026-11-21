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
Each filter is stretched on its own and kept unrounded until the picture is
saved; a stack not calibrated makes a picture called a preview.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from astropy.io import fits
from PIL import Image

import config
import interface
import process
import stacking

COLOURS = ("R", "G", "B")
# palette: (the filter in red, in green, in blue), the filter lined up on,
# the filter giving the detail (None: the colour's own brightness)
PALETTES = {"LRGB": (COLOURS, "L", "L"),
            "SHO": (("SII", "Ha", "OIII"), "Ha", None),
            "HOO": (("Ha", "OIII", "OIII"), "Ha", None)}


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
    stars = stacking.find_stars(np.nan_to_num(image))
    moved, info = stacking.register(image[..., None], np.nan_to_num(image), stars, reference)
    if not fits_well(info):
        turned = np.ascontiguousarray(image[::-1, ::-1])
        clean = np.nan_to_num(turned)
        again, second = stacking.register(turned[..., None], clean, stacking.find_stars(clean), reference)
        if fits_well(second) or (not fits_well(info) and second["matched"] > info["matched"]):
            return again[..., 0], second, True
    return moved[..., 0], info, False


MIN_COVERED = 0.75   # share of the frame every filter must cover for the target to be in the picture
GREEN_KEPT = 0.25    # of the green above the red and blue's average, in the Hubble palette
OIII_SHARE = 0.8     # OIII fills two channels in HOO: at full strength the stars come out cyan


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


def combine(stacks, saturation=1.25, say=print, min_covered=MIN_COVERED, palette="LRGB", background=2):
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
    valid = np.all([np.isfinite(i) for i in images.values()], axis=0)
    rgb = np.stack([np.where(valid, images[b], 0) for b in channels], axis=2)
    if palette == "LRGB":
        colour = process.process(rgb, saturation=saturation, background=background, whole=False)
    else:
        colour = narrowband(rgb, channels, saturation, background)
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
            share = colour.shape[0] * colour.shape[1] / valid.size
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
    return np.clip(colour, 0, 255).astype(np.uint8), used


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("name", help="the object, as given to shoot.py")
    ap.add_argument("--night", metavar="YYYYMMDD", help="only sessions begun that date")
    ap.add_argument("--saturation", type=float, default=1.25, help="colour strength; 1 is as shot")
    ap.add_argument("--palette", choices=sorted(PALETTES), default="LRGB",
                    help="LRGB (default), SHO (SII red, Ha green, OIII blue) or HOO (Ha red, OIII green and blue)")
    ap.add_argument("--any-coverage", action="store_true",
                    help="make the picture even when the filters share under 75%% of the frame")
    ap.add_argument("--json", action="store_true", help="answer in JSON at the end")
    args = ap.parse_args()
    return interface.main("colour", lambda: run(args), args.json)


def run(args):
    # At least a tilt: a level alone left NGC 2174's sky teal on one side and red on
    # the other (21 November 2026), and a flat plane cannot take a nebula away.
    stacks = sessions(args.name, args.night, say=print)
    print("stacks: " + (", ".join(f"{b} {p.parent.name}" for b, p in sorted(stacks.items())) or "none"))
    picture, used = combine(stacks, args.saturation, min_covered=0.0 if args.any_coverage else MIN_COVERED,
                            palette=args.palette, background=max(process.sky_for(args.name), 1))
    suffix = "colour" if args.palette == "LRGB" else args.palette
    out = config.DATA / "web" / f"{stacking.folder_name(args.name)}-{suffix}.jpg"
    out.parent.mkdir(exist_ok=True)
    Image.fromarray(picture).save(out, quality=93)
    print(f"saved {out}")
    result = {"name": args.name, "palette": args.palette, "picture": str(out), "filters": used}
    (out.with_suffix(".json")).write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


if __name__ == "__main__":
    main()
