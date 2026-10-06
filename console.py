#!/usr/bin/env python3
"""A control console in the browser, for the person beside the telescope.

    ./console.py            open the console (http://127.0.0.1:8081)
    ./console.py --demo     try it with a simulated mount and a made-up run

Every button runs one of the project's own commands, as a person would type
it, so every limit and the MOTION_LOCKED file apply as they always do. A move
is first planned with --dry-run and shown; the mount moves only when the
person confirms that plan. Stop is always allowed.

It listens on this computer only and needs a key made each time it starts.
serve.py remains the read-only page for the rest of the house. The design is
in docs/gui.md.
"""
import os
import sys

if "--demo" in sys.argv[1:]:
    os.environ["TY_DEMO"] = "1"      # before anything is imported: the demo keeps its own files

import argparse
import json
import math
import secrets
import subprocess
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import config
import host
import interface

ROOT = Path(__file__).parent
PAGE = ROOT / "console"
WEB = config.DATA / "web"
PYTHON = sys.executable

PLAN_LIFE = 120     # seconds a plan may be confirmed for
# Seconds a job asked to end is given before it is killed. On Windows the
# request is only noticed between calls, so it must outlast a frame arriving.
FINISH_WAIT = 30
KEEP_LINES = 400    # progress lines kept per job

# The page's own files, and the pictures it may show. Nothing else is served.
FILES = {"/": ("index.html", "text/html; charset=utf-8"),
         "/console.css": ("console.css", "text/css; charset=utf-8"),
         "/console.js": ("console.js", "text/javascript; charset=utf-8"),
         "/icons.svg": ("icons.svg", "image/svg+xml")}
PICTURES = ("latest.jpg", "stack.jpg", "scope.jpg", "clouds.jpg", "landmark.jpg")

HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self'; "
                               "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
                               "base-uri 'none'; form-action 'self'",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


class Refused(Exception):
    """A request the console will not act on. Becomes an error envelope."""

    def __init__(self, message, status=409, code="INVALID_REQUEST"):
        super().__init__(message)
        self.message, self.status, self.code = message, status, code


# --- what the console can be asked to do -------------------------------------
#
# Each action builds its command from checked values and nothing else. `uses`
# says what it holds while it runs: "mount" (which Stop ends at once),
# "camera", or None for an order to a run already going. `moves` means it
# goes through a plan that a person confirms.

def target_name(params):
    import mount
    name = str(params.get("target", "")).strip()
    if not name or len(name) > 60:
        raise Refused("Choose a target.")
    try:
        return mount.find_target(name)["id"]
    except interface.Refusal as refusal:
        raise Refused(refusal.message, code=refusal.code_name)


def number(params, key, low, high, default=None, whole=False):
    value = params.get(key, default)
    try:
        value = int(value) if whole else float(value)
    except (TypeError, ValueError):
        raise Refused(f"{key} must be a number.")
    if not low <= value <= high:
        raise Refused(f"{key} must be between {low:g} and {high:g}.")
    return value


def choice(params, key, allowed, default):
    value = params.get(key, default)
    if value not in allowed:
        raise Refused(f"{key} must be one of: {', '.join(map(str, allowed))}.")
    return value


def goto(params):
    return ["mount.py", "goto", target_name(params)] + (["--solve"] if params.get("solve") else [])


def run(params):
    exposure = choice(params, "exposure", ("auto", "1", "2", "3", "4"), "2")
    cmd = ["shoot.py", target_name(params), "--frames", str(number(params, "frames", 1, 5000, 60, True)),
           "--exposure", exposure, "--gain", str(number(params, "gain", 100, 5000, 1500, True))]
    if not params.get("recentre", True):
        return cmd + ["--no-recentre"]   # shoot.py then never touches the mount, assist included
    return cmd + (["--assist"] if params.get("assist") else [])


def focusing(params):
    sound = choice(params, "sound", ("speech", "tones", "silent"), "speech")
    return ["focus.py"] + {"speech": [], "tones": ["--tones"], "silent": ["--quiet"]}[sound]


def survey(params):
    cmd = ["horizon.py"]
    if params.get("trace"):
        cmd.append("--trace")
    if params.get("daylight"):
        cmd.append("--daylight")
    return cmd


def landmark_name(params):
    import landmark
    try:
        return landmark.name_ok(str(params.get("name", "")))
    except interface.Refusal as refusal:
        raise Refused(refusal.message)


def pointing(params):
    return ["mount.py", "point", f"{number(params, 'bearing', 0, 360):g}", f"{number(params, 'height', 2, 89):g}"]


def calibration(params):
    kind = choice(params, "kind", ("dark", "bias", "flat"), "dark")
    return ["calibrate.py", kind, "--frames", str(number(params, "frames", 1, 200, 20, True)),
            "--exposure", f"{number(params, 'exposure', 0.001, 60, 2.0):g}",
            "--gain", str(number(params, "gain", 100, 5000, 1500, True))]


