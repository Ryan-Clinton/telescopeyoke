"""What the telescope is doing now, for the console, when it is not imaging.

    with activity.doing("Moving", "to M31"):
        ...

Any command run from anywhere (the console, a terminal, an agent) leaves a
line saying what it is doing, and the console shows it: a GoTo, a plate
solve, focusing, the polar check, a patrol's panel. Before 19 October 2026
the console knew only the jobs it had started itself, and between frames
it showed nothing. Lines nest, outermost first ("Panel 3 of 8: M31-P5 ·
Moving to M31-P5"), each kept by its process's id and dropped when that
process ends, however it ends.
"""
import functools
import inspect
import itertools
import json
import os
import threading
import time
from contextlib import contextmanager

import config

FILE = config.DATA / "cache" / "activity.json"
STALE_S = 6 * 3600        # a line older than this is from a run that never cleared it


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
_lock = threading.Lock()


def _key(name):
    return f"{os.getpid()}-{name}"


def set_(what, detail="", step=None, of=None, key=None):
    """Say what this process is doing now, replacing what it said before
    with the same key (one per process unless given). Never raises."""
    try:
        with _lock:
            entries = _read()
            key = key or _key("main")
            before = entries.get(key, {})
            entries[key] = {"what": what, "detail": detail, "step": step, "of": of, "updated": time.time(),
                            "started": before.get("started") if before.get("what") == what else time.time()}
            _write(entries)
    except Exception:
        pass


def clear(key=None):
    try:
        with _lock:
            entries = _read()
            if entries.pop(key or _key("main"), None) is not None:
                _write(entries)
    except Exception:
        pass


_count = itertools.count()


@contextmanager
def doing(what, detail="", step=None, of=None):
    """This process is doing `what` until the block ends: a line of its own,
    so a plate solve inside a GoTo shows under it rather than in its place."""
    key = _key(f"block{next(_count)}")
    set_(what, detail, step, of, key=key)
    try:
        yield
    finally:
        clear(key)


def now(clock=time.time, alive=_alive):
    """What is being done now, outermost first: [{"what", "detail", "step",
    "of", "started", "for_s", "words"}], or [] when nothing is."""
    entries = _read()
    live = {key: e for key, e in entries.items()
            if alive(key.split("-")[0]) and clock() - e.get("updated", 0) < STALE_S}
    if len(live) != len(entries):
        _write(live)
    out = []
    for key, e in sorted(live.items(), key=lambda item: item[1].get("started", 0)):
        count = f" {e['step']} of {e['of']}" if e.get("step") is not None and e.get("of") else ""
        words = f"{e['what']}{count}" + (f": {e['detail']}" if e.get("detail") else "")
        out.append({**e, "pid": int(key.split("-")[0]), "for_s": round(clock() - e.get("started", clock())),
                    "words": words})
    return out


def during(what, detail=""):
    """A function that says what it is doing while it runs: `detail` is
    filled in from its arguments ("to {name}" with name="M31")."""
    def wrap(function):
        signature = inspect.signature(function)

        @functools.wraps(function)
        def run(*args, **kwargs):
            try:
                bound = signature.bind(*args, **kwargs)
                bound.apply_defaults()
                words = detail.format(**bound.arguments)
            except Exception:
                words = ""
            with doing(what, words):
                return function(*args, **kwargs)
        return run
    return wrap
