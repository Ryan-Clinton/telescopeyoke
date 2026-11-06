"""Autoguiding through the guide camera's ST4 lead (docs/autoguiding.md):
finding and following a guide star, calibrating which way each ST4
direction moves it, and the loop that keeps it on its lock position.

    ./guidecam.py star        find a star and follow it, no pulses
    ./guidecam.py calibrate   pulse each way and learn what each does
    ./guidecam.py guide       guide: calibration reused or made, then the loop

Built so far: the star, the calibration, the closed loop, and (stage 4)
one guider owning the camera, the heartbeat on its own timer, numbered
orders confirmed once done, and the watch on a hung loop. Not yet:
shoot.py --guide and dithering.

The guide scope is the 50 mm Orion Mini (162 mm) with the GPCAM's 3.75 um
pixels read 2 x 2 binned: 9.55" a pixel (4.77" at full size, where the
camera drops frames). The guide rate is the handset's, measured on
6 November 2026 at about 7.1"/s; a calibration replaces it with its own.
"""
import fcntl
import json
import math
import os
import signal
import threading
import time
import uuid
from collections import deque, namedtuple
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy import ndimage

import config
import guidemath
import interface

FOCAL_MM = 162.0
PIXEL_UM = 3.75
BIN = 2                  # the camera is read 2 x 2 binned (guidecam.GUIDE_SIZE): full size drops frames
SCALE = 206.265 * PIXEL_UM * BIN / FOCAL_MM     # arcseconds a guide pixel: 9.55 binned (4.77 at full size)

# The limits below in guide pixels are for 2 x 2 binning: each is half its
# full-size value, so it is the same on the sky.
GUIDE_RATE = 7.1                          # "/s, measured 6 Nov 2026; a calibration's own replaces it

# Finding the star
SATURATED = 230      # a peak this high or more may be clipped: not chosen
EDGE = 15            # px from the frame's edge (640 x 480)
NEIGHBOUR = 8        # px: no brighter star nearer than this
SNR_FIND = 10        # to be chosen
SNR_LOST = 6         # below this while guiding, the star counts as lost
HFD_LEAST = 0.4      # px: narrower is a hot pixel, not a star (binned, a star is only a pixel or two across)
BOX = 6              # half-width of the box a star is measured in
AMBIGUOUS = 1.0      # px: two stars this close in distance from where the star should be: neither taken
WINDOW = 10          # half-width of the search window round where the star should be
RELOCK_RADIUS = 5    # px from the lock a lost star must come back within
JUMP = 4             # px in one frame: a satellite, a bird or a cosmic ray
LOST_FRAMES = 3      # frames running without the star: lost
RETRY_S = 10         # seconds between looks for a star when there is none

# Calibration
CAL_DISTANCE = 13    # px each leg aims to move the star: about 2' (25 px at full size)
CAL_STEPS = 12       # steps the leg is planned in
CAL_MOST_STEPS = 15
CAL_LEAST_STEPS = 8  # fewer than this to cover the distance: steps too long
CAL_LONGEST_MS = 3000
CAL_SLACK_STEPS = 10  # most steps north before the Dec slack counts as taken up
CAL_REVERSAL_STEPS = 6  # steps of each extra Dec reversal that measures the slack again
VERIFY_STEPS = 3     # steps each way of the check on a reused calibration
VERIFY_ANGLE = 30    # degrees a reused direction may be off
VERIFY_SIZE = 0.35   # share a reused strength may be off
RETURN_PX = 1.0      # px from where it started a check's way back must end
SLACK_MOVED = 0.8    # px: the star has started to move (the Dec slack taken up); three times it, a leg that moved at all

# The loop (PHD2's defaults as a start)
RA_AGGRESSION = 0.7
RA_HYSTERESIS = 0.1
RA_MIN_MOVE = 0.15   # guide px
DEC_AGGRESSION = 1.0
DEC_MIN_MOVE = 0.20  # guide px
DEC_SWITCH_FRAMES = 3
DEC_FAST = 3         # an error this many times the minimum move switches Dec at once
SLACK_START = 0.5    # share of the measured slack taken up on a Dec reversal, to start
LONGEST_PULSE = 2.5  # seconds per axis per frame
RMS_FRAMES = 30

# Limits: each is a fault
ERROR_FAULT_PX = 15
ERROR_FAULT_FRAMES = 5
CORRECTION_FAULT = 600.0   # arcseconds of signed correction on an axis since the lock was set
RUNAWAY_FRAMES = 10        # frames running at the longest pulse the same way

# Owning the camera, the heartbeat and orders
HEARTBEAT_S = 1.0          # the state file's heartbeat, on its own timer
STALE_S = 5.0              # a heartbeat older than this: the guider is not to be trusted
ORDERS = ("pause", "resume", "relock", "dither", "stop")
ORDER_TIMEOUT = {"pause": 10, "resume": 30, "relock": 60, "dither": 60, "stop": 15}
ORDER_STALE_S = 120        # an order not taken within this long is answered as failed
RELOCK_PATIENCE = 50.0     # seconds a relock looks for a star
DITHER_MOST_PX = 5.0       # guide px (about 48"): the furthest a dither may put the lock from where relock set it
DITHER_SETTLED_PX = 0.5    # guide px: a dither is done once the star is this close to its new lock...
DITHER_SETTLED_FRAMES = 2  # ...for this many guide frames running
DITHER_SETTLE_MAX = 50.0   # seconds a dither may take to settle (its order times out at 60)

STATE_FILE = config.DATA / "cache" / "guide.json"
PID_FILE = config.DATA / "cache" / "guide.pid"          # who holds the guide camera (information only)
CAMERA_LOCK = config.DATA / "cache" / "guide.lock"      # the kernel lock that decides it
ORDER_DIR = config.DATA / "cache" / "guide-orders"      # one file per order, and one per result
CAL_FILE = config.DATA / "cache" / "guide-cal.json"
LOG_FOLDER = config.DATA / "frames" / "guide"

# Each ST4 direction, as the shared maths names it.
AXIS_SIGN = {"west": ("RA", 1), "east": ("RA", -1), "north": ("Dec", 1), "south": ("Dec", -1)}
OPPOSITE = {"west": "east", "east": "west", "north": "south", "south": "north"}

Star = namedtuple("Star", "x y peak snr hfd")


class Fault(interface.Refusal):
    def __init__(self, message):
        super().__init__("INVALID_REQUEST", message)


def light_path():
    """What a calibration was made with: it is used again only on the same."""
    import guidecam
    return {"camera": guidecam.MODEL, "focal_mm": round(FOCAL_MM), "binning": BIN}


def motion_check():
    """Refuses while the motion lock is set: checked before every pulse."""
    import mount
    if mount.LOCK_FILE.exists():
        raise interface.Refusal("MOTION_LOCKED", "Motion is locked: "
                                + mount.LOCK_FILE.read_text(encoding="utf-8").strip())


# ---------------------------------------------------------------- the star

def measure(frame, x, y, box=BOX):
    """The star near (x, y): its centroid, peak, signal to noise and HFD,
    from a box round it with the median of the box's border taken off as
    background. Only pixels 3 noise above the background count, so the
    noise does not pull the centroid. None if there is nothing there or the
    box would cross the frame's edge."""
    h, w = frame.shape
    cx, cy = int(round(x)), int(round(y))
    x0, x1, y0, y1 = cx - box, cx + box + 1, cy - box, cy + box + 1
    if x0 < 0 or y0 < 0 or x1 > w or y1 > h:
        return None
    cut = frame[y0:y1, x0:x1].astype(float)
    border = np.concatenate([cut[0], cut[-1], cut[1:-1, 0], cut[1:-1, -1]])
    bg = float(np.median(border))
    noise = max(float(np.median(np.abs(border - bg))) * 1.4826, 0.5)
    signal = cut - bg
    signal[signal < 3 * noise] = 0
    flux = float(signal.sum())
    if flux <= 0:
        return None
    yy, xx = np.mgrid[0:cut.shape[0], 0:cut.shape[1]]
    mx, my = float((signal * xx).sum() / flux), float((signal * yy).sum() / flux)
    pixels = int((signal > 0).sum())
    snr = flux / (noise * math.sqrt(pixels))
    hfd = 2 * float((signal * np.hypot(xx - mx, yy - my)).sum() / flux)
    return Star(mx + x0, my + y0, float(cut.max()), snr, hfd)


def _peaks(frame, threshold, within=None):
    """Local maxima of the lightly smoothed frame above `threshold`,
    brightest first, as (x, y, raw peak nearby)."""
    smooth = ndimage.uniform_filter(frame.astype(float), 3)
    local = ndimage.maximum_filter(smooth, size=5)
    ys, xs = np.nonzero((smooth == local) & (smooth > threshold))
    if within is not None:
        (ox, oy), r = within
        keep = (np.abs(xs - ox) <= r) & (np.abs(ys - oy) <= r)
        xs, ys = xs[keep], ys[keep]
    order = np.argsort(-smooth[ys, xs])[:200]
    h, w = frame.shape
    out = []
    for k in order:
        x, y = int(xs[k]), int(ys[k])
        raw = int(frame[max(y - 1, 0):min(y + 2, h), max(x - 1, 0):min(x + 2, w)].max())
        out.append((x, y, raw))
    return out