def restacking(params):
    name = target_name(params)
    return ["restack.py", name] + (["--all"] if params.get("all") else [])


ACTIONS = {
    "goto":       {"label": "Go to {target}", "command": goto, "uses": "mount", "moves": True},
    "home":       {"label": "Home", "command": lambda p: ["mount.py", "home"], "uses": "mount", "moves": True},
    "zenith":     {"label": "Zenith", "command": lambda p: ["mount.py", "zenith"], "uses": "mount", "moves": True},
    "compensate": {"label": "Compensate for drift", "command": lambda p: ["mount.py", "compensate"],
                   "uses": "mount", "moves": True,
                   "says": "This slews the mount twice, plate-solving each time, and then changes "
                           "the Dec motor's creep."},
    "drift":      {"label": "Measure drift", "command": lambda p: ["mount.py", "drift"],
                   "uses": "mount", "moves": True,
                   "says": "The tube does not slew, but the Dec motor's creep will be changed."},
    "sync":       {"label": "Sync from plate solve", "command": lambda p: ["mount.py", "sync"],
                   "uses": "mount", "moves": False},
    "position":   {"label": "Read position", "command": lambda p: ["mount.py", "status"],
                   "uses": "mount", "moves": False, "demo": True},
    "run":        {"label": "Image {target}", "command": run, "uses": "mount", "moves": True},
    "focus":      {"label": "Focusing", "command": focusing, "uses": "camera", "moves": False},
    "horizon":    {"label": "Horizon survey", "command": survey, "uses": "mount", "moves": True,
                   "says": "This moves the mount all over the sky, over the pole and back, for "
                           "about a minute per look. Keep clear of it while it runs."},
    # Fetches nothing from the network and needs no camera to start: it is
    # what says why there is no camera yet.
    "camera-setup": {"label": "Set up the camera", "uses": "camera", "moves": False,
                     "command": lambda p: ["camera_setup.py", "--open"]},
    "point":      {"label": "Point at a bearing", "command": pointing, "uses": "mount", "moves": True},
    "landmark-remember": {"label": "Remember landmark", "uses": "mount", "moves": False,
                          "command": lambda p: ["landmark.py", "remember", landmark_name(p)]},
    "landmark-check":    {"label": "Check landmark", "uses": "mount", "moves": True,
                          "command": lambda p: ["landmark.py", "check", landmark_name(p), "--watch", "40"],
                          "says": "The mount turns to where it was when the landmark was remembered, holds "
                                  "there, and photographs it every few seconds for two minutes while you "
                                  "turn the azimuth bolts. Press Finish when it is on the cross."},
    "polar":      {"label": "Polar alignment", "command": lambda p: ["polaralign.py"], "uses": "mount", "moves": True,
                   "says": "This photographs the sky where the telescope is, slews 25° away from the "
                           "meridian twice, photographing each time, and returns. Start from a target "
                           "well away from the pole."},
    "camera-capabilities": {"label": "What the camera is", "uses": "camera", "moves": False,
                            "command": lambda p: ["camera_test.py", "--capabilities"]},
    "camera-throughput":   {"label": "Throughput test", "uses": "camera", "moves": False,
                            "command": lambda p: ["camera_test.py", "--throughput"]},
    "camera-gain-sweep":   {"label": "Gain sweep", "uses": "camera", "moves": False,
                            "command": lambda p: ["camera_test.py", "--gain-sweep"]},
    "calibrate":  {"label": "Calibration frames", "command": calibration, "uses": "camera", "moves": False},
    "restack":    {"label": "Restack {target}", "command": restacking, "uses": "camera", "moves": False},
    # Orders to an imaging run that is already going: they hold nothing.
    "run-finish":     {"label": "Finish run", "command": lambda p: ["ty", "run", "stop"], "uses": None},
    "run-recentre":   {"label": "Re-centre", "command": lambda p: ["ty", "run", "recentre"], "uses": None},
    "run-assist-on":  {"label": "Drift assist on", "command": lambda p: ["ty", "run", "assist-on"], "uses": None},
    "run-assist-off": {"label": "Drift assist off", "command": lambda p: ["ty", "run", "assist-off"], "uses": None},
}
# The demo has a pretend mount, camera and sky, so nearly everything runs in
# it. These do not: they test or set up real equipment.
NOT_IN_DEMO = ("camera-setup", "camera-capabilities", "camera-throughput", "camera-gain-sweep",
               "calibrate", "sync", "drift", "compensate",
               # Each demo command starts a fresh pretend mount at home, so there
               # is no "where it was pointing" for a landmark to be remembered at.
               "landmark-remember", "landmark-check")
# Setting up and testing the equipment belongs to the application's own
# window. The companion page in a browser is for observing, and is refused these.
WORKSTATION = ("camera-setup", "camera-capabilities", "camera-throughput", "camera-gain-sweep",
               "calibrate", "horizon", "polar", "point", "landmark-remember", "landmark-check", "restack",
               "drift", "compensate", "sync", "open-settings")
