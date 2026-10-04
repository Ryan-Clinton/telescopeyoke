#!/usr/bin/env python3
"""Serve the tonight report on the home network so it can be watched from
another computer: run this, then open http://<this laptop's address>:8080

The page is rebuilt every few minutes. Anything else saved into web/ (such as
latest.jpg from the camera) is served alongside it.
"""
import argparse
import functools
import socket
import threading
import time
import traceback
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import json
import shutil
from urllib.parse import parse_qs, unquote, urlparse

import clouds
import config
import agent
import demo
import host
import sky
import stacking
import tonight

WEB = tonight.ROOT / "web"


def rebuild_forever(minutes, top, demo_mode):
    while True:
        try:
            cfg = config.example() if demo_mode else config.load()
            if demo_mode:
                demo.install_sample_frame(WEB)
            else:
                try:
                    clouds.update(cfg["site"])
                except Exception:
                    traceback.print_exc()  # the satellite picture is optional
            rep = tonight.build(cfg, demo=demo_mode)
            tonight.write_html(rep, top, WEB / "index.html")
        except Exception:
            # Keep serving the last good page.
            traceback.print_exc()
        time.sleep(minutes * 60)


# Pictures in web/ that are part of the page's furniture, not results.
NOT_RESULTS = {"latest.jpg", "stack.jpg", "scope.jpg", "clouds.jpg"}
KINDS = (("-final", "final (quality pass)"), ("-processed-closeup", "processed close-up"),
         ("-processed", "processed"), ("-closeup", "close-up"), ("compare", "comparison"))


def pictures():
    """Finished pictures in web/, newest first, described for the page."""
    found = []
    for path in WEB.glob("*.jpg"):
        if path.name in NOT_RESULTS or path.name.endswith(".part.jpg"):
            continue
        stem = path.stem
        kind = next((label for ending, label in KINDS if stem.endswith(ending) or stem == ending),
                    "live stack")
        target = stem
        for ending, _ in KINDS:
            if stem.endswith(ending):
                target = stem[:-len(ending)]
                break
        found.append({"file": path.name, "target": target.upper() if target != "compare" else "",
                      "kind": kind, "time": path.stat().st_mtime})
    return sorted(found, key=lambda p: -p["time"])


def age(path):
    """Seconds since a file was written, or None if it is not there."""
    return round(time.time() - path.stat().st_mtime) if path.exists() else None


def fresh(seconds, limit):
    """('3 min ago', level) for a data feed that should be newer than `limit`."""
    if seconds is None:
        return "not fetched", "fair"
    text = (f"{seconds} s ago" if seconds < 90 else f"{seconds // 60} min ago"
            if seconds < 5400 else f"{seconds // 3600} h ago")
    return text, "good" if seconds <= limit else "fair"


def system_status(run_age=None):
    """The state of the kit, as rows for the page. Read-only: it looks at
    files and the INDI server, and never opens the mount's serial port,
    which belongs to whatever command is driving the mount."""
    import doctor
    import mount
    rows = []

    def add(label, text, level="good"):
        rows.append({"label": label, "text": text, "level": level})

    lead = doctor.find_serial_port()
    add("Mount lead", "connected" if lead else "not connected", "good" if lead else "bad")
    solved = age(mount.LAST_SOLVE)
    add("Last plate solve", *(fresh(solved, 900) if solved is not None else ("none yet", "fair")))
    marks = {doctor.OK: "good", doctor.WARN: "fair", doctor.FAIL: "bad"}
    if config.hardware()["camera"]["backend"] == "indi":
        status, message = doctor.check_indi_server()
        add("INDI server", "running" if status == doctor.OK else message, marks[status])
    status, message = doctor.check_camera()
    capturing = run_age is not None and run_age < 60
    add("Camera", ("capturing" if capturing else "connected") if status == doctor.OK else message,
        marks[status])
    solver = (doctor.check_solver()[0] == doctor.OK
              and doctor.check_star_database()[0] == doctor.OK)
    add("Plate solver", "ready" if solver else "not installed", "good" if solver else "bad")
    cache = tonight.ROOT / "cache"
    newest = lambda pattern: min((age(p) for p in cache.glob(pattern)), default=None)
    add("Weather forecast", *fresh(newest("weather_*.json"), 3600))
    add("Seeing forecast", *fresh(newest("seeing_*.json"), 6 * 3600))
    add("Satellite image", *fresh(age(WEB / "clouds.jpg"), 1800))
    free = shutil.disk_usage(tonight.ROOT).free / 1e9
    add("Disk free", f"{free:.0f} GB", "good" if free > 20 else "fair" if free > 5 else "bad")
    load = host.processor_load()
    if load is not None:
        add("Processor", f"{load:.0f}% busy", "good" if load < 80 else "fair")
    degrees = host.temperature()
    if degrees is not None:
        add("Temperature", f"{degrees:.0f}°C", "good" if degrees < 80 else "fair" if degrees < 92 else "bad")
    return rows


