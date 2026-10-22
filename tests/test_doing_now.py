"""The status page's "Doing now" and imaging panel say what the telescope is
really doing (22 October 2026). During an M31 panel patrol the page said
"Doing now: Nothing running" while shoot.py had waited over five minutes for
M31-P6's first frame from a camera that had stopped sending, showed a
WASP-12 stack from two nights before under it, and once the run was stopped
by hand still read as imaging.

serve.run_now() makes the part of web/status.json the page reads; the page's
own script is then run in Node on that status, so what is tested is the
words the person sees."""
import json
import os
import re
import shutil
import subprocess
import time

import pytest

import activity
import config
import page
import serve
import stream
import tonight


@pytest.fixture
def place(tmp_path, monkeypatch):
    for path in (activity.FILE, activity._last_file(), activity._runs_file()):
        path.unlink(missing_ok=True)
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(serve, "WEB", tmp_path / "web")
    (tmp_path / "web").mkdir()
    session = tmp_path / "frames" / "M31-P6" / "20261022-043951"
    session.mkdir(parents=True)
    (session / "session.json").write_text(json.dumps({"name": "M31-P6", "frames": 19, "exposure": 16, "gain": 1500}))
    return session


def old_stack(web, name="WASP-12", when=None):
    (web / "stack.jpg").write_bytes(b"jpeg")
    (web / "stack.json").write_text(json.dumps({"kind": f"live stack of {name}",
                                                "detail": "1 accepted frames · 4 s integration"}))
    if when:
        os.utime(web / "stack.jpg", (when, when))


def waiting(session, seconds, planned=19):
    """This process imaging M31-P6, its camera asked for a frame `seconds` ago."""
    now = time.time()
    entries = activity._read()
    entries[f"{os.getpid()}-block90"] = {
        "what": "Imaging", "detail": "M31-P6", "frames": 0, "planned": planned, "exposure": 16.0,
        "session": activity._session(session), "waiting_since": now - seconds,
        "updated": now - seconds, "started": now - seconds - 5}
    activity._write(entries)


def test_a_run_waiting_on_a_silent_camera_is_running_and_says_so(place):
    waiting(place, 300)
    st = serve.run_now()
    assert st["running"] is True and st["stopped_at"] is None and st["camera_silent_s"] >= 300
    assert [a["words"] for a in st["activity"]] == [
        "Imaging M31-P6: 0 of 19 frames of 16 s — camera has sent no frame for 5 min"]


def test_a_stack_from_an_earlier_run_is_not_this_runs(place):
    old_stack(serve.WEB, when=time.time() - 2 * 86400)
    st = serve.run_now()
    assert st["stack"]["current"] is False and st["stack"]["instead"] == "no stack yet for M31-P6"
    assert st["stack"]["kind"] == "live stack of WASP-12"          # the fields already there stay


def test_a_stack_of_this_run_made_since_it_began_is_its_own(place):
    serve.WEB.joinpath("stack.jpg").write_bytes(b"jpeg")
    import snap
    snap.label("live stack of M31-P6", "3 accepted frames · 48 s integration", serve.WEB, name="stack",
               target="M31-P6")
    assert serve.run_now()["stack"]["current"] is True


def test_the_stream_shows_no_stack_that_is_not_this_runs(place, monkeypatch):
    from PIL import Image
    monkeypatch.setattr(stream, "WEB", serve.WEB)
    for name in ("stack.jpg", "latest.jpg"):
        Image.new("RGB", (4, 4)).save(serve.WEB / name)
    stack, single = stream.pictures({"stack": {"current": False}})
    assert stack is None and single is not None
    assert stream.pictures({"stack": {"current": True}})[0] is not None
    assert stream.pictures({})[0] is not None       # a status.json from before the field


def test_a_run_no_process_is_running_was_stopped(place):
    waiting(place, 30)
    activity._write({k.replace(str(os.getpid()), "999999"): v for k, v in activity._read().items()})
    st = serve.run_now()          # the page's next look finds its process gone
    assert st["running"] is False and st["finished"] is False and st["captured"] == 0
    assert abs(st["stopped_at"] - time.time()) < 5
    assert st["activity"] == [] and st["activity_last"]["stopped"]
    assert st["activity_last"]["words"] == "Imaging M31-P6: 0 of 19 frames of 16 s"


# --- the page's own script, run in Node on a status -----------------------------

NODE = shutil.which("node")

