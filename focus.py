#!/usr/bin/env python3
"""Focusing aid you can use without looking at a screen.

    ./focus.py                 on stars: a click and a tone for every frame measured
    ./focus.py --quiet         no sound; the readings are printed and shown
    ./focus.py --report        how quickly the last run answered a turn of the knob, level by level
    ./focus.py --numbers       each reading spoken as a number, in place of the sounds
    ./focus.py --field         first slew to a bright star in a rich part of
                               the sky (this MOVES the telescope)
    ./focus.py --field --dry-run   say which star; nothing moves
    ./focus.py --scene         on rooftops or trees, in daylight
    ./focus.py --check         how sharp the stars are now, against the usual best; nothing turns
    ./focus.py --motor         the motor focuser does it, unless focus is already as good as usual
    ./focus.py --motor --anyway   focus with the motor even so
                               (turns the focuser; the mount stays still)
    ./focus.py --motor --dry-run   whether the focuser is plugged in; nothing turns

Turn the focuser and listen. Each frame, once it has been measured, gives a
click and then a tone: the click says "that turn has been seen", and the
tone is higher the better the focus. Two clicks and no tone is a reading
too uncertain to judge; a low buzz is no star at all. Words are kept for
changes: "Level two", "Level three. Fine focus", "Minimum passed. Reverse
slightly", "Best focus", "Focus good. Hold", "Stars lost".

It works in three levels and moves between them by itself:

    1 coarse   quick binned frames, each judged alone; a star far out of
               focus is measured as the one big ring it makes
    2 stars    quick binned frames, many stars at once, two readings averaged
    3 fine     the full sensor, many stars at once, steadied over three
               readings, changes judged against the air's own shimmering

The size it measures is the half-flux radius (HFR): the radius holding half
of a star's light, in pixels of the full-size picture, whatever the camera
was binned by. Smaller is sharper; about 2 is good focus on a 150P with the
183C. "Focus good" is said only on level 3, after the readings have gone
through their lowest and come back to stay on it.

Runs for 15 minutes (Ctrl+C to stop sooner); the web page shows the picture.
"""
import argparse
import json
import os
import queue
import signal
import sys
import threading
import time
import wave
from pathlib import Path

import activity
import config

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

import host
import interface
import snap
import stacking
from camera import PORT, WHITE, Camera, luminance
from indi import IndiError

ROOT = Path(__file__).parent
PREVIEW = config.DATA / "web" / "latest.jpg"
# The newest reading taken on many stars, kept so the status tools can say
# how good focus was.
FOCUS_FILE = config.DATA / "cache" / "focus.json"
# The newest frame's reading whatever it was (a ring, one star, nothing),
# for the Focus screen; every frame of the last run, with its timing; and
# one line for each run that reached "Focus good".
LIVE_FILE = config.DATA / "cache" / "focus_live.json"
FRAMES_FILE = config.DATA / "cache" / "focus_frames.jsonl"
RUNS_FILE = config.DATA / "cache" / "focus_runs.jsonl"
SOUNDS = config.DATA / "cache" / "sounds"
CROP = 300          # half-width in pixels of the box shown around the star
MIN_EXPOSURE, MAX_EXPOSURE = 0.001, 2.0

LEVELS = {1: "coarse", 2: "stars", 3: "fine"}
SMOOTH = {1: 1, 2: 2, 3: 3}             # readings each level steadies over
PERCENT = {1: 10.0, 2: 6.0, 3: 4.0}     # the smallest change each level calls a change
ENOUGH = 10         # stars in the middle of a full-size frame that make the rest not worth measuring
SURE = 3            # readings in a row that settle a change of level
WALK_MS = 40        # ms a half-step for --walk-in: the slowest and strongest tried on 19 October 2026
HOLD = 5            # readings that must stay on the best before "Focus good"
# Half-flux radius at good focus, in arcseconds: HFR 2 on the 150P with the
# 183C. A starting figure only. Once runs have ended on "Focus good", what
# they reached is used instead (usual_best()).
USUAL_BEST = 2.6


def arcsec_per_pixel():
    """Arcseconds of sky across one pixel of the full-size brightness
    picture, the pixel every HFR here is given in: two of the sensor's."""
    equipment = config.hardware()
    return 2 * 206.265 * equipment["camera"]["pixel_size_um"] / equipment["scope"]["focal_length_mm"]


def last_focused():
    """When focus was last set or measured good, from either way of doing
    it: the hand aid's reading (FOCUS_FILE) or a motor run or check
    (RUNS_FILE). None if never."""
    times = []
    if FOCUS_FILE.exists():
        try:
            times.append(float(json.loads(FOCUS_FILE.read_text(encoding="utf-8")).get("saved", 0)))
        except (ValueError, OSError):
            pass
    if RUNS_FILE.exists():
        for line in RUNS_FILE.read_text(encoding="utf-8").splitlines():
            try:
                times.append(float(json.loads(line)["saved"]))
            except (ValueError, KeyError):
                pass
    return max(times) if times else None


def usual_best():
    """The HFR, in arcseconds, that focusing on this telescope ends at: the
    middle one of the last five runs that reached "Focus good", or the
    starting figure when there has been none."""
    reached = []
    if RUNS_FILE.exists():
        for line in RUNS_FILE.read_text(encoding="utf-8").splitlines():
            try:
                reached.append(float(json.loads(line)["best_arcsec"]))
            except (ValueError, KeyError, TypeError):
                pass
    return float(np.median(reached[-5:])) if reached else USUAL_BEST


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


# How far a star's light must stand above the grain of the sky to count. With
# the focuser far out there are no stars to find, only specks of grain, and
# they have radii too: on 6 October 2026 forty of them read 2.2 while every
# star was a ring a hundred pixels across. Those specks stood out by 2 at
# most; the faintest stars that measured truly stood out by 8.
STANDS_OUT = 8.0


def measure_stars(lum, most=40):
    """(median half-flux radius, number of stars used) over the field's best
    stars, leaving out burnt-out ones; (None, 0) with fewer than two.

    Only stars within a third of the second brightest count. Out of focus
    the faint ones are rings sunk in the sky's grain, and their radii are
    the grain's: on 6 October 2026 forty of them read 3.2 and wandered while
    the two real stars in the field went from 7 to 11. A hot pixel, which
    has no radius at all, is left out too."""
    stars = stacking.find_stars(lum, limit=120)
    sky = float(np.median(lum))
    grain = 1.4826 * float(np.median(np.abs(lum[::4, ::4] - sky))) or 1.0
    found = []
    for x, y, flux, fwhm, _ in stars:
        if lum[int(y), int(x)] >= 0.9 * 4 * WHITE:   # burnt out: its shape lies
            continue
        reach = int(np.clip(3 * fwhm, 8, 40))
        # A star's light against the grain of the sky it was measured in.
        if flux < STANDS_OUT * grain * np.sqrt(np.pi) * reach:
            continue
        radius = half_flux_radius(lum, x, y, reach=reach)
        if radius and radius >= 0.3:
            found.append((flux, radius))
    if len(found) < 2:
        return None, len(found)
    least = sorted(flux for flux, _ in found)[-2] / 3
    radii = [radius for flux, radius in found if flux >= least][:most]
    return float(np.median(radii)), len(radii)


