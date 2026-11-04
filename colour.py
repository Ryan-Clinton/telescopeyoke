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
R, G and B, there is no colour and it says so. Nothing is moved or exposed.
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
    """{filter: newest stack path} for this object, from each session's own
    raw frames' FILTER (the stack's header may not carry it)."""
    folder = config.DATA / "frames" / stacking.folder_name(name)
    found = {}
    for session in sorted(p for p in folder.glob("*") if p.is_dir() and p.name[:8].isdigit()):
        if night and not session.name.startswith(night):
            continue
        stack = next((session / f for f in ("final.fits", "live.fits") if (session / f).exists()), None)
        light = next(iter(sorted(session.glob("light-*.fits"))), None)
        if stack is None or light is None:
            continue
        band = stacking.load_light(light)[1].get("FILTER")   # in the compressed image's header, not the primary
        if band:
            found[str(band)] = stack      # sorted by time: the newest of each filter wins
    return found


def brightness(path):
    """A stack as one brightness image (a mono stack keeps three equal planes)."""
    data = fits.getdata(path).astype(np.float32)
    return data.mean(axis=0) if data.ndim == 3 else data


def lined_up(image, reference):
    """`image` moved onto `reference` (a dict of its "square" and "stars")."""
    stars = stacking.find_stars(np.nan_to_num(image))
    moved, info = stacking.register(image[..., None], np.nan_to_num(image), stars, reference)
    return moved[..., 0], info


def combine(stacks, saturation=1.25, say=print):
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
        if not info["matched"]:
            raise interface.Refusal("NO_STARS", f"The {band} stack matched no stars of the {base} stack: "
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
    return np.clip(colour, 0, 255).astype(np.uint8), used


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("name", help="the object, as given to shoot.py")
    ap.add_argument("--night", metavar="YYYYMMDD", help="only sessions begun that date")
    ap.add_argument("--saturation", type=float, default=1.25, help="colour strength; 1 is as shot")
    ap.add_argument("--json", action="store_true", help="answer in JSON at the end")
    args = ap.parse_args()
    return interface.main("colour", lambda: run(args), args.json)


def run(args):
    stacks = sessions(args.name, args.night)
    print("stacks: " + (", ".join(f"{b} {p.parent.name}" for b, p in sorted(stacks.items())) or "none"))
    picture, used = combine(stacks, args.saturation)
    out = config.DATA / "web" / f"{stacking.folder_name(args.name)}-colour.jpg"
    out.parent.mkdir(exist_ok=True)
    Image.fromarray(picture).save(out, quality=93)
    print(f"saved {out}")
    result = {"name": args.name, "picture": str(out), "filters": used}
    (out.with_suffix(".json")).write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


if __name__ == "__main__":
    main()
