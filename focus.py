#!/usr/bin/env python3
"""Focusing aid: take quick frames, measure the brightest star, show it big.

    ./focus.py                 on a bright star: smaller "star size" is sharper
    ./focus.py --scene         on rooftops or trees: bigger "sharpness" is sharper

Runs for 15 minutes (Ctrl+C to stop sooner). After each frame the laptop says
"better", "worse" or "same" compared with the frame before, and the web page
shows the picture. Turn the focuser a little, then wait for the next verdict.
"""
import argparse
import subprocess
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

from camera import WHITE, Camera, luminance

ROOT = Path(__file__).parent
PREVIEW = ROOT / "web" / "latest.jpg"
CROP = 300          # half-width in pixels of the box shown around the star
MIN_EXPOSURE, MAX_EXPOSURE = 0.001, 2.0


def measure(lum):
    """(x, y, diameter in pixels) of the brightest star, or None. Works for a
    sharp star and for the wide, faint ring of a badly defocused one."""
    # Average 4x4 blocks and smooth, so a faint ring adds up to a clear blob.
    rows, cols = lum.shape[0] // 4 * 4, lum.shape[1] // 4 * 4
    small = lum[:rows, :cols].reshape(rows // 4, 4, cols // 4, 4).mean(axis=(1, 3))
    small = ndimage.median_filter(small, 3)
    small = small - ndimage.uniform_filter(small, 100)  # take out the sky gradient
    smooth = ndimage.gaussian_filter(small, 4)
    noise = 1.4826 * float(np.median(np.abs(smooth - np.median(smooth))))
    peak = float(smooth.max())
    if peak < 6 * max(noise, 1e-6):
        return None
    y, x = np.unravel_index(np.argmax(smooth), smooth.shape)
    # Size from the light around that spot only, so noise elsewhere in the
    # frame cannot join in: twice the average distance of the light from its
    # centre. For a ring that is its diameter; it shrinks steadily to focus.
    reach = 70
    for _ in range(2):  # second pass re-centres on the ring's middle
        y0, x0 = max(int(y) - reach, 0), max(int(x) - reach, 0)
        box = np.clip(smooth[y0:y0 + 2 * reach, x0:x0 + 2 * reach] - 0.3 * peak, 0, None)
        by, bx = ndimage.center_of_mass(box)
        y, x = y0 + by, x0 + bx
    yy, xx = np.indices(box.shape)
    diameter = 4.0 * 2 * float((box * np.hypot(yy - by, xx - bx)).sum() / box.sum())
    cy, cx = 4 * y + 2, 4 * x + 2
    if diameter <= 40:
        # Nearly in focus: measure finely on the full-size pixels instead,
        # as the diameter holding half the star's light.
        y0, x0 = int(max(cy - 24, 0)), int(max(cx - 24, 0))
        box = lum[y0:y0 + 48, x0:x0 + 48] - np.median(lum[y0:y0 + 48, x0:x0 + 48])
        box = np.clip(box, 0, None)
        if box.sum() > 0:
            by, bx = ndimage.center_of_mass(box)
            yy, xx = np.indices(box.shape)
            diameter = 2 * float((box * np.hypot(yy - by, xx - bx)).sum() / box.sum())
    return cx, cy, float(diameter)


def sharpness(lum):
    """Edge strength relative to brightness; peaks at best focus."""
    gx, gy = np.diff(lum, axis=1), np.diff(lum, axis=0)
    return 1e4 * float((gx ** 2).mean() + (gy ** 2).mean()) / max(float(lum.mean()) ** 2, 1.0)


def say(words):
    """Speak through the laptop's speaker without holding up the next frame."""
    subprocess.Popen(["spd-say", "-r", "20", words],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def annotate(image, text, colour=(255, 220, 90)):
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=30)
    draw.rectangle([0, 0, image.width, 60], fill=(0, 0, 0))
    draw.text((10, 12), text, fill=colour, font=font)
    return image


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--minutes", type=float, default=15)
    ap.add_argument("--scene", action="store_true",
                    help="focus on a daytime view instead of a star")
    ap.add_argument("--exposure", type=float, default=0.05, help="starting exposure, seconds")
    ap.add_argument("--gain", type=int, default=300)
    ap.add_argument("--quiet", action="store_true", help="no speech from the laptop")
    ap.add_argument("--port", type=int, default=7624)
    args = ap.parse_args()

    cam = Camera(args.port, args.gain)

    exposure, best = args.exposure, None
    frame, previous = 0, None
    end = time.monotonic() + args.minutes * 60
    try:
        while time.monotonic() < end:
            mosaic, _ = cam.frame(exposure)
            lum = luminance(mosaic)
            # Brightness on a 0-255 scale, whatever the sensor's bit depth.
            level = 255 / (4 * WHITE)
            # Brightest 4x4 block, so a single hot pixel does not count.
            rows, cols = lum.shape[0] // 4 * 4, lum.shape[1] // 4 * 4
            blocks = lum[:rows, :cols].reshape(rows // 4, 4, cols // 4, 4).mean(axis=(1, 3))
            top = float(blocks.max()) * level
            found = None if args.scene else measure(lum)
            # Stretch between the darkest and brightest parts of the frame.
            low, high = np.percentile(lum[::4, ::4], (1, 99.7))
            shown = np.clip((lum - low) / max(high - low, 1e-6), 0, 1) * 255
            if args.scene:
                value = sharpness(lum)
                best = value if best is None else max(best, value)
                image = Image.fromarray(shown.astype(np.uint8)).convert("RGB")
                image = image.resize((900, round(900 * image.height / image.width)))
                text = f"sharpness {value:.1f}   best {best:.1f}"
                if lum.mean() * level < 30 and exposure >= MAX_EXPOSURE:
                    text = "too dark to see anything"
                # Judge exposure on the whole view, not its brightest point.
                top = float(np.percentile(lum, 99)) * level * 1.6
            elif found:
                x, y, diameter = found
                best = diameter if best is None else min(best, diameter)
                x0, y0 = int(max(x - CROP, 0)), int(max(y - CROP, 0))
                view = shown[y0:y0 + 2 * CROP, x0:x0 + 2 * CROP]
                image = Image.fromarray(view.astype(np.uint8)).convert("RGB")
                image = image.resize((900, round(900 * image.height / image.width)))
                text = f"star size {diameter:.1f}   best {best:.1f}"
            else:
                image = Image.fromarray(shown.astype(np.uint8)).convert("RGB")
                image = image.resize((900, round(900 * image.height / image.width)))
                text = "no star in view"
            # Say how this frame compares with the last one, on the picture
            # and out loud.
            frame += 1
            score = value if args.scene else (-found[2] if found else None)
            trend = ""
            if score is not None and previous is not None:
                change = (score - previous) / max(abs(previous), 1e-6)
                if change > 0.04:
                    trend, spoken = "SHARPER", "better"
                elif change < -0.04:
                    trend, spoken = "SOFTER", "worse"
                else:
                    trend, spoken = "same", "same"
                if not args.quiet:
                    # In star mode the size itself is worth hearing.
                    say(spoken if args.scene else f"{spoken}, {-score:.0f}")
            elif score is None and not args.quiet:
                say("no star")
            previous = score
            text = f"#{frame} {time.strftime('%H:%M:%S')}  {text}  {trend}"
            annotate(image, text).save(PREVIEW, quality=85)
            print(f"{time.strftime('%H:%M:%S')}  {text}   (exposure {exposure:g}s, peak {top:.0f})",
                  flush=True)
            # Keep the star bright but not burnt out.
            if top >= 250:
                exposure = max(MIN_EXPOSURE, exposure / 2)
            elif top < 40:
                exposure = min(MAX_EXPOSURE, exposure * 2)
    except KeyboardInterrupt:
        pass
    finally:
        cam.close()


if __name__ == "__main__":
    main()