HARNESS = r"""
const vm = require("vm");
const fs = require("fs");
class El {
  constructor(id) { this.id = id; this.hidden = false; this.textContent = ""; this.innerHTML = "";
                    this.className = ""; this.style = {}; this.children = []; this.dataset = {}; }
  querySelector() { return this.img || (this.img = new El(this.id + " img")); }
  querySelectorAll() { return []; }
  replaceChildren(...c) { this.children = c; }
  append(...c) { this.children.push(...c); }
  appendChild(c) { this.children.push(c); return c; }
  setAttribute() {}
  addEventListener() {}
  get classList() { return {add() {}, remove() {}, toggle() {}}; }
}
const els = {};
const document = {
  getElementById: id => els[id] || (els[id] = new El(id)),
  createElement: tag => new El(tag), createElementNS: (ns, tag) => new El(tag),
  querySelectorAll: () => [], querySelector: () => null, addEventListener() {},
};
const context = vm.createContext({document, fetch: () => Promise.reject(new Error("none")),
                                  setInterval: () => 0, setTimeout: () => 0, console, Date, Math, JSON});
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), context);
const st = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const out = {};
context.showDoing(st.activity, st.activity_last, st.schedule);
out.doing = els["doing-lines"].innerHTML.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
out.doingHtml = els["doing-lines"].innerHTML;
out.run = context.showRun(st);
out.runState = els["run-state"] ? els["run-state"].textContent : null;
out.stackShown = context.showImage("stack", st.stack, "stack-kind", false);
out.stackDetail = els["stack-detail"] ? els["stack-detail"].textContent : null;
out.stackPicture = els["stack"] && els["stack"].img ? els["stack"].img.style.display : null;
console.log(JSON.stringify(out));
"""


def on_the_page(tmp_path, status):
    """What the page's script makes of `status`: the Doing now text, the run's
    state and the stack's caption."""
    if not NODE:
        pytest.skip("no Node to run the page's script with")
    page.write(tonight.build(config.example(), demo=True), 5, tmp_path / "index.html")
    html = (tmp_path / "index.html").read_text()
    script = re.findall(r"<script>(.*?)</script>", html, re.S)[0]
    (tmp_path / "page.js").write_text(script)
    (tmp_path / "harness.js").write_text(HARNESS)
    (tmp_path / "status.json").write_text(json.dumps(status))
    done = subprocess.run([NODE, str(tmp_path / "harness.js"), str(tmp_path / "page.js"),
                           str(tmp_path / "status.json")], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_the_page_says_what_a_patrol_is_imaging_and_that_the_camera_is_silent(place, tmp_path):
    now = time.time()
    activity._write({f"{os.getpid()}-main": {"what": "Patrol", "heading": "M31 panels",
                                             "detail": "panel 1 of 8, M31-P6", "updated": now - 400,
                                             "started": now - 400}})
    waiting(place, 300)
    old_stack(serve.WEB, when=time.time() - 2 * 86400)
    shown = on_the_page(tmp_path, serve.run_now())
    activity.clear()
    assert shown["doing"].startswith("Patrol M31 panels: panel 1 of 8, M31-P6")
    assert "Imaging M31-P6: 0 of 19 frames of 16 s — camera has sent no frame for 5 min" in shown["doing"]
    assert "Nothing running" not in shown["doing"] and 'class="inner bad"' in shown["doingHtml"]
    assert shown["run"] is True and shown["runState"] == "camera has sent no frame for 5 min"
    assert shown["stackDetail"] == "no stack yet for M31-P6" and shown["stackPicture"] == "none"


def test_the_page_says_a_stopped_run_stopped_and_when(place, tmp_path):
    waiting(place, 30)
    activity._write({k.replace(str(os.getpid()), "999999"): v for k, v in activity._read().items()})
    st = serve.run_now()
    shown = on_the_page(tmp_path, st)
    at = time.strftime("%H:%M", time.localtime(st["stopped_at"]))
    assert shown["runState"] == f"stopped at {at} with 0 of 19 frames"
    assert shown["doing"].startswith("Nothing running")
    assert "Last: Imaging M31-P6: 0 of 19 frames of 16 s, stopped" in shown["doing"]


def test_the_page_says_nothing_is_running_and_what_was_last(place, tmp_path):
    with activity.doing("Moving", "to M31-P6"):
        pass
    shown = on_the_page(tmp_path, {"activity": activity.now(), "activity_last": activity.last()})
    assert shown["doing"].startswith("Nothing running Last: Moving: to M31-P6, finished")
    assert shown["run"] is False


def test_the_page_shows_a_plain_runs_frames(place, tmp_path):
    with activity.imaging("M31-P6", 19, 16, place) as run:
        run.took(4)
        shown = on_the_page(tmp_path, serve.run_now())
    assert shown["doing"].startswith("Imaging M31-P6: 4 of 19 frames of 16 s")
    assert shown["runState"] == "waiting for the first frame"     # no frame kept in its log yet
