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

import clouds
import config
import tonight

WEB = tonight.ROOT / "web"


def rebuild_forever(minutes, top):
    while True:
        try:
            cfg = config.load()
            try:
                clouds.update(cfg["site"])
            except Exception:
                traceback.print_exc()  # the satellite picture is optional
            rep = tonight.build(cfg)
            tonight.write_html(rep, top, WEB / "index.html")
        except Exception:
            # Keep serving the last good page.
            traceback.print_exc()
        time.sleep(minutes * 60)


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
    args = ap.parse_args()

    WEB.mkdir(exist_ok=True)
    threading.Thread(target=rebuild_forever, args=(args.every, args.top),
                     daemon=True).start()
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(WEB))
    print(f"Serving on http://{lan_address()}:{args.port}  (Ctrl+C to stop)", flush=True)
    ThreadingHTTPServer(("0.0.0.0", args.port), handler).serve_forever()


if __name__ == "__main__":
    main()
