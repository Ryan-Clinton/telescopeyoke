"""Making the best of a mount that is not polar aligned.

A polar axis that misses the pole makes the aim slide in declination at a
rate that depends only on the hour angle:

    drift = A·cos(H) + B·sin(H)        arcseconds per second

where A comes from the axis pointing east or west of the pole and B from it
pointing too high or too low. So the drift can be predicted anywhere in the
sky from the polar error (polaralign.py measures it) or learned from drift
measurements at two or more hour angles, and cancelled by creeping the Dec
motor the other way. This module is the arithmetic; mount.py and shoot.py
do the measuring and the moving.

It does not make a rough alignment good: the field still turns slowly about
the target, which the stacker's rotation alignment takes care of, and the
gears' own periodic error is untouched. It is drift assist, not guiding.
"""
import json
import math
import time
from pathlib import Path

import config

import numpy as np

ROOT = Path(__file__).parent
MODEL_FILE = config.DATA / "cache" / "drift_model.json"
SIDEREAL = 15.041          # arcseconds of sky per second of time
AGGRESSIVENESS = 0.7       # share of a measured error corrected in one go
DEADBAND = 0.15            # arcsec/s of leftover drift not worth chasing
MIN_SPREAD = 15.0          # degrees of hour angle needed to fit both terms


def polar_terms(azimuth, altitude_error, latitude):
    """(A, B) for an axis `azimuth` degrees east of north and
    `altitude_error` degrees too high."""
    return (SIDEREAL * math.radians(azimuth) * math.cos(math.radians(latitude)),
            SIDEREAL * math.radians(altitude_error))


def polar_error(a, b, latitude):
    """The polar error (azimuth east of north, altitude too high) in degrees
    that would cause drift terms (A, B): drift alignment in reverse."""
    return (math.degrees(a / SIDEREAL) / math.cos(math.radians(latitude)),
            math.degrees(b / SIDEREAL))


def drift_at(terms, hour_angle):
    a, b = terms
    h = math.radians(hour_angle)
    return a * math.cos(h) + b * math.sin(h)


def fit_terms(observations):
    """Least-squares (A, B) from observations with "ha" (degrees), "rate" and
    "sigma" (arcsec/s). Needs hour angles spread over MIN_SPREAD degrees."""
    ha = np.radians([o["ha"] for o in observations])
    weights = 1 / np.maximum([o.get("sigma") or 0.1 for o in observations], 0.03)
    design = np.column_stack([np.cos(ha), np.sin(ha)]) * weights[:, None]
    (a, b), *_ = np.linalg.lstsq(design, np.array([o["rate"] for o in observations]) * weights,
                                 rcond=None)
    return float(a), float(b)


def line_fit(times, values):
    """Slope of values against times and its uncertainty (both per second).
    With only two points there is no scatter to judge by, so the uncertainty
    comes back as None."""
    t = np.asarray(times, dtype=float) - times[0]
    v = np.asarray(values, dtype=float)
    slope, intercept = np.polyfit(t, v, 1)
    if len(t) < 3:
        return float(slope), None
    scatter = np.sqrt(((v - (slope * t + intercept)) ** 2).sum() / (len(t) - 2))
    return float(slope), float(scatter / np.sqrt(((t - t.mean()) ** 2).sum()))


def drift_from_shifts(times, shifts, cd):
    """Dec drift (arcsec/s) and its uncertainty from how far successive
    frames had to be shifted to line up with the first.

    `shifts` are the stacker's (x, y) shifts in pixels and `cd` is the plate
    solution's matrix of degrees of sky per pixel. A frame that has to be
    shifted by t to match the reference was aimed t pixels away from it, so
    the row of `cd` for north-south turns the shifts into Dec offsets."""
    shifts = np.asarray(shifts, dtype=float)
    dec = (cd[1][0] * shifts[:, 0] + cd[1][1] * shifts[:, 1]) * 3600
    return line_fit(times, dec)


def creep_effect(creep, west):
    """What a Dec-axis creep does to the declination the scope points at.
    With the tube over the pole (west side) raising the axis lowers the Dec."""
    return -creep if west else creep


def creep_for(drift, west):
    """The Dec-axis creep that cancels a drift in pointing."""
    return drift if west else -drift


def next_creep(current, residual, sigma, west):
    """The creep to use next, given the drift still left over.

    Follows a guider's habits: ignore what is within the deadband or the
    measurement's own uncertainty; correct only part of the error at a time;
    and do not reverse the Dec motor, whose gears have slack, unless the
    error is too big to be an overshoot. Returns (creep, what was decided)."""
    if abs(residual) <= DEADBAND:
        return current, "within the deadband; left alone"
    if sigma is not None and abs(residual) < 2 * sigma:
        return current, "not clearly different from zero; left alone"
    wanted = current + AGGRESSIVENESS * creep_for(residual, west)
    if current != 0 and wanted * current < 0:
        if abs(residual) < 3 * DEADBAND:
            return 0.0, "overshot slightly; creep stopped rather than reversed"
        return wanted, "reversed: the drift has changed direction"
    return wanted, "adjusted"