def background(frame):
    med = float(np.median(frame))
    return med, max(float(np.median(np.abs(frame - med))) * 1.4826, 0.5)


def find_star(frame):
    """The guide star: the brightest that is not saturated, at least EDGE
    from the frame's edge, with no brighter star within NEIGHBOUR, shaped
    like a star (not a hot pixel) and with SNR above SNR_FIND. Returns
    (Star or None, why none)."""
    med, noise = background(frame)
    peaks = _peaks(frame, med + 5 * noise)
    if not peaks:
        return None, "no star above the background"
    h, w = frame.shape
    why = "no star passes"
    for i, (x, y, raw) in enumerate(peaks):
        if raw >= SATURATED:
            why = "only saturated stars"
            continue
        if x < EDGE or y < EDGE or x >= w - EDGE or y >= h - EDGE:
            continue
        if any(math.hypot(x - bx, y - by) < NEIGHBOUR for bx, by, _ in peaks[:i]):
            continue
        star = measure(frame, x, y)
        if star is None or star.hfd < HFD_LEAST:
            continue
        if star.snr < SNR_FIND:
            why = f"the best star's SNR is {star.snr:.1f}, under {SNR_FIND}"
            break       # dimmer ones will be worse
        return star, ""
    return None, why


def follow(frame, where, window=WINDOW, least_snr=SNR_LOST):
    """The star looked for only within `window` of where it should be.
    Returns (Star or None, why not)."""
    med, noise = background(frame)
    peaks = _peaks(frame, med + 3 * noise, within=(where, window))
    if not peaks:
        return None, "no star in the window"
    stars = []
    for x, y, _ in peaks[:20]:
        star = measure(frame, x, y)
        if star is not None and star.hfd >= HFD_LEAST and star.snr >= least_snr:
            stars.append((math.hypot(star.x - where[0], star.y - where[1]), star))
    if not stars:
        return None, f"no star in the window passes (SNR {least_snr}, not a hot pixel, inside the frame)"
    stars.sort(key=lambda pair: pair[0])
    # The nearest to where it should be, not the brightest; two about as near is no answer.
    if len(stars) > 1 and stars[1][0] - stars[0][0] < AMBIGUOUS \
            and math.hypot(stars[1][1].x - stars[0][1].x, stars[1][1].y - stars[0][1].y) > 2 * AMBIGUOUS:
        return None, (f"two stars about as near ({stars[0][0]:.1f} and {stars[1][0]:.1f} px): "
                      "not guessing which")
    return stars[0][1], ""


def first_star(cam, seconds, gain=None, say=print, patience=300.0, sleep=time.sleep, tick=None):
    """A star to guide on, looking every RETRY_S seconds for up to `patience`
    seconds (cloud passes). `tick` is called at each look, so a watcher
    knows the search is alive."""
    began = time.monotonic()
    while True:
        if tick:
            tick()
        frame, _ = cam.timed_frame(seconds, gain)
        star, why = find_star(frame)
        if star:
            return star
        if time.monotonic() - began > patience:
            raise Fault(f"No guide star in {patience:.0f} s: {why}.")
        say(f"  no guide star ({why}; frame level {frame.mean():.1f}, highest {frame.max()}); "
            f"looking again in {RETRY_S} s")
        sleep(RETRY_S)


def watch(cam, seconds, count, gain=None, say=print):
    """Stage 1: find a star and follow it through `count` frames with no
    pulses, saying where it is each frame and, at the end, how much it
    wandered. Returns the per-frame rows."""
    star = first_star(cam, seconds, gain, say)
    say(f"star at {star.x:.2f}, {star.y:.2f}: peak {star.peak:.0f}, SNR {star.snr:.1f}, HFD {star.hfd:.2f} px")
    rows, where = [], (star.x, star.y)
    for n in range(count):
        frame, times = cam.timed_frame(seconds, gain)
        found, why = follow(frame, where)
        if not found:
            say(f"{n + 1:3}: lost ({why})")
            continue
        step = math.hypot(found.x - where[0], found.y - where[1])
        where = (found.x, found.y)
        rows.append((times["mid"], found.x, found.y))
        say(f"{n + 1:3}: {found.x:8.2f} {found.y:8.2f}  SNR {found.snr:5.1f}  HFD {found.hfd:4.2f}  "
            f"moved {step:4.2f} px")
    if len(rows) >= 3:
        xy = np.array([r[1:] for r in rows])
        jitter = float(np.sqrt(np.mean(np.sum((xy - xy.mean(axis=0)) ** 2, axis=1))))
        drift = guidemath.drift_rate(rows, last=len(rows))
        say(f"wander: {jitter:.2f} px RMS ({jitter * SCALE:.1f}\"); drift {drift[0]:+.3f}, {drift[1]:+.3f} px/s")
    return rows


# ------------------------------------------------------------ calibration

def step_seconds(dec, rate=GUIDE_RATE):
    """Calibration step lengths (RA, Dec) in seconds: CAL_DISTANCE pixels in
    CAL_STEPS steps at the guide rate, rounded up to 50 ms. RA's are longer
    by 1/cos(Dec), as the sky turns less far for the same pulse there; both
    capped at CAL_LONGEST_MS."""
    def ms(value):
        return min(math.ceil(value * 1000 / 50) * 50, CAL_LONGEST_MS) / 1000
    base = CAL_DISTANCE * SCALE / rate / CAL_STEPS
    return ms(base / max(math.cos(math.radians(dec)), 0.05)), ms(base)


def _rate(points, step):
    """The column (px/s) a leg's positions give: a straight line through x
    and y against the seconds of pulse sent."""
    t = np.arange(len(points)) * step
    xy = np.array(points, float)
    return np.array([np.polyfit(t, xy[:, k], 1)[0] for k in (0, 1)])


class Calibrator:
    """Moves the star through ST4 in steps and measures each, keeping the
    star in its window throughout."""

    def __init__(self, cam, seconds, gain=None, say=print, tick=None):
        self.cam, self.seconds, self.gain, self.say = cam, seconds, gain, say
        self.tick = tick
        self.where = None

    def look(self):
        if self.tick:
            self.tick()
        frame, _ = self.cam.timed_frame(self.seconds, self.gain)
        star, why = follow(frame, self.where)
        if star is None:
            raise Fault(f"The star was lost during calibration: {why}.")
        self.where = (star.x, star.y)
        return self.where

    def step(self, direction, seconds):
        if self.tick:
            self.tick()                     # orders (a stop) are taken here, before the pulse
        motion_check()
        self.cam.pulse(direction, seconds)
        return self.look()

    def leg(self, direction, seconds, distance=CAL_DISTANCE, most=CAL_MOST_STEPS):
        """Steps one way until the star has moved `distance` px or `most`
        steps have gone. Returns the positions, the start included."""
        points = [self.look()]
        for _ in range(most):
            points.append(self.step(direction, seconds))
            if math.hypot(points[-1][0] - points[0][0], points[-1][1] - points[0][1]) >= distance:
                break
        return points

    def back(self, direction, seconds, steps):
        points = [self.where]
        for _ in range(steps):
            points.append(self.step(direction, seconds))
        return points


def _moved(points):
    return math.hypot(points[-1][0] - points[0][0], points[-1][1] - points[0][1])


def _enough(leg, points, steps):
    """A leg that did not move the star far enough is a failed calibration,
    never a calibration to guide with."""
    moved = _moved(points)
    if moved < SLACK_MOVED * 3:
        raise Fault(f"{steps} {leg} steps moved the star only {moved:.1f} px: the ST4 {leg} line is not "
                    "moving the mount. Calibration failed; nothing kept.")
    if leg in ("west", "north") and moved < CAL_DISTANCE * 0.6:
        raise Fault(f"{steps} {leg} steps moved the star only {moved:.1f} px of {CAL_DISTANCE}: too little "
                    "to measure. Calibration failed; nothing kept.")


def _slack_of(points, step, strength, unit):
    """Seconds of a leg's pulses lost to slack, from how far it got along
    `unit` against what `strength` (px/s) would have moved it."""
    went = float(np.dot(np.subtract(points[-1], points[0]), unit))
    return max((len(points) - 1) * step - max(went, 0.0) / strength, 0.0)