def middle(lum):
    """The middle of the frame, half its width and height: a quarter of the
    work to measure, and on the full sensor still plenty of stars."""
    h, w = lum.shape
    return lum[h // 4:h - h // 4, w // 4:w - w // 4]


class FocusTracker:
    """Turns a stream of focus readings into what the person at the focuser
    should hear. It holds the level (1 coarse, 2 stars, 3 fine), steadies
    the readings as that level asks, and calls a change a change only if it
    beats both a percentage and the readings' own scatter.

    Sizes are in pixels of the full-size picture. `usual` is the HFR good
    focus comes to on this telescope; level 3 begins at twice it."""

    def __init__(self, usual=2.0):
        self.usual, self.fine = usual, 2 * usual
        self.bests = {}                    # the best steadied reading of each level
        self.unsure = 0                    # readings in a row that could not be judged
        self._enter(1)

    def _enter(self, level, single=False):
        self.level = level
        self.single = single               # level 3 on one star: the field has no more
        self.raw, self.now, self.steady = [], None, None   # steady: the value at the last change
        self.falling = 0                   # improvements in a row
        self.passed = False                # gone through the minimum and out the far side
        self.bracketed = False             # ...at some time on this level, so the best is a real minimum
        self.good = False                  # "Focus good" has been said and still holds
        self.top = None                    # the size the lowest tone stands for
        self.multi = self.near = self.far = 0

    @property
    def best(self):
        return self.bests.get(self.level)

    @property
    def state(self):
        if self.unsure >= SURE:
            return "lost"
        return "good" if self.good else "passed" if self.passed else "seeking"

    def scatter(self):
        """How much single readings jitter with nothing being changed. Taken
        from how far each reading sits from the line between its neighbours,
        so a steady rise or fall while the focuser is turned does not count.
        A focuser turned a little at a time bends that line at every turn,
        so when the usual step from one reading to the next says far less,
        it is believed instead: a turn made now and then does not add to it."""
        if len(self.raw) < 5:
            return 0.0
        recent = np.array(self.raw[-11:])
        bends = float(np.median(np.abs(recent[:-2] - 2 * recent[1:-1] + recent[2:]))) / np.sqrt(6)
        steps = float(np.median(np.abs(np.diff(recent)))) / np.sqrt(2)
        return 1.4826 * (steps if steps < bends / 2 else bends)

    def meter(self):
        """How far along this level the focus is, 0 to 1: what the tone's
        pitch and the screen's bar show. Each level has its own span, fixed
        when the level begins, so the same size always gives the same pitch
        and the ear has the whole range to work with at every stage."""
        if self.now is None:
            return None
        floor = min({1: self.top / 6, 2: self.fine, 3: 0.4 * self.fine}[self.level], 0.6 * self.top)
        return float(np.clip(np.log(self.top / self.now) / np.log(self.top / floor), 0, 1))

    def _threshold(self, around):
        return max(PERCENT[self.level] / 100 * around, 3 * self.scatter())

    def feed(self, value, stars=0):
        """Take a frame's reading: `value` is the size measured (None for
        nothing measurable), `stars` how many it was taken over (0: the one
        brightest star, or its ring). Returns what to do about it:
        {"sound": "tone", "double" or "buzz"; "meter": 0 to 1 for a tone's
        pitch; "say": words, or None; "trend": "settling", "improving",
        "worse", "steady", "uncertain" or "lost"}."""
        out = {"sound": "tone", "meter": None, "say": None, "trend": "steady"}
        wants_stars = self.level == 2 or (self.level == 3 and not self.single)
        if value is None or (wants_stars and not stars):
            # Nothing to judge. Three in a row and the search starts again.
            self.unsure += 1
            out.update(sound="buzz" if value is None else "double",
                       trend="lost" if value is None else "uncertain")
            if self.unsure == SURE:
                out["say"] = "Star lost." if self.level == 1 else "Stars lost. Level one."
                if self.level > 1:
                    self._enter(1)
            return out
        self.unsure = 0
        self.raw.append(value)
        now = self.now = float(np.median(self.raw[-SMOOTH[self.level]:]))
        if self.top is None:
            # Room above the first reading, for a turn made the wrong way.
            self.top = 1.5 * self.fine if self.level == 3 else 1.5 * now
        if len(self.raw) <= SMOOTH[self.level]:
            # Settle on a starting value before judging any change.
            self.steady = now
            self.bests[self.level] = min(now, self.best or now)
            out["trend"] = "settling"
        else:
            threshold = self._threshold(self.steady)
            if now < self.steady - threshold:
                self.steady, self.falling = now, self.falling + 1
                out["trend"] = "improving"
                if self.passed and now <= self.best + threshold:
                    self.passed = False
                    out["say"] = "Best focus."
                self.bests[self.level] = min(now, self.best)
            elif now > self.steady + threshold:
                came_down = self.falling >= 2
                self.steady, self.falling = now, 0
                out["trend"] = "worse"
                if self.good:
                    self.good = False
                    out["say"] = "Worse. Go back."
                if came_down and not self.passed and now > self.best + threshold:
                    self.passed = self.bracketed = True
                    out["say"] = "Minimum passed. Reverse slightly."
            if (self.level == 3 and self.bracketed and not self.good and len(self.raw) >= HOLD
                    and max(self.raw[-HOLD:]) <= self.best + self._threshold(self.best)):
                # Through the minimum, back, and the readings have stayed on it.
                self.good, self.passed, self.falling = True, False, 0
                out["say"] = "Focus good. Hold."
        out["meter"] = self.meter()
        return self._move(stars, out)

    def _move(self, stars, out):
        """Change level when three readings in a row call for it."""
        self.multi = self.multi + 1 if stars else 0
        self.near = self.near + 1 if self.now <= self.fine else 0
        self.far = self.far + 1 if self.now > 1.5 * self.fine else 0
        if self.level < 3 and self.near >= SURE:
            self._enter(3, single=self.multi < SURE)
            out["say"] = "Level three. Fine focus."
        elif self.level == 1 and self.multi >= SURE:
            self._enter(2)
            out["say"] = "Level two."
        elif self.level == 3 and self.far >= SURE:
            self._enter(1 if self.single else 2)
            out["say"] = f"Level {'one' if self.level == 1 else 'two'}."
        return out


# --- sounds ---------------------------------------------------------------------
#
# One short sound for each frame measured, at the same loudness whatever it
# says: loudness that changed with the reading would be heard as a change of
# pitch. The pitch runs from LOW to HIGH in equal musical steps, because the
# ear hears pitch by ratio: a semitone is the same step at 300 Hz as at 1200.

RATE = 22050                       # samples a second
LOW, HIGH, STEPS = 250.0, 1600.0, 32     # hertz; 32 semitones between them


def pitch(fraction):
    """The tone, in hertz, for a meter reading from 0 (poor) to 1 (good)."""
    return LOW * (HIGH / LOW) ** (round(STEPS * float(np.clip(fraction, 0, 1))) / STEPS)


def _click():
    t = np.arange(int(0.006 * RATE)) / RATE
    return np.sin(2 * np.pi * 2500 * t) * np.exp(-t / 0.0012)


def _note(hertz, seconds, square=False):
    t = np.arange(int(seconds * RATE)) / RATE
    wave_ = np.sin(2 * np.pi * hertz * t)
    if square:
        wave_ = np.clip(3 * wave_, -1, 1)
    ramp = np.minimum(1, np.minimum(t, seconds - t) / 0.008)    # no thump at either end
    return wave_ * ramp


def waveform(kind, hertz=None):
    """The samples, -1 to 1, of one of the aid's sounds: "tone" (a click,
    then the pitch), "double" (two clicks) or "buzz"."""
    quiet = lambda seconds: np.zeros(int(seconds * RATE))
    if kind == "tone":
        parts = [_click(), quiet(0.03), _note(hertz, 0.16)]
    elif kind == "double":
        parts = [_click(), quiet(0.09), _click()]
    else:
        parts = [_note(110, 0.25, square=True)]
    return np.concatenate([quiet(0.01)] + parts)


def sound(kind, fraction=None):
    """Play one of the aid's sounds without waiting for it. Each is written
    once as a small WAV file and played from there after that."""
    hertz = pitch(fraction) if kind == "tone" else None
    path = SOUNDS / (f"tone-{hertz:.0f}.wav" if hertz else f"{kind}.wav")
    if not path.exists():
        SOUNDS.mkdir(parents=True, exist_ok=True)
        samples = (0.5 * 32767 * waveform(kind, hertz)).astype("<i2")
        partial = path.with_suffix(".part")
        with wave.open(str(partial), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(RATE)
            out.writeframes(samples.tobytes())
        partial.replace(path)
    return host.play(path)


def sharpness(lum):
    """Edge strength relative to brightness; peaks at best focus."""
    gx, gy = np.diff(lum, axis=1), np.diff(lum, axis=0)
    return 1e4 * float((gx ** 2).mean() + (gy ** 2).mean()) / max(float(lum.mean()) ** 2, 1.0)


def say(words):
    """Speak through the laptop's speaker without holding up the next frame."""
    host.speak(words)


def annotate(image, text, colour=(255, 220, 90)):
    """Write `text` across the top of the picture, the letters made smaller
    until the whole line fits: a reading cut off at the edge is no use."""
    draw = ImageDraw.Draw(image)
    text = " ".join(text.split())
    size = 30
    font = ImageFont.load_default(size=size)
    while size > 12 and draw.textlength(text, font=font) > image.width - 20:
        size -= 2
        font = ImageFont.load_default(size=size)
    draw.rectangle([0, 0, image.width, 60], fill=(0, 0, 0))
    draw.text((10, 30 - size // 2 - 3), text, fill=colour, font=font)
    return image


def keep(path, data):
    """Write a small JSON file whole, so nothing reads half of one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial, text = path.with_suffix(".part"), json.dumps(data)
    partial.write_text(text, encoding="utf-8")
    try:
        partial.replace(path)
    except OSError:
        # Windows, while something has the old one open to read.
        path.write_text(text, encoding="utf-8")
        partial.unlink(missing_ok=True)


def ahead(cam, exposure):
    """Start an exposure on a thread of its own and return where its result
    will be put: (mosaic, binning, when it began, when it landed), or the
    exception that stopped it. The camera is then exposing the next frame
    while this one is measured, sounded and drawn."""
    result = queue.Queue(1)

    def take():
        try:
            began = time.perf_counter()
            mosaic, _ = cam.frame(exposure)
            result.put((mosaic, getattr(cam, "binning", 1), began, time.perf_counter()))
        except BaseException as problem:    # a refusal or SystemExit too: main() must hear of it
            result.put(problem)
    threading.Thread(target=take, daemon=True).start()
    return result


def collect(result):
    """Wait for what ahead() puts there. In short waits, so Ctrl+C is not held up."""
    while True:
        try:
            return result.get(timeout=0.2)
        except queue.Empty:
            pass


# Bright stars with many fainter ones round them, in or beside the Milky Way
# and spread round the sky so that one is always well up: the meter is steady
# on thirty stars and jumps about on four. On 6 October 2026 it was used on
# the field of M31, which has few, and read anything from 5 to 15 with the
# focuser still; beside Vega and Deneb it had held to a tenth or two.
FIELDS = ("Deneb", "Vega", "Altair", "Mirfak", "Capella", "Betelgeuse", "Procyon")
HIGH_ENOUGH = 40.0   # degrees up: lower down the air blurs the stars itself
ROOM = 5.0           # degrees to keep above anything known to be in the way


def field(site, skyline, west=None, placed=None):
    """The best placed of FIELDS to focus on, as (name, plan), or (None, why).
    Highest wins, but a star on the side of the meridian the tube is already
    on (`west`) is taken first if it is high enough, so that the tube need
    not swing over the pole and back. `skyline` is config's [horizon];
    `placed` stands in for mount.plan_goto in the tests."""
    import horizon
    import mount
    placed = placed or mount.plan_goto
    choices = []
    for name in FIELDS:
        try:
            plan = placed(name, site)
        except interface.Refusal as refusal:
            if refusal.code_name == "MOTION_LOCKED":
                raise
            continue
        altitude = plan["altitude_deg"]
        hour_angle, dec = plan["hour_angle_hours"] * 15, plan["dec_deg"]
        if altitude < HIGH_ENOUGH or altitude < horizon.in_the_way(skyline, bearing(hour_angle, dec, site)) + ROOM:
            continue
        same_side = west is not None and (plan["pier_side"] == "west") == west
        choices.append((same_side, altitude, name, plan))
    if not choices:
        return None, "None of the stars it focuses on is well up and clear just now."
    _, _, name, plan = max(choices)
    return name, plan


def bearing(hour_angle, dec, site):
    """Compass bearing in degrees of a place in the sky, from the garden."""
    import polaralign
    return polaralign.to_altaz(polaralign.vector(hour_angle, dec), site["latitude"])[1] % 360


def go_to_field(dry_run=False):
    """Slew to the star field() chooses. Returns its name."""
    import mount
    cfg = config.load()
    site = cfg["site"]
    scope = None if dry_run else mount.Mount()
    west = scope.west() if scope else None
    name, plan = field(site, cfg.get("horizon", {}), west)
    if not name:
        raise interface.Refusal("INVALID_REQUEST", plan)
    note = f"{name}, {plan['altitude_deg']:.0f}° up ({plan['side_note']})"
    if dry_run:
        print(f"Would move the mount: to {note}, to focus on.")
        return name
    print(f"Going to {note} to focus on.", flush=True)
    scope.goto_target(name, site)
    time.sleep(min(mount.SETTLE, 5))
    return name


LIVE = 1.2      # seconds: a turn heard within this, on the quick levels, feels live


def report():
    """How quickly the last focusing run answered a turn of the knob, from
    the timing kept for each of its frames: the middle figure on each level
    for the frame's arrival, its measuring, the two together (`feedback_s`)
    and the time from one sound to the next. Takes no frames."""
    frames = []
    if FRAMES_FILE.exists():
        for line in FRAMES_FILE.read_text(encoding="utf-8").splitlines():
            try:
                frames.append(json.loads(line))
            except ValueError:
                pass
    if not frames:
        raise interface.Refusal("NO_SESSION", "No focusing run has been recorded yet: run ./focus.py first.")
    levels = []
    for level in sorted({f["level"] for f in frames}):
        here = [f for f in frames if f["level"] == level]
        row = {"level": level, "name": LEVELS[level], "frames": len(here),
               "binning": int(np.median([f.get("binning", 1) for f in here]))}
        for key in ("capture_s", "process_s", "feedback_s", "cycle_s"):
            found = [f["timing"][key] for f in here if f.get("timing", {}).get(key) is not None]
            row[key] = round(float(np.median(found)), 3) if found else None
        levels.append(row)
    quick = [row["feedback_s"] for row in levels if row["level"] < 3 and row["feedback_s"] is not None]
    last = frames[-1]
    out = {"frames": len(frames), "levels": levels, "ended": last.get("state"), "ended_on_level": last["level"],
           "best_hfr": last.get("best_hfr"), "saved": last.get("saved"),
           "quick_levels_feel_live": bool(quick and max(quick) <= LIVE) if quick else None}
    print(f"{'level':<10} {'frames':>6} {'binned':>6} {'frame':>7} {'measuring':>9} {'heard after':>11} {'sound to sound':>14}")
    seconds = lambda value: "" if value is None else f"{value:.2f} s"
    for row in levels:
        print(f"{row['level']} {row['name']:<8} {row['frames']:>6} {row['binning']:>5}x {seconds(row['capture_s']):>7} "
              f"{seconds(row['process_s']):>9} {seconds(row['feedback_s']):>11} {seconds(row['cycle_s']):>14}")
    if quick:
        print(f"On the quick levels a turn of the knob was heard within {max(quick):.2f} s"
              + (f", inside the {LIVE:g} s that feels live." if out["quick_levels_feel_live"]
                 else f", over the {LIVE:g} s that feels live."))
    print(f"The run ended on level {last['level']}" + (f", {last['state']}." if last.get("state") else "."))
    return out


# Motor focusing: a measured focus curve, the way the established autofocus
# programs do it. One frame's HFR near focus jumps by half again from seeing
# alone (18 October 2026: 4.9, 10.6, 5.5 over 96 half-steps), so no single
# reading can say which way focus lies. Instead the drawtube is swept through
# focus in equal steps, every point reached moving in so the gears' slack
# never enters a measurement, several frames at each; a curve is fitted to
# the whole sweep and the focuser goes once to the curve's lowest point, the
# last move inward; then that is measured, and kept only if it is better.
# Sizes are HFR in pixels of the full-size picture; positions are motor
# half-steps (4096 to a turn), plus out, counted from where the run started.
MOTOR_EXPOSURE, MOTOR_GAIN = 1.0, 1500
SWEEP_POINTS = 9        # positions in a sweep, the guess in the middle
SWEEP_FRAMES = 3        # frames at each position: their median and scatter
CHECK_FRAMES = 5        # frames to check the fitted focus with
SWEEPS = 4              # sweeps a run may take, moving or widening it, before giving up
STEP = 64               # half-steps between sweep positions until --measure-step has measured it
BACKLASH = 256          # half-steps of slack to overshoot until --measure-backlash has measured it: small
                        # enough that a sweep and its overshoot fit inside the travel ([focuser] travel)
SETTLE_S = 1.0          # seconds after a move before a frame, for the tube to stop shaking
NOISE = 0.4             # a "star" this many times smaller than the usual best is a hot pixel
CEILING = 12.0          # HFR beyond this is the measuring box's size, not the star's
MOTOR_TRAVEL = 8192     # the furthest a run goes from where it started, either way (two turns)
FOCUSER_FILE = config.DATA / "cache" / "focuser.json"
SLOW_FRAME_S = 15       # a frame not come this long after its exposure is said to be late, then every 30 s


class OutOfReach(Exception):
    """A focus run would go further than MOTOR_TRAVEL, or the focuser's
    travel setting, from where it started."""


class StarsLost(Exception):
    """Stars that measured at the start of a run have gone partway through
    it: the focuser has run away from focus (23 October 2026, put down to
    cloud while the drawtube ended about an inch out)."""


TRAVEL_MOST = 8192      # the most [focuser] travel may be, as config.SETTINGS allows


def focuser_travel():
    """How far, in half-steps either way, a run may turn the motor from
    where it started ([focuser] travel)."""
    given = config.hardware().get("focuser", {})
    travel = int(given.get("travel") or config.DEFAULTS["focuser"]["travel"])
    return min(travel, TRAVEL_MOST)     # a hand-edited config.toml is held to the Settings form's limit


def motor_refusal(mode, settings, travel):
    """Why a motor run of `mode` must not start, or None: a sweep needs its
    measured sizes, and all of it, overshoot included, inside the travel."""
    if mode not in ("focus", "sweep"):
        return None
    if not (settings["step_measured"] and settings["backlash_measured"]):
        return ("Refused: the focuser's step and backlash are only guesses until measured (on 23 October 2026 "
                "a sweep on guesses left the drawtube about an inch out). From focus, by ./focus.py --walk-in, "
                "run ./focus.py --measure-step and ./focus.py --measure-backlash first.")
    reach = SWEEP_POINTS // 2 * settings["step"] + settings["backlash"]
    if reach > travel:
        return (f"Refused: a sweep {settings['step']} half-steps apart with {settings['backlash']} of overshoot "
                f"reaches {reach} half-steps from the start, beyond the focuser's travel of "
                f"{travel} ([focuser] travel).")
    return None


# What a focus run is doing, as one small file for the live stream
# (streamlook.focus_stream_state): its stage, every reading with where the
# focuser was, the fit, and how it ended. Before 22 October 2026 a motor run
# left only lines of log, and the stream could show nothing of a focus run.
# The brightest star's square, at the start and now, is kept beside it.
STREAM_FILE = config.DATA / "cache" / "focus_stream.json"
STAR_START = STREAM_FILE.with_name("focus_star_start.png")
STAR_NOW = STREAM_FILE.with_name("focus_star_now.png")
STAGES = {"check": ["measure"],
          "focus": ["measure", "sweep", "fit", "verify"],
          "sweep": ["measure", "sweep", "fit"],
          "walk": ["doughnuts", "coming in", "finest steps", "done"],
          "find": ["searching"]}


def star_square(lum, least=12, most=60):
    """The brightest star (or its doughnut) in a square around it, stretched
    to 8 bits, or None when there is no star."""
    found = measure(lum)
    if found is None:
        return None
    x, y, diameter = found
    half = int(np.clip(0.8 * diameter, least, most))
    x0, y0 = max(int(x) - half, 0), max(int(y) - half, 0)
    box = np.asarray(lum[y0:y0 + 2 * half, x0:x0 + 2 * half], dtype=np.float32)
    if box.size == 0:
        return None
    lo, hi = np.percentile(box, (5, 99.8))
    scaled = np.clip((box - lo) / max(float(hi - lo), 1e-6), 0, 1)
    return Image.fromarray((255 * np.sqrt(scaled)).astype(np.uint8))


class Broadcast:
    """A focus run's STREAM_FILE, kept up to date as it goes. Never raises:
    a stream file not written is not worth a focus run failing over. With
    `path` None nothing is written (a run whose caller keeps no file)."""

    def __init__(self, kind, usual, path="stream", picture=None, clock=time.time):
        self.path = STREAM_FILE if path == "stream" else path       # looked up now, not when defined
        self.picture, self.clock = picture, clock
        now = clock()
        self.state = {"kind": kind, "steps": STAGES.get(kind, []), "stage": STAGES.get(kind, [None])[0],
                      "usual_hfr": round(usual, 2) if usual else None, "start_hfr": None, "hfr": None,
                      "best_hfr": None, "best_at": None, "at": 0, "position": None, "positions": None,
                      "readings": [], "fit": None, "outcome": None, "words": None, "pid": os.getpid(),
                      "started": now, "updated": now, "ended": None}
        self.started_star = False
        self.write()

    def write(self):
        if self.path is None:
            return
        try:
            import records
            self.state["updated"] = self.clock()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            records.write(self.path, self.state, indent=None)
        except Exception:
            pass

    def stage(self, name, position=None, positions=None):
        self.state.update(stage=name, position=position, positions=positions)
        self.write()

    def reading(self, at, hfr, doing=None, ring=None):
        """One measurement: where the focuser was (half-steps from the
        start) and the HFR there (None for none), or the doughnuts' size."""
        s = self.state
        s["at"] = at
        s["readings"] = (s["readings"] + [{"at": at, "hfr": hfr, "doing": doing, "ring": ring and round(ring)}])[-80:]
        if hfr is not None:
            s["hfr"] = hfr
            if s["start_hfr"] is None:
                s["start_hfr"] = hfr
            if s["best_hfr"] is None or hfr < s["best_hfr"]:
                s["best_hfr"], s["best_at"] = hfr, at
        self.star()
        self.write()

    def star(self):
        """The brightest star now, and at the start, as small pictures."""
        if self.path is None or self.picture is None:
            return
        import warnings
        try:
            lum = self.picture()
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)      # a blank frame has no star to find
                square = star_square(lum) if lum is not None else None
            if square is None:
                return
            for path in ([STAR_NOW] if self.started_star else [STAR_START, STAR_NOW]):
                partial = path.with_suffix(".part.png")
                square.save(partial)
                partial.replace(path)
            self.started_star = True
        except Exception:
            pass

    def fitted(self, fit):
        if fit:
            self.state["fit"] = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in fit.items()
                                 if k in ("ok", "focus", "hfr", "r2", "reason")}
        self.write()

    def done(self, outcome, words, **extra):
        """How the run ended: "complete", "left_alone" or "passed" (good as
        it was), "soft" (a check that found it worth focusing), "rejected"
        (no curve fitted), "returned" (the fitted focus was no better), "found"
        or "not_found" (the search for stars), or "failed"."""
        self.state.update(outcome=outcome, words=words, ended=self.clock(), **extra)
        self.write()


def progress(line):
    """One line of a focus run, the time at its front, out at once: a log
    being watched, or read for a progress report, shows it the moment it
    happens, not when the run ends. On 21 October 2026 a run's log stayed
    empty for four minutes while the camera hung, then ended in a traceback."""
    print(f"{time.strftime('%H:%M:%S')} {line}", flush=True)


class Watched:
    """The camera, each frame watched: one still not come SLOW_FRAME_S after
    its exposure is said to be late while it is waited for, and `since` says
    when the frame being waited for was asked for, for when it never comes."""

    def __init__(self, cam, seconds):
        self.cam, self.seconds, self.since = cam, seconds, None

    def waited(self):
        return time.monotonic() - self.since if self.since is not None else 0.0

    def frame(self):
        self.since, done = time.monotonic(), threading.Event()

        def watch():
            wait = self.seconds + SLOW_FRAME_S
            while not done.wait(wait):
                progress(f"no picture from the camera after {self.waited():.0f} s (a frame is "
                         f"{self.seconds:g} s): still waiting")
                wait = 30
        threading.Thread(target=watch, daemon=True).start()
        try:
            got = self.cam.frame(self.seconds)
        finally:
            done.set()
        self.since = None
        return got


def hung(problem, frames, moved=None):
    """A camera that stopped answering, as one plain line that ends the run
    (a refusal, so no traceback): how long it was waited for, how to restart
    it, and, with `moved`, where the focuser was left."""
    if frames is not None and frames.since is not None:
        what = f"the camera sent no picture for {frames.waited():.0f} s: it has hung"
    else:
        what = f"the camera did not answer ({problem})"
    where = ("" if moved is None else " The focuser has not moved." if not moved else
             f" The focuser is where it was: {moved:+d} half-steps from the start.")
    return interface.Refusal("CAMERA_NOT_CONNECTED", f"{time.strftime('%H:%M:%S')} {what}; "
                             f"./camera_setup.py restarts it.{where}")


def focuser_settings():
    """The focuser's measured step and backlash (half-steps), or the
    defaults where they have not been measured."""
    kept = {}
    try:
        kept = json.loads(FOCUSER_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return {"step": int(kept.get("step") or STEP), "backlash": int(kept.get("backlash") or BACKLASH),
            "step_measured": bool(kept.get("step")), "backlash_measured": bool(kept.get("backlash"))}


def keep_focuser(**measured):
    kept = {}
    try:
        kept = json.loads(FOCUSER_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    kept.update(measured, saved=time.time())
    keep(FOCUSER_FILE, kept)


class Drive:
    """The motor, counting where it is from the start of a run and refusing
    to go further than MOTOR_TRAVEL from there."""

    def __init__(self, motor):
        self.motor, self.at = motor, 0

    def to(self, place):
        n = place - self.at
        if abs(place) > MOTOR_TRAVEL:
            raise OutOfReach
        if n:
            self.motor.move(n)
            self.at = place
        return n

    def arrive(self, place, backlash):
        """Go to `place` with the last move inward: out beyond it by the
        slack first when it lies out from here, or when the last move was not
        inward. Returns the moves made."""
        moves = []
        if place >= self.at or not getattr(self, "loaded_in", False):
            moves.append(self.to(place + backlash))
        moves.append(self.to(place))
        self.loaded_in = True
        return moves


def sample(read, frames, usual):
    """The HFRs `read(frames)` gave that are stars: not hot pixels, not the
    measuring box. Their median, their scatter (median absolute deviation)
    and how many there were."""
    values = [v for v in read(frames) if v and NOISE * usual <= v <= CEILING]
    if not values:
        return {"hfr": None, "scatter": None, "frames": 0, "all": []}
    median = float(np.median(values))
    scatter = float(np.median(np.abs(np.array(values) - median))) if len(values) > 1 else None
    return {"hfr": round(median, 2), "scatter": scatter and round(scatter, 2),
            "frames": len(values), "all": [round(v, 2) for v in values]}


def hyperbola(x, a, b, x0, c):
    return a + b * np.sqrt((x - x0) ** 2 + c ** 2)


def fit_curve(points, step):
    """The focus curve through a sweep: a hyperbola, checked against two
    straight wings. Returns {"ok", "focus", "hfr", "r2", "spread", "reason",
    "toward"}: "reason" says why a fit is refused ("too few", "flat",
    "edge", "poor fit", "unstable", "wings disagree"), and with "edge",
    "toward" is +1 or -1, the way the sweep should move."""
    from scipy.optimize import curve_fit
    good = [p for p in points if p["hfr"] is not None]
    out = {"ok": False, "focus": None, "hfr": None, "r2": None, "spread": None, "reason": None, "toward": 0}
    if len(good) < 7:
        out["reason"] = "too few"
        if good:        # the stars that were seen lie that way
            lowest = min(good, key=lambda p: p["hfr"])["at"]
            middle = (points[0]["at"] + points[-1]["at"]) / 2
            out["toward"] = 1 if lowest > middle else -1
        return out
    x = np.array([p["at"] for p in good], float)
    y = np.array([p["hfr"] for p in good], float)
    sigma = np.array([max(p["scatter"] or 0, 0.05 * p["hfr"]) for p in good])
    low, high = x.min(), x.max()
    lowest = x[np.argmin(y)]
    if y.max() < 1.3 * y.min():
        out["reason"] = "flat"
        return out

    def fit(xs, ys, ss):
        guess = [0.5 * ys.min(), (ys.max() - ys.min()) / max(xs.max() - xs.min(), 1) * 2,
                 xs[np.argmin(ys)], step]
        values, _ = curve_fit(hyperbola, xs, ys, p0=guess, sigma=ss, maxfev=20000,
                              bounds=([-np.inf, 0, low - 4 * step, 1], [np.inf, np.inf, high + 4 * step, 50 * step]))
        return values

    try:
        a, b, x0, c = fit(x, y, sigma)
    except (RuntimeError, ValueError):
        out["reason"], out["toward"] = "poor fit", (1 if lowest > (low + high) / 2 else -1)
        return out
    model = hyperbola(x, a, b, x0, c)
    r2 = 1 - float(np.sum((y - model) ** 2)) / max(float(np.sum((y - y.mean()) ** 2)), 1e-9)
    out.update(focus=float(x0), hfr=round(float(hyperbola(x0, a, b, x0, c)), 2), r2=round(r2, 3))
    margin = 0.15 * (high - low)
    if not low + margin <= x0 <= high - margin or (x < x0).sum() < 3 or (x > x0).sum() < 3:
        out["reason"], out["toward"] = "edge", (1 if x0 > (low + high) / 2 else -1)
        return out
    if r2 < 0.8:
        out["reason"] = "poor fit"
        return out
    # Leave each point out in turn: a focus that moves with one point is not known.
    others = []
    for i in range(len(x)):
        keep_ = np.arange(len(x)) != i
        try:
            others.append(fit(x[keep_], y[keep_], sigma[keep_])[2])
        except (RuntimeError, ValueError):
            pass
    spread = float(np.std(others)) if others else float("inf")
    out["spread"] = round(spread, 1)
    if spread > 0.5 * step:
        out["reason"] = "unstable"
        return out
    # Two straight wings, split at the fitted focus, should cross near it.
    left, right = x < x0, x > x0
    if left.sum() >= 2 and right.sum() >= 2:
        l1, l0 = np.polyfit(x[left], y[left], 1)
        r1, r0 = np.polyfit(x[right], y[right], 1)
        if l1 < 0 < r1 and abs((r0 - l0) / (l1 - r1) - x0) > step:
            out["reason"] = "wings disagree"
            return out
    out["ok"] = True
    return out


def curve_picture(points, fitted=None, width=40):
    """The sweep as text: one row a position, a bar as long as its HFR."""
    good = [p["hfr"] for p in points if p["hfr"] is not None]
    if not good:
        return []
    top = max(good)
    rows = []
    for p in points:
        bar = "" if p["hfr"] is None else "#" * max(1, round(width * p["hfr"] / top))
        mark = "  <- fitted focus near here" if fitted is not None and abs(p["at"] - fitted) < 0.5 * abs(
            points[1]["at"] - points[0]["at"]) else ""
        size = "none" if p["hfr"] is None else f"{p['hfr']:5.2f}"
        rows.append(f"    {p['at']:+6d}  {size}  {bar}{mark}")
    return rows


def motor_focus(motor, read, usual, say=progress, step=None, backlash=None, sweep_only=False, live=None):
    """Bring the stars to focus with the motor by a measured focus curve.
    `motor.move(n)` turns it (plus is out); `read(frames)` gives that many
    frames' HFRs (None for a frame with no stars). `usual` is the HFR good
    focus usually comes to: it says only whether focusing is needed, never
    where focus is. Returns {"hfr", "moved", "found", "readings", "fit",
    "start_hfr"}; with "found" false the focuser is back where it started.
    With `sweep_only`, one sweep is measured and fitted and the focuser
    goes back to the start, the last move inward. `live` (a Broadcast) is
    told each stage and reading, for the stream."""
    settings = focuser_settings()
    step, backlash = step or settings["step"], backlash or settings["backlash"]
    drive, readings = Drive(motor), []
    half = SWEEP_POINTS // 2
    live = live or Broadcast("sweep" if sweep_only else "focus", usual, path=None)

    def point(doing, frames, n=0):
        found = sample(read, frames, usual)
        found.update(at=drive.at, doing=doing)
        readings.append(found)
        live.reading(drive.at, found["hfr"], doing)
        spread = f" ±{found['scatter']:.2f}" if found["scatter"] is not None else ""
        size = "none" if found["hfr"] is None else f"{found['hfr']:.2f}"
        say(f"  #{len(readings):<3} {doing:<15} step {n:+5d}  at {drive.at:+6d}  "
            f"HFR {size}{spread}  ({found['frames']}/{frames} frames)")
        # A sweep's ends may be too blurred to measure; no stars back near
        # the start, where they measured, is the drawtube having run away.
        if (doing == "sweep" and found["hfr"] is None and readings[0]["hfr"] is not None
                and abs(drive.at) <= step):
            raise StarsLost
        return found

    live.stage("measure")
    start = point("start", SWEEP_FRAMES)
    fitted, centre, tries = None, 0, 0
    try:
        for sweep in range(SWEEPS):
            tries += 1
            say(f"  sweep {sweep + 1}: {SWEEP_POINTS} positions {step} half-steps apart around {centre:+d}, "
                f"{SWEEP_FRAMES} frames each, every one reached moving in")
            live.stage("sweep", 1, SWEEP_POINTS)
            drive.arrive(centre + half * step, backlash)
            points = [point("sweep", SWEEP_FRAMES)]
            for k in range(SWEEP_POINTS - 1):
                live.stage("sweep", k + 2, SWEEP_POINTS)
                n = drive.to(drive.at - step)
                points.append(point("sweep", SWEEP_FRAMES, n))
            live.stage("fit")
            with activity.doing("Fitting the focus curve"):
                fitted = fit_curve(points, step)
            live.fitted(fitted)
            for row in curve_picture(points, fitted["focus"] if fitted["ok"] else None):
                say(row)
            if fitted["ok"]:
                say(f"  fit: focus at {fitted['focus']:+.0f}, HFR {fitted['hfr']:.2f} there, R² {fitted['r2']:.2f}, "
                    f"±{fitted['spread']:.0f} half-steps")
                break
            say(f"  fit refused: {fitted['reason']}")
            if fitted["reason"] == "flat":
                step *= 2               # the sweep did not reach the wings: wider
            elif fitted["toward"]:
                centre += fitted["toward"] * half * step    # the low end of the curve is that way
            else:
                fitted = None
                break
            fitted = None
    except OutOfReach:
        say("  the next move would go beyond the focuser's travel from the start")
        fitted = None
    except StarsLost:
        say(f"  the stars measured at the start and are gone at {drive.at:+d}: the focuser has run away "
            "from focus, not cloud. Stopped: back to the start")
        drive.arrive(0, backlash)
        point("back to start", 1)
        live.done("returned", "The stars went partway through the sweep, so the focuser stopped and went back "
                              "to where it started.")
        return {"readings": readings, "fit": None, "start_hfr": start["hfr"], "sweeps": tries, "step": step,
                "backlash": backlash, "hfr": None, "moved": 0, "found": False, "stars_lost": True}
    result = {"readings": readings, "fit": fitted, "start_hfr": start["hfr"], "sweeps": tries,
              "step": step, "backlash": backlash}
    if sweep_only or not fitted:
        if not sweep_only:
            say("  no focus curve found: back to the start")
        drive.arrive(0, backlash)
        point("back to start", 1)
        if sweep_only:
            live.done("swept", f"Focus curve fitted: best focus at HFR {fitted['hfr']:.2f}; the focuser went back "
                               "to where it started." if fitted else
                               "No focus curve could be fitted; the focuser went back to where it started.")
        else:
            live.done("rejected", "No focus curve could be fitted to the sweep, so the focuser went back to where "
                                  "it started.")
        return dict(result, hfr=None, moved=0, found=False)
    target = round(fitted["focus"])
    moves = drive.arrive(target, backlash)
    live.stage("verify")
    with activity.doing("Checking the fitted focus"):
        check = point("to focus", CHECK_FRAMES, moves[-1])
    # Within what seeing alone scatters a median of a few frames by.
    allow = (check["scatter"] or 0) + (start["scatter"] or 0)
    better = check["hfr"] is not None and (start["hfr"] is None or check["hfr"] <= 1.05 * start["hfr"] + allow)
    near_fit = check["hfr"] is not None and check["hfr"] <= 1.2 * fitted["hfr"] + allow
    if better and near_fit:
        live.done("complete", None, end_hfr=check["hfr"])
        return dict(result, hfr=check["hfr"], moved=target, found=True)
    say(f"  checked: HFR {check['hfr']} at the fitted focus is not better than the start "
        f"({start['hfr']}) or is far from the fit's {fitted['hfr']}: back to the start")
    drive.arrive(0, backlash)
    point("back to start", 1)
    live.done("returned", f"At the fitted focus the stars measured {check['hfr']} against {start['hfr']} at the "
                          "start: no better, so the focuser went back to where it started.")
    return dict(result, hfr=None, moved=0, found=False)


def find_stars(motor, read, usual, say=progress, stride=2048, turns=2, ring=None, live=None):
    """Far out of focus, where no star measures: half a turn at a time in,
    then out, a check after each, until stars measure (HFR under CEILING),
    so a sweep has something to fit. 18 October 2026: after the focuser was
    refitted, stars were found again 1.5 turns in. Leaves the focuser where
    they showed, or back at the start. Returns that place, or None.

    `ring(frames)` gives the size of the defocused stars' doughnuts, which
    no HFR can measure but which shrink steadily towards focus: a way they
    grow on is the wrong way, and is left at once for the other (19 October
    2026: a search went a turn and a half in while the doughnuts did not
    shrink)."""
    drive = Drive(motor)
    reach = turns * 4096 // stride
    live = live or Broadcast("find", usual, path=None)
    live.stage("searching")
    start = ring(SWEEP_FRAMES) if ring else None
    live.reading(0, None, "start", ring=start)
    for way in (-1, 1):
        before = start
        for k in range(1, reach + 1):
            live.stage("searching", k, reach)
            drive.to(way * k * stride)
            found = sample(read, SWEEP_FRAMES, usual)
            size = ring(SWEEP_FRAMES) if ring and found["hfr"] is None else None
            live.reading(drive.at, found["hfr"], "in" if way < 0 else "out", ring=size)
            say(f"  {'in' if way < 0 else 'out'} {k * stride:5d}: HFR {found['hfr'] or 'none'}"
                + (f", doughnuts {size:.0f} px" if size else ""))
            if found["hfr"] is not None:
                live.done("found", f"Stars measure again {abs(drive.at)} half-steps "
                                   f"{'in' if drive.at < 0 else 'out'} from the start.")
                return drive.at
            if size and before and size > 1.05 * before:
                say(f"  the doughnuts grew from {before:.0f} to {size:.0f} px: focus is the other way")
                break
            before = size or before
        drive.to(0)
    live.done("not_found", "No stars measured within two turns either way: the focuser went back to where it "
                           "started.")
    return None


def walk_in(motor, read, usual, say=progress, coarse=64, fine=32, finest=16, closest=8, switch=8.0, near=1.5,
            close=1.15, most=160, tries=3, patience=3, spike=1.8, ring=None, ring_step=128, ring_most=4096,
            live=None, back_out=True, slack=None):
    """Focus from a little outside it, moving only inward, a few half-steps
    at a time, measuring after each, until the stars have been worse three times
    running after their best; returns {"best_hfr", "best_at", "ended_at",
    "ended_hfr", "readings"}. Where the motor can push the drawtube in but
    not lift it out (19 October 2026, the camera's weight on the drawtube),
    a person sets it a little out by hand and this brings it in: then it
    reached HFR 1.58 in 32-step moves. Moves of `coarse` while the HFR is
    over `switch`, `fine` below. A reading that comes back empty is taken
    again, up to `tries` times; then it stops where it is, since a jump
    there once overshot focus. Within `near` x the usual best it moves
    `finest` at a time, and it ends `patience` moves past the best, at most
    `patience` x `finest` inside it. A reading over `spike` x the best is
    taken again before it counts: on 21 October 2026 one passing cloud read
    6.3 between 2.92 and 2.55, and two moves past the best ended a run that
    still had finer focus to find.

    With `back_out`, a run that ended past its best then tries the one small
    move back out to the best, and says whether the motor lifted the
    drawtube: 24 October 2026, it ended 24 half-steps inside the best (2.55
    against 2.16), and the person asked for that move to be tried rather
    than assumed impossible. The result gains "back_out": {"steps", "hfr",
    "lifted"}, and "ended_at" and "ended_hfr" are where it then is. The move
    back goes out past the best by the gears' `slack` (the measured
    backlash, or BACKLASH) and then in to it, so the slack is taken up both
    ways and the drawtube is left resting on the gears' inward side: a move
    of only the 24 to 48 half-steps it had gone past was lost in the slack
    before the drawtube could rise. On 30 October 2026 the motor lifted the
    drawtube with the camera on over half a turn, so it is worth trying."""
    def reading():
        for _ in range(tries):
            hfr = sample(read, SWEEP_FRAMES, usual)["hfr"]
            if hfr is not None:
                return hfr
        return None
    live = live or Broadcast("walk", usual, path=None)
    now = reading()
    at = 0
    if now is None and ring:
        # Doughnuts, too wide for an HFR (21 October 2026, set "a touch out"
        # by hand): in `ring_step` at a time while they shrink, until the
        # stars measure. Doughnuts that grow mean focus is not inward.
        live.stage("doughnuts")
        size = ring(SWEEP_FRAMES)
        live.reading(at, None, "doughnuts", ring=size)
        if size is not None:
            say(f"  start: doughnuts {size:.0f} px; in {ring_step} at a time until the stars measure")
        grew = 0
        while size is not None and now is None and at > -ring_most:
            motor.move(-ring_step)
            at -= ring_step
            now = reading()
            if now is None:
                was, size = size, ring(SWEEP_FRAMES)
                live.reading(at, None, "doughnuts", ring=size)
                say(f"  in {ring_step} (at {at:+d}): doughnuts {size if size is None else round(size)} px")
                grew = grew + 1 if size is not None and size > was else 0
                if grew >= 2:
                    live.done("failed", "The doughnuts grew as the focuser went in: focus is the other way.")
                    raise interface.Refusal("NO_STARS", f"The doughnuts grew as it went in ({at:+d} half-steps "
                                                        "from the start): focus is outward. Set the drawtube a "
                                                        "little out of focus by hand and run this again.")
    if now is None:
        live.done("failed", "No stars measured here, so the focus walk could not start.")
        raise interface.Refusal("NO_STARS", "No stars measure here. Set the drawtube a little out of focus by "
                                            "hand, where the stars still measure, and run this again.")
    best, best_at, worse, readings = now, at, 0, [(at, now)]
    live.stage("coming in")
    live.reading(at, now, "start")
    say(f"  start: HFR {now}")
    for _ in range(most):
        # Sized by the best so far, not the last reading: on 21 October 2026
        # one bad reading past the best went back to 32-step moves and
        # ended 80 half-steps inside focus.
        step = (closest if best < close * usual else finest if best < near * usual
                else fine if best < switch else coarse)
        if step in (finest, closest) and live.state["stage"] != "finest steps":
            live.stage("finest steps")
        motor.move(-step)
        at -= step
        now = reading()
        if now is not None and now > spike * best and best < switch:
            say(f"  in {step} (at {at:+d}): HFR {now}, a cloud? measuring again")
            now = reading()
        say(f"  in {step} (at {at:+d}): HFR {now if now is not None else 'none'}")
        if now is None:
            say("  no reading after three tries: stopped here")
            break
        readings.append((at, now))
        live.reading(at, now, "in")
        if now < best:
            best, best_at, worse = now, at, 0
        else:
            worse += 1
            if worse >= patience:
                break
    result = {"best_hfr": best, "best_at": best_at, "ended_at": at, "ended_hfr": now, "readings": readings}
    if back_out and now is not None and at < best_at:
        steps = best_at - at
        slack = focuser_settings()["backlash"] if slack is None else slack
        live.stage("lifting back")
        say(f"  out {steps + slack} past the best, then in {slack} to it, to take up the gears' slack")
        motor.move(steps + slack)
        if slack:
            motor.move(-slack)
        back = reading()
        lifted = back is not None and back < 0.9 * now
        say(f"  back out {steps} to the best: HFR {back if back is not None else 'none'} "
            f"({'it lifted' if lifted else 'no better: the motor did not lift it'})")
        result["back_out"] = {"steps": steps, "hfr": back, "lifted": lifted}
        if back is not None:
            readings.append((best_at, back))
            result.update(ended_at=best_at if lifted else at, ended_hfr=back)
    live.stage("done")
    live.done("complete", None, end_hfr=result["ended_hfr"] if result["ended_hfr"] is not None else best)
    return result


def measure_step(motor, read, usual, say=progress, backlash=None, increment=64, most=4096):
    """From focus, in by `increment` at a time until the stars are 2.5 times
    the size they were: a sweep step is a quarter of that distance, so the
    ends of a nine-position sweep reach well up the curve's sides. Then back
    to the start, the last move inward. Returns the step, or None."""
    backlash = backlash or focuser_settings()["backlash"]
    drive = Drive(motor)
    drive.arrive(0, backlash)
    first = sample(read, SWEEP_FRAMES, usual)["hfr"]
    say(f"  at focus: HFR {first}")
    distance, found = 0, None
    while first and distance < most:
        drive.to(drive.at - increment)
        distance += increment
        now = sample(read, SWEEP_FRAMES, usual)["hfr"]
        say(f"  in {distance:5d}: HFR {now}")
        if now is None or now >= 2.5 * first:
            found = max(32, round(distance / 4))
            break
    drive.arrive(0, backlash)
    return found


def dead_band(offsets, sizes):
    """How far a reversal turned before the stars began to change: the best
    `d` for a curve flat up to `d` and a straight line after it."""
    x, y = np.array(offsets, float), np.array(sizes, float)
    best = (float("inf"), None)
    for d in x[:-2]:
        after = x >= d
        flat = float(np.mean(y[~after])) if (~after).any() else y[0]
        if after.sum() >= 2:
            slope, _ = np.polyfit(x[after], y[after], 1)
            model = np.where(after, flat + slope * (x - d), flat)
            error = float(np.sum((y - model) ** 2))
            if error < best[0]:
                best = (error, float(d))
    return best[1]


def measure_backlash(motor, read, usual, step, say=progress, increment=64, most=3072, repeats=2):
    """The gears' slack, measured on the steep side of the curve where a
    small move changes the stars: in by four sweep steps, then out by
    `increment` at a time; the turning done before the stars begin to change
    is the slack. Twice, and half as much again as the larger kept, as the
    established programs advise: too much costs only time. Start at focus,
    as a focus run leaves it. Returns it, or None."""
    drive, found = Drive(motor), []
    drive.loaded_in = True      # a focus run ends with an inward move, so start from focus
    for time_ in range(repeats):
        drive.arrive(-4 * step, most)
        offsets, sizes = [0], [sample(read, SWEEP_FRAMES, usual)["hfr"]]
        for k in range(1, most // increment + 1):
            drive.to(-4 * step + k * increment)
            offsets.append(k * increment)
            sizes.append(sample(read, SWEEP_FRAMES, usual)["hfr"])
        pairs = [(o, s) for o, s in zip(offsets, sizes) if s is not None]
        if pairs:       # only up to the sharpest: beyond it the stars grow again
            pairs = pairs[:min(range(len(pairs)), key=lambda i: pairs[i][1]) + 1]
        d = dead_band(*zip(*pairs)) if len(pairs) >= 5 else None
        say(f"  reversal {time_ + 1}: the stars began to change after {d if d is None else round(d)} half-steps")
        if d is not None:
            found.append(d)
    drive.arrive(0, most)
    return round(1.5 * max(found)) if found else None


GOOD_ENOUGH = 1.1    # within this of the usual best, focus is left as it is


def verdict(hfr, usual):
    """What a reading says about focus, against the usual best."""
    if hfr is None:
        return "no stars measured: cloud, the cap, or far out of focus"
    if hfr <= GOOD_ENOUGH * usual:
        return f"good: HFR {hfr:.2f}, against {usual:.2f} usually"
    return f"soft: HFR {hfr:.2f}, against {usual:.2f} usually ({hfr / usual:.1f} times): worth focusing"


def seen_good(hfr, scale):
    """Note that focus was measured good just now, without being changed,
    so the patrol's readiness counts it. Kept apart from the runs' best, so
    it does not move what usual_best() says good focus is."""
    try:
        RUNS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with RUNS_FILE.open("a", encoding="utf-8") as log:
            log.write(json.dumps({"saved": time.time(), "checked_hfr": round(hfr, 2),
                                  "checked_arcsec": round(hfr * scale, 2)}) + "\n")
    except OSError:     # a note lost is not worth a check failing over
        pass


def show(lum, line):
    """The frame a focus reading was measured on as web/latest.jpg, the
    status page's NOW picture, and the reading as the caption above it: a
    line of text written across a 900-pixel picture is cut off or too small
    to read on the page."""
    from camera import stretch
    try:
        image = Image.fromarray(stretch(lum)).convert("RGB")
        image = image.resize((900, round(900 * image.height / image.width)))
        PREVIEW.parent.mkdir(parents=True, exist_ok=True)
        image.save(PREVIEW, quality=85)
        snap.label("focus", f"{time.strftime('%H:%M:%S')} {' '.join(line.split())}", PREVIEW.parent)
    except OSError:     # a picture not shown is not worth a focus run failing over
        pass


@activity.during("Checking focus")
def run_check(args):
    """./focus.py --check: three frames of the stars in view, their size
    against the usual best. Nothing turns."""
    scale = arcsec_per_pixel()
    usual = usual_best() / scale
    frames = None
    seen = {}
    live = Broadcast("check", usual, picture=lambda: seen.get("lum"))
    progress(f"opening the camera (INDI port {args.port})")
    try:
        with Camera(args.port, MOTOR_GAIN) as cam:
            frames = Watched(cam, MOTOR_EXPOSURE)
            progress(f"camera open; checking focus: 3 frames of {MOTOR_EXPOSURE:g} s after one thrown away")
            frames.frame()                          # the first frame after opening can be stale
            values = []
            for n in range(3):
                live.stage("measure", n + 1, 3)
                lum = seen["lum"] = luminance(frames.frame()[0])
                value = measure_stars(lum)[0]
                live.reading(0, value and round(value, 2), "check")
                line = f"focus check {n + 1}/3: HFR {'none' if value is None else f'{value:.2f}'}"
                progress(line)
                show(lum, line)
                if value:
                    values.append(value)
    except IndiError as problem:
        live.done("failed", "The camera stopped sending pictures, so the focus check could not finish.")
        raise hung(problem, frames) from None
    except BaseException:
        live.done("failed", "The focus check stopped before it finished.")
        raise
    hfr = float(np.median(values)) if values else None
    good = hfr is not None and hfr <= GOOD_ENOUGH * usual
    progress(f"Focus now: {verdict(hfr, usual)}.")
    if hfr is None:
        live.done("failed", "No stars measured: cloud, the cap, or far out of focus.")
    else:
        live.done("passed" if good else "soft", None, end_hfr=round(hfr, 2))
    if good:
        seen_good(hfr, scale)
    return {"hfr": hfr and round(hfr, 2), "hfr_arcsec": hfr and round(hfr * scale, 2),
            "usual_hfr": round(usual, 2), "good": good}


class Settled:
    """The motor, waiting SETTLE_S after each move before anything is
    measured, so a frame is not of a tube still shaking. With `travel`, a
    move that would end further than that from where the run started is
    refused before the motor turns."""

    def __init__(self, motor, wait=time.sleep, travel=None):
        self.motor, self.wait, self.moved, self.travel = motor, wait, 0, travel

    def move(self, n):
        if self.travel is not None and abs(self.moved + n) > self.travel:
            raise OutOfReach(self.moved + n)
        try:
            self.motor.move(n)
        except KeyboardInterrupt:
            self.moved += n     # focuser.Focuser.move lets a move ordered finish before it stops
            raise
        self.moved += n         # where it is from the start, for a run cut short
        self.wait(SETTLE_S)

    def home(self, backlash):
        """Back to where the run started, the last move inward: the slack
        overshot outward first when it lies out from here, within the travel."""
        over = min(backlash, self.travel) if self.travel is not None else backlash
        if self.moved < 0 and over:
            self.move(-self.moved + over)
        if self.moved:
            self.move(-self.moved)


def stop_on_term():
    """Until the function returned is called, SIGTERM stops the run as
    Ctrl-C does, so a run stopped in the background still tidies up."""
    if threading.current_thread() is not threading.main_thread():
        return lambda: None

    def interrupt(signum, frame):
        raise KeyboardInterrupt
    before = signal.signal(signal.SIGTERM, interrupt)
    return lambda: signal.signal(signal.SIGTERM, before)


MODE_WORDS = {"focus": "to the sharpest", "walk": "walking in to the sharpest", "find": "finding focus",
              "sweep": "one focus sweep", "step": "measuring the motor's step",
              "backlash": "measuring the backlash"}


@activity.during("Focusing with the motor", lambda a: MODE_WORDS.get(a["mode"], a["mode"]))
def run_motor(args, mode="focus"):
    """./focus.py --motor: focus with the motor by a measured focus curve,
    on the stars in view now; first a reading, and if focus is already as
    good as usual it is left alone (--anyway to focus regardless).
    `mode` "sweep" measures and fits one sweep and goes back to the start;
    "step" and "backlash" measure the focuser and keep what they find."""
    import focuser
    scale = arcsec_per_pixel()
    usual = usual_best() / scale
    settings, travel = focuser_settings(), focuser_travel()
    refused = motor_refusal(mode, settings, travel)
    if refused:
        raise interface.Refusal("INVALID_REQUEST", refused)
    if args.dry_run and mode == "walk":
        port = focuser.find_port()
        print(f"Would turn the focuser on {port} inward only, 64, 32 then 16 half-steps at a time at {WALK_MS} ms a "
              f"half-step, {SWEEP_FRAMES} frames after each, until the stars have been worse three times after their "
              "best, then back out past the best by the gears' slack and in to it. Start it a little outside focus, "
              "where the stars still measure. The mount does not move.")
        return {"would_move": True, "port": port, "usual_hfr": round(usual, 2), "walk_ms": WALK_MS}
    if args.dry_run:
        port = focuser.find_port()
        print(f"Would turn the focuser on {port}: {SWEEP_POINTS} positions {settings['step']} half-steps apart "
              f"through focus, every one reached moving in after {settings['backlash']} half-steps out for the "
              f"gears' slack, {SWEEP_FRAMES} frames each; then a curve fitted and one move, inward, to its "
              f"lowest point, checked with {CHECK_FRAMES} frames. The mount does not move.")
        return {"would_move": True, "port": port, "usual_hfr": round(usual, 2), **settings}
    # Every stage says so as it starts, so a log is never empty while the
    # run waits on the focuser or the camera.
    progress("opening the focuser")
    motor = focuser.Focuser.open()
    stopped = stop_on_term()
    progress(f"focuser open on {getattr(getattr(motor, 'link', None), 'port', None) or 'its port'}; "
             f"opening the camera (INDI port {args.port})")
    frames = drive = None
    seen = {}
    # For the live stream: what this run is doing, stage by stage. The
    # focuser's own measurements (step, backlash) are not shown.
    live = Broadcast(mode, usual, path=STREAM_FILE if mode in STAGES else None, picture=lambda: seen.get("lum"))
    try:
        with Camera(args.port, MOTOR_GAIN) as cam:
            frames = Watched(cam, MOTOR_EXPOSURE)
            progress(f"camera open; one frame of {MOTOR_EXPOSURE:g} s thrown away (the first can be stale)")
            frames.frame()

            def read(count):
                values = []
                for _ in range(count):
                    mosaic, _ = frames.frame()
                    seen["lum"] = luminance(mosaic)
                    values.append(measure_stars(seen["lum"])[0])
                return values

            def ring(count):
                """The doughnuts' size, median over `count` frames, from the
                brightest star's ring (measure())."""
                sizes = []
                for _ in range(count):
                    mosaic, _ = frames.frame()
                    seen["lum"] = luminance(mosaic)
                    found = measure(seen["lum"])
                    if found:
                        sizes.append(found[2])
                        seen.setdefault("doughnut", seen["lum"])    # for the collimation check
                return float(np.median(sizes)) if sizes else None

            def say(line):
                progress(line)
                if "lum" in seen:
                    show(seen["lum"], "focus: " + line)
            drive = Settled(motor, travel=travel)
            if mode == "walk":
                if hasattr(motor, "speed"):
                    motor.speed(WALK_MS)
                progress(f"walking in at {WALK_MS} ms a half-step, {SWEEP_FRAMES} frames of "
                         f"{MOTOR_EXPOSURE:g} s after each move")
                result = walk_in(drive, read, usual, say=say, ring=ring, live=live)
                if "doughnut" in seen:
                    # The doughnuts it started from show the collimation for free
                    # (collimation.py; 24 October 2026).
                    import collimation
                    checked = collimation.check(seen["doughnut"])
                    progress(collimation.words(checked))
                    if checked:
                        collimation.keep(checked, "walk-in")
                        result["collimation"] = checked
                progress(f"Best HFR {result['best_hfr']} at {result['best_at']:+d} half-steps; ended at "
                         f"{result['ended_at']:+d}, HFR {result['ended_hfr']}.")
                # Where it ended, if that is good, counts as focused for the
                # patrol's readiness (21 October 2026: it said "last focused
                # 52 hours ago" straight after a walk-in to HFR 2.31).
                last = result["readings"][-1][1]
                if last <= 1.5 * usual:
                    seen_good(last, scale)
                return result
            if mode == "find":
                progress("looking for stars: half a turn at a time, in and then out")
                found = find_stars(drive, read, usual, say=say, ring=ring, live=live)
                progress(f"Stars measure {found:+d} half-steps from the start." if found is not None else
                         "No stars within two turns either way: the focuser is back where it started.")
                return {"found_at": found}
            if mode == "step":
                progress("measuring the sweep step, out from focus")
                found = measure_step(drive, read, usual, say=say, most=travel)
                if found:
                    keep_focuser(step=found)
                progress(f"Sweep step: {found} half-steps" + (", kept." if found else ": not measured."))
                return {"step": found}
            if mode == "backlash":
                progress("measuring the gears' slack")
                # Out no further than the travel, the return's overshoot too.
                found = measure_backlash(drive, read, usual, settings["step"], say=say,
                                         most=min(3072, travel - travel % 64))
                if found:
                    keep_focuser(backlash=found)
                progress(f"Backlash to overshoot: {found} half-steps" + (", kept." if found else ": not measured."))
                return {"backlash": found}
            progress(f"measuring the start: {SWEEP_FRAMES} frames of {MOTOR_EXPOSURE:g} s")
            live.stage("measure")
            now = sample(read, SWEEP_FRAMES, usual)["hfr"]
            live.reading(0, now, "start")
            progress(f"Focus now: {verdict(now, usual)}.")
            if (mode == "focus" and now is not None and now <= GOOD_ENOUGH * usual
                    and not getattr(args, "anyway", False)):
                progress("Left as it is: it is already as good as focusing usually gets (--anyway to focus "
                         "regardless).")
                live.done("left_alone", None, end_hfr=round(now, 2))
                seen_good(now, scale)
                return {"hfr": round(now, 2), "moved": 0, "found": True, "readings": [], "left_alone": True,
                        "hfr_arcsec": round(now * scale, 2)}
            progress(f"sweeping: {SWEEP_POINTS} positions {settings['step']} half-steps apart, "
                     f"{SWEEP_FRAMES} frames each")
            result = motor_focus(drive, read, usual, say=say, sweep_only=mode == "sweep", live=live)
    except IndiError as problem:
        # A hung camera ends the run in one plain line, not a traceback,
        # saying where it left the focuser.
        if live.state["outcome"] is None:
            live.done("failed", "The camera stopped sending pictures, so the focus run could not finish.")
        raise hung(problem, frames, drive.moved if drive else 0) from None
    except OutOfReach:
        live.done("failed", "The next move would have gone beyond the focuser's travel, so the run stopped.")
        raise interface.Refusal("INVALID_REQUEST", f"Stopped: the next move would have taken the focuser beyond "
                                                   f"{travel} half-steps from where it started "
                                                   f"([focuser] travel). It is {drive.moved:+d} half-steps "
                                                   "from the start.") from None
    except KeyboardInterrupt:
        # Stopped part way (Ctrl-C, or the SIGTERM of a background stop):
        # on 23 October 2026 two runs stopped mid-sweep left the drawtube
        # wound out. Back to the start, the last move inward. A walk-in
        # moves inward only and stays where it is: going home would turn
        # the drawtube out, and throw away the way in.
        if drive is not None and drive.moved and mode != "walk":
            progress(f"stopped: taking the focuser back {-drive.moved:+d} half-steps to where it started")
            drive.home(settings["backlash"])
        live.done("failed", "The walk-in was stopped before it finished; the focuser stays where it is."
                  if mode == "walk" else
                  "The focus run was stopped before it finished; the focuser went back to where it started.")
        raise
    except BaseException:
        if live.state["outcome"] is None:
            live.done("failed", "The focus run stopped before it finished.")
        raise
    finally:
        motor.close()
        stopped()
    hfr = result["hfr"]
    fit = result["fit"]
    if mode == "sweep":
        progress(f"Sweep: {'focus at ' + format(fit['focus'], '+.0f') + ', HFR ' + str(fit['hfr']) if fit and fit['ok'] else 'no curve fitted'}"
                 "; the focuser is back where it started.")
    elif result["found"]:
        progress(f"Focused: HFR {hfr:.2f} ({hfr * scale:.1f}\"), {result['moved']:+d} half-steps from the start "
                 f"(it was {result['start_hfr']}).")
        # Only a run that reached good focus says what good focus is: one
        # that ended soft (18 October 2026, HFR 5.03) would raise the aim.
        if hfr <= 1.5 * usual:
            with RUNS_FILE.open("a", encoding="utf-8") as log:
                log.write(json.dumps({"saved": time.time(), "best_hfr": round(hfr, 2),
                                      "best_arcsec": round(hfr * scale, 2), "motor": True}) + "\n")
        else:
            progress(f"That is {hfr / usual:.1f} times the usual best, so it is not kept as what good focus is.")
    else:
        progress("No focus found: the focuser is back where it started.")
    return dict(result, hfr_arcsec=hfr and round(hfr * scale, 2))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--minutes", type=float, default=15)
    ap.add_argument("--scene", action="store_true",
                    help="focus on a daytime view instead of a star")
    ap.add_argument("--exposure", type=float, default=0.05, help="starting exposure, seconds")
    ap.add_argument("--gain", type=int, default=300)
    ap.add_argument("--quiet", action="store_true", help="no sound from the laptop")
    ap.add_argument("--numbers", action="store_true",
                    help="say each reading as a number, in place of the click and tone")
    ap.add_argument("--field", action="store_true",
                    help="first slew to a bright star in a rich part of the sky: MOVES the telescope")
    ap.add_argument("--dry-run", action="store_true",
                    help="with --field: say which star it would go to; with --motor: check the focuser "
                    "is plugged in. No camera, no mount, nothing turns")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--report", action="store_true",
                    help="how quickly the last run answered a turn of the knob; takes no frames")
    ap.add_argument("--frames", type=int, help="stop after this many frames")
    ap.add_argument("--json", action="store_true", help="the last reading as JSON at the end")
    ap.add_argument("--motor", action="store_true",
                    help="focus with the motor focuser, no hand on the knob; turns the focuser only, and "
                         "not at all if focus is already as good as usual")
    ap.add_argument("--anyway", action="store_true", help="with --motor: focus even if it is already good")
    ap.add_argument("--check", action="store_true",
                    help="how sharp the stars are now against the usual best; takes three frames, turns nothing")
    ap.add_argument("--sweep", action="store_true",
                    help="measure and fit one focus sweep with the motor, then go back to the start")
    ap.add_argument("--measure-step", action="store_true",
                    help="from focus, measure how far the motor must turn to grow the stars 2.5 times; keeps a "
                         "quarter of it as the sweep step")
    ap.add_argument("--find", action="store_true",
                    help="far out of focus: half a turn at a time in, then out, until stars measure")
    ap.add_argument("--walk-in", action="store_true",
                    help="from a little outside focus, set by hand: in a few half-steps at a time, slowly, "
                         "measuring each, to the sharpest; for when the motor cannot lift the drawtube out")
    ap.add_argument("--measure-backlash", action="store_true",
                    help="measure the focuser gears' slack on the steep side of the curve; keeps half as much "
                         "again as the overshoot")
    args = ap.parse_args()
    # Written to a file, stdout is held back in blocks: line by line, a log
    # being tailed shows each line as it is printed.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):     # not a real stream (a test's)
        pass
    for flag, mode in (("sweep", "sweep"), ("find", "find"), ("measure_step", "step"),
                       ("measure_backlash", "backlash"), ("walk_in", "walk")):
        if getattr(args, flag):
            return interface.main("focus.motor", lambda: run_motor(args, mode), args.json)
    if args.check:
        return interface.main("focus.check", lambda: run_check(args), args.json)
    if args.motor:
        return interface.main("focus.motor", lambda: run_motor(args), args.json)
    if args.report:
        return interface.main("focus.report", report, args.json)
    return interface.main("focus", lambda: run(args), args.json)


@activity.during("Focusing", "by the live view")
def run(args):
    """The focusing loop. Returns the last reading."""
    if not args.quiet and not host.has_sound()[0] == host.OK:
        print("No program to play sounds with (pw-play, paplay, aplay or ffplay), so there is no "
              "click or tone: only the changes of state are spoken.", flush=True)
    if getattr(args, "field", False):
        name = go_to_field(getattr(args, "dry_run", False))
        if args.dry_run:
            return {"would_move": True, "field": name}
    cam = Camera(args.port, args.gain)
    reading, live = {}, {}
    scale = arcsec_per_pixel()
    tracker = FocusTracker(usual_best() / scale)
    if not args.scene:
        cam.use("focus_fast")

    exposure, best = args.exposure, None
    frame, previous, seen = 0, None, []
    heard, rising, timings = None, False, []
    FRAMES_FILE.parent.mkdir(parents=True, exist_ok=True)
    FRAMES_FILE.write_text("", encoding="utf-8")
    end = time.monotonic() + args.minutes * 60
    pending = ahead(cam, exposure)
    try:
        while True:
            got, pending = collect(pending), None
            if isinstance(got, BaseException):
                raise got
            mosaic, binning, began, landed = got
            shot = exposure
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
            crop = CROP // binning
            words, noise, fraction = None, None, None
            if args.scene:
                value = sharpness(lum)
                best = value if best is None else max(best, value)
                seen.append(value)
                picture = shown
                text = f"sharpness {value:.1f}   best {best:.1f}"
                if lum.mean() * level < 30 and exposure >= MAX_EXPOSURE:
                    text = "too dark to see anything"
                # Judge exposure on the whole view, not its brightest point.
                top = float(np.percentile(lum, 99)) * level * 1.6
                if previous is not None:
                    change = (value - previous) / max(abs(previous), 1e-6)
                    trend = "better" if change > 0.04 else "worse" if change < -0.04 else "same"
                    text += f"  {trend.upper() if trend != 'same' else trend}"
                previous = value
                # The pitch runs from the dullest view seen to the sharpest.
                dullest = max(min(seen), 1e-9)
                spread = np.log(max(best / dullest, 1.0))
                fraction = float(np.log(max(value, dullest) / dullest) / spread) if spread > 0.05 else 0.5
                noise = "tone"
            else:
                # A full-size frame is measured on its middle alone, unless
                # that holds too few stars to trust.
                value, count = measure_stars(middle(lum)) if binning == 1 else (None, 0)
                if count < ENOUGH:
                    value, count = measure_stars(lum)
                # One star, or the ring of one far out of focus: where there
                # are not three stars to measure, and on a field that never
                # had them.
                ring = measure(lum) if not value or tracker.single else None
                picture = shown
                if value and not tracker.single:
                    value *= binning
                    text = f"HFR {value:.1f} ({value * scale:.1f}\")   {count} stars"
                    # Show the middle of the frame, where stars are big
                    # enough to see on a phone.
                    h, w = shown.shape[0] // 2, shown.shape[1] // 2
                    picture = shown[h - crop:h + crop, w - crop:w + crop]
                    # Many stars are wanted, so let the few brightest burn
                    # out: set the exposure by about the 30th brightest spot.
                    top = float(np.partition(blocks.ravel(), -30)[-30]) * level * 2
                elif ring:
                    # Its radius stands in for the HFR until stars appear.
                    x, y, diameter = ring
                    value, count = binning * diameter / 2, 0
                    x0, y0 = int(max(x - crop, 0)), int(max(y - crop, 0))
                    picture = shown[y0:y0 + 2 * crop, x0:x0 + 2 * crop]
                    text = (f"one star, radius {value:.1f}" if tracker.single else
                            f"ring radius {value:.0f}   (far from focus)")
                else:
                    value, count = None, 0
                    text = "no star in view"
                was = tracker.level
                told = tracker.feed(value, count)
                words, noise, fraction = told["say"], told["sound"], told["meter"]
                text = f"L{was} {LEVELS[was]}   {text}"
                if value and tracker.best:
                    text += f"   best {tracker.best:.1f}"
                text += f"   {told['trend']}" + (f"   {words}" if words else "")
                live = {"level": tracker.level, "level_name": LEVELS[tracker.level], "kind": "stars" if count else "ring" if value else "none",
                        "hfr": value and round(value, 2), "hfr_arcsec": value and round(value * scale, 2),
                        "stars": count, "best_hfr": tracker.best and round(tracker.best, 2),
                        "scatter": round(tracker.scatter(), 2), "trend": told["trend"], "state": tracker.state,
                        "meter": fraction and round(fraction, 3), "advice": words or live.get("advice"),
                        "binning": binning, "exposure_s": shot, "frame": frame, "saved": time.time()}
            # The next frame's exposure: keep the star bright but not burnt out.
            if top >= 250:
                exposure = max(MIN_EXPOSURE, exposure / 2)
            elif top < 40 and exposure < MAX_EXPOSURE:
                exposure = min(MAX_EXPOSURE, exposure * 2)
                if not rising and not words:
                    words = "Exposure increasing."
            rising = exposure > shot
            # The camera starts on the next frame before this one is heard.
            more = time.monotonic() < end and not (args.frames and frame >= args.frames)
            if more:
                if not args.scene:
                    cam.use("focus_fine" if tracker.level == 3 else "focus_fast")
                pending = ahead(cam, exposure)
            spoken = live.get("hfr") if getattr(args, "numbers", False) and not args.scene else None
            if not args.quiet and spoken:
                # The reading itself, for someone who would sooner hear it.
                say(f"{spoken:.1f}")
            elif not args.quiet:
                sound(noise, fraction)
                if words:
                    say(words)
            now = time.perf_counter()
            timing = {"capture_s": round(landed - began, 3), "process_s": round(now - landed, 3),
                      "feedback_s": round(now - began, 3), "cycle_s": heard and round(now - heard, 3)}
            heard = now
            timings.append(timing)
            if not args.scene:
                live["timing"] = timing
                keep(LIVE_FILE, live)
                with FRAMES_FILE.open("a", encoding="utf-8") as log:
                    log.write(json.dumps(live) + "\n")
                if live["kind"] == "stars":
                    reading = {"hfr": live["hfr"], "stars": count, "best_hfr": live["best_hfr"],
                               "hfr_arcsec": live["hfr_arcsec"], "level": live["level"], "state": live["state"],
                               "advice": live["advice"] or told["trend"], "exposure_s": shot,
                               "feedback_s": timing["feedback_s"], "saved": live["saved"]}
                    keep(FOCUS_FILE, reading)
            image = Image.fromarray(picture.astype(np.uint8)).convert("RGB")
            image = image.resize((900, round(900 * image.height / image.width)))
            text = f"#{frame} {time.strftime('%H:%M:%S')}  {text}"
            PREVIEW.parent.mkdir(exist_ok=True)    # the first thing run on a new machine may be this
            annotate(image, text).save(PREVIEW, quality=85)
            snap.label("focus view", f"{shot:g} s", PREVIEW.parent)
            print(f"{text}   (exposure {shot:g}s, peak {top:.0f}; frame in {timing['capture_s']:.2f} s, "
                  f"heard {timing['feedback_s']:.2f} s after it began)", flush=True)
            if not more:
                break
    except KeyboardInterrupt:
        pass
    finally:
        if pending is not None:
            # Let the exposure under way finish before the camera is closed.
            try:
                pending.get(timeout=exposure + 3)
            except queue.Empty:
                pass
        try:
            cam.use("imaging")      # leave it as every other script expects to find it
        except Exception:
            pass
        cam.close()
    # The middle figure of each timing over the run.
    timing = {}
    for key in ("capture_s", "process_s", "feedback_s", "cycle_s"):
        found = [t[key] for t in timings if t[key] is not None]
        timing[key] = round(float(np.median(found)), 3) if found else None
    if not reading:
        if args.scene:
            # A note that the focus was looked at by day: ./polaris.py will
            # not search on a focus nobody has checked.
            if best is not None:
                keep(FOCUS_FILE.with_name("focus_scene.json"),
                     {"sharpness": round(float(best), 2), "frames": frame, "saved": time.time()})
            return {"sharpness": best, "frames": frame, "timing": timing}
        raise interface.Refusal("NO_STARS", "No stars were measured.")
    if tracker.good:
        # What this run reached, for the next one to set its levels by.
        with RUNS_FILE.open("a", encoding="utf-8") as log:
            log.write(json.dumps({"saved": time.time(), "frames": frame, "best_hfr": round(tracker.best, 2),
                                  "best_arcsec": round(tracker.best * scale, 2), "timing": timing}) + "\n")
    return dict(reading, frames=frame, timing=timing)


if __name__ == "__main__":
    main()
