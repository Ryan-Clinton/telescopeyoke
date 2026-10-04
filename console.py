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
import argparse
import json
import secrets
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import host
import interface

ROOT = Path(__file__).parent
PAGE = ROOT / "console"
WEB = ROOT / "web"
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
PICTURES = ("latest.jpg", "stack.jpg", "scope.jpg")

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
# What the simulated mount can show. The rest need the real camera.
DEMO_ACTIONS = ("goto", "home", "zenith", "position")
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
    if demo and action not in DEMO_ACTIONS:
        raise Refused("That needs the real camera or mount; there is no demo of it.", code="DEMO_UNSUPPORTED")
    cmd = [PYTHON, str(ROOT / (script := ACTIONS[action]["command"](params))[0])] + script[1:]
    if demo:
        cmd.insert(2, "--demo")
    if dry_run:
        cmd.append("--dry-run")
    return cmd + ["--json"]


def label(action, params):
    return ACTIONS[action]["label"].format(target=str(params.get("target", "")).strip())


# --- jobs ----------------------------------------------------------------------

def start(cmd, **more):
    return subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace", **more)


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

    def __init__(self, demo=False, start=start):
        self.demo, self.start = demo, start
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
                              timeout=120, **host.QUIET)
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
            if held is None or held["used"] or time.time() - held["made"] > PLAN_LIFE:
                raise Refused("That plan is no longer valid. Make it again.", status=410)
            held["used"] = True
            stops = self.stops
        again = self.dry_run(held["action"], held["params"])
        if changed(held["plan"], again):
            fresh = self.plan(held["action"], held["params"])
            return dict(fresh, changed=True, message="The situation has changed. Look at the new plan.")
        return self.begin(held["action"], held["params"], stops)

    def act(self, action, params):
        if action not in ACTIONS:
            raise Refused(f"No such action: {action}", status=404)
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
            job["child"] = self.start(cmd, **host.OWN_GROUP)
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
            cmd = [PYTHON, str(ROOT / "mount.py")] + (["--demo"] if self.demo else []) + ["stop", "--json"]
            done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=30, **host.QUIET)
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

    def __init__(self, demo=False):
        self.demo, self.kept, self.lock = demo, {}, threading.Lock()

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
        if self.demo:
            import demo
            run = demo.status()
            return {"demo": True, "site": config.example()["site"]["name"],
                    "mount": {"state": "tracking", "motion_locked": False},
                    "camera": {"state": "capturing"}, "solver": {"state": "ready"},
                    "imaging": {"state": "capturing", "target": run["name"], "captured": run["captured"],
                                "accepted": run["accepted"]},
                    "capabilities": agent.capabilities(), "available": list(DEMO_ACTIONS)}
        site = (config.load() if config.FILE.exists() else config.example())["site"]["name"]
        return dict(agent.status(), demo=False, site=site, capabilities=agent.capabilities(),
                    available=list(ACTIONS))

    def session(self):
        import agent
        if self.demo:
            import demo
            run = demo.status()
            return dict(run, state="capturing", acceptance_rate=round(run["accepted"] / run["captured"], 3))
        return agent.session(include_series=True)

    def catalogue(self):
        import mount
        import sky
        stars = [{"id": name, "alt_id": "", "name": "star", "kind": "star"} for name in mount.STARS]
        return {"targets": stars + [{k: t[k] for k in ("id", "alt_id", "name", "kind")}
                                    for t in sky.load_targets()]}

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
            return interface.run("target", lambda: agent.target(wanted, demo))
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
        if path.startswith("/pictures/"):
            name = path[len("/pictures/"):]
            if name in PICTURES and self.jobs.demo:
                # The demo's run is made up, so its picture is the sample one:
                # never whatever the real camera last left in web/.
                import demo
                if name != "scope.jpg" and demo.SAMPLE_FRAME.exists():
                    return self.send(200, demo.SAMPLE_FRAME.read_bytes(), "image/jpeg")
            elif name in PICTURES and (WEB / name).exists():
                return self.send(200, (WEB / name).read_bytes(), "image/jpeg")
            return self.send(404, b"", "text/plain")
        if path.startswith("/api/"):
            if not self.keyed():
                return self.refuse("console", Refused("The console's key is missing or wrong.", 403))
            name = path[len("/api/"):].strip("/")
            if name == "job":
                return self.answer(interface.envelope("job", self.jobs.snapshot()))
            result = self.reader.read(name, {})
            if result is not None:
                return self.answer(result, 200 if result["ok"] else 409)
        self.refuse("console", Refused(f"No such page: {path}", 404))

    # -- acting

    def do_POST(self):
        path = urlparse(self.path).path
        name = path[len("/api/"):].strip("/") if path.startswith("/api/") else ""
        if not self.ours():
            return self.refuse(name, Refused("Not this console's address.", 400))
        if not self.same_origin():
            return self.refuse(name, Refused("Requests from other pages are refused.", 403))
        if not self.keyed():
            return self.refuse(name, Refused("The console's key is missing or wrong.", 403))
        try:
            length = int(self.headers.get("Content-Length") or 0)
            params = json.loads(self.rfile.read(length) or b"{}") if length <= 4096 else None
            if not isinstance(params, dict):
                raise ValueError
        except ValueError:
            return self.refuse(name, Refused("The request was not understood.", 400))
        jobs = self.jobs
        try:
            if name == "stop":
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


def serve(port=8081, demo=False, key=None, start_job=start):
    """The console's server, bound to this computer only, and its key."""
    key = key or secrets.token_urlsafe(24)
    handler = type("ConsoleHandler", (Handler,), {
        "key": key, "port": port, "jobs": Jobs(demo, start_job), "reader": Reader(demo)})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    handler.port = server.server_address[1]   # the real one, when port 0 asked for any
    return server, key


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8081)
    ap.add_argument("--demo", action="store_true",
                    help="a simulated mount and a made-up imaging run; needs no telescope")
    ap.add_argument("--no-browser", action="store_true", help="print the address and do not open it")
    args = ap.parse_args()

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
