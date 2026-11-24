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
import socket
import struct
import sys
import threading
import time

import config

SOCKET = config.DATA / "cache" / "camera.sock"
KEY = config.DATA / "cache" / "camera.key"
STATE = config.DATA / "cache" / "keeper.json"
POLL_S = 5          # seconds between the cooler's ramp steps and temperature checks
SAY_EVERY_S = 60
SEND_WAIT_S = 30    # a video frame a borrower has not taken after this long ends the video


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


def video(gain, seconds, count, roi=None, timeout=5.0):
    """A video from the kept camera, one frame at a time, as AltairCamera.video
    yields them. A generator cannot cross to the keeper, so the keeper runs it
    and sends each frame down this connection. Leaving the loop early closes
    the connection, which ends the video there."""
    from multiprocessing.connection import Client
    with Client(address(), family="AF_UNIX", authkey=key()) as link:
        link.send(("video", gain, seconds, count, roi, timeout))
        while True:
            try:
                ok, answer = link.recv()
            except (EOFError, OSError):
                raise failure("CameraError", "the camera keeper stopped answering during the video") from None
            if not ok:
                raise failure(*answer)
            if answer is None:
                return
            yield answer


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


def serve(cam, say=print, job=None):
    """Hold `cam` and answer borrowers until told to stop or killed. `job`
    (jobs.py) is told the sensor's state, and when it first reaches its target."""
    from multiprocessing.connection import Listener

    import altair
    calls = threading.Lock()        # one camera call at a time, from any borrower
    stopping = threading.Event()
    streaming = threading.Event()   # a video holds `calls`; plain values may still be read
    status = {"ready": False, "sensor_c": None, "target_c": getattr(cam, "target", None)}

    def stream(link, gain, seconds, count, roi, timeout):
        """Frames to one borrower. The video holds the camera, so the main
        loop cannot look after the cooler: its ramp and checks run here,
        between frames. A borrower that stops reading for SEND_WAIT_S ends
        the video rather than leaving the cooler unwatched."""
        with socket.socket(fileno=os.dup(link.fileno())) as raw:
            raw.setsockopt(socket.SOL_SOCKET, socket.SO_SNDTIMEO, struct.pack("ll", SEND_WAIT_S, 0))
        with calls:
            cam.gain = gain
            frames = cam.video(seconds, count, roi=roi, timeout=timeout)
            checked = time.monotonic()
            streaming.set()
            try:
                for frame in frames:
                    link.send((True, frame))
                    if time.monotonic() - checked >= POLL_S:
                        checked = time.monotonic()
                        cam.ramp()
                        status.update(sensor_c=cam.temperature(), level_c=getattr(cam, "level", None))
                        write_state(**status, pid=os.getpid())
            finally:
                streaming.clear()
                frames.close()      # puts the camera back in its single-frame mode

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
                    elif kind == "get" and streaming.is_set():
                        # The video's borrower asks the camera's name while
                        # the video holds `calls`: waiting would stop both.
                        answer = getattr(cam, request[1])
                    elif kind == "get":
                        with calls:
                            answer = getattr(cam, request[1])
                    elif kind == "call":
                        _, name, gain, args, kwargs = request
                        with calls:
                            cam.gain = gain
                            answer = getattr(cam, name)(*args, **kwargs)
                    elif kind == "video":
                        stream(link, *request[1:])
                        answer = None       # the end of the video
                    else:
                        raise ValueError(f"the keeper does not know {kind!r}")
                    link.send((True, answer))
                except BaseException as problem:
                    if getattr(cam, "disobeying", False):
                        # The cooler failed safe inside this request: the
                        # keeper ends now (its cooler off, the camera closed)
                        # rather than ramping a faulted cooler on.
                        stopping.set()
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
                # Kept so the cooler's draw in normal running is on record
                # (does it ever read 0 while holding? the power-loss check assumes not).
                status["tec_power"] = getattr(cam, "tec_power", lambda: None)()
            target = getattr(cam, "target", None)
            ready = ramped and degrees is not None and target is not None \
                and abs(degrees - target) <= altair.TEC_READY
            if ready and not status["ready"]:
                say(f"camera: sensor at {degrees:.1f} °C, its target {target:g} °C: ready")
                if job is not None and not status.get("was_ready"):
                    # Once: the reading wobbling round the line is not news.
                    job.milestone(f"camera ready: sensor at {degrees:.1f} °C, target {target:g} °C", name="ready")
                status["was_ready"] = True
            if job is not None and degrees is not None:
                job.reading(f"sensor {degrees:.1f} °C, target {target} °C" + ("" if ready else ", cooling"))
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
            off = cam.warm_up(say=say)
            try:
                degrees = cam.temperature()
            except Exception:       # noqa: BLE001 - the message goes either way
                degrees = None
        ambient = getattr(cam, "ambient", None)
        if off is False or degrees is None:
            # What is known, said as known: the cooler's off command refused,
            # or the sensor not read, is not a finished warm-up.
            warmed = ("The camera is closing, but " + ("its cooler did not take the off command (closing the "
                      "camera stops it)" if off is False else "its sensor's temperature could not be read")
                      + ": whether it has warmed up is not known. Leave it a few minutes before switching off.")
        elif (degrees < (ambient if ambient is not None else degrees) - 2 * altair.WARM_STEP_C
              and getattr(cam, "warm_finished", False) and getattr(cam, "warm_from", None) is not None
              and degrees >= cam.warm_from + altair.WARM_STEP_C):
            # Every step taken and the sensor rose with them, but it began
            # the night warmer than the air is now (21 November 2026: 1.7 °C
            # against 13.3 °C, the air about -2.5 °C). Not a fault.
            warmed = (f"The camera's warm-up finished at {degrees:.1f} °C, below the {ambient:.1f} °C it started "
                      "from, most likely because the night air is colder now. Its cooler is off: safe to "
                      "switch off.")
        elif degrees is not None and ambient is not None and degrees < ambient - 2 * altair.WARM_STEP_C:
            # The warm-up was cut short (its time up, a refused step, a
            # faulted cooler): said as it is, not as a finished warm-up.
            warmed = (f"The camera's warm-up was cut short at {degrees:.1f} °C, below the {ambient:.1f} °C it "
                      "started from; its cooler is off. Leave it a few minutes before switching off.")
        else:
            warmed = ("The camera has warmed up" + (f" ({degrees:.1f} °C)" if degrees is not None else "")
                      + " and its cooler is off: safe to switch off.")
        say(f"camera: {warmed}")
        try:
            # The person asked to be told (18 November 2026): it is the last
            # step before the power goes off at the night's end.
            import notify
            notify.send(warmed)
        except Exception as problem:   # noqa: BLE001 - a help, never a step anything waits on
            say(f"camera: the phone could not be told ({problem})")
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
        import activity
        with activity.job("keeper", kind="service") as job:
            serve(cam, say=lambda line: print(line, flush=True), job=job)
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
    if running():
        say(f"The camera keeper has not gone after {wait / 60:.0f} minutes: whether the camera is warm "
            "and closed is not known. ./keeper.py status")
        return False
    return True


