"""What the telescope is doing now, for the console and the status page.

    with activity.doing("Moving", "to M31"):
        ...

    with activity.imaging("M31-P6", 19, 16, session_folder) as run:
        run.waiting()            # the camera is asked for a frame
        run.took(1)              # one has come

Any command run from anywhere (the console, a terminal, an agent) leaves a
line saying what it is doing, and the console shows it: a GoTo, a plate
solve, focusing, the polar check, a patrol's panel, an imaging run. Before
19 October 2026 the console knew only the jobs it had started itself, and
between frames it showed nothing. Lines nest, outermost first ("Panel 3 of
8: M31-P5 · Moving to M31-P5"), each kept by its process's id and dropped
when that process ends, however it ends. An imaging run's line says how
many frames have come, and when the camera has kept it waiting much longer
than a frame takes, says so (22 October 2026).
"""
import functools
import inspect
import itertools
import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import config

FILE = config.DATA / "cache" / "activity.json"
STALE_S = 6 * 3600        # a line older than this is from a run that never cleared it
SILENT_MARGIN_S = 60      # a camera silent for more than 2 x the exposure + this has stopped sending
KEEP_RUNS = 30            # imaging runs remembered in RUNS


def _last_file():
    return FILE.with_name("activity_last.json")


def _runs_file():
    return FILE.with_name("activity_runs.json")


