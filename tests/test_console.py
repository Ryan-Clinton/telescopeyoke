"""The control console: who it answers, what it will start, and in what order
it stops. Nothing here can move a real telescope: it runs in demo mode, against
the simulated mount, or with harmless commands in place of the real ones."""
import json
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import console
import interface

ROOT = Path(__file__).parent.parent
PAGE = ROOT / "console"

# A stand-in job: it waits, and ends properly when asked to as Ctrl+C would.
POLITE = ("import json, sys, time, host\n"
          "print('working', file=sys.stderr, flush=True)\n"
          # Short waits, as a script taking frames has: on Windows a request to
          # end is only noticed between calls, not in the middle of one.
          "try:\n    for _ in range(600):\n        time.sleep(0.1)\nexcept KeyboardInterrupt:\n    pass\n"
          "print(json.dumps({'ok': True, 'data': {'closed': True}, 'warnings': [], 'errors': []}))\n")
BROKEN = "import sys; print('the camera fell off', file=sys.stderr); sys.exit(1)"


@pytest.fixture
def desk(tmp_path, monkeypatch):
    """A console on a free port, in the demo, and a way to ask it things. The
    demo keeps its files in a folder of the test's own."""
    import agent
    import config
    import focus
    import horizon
    import mount
    import serve
    monkeypatch.setattr(config, "DEMO", True)
    monkeypatch.setattr(config, "DATA", tmp_path)
    for module, name, where in ((agent, "WEB", "web"), (console, "WEB", "web"), (serve, "WEB", "web"),
                                (focus, "FOCUS_FILE", "cache/focus.json"), (focus, "LIVE_FILE", "cache/focus_live.json"),
                                (focus, "FRAMES_FILE", "cache/focus_frames.jsonl"),
                                (focus, "RUNS_FILE", "cache/focus_runs.jsonl"), (horizon, "RESULTS", "cache/horizon.json"),
                                (mount, "LAST_SOLVE", "cache/last_solve.json")):
        monkeypatch.setattr(module, name, tmp_path / where)
    server, key = console.serve(port=0, demo=True, mode="app")
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def ask(path, body=None, key=key, headers=None):
        send = {"X-Console-Key": key} if key else {}
        send.update(headers or {})
        request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=send,
                                         data=None if body is None else json.dumps(body).encode())
        try:
            with urllib.request.urlopen(request, timeout=120) as reply:
                return reply.status, reply.headers, reply.read()
        except urllib.error.HTTPError as refused:
            return refused.code, refused.headers, refused.read()

    ask.json = lambda *a, **k: (lambda status, _, body: (status, json.loads(body)))(*ask(*a, **k))
    ask.jobs = server.RequestHandlerClass.jobs
    ask.server, ask.port = server, port
    yield ask
    if ask.jobs.current:
        ask.jobs.current["child"].kill()
    server.shutdown()
    server.server_close()


def stand_in(monkeypatch, script, action="focus"):
    """Have one action run a harmless script instead of its real command."""
    real = console.command

    def command(name, params, demo=False, dry_run=False):
        if name == action:
            return [sys.executable, "-c", script]
        return real(name, params, demo, dry_run)
    monkeypatch.setattr(console, "command", command)


def wait_for(test, seconds=30):
    end = time.time() + seconds
    while not test():
        assert time.time() < end, "it did not happen in time"
        time.sleep(0.05)


# --- who it answers ------------------------------------------------------------

def test_it_listens_on_this_computer_only(desk):
    assert desk.server.server_address[0] == "127.0.0.1"


def test_every_response_carries_the_headers(desk):
    for path in ("/", "/console.js", "/console.css", "/icons.svg", "/api/state", "/pictures/stack.jpg", "/nothing"):
        _, headers, _ = desk(path)
        for name, value in console.HEADERS.items():
            assert headers[name] == value, (path, name)


def test_requests_without_the_key_or_from_elsewhere_are_refused(desk):
    actions = ["/api/stop", "/api/finish", "/api/plan/home", "/api/confirm/abc"] + \
              [f"/api/action/{name}" for name in console.ACTIONS]
    for path in actions:
        assert desk(path, {}, key=None)[0] == 403, path
        assert desk(path, {}, key="wrong")[0] == 403, path
        assert desk(path, {}, headers={"Host": "evil.example"})[0] == 400, path
        assert desk(path, {}, headers={"Origin": "http://evil.example"})[0] == 403, path
    assert desk("/api/state", key=None)[0] == 403
    assert desk("/", headers={"Host": f"attacker.example:{desk.port}"})[0] == 400
    assert desk.jobs.current is None and not desk.jobs.history and not desk.jobs.plans