def calibrate(cam, seconds, dec, west, gain=None, say=print, rate=GUIDE_RATE, tick=None):
    """Stage 2: west and back east, then north and back south (the Dec
    slack taken up first), then two short Dec reversals to measure the
    slack again. Returns the calibration (also kept in CAL_FILE)."""
    motion_check()
    ra_step, dec_step = step_seconds(dec, rate)
    say(f"calibrating at Dec {dec:+.1f}, {'west' if west else 'east'} of the pier: steps of "
        f"{ra_step * 1000:.0f} ms in RA, {dec_step * 1000:.0f} ms in Dec")
    star = first_star(cam, seconds, gain, say, tick=tick)
    c = Calibrator(cam, seconds, gain, say, tick)
    c.where = (star.x, star.y)
    columns, steps, notes = {}, {}, []

    west_points = c.leg("west", ra_step)
    steps["west"] = len(west_points) - 1
    _enough("west", west_points, steps["west"])
    columns["west"] = _rate(west_points, ra_step)
    say(f"  west: {steps['west']} steps, {np.hypot(*columns['west']):.2f} px/s")
    east_points = c.back("east", ra_step, steps["west"])
    _enough("east", east_points, steps["west"])
    columns["east"] = _rate(east_points, ra_step)
    say(f"  east: {steps['west']} steps back, {np.hypot(*columns['east']):.2f} px/s")

    # The Dec slack: north until the star starts to move.
    start = c.look()
    for n in range(CAL_SLACK_STEPS):
        here = c.step("north", dec_step)
        if math.hypot(here[0] - start[0], here[1] - start[1]) >= SLACK_MOVED:
            break
    else:
        raise Fault(f"{CAL_SLACK_STEPS} north steps of {dec_step:.2f} s did not move the star: "
                    "Dec slack longer than that, or the ST4 north line is not working.")
    say(f"  Dec slack taken up after {n + 1} north steps")
    north_points = c.leg("north", dec_step)
    steps["north"] = len(north_points) - 1
    _enough("north", north_points, steps["north"])
    columns["north"] = _rate(north_points, dec_step)
    north_strength = float(np.hypot(*columns["north"]))
    say(f"  north: {steps['north']} steps, {north_strength:.2f} px/s")

    unit = columns["north"] / north_strength
    south_points = c.back("south", dec_step, steps["north"])
    slacks = [_slack_of(south_points, dec_step, north_strength, -unit)]
    # The south column from the steps after the slack, as the motor turns as fast either way.
    moving = [i for i in range(1, len(south_points))
              if np.dot(np.subtract(south_points[i], south_points[i - 1]), -unit) > 0.5 * north_strength * dec_step]
    columns["south"] = (_rate(south_points[moving[0] - 1:], dec_step)
                        if len(moving) >= 3 else -columns["north"])
    for direction, sign in (("north", 1), ("south", -1)):
        points = c.back(direction, dec_step, CAL_REVERSAL_STEPS)
        slacks.append(_slack_of(points, dec_step, north_strength, sign * unit))
    backlash = float(np.mean(slacks))
    spread = float(np.std(slacks))
    capped = any(s >= CAL_REVERSAL_STEPS * dec_step * 0.95 for s in slacks[1:])
    say(f"  Dec slack: {', '.join(f'{s:.2f}' for s in slacks)} s; {backlash:.2f} +/- {spread:.2f} s"
        + (" (at least: a reversal moved nothing)" if capped else ""))
    if capped:
        notes.append("Dec slack may be longer than the reversal steps measured")

    angle = math.degrees(math.atan2(columns["west"][1], columns["west"][0]))
    between = math.degrees(math.acos(np.clip(
        np.dot(columns["west"], columns["north"]) / (np.hypot(*columns["west"]) * north_strength), -1, 1)))
    ra_rate = float(np.hypot(*columns["west"])) * SCALE / max(math.cos(math.radians(dec)), 0.05)
    dec_rate = north_strength * SCALE
    if abs(between - 90) > 10:
        raise Fault(f"RA and Dec moved the star {between:.0f} degrees apart, not 90 +/- 10: the measurement "
                    "is not to be trusted (wind, a slipping clutch, or the star mistaken). Calibration failed; "
                    "nothing kept.")
    # Usable from here. Whether it also meets the first night's pass
    # (docs/autoguiding.md, proof step 1) is said apart: a usable calibration
    # is not a passed commissioning.
    for label, measured in (("RA", ra_rate), ("Dec", dec_rate)):
        if abs(measured / rate - 1) > 0.2:
            notes.append(f"{label} guide rate {measured:.1f}\"/s, not within 20 % of {rate:.1f}")
    for leg in ("west", "north"):
        if steps[leg] < CAL_LEAST_STEPS:
            notes.append(f"{leg} took {steps[leg]} steps, under {CAL_LEAST_STEPS}: steps too long")

    cal = {
        "made": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **light_path(), "scale": SCALE, "dec": dec, "west": west,
        "columns": {k: [float(v[0]), float(v[1])] for k, v in columns.items()},
        "steps": steps, "step_ms": {"ra": round(ra_step * 1000), "dec": round(dec_step * 1000)},
        "angle_deg": round(angle, 1), "axes_apart_deg": round(between, 1),
        "ra_rate": round(ra_rate, 2), "dec_rate": round(dec_rate, 2),
        "backlash_s": round(backlash, 2), "backlash_spread_s": round(spread, 2),
        "dec_after_flip": None, "notes": notes,
        "usable": True, "first_night_pass": not notes,
    }
    say(f"  camera angle {angle:.1f} deg, axes {between:.1f} deg apart, guide rate RA {ra_rate:.1f}\"/s, "
        f"Dec {dec_rate:.1f}\"/s")
    for note in notes:
        say(f"  short of the first night's pass: {note}")
    say("  usable for guiding; " + ("meets the first night's calibration pass" if not notes
                                     else "does NOT meet the first night's calibration pass"))
    keep_calibration(cal)
    return cal


def keep_calibration(cal, path=None):
    path = path or CAL_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cal, indent=1), encoding="utf-8")


def load_calibration(path=None):
    path = path or CAL_FILE
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def reuse(cal, dec, west):
    """The calibration's columns for a target at `dec` on side `west`, or
    (None, why) when it cannot be reused. RA is scaled by
    cos(target Dec)/cos(calibration Dec). Across the pier the camera has
    turned half round, so RA's columns turn round; which way Dec goes is
    taken only from what was measured on this mount (dec_after_flip), never
    assumed: until it is, Dec is left as calibrated and verify() measures
    it before any guiding."""
    if not cal:
        return None, "no calibration kept"
    if {k: cal.get(k) for k in light_path()} != light_path() or abs((cal.get("scale") or 0) - SCALE) > 0.01:
        return None, (f"made with another guide camera, scope or binning (binning {cal.get('binning')}, "
                      f"{cal.get('scale') or 0:.2f}\"/px; now {BIN}, {SCALE:.2f}\"/px)")
    factor = math.cos(math.radians(dec)) / max(math.cos(math.radians(cal["dec"])), 0.05)
    cols = {k: np.array(v, float) for k, v in cal["columns"].items()}
    for k in ("west", "east"):
        cols[k] = cols[k] * factor
    if west != cal["west"]:
        # Dec unknown after a flip: left as it was, and verify() finds out.
        for k in ("west", "east"):
            cols[k] = -cols[k]
        if cal["dec_after_flip"] == "negated":
            for k in ("north", "south"):
                cols[k] = -cols[k]
    return cols, ""


