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

import clouds
import config
import demo
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
NOT_RESULTS = {"latest.jpg", "scope.jpg", "clouds.jpg"}
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


def status_forever(seconds=2):
    """Keep web/status.json describing the newest imaging run, so the page can
    show how far it has got without being rebuilt."""
    target = WEB / "status.json"
    while True:
        try:
            sessions = sorted((tonight.ROOT / "frames").glob("*/*/frames.json"),
                              key=lambda p: p.stat().st_mtime)
            status = stacking.run_status(sessions[-1].parent) if sessions else {}
            status["pictures"] = pictures()
            partial = target.with_suffix(".part")
            partial.write_text(json.dumps(status))
            partial.replace(target)
        except Exception:
            traceback.print_exc()
        time.sleep(seconds)


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
    if not args.demo:
        threading.Thread(target=status_forever, daemon=True).start()
    # The page is read-only, so it is served to the whole home network without
    # a login. Anything that could move the mount must not be added here
    # without authentication designed in first.
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(WEB))
    print(f"Serving on http://{lan_address()}:{args.port}  (Ctrl+C to stop)", flush=True)
    ThreadingHTTPServer(("0.0.0.0", args.port), handler).serve_forever()


if __name__ == "__main__":
    main()