def test_reading_starts_nothing(desk):
    for name in ("state", "job", "night", "targets", "observing", "session", "doctor", "catalogue",
                 "focus", "horizon", "report", "system", "gallery", "rigs", "characterise", "target/M27"):
        status, answer = desk.json(f"/api/{name}")
        assert status == 200 and answer["ok"], name
    report = desk.json("/api/hardware")[1]["data"]["text"]
    assert "hardware report" in report and "as the handset names it: EQ3" in report and "Ready for mount" in report
    assert desk.jobs.current is None and not desk.jobs.history and not desk.jobs.plans
    assert desk.json("/api/state")[1]["data"]["demo"] is True


def test_only_the_named_files_and_pictures_are_served(desk):
    assert desk("/pictures/../config.toml")[0] == 404
    assert desk("/pictures/index.html")[0] == 404
    assert desk("/console.py")[0] == 404
    assert desk("/config.toml")[0] == 404


def test_the_night_is_reported_as_the_status_page_shows_it(desk):
    import config
    import page
    import tonight
    report = desk.json("/api/report")[1]["data"]
    rep = tonight.build(config.example(), demo=True)
    assert [c["title"] for c in report["cards"]] == [c[0] for c in page.card_data(rep)]
    assert report["conditions"] == page.conditions(rep)
    assert report["weather_head"] == tonight.WEATHER_HEAD and len(report["weather_rows"]) == len(rep["weather"]["hours"])
    assert len(report["targets"]) == 40 and report["targets"][0]["row"][1] == rep["targets"][0]["id"]
    assert {"tags", "score", "best", "start", "end", "now"} <= set(report["targets"][0])
    assert all(hour["level"] in ("good", "fair", "bad") for hour in report["hours"])
    assert desk.json("/api/system")[1]["data"]["rows"][0].keys() == {"label", "text", "level"}


def test_rig_knowledge_says_how_each_measurement_is_started(desk):
    found = desk.json("/api/characterise")[1]["data"]
    by_action = {item["action"]: item for item in found["items"] if item["action"]}
    assert found["of"] == len(found["items"]) == 12
    # Anything that moves the mount, or stops it following the sky, is a plan first.
    assert all(by_action[name]["plan"] for name in ("polar", "polar-repeat", "pointing-survey", "creep-response", "camera-trail"))
    assert not by_action["camera-timing"]["plan"] and not by_action["focus"]["plan"]
    page = (PAGE / "index.html").read_text(encoding="utf-8")
    assert 'id="knowledge"' in page and 'data-task="knowledge" data-only="app"' in page


def test_the_demo_keeps_its_own_pictures_and_tells_the_pretend_sky(desk, tmp_path):
    # Nothing the real camera, webcam or satellite left in web/ is shown in the demo.
    assert desk("/pictures/stack.jpg?v=123")[0] == 404 and desk("/pictures/clouds.jpg")[0] == 404
    assert desk.json("/api/gallery")[1]["data"]["pictures"] == []
    (tmp_path / "web").mkdir(exist_ok=True)
    (tmp_path / "web" / "stack.jpg").write_bytes(b"made up")
    assert desk("/pictures/stack.jpg?v=124")[2] == b"made up"
    assert desk.json("/api/session")[1]["data"] == {"none": True}        # no run yet is not a fault

    sky = desk.json("/api/state")[1]["data"]["sky"]
    assert sky["cloud"] is False and sky["unplugged"] is False
    assert desk.json("/api/demo", {"cloud": True, "turn": -1})[1]["data"]["sky"]["cloud"] is True
    assert desk.json("/api/demo", {"turn": 1})[1]["data"]["sky"]["focus"] == sky["focus"]
    for bad in ({"cloud": "yes"}, {"turn": 5}):
        assert desk.json("/api/demo", bad)[0] == 409
    for action in console.NOT_IN_DEMO:
        path = "plan" if console.ACTIONS[action].get("moves") else "action"
        answer = desk.json(f"/api/{path}/{action}", {"kind": "dark"})[1]
        assert answer["errors"][0]["code"] == "DEMO_UNSUPPORTED", action


def test_finished_pictures_are_served_by_name_and_nothing_else(tmp_path, monkeypatch):
    import serve
    (tmp_path / "M27-final.jpg").write_bytes(b"picture")
    (tmp_path / "secret.txt").write_text("no")
    monkeypatch.setattr(serve, "WEB", tmp_path)
    monkeypatch.setattr(console, "WEB", tmp_path)
    server, key = console.serve(port=0, demo=False)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        assert urllib.request.urlopen(f"{base}/pictures/M27-final.jpg").read() == b"picture"
        for name in ("secret.txt", "../console.py", "M27-final.jpg/../secret.txt"):
            with pytest.raises(urllib.error.HTTPError):
                urllib.request.urlopen(f"{base}/pictures/{name}")
    finally:
        server.shutdown()
        server.server_close()


# --- the page's own files ---------------------------------------------------------