# Orders that have a run move the mount or change its motors.
MOVING_ORDERS = ("run-recentre", "run-assist-on", "run-assist-off")


def moves(action, params):
    """Whether this needs a plan a person confirms. An imaging run started
    without re-centring never touches the mount, so it does not."""
    if action == "run":
        return bool(params.get("recentre", True))
    return bool(ACTIONS[action].get("moves"))


def uses(action, params):
    """What it holds while it runs: "mount" (which Stop ends at once),
    "camera", or None."""
    if action == "run" and not params.get("recentre", True):
        return "camera"
    return ACTIONS[action]["uses"]


def command(action, params, demo=False, dry_run=False):
    """The full command line for an action, as a list. Never a string."""
    if action not in ACTIONS:
        raise Refused(f"No such action: {action}", status=404)
    if demo and action in NOT_IN_DEMO:
        raise Refused("That tests or sets up real equipment; there is no demo of it.", code="DEMO_UNSUPPORTED")
    cmd = [PYTHON, str(ROOT / (script := ACTIONS[action]["command"](params))[0])] + script[1:]
    if dry_run:
        cmd.append("--dry-run")
    return cmd + ["--json"]


def label(action, params):
    return ACTIONS[action]["label"].format(target=str(params.get("target", "")).strip())


# --- jobs ----------------------------------------------------------------------

def start(cmd, **more):
    return subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace", **more)


def surroundings(demo):
    """The environment a command is started in. In the demo it says so, and
    says where the demo keeps its files, so the command uses the pretend
    mount and camera and never touches a real night's files."""
    if not demo:
        return None
    return {**os.environ, "TY_DEMO": "1", "TY_DATA": str(config.DATA)}


def envelope_from(text):
    """The envelope a script printed, or None if it printed something else."""
    try:
        found = json.loads(text)
        return found if isinstance(found, dict) and "ok" in found else None
    except ValueError:
        return None


