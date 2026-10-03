#!/usr/bin/env python3
"""Focusing aid you can use without looking at a screen.

    ./focus.py                 on stars: it speaks as you turn the focuser
    ./focus.py --tones         a rising pitch instead of speech
    ./focus.py --scene         on rooftops or trees, in daylight

On stars it measures many at once and reports their half-flux radius (HFR):
the radius holding half of a star's light, in pixels. Smaller is sharper;
about 2 is good focus on this telescope. It says things like "Improving.
4.8", "No change", "Worse. Go back", and, once the numbers turn round,
"Minimum passed. Reverse slightly". Readings are steadied over three frames
and small changes are ignored, so it does not chase the air's shimmering.

With the star badly out of focus it falls back to measuring the one big ring.
Runs for 15 minutes (Ctrl+C to stop sooner); the web page shows the picture.
"""
import argparse
import json
import subprocess
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

import interface
import snap
import stacking
from camera import PORT, WHITE, Camera, luminance

ROOT = Path(__file__).parent
PREVIEW = ROOT / "web" / "latest.jpg"
# The newest reading, kept so the status tools can say how good focus was.
FOCUS_FILE = ROOT / "cache" / "focus.json"
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


def half_flux_radius(lum, x, y, reach):
    """Radius in pixels holding half of one star's light, or None if the star
    is too close to the edge."""
    x0, y0 = int(round(x)), int(round(y))
    if not (reach <= x0 < lum.shape[1] - reach and reach <= y0 < lum.shape[0] - reach):
        return None
    box = lum[y0 - reach:y0 + reach + 1, x0 - reach:x0 + reach + 1].astype(np.float32)
    yy, xx = np.indices(box.shape)
    distance = np.hypot(yy - (y - y0 + reach), xx - (x - x0 + reach))
    # The sky's level is taken from the rim of the box.
    box = box - np.median(box[distance > reach - 2])
    inside = distance <= reach - 2
    order = np.argsort(distance[inside])
    light = np.cumsum(np.clip(box[inside][order], 0, None))
    if light[-1] <= 0:
        return None
    return float(distance[inside][order][np.searchsorted(light, light[-1] / 2)])


def measure_stars(lum, most=40):
    """(median half-flux radius, number of stars used) over the field's best
    stars, leaving out burnt-out ones; (None, 0) with fewer than three."""
    stars = stacking.find_stars(lum, limit=120)
    radii = []
    for x, y, _, fwhm, _ in stars:
        if lum[int(y), int(x)] >= 0.9 * 4 * WHITE:   # burnt out: its shape lies
            continue
        radius = half_flux_radius(lum, x, y, reach=int(np.clip(3 * fwhm, 8, 40)))
        if radius:
            radii.append(radius)
        if len(radii) >= most:
            break
    if len(radii) < 3:
        return None, len(radii)
    return float(np.median(radii)), len(radii)


class FocusTracker:
    """Turns a stream of focus readings into what to tell the person at the
    focuser. Readings are steadied over the last three, and a change only
    counts if it beats both a percentage and the readings' own scatter."""

    def __init__(self, percent=4.0):
        self.percent = percent
        self.raw, self.steady = [], None   # steady: last value announced as a change
        self.best = None
        self.falling = 0                   # improvements in a row
        self.passed = False                # gone through the minimum and out the far side

    def scatter(self):
        """How much single readings jitter with nothing being changed. Taken
        from how far each reading sits from the line between its neighbours,
        so a steady rise or fall while the focuser is turned does not count."""
        if len(self.raw) < 5:
            return 0.0
        recent = np.array(self.raw[-11:])
        bends = np.abs(recent[:-2] - 2 * recent[1:-1] + recent[2:])
        return 1.4826 * float(np.median(bends)) / np.sqrt(6)

    def feed(self, value):
        """Take a new reading; return the words to say."""
        self.raw.append(value)
        now = float(np.median(self.raw[-3:]))
        if len(self.raw) <= 3:
            # Settle on a starting value before judging any change.
            self.steady = self.best = now
            return f"{now:.1f}"
        threshold = max(self.percent / 100 * self.steady, 3 * self.scatter())
        if now < self.steady - threshold:
            self.steady, self.falling = now, self.falling + 1
            if now <= self.best:
                self.best = now
                if self.passed:
                    self.passed = False
                    return f"Best focus. {now:.1f}. Hold."
                return f"Improving. {now:.1f}. Best."
            if self.passed and now <= self.best + threshold:
                self.passed = False
                return f"Best focus. {now:.1f}. Hold."
            return f"Improving. {now:.1f}."
        if now > self.steady + threshold:
            came_down = self.falling >= 2
            self.steady, self.falling = now, 0
            if came_down and not self.passed and now > self.best + threshold:
                self.passed = True
                return f"Minimum passed. Reverse slightly. Best was {self.best:.1f}."
            return f"Worse. {now:.1f}. Go back."
        return "No change."