def test_the_page_has_nothing_inline_and_loads_nothing_from_the_internet():
    page = (PAGE / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<style|style=|<script(?![^>]*\bsrc=)[^>]*>|\son\w+=", page)
    for name in ("index.html", "console.css", "console.js"):
        text = (PAGE / name).read_text(encoding="utf-8")
        assert not re.search(r"https?://(?!www\.w3\.org)", text), name
        assert ".style." not in text and "innerHTML" not in text, name


def test_there_are_no_emoji_in_the_page():
    emoji = re.compile("[\U0001F000-\U0001FAFF☀-⛿⭐⭕️]")
    for path in PAGE.iterdir():
        if path.suffix not in (".png", ".ico"):       # the icon's pictures are not text
            assert not emoji.search(path.read_text(encoding="utf-8")), path.name


def test_the_page_takes_the_key_out_of_the_address_and_says_demo():
    script = (PAGE / "console.js").read_text(encoding="utf-8")
    assert "history.replaceState(null, \"\", location.pathname + location.hash)" in script
    assert "DEMO: no real telescope is being controlled" in (PAGE / "index.html").read_text(encoding="utf-8")


def test_the_status_page_and_the_mcp_server_still_offer_no_action():
    import serve
    assert not hasattr(serve.Handler, "do_POST")
    assert "console" not in (ROOT / "serve.py").read_text(encoding="utf-8")
    assert "console" not in (ROOT / "mcp_server.py").read_text(encoding="utf-8")
    assert not (ROOT / "web" / "console.js").exists()


# --- what it will start ------------------------------------------------------------

def test_every_action_builds_exactly_its_command():
    def tail(action, params=None, **more):
        cmd = console.command(action, params or {}, **more)
        assert cmd[0] == sys.executable and Path(cmd[1]).parent == ROOT and cmd[-1] == "--json"
        return [Path(cmd[1]).name] + cmd[2:-1]

    assert tail("goto", {"target": "m27"}) == ["mount.py", "goto", "M27"]
    assert tail("goto", {"target": "Dumbbell Nebula", "solve": True}) == ["mount.py", "goto", "M27", "--solve"]
    assert tail("home") == ["mount.py", "home"] and tail("zenith") == ["mount.py", "zenith"]
    assert tail("home", demo=True, dry_run=True) == ["mount.py", "home", "--dry-run"]
    assert tail("sync") == ["mount.py", "sync"] and tail("drift") == ["mount.py", "drift"]
    assert tail("compensate") == ["mount.py", "compensate"] and tail("position") == ["mount.py", "status"]
    assert tail("run", {"target": "M27", "frames": 300, "exposure": "auto", "gain": 300, "assist": True}) == \
        ["shoot.py", "M27", "--frames", "300", "--exposure", "auto", "--gain", "300", "--assist"]
    assert tail("run", {"target": "M27", "frames": 300, "exposure": "auto", "gain": 300, "assist": True,
                        "recentre": False}) == \
        ["shoot.py", "M27", "--frames", "300", "--exposure", "auto", "--gain", "300", "--no-recentre"]
    assert tail("run", {"target": "M27"}) == ["shoot.py", "M27", "--frames", "60", "--exposure", "2", "--gain", "1500"]
    assert tail("focus") == ["focus.py"] and tail("focus", {"sound": "sound"}) == ["focus.py"]
    assert tail("focus", {"sound": "silent"}) == ["focus.py", "--quiet"]
    assert tail("horizon", {"trace": True, "daylight": True}) == ["horizon.py", "--trace", "--daylight"]
    assert tail("horizon", {"trace": True, "fresh": True}) == ["horizon.py", "--trace", "--fresh"]
    assert tail("horizon-forget") == ["horizon.py", "--forget"]
    # The skyline from a phone panorama: none of it moves the mount or needs a plan.
    assert tail("panorama-use", {"file": " /home/me/My Pictures/garden.jpg "}) == \
        ["panorama.py", "use", "/home/me/My Pictures/garden.jpg"]
    assert tail("panorama-also", {"file": "C:/Users/me/high.jpg"}) == ["panorama.py", "also", "C:/Users/me/high.jpg"]
    assert tail("panorama-mark", {"x": 0.25, "y": "0.4", "bearing": 137, "height": 24.5}) == \
        ["panorama.py", "mark", "0.25", "0.4", "137", "24.5", "--picture", "1"]
    assert tail("panorama-mark", {"x": 0.25, "y": 0.4, "telescope": True, "picture": 2}) == \
        ["panorama.py", "mark", "0.25", "0.4", "--telescope", "--picture", "2"]
    assert tail("panorama-mark", {"x": 0.25, "y": 0.4, "landmark": "Old Chimney"}) == \
        ["panorama.py", "mark", "0.25", "0.4", "--landmark", "old-chimney", "--picture", "1"]
    assert tail("panorama-move", {"points": [[0.5, 0.25], [0.51, 0.3]], "picture": 3}) == \
        ["panorama.py", "move", "0.5000,0.2500", "0.5100,0.3000", "--picture", "3"]
    assert tail("panorama-unmark", {"mark": 2}) == ["panorama.py", "unmark", "2", "--picture", "1"]
    assert tail("panorama-save") == ["panorama.py", "save"] and tail("panorama-clear") == ["panorama.py", "clear"]
    for action in ("panorama-use", "panorama-also", "panorama-mark", "panorama-unmark", "panorama-move",
                   "panorama-save", "panorama-clear", "horizon-forget"):
        assert action in console.WORKSTATION and not console.moves(action, {})
    # Asking the mount where it points holds the mount; a mark typed in holds nothing.
    assert console.uses("panorama-mark", {"telescope": True}) == "mount" and console.uses("panorama-mark", {}) is None
    for action, bad in (("panorama-use", {"file": "--help"}), ("panorama-use", {"file": ""}), ("panorama-use", {}),
                        ("panorama-use", {"file": "a\nb.jpg"}), ("panorama-use", {"file": "x" * 500}),
                        ("panorama-mark", {"x": 2, "y": 0.5, "bearing": 10, "height": 10}),
                        ("panorama-mark", {"x": 0.5, "y": 0.5, "bearing": 400, "height": 10}),
                        ("panorama-mark", {"x": 0.5, "y": 0.5}), ("panorama-mark", {"x": 0.5, "y": 0.5, "landmark": "../x"}),
                        ("panorama-move", {"points": []}), ("panorama-move", {"points": [[0.5, "0.5; ls"]]}),
                        ("panorama-move", {"points": [[0.5]]}), ("panorama-move", {"points": [[0.5, 0.5]], "picture": 9}),
                        ("panorama-unmark", {})):
        with pytest.raises(console.Refused):
            console.command(action, bad)
    assert tail("camera-setup") == ["camera_setup.py", "--open"]
    assert tail("polar") == ["polaralign.py"] and console.moves("polar", {})
    assert tail("point", {"bearing": "112.5", "height": 8}) == ["mount.py", "point", "112.5", "8"]
    assert tail("landmark-remember", {"name": "Old Chimney"}) == ["landmark.py", "remember", "old-chimney"]
    assert tail("landmark-check", {"name": "mast"}) == ["landmark.py", "check", "mast", "--watch", "40"]
    # Polar alignment by day: the check moves nothing, the other two say what they will do first.
    assert tail("polaris-check") == ["polaris.py", "check"] and not console.moves("polaris-check", {})
    assert tail("polaris-find") == ["polaris.py", "find", "--record"] and console.moves("polaris-find", {})
    assert tail("polaris-find", {"anyway": True})[-1] == "--anyway"
    assert tail("polaris-align") == ["polaris.py", "align", "--watch", "60"] and console.moves("polaris-align", {})
    for action in ("polaris-check", "polaris-find", "polaris-align"):
        assert action in console.WORKSTATION and action in console.NOT_IN_DEMO
    for bad in ({"name": "../x"}, {"name": ""}, {"bearing": 400, "height": 5}, {"bearing": 10, "height": 0}):
        with pytest.raises(console.Refused):
            console.command("landmark-check" if "name" in bad else "point", bad)
    assert tail("camera-capabilities") == ["camera_test.py", "--capabilities"]
    assert tail("camera-throughput") == ["camera_test.py", "--throughput"]
    assert tail("camera-gain-sweep") == ["camera_test.py", "--gain-sweep"]
    assert tail("calibrate", {"kind": "flat"}) == ["calibrate.py", "flat", "--frames", "20", "--exposure", "2", "--gain", "1500"]
    assert tail("restack", {"target": "M27", "all": True}) == ["restack.py", "M27", "--all"]
    assert tail("run-finish") == ["ty", "run", "stop"] and tail("run-recentre") == ["ty", "run", "recentre"]
    assert tail("run-assist-on") == ["ty", "run", "assist-on"] and tail("run-assist-off") == ["ty", "run", "assist-off"]
    assert tail("polar-repeat") == ["polaralign.py", "--repeat", "5", "--step", "12"]
    assert tail("polar-repeat", {"step": 20}, dry_run=True) == ["polaralign.py", "--repeat", "5", "--step", "20", "--dry-run"]
    assert tail("pointing-survey") == ["mount.py", "pointing"] and tail("creep-response") == ["mount.py", "response"]
    assert tail("camera-timing") == ["camera_test.py", "--timing"]
    assert tail("camera-trail", dry_run=True) == ["camera_test.py", "--trail", "--dry-run"]
    # Every script the table names exists, and every moving one can be planned.
    for name, spec in console.ACTIONS.items():
        assert (ROOT / spec["command"]({"target": "M27", "name": "mast", "bearing": 90, "height": 10, "file": "/a.jpg",
                                        "x": 0.5, "y": 0.5, "mark": 1, "points": [[0.5, 0.5]]})[0]).exists(), name


def test_nothing_from_the_browser_reaches_a_command_line(desk, monkeypatch):
    started = []
    monkeypatch.setattr(desk.jobs, "start", lambda cmd, **more: started.append(cmd))
    for bad in ("M27; rm -rf /", "$(reboot)", "--port=/dev/null", "../../etc/passwd", "", "x" * 200):
        for path in ("/api/plan/goto", "/api/plan/run", "/api/action/restack"):
            status, answer = desk.json(path, {"target": bad})
            assert not answer["ok"] and status == 409, (path, bad)
    assert desk.json("/api/action/calibrate", {"kind": "dark; ls"})[1]["ok"] is False
    assert desk.json("/api/action/calibrate", {"kind": "dark", "frames": "20 --help"})[1]["ok"] is False
    assert desk.json("/api/plan/run", {"target": "M27", "exposure": "9; ls"})[1]["ok"] is False
    assert desk.json("/api/action/format-disk", {})[0] == 404
    assert desk.json("/api/plan/../../mount", {})[1]["ok"] is False
    assert not started


def test_a_move_needs_a_plan_that_works_once(desk):
    for action, spec in console.ACTIONS.items():
        if spec.get("moves"):
            status, answer = desk.json(f"/api/action/{action}", {"target": "M27"})
            assert status == 409 and "needs a confirmed plan" in answer["errors"][0]["message"], action
    assert desk.json("/api/plan/sync", {})[1]["ok"] is False      # not a move: nothing to plan
    assert desk.json("/api/confirm/not-a-plan", {})[0] == 410

    status, answer = desk.json("/api/plan/zenith", {})
    assert status == 200 and answer["data"]["plan"]["would_move"]
    plan = answer["data"]["id"]
    status, answer = desk.json(f"/api/confirm/{plan}", {})
    assert status == 200 and answer["data"]["job"]["action"] == "zenith"
    assert desk.json(f"/api/confirm/{plan}", {})[0] == 410          # twice
    wait_for(lambda: desk.jobs.current is None)
    job = desk.jobs.history[-1]
    assert job["outcome"] == "finished"

    # It ends where the command typed by hand ends.
    by_hand = json.loads(subprocess.run([sys.executable, str(ROOT / "mount.py"), "--demo", "zenith", "--json"],
                                        capture_output=True, text=True, cwd=ROOT).stdout)["data"]
    for axis in ("ra_axis_deg", "dec_axis_deg"):
        assert job["result"][axis] == pytest.approx(by_hand[axis], abs=0.05)


def test_a_plan_expires(desk, monkeypatch):
    plan = desk.json("/api/plan/home", {})[1]["data"]["id"]
    monkeypatch.setattr(console, "PLAN_LIFE", 0)
    assert desk.json(f"/api/confirm/{plan}", {})[0] == 410
    assert desk.jobs.current is None


def test_confirm_makes_the_plan_again(desk, monkeypatch):
    seen = {"would_move": True, "safe": True, "altitude_deg": 48.0, "hour_angle_hours": 2.0,
            "pier_side": "west", "target": "M27", "warnings": ["The tube will swing over the pole."]}
    answers = [dict(seen), dict(seen, altitude_deg=48.4, hour_angle_hours=2.03)]
    monkeypatch.setattr(desk.jobs, "dry_run", lambda action, params: answers.pop(0))
    started = []
    monkeypatch.setattr(desk.jobs, "begin", lambda action, params, stops=None: started.append(action) or {"job": {}})
    plan = desk.json("/api/plan/goto", {"target": "M27"})[1]["data"]["id"]
    assert "job" in desk.json(f"/api/confirm/{plan}", {})[1]["data"]      # the sky moved a little: still the plan
    assert started == ["goto"]

    # The target has crossed the meridian since: nothing starts; a new plan comes back.
    answers[:] = [dict(seen), dict(seen, pier_side="east", warnings=[]), dict(seen, pier_side="east", warnings=[])]
    plan = desk.json("/api/plan/goto", {"target": "M27"})[1]["data"]["id"]
    answer = desk.json(f"/api/confirm/{plan}", {})[1]["data"]
    assert answer["changed"] and answer["id"] != plan and answer["plan"]["pier_side"] == "east"
    assert started == ["goto"]

    # It has set, or the lock has gone on: refused, and nothing starts.
    def locked(action, params):
        raise console.PlanRefused(interface.error("MOTION_LOCKED", "Motion is locked: testing"))
    answers[:] = [dict(seen)]
    plan = desk.json("/api/plan/goto", {"target": "M27"})[1]["data"]["id"]
    monkeypatch.setattr(desk.jobs, "dry_run", locked)
    status, answer = desk.json(f"/api/confirm/{plan}", {})
    assert status == 200 and answer["data"]["refused"]["code"] == "MOTION_LOCKED"
    assert desk.json("/api/plan/home", {})[1]["data"]["refused"]["code"] == "MOTION_LOCKED"
    assert started == ["goto"]
    assert desk.json("/api/stop", {})[1]["data"]["stopped"]             # Stop still works


def test_the_simulated_mount_refuses_what_the_real_one_would(desk):
    status, answer = desk.json("/api/plan/goto", {"target": "Polaris"})
    assert status == 409 and answer["errors"][0]["code"] == "TARGET_UNKNOWN"


# --- one job, finishing, and Stop ------------------------------------------------------

def test_one_job_at_a_time_and_reading_still_answers(desk, monkeypatch):
    stand_in(monkeypatch, POLITE)
    assert desk.json("/api/action/focus", {})[1]["ok"]
    status, answer = desk.json("/api/action/restack", {"target": "M27"})
    assert status == 409 and "Busy: Focusing is running" in answer["errors"][0]["message"]
    plan = desk.json("/api/plan/home", {})[1]["data"]["id"]
    assert "Busy" in desk.json(f"/api/confirm/{plan}", {})[1]["errors"][0]["message"]
    assert desk.json("/api/state")[1]["ok"]
    running = desk.json("/api/job")[1]["data"]["running"]
    assert running["label"] == "Focusing" and running["state"] == "running"


def test_finishing_lets_the_job_close_and_the_next_one_start(desk, monkeypatch):
    stand_in(monkeypatch, POLITE)
    desk.json("/api/action/focus", {})
    wait_for(lambda: desk.jobs.current and desk.jobs.current["lines"])      # it is up and waiting
    assert desk.json("/api/finish", {})[1]["data"]["finishing"] == "Focusing"
    wait_for(lambda: desk.jobs.current is None)
    job = desk.jobs.history[-1]
    assert job["outcome"] == "finished" and job["result"] == {"closed": True}     # it ended itself; not killed
    assert desk.json("/api/action/focus", {})[1]["ok"]                           # and the camera is free again
    assert desk.json("/api/finish", {})[1]["ok"]


def test_a_job_that_will_not_end_is_killed_after_the_wait(desk, monkeypatch):
    monkeypatch.setattr(console, "FINISH_WAIT", 0.5)
    stand_in(monkeypatch, "import time, signal, sys, host\n"
                          "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
                          "getattr(signal, 'SIGBREAK', None) and signal.signal(signal.SIGBREAK, signal.SIG_IGN)\n"
                          "print('deaf', file=sys.stderr, flush=True)\ntime.sleep(60)")
    desk.json("/api/action/focus", {})
    wait_for(lambda: desk.jobs.current and desk.jobs.current["lines"])
    desk.json("/api/finish", {})
    wait_for(lambda: desk.jobs.current is None, seconds=15)


def test_the_three_outcomes_are_kept_apart(desk, monkeypatch):
    refused = desk.json("/api/plan/goto", {"target": "Vega"})[1]
    if "refused" in refused["data"]:                       # below a limit at this hour: a refusal, not a fault
        assert refused["ok"] and refused["data"]["refused"]["code"].startswith("TARGET_")
    stand_in(monkeypatch, BROKEN)
    desk.json("/api/action/focus", {})
    wait_for(lambda: desk.jobs.history)
    failed = desk.jobs.history[-1]
    assert failed["outcome"] == "failed" and "the camera fell off" in failed["error"]["message"]
    desk.json("/api/action/position", {})
    wait_for(lambda: len(desk.jobs.history) == 2)
    assert desk.jobs.history[-1]["outcome"] == "finished"
    assert desk.jobs.position["at_home"] is True


def test_stop_ends_the_mount_job_first_and_lets_nothing_reopen_the_mount(desk, monkeypatch):
    stand_in(monkeypatch, POLITE, action="zenith")
    real_dry_run = desk.jobs.dry_run
    monkeypatch.setattr(desk.jobs, "dry_run", lambda action, params: {"would_move": True, "safe": True})
    plan = desk.json("/api/plan/zenith", {})[1]["data"]["id"]
    desk.json(f"/api/confirm/{plan}", {})
    wait_for(lambda: desk.jobs.current and desk.jobs.current["lines"])
    child = desk.jobs.current["child"]
    spare = desk.json("/api/plan/home", {})[1]["data"]["id"]
    order, real_run = [], subprocess.run

    def stopping(cmd, **more):
        # By the time the handset is told to stop, the job has gone and its port is free.
        order.append(("stop sent", child.poll() is not None, desk.jobs.stopping))
        # Meanwhile nothing else may open the mount: not a confirm, not anything.
        with pytest.raises(console.Refused, match="Stop is under way"):
            desk.jobs.confirm(spare)
        with pytest.raises(console.Refused, match="Stop is under way"):
            desk.jobs.begin("position", {})
        assert cmd[-3:] == ["--demo", "stop", "--json"][-3:] or cmd[-2:] == ["stop", "--json"]
        return real_run(cmd, **more)
    monkeypatch.setattr(console.subprocess, "run", stopping)
    status, answer = desk.json("/api/stop", {})
    monkeypatch.setattr(desk.jobs, "dry_run", real_dry_run)
    assert order == [("stop sent", True, True)]
    assert answer["data"]["stopped"] and answer["data"]["ended_job"] == "Zenith" and answer["data"]["seconds"] < 20
    wait_for(lambda: desk.jobs.history)
    assert desk.jobs.history[-1]["outcome"] == "stopped" and desk.jobs.stopping is False
    assert desk.jobs.current is None


def test_stop_with_nothing_running_still_tells_the_mount(desk):
    status, answer = desk.json("/api/stop", {})
    assert status == 200 and answer["data"]["stopped"] and answer["data"]["ended_job"] is None


def test_stop_leaves_a_camera_job_alone(desk, monkeypatch):
    stand_in(monkeypatch, POLITE)
    desk.json("/api/action/focus", {})
    wait_for(lambda: desk.jobs.current and desk.jobs.current["lines"])
    assert desk.json("/api/stop", {})[1]["data"]["ended_job"] is None
    assert desk.jobs.current and desk.jobs.current["child"].poll() is None


def test_a_confirm_already_on_its_way_is_dead_once_stop_is_pressed(desk, monkeypatch):
    """Confirm makes the plan again before starting, which takes a moment. Stop
    pressed in that moment must kill the request for good: it may not start
    the mount after Stop has finished."""
    plan_made, let_go, started = threading.Event(), threading.Event(), []
    plan = {"would_move": True, "safe": True, "altitude_deg": 50.0, "hour_angle_hours": 1.0, "pier_side": "west"}
    calls = []

    def slow_dry_run(action, params):
        calls.append(action)
        if len(calls) == 2:          # the second making of the plan, inside Confirm
            plan_made.set()
            assert let_go.wait(20)
        return dict(plan)
    monkeypatch.setattr(desk.jobs, "dry_run", slow_dry_run)
    monkeypatch.setattr(desk.jobs, "start", lambda cmd, **more: started.append(cmd))
    plan_id = desk.json("/api/plan/zenith", {})[1]["data"]["id"]
    answer = {}
    confirm = threading.Thread(target=lambda: answer.update(reply=desk.json(f"/api/confirm/{plan_id}", {})))
    confirm.start()
    assert plan_made.wait(20)
    assert desk.json("/api/stop", {})[1]["data"]["stopped"]      # Stop runs, and finishes
    assert desk.jobs.stopping is False
    let_go.set()
    confirm.join(20)
    status, reply = answer["reply"]
    assert status == 409 and "Stop was pressed" in reply["errors"][0]["message"]
    assert not started and desk.jobs.current is None
    # A plan made after Stop is a new request by the person, and works.
    monkeypatch.setattr(desk.jobs, "dry_run", lambda action, params: dict(plan))
    fresh = desk.json("/api/plan/zenith", {})[1]["data"]["id"]
    monkeypatch.setattr(desk.jobs, "begin", lambda action, params, stops=None: {"job": {"action": action}})
    assert desk.json(f"/api/confirm/{fresh}", {})[1]["data"]["job"]["action"] == "zenith"


def test_a_run_without_recentring_is_a_camera_job_and_needs_no_plan(desk, monkeypatch):
    still = {"target": "M27", "recentre": False, "assist": True}
    assert console.uses("run", still) == "camera" and not console.moves("run", still)
    assert console.uses("run", {"target": "M27"}) == "mount" and console.moves("run", {"target": "M27"})
    assert "--assist" not in console.command("run", still) and "--no-recentre" in console.command("run", still)
    assert desk.json("/api/plan/run", still)[1]["ok"] is False          # nothing to plan
    assert desk.json("/api/action/run", {"target": "M27"})[0] == 409    # with re-centring: a plan first

    stand_in(monkeypatch, POLITE, action="run")
    # No run going: the console does not pass on orders that move the mount.
    assert "No imaging run started from this console" in desk.json("/api/action/run-recentre", {})[1]["errors"][0]["message"]
    assert desk.json("/api/action/run", still)[1]["ok"]
    wait_for(lambda: desk.jobs.current and desk.jobs.current["lines"])
    assert desk.json("/api/job")[1]["data"]["run_scope"] == {"mount": False}
    for order in console.MOVING_ORDERS:
        status, answer = desk.json(f"/api/action/{order}", {})
        assert status == 409 and "without re-centring" in answer["errors"][0]["message"], order
    # Stop is for the mount: this run is only taking frames, and carries on.
    assert desk.json("/api/stop", {})[1]["data"]["ended_job"] is None
    assert desk.jobs.current["child"].poll() is None
    desk.json("/api/finish", {})
    wait_for(lambda: desk.jobs.current is None)
    assert desk.jobs.run_scope is None


def test_closing_the_console_always_tells_the_mount_to_stop(desk, monkeypatch):
    sent, real_run = [], subprocess.run

    def run(cmd, **more):
        sent.append(cmd[-2:])
        return real_run(cmd, **more)
    monkeypatch.setattr(console.subprocess, "run", run)
    assert desk.jobs.close()["stopped"] and sent == [["stop", "--json"]]      # nothing was running

    stand_in(monkeypatch, POLITE)
    desk.json("/api/action/focus", {})
    wait_for(lambda: desk.jobs.current and desk.jobs.current["lines"])
    child = desk.jobs.current["child"]
    assert desk.jobs.close()["stopped"] and len(sent) == 2                   # a camera job was running
    assert child.poll() is not None
    wait_for(lambda: desk.jobs.history)
    assert desk.jobs.history[-1]["result"] == {"closed": True}               # and it was let close the camera


# --- the application's window and the companion page ---------------------------------

def test_the_companion_page_is_refused_what_belongs_to_the_application():
    server, key = console.serve(port=0, demo=False)          # as "console.py" in a browser starts it
    threading.Thread(target=server.serve_forever, daemon=True).start()
    jobs, started = server.RequestHandlerClass.jobs, []
    jobs.start = lambda cmd, **more: started.append(cmd)
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def post(path, body=None):
        request = urllib.request.Request(base + path, data=json.dumps(body or {}).encode(),
                                         headers={"X-Console-Key": key})
        try:
            with urllib.request.urlopen(request, timeout=60) as reply:
                return reply.status, json.loads(reply.read())
        except urllib.error.HTTPError as refused:
            return refused.code, json.loads(refused.read())
    try:
        assert jobs.mode == "companion"
        for action in console.WORKSTATION:
            if action == "open-settings":
                continue
            path = "plan" if console.ACTIONS[action].get("moves") else "action"
            status, answer = post(f"/api/{path}/{action}", {"target": "M27", "kind": "dark"})
            assert status == 403 and "TelescopeYoke application" in answer["errors"][0]["message"], action
        assert post("/api/open/settings")[0] == 403
        request = urllib.request.Request(base + "/api/state", headers={"X-Console-Key": key})
        state = json.loads(urllib.request.urlopen(request, timeout=60).read())["data"]
        assert state["mode"] == "companion" and not set(state["available"]) & set(console.WORKSTATION)
        assert {"goto", "run", "focus", "run-finish"} <= set(state["available"])     # observing is all there
        assert not started
    finally:
        server.shutdown()
        server.server_close()


def test_the_application_offers_everything_and_says_how_it_is_set_up(desk):
    state = desk.json("/api/state")[1]["data"]
    assert state["mode"] == "app" and state["version"] and state["mount_link"] == "handset"
    assert state["settings_file"].endswith("config.toml") and state["camera_backend"] in ("indi", "altair")
    # The demo has no settings of its own to edit.
    status, answer = desk.json("/api/open/settings", {})
    assert status == 409 and answer["errors"][0]["code"] == "DEMO_UNSUPPORTED"


def test_opening_the_settings_makes_them_from_the_example_first(tmp_path, monkeypatch):
    import config
    import host
    opened = []
    monkeypatch.setattr(config, "FILE", tmp_path / "config.toml")
    monkeypatch.setattr(host, "open_file", opened.append)
    server, key = console.serve(port=0, demo=False, mode="app")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    request = urllib.request.Request(f"http://127.0.0.1:{server.server_address[1]}/api/open/settings",
                                     data=b"{}", headers={"X-Console-Key": key})
    try:
        answer = json.loads(urllib.request.urlopen(request, timeout=60).read())["data"]
        assert answer["created"] and opened == [tmp_path / "config.toml"]
        assert (tmp_path / "config.toml").read_text(encoding="utf-8") == config.EXAMPLE.read_text(encoding="utf-8")
    finally:
        server.shutdown()
        server.server_close()


def test_the_page_keeps_the_equipment_screens_to_the_application():
    page = (PAGE / "index.html").read_text(encoding="utf-8")
    for screen in ("camera", "telescope", "solver", "webcam", "polar", "landmark", "horizon", "calibration", "testing",
                   "processing", "rigs", "doctor", "settings", "logs", "about", "welcome"):
        assert re.search(rf'<section id="{screen}" class="task" data-only="app"', page), screen
    for screen in ("home", "targets", "imaging", "focus", "mount"):
        assert re.search(rf'<section id="{screen}" class="task"(?! data-only)', page), screen
    assert '<section id="status" class="task" data-only="companion"' in page


def test_a_target_comes_with_how_it_fits_the_camera(desk):
    framing = desk.json("/api/target/M31")[1]["data"]["framing"]
    # The example's 183C behind 750 mm: about 1.0 by 0.67 degrees, 0.66 arcseconds a pixel.
    assert framing["field_deg"] == pytest.approx([0.997, 0.669], abs=0.01) and framing["scale_arcsec_px"] == 0.66
    assert framing["size_arcmin"] > 60                      # Andromeda is far wider than the frame
    assert desk.json("/api/target/Vega")[1]["data"]["framing"]["size_arcmin"] is None
