"""Focus again during an imaging run, between frames, when the stars have
widened or the tube's temperature has moved (shoot.py).

19 November 2026: focus crept outward about 6 half-steps a minute, and
nothing put it back until the next filter change. On 20 November the same
filter's focus moved about 80 half-steps for each °C the focuser cooled.

What it does to a night:

- Framing: the mount is not moved, and guiding carries on.
- The sensor: only with the camera keeper holding it, so it stays cold.
- Minutes: a motor focus took 80 to 200 s on 20 and 21 November, and one
  comes at most every AT_MOST_S.
- The mount's safety: nothing here sends the mount anything.

`./focus.py --auto --only-if-better` does the focusing: a focus that does not
end sharper than it began goes back to where it started. A focus that fails
with the drawtube's place unknown stops the run (REFOCUS_NEEDED), as a filter
change's does, so no frames are kept at a focus nobody knows.

Runs measuring brightness over time are left alone (--hold, and the patrols
and star watches, which pass --no-refocus): a focus change part way through
would change the stars' shape in the middle of their light curve.

The figures are first estimates. WIDER is from 67 kept runs of 16 s or
longer: at 1.15 six would have fired, at 1.25 three (M31-P1, M31-P8, M33).
"""
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

import config

ROOT = Path(__file__).parent

WIDER = 1.25            # the stars this many times the width they began at
BASE_FRAMES = 5         # frames after a focus that say what the width was
RECENT_FRAMES = 4       # newest frames, whose median is compared with it
STARS_KEPT = 0.6        # fewer stars than this share of the start is cloud, not focus
ROUND_KEPT = 0.9        # rounder than this share of the start, or it is trailing, not focus
COOLER_C = 1.0          # °C the focuser's thermistor has moved since the last focus
AT_MOST_S = 1200        # never two in-run focuses closer than this
TEMPERATURE_S = 600     # how often the thermistor is read, between frames
LOG_FRESH_S = 6 * 3600  # a focus logged this recently is the one the temperature counts from
TIMEOUT_S = 600         # a focus still going after this is stopped
TERM_WAIT_S = 60        # and killed if it has not ended this long after


def blocked(args):
    """Why this run does not refocus itself, or None."""
    import camera
    if getattr(args, "no_refocus", False):
        return "--no-refocus"
    if config.DEMO:
        return "the demo has no pretend focuser"      # it would turn the real one
    if getattr(args, "hold", None):
        return "--hold keeps the stars on the same pixels for photometry"
    if getattr(args, "focus_fixed", None):
        return "--focus-as-is"
    if getattr(args, "block_frames", None):
        return "the sub-length ladder compares its frames' stars"
    if not camera.kept():
        return "the camera keeper is not holding the camera, so a focus could let the sensor warm"
    import focuser
    try:
        focuser.find_port()
    except (Exception, SystemExit):
        return "no motor focuser found"
    return None


def start(args, say=print):
    """A Watch for this run, or None, said either way."""
    why = blocked(args)
    if why:
        say(f"  focus during the run: off ({why})", flush=True)
        return None
    say(f"  focus during the run: on (stars {WIDER:g} times wider, or the focuser {COOLER_C:g} °C from its last "
        f"focus; at most every {AT_MOST_S / 60:.0f} min)", flush=True)
    return Watch()


def temperature():
    """The focuser's thermistor in °C, or None. Opening the port restarts the
    Nano, which is harmless between moves: its driver is off then anyway."""
    import focuser
    try:
        motor = focuser.Focuser.open(full=False, ms=0)
    except (Exception, SystemExit):
        return None
    try:
        return motor.temperature()
    except Exception:
        return None
    finally:
        motor.close()


def last_focus(now=None):
    """(when, °C) of the newest motor focus logged lately, or (None, None)."""
    import focus
    now = time.time() if now is None else now
    try:
        lines = focus.FOCUS_LOG.read_text(encoding="utf-8").strip().splitlines()
        line = json.loads(lines[-1])
    except (OSError, ValueError, IndexError):
        return None, None
    when = line.get("time")
    if not when or now - when > LOG_FRESH_S:
        return None, None
    return when, line.get("focuser_c")