class Jobs:
    """At most one job holds the mount or the camera. This is the rule, not a
    first version of something cleverer."""

    def __init__(self, demo=False, start=start, mode="app"):
        self.demo, self.start, self.mode = demo, start, mode
        self.lock = threading.Lock()
        self.current = None       # the job running now
        self.history = []         # finished ones, newest last
        self.plans = {}           # id -> {"action", "params", "made", "plan", "used"}
        self.stopping = False     # Stop is under way: nothing may open the mount
        # Counts presses of Stop. A request to start the mount that was already
        # on its way when Stop was pressed carries the old count and is dead
        # for good: it must not start once Stop has finished.
        self.stops = 0
        self.run_scope = None     # what the run started here was allowed: {"mount": bool}
        self.position = None      # the last answer from "Read position", with its time

    # -- reading

    def describe(self, job):
        if job is None:
            return None
        return {k: job[k] for k in ("id", "action", "label", "uses", "state", "outcome", "started",
                                    "ended", "lines", "result", "error")}

    def snapshot(self):
        with self.lock:
            return {"running": self.describe(self.current),
                    "recent": [self.describe(j) for j in self.history[-10:]],
                    "stopping": self.stopping, "position": self.position, "run_scope": self.run_scope}

    # -- planning and starting

    def dry_run(self, action, params):
        """The plan for a move, or a Refused carrying the script's refusal."""
        done = subprocess.run(command(action, params, self.demo, dry_run=True), cwd=ROOT,
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=120, env=surroundings(self.demo), **host.QUIET)
        answer = envelope_from(done.stdout)
        if answer is None:
            raise Refused("The plan could not be made: " + (done.stderr.strip()[-300:] or "no answer"),
                          status=500, code="INTERNAL_ERROR")
        if not answer["ok"]:
            raise PlanRefused(answer["errors"][0])
        plan = dict(answer["data"], warnings=answer["data"].get("warnings") or answer["warnings"])
        if ACTIONS[action].get("says"):
            plan["says"] = ACTIONS[action]["says"]
        return plan

    def plan(self, action, params):
        if action not in ACTIONS:
            raise Refused(f"No such action: {action}", status=404)
        self.allowed_here(action)
        if not moves(action, params):
            raise Refused(f"{action} is not planned; it does not move the mount.")
        found = self.dry_run(action, params)
        with self.lock:
            now = time.time()
            self.plans = {k: v for k, v in self.plans.items() if now - v["made"] < PLAN_LIFE}
            plan_id = uuid.uuid4().hex
            self.plans[plan_id] = {"action": action, "params": params, "made": now, "plan": found,
                                   "used": False}
        return {"id": plan_id, "action": action, "label": label(action, params), "plan": found,
                "expires_in_s": PLAN_LIFE}

    def confirm(self, plan_id):
        """Start a planned move, if the plan still holds. The plan is made
        again first: it described the world two minutes ago at most, and the
        sky and the mount move on."""
        with self.lock:
            held = self.plans.get(plan_id)
            if held is None or held["used"] or time.time() - held["made"] >= PLAN_LIFE:
                raise Refused("That plan is no longer valid. Make it again.", status=410)
            held["used"] = True
            stops = self.stops
        again = self.dry_run(held["action"], held["params"])
        if changed(held["plan"], again):
            fresh = self.plan(held["action"], held["params"])
            return dict(fresh, changed=True, message="The situation has changed. Look at the new plan.")
        return self.begin(held["action"], held["params"], stops)

    def allowed_here(self, action):
        if self.mode == "companion" and action in WORKSTATION:
            raise Refused("That is done in the TelescopeYoke application, not in the companion page.", 403)

    def act(self, action, params):
        if action not in ACTIONS:
            raise Refused(f"No such action: {action}", status=404)
        self.allowed_here(action)
        if moves(action, params):
            raise Refused(f"{label(action, params)} moves the mount: it needs a confirmed plan.")
        if action in MOVING_ORDERS:
            # shoot.py ignores these in a run started without re-centring, and
            # the console cannot know what a run started elsewhere was allowed.
            with self.lock:
                scope = self.run_scope
            if scope is None:
                raise Refused("No imaging run started from this console is going. Give the order "
                              "where the run was started.")
            if not scope["mount"]:
                raise Refused("This run was started without re-centring, so it may not move the "
                              "mount. Finish it and start one with re-centring.")
        with self.lock:
            stops = self.stops
        return self.begin(action, params, stops)

    def begin(self, action, params, stops=None):
        """Start an action. `stops` is the count of Stop presses when the
        request was made; if Stop has been pressed since, it is refused."""
        using = uses(action, params)
        cmd = command(action, params, self.demo)
        with self.lock:
            touches_mount = using == "mount" or action in MOVING_ORDERS
            if touches_mount and (self.stopping or (stops is not None and stops != self.stops)):
                raise Refused("Stop was pressed. This request is cancelled; plan it again if it is "
                              "still wanted." if not self.stopping else
                              "Stop is under way. Nothing may use the mount until it has answered.")
            if using and self.current:
                raise Refused(f"Busy: {self.current['label']} is running.")
            job = {"id": uuid.uuid4().hex, "action": action, "label": label(action, params),
                   "uses": using, "state": "running", "outcome": None, "started": time.time(),
                   "ended": None, "lines": [], "result": None, "error": None, "stopped": False}
            job["child"] = self.start(cmd, env=surroundings(self.demo), **host.OWN_GROUP)
            if using:
                self.current = job
            if action == "run":
                self.run_scope = {"mount": using == "mount"}
        threading.Thread(target=self._watch, args=(job,), daemon=True).start()
        return {"job": self.describe(job)}

    def _watch(self, job):
        child = job["child"]

        def progress():
            for line in child.stderr:
                if line.strip():
                    job["lines"].append({"time": time.time(), "text": line.rstrip()})
                    del job["lines"][:-KEEP_LINES]

        reader = threading.Thread(target=progress, daemon=True)
        reader.start()
        printed = child.stdout.read()
        child.wait()
        reader.join(timeout=2)
        answer = envelope_from(printed)
        with self.lock:
            job["ended"] = time.time()
            if job["stopped"]:
                job["outcome"], job["error"] = "stopped", {"message": "Ended by Stop."}
            elif job.get("finishing") and (answer is None or answer["ok"]):
                job["outcome"], job["result"] = "finished", (answer or {}).get("data")
            elif answer and answer["ok"]:
                job["outcome"], job["result"] = "finished", answer["data"]
            else:
                job["outcome"] = "failed"
                job["error"] = (answer["errors"][0] if answer and answer["errors"] else
                                {"message": (job["lines"][-1]["text"] if job["lines"] else
                                             f"It ended with code {child.returncode} and no answer.")})
            job["state"] = "ended"
            if job["action"] == "position" and job["result"]:
                self.position = dict(job["result"], read=job["ended"])
            if self.current is job:
                self.current = None
            if job["action"] == "run":
                self.run_scope = None
            self.history.append(job)
            del self.history[:-20]

    # -- ending

    def finish(self):
        """Ask the running job to end as Ctrl+C would, so that it closes the
        camera properly; kill it only if it does not go. This is not Stop."""
        with self.lock:
            job = self.current
            if job is None:
                raise Refused("Nothing is running.")
            job["finishing"] = True
        child = job["child"]
        try:
            host.ask_to_end(child)
        except OSError:
            pass   # it has just gone by itself

        def make_sure():
            try:
                child.wait(timeout=FINISH_WAIT)
            except subprocess.TimeoutExpired:
                child.kill()
        threading.Thread(target=make_sure, daemon=True).start()
        return {"finishing": job["label"]}

    def stop(self):
        """Stop the mount, now. In this order: nothing may open the mount from
        here on; whatever holds its serial port is killed, since on Windows a
        port can be held by one process only; then the handset is told to
        stop. Returns how long that took."""
        pressed = time.monotonic()
        with self.lock:
            self.stopping = True
            self.stops += 1      # every mount start already on its way is now dead
            job = self.current if self.current and self.current["uses"] == "mount" else None
            if job:
                job["stopped"] = True
        try:
            if job:
                job["child"].kill()
                job["child"].wait(timeout=10)   # until the system says it has gone
            cmd = [PYTHON, str(ROOT / "mount.py"), "stop", "--json"]
            done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=30, env=surroundings(self.demo), **host.QUIET)
            answer = envelope_from(done.stdout)
        finally:
            with self.lock:
                self.stopping = False
        took = round(time.monotonic() - pressed, 2)
        ok = bool(answer and answer["ok"])
        return {"stopped": ok, "seconds": took, "ended_job": job["label"] if job else None,
                "error": None if ok else (answer["errors"][0] if answer and answer["errors"] else
                                          {"message": done.stderr.strip()[-300:] or "no answer"})}


    def close(self):
        """The console is closing: end whatever is running, and always tell
        the mount to stop, whether or not anything here was using it."""
        with self.lock:
            job = self.current
        if job and job["uses"] != "mount":
            try:
                host.ask_to_end(job["child"])
                job["child"].wait(timeout=FINISH_WAIT)
            except (OSError, subprocess.TimeoutExpired):
                job["child"].kill()
        return self.stop()


