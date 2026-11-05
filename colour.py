#!/usr/bin/env python3
"""One colour picture from a mono camera's stacks in L, R, G and B.

    ./colour.py "NGC 281"              the newest stack in each filter -> web/NGC281-colour.jpg
    ./colour.py "NGC 281" --night 20261104      only that night's sessions
    ./colour.py "NGC 281" --saturation 1.6      stronger colour

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
"""
import argparse
import json

import numpy as np
from astropy.io import fits
from PIL import Image

import config
import interface
import process
import stacking

COLOURS = ("R", "G", "B")


def sessions(name, night=None):
    """{filter: the deepest stack} for this object: each session's own, and
    restack.py's combinations of several (combined-FILTER), the one with the
    most exposure winning. 5 November 2026: the newest won, so a 28-frame
    restart of M33 in L would have stood in for the 126-frame stack."""
    folder = config.DATA / "frames" / stacking.folder_name(name)
    found = {}
    for session in sorted(p for p in folder.glob("*") if p.is_dir()):
        combined = session.name.startswith("combined-")
        if not (combined or session.name[:8].isdigit()):
            continue
        if night and not combined and not session.name.startswith(night):
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
        depth = float(fits.getheader(stack).get("EXPTIME") or 0)
        if depth >= found.get(str(band), (0.0, None))[0]:
            found[str(band)] = (depth, stack)
    return {band: stack for band, (_, stack) in found.items()}


def brightness(path):
    """A stack as one brightness image (a mono stack keeps three equal planes)."""
    data = fits.getdata(path).astype(np.float32)
    return data.mean(axis=0) if data.ndim == 3 else data


def lined_up(image, reference):
    """`image` moved onto `reference` (a dict of its "square" and "stars")."""
    stars = stacking.find_stars(np.nan_to_num(image))
    moved, info = stacking.register(image[..., None], np.nan_to_num(image), stars, reference)
    return moved[..., 0], info


MIN_COVERED = 0.75   # share of the frame every filter must cover for the target to be in the picture


def combine(stacks, saturation=1.25, say=print, min_covered=MIN_COVERED):
    """The colour picture (8-bit RGB array) and what went into it."""
    have = [b for b in ("L",) + COLOURS if b in stacks]
    if not all(b in stacks for b in COLOURS):
        missing = ", ".join(b for b in COLOURS if b not in stacks)
        raise interface.Refusal("NO_SESSION", f"No stack in {missing}: a colour picture needs R, G and B "
                                f"(have {', '.join(have) or 'none'}).")
    base = "L" if "L" in stacks else "R"
    images = {b: brightness(stacks[b]) for b in have}
    rows = min(i.shape[0] for i in images.values())
    cols = min(i.shape[1] for i in images.values())
    images = {b: i[:rows, :cols] for b, i in images.items()}
    ref_image = np.nan_to_num(images[base])
    reference = {"square": stacking.centre_square(ref_image), "stars": stacking.find_stars(ref_image)}
    used = {base: {"stack": str(stacks[base]), "matched": None}}
    for band in have:
        if band == base:
            continue
        images[band], info = lined_up(images[band], reference)
        used[band] = {"stack": str(stacks[band]), "matched": info["matched"],
                      "residual_px": None if info["residual"] is None else round(float(info["residual"]), 2),
                      "shift_px": [round(v, 1) for v in info["shift"]]}
        say(f"  {band} lined up on {base}: {info['matched']} stars matched, shift "
            f"{info['shift'][0]:+.1f}, {info['shift'][1]:+.1f} px")
        if not stacking.lined_up(info["matched"]):
            raise interface.Refusal("NO_STARS", f"The {band} stack matched only {info['matched']} stars of the "
                                    f"{base} stack (at least {stacking.LINED_UP} are needed): "
                                    "the colours would not line up.")
    valid = np.all([np.isfinite(i) for i in images.values()], axis=0)
    rgb = np.stack([np.where(valid, images[b], 0) for b in COLOURS], axis=2)
    colour = process.process(rgb, saturation=saturation).astype(np.float32)
    if "L" in images:
        grey = np.where(valid, images["L"], 0)
        detail = process.process(np.repeat(grey[..., None], 3, axis=2), saturation=1.0)[..., 0].astype(np.float32)
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
    ap.add_argument("--any-coverage", action="store_true",
                    help="make the picture even when the filters share under 75%% of the frame")
    ap.add_argument("--json", action="store_true", help="answer in JSON at the end")
    args = ap.parse_args()
    return interface.main("colour", lambda: run(args), args.json)


def run(args):
    stacks = sessions(args.name, args.night)
    print("stacks: " + (", ".join(f"{b} {p.parent.name}" for b, p in sorted(stacks.items())) or "none"))
    picture, used = combine(stacks, args.saturation, min_covered=0.0 if args.any_coverage else MIN_COVERED)
    out = config.DATA / "web" / f"{stacking.folder_name(args.name)}-colour.jpg"
    out.parent.mkdir(exist_ok=True)
    Image.fromarray(picture).save(out, quality=93)
    print(f"saved {out}")
    result = {"name": args.name, "picture": str(out), "filters": used}
    (out.with_suffix(".json")).write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


if __name__ == "__main__":
    main()
