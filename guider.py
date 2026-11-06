"""Autoguiding through the guide camera's ST4 lead (docs/autoguiding.md):
finding and following a guide star, calibrating which way each ST4
direction moves it, and the loop that keeps it on its lock position.

    ./guidecam.py star        find a star and follow it, no pulses
    ./guidecam.py calibrate   pulse each way and learn what each does
    ./guidecam.py guide       guide: calibration reused or made, then the loop

Built so far: the star, the calibration and the closed loop (the spec's
first three stages). Not yet: one guider owning the camera, the heartbeat
on its own timer, the numbered orders, and shoot.py --guide.

The guide scope is the 50 mm Orion Mini (162 mm) with the GPCAM's 3.75 um
pixels: 4.77" a pixel. The guide rate is the handset's, measured on
6 November 2026 at about 7.1"/s; a calibration replaces it with its own.
"""
import json
import math
import os
import time
import uuid
from collections import deque, namedtuple
from datetime import datetime, timezone

import numpy as np
from scipy import ndimage

import config
import guidemath
import interface

FOCAL_MM = 162.0
PIXEL_UM = 3.75
SCALE = 206.265 * PIXEL_UM / FOCAL_MM     # arcseconds a guide pixel: 4.77
GUIDE_RATE = 7.1                          # "/s, measured 6 Nov 2026; a calibration's own replaces it

# Finding the star
SATURATED = 230      # a peak this high or more may be clipped: not chosen
EDGE = 30            # px from the frame's edge
NEIGHBOUR = 15       # px: no brighter star nearer than this
SNR_FIND = 10        # to be chosen
SNR_LOST = 6         # below this while guiding, the star counts as lost
HFD_LEAST = 0.7      # px: narrower is a hot pixel, not a star
BOX = 10             # half-width of the box a star is measured in
AMBIGUOUS = 2.0      # px: two stars this close in distance from where the star should be: neither taken
WINDOW = 20          # half-width of the search window round where the star should be
RELOCK_RADIUS = 10   # px from the lock a lost star must come back within
JUMP = 8             # px in one frame: a satellite, a bird or a cosmic ray
LOST_FRAMES = 3      # frames running without the star: lost
RETRY_S = 10         # seconds between looks for a star when there is none

# Calibration
CAL_DISTANCE = 25    # px each leg aims to move the star
CAL_STEPS = 12       # steps the leg is planned in
CAL_MOST_STEPS = 15
CAL_LEAST_STEPS = 8  # fewer than this to cover the distance: steps too long
CAL_LONGEST_MS = 3000
CAL_SLACK_STEPS = 10  # most steps north before the Dec slack counts as taken up
CAL_REVERSAL_STEPS = 6  # steps of each extra Dec reversal that measures the slack again
VERIFY_STEPS = 3     # steps each way of the check on a reused calibration
VERIFY_ANGLE = 30    # degrees a reused direction may be off
VERIFY_SIZE = 0.35   # share a reused strength may be off
RETURN_PX = 2.0      # px from where it started a check's way back must end

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
ERROR_FAULT_PX = 30
ERROR_FAULT_FRAMES = 5
CORRECTION_FAULT = 600.0   # arcseconds of signed correction on an axis since the lock was set
RUNAWAY_FRAMES = 10        # frames running at the longest pulse the same way

STATE_FILE = config.DATA / "cache" / "guide.json"
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
    return {"camera": guidecam.MODEL, "focal_mm": round(FOCAL_MM)}


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
            and math.hypot(stars[1][1].x - stars[0][1].x, stars[1][1].y - stars[0][1].y) > 2:
        return None, (f"two stars about as near ({stars[0][0]:.1f} and {stars[1][0]:.1f} px): "
                      "not guessing which")
    return stars[0][1], ""