class PlanRefused(Exception):
    """The script refused the plan: the limits working, not a fault."""

    def __init__(self, error):
        super().__init__(error.get("message", ""))
        self.error = error


def changed(before, after):
    """Whether a plan made again differs in what matters from the one the
    person saw."""
    for key in ("would_move", "safe", "pier_side", "target"):
        if before.get(key) != after.get(key):
            return True
    if sorted(before.get("warnings") or []) != sorted(after.get("warnings") or []):
        return True
    a, b = before.get("goto") or before, after.get("goto") or after
    if a.get("pier_side") != b.get("pier_side"):
        return True
    for key, most in (("altitude_deg", 1.0), ("hour_angle_hours", 1 / 15)):
        if key in a and key in b and abs(a[key] - b[key]) > most:
            return True
    return False


# --- what the page reads ---------------------------------------------------------

class Reader:
    """The read-only answers, each kept for a little while so that a page
    asking every two seconds does not run the doctor every two seconds."""

    def __init__(self, demo=False, mode="app"):
        self.demo, self.mode, self.kept, self.lock = demo, mode, {}, threading.Lock()

    def get(self, name, work, seconds):
        with self.lock:
            held = self.kept.get(name)
            if held and time.time() - held[0] < seconds:
                return held[1]
        result = interface.run(name, work)
        with self.lock:
            self.kept[name] = (time.time(), result)
        return result

    def forget(self, name):
        with self.lock:
            self.kept.pop(name, None)

    def state(self):
        import agent
        import config
        site = (config.load() if config.FILE.exists() else config.example())["site"]["name"]
        sky = {}
        if self.demo:
            import simulator
            sky = {"sky": simulator.sky()}
        return dict(agent.status(), demo=self.demo, site=site, capabilities=agent.capabilities(),
                    available=[a for a in ACTIONS if (self.mode == "app" or a not in WORKSTATION)
                               and not (self.demo and a in NOT_IN_DEMO)],
                    **sky, **self.about())

    def about(self):
        """What this is and how it is set up, for the page's frame."""
        import agent
        import config
        import doctor
        hardware = config.hardware()
        return {"mode": self.mode, "version": agent.VERSION, "configured": config.FILE.exists(),
                "settings_file": str(config.FILE), "camera_backend": hardware["camera"]["backend"],
                "mount_link": doctor.mount_link(), "system": sys.platform}

    def session(self):
        import agent
        try:
            return agent.session(include_series=True)
        except interface.Refusal:
            return {"none": True}      # no imaging run yet: not a fault

    def catalogue(self):
        import mount
        import sky
        stars = [{"id": name, "alt_id": "", "name": "star", "kind": "star"} for name in mount.STARS]
        return {"targets": stars + [{k: t[k] for k in ("id", "alt_id", "name", "kind")}
                                    for t in sky.load_targets()]}

    def report(self):
        """The night as the status page shows it: the cards, the conditions,
        the timeline's hours, the ranked targets and the weather table."""
        import config
        import page
        import tonight
        cfg = config.example() if self.demo or not config.FILE.exists() else config.load()
        rep = tonight.build(cfg, demo=self.demo)
        w = rep["weather"]
        return {
            "cards": [dict(zip(("title", "big", "small", "tone"), one)) for one in page.card_data(rep)],
            "conditions": page.conditions(rep),
            "night": {k: rep[k] for k in ("sunset", "sunrise", "dark_start", "dark_end", "dark_level", "now")},
            "moon": rep["moon"],
            "hours": [{"time": h["time"], "cloud": h["cloud"], "level": page.level(h["cloud"], 25, 60)}
                      for h in w["hours"]] if w else [],
            "weather_head": tonight.WEATHER_HEAD,
            "weather_rows": page.weather_rows(w) if w else [],
            "target_head": tonight.TARGET_HEAD,
            "targets": [{"id": t["id"], "name": t["name"], "kind": t["kind"], "score": round(t["score"]),
                         "best": t["best"], "best_alt": round(t["best_alt"]), "direction": t["direction"],
                         "start": t["start"], "end": t["end"], "tags": t["tags"], "now": t["now"],
                         "row": tonight.target_row(i, t)}
                        for i, t in enumerate(rep["targets"][:40], 1)],
        }

    def system(self):
        """The state of the kit as the status page's rows."""
        import serve
        return {"rows": serve.system_status()}

    def finished(self):
        """File names of the finished pictures in web/. None in the demo: its
        run is made up, and the real ones are not part of it."""
        import serve
        return [p["file"] for p in serve.pictures()]

    def gallery(self):
        import serve
        return {"pictures": serve.pictures()}

    def landmarks(self):
        import landmark
        return {"landmarks": landmark.listed(), "degrees_per_pixel": landmark.scale()}

    def polar(self):
        """The last polar alignment measurement, if there is one."""
        import mount
        if not mount.DRIFT_FILE.exists():
            return {"measured": None}
        saved = json.loads(mount.DRIFT_FILE.read_text(encoding="utf-8"))
        found = saved.get("polar")
        if not found:
            return {"measured": None}
        return {"measured": saved.get("saved"), "azimuth_deg": round(found["azimuth"], 2),
                "altitude_deg": round(found["altitude"], 2)}

    def framing(self, name):
        """How a target fits the camera: the field of view from the sensor
        and focal length in the settings, and the target's size from the
        catalogue where it gives one."""
        import config
        import mount
        cfg = config.hardware()
        camera, focal = cfg["camera"], cfg["scope"]["focal_length_mm"]
        degrees = lambda pixels: math.degrees(pixels * camera["pixel_size_um"] / 1000 / focal)
        target = mount.find_target(name)
        return {"field_deg": [round(degrees(camera["width"]), 3), round(degrees(camera["height"]), 3)],
                "scale_arcsec_px": round(206.265 * camera["pixel_size_um"] / focal, 2),
                "size_arcmin": target.get("size"), "minor_arcmin": target.get("minor")}

    def settings(self):
        """Every setting the application can change, with its value now."""
        import config
        if self.mode != "app":
            raise interface.Refusal("INVALID_REQUEST", "Settings are changed in the TelescopeYoke application.")
        written = config._read(config.EXAMPLE if self.demo or not config.FILE.exists() else config.FILE)
        in_use = config._merged(written)
        # A setting that may be left blank shows what the file says, blank
        # included; the rest show the value in use, default or not.
        return {"file": str(config.FILE), "exists": config.FILE.exists(), "demo": self.demo,
                "fields": [dict({"section": section, "key": key, "label": label, "kind": kind, "help": text,
                                 "value": (written if limits.get("optional") else in_use).get(section, {}).get(key)},
                                **limits)
                           for section, key, label, kind, text, limits in config.SETTINGS]}

    def focus(self):
        import focus
        if not focus.FOCUS_FILE.exists():
            return {"reading": None}
        reading = json.loads(focus.FOCUS_FILE.read_text(encoding="utf-8"))
        return {"reading": dict(reading, age_s=round(time.time() - reading["saved"]))}

    def horizon(self):
        import config
        import horizon
        cfg = config.load() if config.FILE.exists() and not self.demo else config.example()
        saved = json.loads(horizon.RESULTS.read_text(encoding="utf-8")) \
            if horizon.RESULTS.exists() and not self.demo else {}
        return {"min_altitude": cfg["horizon"]["min_altitude"], "blocked": cfg["horizon"].get("blocked", []),
                "skyline": saved.get("skyline"), "surveyed": saved.get("saved")}

    def read(self, name, query):
        import agent
        import doctor
        demo = self.demo
        if name.startswith("target/"):
            wanted = unquote(name[len("target/"):])
            return interface.run("target", lambda: dict(agent.target(wanted, demo), framing=self.framing(wanted)))
        routes = {
            "state": (self.state, 2),
            "night": (lambda: agent.night(demo), 300),
            "targets": (lambda: agent.targets(40, None, False, demo), 300),
            "observing": (lambda: agent.observing(demo), 5),
            "session": (self.session, 2),
            "doctor": (lambda: doctor.report(skip_handset=True), 15),
            "catalogue": (self.catalogue, 3600),
            "focus": (self.focus, 1),
            "horizon": (self.horizon, 30),
            "report": (self.report, 300),
            "polar": (self.polar, 2),
            "landmarks": (self.landmarks, 2),
            "settings": (self.settings, 0),
            "system": (self.system, 10),
            "gallery": (self.gallery, 10),
        }
        if name not in routes:
            return None
        work, seconds = routes[name]
        return self.get(name, work, seconds)