def response(rows, west):
    """What a sweep of the Dec motor's creep showed. `rows` are
    {"creep", "drift"} in arcseconds per second: the creep set, and the Dec
    drift then measured, several times at each creep. A straight line is
    put through them:

        drift = natural + per_unit x creep

    `per_unit` should be creep_effect(1, west): +1 or -1. `repeat_scatter`
    is how far repeats at one creep sit from each other, and `off_line` how
    far the worst creep's average sits from the line. Where that is more
    than the repeats can explain, the motor is not answering in proportion
    (slack in the gears, a dead zone, a rate the handset rounds away), and
    `straight` is False. Nothing here changes how the creep is chosen: it
    is a measurement to be looked at first."""
    creeps, drifts = np.array([r["creep"] for r in rows], float), np.array([r["drift"] for r in rows], float)
    if len(set(creeps)) < 2:
        return None
    per_unit, natural = np.polyfit(creeps, drifts, 1)
    groups = {c: drifts[creeps == c] for c in sorted(set(creeps))}
    within = [g - g.mean() for g in groups.values() if len(g) > 1]
    freedom = sum(len(g) - 1 for g in within)
    scatter = float(np.sqrt(sum((g ** 2).sum() for g in within) / freedom)) if freedom else None
    off = max(abs(float(g.mean()) - (natural + per_unit * c)) for c, g in groups.items())
    fewest = min(len(g) for g in groups.values())
    allowed = max(DEADBAND, 3 * scatter / np.sqrt(fewest)) if scatter is not None else DEADBAND
    return {"natural_arcsec_s": round(float(natural), 3), "per_unit": round(float(per_unit), 3),
            "expected_per_unit": creep_effect(1.0, west), "repeat_scatter_arcsec_s": scatter and round(scatter, 3),
            "off_line_arcsec_s": round(off, 3), "straight": bool(off <= allowed),
            "by_creep": [{"creep": float(c), "drift": round(float(g.mean()), 3), "measurements": len(g)}
                         for c, g in groups.items()]}


def exposure_limit(residual, blur=2.0, ceiling=10.0):
    """Longest exposure, in seconds, before leftover drift smears a star by
    `blur` arcseconds. Capped, because the gears' periodic error takes over."""
    return ceiling if abs(residual) < blur / ceiling else min(ceiling, blur / abs(residual))


class Model:
    """What has been learned about this setup's drift since the handset was
    last set up: the polar error if measured, drift observations, and the
    creep now running."""

    def __init__(self, path=MODEL_FILE, latitude=None):
        self.path, self.latitude = Path(path), latitude
        self.polar, self.observations, self.creep = None, [], None
        if self.path.exists():
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            self.polar = saved.get("polar")
            self.observations = saved.get("observations", [])
            self.creep = saved.get("creep")

    def save(self):
        self.path.parent.mkdir(exist_ok=True)
        self.path.write_text(json.dumps({"polar": self.polar, "observations": self.observations,
                                         "creep": self.creep, "saved": time.time()}, indent=1), encoding="utf-8")

    def forget(self):
        """Start again: the mount has been moved or re-aligned."""
        self.polar, self.observations, self.creep = None, [], None
        self.path.unlink(missing_ok=True)

    def observe(self, hour_angle, dec, rate, sigma=None):
        """Record the natural (uncompensated) Dec drift at a sky position."""
        self.observations.append({"ha": hour_angle, "dec": dec, "rate": rate,
                                  "sigma": sigma, "time": time.time()})
        self.save()

    def set_polar(self, azimuth, altitude_error):
        self.polar = {"azimuth": azimuth, "altitude": altitude_error}
        self.save()

    def terms(self):
        """Best available (A, B), or None if nothing is known yet."""
        hour_angles = [o["ha"] for o in self.observations]
        if len(hour_angles) >= 2 and max(hour_angles) - min(hour_angles) >= MIN_SPREAD:
            return fit_terms(self.observations)
        if self.polar and self.latitude is not None:
            return polar_terms(self.polar["azimuth"], self.polar["altitude"], self.latitude)
        return None

    def predict(self, hour_angle):
        """Expected natural Dec drift at an hour angle (degrees), or None.
        With observations too close together to separate the two terms, the
        nearest one within 20 degrees is used as it stands."""
        terms = self.terms()
        if terms:
            return drift_at(terms, hour_angle)
        near = [o for o in self.observations if abs(o["ha"] - hour_angle) <= 20]
        if near:
            return min(near, key=lambda o: abs(o["ha"] - hour_angle))["rate"]
        return None