def _read():
    try:
        entries = json.loads(FILE.read_text(encoding="utf-8"))
        return {k: v for k, v in entries.items() if isinstance(v, dict)} if isinstance(entries, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def _write(entries):
    # Never an error: this is a line for the console, called from inside a
    # GoTo, and a full disk must not make a finished move look failed. The
    # spare file is this thread's own: a patrol plate-solves its last panel
    # in the background while it moves on, and two threads sharing one spare
    # could fail each other's write.
    try:
        FILE.parent.mkdir(parents=True, exist_ok=True)
        spare = FILE.with_name(f"{FILE.name}.{os.getpid()}.{threading.get_ident()}")
        spare.write_text(json.dumps(entries), encoding="utf-8")
        os.replace(spare, FILE)       # whole or not at all, with other processes writing too
    except Exception:
        pass


def _alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True
    except (OSError, ValueError):
        return False


# One read-change-write at a time within a process: two threads doing it at
# once each write back what the other has not seen, and a cleared line returns.
_thread_lock = threading.Lock()


@contextmanager
def _lock():
    """One read-change-write at a time, across processes too: the status
    page drops dead processes' lines while a patrol, its shoot.py and a GoTo
    each write theirs, and without a lock between processes one can write
    back a file that has lost another's line (22 October 2026: the page
    said "Nothing running" through a patrol). Never an error: if the lock
    cannot be had, it goes on without it."""
    with _thread_lock:
        held = None
        try:
            import records
            held = records.locked(FILE)
            held.__enter__()
        except Exception:
            held = None
        try:
            yield
        finally:
            if held is not None:
                try:
                    held.__exit__(None, None, None)
                except Exception:
                    pass


def _session(path):
    """A session folder as kept in a line: under config.DATA where it is
    (frames/M31-P6/20261022-043951), so status.json carries no home folder."""
    try:
        return Path(path).resolve().relative_to(Path(config.DATA).resolve()).as_posix()
    except (ValueError, OSError):
        return str(path)


def _key(name):
    return f"{os.getpid()}-{name}"


def set_(what, detail="", step=None, of=None, key=None, **extra):
    """Say what this process is doing now, replacing what it said before
    with the same key (one per process unless given). `extra` is kept with
    the line (an imaging run's frames, exposure and session). Never raises."""
    try:
        with _lock():
            entries = _read()
            key = key or _key("main")
            before = entries.get(key, {})
            entries[key] = {**extra, "what": what, "detail": detail, "step": step, "of": of,
                            "updated": time.time(),
                            "started": before.get("started") if before.get("what") == what else time.time()}
            _write(entries)
    except Exception:
        pass


def _ended(entry, when, stopped=False):
    """Note a line that has ended: as the last thing done, and for an
    imaging run against its session too, so the page can say when a run
    that never finished stopped."""
    try:
        _last_file().write_text(json.dumps(dict(entry, ended=when, stopped=stopped)), encoding="utf-8")
    except Exception:
        pass
    if not entry.get("session"):
        return
    try:
        runs = json.loads(_runs_file().read_text(encoding="utf-8"))
        runs = runs if isinstance(runs, dict) else {}
    except (OSError, ValueError):
        runs = {}
    runs[entry["session"]] = {"ended": when, "stopped": stopped, "frames": entry.get("frames"),
                              "planned": entry.get("planned")}
    runs = dict(sorted(runs.items(), key=lambda item: item[1].get("ended") or 0)[-KEEP_RUNS:])
    try:
        _runs_file().write_text(json.dumps(runs), encoding="utf-8")
    except Exception:
        pass


def clear(key=None, stopped=False):
    try:
        with _lock():
            entries = _read()
            ended = entries.pop(key or _key("main"), None)
            if ended is not None:
                _write(entries)
                # What finished last, so a page with nothing going on can
                # still say what happened and when (20 October 2026).
                _ended(ended, time.time(), stopped)
    except Exception:
        pass


def lasted(seconds):
    """How long, as the page says it: "40 s", "5 min"."""
    seconds = max(0, round(seconds))
    return f"{seconds} s" if seconds < 90 else f"{round(seconds / 60)} min"


def _words(e):
    if e.get("exposure") is not None and e.get("frames") is not None:
        # An imaging run: "Imaging M31-P6: 4 of 19 frames of 16 s".
        count = f"{e['frames']} of {e['planned']}" if e.get("planned") else f"{e['frames']}"
        name = f" {e['detail']}" if e.get("detail") else ""
        return f"{e['what']}{name}: {count} frames of {e['exposure']:g} s"
    count = f" {e['step']} of {e['of']}" if e.get("step") is not None and e.get("of") else ""
    heading = f" {e['heading']}" if e.get("heading") else ""    # "Patrol M31 panels: ..."
    return f"{e['what']}{heading}{count}" + (f": {e['detail']}" if e.get("detail") else "")


def last():
    """The last thing that ended: {"what", "detail", "ended", "stopped",
    "words"}, or None. `stopped` when it was stopped (by hand, or its
    process ended) rather than finishing."""
    try:
        e = json.loads(_last_file().read_text(encoding="utf-8"))
        return dict(e, stopped=bool(e.get("stopped")), words=_words(e))
    except Exception:
        return None


_count = itertools.count()


@contextmanager
def doing(what, detail="", step=None, of=None):
    """This process is doing `what` until the block ends: a line of its own,
    so a plate solve inside a GoTo shows under it rather than in its place."""
    key = _key(f"block{next(_count)}")
    set_(what, detail, step, of, key=key)
    stopped = True
    try:
        yield
        stopped = False
    finally:
        clear(key, stopped=stopped)


class Imaging:
    """An imaging run's line, kept up to date frame by frame (imaging())."""

    def __init__(self, name, planned, exposure, session, key):
        self.name, self.key = name, key
        self.fields = {"frames": 0, "planned": planned or None, "exposure": float(exposure),
                       "session": _session(session) if session else None, "waiting_since": None}

    def _say(self):
        set_("Imaging", self.name, key=self.key, **self.fields)

    def waiting(self):
        """The camera is being opened or asked for a frame, from now."""
        self.fields["waiting_since"] = time.time()
        self._say()

    def took(self, frames):
        """A frame has come, `frames` so far; the next is asked for at once."""
        self.fields.update(frames=frames, waiting_since=time.time())
        self._say()

    def pause(self):
        """Not waiting on the camera (re-centring, dithering)."""
        self.fields["waiting_since"] = None
        self._say()


@contextmanager
def imaging(name, planned, exposure, session=None):
    """An imaging run (shoot.py) for as long as the block runs: "Imaging
    M31-P6: 4 of 19 frames of 16 s", and once the camera has sent nothing
    for more than twice the exposure and a minute, "... — camera has sent no
    frame for 5 min" (22 October 2026: a run waited over five minutes for
    its first frame while the page said nothing was running)."""
    run = Imaging(name, planned, exposure, session, _key(f"block{next(_count)}"))
    run._say()
    stopped = True
    try:
        yield run
        stopped = False
    finally:
        clear(run.key, stopped=stopped)


def silent(e, entries, clock=time.time):
    """Seconds an imaging run has waited on the camera, when that is longer
    than a frame can take (2 x exposure + SILENT_MARGIN_S); else None. Not
    while something its own process started since the wait began is going
    on (a re-centring GoTo); `entries` are that process's lines."""
    since, exposure = e.get("waiting_since"), e.get("exposure")
    if since is None or exposure is None:
        return None
    if any(other is not e and other.get("started", 0) > since for other in entries):
        return None
    waited = clock() - since
    return round(waited) if waited > 2 * exposure + SILENT_MARGIN_S else None


def now(clock=time.time, alive=_alive):
    """What is being done now, outermost first: [{"what", "detail", "step",
    "of", "started", "for_s", "words", "camera_silent_s"}], or [] when
    nothing is."""
    with _lock():
        entries = _read()
        live = {key: e for key, e in entries.items()
                if alive(key.split("-")[0]) and clock() - e.get("updated", 0) < STALE_S}
        if len(live) != len(entries):
            _write(live)
            # A process that ended without clearing its line was stopped
            # (Ctrl-C on a patrol, a kill): its imaging run is noted as
            # stopped, and the last thing done is the innermost of its lines.
            gone = sorted((e for key, e in entries.items() if key not in live),
                          key=lambda e: (bool(e.get("session")), e.get("started", 0)))
            for e in gone:
                if e.get("session"):
                    _ended(e, clock(), stopped=True)
            if gone and not gone[-1].get("session"):
                _ended(gone[-1], clock(), stopped=True)
    ordered = sorted(live.items(), key=lambda item: item[1].get("started", 0))
    out = []
    for key, e in ordered:
        words = _words(e)
        pid = key.split("-")[0]
        quiet = silent(e, [other for k, other in ordered if k.split("-")[0] == pid], clock)
        if quiet is not None:
            words += f" — camera has sent no frame for {lasted(quiet)}"
        out.append({**e, "pid": int(key.split("-")[0]), "for_s": round(clock() - e.get("started", clock())),
                    "words": words, "camera_silent_s": quiet})
    return out


def run_state(session, entries=None):
    """Whether the imaging run in `session` is still being run, from the
    lines of the processes running now: {"running", "stopped_at",
    "camera_silent_s"}. A run no process is running ended at `stopped_at`:
    when its line ended if that was seen, else its newest file (22 October
    2026: an M31-P6 run stopped by hand still read as imaging)."""
    entries = now() if entries is None else entries
    folder, session = Path(session), _session(session)
    mine = next((e for e in entries if e.get("session") == session), None)
    if mine is not None:
        return {"running": True, "stopped_at": None, "camera_silent_s": mine.get("camera_silent_s")}
    try:
        runs = json.loads(_runs_file().read_text(encoding="utf-8"))
        ended = (runs.get(session) or {}).get("ended") if isinstance(runs, dict) else None
    except (OSError, ValueError, AttributeError):
        ended = None
    if ended is None:
        ended = max((p.stat().st_mtime for p in folder.glob("*.json*")), default=None)
    return {"running": False, "stopped_at": ended, "camera_silent_s": None}


# Where getting to a target has got, by the name each step's code gives its
# activity line (mount.py, solve.py, focus.py, patrol.py, shoot.py): the
# stream's between-targets card reads this rather than the words.
PHASES = {"Moving": "goto", "Plate solving": "solve", "Checking focus": "focus", "Focusing": "focus",
          "Focusing with the motor": "focus", "Patrol": "imaging", "Imaging": "imaging", "Searching": "imaging"}
ORDER = ["goto", "solve", "focus", "imaging"]


def phase(entries=None):
    """The newest of goto / solve / focus / imaging being done now, or None."""
    entries = now() if entries is None else entries
    found = [PHASES[e["what"]] for e in entries if e.get("what") in PHASES]
    return found[-1] if found else None


def during(what, detail=""):
    """A function that says what it is doing while it runs: `detail` is
    filled in from its arguments ("to {name}" with name="M31"), or is a
    function given them all."""
    def wrap(function):
        signature = inspect.signature(function)

        @functools.wraps(function)
        def run(*args, **kwargs):
            try:
                bound = signature.bind(*args, **kwargs)
                bound.apply_defaults()
                words = detail(bound.arguments) if callable(detail) else detail.format(**bound.arguments)
            except Exception:
                words = ""
            with doing(what, words):
                return function(*args, **kwargs)
        return run
    return wrap