# --- the server ------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    """Serves the page to this computer only. GET reads; POST acts, and needs
    the key. See docs/gui.md, "The rule this changes"."""

    key = jobs = reader = None
    port = 8081
    server_version = "telescopeyoke-console"

    def log_message(self, *args):
        pass

    # -- answering

    def send(self, status, body, kind="application/json"):
        self.send_response(status)
        for name, value in HEADERS.items():
            self.send_header(name, value)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def answer(self, result, status=None):
        body = json.dumps(result, default=interface.jsonable).encode()
        self.send(status or (200 if result["ok"] else 409), body)

    def refuse(self, command, refused):
        error = {"code": refused.code, "message": refused.message, "retryable": False,
                 "advice": interface.ERRORS.get(refused.code, (False, ""))[1]}
        self.answer(interface.envelope(command, errors=[error]), refused.status)

    # -- who is asking

    def ours(self):
        """The Host header must be this console's own. A page elsewhere whose
        name has been pointed at 127.0.0.1 (DNS rebinding) sends its own."""
        return self.headers.get("Host", "") in (f"127.0.0.1:{self.port}", f"localhost:{self.port}")

    def keyed(self):
        given = self.headers.get("X-Console-Key", "").encode("utf-8", "replace")
        return secrets.compare_digest(given, self.key.encode())

    def same_origin(self):
        origin = self.headers.get("Origin")
        return origin is None or origin in (f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}")

    # -- reading

    def do_GET(self):
        path = urlparse(self.path).path
        if not self.ours():
            return self.refuse("console", Refused("Not this console's address.", 400))
        if path in FILES:
            name, kind = FILES[path]
            return self.send(200, (PAGE / name).read_bytes(), kind)
        if path.startswith("/landmarks/"):
            # The picture kept with a remembered landmark, by its name only.
            import landmark
            wanted = path[len("/landmarks/"):]
            if wanted in [f"{note['name']}.jpg" for note in landmark.listed()]:
                return self.send(200, (landmark.FOLDER / wanted).read_bytes(), "image/jpeg")
            return self.send(404, b"", "text/plain")
        if path.startswith("/pictures/"):
            name = path[len("/pictures/"):]
            if (name in PICTURES or name in self.reader.finished()) and (WEB / name).exists():
                return self.send(200, (WEB / name).read_bytes(), "image/jpeg")
            return self.send(404, b"", "text/plain")
        if path.startswith("/api/"):
            if not self.keyed():
                return self.refuse("console", Refused("The console's key is missing or wrong.", 403))
            name = path[len("/api/"):].strip("/")
            if name == "job":
                return self.answer(interface.envelope("job", self.jobs.snapshot()))
            if name == "hardware":
                # The handset is asked what it is only while no job has the mount.
                import doctor
                busy = self.jobs.current is not None
                return self.answer(interface.run("hardware", lambda: {"text": doctor.hardware_report(skip_handset=busy)}))
            result = self.reader.read(name, {})
            if result is not None:
                return self.answer(result, 200 if result["ok"] else 409)
        self.refuse("console", Refused(f"No such page: {path}", 404))

    def demo_sky(self, params):
        """Tell the demo's pretend sky and camera what to do: cloud, the
        focuser turned, the camera's lead pulled out, drift. Nothing real."""
        import simulator
        if not self.jobs.demo:
            raise Refused("That is only for the demo.", 403)
        changes = {}
        for key in ("cloud", "unplugged", "drift"):
            if key in params:
                if not isinstance(params[key], bool):
                    raise Refused(f"{key} must be on or off.")
                changes[key] = params[key]
        if "turn" in params:
            if params["turn"] not in (-1, 1):
                raise Refused("The focuser turns one step in or out.")
            changes["focus"] = simulator.sky()["focus"] + params["turn"]
        return {"sky": simulator.set_sky(**changes)}

    def save_settings(self, params):
        """Change settings in config.toml from the application's Settings
        screen. Every value is checked first; nothing is written if any is
        wrong."""
        import config
        self.jobs.allowed_here("open-settings")
        if self.jobs.demo:
            raise Refused("The demo uses the example settings; there is nothing to save.", code="DEMO_UNSUPPORTED")
        given = params.get("values")
        if not isinstance(given, dict) or not given:
            raise Refused("No settings were sent.")
        written = config._read(config.FILE) if config.FILE.exists() else {}
        in_use = config._merged(written)
        changes, wrong = {}, []
        for name, value in given.items():
            section, _, key = str(name).partition(".")
            try:
                value = config.checked(section, key, value)
            except ValueError as problem:
                wrong.append(str(problem))
                continue
            # Only what differs from the value in use is written, so saving
            # does not fill the file with defaults.
            before = (written if value is None else in_use).get(section, {}).get(key)
            if before != value:
                changes[(section, key)] = value
        if wrong:
            raise Refused(" ".join(wrong))
        try:
            if changes or not config.FILE.exists():
                config.save(changes)
        except (ValueError, OSError) as problem:
            raise Refused(f"The settings were not saved: {problem}", 500, "INTERNAL_ERROR")
        with self.reader.lock:
            self.reader.kept.clear()      # everything read from now on uses the new settings
        return {"saved": len(changes), "file": str(config.FILE)}

    def open_settings(self):
        """Open config.toml in the system's own editor, making it from the
        example first if there is none. Only the application's window may."""
        import config
        import shutil as files
        self.jobs.allowed_here("open-settings")
        if self.jobs.demo:
            raise Refused("The demo uses the example settings; there is nothing to edit.", code="DEMO_UNSUPPORTED")
        made = not config.FILE.exists()
        if made:
            files.copy(config.EXAMPLE, config.FILE)
        host.open_file(config.FILE)
        return {"opened": str(config.FILE), "created": made}

    # -- acting

    def do_POST(self):
        path = urlparse(self.path).path
        name = path[len("/api/"):].strip("/") if path.startswith("/api/") else ""
        # Take what was sent before answering, even to refuse: on Windows a
        # refusal sent with the request still unread arrives as a broken connection.
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        sent = self.rfile.read(min(max(length, 0), 65536))
        if not self.ours():
            return self.refuse(name, Refused("Not this console's address.", 400))
        if not self.same_origin():
            return self.refuse(name, Refused("Requests from other pages are refused.", 403))
        if not self.keyed():
            return self.refuse(name, Refused("The console's key is missing or wrong.", 403))
        try:
            params = json.loads(sent or b"{}") if length <= 4096 else None
            if not isinstance(params, dict):
                raise ValueError
        except ValueError:
            return self.refuse(name, Refused("The request was not understood.", 400))
        jobs = self.jobs
        try:
            if name == "demo":
                data = self.demo_sky(params)
            elif name == "open/settings":
                data = self.open_settings()
            elif name == "settings":
                data = self.save_settings(params)
            elif name == "stop":
                data = jobs.stop()
            elif name == "finish":
                data = jobs.finish()
            elif name.startswith("plan/"):
                data = jobs.plan(name[len("plan/"):], params)
            elif name.startswith("confirm/"):
                data = jobs.confirm(name[len("confirm/"):])
            elif name.startswith("action/"):
                data = jobs.act(name[len("action/"):], params)
            else:
                raise Refused(f"No such action: {path}", 404)
        except PlanRefused as refused:
            # The limits working, not a fault: 200, with the script's own refusal.
            return self.answer(interface.envelope(name, {"refused": refused.error}), 200)
        except Refused as refused:
            return self.refuse(name, refused)
        except subprocess.TimeoutExpired:
            return self.refuse(name, Refused("It did not answer in time.", 504, "INTERNAL_ERROR"))
        self.answer(interface.envelope(name, data))


