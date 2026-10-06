#!/usr/bin/env python3
"""Record a tour of the demo: the animation in the README and a still of each screen.

    ./tour.py                  writes docs/tour.gif and docs/screens/*.png
    ./tour.py --target M13     the object to go to (default: M27 if it is up, else the best that is)
    ./tour.py --frames 30      how many exposures the imaging run takes

It opens TelescopeYoke (demo) in its own window and presses the same buttons a
person would: Tonight, a target, a GoTo centred by plate solving, focusing,
and an imaging run with cloud brought over part of the way through. Each
press is ringed in the recording. It is the demo, so the mount, camera and
sky are pretend and nothing real is connected or moved.

Ubuntu only: it needs the GTK and WebKit window that app.py uses there.
"""
import os
import tempfile

# Before anything is imported: this is the demo, and it starts from nothing
# each time, in a folder of its own, so every recording begins the same way
# and the demo's own files (demo/) are left as they were.
os.environ["TY_DEMO"] = "1"
os.environ["TY_DATA"] = tempfile.mkdtemp(prefix="telescopeyoke-tour-")

import argparse
import io
import json
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import console

ROOT = Path(__file__).parent
WINDOW = (1280, 800)
WIDTH = 960                       # the recording is scaled to this many pixels across
CAPTION = 44
FONTS = ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "DejaVuSans-Bold.ttf")


