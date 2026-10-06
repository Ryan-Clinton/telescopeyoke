#!/usr/bin/env python3
"""Focusing aid you can use without looking at a screen.

    ./focus.py                 on stars: a click and a tone for every frame measured
    ./focus.py --quiet         no sound; the readings are printed and shown
    ./focus.py --numbers       each reading spoken as a number, in place of the sounds
    ./focus.py --field         first slew to a bright star in a rich part of
                               the sky (this MOVES the telescope)
    ./focus.py --field --dry-run   say which star; nothing moves
    ./focus.py --scene         on rooftops or trees, in daylight

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
import queue
import threading
import time
import wave
from pathlib import Path

import config

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

import host
import interface
import snap
import stacking
from camera import PORT, WHITE, Camera, luminance

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
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=30)
    draw.rectangle([0, 0, image.width, 60], fill=(0, 0, 0))
    draw.text((10, 12), text, fill=colour, font=font)
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
                    help="with --field: say which star it would go to; no camera, no mount")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--frames", type=int, help="stop after this many frames")
    ap.add_argument("--json", action="store_true", help="the last reading as JSON at the end")
    args = ap.parse_args()
    return interface.main("focus", lambda: run(args), args.json)


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