def widened(log, wider=WIDER):
    """Why the newest frames in `log` (a run's entries since the last focus)
    say focus has gone, or None. Rejected frames count, since the frames that
    have gone softest are the ones rejected; frames with few stars or
    elongated ones do not say anything about focus."""
    frames = [e for e in log if e.get("fwhm") and e.get("stars")]
    if len(frames) < BASE_FRAMES + RECENT_FRAMES:
        return None
    first, last = frames[:BASE_FRAMES], frames[-RECENT_FRAMES:]

    def middle(rows, key):
        values = [r[key] for r in rows if r.get(key) is not None]
        return statistics.median(values) if values else None

    began, now = middle(first, "fwhm"), middle(last, "fwhm")
    if now < wider * began or middle(last, "stars") < STARS_KEPT * middle(first, "stars"):
        return None
    round_then, round_now = middle(first, "roundness"), middle(last, "roundness")
    if round_then and round_now and round_now < ROUND_KEPT * round_then:
        return None
    return f"the stars have widened from {began:.1f} to {now:.1f} px"


class Watch:
    """Whether this run should focus again, asked after each frame."""

    def __init__(self, read=temperature, clock=time.time):
        self.read, self.clock = read, clock
        self.focused, self.focused_c = last_focus(clock())
        self.since = 0              # the log's length at the last focus
        self.read_at = 0.0
        self.why = None
        if self.focused is None:
            self.focused = clock()  # no focus logged lately: the run's start is the first chance to judge from

    def due(self, log):
        if self.why:
            return True
        now = self.clock()
        if now - self.focused < AT_MOST_S:
            return False
        self.why = widened(log[self.since:])
        if not self.why and now - self.read_at >= TEMPERATURE_S:
            self.read_at = now
            degrees = self.read()
            if degrees is not None:
                if self.focused_c is None:
                    self.focused_c = degrees
                elif abs(degrees - self.focused_c) >= COOLER_C:
                    self.why = f"the focuser has gone from {self.focused_c:.1f} to {degrees:.1f} °C"
        return bool(self.why)

    def done(self, log, focused=True):
        """After a focus: judged afresh from the next frames. One that found
        nothing better waits its turn too, so a soft night is not refocused
        frame after frame."""
        self.why, self.since, self.focused = None, len(log), self.clock()
        if focused:
            self.focused_c = self.read()


def focus_now(stop, say=print):
    """./focus.py --auto --only-if-better, waited for, with `stop()` asked
    every couple of seconds. Returns ("better" | "left" | "stopped" | "failed",
    words): "left" is the focuser where it began."""
    import focuser

    def place():
        kept = focuser.position()
        return kept["position"] if kept else None

    before = place()
    child = subprocess.Popen([sys.executable, str(ROOT / "focus.py"), "--auto", "--only-if-better", "--json"],
                             stdout=subprocess.PIPE, text=True, cwd=ROOT)
    deadline, ended, killed_at = time.monotonic() + TIMEOUT_S, None, None
    while True:
        try:
            out, _ = child.communicate(timeout=2)
            break
        except subprocess.TimeoutExpired:
            if ended is None and (stop() or time.monotonic() > deadline):
                ended = "stopped" if time.monotonic() <= deadline else "timed out"
                killed_at = time.monotonic() + TERM_WAIT_S
                child.terminate()
            elif killed_at and time.monotonic() > killed_at:
                child.kill()
    if ended == "stopped":
        return "stopped", "told to stop during the focus"
    if ended:
        return "failed", f"the focus did not finish in {TIMEOUT_S / 60:.0f} minutes"
    try:
        answer = json.loads(out)
    except ValueError:
        answer = {"ok": False, "errors": [{"code": "INTERNAL_ERROR", "message": "the focus gave no answer"}]}
    if answer.get("ok"):
        data = answer.get("data") or {}
        if data.get("kept"):
            return "better", f"HFR {data.get('start_hfr')} to {data.get('ended_hfr')}"
        return "left", data.get("why") or "no sharper than it began"
    problem = (answer.get("errors") or [{}])[0].get("message", "the focus failed")
    now = place()
    if before is not None and now == before:
        return "left", problem
    return "failed", problem
