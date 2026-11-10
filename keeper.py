#!/usr/bin/env python3
"""Keep the cooled camera open and cold for the whole night.

    ./keeper.py start      open the camera, cool it slowly to its tec_target,
                           and hold it open for every other command (run it in
                           the background, at the start of setup)
    ./keeper.py status     the sensor's temperature, its target, and whether
                           it is ready
    ./keeper.py stop       warm the sensor slowly, then close the camera

The 183M's cooler runs only while a program has the camera open, and each
command (focus, polar alignment, a plate solve, a run, the darks) used to
open and close it, so the cooler stopped and the sensor was cooled again
from warm each time. Gary's way, and the right one: cool slowly once at the
start of the night and warm slowly once at the end. So this holds the
camera, and while it runs, Camera() in any other command is lent it
(camera.Kept): frames, settings and the temperature pass through here, one
call at a time, and the borrower's close and warm-up leave it cold.
5 November 2026: the first night with the 183M lost hours to warming and
re-cooling between steps.

Only a cooled camera on the SDK backend is kept; on any other, `start` says
so and ends. Nothing here moves the mount.
"""
import argparse
import os
import secrets
import signal
import threading
import time

import config

SOCKET = config.DATA / "cache" / "camera.sock"
KEY = config.DATA / "cache" / "camera.key"
STATE = config.DATA / "cache" / "keeper.json"
POLL_S = 5          # seconds between the cooler's ramp steps and temperature checks
SAY_EVERY_S = 60


def key():
    """The secret a borrower shows (a file only this user can read)."""
    return KEY.read_bytes()


def address():
    return str(SOCKET)


def running():
    """Whether a keeper is answering now."""
    return ask(("ping",), quiet=True) == "pong"


def ask(request, quiet=False):
    """One request to the keeper; its answer. None (quiet) if none answers."""
    from multiprocessing.connection import Client
    try:
        with Client(address(), family="AF_UNIX", authkey=key()) as link:
            link.send(request)
            ok, answer = link.recv()
    except (OSError, EOFError, ConnectionError):
        if quiet:
            return None
        raise
    if not ok:
        raise failure(*answer)
    return answer


def failure(kind, message, code=None):
    """The keeper's error, raised again in the borrower as what it was."""
    if code:
        import interface
        return interface.Refusal(code, message)
    if kind in ("CameraError", "IndiError"):
        from altair import CameraError
        return CameraError(message)
    if kind == "KeyboardInterrupt":
        return KeyboardInterrupt()
    return RuntimeError(f"camera keeper: {kind}: {message}")


def write_state(**fields):
    import records
    try:
        records.write(STATE, dict(fields, updated=time.time()))
    except OSError:
        pass