def tone(value, worst, floor=1.5):
    """A short tone whose pitch rises as focus improves: 300 Hz at the first
    reading, 1200 Hz at a perfect star."""
    span = max(worst - floor, 1e-6)
    pitch = 300 + 900 * float(np.clip((worst - value) / span, 0, 1))
    subprocess.Popen(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-f", "lavfi",
                      "-i", f"sine=frequency={pitch:.0f}:duration=0.25"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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
    ap.add_argument("--tones", action="store_true",
                    help="a tone that rises in pitch as focus improves, instead of speech")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--frames", type=int, help="stop after this many frames")
    ap.add_argument("--json", action="store_true", help="the last reading as JSON at the end")
    args = ap.parse_args()
    return interface.main("focus", lambda: run(args), args.json)


def run(args):
    """The focusing loop. Returns the last reading."""
    cam = Camera(args.port, args.gain)
    reading = {}

    exposure, best = args.exposure, None
    frame, previous = 0, None
    tracker, first = FocusTracker(), None
    end = time.monotonic() + args.minutes * 60
    try:
        while time.monotonic() < end and not (args.frames and frame >= args.frames):
            mosaic, _ = cam.frame(exposure)
            lum = luminance(mosaic)
            # Brightness on a 0-255 scale, whatever the sensor's bit depth.
            level = 255 / (4 * WHITE)
            # Brightest 4x4 block, so a single hot pixel does not count.
            rows, cols = lum.shape[0] // 4 * 4, lum.shape[1] // 4 * 4
            blocks = lum[:rows, :cols].reshape(rows // 4, 4, cols // 4, 4).mean(axis=(1, 3))
            top = float(blocks.max()) * level
            # Stretch between the darkest and brightest parts of the frame.
            low, high = np.percentile(lum[::4, ::4], (1, 99.7))
            shown = np.clip((lum - low) / max(high - low, 1e-6), 0, 1) * 255
            frame += 1
            words = None
            if args.scene:
                value = sharpness(lum)
                best = value if best is None else max(best, value)
                picture = shown
                text = f"sharpness {value:.1f}   best {best:.1f}"
                if lum.mean() * level < 30 and exposure >= MAX_EXPOSURE:
                    text = "too dark to see anything"
                # Judge exposure on the whole view, not its brightest point.
                top = float(np.percentile(lum, 99)) * level * 1.6
                if previous is not None:
                    change = (value - previous) / max(abs(previous), 1e-6)
                    words = "better" if change > 0.04 else "worse" if change < -0.04 else "same"
                    text += f"  {words.upper() if words != 'same' else words}"
                previous = value
            else:
                value, count = measure_stars(lum)
                ring = None if value else measure(lum)
                picture = shown
                if value:
                    text = f"HFR {value:.1f}   {count} stars"
                    # Show the middle of the frame, where stars are big
                    # enough to see on a phone.
                    h, w = shown.shape[0] // 2, shown.shape[1] // 2
                    picture = shown[h - CROP:h + CROP, w - CROP:w + CROP]
                    # Many stars are wanted, so let the few brightest burn
                    # out: set the exposure by about the 30th brightest spot.
                    top = float(np.partition(blocks.ravel(), -30)[-30]) * level * 2
                elif ring:
                    # Too far out for separate stars: one big ring. Its radius
                    # stands in for the HFR until stars appear.
                    x, y, diameter = ring
                    value = diameter / 2
                    x0, y0 = int(max(x - CROP, 0)), int(max(y - CROP, 0))
                    picture = shown[y0:y0 + 2 * CROP, x0:x0 + 2 * CROP]
                    text = f"ring radius {value:.0f}   (far from focus)"
                else:
                    text = "no star in view"
                    words = "no star"
                if value:
                    first = first or value
                    words = tracker.feed(value)
                    text += f"   best {tracker.best:.1f}   {words.split('.')[0]}"
                    if not ring:
                        reading = {"hfr": round(value, 2), "stars": count,
                                   "best_hfr": round(tracker.best, 2), "advice": words,
                                   "exposure_s": exposure, "saved": time.time()}
                        FOCUS_FILE.parent.mkdir(exist_ok=True)
                        FOCUS_FILE.write_text(json.dumps(reading))
            image = Image.fromarray(picture.astype(np.uint8)).convert("RGB")
            image = image.resize((900, round(900 * image.height / image.width)))
            text = f"#{frame} {time.strftime('%H:%M:%S')}  {text}"
            annotate(image, text).save(PREVIEW, quality=85)
            snap.label("focus view", f"{exposure:g} s", PREVIEW.parent)
            if words and not args.quiet:
                if args.tones and not args.scene and value:
                    tone(value, first)
                else:
                    say(words)
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
    if not reading:
        if args.scene:
            return {"sharpness": best, "frames": frame}
        raise interface.Refusal("NO_STARS", "No stars were measured.")
    return dict(reading, frames=frame)


if __name__ == "__main__":
    main()