def main():
    # Each line out as it is printed, so a log being tailed (a run left in
    # the background) shows progress, not nothing until the end
    # (18 November 2026: a guiding calibration's log stayed empty for 5 min).
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", choices=["start", "status", "stop"])
    ap.add_argument("--after-fault", action="store_true",
                    help="with start: a person's go to cool again after the cooler failed safe "
                         "(refused within 10 minutes of it)")
    args = ap.parse_args()
    if args.action == "start":
        import altair
        if args.after_fault:
            try:
                cleared = altair.clear_fault()
            except altair.CameraError as problem:
                raise SystemExit(f"Not started: {problem}.")
            if cleared:
                print(f"Cooler fault cleared ({cleared.get('reason')}); cooling again, watched.")
        elif altair.fault_latched() and not altair.fault_latched().get("cleared_at"):
            # A fault a person has cleared is kept only until the sensor holds
            # its target (altair.ramp); it does not stop the next start.
            raise SystemExit(f"Not started: the cooler failed safe ({altair.fault_latched().get('reason')}). "
                             "Secure the 12 V lead, then ./keeper.py start --after-fault (10 minutes after it).")
        start()
    elif args.action == "status":
        print("The camera keeper: " + words(ask(("status",), quiet=True)))
    else:
        stop()


if __name__ == "__main__":
    main()