def serve(port=8081, demo=False, key=None, start_job=start, mode="companion"):
    """The console's server, bound to this computer only, and its key.
    `mode` is "app" for the application's own window, which offers
    everything, or "companion" for the page in a browser, which offers
    observing and nothing that sets the equipment up."""
    key = key or secrets.token_urlsafe(24)
    handler = type("ConsoleHandler", (Handler,), {
        "key": key, "port": port, "jobs": Jobs(demo, start_job, mode), "reader": Reader(demo, mode)})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    handler.port = server.server_address[1]   # the real one, when port 0 asked for any
    return server, key


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8081)
    ap.add_argument("--demo", action="store_true",
                    help="a simulated mount, camera and sky; needs no telescope")
    ap.add_argument("--no-browser", action="store_true", help="print the address and do not open it")
    args = ap.parse_args()
    args.demo = args.demo or config.DEMO

    server, key = serve(args.port, args.demo)
    address = f"http://127.0.0.1:{server.server_address[1]}/?key={key}"
    print(f"Console at {address}\nThis computer only. Ctrl+C to close; that also stops the mount.",
          flush=True)
    if not args.no_browser:
        webbrowser.open(address)
    jobs = server.RequestHandlerClass.jobs
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        # Closing the console ends its job and always tells the mount to stop.
        print("Closing: stopping the mount.", flush=True)
        answer = jobs.close()
        if not answer["stopped"]:
            print(f"The mount did not answer the stop: {answer['error'].get('message', '')}", flush=True)


if __name__ == "__main__":
    main()