def image_status(name):
    """What web/<name>.jpg is a picture of, from the note written beside it."""
    note = WEB / f"{name}.json"
    if not (note.exists() and (WEB / f"{name}.jpg").exists()):
        return None
    info = json.loads(note.read_text(encoding="utf-8"))
    info["age"] = age(WEB / f"{name}.jpg")
    return info


def status_forever(seconds=2):
    """Keep web/status.json describing the newest imaging run, so the page can
    show how far it has got without being rebuilt."""
    target = WEB / "status.json"
    system, checked, notes = None, 0.0, []
    names = {t["id"]: t["name"] for t in sky.load_targets()}
    while True:
        try:
            # A session is any folder with a frame log, newest activity last.
            folders = {p.parent for p in (tonight.ROOT / "frames").glob("*/*/frames.json*")}
            sessions = sorted(folders, key=lambda d: max(q.stat().st_mtime for q in d.glob("*.json*")))
            status = stacking.run_status(sessions[-1]) if sessions else {}
            if status.get("name"):
                full = names.get(status["name"], "")
                status["title"] = f"{status['name']} — {full}" if full else status["name"]
            status["pictures"] = pictures()
            status["now"] = image_status("latest")     # the newest single exposure
            status["stack"] = image_status("stack")    # the running stack
            status["scope_age"] = age(WEB / "scope.jpg")
            # The system checks open a connection to INDI, so do them less often.
            if time.time() - checked > 15:
                system, checked = system_status(status.get("age")), time.time()
                try:
                    notes = agent.observing()["notes"]
                except Exception:
                    notes = []
            status["system"] = system
            status["notes"] = notes
            partial = target.with_suffix(".part")
            partial.write_text(json.dumps(status), encoding="utf-8")
            host.replace_preview(partial, target)
        except Exception:
            traceback.print_exc()
        time.sleep(seconds)


class Handler(SimpleHTTPRequestHandler):
    """The static page, plus a small read-only API with the same answers the
    `ty` command gives:

        /api/v1/status  /api/v1/capabilities  /api/v1/night
        /api/v1/targets?limit=10&kind=galaxy&now=1
        /api/v1/target/M27  /api/v1/session/current  /api/v1/context
        /api/v1/observing

    GET only. Nothing here can move the mount or change anything."""

    demo = False

    def do_GET(self):
        url = urlparse(self.path)
        if not url.path.startswith("/api/v1/"):
            return super().do_GET()
        import agent
        import interface
        name = url.path[len("/api/v1/"):].strip("/")
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        routes = {
            "status": agent.status,
            "capabilities": agent.capabilities,
            "night": lambda: agent.night(self.demo),
            "targets": lambda: agent.targets(int(query.get("limit", 10)), query.get("kind"),
                                             query.get("now") in ("1", "true"), self.demo),
            "session/current": lambda: agent.session(query.get("frames") in ("1", "true"),
                                                     int(query.get("limit", 50))),
            "context": lambda: {"text": agent.context(self.demo)},
            "observing": lambda: agent.observing(self.demo),
        }
        if name.startswith("target/"):
            work = lambda: agent.target(unquote(name[len("target/"):]), self.demo)
        elif name in routes:
            work = routes[name]
        else:
            work = lambda: (_ for _ in ()).throw(
                interface.Refusal("INVALID_REQUEST", f"No such endpoint: /api/v1/{name}"))
        result = interface.run(name, work)
        body = json.dumps(result, default=interface.jsonable).encode()
        self.send_response(200 if result["ok"] else 404 if name not in routes
                           and not name.startswith("target/") else 409)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def lan_address():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 9))  # no packet is sent; this picks the route
            return s.getsockname()[0]
        except OSError:
            return "localhost"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--every", type=float, default=10, help="minutes between rebuilds")
    ap.add_argument("--top", type=int, default=40, help="targets to list")
    ap.add_argument("--demo", action="store_true",
                    help="made-up weather at the example site; needs no telescope")
    args = ap.parse_args()

    WEB.mkdir(exist_ok=True)
    threading.Thread(target=rebuild_forever, args=(args.every, args.top, args.demo),
                     daemon=True).start()
    if args.demo:
        # A made-up imaging run, so the live parts of the page have something to show.
        (WEB / "status.json").write_text(json.dumps(demo.status()), encoding="utf-8")
    else:
        threading.Thread(target=status_forever, daemon=True).start()
    # The page is read-only, so it is served to the whole home network without
    # a login. Anything that could move the mount must not be added here
    # without authentication designed in first.
    Handler.demo = args.demo
    handler = functools.partial(Handler, directory=str(WEB))
    print(f"Serving on http://{lan_address()}:{args.port}  (Ctrl+C to stop)", flush=True)
    ThreadingHTTPServer(("0.0.0.0", args.port), handler).serve_forever()


if __name__ == "__main__":
    main()