def verify(cam, seconds, cal, cols, west, gain=None, say=print, tick=None):
    """The check on a reused calibration: VERIFY_STEPS steps west and back,
    north and back. Each must go the way the columns say, within
    VERIFY_ANGLE degrees and VERIFY_SIZE of the strength. Across the pier
    with Dec not yet known, a north move exactly reversed is recorded as
    what this mount does, once its strength has matched too. The way back
    is checked as well: RA must return within RETURN_PX of where it
    started, Dec within the measured slack's worth plus RETURN_PX. Returns
    (True, "") or (False, why)."""
    ra_step, dec_step = (cal["step_ms"]["ra"] / 1000, cal["step_ms"]["dec"] / 1000)
    star = first_star(cam, seconds, gain, say, tick=tick)
    c = Calibrator(cam, seconds, gain, say, tick)
    c.where = (star.x, star.y)
    results = {}
    for direction, step in (("west", ra_step), ("north", dec_step)):
        start = c.look()
        if direction == "north":                    # the slack first, as in calibration
            for _ in range(CAL_SLACK_STEPS):
                here = c.step("north", dec_step)
                if math.hypot(here[0] - start[0], here[1] - start[1]) >= SLACK_MOVED:
                    break
            start = c.look()
        end = c.back(direction, step, VERIFY_STEPS)[-1]
        home = c.back(OPPOSITE[direction], step, VERIFY_STEPS)[-1]
        results[direction] = np.subtract(end, start) / (VERIFY_STEPS * step)
        results[OPPOSITE[direction]] = np.subtract(home, end) / (VERIFY_STEPS * step)
        missed = math.hypot(home[0] - start[0], home[1] - start[1])
        allowed = RETURN_PX + (cal.get("backlash_s", 0.0) * float(np.hypot(*cols["north"]))
                               if direction == "north" else 0.0)
        if missed > allowed:
            return False, (f"{OPPOSITE[direction]} did not bring the star back: {missed:.1f} px from where "
                           f"it started, more than {allowed:.1f}")
    say("  check: " + ", ".join(f"{k} {v[0]:+.2f},{v[1]:+.2f} px/s" for k, v in results.items()))
    measured_now = None             # Dec after a flip, if this check is what found it out
    for direction, got in results.items():
        want = -cols[direction] if direction == "south" and measured_now == "negated" else cols[direction]
        strength, expected = float(np.hypot(*got)), float(np.hypot(*want))
        if direction == "south":
            # The way back after a reversal: shortened by the slack by design,
            # so only its direction is judged.
            off = math.degrees(math.acos(np.clip(np.dot(got, want) / max(strength * expected, 1e-9), -1, 1)))
            if strength < 0.1 * expected or off > 90:
                return False, f"south did not move the star back towards where it came from ({off:.0f} degrees off)"
            continue
        if abs(strength / max(expected, 1e-9) - 1) > VERIFY_SIZE:
            return False, f"{direction} moved the star {strength:.2f} px/s against {expected:.2f}"
        off = math.degrees(math.acos(np.clip(np.dot(got, want) / max(strength * expected, 1e-9), -1, 1)))
        if direction == "north" and west != cal["west"] and cal.get("dec_after_flip") is None:
            what = "same" if off < VERIFY_ANGLE else "negated" if off > 180 - VERIFY_ANGLE else None
            if what is None:
                return False, f"north went {off:.0f} degrees from either way it could"
            cal["dec_after_flip"] = measured_now = what
            keep_calibration(cal)
            say(f"  after a flip, Dec on this mount: {what}; kept")
            continue
        if off > VERIFY_ANGLE:
            return False, f"{direction} went {off:.0f} degrees off the calibrated way"
    return True, ""


# ------------------------------------------------------------ the loop

class Controller:
    """Each frame's error (px from the lock) to pulses (signed seconds on
    RA and Dec: + is west and north): RA by hysteresis, Dec by resist
    switch, the Dec slack partly taken up on a reversal and adjusted by
    what follows, and the limits that make a fault."""

    def __init__(self, cols, backlash=0.0, spread=0.0, exposure=2.0, one_way=None):
        self.columns = {AXIS_SIGN[k]: np.asarray(v, float) for k, v in cols.items()}
        self.backlash, self.spread, self.exposure = backlash, spread, exposure
        self.one_way = {"north": 1, "south": -1}.get(one_way)
        self.ra_last = 0.0
        self.dec_dir = None
        self.dec_waiting = 0
        self.slack_share = SLACK_START
        self.slack_most = (backlash + spread) / backlash if backlash > 0 else 0.0
        self.reversed_with = None       # the Dec error before a reversal with slack taken up
        self.reset_limits()

    def reset_limits(self):
        """The three limits start again: only on an acknowledged relock."""
        self.sent = {"RA": 0.0, "Dec": 0.0}
        self.far_frames = 0
        self.saturated = {"RA": (0, 0), "Dec": (0, 0)}     # (sign, frames running at the longest)

    def strength(self, axis, sign):
        return float(np.hypot(*self.columns[(axis, sign)]))

    def axis_errors(self, error):
        """The correction each axis needs to bring the star back, in guide
        px along that axis (signed: + west / north)."""
        seconds = guidemath.solve(self.columns, -np.asarray(error, float))
        return [s * self.strength(axis, 1 if s >= 0 else -1) for axis, s in zip(("RA", "Dec"), seconds)]

    def ra(self, x):
        if abs(x) < RA_MIN_MOVE:
            out = 0.0
        else:
            out = ((1 - RA_HYSTERESIS) * x + RA_HYSTERESIS * self.ra_last) * RA_AGGRESSION
        self.ra_last = out
        return out

    def dec(self, y):
        """The Dec move in px, and whether it reverses the Dec motor."""
        if self.reversed_with is not None:
            before = self.reversed_with
            self.reversed_with = None
            if y * before < 0 and abs(y) > DEC_MIN_MOVE:
                self.slack_share = max(self.slack_share - 0.1, 0.0)            # overshot
            elif y * before > 0 and abs(y) > 0.7 * abs(before):
                self.slack_share = min(self.slack_share + 0.1, self.slack_most)  # barely moved
        if abs(y) < DEC_MIN_MOVE:
            return 0.0, False
        want = 1 if y > 0 else -1
        if self.one_way and want != self.one_way:
            return 0.0, False
        if self.dec_dir is None or want == self.dec_dir:
            self.dec_dir, self.dec_waiting = want, 0
            return y * DEC_AGGRESSION, False
        self.dec_waiting += 1
        if self.dec_waiting >= DEC_SWITCH_FRAMES or abs(y) > DEC_FAST * DEC_MIN_MOVE:
            self.dec_dir, self.dec_waiting = want, 0
            self.reversed_with = y
            return y * DEC_AGGRESSION, True
        return 0.0, False

    def pulses(self, error):
        """Signed seconds (RA, Dec) for this frame, and what was decided."""
        error = np.asarray(error, float)
        self.far_frames = self.far_frames + 1 if np.hypot(*error) > ERROR_FAULT_PX else 0
        if self.far_frames >= ERROR_FAULT_FRAMES:
            raise Fault(f"The star has been over {ERROR_FAULT_PX} px from the lock for {self.far_frames} frames.")
        ra_px, dec_px = self.axis_errors(error)
        ra_move = self.ra(ra_px)
        dec_move, reversal = self.dec(dec_px)
        seconds = []
        for axis, move in (("RA", ra_move), ("Dec", dec_move)):
            sign = 1 if move >= 0 else -1
            seconds.append(move / self.strength(axis, sign) if move else 0.0)
        if reversal and self.backlash > 0:
            seconds[1] += math.copysign(self.slack_share * self.backlash, seconds[1])
        wanted = list(seconds)
        seconds = [max(-LONGEST_PULSE, min(LONGEST_PULSE, s)) for s in seconds]
        total = abs(seconds[0]) + abs(seconds[1])
        if total > self.exposure:
            seconds = [s * self.exposure / total for s in seconds]
        for axis, want in zip(("RA", "Dec"), wanted):
            sign, run = self.saturated[axis]
            at_most = abs(want) >= LONGEST_PULSE
            new_sign = 1 if want > 0 else -1
            self.saturated[axis] = (new_sign, run + 1 if at_most and new_sign == sign else int(at_most))
            if self.saturated[axis][1] >= RUNAWAY_FRAMES:
                raise Fault(f"{RUNAWAY_FRAMES} frames running wanted the longest {axis} pulse the same way: a runaway.")
        for axis, s in zip(("RA", "Dec"), seconds):
            if s:
                self.sent[axis] += s * self.strength(axis, 1 if s > 0 else -1) * SCALE
            if abs(self.sent[axis]) > CORRECTION_FAULT:
                raise Fault(f"{self.sent[axis] / 60:+.1f}' of {axis} correction since the lock was set, "
                            f"past {CORRECTION_FAULT / 60:.0f}'.")
        return seconds, {"ra_px": ra_px, "dec_px": dec_px, "reversal": reversal,
                         "slack_share": round(self.slack_share, 2)}


def write_state(state, path=None):
    path = path or STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_suffix(f".{threading.get_ident()}.tmp")
    scratch.write_text(json.dumps(state), encoding="utf-8")
    os.replace(scratch, path)