def first_star(cam, seconds, gain=None, say=print, patience=300.0, sleep=time.sleep):
    """A star to guide on, looking every RETRY_S seconds for up to `patience`
    seconds (cloud passes)."""
    began = time.monotonic()
    while True:
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

    def __init__(self, cam, seconds, gain=None, say=print):
        self.cam, self.seconds, self.gain, self.say = cam, seconds, gain, say
        self.where = None

    def look(self):
        frame, _ = self.cam.timed_frame(self.seconds, self.gain)
        star, why = follow(frame, self.where)
        if star is None:
            raise Fault(f"The star was lost during calibration: {why}.")
        self.where = (star.x, star.y)
        return self.where

    def step(self, direction, seconds):
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
    if moved < 5:
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


def calibrate(cam, seconds, dec, west, gain=None, say=print, rate=GUIDE_RATE):
    """Stage 2: west and back east, then north and back south (the Dec
    slack taken up first), then two short Dec reversals to measure the
    slack again. Returns the calibration (also kept in CAL_FILE)."""
    motion_check()
    ra_step, dec_step = step_seconds(dec, rate)
    say(f"calibrating at Dec {dec:+.1f}, {'west' if west else 'east'} of the pier: steps of "
        f"{ra_step * 1000:.0f} ms in RA, {dec_step * 1000:.0f} ms in Dec")
    star = first_star(cam, seconds, gain, say)
    c = Calibrator(cam, seconds, gain, say)
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
        if math.hypot(here[0] - start[0], here[1] - start[1]) >= 1.5:
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
    # Warnings only: the calibration measured what the mount does, and that is what is used.
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
    }
    say(f"  camera angle {angle:.1f} deg, axes {between:.1f} deg apart, guide rate RA {ra_rate:.1f}\"/s, "
        f"Dec {dec_rate:.1f}\"/s")
    for note in notes:
        say(f"  warning: {note}")
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
    if {k: cal.get(k) for k in light_path()} != light_path():
        return None, "made with another guide camera or scope"
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


def verify(cam, seconds, cal, cols, west, gain=None, say=print):
    """The check on a reused calibration: VERIFY_STEPS steps west and back,
    north and back. Each must go the way the columns say, within
    VERIFY_ANGLE degrees and VERIFY_SIZE of the strength. Across the pier
    with Dec not yet known, a north move exactly reversed is recorded as
    what this mount does, once its strength has matched too. The way back
    is checked as well: RA must return within RETURN_PX of where it
    started, Dec within the measured slack's worth plus RETURN_PX. Returns
    (True, "") or (False, why)."""
    ra_step, dec_step = (cal["step_ms"]["ra"] / 1000, cal["step_ms"]["dec"] / 1000)
    star = first_star(cam, seconds, gain, say)
    c = Calibrator(cam, seconds, gain, say)
    c.where = (star.x, star.y)
    results = {}
    for direction, step in (("west", ra_step), ("north", dec_step)):
        start = c.look()
        if direction == "north":                    # the slack first, as in calibration
            for _ in range(CAL_SLACK_STEPS):
                here = c.step("north", dec_step)
                if math.hypot(here[0] - start[0], here[1] - start[1]) >= 1.5:
                    break
            start = c.look()
        end = c.back(direction, step, VERIFY_STEPS)[-1]
        home = c.back(OPPOSITE[direction], step, VERIFY_STEPS)[-1]
        results[direction] = np.subtract(end, start) / (VERIFY_STEPS * step)
        missed = math.hypot(home[0] - start[0], home[1] - start[1])
        allowed = RETURN_PX + (cal.get("backlash_s", 0.0) * float(np.hypot(*cols["north"]))
                               if direction == "north" else 0.0)
        if missed > allowed:
            return False, (f"{OPPOSITE[direction]} did not bring the star back: {missed:.1f} px from where "
                           f"it started, more than {allowed:.1f}")
    for direction, got in results.items():
        want = cols[direction]
        strength, expected = float(np.hypot(*got)), float(np.hypot(*want))
        if abs(strength / max(expected, 1e-9) - 1) > VERIFY_SIZE:
            return False, f"{direction} moved the star {strength:.2f} px/s against {expected:.2f}"
        off = math.degrees(math.acos(np.clip(np.dot(got, want) / max(strength * expected, 1e-9), -1, 1)))
        if direction == "north" and west != cal["west"] and cal.get("dec_after_flip") is None:
            what = "same" if off < VERIFY_ANGLE else "negated" if off > 180 - VERIFY_ANGLE else None
            if what is None:
                return False, f"north went {off:.0f} degrees from either way it could"
            cal["dec_after_flip"] = what
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
    scratch = path.with_suffix(".tmp")
    scratch.write_text(json.dumps(state), encoding="utf-8")
    os.replace(scratch, path)


