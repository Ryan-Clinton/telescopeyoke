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
import json
import os
import time
from contextlib import contextmanager

import config

FILE = config.DATA / "cache" / "activity.json"
STALE_S = 6 * 3600        # a line older than this is from a run that never cleared it


def _read():
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(entries):
    # Never an error: this is a line for the console, called from inside a
    # GoTo, and a full disk must not make a finished move look failed.
    try:
        FILE.parent.mkdir(parents=True, exist_ok=True)
        spare = FILE.with_name(f"{FILE.name}.{os.getpid()}")
        spare.write_text(json.dumps(entries), encoding="utf-8")
        os.replace(spare, FILE)       # whole or not at all, with other processes writing too
    except OSError:
        pass


def _alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True
    except (OSError, ValueError):
        return False


def set_(what, detail="", step=None, of=None):
    """Say what this process is doing now, replacing what it said before."""
    entries = _read()
    pid = str(os.getpid())
    before = entries.get(pid, {})
    entries[pid] = {"what": what, "detail": detail, "step": step, "of": of, "updated": time.time(),
                    "started": before.get("started") if before.get("what") == what else time.time()}
    _write(entries)


def clear():
    entries = _read()
    if entries.pop(str(os.getpid()), None) is not None:
        _write(entries)


@contextmanager
def doing(what, detail="", step=None, of=None):
    """This process is doing `what` until the block ends."""
    set_(what, detail, step, of)
    try:
        yield
    finally:
        clear()


def now(clock=time.time, alive=_alive):
    """What is being done now, outermost first: [{"what", "detail", "step",
    "of", "started", "for_s", "words"}], or [] when nothing is."""
    entries = _read()
    live = {pid: e for pid, e in entries.items() if alive(pid) and clock() - e.get("updated", 0) < STALE_S}
    if len(live) != len(entries):
        _write(live)
    out = []
    for pid, e in sorted(live.items(), key=lambda item: item[1].get("started", 0)):
        count = f" {e['step']} of {e['of']}" if e.get("step") is not None and e.get("of") else ""
        words = f"{e['what']}{count}" + (f": {e['detail']}" if e.get("detail") else "")
        out.append({**e, "pid": int(pid), "for_s": round(clock() - e.get("started", clock())), "words": words})
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
            except (TypeError, KeyError, IndexError):
                words = ""
            with doing(what, words):
                return function(*args, **kwargs)
        return run
    return wrap