def serve(cam, say=print):
    """Hold `cam` and answer borrowers until told to stop or killed."""
    from multiprocessing.connection import Listener

    import altair
    calls = threading.Lock()        # one camera call at a time, from any borrower
    stopping = threading.Event()
    status = {"ready": False, "sensor_c": None, "target_c": getattr(cam, "target", None)}

    def handle(link):
        with link:
            while True:
                try:
                    request = link.recv()
                except (EOFError, OSError):
                    return
                kind = request[0]
                try:
                    if kind == "ping":
                        answer = "pong"
                    elif kind == "status":
                        answer = dict(status)
                    elif kind == "stop":
                        stopping.set()
                        answer = "stopping"
                    elif kind == "get":
                        with calls:
                            answer = getattr(cam, request[1])
                    elif kind == "call":
                        _, name, gain, args, kwargs = request
                        with calls:
                            cam.gain = gain
                            answer = getattr(cam, name)(*args, **kwargs)
                    else:
                        raise ValueError(f"the keeper does not know {kind!r}")
                    link.send((True, answer))
                except BaseException as problem:
                    try:
                        link.send((False, (problem.__class__.__name__, str(problem),
                                           getattr(problem, "code_name", None))))
                    except (OSError, EOFError):
                        return

    if SOCKET.exists():
        SOCKET.unlink()
    KEY.parent.mkdir(parents=True, exist_ok=True)
    KEY.write_bytes(secrets.token_bytes(32))
    os.chmod(KEY, 0o600)
    listener = Listener(address(), family="AF_UNIX", authkey=key())

    def accept():
        while not stopping.is_set():
            try:
                link = listener.accept()
            except Exception:
                if stopping.is_set():
                    return
                continue
            threading.Thread(target=handle, args=(link,), daemon=True).start()

    threading.Thread(target=accept, daemon=True).start()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    said = 0.0
    try:
        while not stopping.is_set():
            with calls:
                ramped = cam.ramp()
                degrees = cam.temperature()
            target = getattr(cam, "target", None)
            ready = ramped and degrees is not None and target is not None \
                and abs(degrees - target) <= altair.TEC_READY
            if ready and not status["ready"]:
                say(f"camera: sensor at {degrees:.1f} °C, its target {target:g} °C: ready")
            elif time.monotonic() - said >= SAY_EVERY_S and not ready:
                unpowered = getattr(cam, "cooler_unpowered", lambda: False)()
                note = ("; NOT FOLLOWING: the cooler draws nothing, set point held near the sensor: "
                        "is the camera's 12 V lead plugged in?") if unpowered else ""
                say(f"camera: cooling, sensor at {degrees} °C, set point {getattr(cam, 'level', None)} °C, "
                    f"target {target} °C{note}")
                said = time.monotonic()
            status["unpowered"] = bool(getattr(cam, "cooler_unpowered", lambda: False)())
            status.update(ready=ready, sensor_c=degrees, target_c=target, level_c=getattr(cam, "level", None))
            write_state(**status, pid=os.getpid())
            stopping.wait(POLL_S)
    except KeyboardInterrupt:
        pass
    finally:
        stopping.set()
        say("camera: the keeper is stopping: warming the sensor slowly, then closing the camera")
        with calls:
            cam.warm_up(say=say)
        listener.close()
        for path in (SOCKET, STATE):
            try:
                path.unlink()
            except OSError:
                pass


def start(say=print):
    import camera
    if running():
        say("The camera keeper is already running: " + words(ask(("status",))))
        return {"started": False}
    os.environ["TY_KEEPER"] = "1"           # this process opens the camera itself
    with camera.Camera() as cam:
        if getattr(cam, "warm_up", None) is None or getattr(cam, "target", None) is None:
            say("This camera has no cooler, or no tec_target in its settings: nothing to keep cold.")
            return {"started": False}
        say(f"camera: open and cooling slowly to {cam.target:g} °C; held for every command until "
            "./keeper.py stop")
        serve(cam, say=lambda line: print(line, flush=True))
    return {"started": True}


def words(status):
    if not status:
        return "not running"
    sensor = status.get("sensor_c")
    return (f"sensor at {sensor if sensor is None else f'{sensor:.1f}'} °C, target {status.get('target_c')} °C, "
            + ("ready" if status.get("ready") else
               "NOT COOLING: the cooler draws nothing; is its 12 V lead plugged in?" if status.get("unpowered")
               else "still cooling"))


def stop(say=print, wait=900):
    """Tell the keeper to warm up and close; wait for it to go."""
    if not running():
        say("The camera keeper is not running.")
        return False
    ask(("stop",))
    say("The camera keeper is warming the sensor slowly, then closing the camera.")
    end = time.monotonic() + wait
    while time.monotonic() < end and running():
        time.sleep(5)
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", choices=["start", "status", "stop"])
    args = ap.parse_args()
    if args.action == "start":
        start()
    elif args.action == "status":
        print("The camera keeper: " + words(ask(("status",), quiet=True)))
    else:
        stop()


if __name__ == "__main__":
    main()