def send(cam, seconds):
    """The pulses, RA then Dec, the second only once the first has ended
    (GuideCamera.pulse returns only then), the motion lock checked before
    each."""
    for (plus, minus), s in zip((("west", "east"), ("north", "south")), seconds):
        if abs(s) >= 0.01:
            motion_check()
            cam.pulse(plus if s > 0 else minus, abs(s))


def guide(cam, cols, cal, seconds=2.0, gain=None, minutes=None, one_way=None, say=print,
          state_path=None, log_folder=None):
    """Stage 3: the closed loop. Finds a star, locks on it and keeps it
    there until `minutes` pass, Ctrl-C, or a fault. The state file is
    written every frame and each frame is logged to guide-DATE.jsonl."""
    motion_check()
    run_id = uuid.uuid4().hex[:8]
    folder = log_folder or LOG_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    log = folder / f"guide-{datetime.now():%Y%m%d}.jsonl"
    ctl = Controller(cols, cal.get("backlash_s", 0.0), cal.get("backlash_spread_s", 0.0), seconds, one_way)
    base = {"pid": os.getpid(), "run": run_id, "exposure": seconds}
    errors = deque(maxlen=RMS_FRAMES)
    star = first_star(cam, seconds, gain, say)
    lock = where = (star.x, star.y)
    say(f"locked on the star at {lock[0]:.1f}, {lock[1]:.1f} (SNR {star.snr:.1f}); guiding")
    lost, state, reason = 0, "guiding", ""
    ended = time.monotonic() + minutes * 60 if minutes else None
    try:
        while ended is None or time.monotonic() < ended:
            frame, times = cam.timed_frame(seconds, gain)
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
                    say(f"  star lost ({why}); no pulses; looking within {RELOCK_RADIUS} px of the lock")
            else:
                if state == "lost":
                    say("  star back; guiding")
                lost, state = 0, "guiding"
                where = (found.x, found.y)
                error = (found.x - lock[0], found.y - lock[1])
                sent, info = ctl.pulses(error)
                errors.append((info["ra_px"] * SCALE, info["dec_px"] * SCALE))
                pulsed = time.time()
                send(cam, sent)
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
            write_state({**base, "state": state, "time": time.time(), "lock": list(lock),
                         "star": row.get("star"), "ra_err": row.get("ra_err"), "dec_err": row.get("dec_err"),
                         "rms": rms, "pulses": list(sent), "sent_arcsec": ctl.sent}, state_path)
            if found is not None:
                say(f"  RA {row['ra_err']:+5.1f}\" Dec {row['dec_err']:+5.1f}\"  pulses {sent[0]:+.2f} "
                    f"{sent[1]:+.2f} s" + (f"  RMS {rms['total']:.2f}\"" if rms else ""))
        state = "stopped"
    except interface.Refusal as fault:
        state, reason = "fault", fault.message
        say(f"guiding stopped: {reason}")
        raise
    except KeyboardInterrupt:
        state, reason = "stopped", "Ctrl-C"
    except Exception as failure:            # anything else is a fault too, never left as "guiding"
        state, reason = "fault", f"{type(failure).__name__}: {failure}"
        say(f"guiding stopped: {reason}")
        raise
    finally:
        if state not in ("stopped", "fault"):
            state, reason = "fault", reason or "ended unexpectedly"
        try:
            cam.stop_pulse()
        except Exception as failure:
            say(f"  the ST4 stop failed too: {failure}")
        try:
            write_state({**base, "state": state, "reason": reason, "time": time.time(), "lock": list(lock)},
                        state_path)
        except Exception as failure:        # never hide the error that ended the loop
            say(f"  the final state could not be written: {failure}")
    return state