def read_state(path=None):
    try:
        return json.loads((path or STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def send(cam, seconds):
    """The pulses, RA then Dec, the second only once the first has ended
    (GuideCamera.pulse returns only then), the motion lock checked before
    each."""
    for (plus, minus), s in zip((("west", "east"), ("north", "south")), seconds):
        if abs(s) >= 0.01:
            motion_check()
            cam.pulse(plus if s > 0 else minus, abs(s))


# ------------------------------------------------- owning the guide camera

def alive(pid):
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (TypeError, ValueError, OverflowError):
        return False
    return True


def owner(lock_path=None, info_path=None):
    """Who holds the guide camera ({pid, run, role, started}), or None. The
    kernel's lock on CAMERA_LOCK says whether it is held (it goes when the
    holder's process ends, however it ends); the pid file says by whom."""
    lock_path, info_path = lock_path or CAMERA_LOCK, info_path or PID_FILE
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        try:
            held = json.loads(info_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            held = {}
        return held if isinstance(held, dict) and held else {"pid": None, "role": "unknown"}
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return None
    finally:
        os.close(fd)


class Ownership:
    """The guide camera and its ST4 port held by this process for as long as
    the `with` lasts. Every command that opens the guide camera takes it,
    the guider and the diagnostics alike, so two can never use it at once.
    It is a kernel lock (flock), so it is atomic, and it is let go when the
    process ends, even by a crash or SIGKILL: no stale file to take over."""

    def __init__(self, run=None, role="guider", lock_path=None, info_path=None):
        self.lock_path, self.info_path = lock_path or CAMERA_LOCK, info_path or PID_FILE
        self.run, self.role, self.fd = run, role, None

    def __enter__(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            try:
                held = json.loads(self.info_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                held = {}
            raise interface.Refusal("INVALID_REQUEST", f"The guide camera is in use ({held.get('role', 'unknown')}, "
                                    f"process {held.get('pid')}, run {held.get('run')}): one user at a time."
                                    + (" Stop the guider with ./guidecam.py tell stop." if held.get("role") == "guider"
                                       else "")) from None
        self.fd = fd
        scratch = self.info_path.with_suffix(".tmp")
        scratch.write_text(json.dumps({"pid": os.getpid(), "run": self.run, "role": self.role,
                                       "started": time.time()}), encoding="utf-8")
        os.replace(scratch, self.info_path)
        return self

    def __exit__(self, *exc):
        try:
            held = json.loads(self.info_path.read_text(encoding="utf-8"))
            if held.get("pid") == os.getpid():
                self.info_path.unlink()
        except (OSError, ValueError):
            pass
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None


def process_start(pid):
    """When process `pid` started (clock ticks since boot, /proc/PID/stat),
    or None if there is no such process. With the pid it names one process:
    a pid can be used again by another once the first has gone."""
    try:
        stat = Path(f"/proc/{int(pid)}/stat").read_text()
    except (OSError, TypeError, ValueError):
        return None
    return int(stat.rsplit(")", 1)[1].split()[19])


def terminate(pid, start, wait=10.0, sleep=time.sleep):
    """End a guider that cannot end itself (its loop hung inside the camera
    library: the heartbeat's watch writes `fault` but cannot interrupt the
    call). SIGTERM first; SIGKILL if it is still there after `wait`
    seconds. The kernel then lets go of its lock on the camera.

    Only the process that is still the guider is signalled: `start` is the
    pid_start from its state file, checked before each signal, so a pid
    since used by another process is never touched. Returns True once that
    guider is gone."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if process_start(pid) != start:
            return True                     # that guider has gone; the pid is not its any more
        try:
            os.kill(int(pid), sig)
        except ProcessLookupError:
            return True
        end = time.monotonic() + wait
        while time.monotonic() < end:
            if process_start(pid) != start:
                return True
            sleep(0.2)
    return process_start(pid) != start


# ------------------------------------------------- the heartbeat

class Heartbeat:
    """The state file, written by the loop whenever something changes and
    by a timer of its own every HEARTBEAT_S, whether or not a frame came
    in. The timer also watches the loop: if the loop has not moved for
    `stuck_after` seconds (the camera or a pulse hung inside the library),
    it writes `fault` and stops beating, so no reader takes a hung guider
    for a working one."""

    def __init__(self, base, stuck_after, path=None, say=print):
        self.path, self.stuck_after, self.say = path, stuck_after, say
        self.fields = dict(base)
        self.lock = threading.Lock()
        self.halt = threading.Event()
        self.moved = time.monotonic()
        self.thread = threading.Thread(target=self._beat, daemon=True, name="guide-heartbeat")

    def start(self):
        self.write()
        self.thread.start()
        return self

    def progress(self):
        self.moved = time.monotonic()

    def update(self, **fields):
        with self.lock:
            self.fields.update(fields, time=time.time())
        self.progress()
        self.write()

    def write(self):
        with self.lock:
            self.fields["heartbeat"] = time.time()
            write_state(self.fields, self.path)

    def _beat(self):
        while not self.halt.wait(HEARTBEAT_S):
            idle = time.monotonic() - self.moved
            if idle > self.stuck_after:
                with self.lock:
                    self.fields.update(state="fault", reason=f"the guide loop has not moved for {idle:.0f} s "
                                       "(the camera or a pulse hung)", time=time.time())
                try:
                    self.write()
                finally:
                    self.say(f"guiding stopped: the loop has not moved for {idle:.0f} s")
                return
            try:
                self.write()
            except OSError:
                pass

    def stop(self):
        self.halt.set()
        if self.thread.is_alive():
            self.thread.join(timeout=2 * HEARTBEAT_S)


def health(state, run=None, now=None):
    """Whether a state read from the file can be trusted: (True, "") or
    (False, why). A heartbeat older than STALE_S, a process that has gone,
    another run than the one expected, or `fault` all fail."""
    now = time.time() if now is None else now
    if not state:
        return False, "no guider state"
    if run is not None and state.get("run") != run:
        return False, f"the state is run {state.get('run')}'s, not {run}'s"
    if not alive(state.get("pid")):
        return False, f"the guider (process {state.get('pid')}) has gone"
    age = now - (state.get("heartbeat") or 0)
    if age > STALE_S:
        return False, f"the guider's heartbeat is {age:.0f} s old"
    if state.get("state") == "fault":
        return False, f"the guider is in fault: {state.get('reason')}"
    return True, ""


# ------------------------------------------------- orders

class StopRequested(Exception):
    """A stop order taken between pulses (calibration, its check, or the loop)."""

    def __init__(self, order):
        super().__init__("a stop order")
        self.order = order


def tell(order, args=(), run=None, folder=None, state_path=None):
    """An order for the running guider: a file of its own in ORDER_DIR,
    named by a random ID and naming the guider's run (the one in the state
    file unless `run` is given), so no order can overwrite another.
    Returns (id, run)."""
    if order not in ORDERS:
        raise interface.Refusal("INVALID_REQUEST", f"Unknown guider order '{order}'. Known: {', '.join(ORDERS)}")
    if run is None:
        state = read_state(state_path)
        ok, why = health(state)
        if not ok:
            raise Fault(f"No guider to tell: {why}.")
        run = state["run"]
    ident = uuid.uuid4().hex
    folder = folder or ORDER_DIR
    folder.mkdir(parents=True, exist_ok=True)
    scratch = folder / f"{ident}.tmp"
    scratch.write_text(json.dumps({"id": ident, "run": run, "order": order, "args": list(args),
                                   "at": time.time()}), encoding="utf-8")
    os.replace(scratch, folder / f"{ident}.order.json")
    return ident, run


def answer_order(order, done, why="", folder=None):
    """An order's result, in a file of its own beside it: written only once
    what it asked for is true."""
    folder = folder or ORDER_DIR
    result = {"id": order["id"], "run": order.get("run"), "order": order.get("order"),
              "outcome": "done" if done else "failed", "reason": why, "at": time.time()}
    scratch = folder / f"{order['id']}.result.tmp"
    scratch.write_text(json.dumps(result), encoding="utf-8")
    os.replace(scratch, folder / f"{order['id']}.result.json")
    (folder / f"{order['id']}.taken.json").unlink(missing_ok=True)
    return result


def wait_for(ident, run, timeout=None, order=None, state_path=None, folder=None, sleep=time.sleep):
    """The result of order `ident` sent to `run`. Only a result with both is
    accepted. A failed result, a guider that stops being healthy (or, for a
    stop, one that ends without answering), or the order's timeout is a
    Fault."""
    folder = folder or ORDER_DIR
    timeout = timeout or ORDER_TIMEOUT.get(order, 30)
    end = time.monotonic() + timeout
    path = folder / f"{ident}.result.json"
    while time.monotonic() < end:
        try:
            done = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            done = None
        if done and done.get("id") == ident and done.get("run") == run:
            if done.get("outcome") != "done":
                raise Fault(f"The guider's {done.get('order')} failed: {done.get('reason')}.")
            return done
        state = read_state(state_path)
        if order == "stop":
            if state and state.get("run") == run and not alive(state.get("pid")):
                raise Fault("The guider ended without answering the stop.")
        else:
            ok, why = health(state, run)
            if not ok:
                raise Fault(f"Waiting for the guider's {order or 'order'}: {why}.")
        sleep(0.2)
    raise Fault(f"The guider did not carry out {order or 'the order'} within {timeout:.0f} s.")


class OrderDesk:
    """The guider's side of the orders: each order file claimed once (by
    renaming it), in the order sent. One for another run, one sent before
    this guider started, or one older than ORDER_STALE_S is answered as
    failed, so its sender hears why rather than waiting."""

    def __init__(self, run, started=None, folder=None, say=print):
        self.run, self.started = run, started or time.time()
        self.folder, self.say = folder or ORDER_DIR, say
        self.folder.mkdir(parents=True, exist_ok=True)
        for old in self.folder.glob("*.result.json"):           # results nobody collected
            try:
                if time.time() - old.stat().st_mtime > 3600:
                    old.unlink()
            except OSError:
                pass

    def answer(self, order, done, why=""):
        answer_order(order, done, why, self.folder)
        self.say(f"  order {order.get('order')}: {'done' if done else 'failed'}" + (f" ({why})" if why else ""))

    def next(self, now=None):
        """The oldest order for this run waiting to be carried out, claimed,
        or None. One at a time: the rest stay unclaimed, and visible, until
        they can be handled."""
        now = time.time() if now is None else now
        found = []
        for path in self.folder.glob("*.order.json"):
            try:
                found.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        found.sort(key=lambda o: (o.get("at") or 0, o.get("id", "")))
        for order in found:
            source = self.folder / f"{order.get('id')}.order.json"
            claimed = self.folder / f"{order.get('id')}.taken.json"
            try:
                os.replace(source, claimed)          # claimed once, by one reader
            except OSError:
                continue
            if order.get("run") != self.run:
                self.answer(order, False, f"sent to run {order.get('run')}; this guider is run {self.run}")
            elif (order.get("at") or 0) < self.started:
                self.answer(order, False, "sent before this guider started")
            elif now - (order.get("at") or 0) > ORDER_STALE_S:
                self.answer(order, False, f"not taken within {ORDER_STALE_S:.0f} s")
            else:
                return order
        return None

    def close(self, why="the guider stopped"):
        """Every order still waiting when the guider ends gets an answer:
        failed, with why, so no sender waits on it until its timeout."""
        for path in self.folder.glob("*.order.json"):
            try:
                order = json.loads(path.read_text(encoding="utf-8"))
                os.replace(path, self.folder / f"{order.get('id')}.taken.json")
            except (OSError, ValueError):
                continue
            if order.get("run") == self.run:
                self.answer(order, False, why)
            else:                                   # not ours to answer: put it back
                os.replace(self.folder / f"{order.get('id')}.taken.json", path)

    def between_pulses(self, doing="calibrating"):
        """For calibration and its check, before every pulse: a stop ends it
        (StopRequested, answered by the caller once the pulses have stopped
        and the camera is let go); any other order is answered as failed."""
        while (order := self.next()) is not None:
            if order.get("order") == "stop":
                raise StopRequested(order)      # later orders stay unclaimed; close() answers them
            self.answer(order, False, f"{doing}: only stop is taken until guiding starts")


# ------------------------------------------------- the loop

def guide(cam, cols, cal, seconds=2.0, gain=None, minutes=None, one_way=None, say=print,
          state_path=None, log_folder=None, run_id=None, desk=None):
    """The closed loop, with its heartbeat and its orders. Finds a star,
    locks on it and keeps it there until `minutes` pass, a `stop` order,
    Ctrl-C or SIGTERM, or a fault. The state file has the heartbeat every
    second and everything else every frame; each frame is logged to
    guide-DATE.jsonl. The caller holds the camera (Ownership), and answers
    a stop order only once the camera is let go: this returns (the final
    state, the stop order or None)."""
    motion_check()
    run_id = run_id or uuid.uuid4().hex[:8]
    folder = log_folder or LOG_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    log = folder / f"guide-{datetime.now():%Y%m%d}.jsonl"
    ctl = Controller(cols, cal.get("backlash_s", 0.0), cal.get("backlash_spread_s", 0.0), seconds, one_way)
    stuck_after = 3 * seconds + 5 + RETRY_S + 2 * LONGEST_PULSE
    desk = desk or OrderDesk(run_id, say=say)
    beat = Heartbeat({"pid": os.getpid(), "pid_start": process_start(os.getpid()), "run": run_id,
                      "exposure": seconds, "state": "starting", "camera_held": True},
                     stuck_after, state_path, say)
    errors = deque(maxlen=RMS_FRAMES)
    lock, state, reason = None, "starting", ""
    answer = desk.answer

    def starting():
        beat.progress()
        desk.between_pulses("finding the guide star")

    def sigterm(signum, frame):
        raise KeyboardInterrupt

    try:
        previous = signal.signal(signal.SIGTERM, sigterm)
    except ValueError:            # not the main thread
        previous = None
    beat.start()
    resuming = stopping = None
    dithering = None                # a dither order not yet settled: {order, since, good}
    whole = [0.0, 0.0, 0]           # the whole run's squared RA and Dec errors, and how many
    frames = 0                      # guide frames taken: what a reader counts samples by
    try:
        star = first_star(cam, seconds, gain, say, tick=starting)
        lock = where = origin = (star.x, star.y)      # origin: where relock set it; dithers are offsets from it
        say(f"locked on the star at {lock[0]:.1f}, {lock[1]:.1f} (SNR {star.snr:.1f}); guiding")
        lost, state = 0, "guiding"
        beat.update(state=state, lock=list(lock))
        ended = time.monotonic() + minutes * 60 if minutes else None
        while (ended is None or time.monotonic() < ended) and stopping is None:
            beat.progress()
            while (order := desk.next()) is not None:
                name = order.get("order")
                if name == "stop":
                    stopping = order
                    break
                elif name == "pause":
                    cam.stop_pulse()                # no pulse can be running: they finish before this
                    state = "paused"
                    if dithering:                   # it cannot settle with no guide frames
                        answer(dithering["order"], False, "paused before it settled")
                        dithering = None
                    beat.update(state=state, pulses=[0.0, 0.0])
                    answer(order, True)
                elif name == "resume":
                    if state != "paused":
                        answer(order, False, f"not paused ({state})")
                    else:
                        state, lost, resuming = "guiding", 0, order
                        beat.update(state=state)
                elif name == "relock":
                    state = "relocking"
                    beat.update(state=state)
                    def relocking():
                        beat.progress()
                        desk.between_pulses("relocking")     # a stop is taken here too
                    try:
                        star = first_star(cam, seconds, gain, say, patience=RELOCK_PATIENCE, tick=relocking)
                    except StopRequested:
                        answer(order, False, "a stop came first")
                        raise
                    except Fault as why:
                        state = "lost"
                        beat.update(state=state)
                        answer(order, False, why.message)
                    else:
                        lock = where = origin = (star.x, star.y)
                        if dithering:
                            answer(dithering["order"], False, "a relock came before it settled")
                            dithering = None
                        ctl.reset_limits()
                        errors.clear()
                        lost, state = 0, "guiding"
                        beat.update(state=state, lock=list(lock), sent_arcsec=ctl.sent)
                        say(f"  relocked on the star at {lock[0]:.1f}, {lock[1]:.1f}")
                        answer(order, True)
                elif name == "dither":
                    # The lock moved to an offset from the origin (never from the
                    # last dither, so the field cannot wander); done once the
                    # star has settled on it.
                    try:
                        dx, dy = (float(v) for v in order.get("args", [])[:2])
                    except (TypeError, ValueError):
                        answer(order, False, "a dither needs DX and DY in guide pixels")
                        continue
                    if state != "guiding":
                        answer(order, False, f"not guiding ({state})")
                    elif math.hypot(dx, dy) > DITHER_MOST_PX:
                        answer(order, False, f"{math.hypot(dx, dy):.1f} px is past the {DITHER_MOST_PX:g} px a "
                                             "dither may go from the origin")
                    else:
                        if dithering:
                            answer(dithering["order"], False, "a newer dither came before it settled")
                        lock = (origin[0] + dx, origin[1] + dy)
                        dithering = {"order": order, "since": time.monotonic(), "good": 0}
                        beat.update(lock=list(lock), dither=[dx, dy])
                        say(f"  dither: lock moved {dx:+.2f}, {dy:+.2f} px from the origin")
                else:
                    answer(order, False, f"unknown order {name}")
            if stopping:
                break                       # no frame and no pulse after a stop
            if dithering and time.monotonic() - dithering["since"] > DITHER_SETTLE_MAX:
                answer(dithering["order"], False, f"not settled within {DITHER_SETTLE_MAX:.0f} s")
                dithering = None
            if state == "paused":
                time.sleep(0.5)
                continue
            frame, times = cam.timed_frame(seconds, gain)
            beat.progress()
            row = {"time": times, "state": state}
            looking = (lock, RELOCK_RADIUS) if state == "lost" else (where, WINDOW)
            found, why = follow(frame, looking[0], looking[1])
            if found and found.peak >= 250:
                found, why = None, "saturated"
            if found and state != "lost" and math.hypot(found.x - where[0], found.y - where[1]) > JUMP:
                found, why = None, f"jumped {math.hypot(found.x - where[0], found.y - where[1]):.1f} px"
            sent = (0.0, 0.0)
            if found is None:
                lost += 1
                row["rejected"] = why
                if lost >= LOST_FRAMES and state != "lost":
                    state = "lost"
                    if dithering:
                        answer(dithering["order"], False, f"the star was lost before it settled ({why})")
                        dithering = None
                    say(f"  star lost ({why}); no pulses; looking within {RELOCK_RADIUS} px of the lock")
                    if resuming:
                        answer(resuming, False, f"the star was not found after the pause ({why})")
                        resuming = None
            else:
                if state == "lost":
                    say("  star back; guiding")
                lost, state = 0, "guiding"
                where = (found.x, found.y)
                error = (found.x - lock[0], found.y - lock[1])
                sent, info = ctl.pulses(error)
                errors.append((info["ra_px"] * SCALE, info["dec_px"] * SCALE))
                whole[0] += (info["ra_px"] * SCALE) ** 2
                whole[1] += (info["dec_px"] * SCALE) ** 2
                whole[2] += 1
                pulsed = time.time()
                send(cam, sent)
                if resuming:
                    answer(resuming, True)
                    resuming = None
                if dithering:
                    near = math.hypot(*error) < DITHER_SETTLED_PX
                    dithering["good"] = dithering["good"] + 1 if near else 0
                    took = time.monotonic() - dithering["since"]
                    if dithering["good"] >= DITHER_SETTLED_FRAMES:
                        answer(dithering["order"], True, f"settled in {took:.0f} s")
                        row["dither_settled_s"] = round(took, 1)
                        dithering = None
                row.update(star={"x": round(found.x, 3), "y": round(found.y, 3), "snr": round(found.snr, 1),
                                 "hfd": round(found.hfd, 2), "peak": found.peak},
                           error_px=[round(error[0], 3), round(error[1], 3)],
                           ra_err=round(-info["ra_px"] * SCALE, 2), dec_err=round(-info["dec_px"] * SCALE, 2),
                           pulse_s=[round(sent[0], 3), round(sent[1], 3)], pulsed=pulsed,
                           delay_s=round(pulsed - times["mid"], 3), reversal=info["reversal"],
                           slack_share=info["slack_share"])
            rms = None
            if errors:
                e = np.array(errors)
                ra_rms, dec_rms = (float(np.sqrt(np.mean(e[:, k] ** 2))) for k in (0, 1))
                rms = {"ra": round(ra_rms, 2), "dec": round(dec_rms, 2), "total": round(math.hypot(ra_rms, dec_rms), 2)}
            row["state"] = state
            with log.open("a", encoding="utf-8") as f:
                f.write(json.dumps({**row, "run": run_id}) + "\n")
            frames += 1
            beat.update(state=state, lock=list(lock), star=row.get("star"), ra_err=row.get("ra_err"),
                        dec_err=row.get("dec_err"), rms=rms, pulses=list(sent), sent_arcsec=dict(ctl.sent),
                        rejected=row.get("rejected"), frame=frames, frame_mid=times["mid"])
            if found is not None:
                say(f"  RA {row['ra_err']:+5.1f}\" Dec {row['dec_err']:+5.1f}\"  pulses {sent[0]:+.2f} "
                    f"{sent[1]:+.2f} s" + (f"  RMS {rms['total']:.2f}\"" if rms else ""))
        state, reason = "stopped", ("a stop order" if stopping else "its time was up")
        guided_for = (time.monotonic() - (ended - minutes * 60)) / 60 if minutes else None
        if guided_for is not None and guided_for >= CHECK_MINUTES * 0.99 and whole[2]:
            ra, dec = (math.sqrt(whole[k] / whole[2]) for k in (0, 1))
            keep_check(guided_for, {"ra": round(ra, 2), "dec": round(dec, 2), "total": round(math.hypot(ra, dec), 2),
                                    "frames": whole[2]}, run_id)
    except StopRequested as stop:
        stopping = stop.order
        state, reason = "stopped", "a stop order"
    except interface.Refusal as fault:
        state, reason = "fault", fault.message
        say(f"guiding stopped: {reason}")
        raise
    except KeyboardInterrupt:
        state, reason = "stopped", "Ctrl-C or SIGTERM"
    except Exception as failure:            # anything else is a fault too, never left as "guiding"
        state, reason = "fault", f"{type(failure).__name__}: {failure}"
        say(f"guiding stopped: {reason}")
        raise
    finally:
        if state not in ("stopped", "fault"):
            state, reason = "fault", reason or "ended unexpectedly"
        beat.stop()
        try:
            cam.stop_pulse()
        except Exception as failure:
            say(f"  the ST4 stop failed too: {failure}")
        if dithering:
            try:
                answer(dithering["order"], False, "the guider stopped before it settled")
            except OSError:
                pass
        final = {"state": state, "reason": reason, "lock": list(lock) if lock else None, "pulses": [0.0, 0.0]}
        try:
            with beat.lock:
                beat.fields.update(final, time=time.time(), heartbeat=time.time())
                write_state(beat.fields, state_path)
        except Exception as failure:        # never hide the error that ended the loop
            say(f"  the final state could not be written: {failure}")
        if previous is not None:
            signal.signal(signal.SIGTERM, previous)
    return state, stopping


# ------------------------------------------------- shoot.py's side: a guided run

GUIDE_START_S = 480.0      # a new guider has this long to calibrate and reach `guiding`
RESTART_S = 180.0          # a restarted guider, its calibration reused, has this long
SETTLE_PX = 0.5            # guide px (about 5"): every error under this...
SETTLE_FRAMES = 2          # ...for this many guide frames running, spanning at least SETTLE_SPAN
SETTLE_SPAN = 3.0          # seconds
SETTLE_S = 30.0            # still guiding but not settled after this: the frame is taken and marked
LOST_WAIT_S = 300.0        # lost (cloud), relocking or calibrating this long: guided imaging stops
RUN_LOG = config.DATA / "cache" / "guide-run.log"
CHECK_FILE = config.DATA / "cache" / "guide-check.json"   # the last guiding check of 10 minutes or more
CHECK_MINUTES = 10
CHECK_RMS = 2.5            # arcsec total RMS: the first night's pass (docs/autoguiding.md, proof step 2)


def keep_check(minutes, rms, run, path=None):
    """A guiding run of CHECK_MINUTES or more, kept with its RMS, for the
    ladder to say before it starts."""
    path = path or CHECK_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"at": time.time(), "minutes": round(minutes, 1), "rms": rms, "run": run,
                                **light_path()}), encoding="utf-8")


def check_note(path=None, now=None):
    """What the last guiding check says, in a line: passed, failed, or
    none tonight (within 12 hours)."""
    now = time.time() if now is None else now
    try:
        check = json.loads((path or CHECK_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        check = None
    if not check or now - check.get("at", 0) > 12 * 3600:
        return (f"  guiding check: none tonight. The first night's order is {CHECK_MINUTES} minutes of "
                f"./guidecam.py guide --minutes {CHECK_MINUTES} under {CHECK_RMS}\" RMS before the ladder.")
    rms = (check.get("rms") or {}).get("total")
    verdict = "passed" if rms is not None and rms < CHECK_RMS else "NOT passed"
    return (f"  guiding check: {check['minutes']:g} minutes, {rms}\" RMS, "
            f"{(now - check['at']) / 3600:.1f} h ago: {verdict} (under {CHECK_RMS}\")")
MARGIN_S = 10.0            # guide frames this long before an imaging frame began are read for its coverage


class Supervisor:
    """What shoot.py --guide does with the guider: starts one (or uses one
    already guiding), pauses it around every GoTo and relocks after, keeps
    the Dec creep off while it guides, waits for it to settle before each
    frame, says how guiding went during each frame, and recovers from a
    fault once before stopping guided imaging. It never lets a guided run
    carry on unguided: every way it gives up is a Fault."""

    def __init__(self, exposure=2.0, say=print, popen=None, site=None):
        import subprocess
        self.exposure, self.say = exposure, say
        self.popen = popen or subprocess.Popen
        self.site = site
        self.run = self.pid = self.pid_start = None
        self.launched = False          # this run started it, so this run stops it
        self.active = False
        self.restarts = 0

    # -- the mount's Dec creep: off while the guider owns Dec

    def creep_off(self):
        import mount
        try:
            mount.Mount(watch=False).dec_creep(0)
        except (OSError, SystemExit) as problem:
            raise Fault(f"The Dec creep could not be turned off for guiding ({problem}).") from None

    def creep_back(self):
        import mount
        try:
            scope = mount.Mount(watch=False)
            if self.site:
                scope.apply_drift_correction(self.site)
        except (OSError, SystemExit, KeyError, ValueError) as problem:
            self.say(f"  guide: the Dec creep could not be put back ({problem})")

    # -- starting, and the guider's state

    def start(self):
        """A guider guiding, with the creep off. One already guiding (healthy)
        is used; otherwise one is started."""
        state = read_state()
        ok, _ = health(state)
        held = owner()
        if ok and held and held.get("role") == "guider" and state.get("state") in ("guiding", "paused"):
            self.run, self.pid, self.pid_start = state["run"], state["pid"], state.get("pid_start")
            self.say(f"  guide: using the guider already running (run {self.run})")
            self.active = True
            self.creep_off()
            self.order("relock")
            return
        self.creep_off()
        self.launch(GUIDE_START_S)

    def launch(self, timeout):
        import sys
        RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
        log = RUN_LOG.open("a", encoding="utf-8")
        proc = self.popen([sys.executable, str(config.ROOT / "guidecam.py"), "guide",
                           "--exposure", f"{self.exposure:g}"],
                          stdout=log, stderr=log, start_new_session=True)
        self.launched, self.pid = True, proc.pid
        self.say(f"  guide: guider started (process {proc.pid}); calibrating or checking its calibration")
        try:
            self._wait_guiding(proc, timeout)
        except BaseException:
            # A guider this run started and that did not reach guiding is
            # ended here, never left running behind a failed start.
            self.end_launched(proc)
            raise

    def end_launched(self, proc=None):
        """The guider this run launched, ended: a stop order if it can take
        one, else signalled (only if the pid is still that guider)."""
        state = read_state()
        ok, _ = health(state, self.run) if self.run else (False, "")
        if ok:
            try:
                ident, run = tell("stop", run=self.run)
                wait_for(ident, run, order="stop")
                return
            except interface.Refusal:
                pass
        start = self.pid_start if self.pid_start is not None else process_start(self.pid)
        if self.pid and start is not None:
            terminate(self.pid, start)
        if proc is not None:
            try:
                proc.wait(timeout=5)
            except Exception:
                pass

    def _wait_guiding(self, proc, timeout):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            state = read_state()
            if state and state.get("pid") == proc.pid:
                self.run, self.pid_start = state.get("run"), state.get("pid_start")
                if state.get("state") == "guiding":
                    self.active = True
                    self.say(f"  guide: guiding (run {self.run})")
                    return
                ok, why = health(state, self.run)
                if not ok or state.get("state") == "stopped":
                    raise Fault(f"The guider did not start guiding: {why or state.get('reason')}. "
                                f"Its log: {RUN_LOG}.")
            elif proc.poll() is not None:
                raise Fault(f"The guider ended before it started guiding. Its log: {RUN_LOG}.")
            time.sleep(1)
        raise Fault(f"The guider was not guiding within {timeout:.0f} s. Its log: {RUN_LOG}.")

    def order(self, name, args=()):
        ident, run = tell(name, args, run=self.run)
        return wait_for(ident, run, order=name)

    def dither(self, size_arcsec, rng):
        """The guider's lock moved a random way, between half and all of
        `size_arcsec` from where its last relock set it (never from the last
        dither, so the field cannot wander), and settled on: no GoTo.
        Returns (dx, dy) in guide pixels and the guider's word on settling."""
        size = size_arcsec / SCALE
        distance = size * (0.5 + 0.5 * rng.random())
        angle = rng.random() * 2 * math.pi
        dx, dy = distance * math.cos(angle), distance * math.sin(angle)
        done = self.order("dither", (round(dx, 3), round(dy, 3)))
        return (dx, dy), done.get("reason", "")

    # -- around a GoTo

    def before_move(self):
        """Paused, confirmed: no pulse goes while the mount slews."""
        if self.active:
            self.order("pause")

    def after_move(self):
        """The creep the GoTo set turned off again, and a new lock where the star now is."""
        if self.active:
            self.creep_off()
            self.order("relock")

    # -- before and during each frame

    def settle(self, sleep=time.sleep):
        """Waits until guiding has settled; True if it did, False if it was
        still guiding but not inside SETTLE_PX after SETTLE_S (the frame is
        taken and marked). lost, relocking or calibrating for LOST_WAIT_S, or
        a fault that a restart does not cure, is a Fault."""
        begun = time.monotonic()
        seen = []                         # (frame time, error in guide px) of guide frames since asked
        troubled = None                   # when it was last found not guiding
        while True:
            state = read_state()
            ok, why = health(state, self.run)
            if not ok:
                self.recover(why)
                begun, seen, troubled = time.monotonic(), [], None
                continue
            now = time.monotonic()
            if state.get("state") != "guiding":
                troubled = troubled or now
                if now - troubled > LOST_WAIT_S:
                    raise Fault(f"The guider has been {state.get('state')} for {LOST_WAIT_S / 60:.0f} minutes "
                                f"({state.get('rejected') or state.get('reason') or 'no star'}): guided imaging stops.")
            else:
                troubled = None
                # One sample per guide frame, by its number: a heartbeat, an
                # order's answer or a pause rewrites the file but is no new frame.
                number = state.get("frame")
                if number is not None and (not seen or seen[-1][0] != number):
                    if state.get("ra_err") is None or state.get("rejected"):
                        seen.append((number, None, state.get("frame_mid")))
                    else:
                        seen.append((number, math.hypot(state["ra_err"], state["dec_err"]) / SCALE,
                                     state.get("frame_mid")))
                recent = seen[-SETTLE_FRAMES:]
                if (len(recent) == SETTLE_FRAMES and all(e is not None and e < SETTLE_PX for _, e, _ in recent)
                        and recent[-1][2] - recent[0][2] >= SETTLE_SPAN * 0.99):
                    return True
                if now - begun > SETTLE_S:
                    return False
            sleep(0.3)

    def recover(self, why):
        """One restart in a run: the hung or failed guider ended (only if it is
        still that process), a new one started with the calibration reused,
        the creep off. A second fault, or a restart that does not reach
        guiding, is a Fault."""
        if self.restarts >= 1:
            raise Fault(f"The guider failed again ({why}): guided imaging stops.")
        self.restarts += 1
        self.say(f"  guide: {why}; restarting the guider once")
        if self.pid and self.pid_start is not None and not terminate(self.pid, self.pid_start):
            raise Fault(f"The guider (process {self.pid}) could not be ended: guided imaging stops.")
        self.active = False
        self.creep_off()
        self.launch(RESTART_S)

    def during(self, start, end):
        """How guiding went from `start` to `end` (UTC seconds): RMS and the
        largest error in arcseconds, and seconds without the star."""
        rows = []
        path = LOG_FOLDER / f"guide-{datetime.fromtimestamp(start):%Y%m%d}.jsonl"
        try:
            for line in path.read_text(encoding="utf-8").splitlines()[-2000:]:
                row = json.loads(line)
                mid = (row.get("time") or {}).get("mid", 0)
                # From a little before the frame began: a guide frame then
                # also covers the frame's first seconds.
                if row.get("run") == self.run and start - MARGIN_S <= mid <= end:
                    rows.append(row)
        except (OSError, ValueError):
            pass
        good = sorted((r["time"]["mid"], math.hypot(r["ra_err"], r["dec_err"]))
                      for r in rows if r.get("ra_err") is not None)
        inside = [r for r in rows if r["time"]["mid"] >= start]
        rejected = sum(1 for r in inside if r.get("ra_err") is None)
        errors = [e for t, e in good if t >= start]
        # The guider's own cycle (exposure, readout, pulses), from the spacing
        # of every frame it logged, good or not; the exposure plus a second
        # when there are too few to tell.
        mids = sorted((r.get("time") or {}).get("mid", 0) for r in rows)
        spacing = [b - a for a, b in zip(mids, mids[1:]) if b > a]
        cycle = float(np.median(spacing)) if len(spacing) >= 2 else self.exposure + 1.0
        # Each good guide frame covers its own cycle, centred on its midpoint.
        # Lost: every part of the frame no good guide frame covered, a
        # rejected frame and one that never came alike, counted in full.
        # The last cycle is left out: the guide frame being taken as the frame
        # ends is not logged yet, and the guider's state at the end judges it.
        judged_to = max(start, end - cycle)
        covered = 0.0
        edge = start
        for t, _ in good:
            lo, hi = max(t - cycle / 2, edge, start), min(t + cycle / 2, judged_to)
            if hi > lo:
                covered += hi - lo
                edge = hi
        span = max(judged_to - start, 1e-9)
        lost = max(0.0, span - covered) if judged_to > start else 0.0
        state = read_state()
        ok, why = health(state, self.run)
        if ok and state.get("state") != "guiding":
            ok, why = False, f"the guider was {state.get('state')} at the frame's end"
        if ok and not errors:
            ok, why = False, "no guide frame during it"
        if ok and rejected:
            ok, why = False, f"{rejected} guide frame(s) without the star during it"
        if ok and lost > 0.5 * cycle:
            ok, why = False, f"{lost:.0f} s of it with no good guide frame"
        # A frame shorter than two guide cycles has no stretch to judge
        # coverage over: none is given, and GUIDED rests on a good guide frame
        # inside it, none rejected, and guiding at its end.
        coverage = round(covered / span, 3) if end - start >= 2 * cycle else None
        return {"rms": round(float(np.sqrt(np.mean(np.square(errors)))), 2) if errors else None,
                "max": round(max(errors), 2) if errors else None,
                "lost_s": round(lost, 1), "rejected": rejected, "coverage": coverage,
                "frames": len(rows), "guided": ok, "why": why}

    def stop(self):
        """The guider stopped if this run started it, and the creep put back.
        One this run found running is left guiding, the creep left off."""
        if not self.launched:
            return
        try:
            self.end_launched()          # whether or not it ever reached guiding
        finally:
            self.active = False
            self.creep_back()
