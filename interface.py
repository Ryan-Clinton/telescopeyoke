"""The machine-readable side of telescopeyoke: one envelope for every JSON
answer, error codes that mean the same thing everywhere, and the fixed sets
of states things can be in.

People read the commands' ordinary output. Programs and language models ask
for --json and get this instead; its shape is described in schemas/ and only
changes with SCHEMA_VERSION.
"""
import contextlib
import json
import sys
from datetime import datetime, timezone

SCHEMA_VERSION = "1.0"

# Every way a command can refuse or fail, with whether trying again unchanged
# could work, and what to try instead.
ERRORS = {
    "MOTION_LOCKED": (False, "A MOTION_LOCKED file blocks all movement; a person must remove it."),
    "HANDSET_NOT_ANSWERING": (True, "Check the handset is on, past its start-up screens, and the lead is in."),
    "HANDSET_NOT_SET_UP": (False, "Press ENTER through the handset's start-up screens, entering today's date."),
    "MOUNT_NOT_CONNECTED": (False, "Plug in the handset's serial lead."),
    "TARGET_UNKNOWN": (False, "Use a catalogue name such as M27, NGC 7000 or Vega."),
    "TARGET_BELOW_ALTITUDE_LIMIT": (False, "Wait for it to rise, or pick a higher target."),
    "TARGET_BEYOND_HOUR_ANGLE_LIMIT": (False, "Pick a target nearer the meridian."),
    "TARGET_NEAR_SUN": (False, "Never point near the Sun."),
    "ALTITUDE_OUT_OF_RANGE": (False, "Altitude must be between 2 and 89 degrees."),
    "SLEW_TIMED_OUT": (True, "The mount was stopped; check it is free to move."),
    "GOTO_REFUSED": (True, "The handset would not accept the GoTo."),
    "PLATE_SOLVE_FAILED": (True, "Usual causes: cloud, focus, too few stars. Take a frame and look."),
    "CAMERA_NOT_CONNECTED": (False, "Plug in the camera and start its INDI driver."),
    "NO_STARS": (True, "No stars in the frame: cloud, the cap, or far out of focus. Look at "
                       "the newest frame, then try again."),
    "NO_USABLE_FRAMES": (True, "Every frame was rejected; see the reasons in the session log."),
    "NO_SESSION": (False, "No imaging run has been recorded yet."),
    "NO_CONFIG": (False, "Copy config.example.toml to config.toml and set the location."),
    "DEMO_UNSUPPORTED": (False, "This needs the real camera; there is no demo of it."),
    "INVALID_REQUEST": (False, "Check the command's arguments."),
    "INTERNAL_ERROR": (False, "Unexpected failure; see the message."),
}

MOUNT_STATES = ("offline", "connected", "slewing", "tracking", "stopped", "unknown")
CAMERA_STATES = ("offline", "idle", "capturing")
IMAGING_STATES = ("idle", "capturing", "processing", "finished")


class Refusal(SystemExit):
    """A command declining to act, with a stable code. It is a SystemExit, so
    on the command line it prints its message and exits non-zero as before."""

    def __init__(self, code, message):
        assert code in ERRORS, code
        super().__init__(message)
        self.code_name, self.message = code, message

    def as_error(self):
        return error(self.code_name, self.message)


def error(code, message):
    retryable, advice = ERRORS[code]
    return {"code": code, "message": message, "retryable": retryable, "advice": advice}


def envelope(command, data=None, warnings=(), errors=()):
    """The one shape every JSON answer has."""
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": not errors,
        "command": command,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data": data if data is not None else {},
        "warnings": list(warnings),
        "errors": list(errors),
    }


def jsonable(value):
    """Datetimes and numpy numbers as plain JSON values."""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def emit(result):
    """Print an envelope on stdout and return the exit code that goes with it."""
    json.dump(result, sys.stdout, indent=1, default=jsonable)
    print()
    return 0 if result["ok"] else 1


def run(command, work):
    """Call work() and wrap what it returns, or how it refused, in an envelope.
    work() returns data, or (data, warnings)."""
    try:
        result = work()
    except Refusal as refusal:
        return envelope(command, errors=[refusal.as_error()])
    except SystemExit as stop:   # an older-style refusal with no code yet
        return envelope(command, errors=[error("INTERNAL_ERROR", str(stop))])
    except Exception as problem:   # the envelope must always come back
        return envelope(command, errors=[error("INTERNAL_ERROR", f"{type(problem).__name__}: {problem}")])
    data, warnings = result if isinstance(result, tuple) else (result, ())
    return envelope(command, data, warnings)


def main(command, work, as_json=False):
    """Run a script's work. Normally it prints as it always has. With as_json,
    whatever it prints goes to stderr and one envelope goes to stdout, so a
    program reading stdout gets JSON and nothing else."""
    if not as_json:
        return work()
    with contextlib.redirect_stdout(sys.stderr):
        result = run(command, work)
    raise SystemExit(emit(result))