class Tour:
    """The window, and the three things done to it: run a line of JavaScript
    in the page, wait, and photograph it. The steps run in a thread of their
    own and hand each of those to GTK's thread."""

    def __init__(self, view, key, port):
        self.view, self.key, self.port = view, key, port
        self.frames, self.stills, self.caption = [], {}, ""
        self.font = next((ImageFont.truetype(f, 20) for f in FONTS if _font_there(f)), None) \
            or ImageFont.load_default(20)

    # -- GTK's thread does the work; the steps wait for it

    def _on_gtk(self, begin):
        from gi.repository import GLib
        done, box = threading.Event(), {}

        def finish(value):
            box["value"] = value
            done.set()
        GLib.idle_add(lambda: begin(finish) and False)
        if not done.wait(30):
            raise RuntimeError("the window did not answer")
        return box["value"]

    def js(self, script):
        """Run JavaScript in the page and return what it gives, through JSON."""
        def begin(finish):
            def ready(view, result):
                try:
                    finish(json.loads(view.evaluate_javascript_finish(result).to_string() or "null"))
                except Exception as problem:      # a page that is mid-redraw: the caller tries again
                    finish({"error": str(problem)})
            self.view.evaluate_javascript(f"JSON.stringify((function(){{ {script} }})())", -1, None, None, None, ready)
        return self._on_gtk(begin)

    def picture(self):
        from gi.repository import WebKit2

        def begin(finish):
            def ready(view, result):
                png = io.BytesIO()
                view.get_snapshot_finish(result).write_to_png(png)
                finish(png.getvalue())
            self.view.get_snapshot(WebKit2.SnapshotRegion.VISIBLE, WebKit2.SnapshotOptions.NONE, None, ready)
        shot = Image.open(io.BytesIO(self._on_gtk(begin))).convert("RGB")
        return shot.resize((WIDTH, round(shot.height * WIDTH / shot.width)), Image.LANCZOS)

    # -- recording

    def frame(self, seconds=1.0, ring=None):
        """Add the window as it is now to the recording, with the caption
        under it and a ring round the button about to be pressed."""
        shot = self.picture()
        page = Image.new("RGB", (WIDTH, shot.height + CAPTION), (12, 14, 20))
        page.paste(shot, (0, 0))
        draw = ImageDraw.Draw(page)
        draw.text((16, shot.height + 10), self.caption, fill=(236, 238, 242), font=self.font)
        if ring:
            scale = WIDTH / WINDOW[0]
            x, y, w, h = (v * scale for v in ring)
            for grow in (4, 6, 8):
                draw.rounded_rectangle((x - grow, y - grow, x + w + grow, y + h + grow), radius=8, outline=(255, 196, 0))
        self.frames.append((page, seconds))
        return shot

    def say(self, caption):
        self.caption = caption
        print(f"{time.strftime('%H:%M:%S')}  {caption}", file=sys.stderr, flush=True)

    def still(self, name):
        self.stills[name] = self.picture()

    def watch(self, until, limit=240, every=1.0, played=0.5):
        """Photograph once a second until the page says `until` (JavaScript
        giving true). The recording plays these faster than they happened."""
        end = time.time() + limit
        while time.time() < end:
            self.frame(played)
            if self.js(f"return !!({until});") is True:
                return
            time.sleep(every)
        raise RuntimeError(f"gave up waiting for: {until}")

    def wait(self, until, limit=60):
        end = time.time() + limit
        while time.time() < end:
            if self.js(f"return !!({until});") is True:
                return
            time.sleep(0.3)
        raise RuntimeError(f"gave up waiting for: {until}")

    def press(self, selector, text=None):
        """Ring a button or link in the recording, then click it."""
        find = (f"const all = [...document.querySelectorAll({json.dumps(selector)})].filter((b) => b.offsetParent !== null && !b.disabled"
                + (f" && b.textContent.trim().startsWith({json.dumps(text)})" if text else "") + "); const b = all[0];")
        self.wait(f"(function(){{ {find} return b; }})()")
        box = self.js(find + " b.scrollIntoView({block: 'nearest'}); const r = b.getBoundingClientRect(); return [r.x, r.y, r.width, r.height];")
        self.frame(1.2, ring=box)
        self.js(find + " b.click(); return true;")
        time.sleep(0.6)

    def ask(self, name):
        """One of the console's read-only answers, or {} if it has none to give."""
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/{name}", headers={"X-Console-Key": self.key})
        try:
            with urllib.request.urlopen(request, timeout=60) as reply:
                return json.loads(reply.read())["data"]
        except urllib.error.HTTPError:
            return {}

    def save(self, gif, stills):
        gif.parent.mkdir(parents=True, exist_ok=True)
        stills.mkdir(parents=True, exist_ok=True)
        # One palette for every frame, so that only what changed between two
        # frames has to be stored.
        sample = Image.new("RGB", (WIDTH, self.frames[0][0].height * 4))
        for i, n in enumerate((0, len(self.frames) // 3, 2 * len(self.frames) // 3, len(self.frames) - 1)):
            sample.paste(self.frames[n][0], (0, i * self.frames[0][0].height))
        palette = sample.quantize(96, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        pages = [page.quantize(palette=palette, dither=Image.Dither.NONE) for page, _ in self.frames]
        pages[0].save(gif, save_all=True, append_images=pages[1:], loop=0, optimize=False,
                      duration=[round(seconds * 1000) for _, seconds in self.frames])
        for name, shot in self.stills.items():
            shot.save(stills / f"{name}.png", optimize=True)


def _font_there(name):
    try:
        ImageFont.truetype(name, 20)
        return True
    except OSError:
        return False


def pick_target(tour, wanted):
    """The object the tour goes to: the one asked for, else M27, else the
    best-placed one, taking the first that the limits allow a GoTo to now."""
    ranked = [t["id"] for t in tour.ask("targets")["targets"]]
    for name in ([wanted] if wanted else ["M27"] + ranked):
        found = tour.ask("target/" + urllib.parse.quote(name))
        if (found.get("goto") or {}).get("allowed"):
            return found["id"]
    sys.exit(f"{wanted} cannot be reached just now." if wanted else "Nothing can be reached just now; try later.")


def steps(tour, wanted, frames):
    nav = lambda task: tour.press(f'nav a[data-task="{task}"]')
    idle = "seen.job && !seen.job.running"

    tour.say("Tonight: the verdict, and the best targets for your own sky")
    tour.wait("document.querySelector('#cards div') && seen.targets && seen.catalogue")
    target = pick_target(tour, wanted)
    time.sleep(1)
    tour.still("tonight")
    tour.frame(3.5)

    tour.say(f"Pick a target: {target}")
    nav("targets")
    tour.js(f"const s = document.getElementById('search'); s.value = {json.dumps(target)}; s.dispatchEvent(new Event('input')); return true;")
    tour.press("#ranked .row, #catalogue .row")
    tour.wait("document.querySelector('#chosen .buttons button')")
    tour.still("target")
    tour.frame(3)

    tour.say("Every move is shown as a plan first. Nothing turns until you confirm it")
    tour.press("#chosen button", "Centre with plate solve")
    tour.wait("!document.getElementById('plan').hidden")
    tour.still("plan")
    tour.frame(3.5)
    tour.press("#plan button.confirm")
    tour.say("GoTo: slew, photograph the sky, plate-solve, correct, until it is centred")
    tour.wait("seen.job && seen.job.running", 20)
    tour.js("document.getElementById('log-toggle').click(); return true;")
    tour.watch(idle, played=0.7)
    tour.frame(3)
    tour.js("document.getElementById('log-toggle').click(); return true;")

    tour.say("Focus: start out of focus, and turn the knob while it calls the readings")
    nav("focus")
    tour.js("document.getElementById('focus-sound').value = 'silent'; return true;")
    tour.press("#focus-start")
    tour.wait("seen.job && seen.job.running && seen.job.running.action === 'focus'", 20)
    tour.watch("seen.focus && seen.focus.reading && seen.focus.reading.age_s < 10", 60)
    turns = abs(tour.js("return seen.state.sky.focus;"))
    for _ in range(turns):
        before = tour.js("return seen.focus.reading.saved;")
        tour.js("tellSky({turn: seen.state.sky.focus > 0 ? -1 : 1}); return true;")
        tour.watch(f"seen.focus.reading.saved !== {json.dumps(before)}", 60, played=0.8)
    tour.still("focus")
    tour.frame(3)
    tour.press("#focus-finish")
    tour.wait(idle, 60)

    tour.say(f"Image {target}: short exposures, each one checked, lined up and stacked")
    nav("targets")
    tour.press("#chosen button", "Start imaging")
    tour.js(f"const f = document.getElementById('run-frames'); f.value = {frames}; f.dispatchEvent(new Event('input')); return true;")
    tour.frame(2.5)
    tour.press("#sheet-plan")
    tour.wait("!document.getElementById('plan').hidden")
    tour.frame(3)
    tour.press("#plan button.confirm")
    tour.wait("seen.job && seen.job.running && seen.job.running.action === 'run'", 20)
    nav("imaging")
    taken = lambda n: f"seen.session && seen.session.captured >= {n}"
    tour.watch(taken(frames // 3), 300)
    tour.say("Cloud comes over (a switch in the demo): those frames are rejected, not stacked")
    tour.js("tellSky({cloud: true}); return true;")
    tour.watch(taken(2 * frames // 3), 300)
    tour.js("tellSky({cloud: false}); return true;")
    tour.say("The cloud clears, the run carries on, and the quality pass makes the picture")
    tour.watch(idle, 600)
    time.sleep(2.5)
    tour.still("imaging")
    tour.frame(5)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--target", help="the object to go to (default: M27 if it is up, else the best that is)")
    ap.add_argument("--frames", type=int, default=24, help="exposures in the imaging run (default 24)")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "tour.gif")
    ap.add_argument("--stills", type=Path, default=ROOT / "docs" / "screens")
    args = ap.parse_args()

    try:
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("WebKit2", "4.1")
        from gi.repository import Gtk, WebKit2
    except (ImportError, ValueError):
        sys.exit("tour.py needs the GTK and WebKit window that app.py uses on Ubuntu (./install.sh --planner).")
    import simulator
    simulator.set_sky(focus=4, cloud=False, unplugged=False, drift=True)     # the same start every time

    server, key = console.serve(port=0, demo=True, mode="app")
    jobs = server.RequestHandlerClass.jobs
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    window = Gtk.Window(title="TelescopeYoke (demo): recording a tour")
    window.set_default_size(*WINDOW)
    window.set_resizable(False)
    view = WebKit2.WebView()
    window.add(view)
    window.connect("destroy", Gtk.main_quit)
    view.load_uri(f"http://127.0.0.1:{port}/?key={key}")
    window.show_all()

    tour, failed = Tour(view, key, port), []

    def work():
        from gi.repository import GLib
        try:
            steps(tour, args.target, args.frames)
        except BaseException as problem:      # say what stopped it, and still close the window
            failed.append(problem)
        GLib.idle_add(window.destroy)

    threading.Thread(target=work, daemon=True).start()
    try:
        Gtk.main()
    finally:
        jobs.close()
        server.shutdown()
        server.server_close()
    if failed:
        sys.exit(f"The tour stopped: {failed[0]}")
    tour.save(args.out, args.stills)
    length = sum(seconds for _, seconds in tour.frames)
    print(f"{args.out}: {len(tour.frames)} frames, {length:.0f} s, {args.out.stat().st_size / 1e6:.1f} MB")
    print(f"{args.stills}: " + ", ".join(f"{name}.png" for name in tour.stills))


if __name__ == "__main__":
    main()
