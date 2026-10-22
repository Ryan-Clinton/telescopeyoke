#!/usr/bin/env python3
"""Stream the telescope live to YouTube, Twitch or both while it is imaging.

    ./stream.py                    what it would do now, and why; streams nothing
    ./stream.py watch              keep watching: stream while a run is imaging, stop when it is not
    ./stream.py watch --to F.mp4   the same into a file, to try it with no account and no key
    ./stream.py watch --install    run `watch` as a systemd user service, from boot; it idles while off
    ./stream.py frame              make one picture of what would be sent, as cache/stream-preview.jpg
    ./stream.py preview            the new look (docs/stream-look.md) in each state, as cache/stream-preview/*.png
    ./stream.py twitch-login       once: let it set the Twitch channel's title, category and tags (twitch.py)
    ./stream.py key                paste the stream key in (not shown as typed); kept readable only by you
    ./stream.py key youtube        the same for one service, when streaming to more than one

Off unless [stream] enabled in config.toml (the Settings screen has it).
Where it goes is [stream] service: "youtube", "twitch", or "custom" with
[stream] url; or several at once, as a list (["youtube", "twitch"]) or
joined with + ("youtube+twitch", which is what the Settings screen writes).
The picture is encoded once and sent to every one through ffmpeg's tee
muxer, each with onfail=ignore, so one service dropping the stream leaves
the others on air (the dropped one comes back at the next start).

A stream key is the person's and works like a password: kept readable only
by them under ~/.config/telescopeyoke/, never in config.toml, never shown,
never written to a log. Each service has its own file, stream-key-youtube,
stream-key-twitch or stream-key-custom (`./stream.py key SERVICE`). The
plain stream-key (`./stream.py key`) is the key when there is one service,
as it always was, and when there are several it is still the Twitch key
when stream-key-twitch is missing: it held the Twitch key before there
were two. A service with no key is left out, said once, and the stream goes
to the others.

What is sent: the running stack, beside the newest frame, with the target,
how many frames, and what is next. Nothing else: no webcam, no cloud map,
nothing that names the place (the same rule as the status page and the
site's live page). The pictures change every few seconds, so a few frames a
second are sent, the picture repeating between updates, with a sound track
as the services expect: silent, but for the focus tones while focusing
([stream] focus_tones, on unless set false). The video is encoded by the laptop's own
video hardware where it has some (Intel Quick Sync, through VAAPI), so it
does not take the processors the stacking needs.

It starts when a run's newest frame is under START_S old, or while the
telescope focuses or is polar aligned (observatory(): their own files, with
a look of their own and the focus tones as the sound), and stops when
nothing new has come for STOP_S: cloud, the end of the night, or the
telescope put away. YouTube makes and ends a broadcast by itself when its stream key
has Auto-start and Auto-stop on; Twitch goes live when the stream arrives.
"""
import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

import config

WEB = config.DATA / "web"
KEY_FILE = Path(os.path.expanduser("~/.config/telescopeyoke/stream-key"))
PREVIEW = config.DATA / "cache" / "stream-preview.jpg"   # not web/: that goes on the pages
PROGRESS = config.DATA / "cache" / "stream-progress.txt"   # ffmpeg's own speed reports
WIDTH, HEIGHT = 1920, 1080
FALLBACK = (1280, 720)  # when the upload cannot keep up with 1080p
BITRATE = {(1920, 1080): "5000k", (1280, 720): "3000k"}
FPS = 30                # frames a second sent, as the services expect
INPUT_FPS = 10          # pictures a second handed to ffmpeg, which repeats each up to FPS
FADE = 3                # pictures in a crossfade: 300 ms
SLOW_S = 60             # falling behind this long (sustained, not a blip): go down to FALLBACK
BREAKS = 3              # the stream breaking off this often within BREAKS_S at 1080p: go down too
BREAKS_S = 600
TEST_S = 20             # Twitch's bandwidth test at the start: seconds of 1080p sent and not shown
BETWEEN_S = 15 * 60     # stay on air between targets when the next step is due within this
END_S = 120             # the end-of-night card is held this long
MEASURE_S = 300         # a transit's light curve is measured again this often
START_S = 120           # a run whose newest frame is younger than this is imaging
LOOK_S = 2              # how often the focus and polar files are looked at while watching
STOP_S = 300            # no new frame for this long: stop streaming
INGEST = {
    "youtube": "rtmp://a.rtmp.youtube.com/live2/{key}",
    "twitch": "rtmp://live.twitch.tv/app/{key}",
}


NAMES = {"youtube": "YouTube", "twitch": "Twitch", "custom": "the custom address"}


def settings():
    found = config.hardware().get("stream", {})
    return {"enabled": bool(found.get("enabled", False)), "service": found.get("service", "youtube"),
            "url": found.get("url", ""), "tones": bool(found.get("focus_tones", True))}


def services(s):
    """The services streamed to, in order: [stream] service as one name, a
    list of names, or names joined with +."""
    found = s["service"]
    names = found if isinstance(found, (list, tuple)) else str(found).split("+")
    out = []
    for name in (str(n).strip().lower() for n in names):
        if name and name not in out:
            out.append(name)
    return out or ["youtube"]


def key_file(service=None):
    """Where a service's own key is kept; KEY_FILE, the plain one, for None."""
    return KEY_FILE if service is None else KEY_FILE.with_name(f"stream-key-{service}")


def _read(path):
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def key_path(service=None, alone=True):
    """The file `service`'s key is read from, or None when there is none:
    its own file first, then the plain KEY_FILE when it is the only service
    (`alone`) or Twitch, whose key that file held before there were two."""
    places = [KEY_FILE] if service is None else \
        [key_file(service)] + ([KEY_FILE] if alone or service == "twitch" else [])
    return next((p for p in places if _read(p)), None)


def key(service=None, alone=True):
    """The stream key, or None. Read only here, and only when streaming."""
    found = key_path(service, alone)
    return _read(found) if found else None


def keep_key(text, service=None):
    """Keep a stream key (`service`'s own, or the plain one), readable only
    by its owner. False when empty."""
    text = text.strip()
    if not text:
        return False
    path = key_file(service)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as out:
        out.write(text + "\n")
    os.chmod(path, 0o600)
    return True


def destination(s, stream_key):
    if s["service"] == "custom":
        return s["url"].replace("{key}", stream_key) if s["url"] else None
    template = INGEST.get(s["service"])
    return template.format(key=stream_key) if template else None


def destinations(s):
    """([(service, address, key)], [(service, why it is left out)]) for
    the services in `s`: one without a key, or not known, is left out."""
    names = services(s)
    found, left = [], []
    for name in names:
        if name not in INGEST and name != "custom":
            left.append((name, f"{name} left out: not a service this streams to (youtube, twitch or custom)."))
            continue
        stream_key = key(name, alone=len(names) == 1)
        address = destination(dict(s, service=name), stream_key) if stream_key else None
        if address:
            found.append((name, address, stream_key))
        elif stream_key:
            left.append((name, f"{NAMES[name]} left out: no [stream] url in config.toml."))
        else:
            left.append((name, f"{NAMES[name]} left out: no stream key in {key_file(name)} "
                               f"(./stream.py key {name})."))
    return found, left


def hidden(text, keys):
    """Text with the key, or every one of `keys`, taken out, for anything
    that might be shown."""
    for stream_key in ([keys] if isinstance(keys, str) else keys or []):
        if stream_key:
            text = text.replace(stream_key, "<stream key>")
    return text


def status():
    try:
        return json.loads((WEB / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def imaging(st, now=None):
    """Whether a run is imaging: it has a name and its newest frame is recent."""
    age = st.get("age")
    return bool(st.get("name")) and isinstance(age, (int, float)) and age < START_S


def runner_alive():
    """Whether tonight's schedule runner is still going (schedule.py run)."""
    try:
        pid = int((config.DATA / "cache" / "schedule.runner").read_text().split()[0])
        os.kill(pid, 0)
        return True
    except (OSError, ValueError, IndexError):
        return False


def due_soon(st, now, within=BETWEEN_S):
    """Whether the schedule has a step starting within `within` seconds."""
    steps = (st.get("schedule") or {}).get("steps") or []
    upcoming = next((s for s in steps if s.get("status") in ("queued", "running")), None)
    return bool(upcoming) and (upcoming.get("status") == "running" or (upcoming.get("start") or now) - now <= within)


def night_over(st):
    """Whether tonight's schedule has run to its end."""
    steps = (st.get("schedule") or {}).get("steps") or []
    return bool(steps) and all(s.get("status") in ("done", "failed", "skipped") for s in steps)


def observatory(now=None):
    """("focus" | "polar", its state) while a focus run or a polar alignment
    is worth showing (running, a person turning the bolts between rounds,
    or its result card), from their own files (streamlook.focus_stream_state,
    polar_stream_state); else (None, None). Focus first: polar alignment
    needs focus, and the two never run at once."""
    import streamlook
    now = now or time.time()
    try:
        found = streamlook.focus_stream_state(now)
        if found and found["showing"]:
            return "focus", found
        found = streamlook.polar_stream_state(now)
        if found and found["showing"]:
            return "polar", found
    except Exception:            # a file half-read is never worth the stream
        pass
    return None, None


def broadcasting(now=None):
    """(the segment to show or None, whether the observatory is doing
    something worth going on air for): a focus run or polar alignment by its
    file, or any broadcast activity line (activity.BROADCAST)."""
    import activity
    kind, found = observatory(now)
    return kind, found, kind is not None or activity.phase() in activity.BROADCAST


def decide(streaming, st, quiet_since, now, between=False, ending=False, active=False):
    """("start" | "stop" | "carry on", quiet_since): start when a run is
    imaging, or when the observatory is focusing or polar aligning
    (`active`); carry on between targets while the schedule has more due
    (`between`); hold the end card for END_S once the night is over
    (`ending`); otherwise stop once nothing new has come for STOP_S."""
    if imaging(st) or active:
        return ("carry on" if streaming else "start"), None
    if not streaming:
        return "carry on", None
    quiet_since = now if quiet_since is None else quiet_since
    if between:
        return "carry on", quiet_since
    if ending:
        return ("stop" if now - quiet_since >= END_S else "carry on"), quiet_since
    return ("stop" if now - quiet_since >= STOP_S else "carry on"), quiet_since


def session_of(st):
    """The newest session folder of the run status.json describes."""
    try:
        return sorted(p for p in (config.DATA / "frames" / st["name"]).iterdir() if p.is_dir())[-1]
    except (KeyError, OSError, IndexError):
        return None


def pictures(st=None):
    """The stack and the newest single frame; no stack when status.json
    says web/stack.jpg is an earlier run's (serve.stack_status)."""
    stack = single = None
    try:
        if ((st or {}).get("stack") or {}).get("current") is not False:
            with Image.open(WEB / "stack.jpg") as im:
                stack = im.convert("RGB")
        with Image.open(WEB / "latest.jpg") as im:
            single = im.convert("RGB")
    except OSError:
        pass
    return stack, single


def end_lines(st):
    """The end card's figures, counted from tonight's sessions only."""
    sessions = (st.get("discovery") or {}).get("sessions") or []
    lines = [f"{len({s['field'] for s in sessions})} fields observed",
             f"{sum(s.get('kept') or 0 for s in sessions) + (st.get('accepted') or 0)} frames kept"]
    for m in (st.get("discovery") or {}).get("mosaics", []):
        done = sum(p.get("state") == "done" for p in m["panels"])
        lines.append(f"{done} {m['name']} panels searched")
    possible = sum(1 for s in sessions if s.get("unexplained"))
    lines.append(f"{possible} possible change{'s' if possible != 1 else ''}, kept for checking" if possible
                 else "no possible changes")
    return lines


def between_state(st, now):
    """The card between targets: what comes next and how far the getting
    ready has gone, from what is being done now (activity.py)."""
    import activity
    steps = (st.get("schedule") or {}).get("steps") or []
    upcoming = next((s for s in steps if s.get("status") in ("running", "queued")
                     and not s["label"].lower().startswith(("goto", "focus"))), None)
    labels = {"goto": "moving telescope", "solve": "confirming field", "focus": "checking focus",
              "imaging": "imaging"}
    found = activity.step_of(activity.phase())
    current = activity.ORDER.index(found) if found else None
    checklist = [(labels[name], "now" if i == current else ("done" if current is not None and i < current else "open"))
                 for i, name in enumerate(activity.ORDER)]
    label = upcoming["label"] if upcoming else "the next target"
    begins = max(0, (upcoming.get("start") or now) - now) if upcoming else 0
    tonight = [(s["label"].split(",")[0], {"done": "done", "running": "running"}.get(s.get("status"), "open"))
               for s in steps if not s["label"].lower().startswith(("goto", "focus", "keep going"))]
    return {"kind": "between", "target": label.split(",")[0], "now": now, "next": None,
            "between": {"programme": label, "begins_in_s": begins, "steps": checklist}, "tonight": tonight}


def frame(st, now=None, mode="imaging"):
    """The picture sent (docs/stream-look.md, drawn by streamlook.py): while
    imaging, the stack with one exposure and the side panel; between
    targets, the card with what comes next; at the night's end, its
    summary; while focusing or polar aligning ("focus", "polar"), their
    looks. Never anything that names the place."""
    import streamlook
    now = now or time.time()
    stack, single = pictures(st)
    if mode in ("focus", "polar"):
        import streamstory
        found = (streamlook.focus_stream_state if mode == "focus" else streamlook.polar_stream_state)(now)
        if found is not None:
            state = {"kind": mode, "target": "", "now": now, mode: found}
            state["story"] = streamstory.plan(state, st, now)
            return streamlook.compose(state).image
        mode = "imaging"                # gone between looking and drawing: what was there before
    if mode == "between":
        state = between_state(st, now)
    elif mode == "end":
        state = {"kind": "end", "target": st.get("name") or "", "now": now, "end": {"lines": end_lines(st)}}
    else:
        state = streamlook.from_status(st, now, session_of(st))
    canvas = streamlook.compose(state, stack, single)
    canvas.image.info["crawl"] = canvas.crawl          # run along the bottom by Composer, not drawn in
    return canvas.image


def encoder(device=None, size=(WIDTH, HEIGHT)):
    """ffmpeg's video encoding arguments: the laptop's video hardware where
    there is some that works, else the processors. The pictures come in
    INPUT_FPS a second and go out at FPS, each repeated."""
    rate = BITRATE[size]
    common = ["-b:v", rate, "-maxrate", rate, "-bufsize", f"{2 * int(rate[:-1])}k", "-g", str(FPS * 2)]
    scale = f"scale={size[0]}:{size[1]}," if size != (WIDTH, HEIGHT) else ""
    if device is not None:
        return ["-vaapi_device", str(device), "-vf", f"fps={FPS},{scale}format=nv12,hwupload",
                "-c:v", "h264_vaapi", *common]
    return ["-vf", f"fps={FPS},{scale}format=yuv420p", "-c:v", "libx264", "-preset", "veryfast",
            "-tune", "stillimage", *common]


def command(target, device=None, size=(WIDTH, HEIGHT), audio_fd=None):
    """ffmpeg taking raw pictures on its input and sending them to `target`
    (an rtmp:// address, a file to try it, or a list of addresses),
    reporting its speed in PROGRESS. Several are fed from one encoding by
    the tee muxer, each with onfail=ignore so one failing leaves the rest.
    The sound is silence, or with `audio_fd` raw sound read from that
    descriptor (Tones: the focus run's tones)."""
    sound = (["-f", "s16le", "-ar", str(TONE_RATE), "-ac", "1", "-i", f"pipe:{audio_fd}"] if audio_fd is not None
             else ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"])
    targets = [target] if isinstance(target, str) else list(target)
    if len(targets) > 1:
        out = ["-map", "0:v", "-map", "1:a", "-flags", "+global_header", "-f", "tee",
               "|".join(f"[f=flv:onfail=ignore]{t}" for t in targets)]
    else:
        out = ["-f", "flv", targets[0]] if targets[0].startswith("rtmp") else [targets[0]]
    return ["ffmpeg", "-loglevel", "error", "-y", "-progress", str(PROGRESS), "-stats_period", "5",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{WIDTH}x{HEIGHT}", "-r", str(INPUT_FPS), "-i", "-",
            *sound, *encoder(device, size), "-c:a", "aac", "-b:a", "64k", "-ar", "44100", "-ac", "2",
            "-shortest", *out]


TONE_RATE = 22050         # the focus aid's own (focus.RATE)
TONE_CHUNK_S = 0.1        # sound handed to ffmpeg this much at a time, paced by the clock


class Tones:
    """The stream's sound while the telescope focuses: for each new reading
    a click and a tone, higher the sharper the stars (focus.pitch, as the
    focus aid's), or two clicks for a reading with no stars; silence
    between. Written to ffmpeg's second input on a thread of its own,
    paced by the clock, so the pictures never wait on it; it ends when
    ffmpeg does (a broken pipe) or on stop()."""

    def __init__(self, fd, clock=time.monotonic, sleep=time.sleep):
        import threading
        self.fd, self.clock, self.sleep = fd, clock, sleep
        self.queue, self.lock = np.zeros(0, dtype=np.int16), threading.Lock()
        self.seen, self.run_started = None, None
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def hear(self, found):
        """Queue the sound for the newest reading of a focus run's state
        (streamlook.focus_stream_state), if it is new."""
        import focus
        if not found or not found.get("running"):
            return
        count = found.get("count") or 0
        if found.get("started") != self.run_started:
            self.run_started, self.seen = found.get("started"), count     # a new run: from its next reading
            return
        if count <= (self.seen or 0):
            return
        self.seen = count
        hfr, usual = found.get("last_hfr"), found.get("usual_hfr")
        if not hfr:
            samples = focus.waveform("double")
        else:
            fraction = min(1.0, (usual or hfr) / hfr)        # 1 at the usual best or sharper
            samples = focus.waveform("tone", focus.pitch(fraction))
        with self.lock:
            self.queue = np.concatenate([self.queue, (0.4 * 32767 * samples).astype(np.int16)])

    def chunk(self, n):
        """The next `n` samples: queued sound, then silence."""
        with self.lock:
            out, self.queue = self.queue[:n], self.queue[n:]
        return np.concatenate([out, np.zeros(n - len(out), dtype=np.int16)]).astype("<i2").tobytes()

    def run(self):
        n = int(TONE_RATE * TONE_CHUNK_S)
        tick = self.clock()
        try:
            while not self.stopped.is_set() and self.fd is not None:
                os.write(self.fd, self.chunk(n))
                tick += TONE_CHUNK_S
                self.sleep(max(0.0, tick - self.clock()))
        except (OSError, TypeError):      # ffmpeg has gone (or stop() closed it): so has the sound
            pass
        finally:
            self.close()

    def close(self):
        with self.lock:
            fd, self.fd = self.fd, None          # closed once only: the number may be reused after
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

    def stop(self):
        self.stopped.set()
        if not self.thread.is_alive():
            self.close()


def reported(text, name):
    """ffmpeg's newest `name=` progress report as a number, or None."""
    found = [line.split("=", 1)[1].strip().rstrip("x") for line in text.splitlines() if line.startswith(name + "=")]
    try:
        return float(found[-1]) if found else None
    except ValueError:
        return None


def speed(text):
    """ffmpeg's newest speed= report (1.0 keeps up), or None."""
    return reported(text, "speed")


def falling_behind(reports, now, within=SLOW_S, drops=None, frames=None, breaks=()):
    """True when the stream is not getting out as fast as it is made: every
    speed report for `within` seconds under 0.95; ffmpeg dropping more than
    a second's frames in that time (`drops`: (time, drop_frames)); its frame
    count standing still that long (`frames`: (time, frame)), which is how a
    stalled connection shows; or the stream breaking off BREAKS times in
    BREAKS_S (`breaks`: their times). Encoder speed alone says little about
    the network, so it takes any of them."""
    if sum(1 for t in breaks if now - t <= BREAKS_S) >= BREAKS:
        return True
    if frames:
        old = [f for t, f in frames if now - t >= within]
        if old and frames[-1][1] <= old[-1]:
            return True
    if drops:
        old = [d for t, d in drops if now - t >= within]
        if old and drops[-1][1] - old[-1] > FPS:
            return True
    recent = [s for t, s in reports if now - t <= within]
    return len(recent) >= 3 and reports[0][0] <= now - within and all(s < 0.95 for s in recent)


def bandwidth_test(target, device=None, run=subprocess.run, seconds=TEST_S):
    """The size to start at: 1080p if a short test of it to Twitch kept up,
    else 720p. Twitch takes a stream key with ?bandwidthtest=true without
    showing it to anyone. Other services have no such test: 1080p, and the
    stream watches itself. `target` may be a list: the test goes to the
    Twitch one among them. It measures one stream, so with two the upload
    needs twice what it showed; falling_behind catches it if that is short."""
    target = next((t for t in ([target] if isinstance(target, str) else target) if "live.twitch.tv" in t), None)
    if target is None:
        return (WIDTH, HEIGHT)
    progress = PROGRESS.with_name("stream-bandwidth.txt")
    rate = BITRATE[(WIDTH, HEIGHT)]
    try:
        run(["ffmpeg", "-loglevel", "error", "-y", "-progress", str(progress), "-re", "-f", "lavfi",
             "-i", f"testsrc2=size={WIDTH}x{HEIGHT}:rate={FPS}", "-f", "lavfi",
             "-i", "anullsrc=channel_layout=stereo:sample_rate=44100", "-t", str(seconds),
             *encoder(device), "-c:a", "aac", "-b:a", "64k", "-f", "flv", target + "?bandwidthtest=true"],
            capture_output=True, timeout=seconds + 60)
        text = progress.read_text()
    except (OSError, subprocess.SubprocessError):
        return FALLBACK
    found, lost = speed(text), reported(text, "drop_frames") or 0
    return (WIDTH, HEIGHT) if found is not None and found >= 0.95 and lost <= FPS else FALLBACK


def measure_transit(st, running, say=print):
    """Start `transits.py measure` on the run at low priority, in its own
    process, if the run is a transit and none is going; returns it."""
    import streamlook
    if running is not None and running.poll() is None:
        return running
    p = streamlook.transit_for(st.get("name") or "")
    session = session_of(st)
    if not p or session is None:
        return None
    return subprocess.Popen(["nice", "-n", "19", sys.executable, str(Path(__file__).with_name("transits.py")),
                             "measure", str(session), "--planet", p["planet"]],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def announce(st, now, say=print):
    """Set the Twitch channel's title, category and tags for this run, on
    its own thread: the feed never waits on Twitch."""
    import threading

    import streamlook
    import twitch

    def run():
        try:
            title, tags = twitch.describe(streamlook.from_status(st, now, session_of(st)))
            twitch.set_channel(title, tags, say=say)
        except Exception as error:               # the stream goes on whatever Twitch says
            say(f"The channel's info was left as it is: {error}")
    threading.Thread(target=run, daemon=True).start()


def chat(say=print):
    """Answer the chat's commands (streamchat.py) on their own thread while
    streaming; False when the sign-in does not allow it (said once)."""
    import threading

    import streamchat
    import twitch
    tokens = twitch.chat_tokens()
    if tokens is None:
        say("The chat's commands are off: sign in again with ./stream.py twitch-login to allow them.")
        return False
    threading.Thread(target=streamchat.run, args=(status, tokens, say), daemon=True).start()
    return True


class Composer:
    """Draws the picture on its own thread every few seconds, so the loop
    feeding ffmpeg never waits on it: a 1080p picture takes most of a
    second to draw, and the feed must not stall for it (20 October 2026: at
    0.79x speed when it did). `view` is what to draw: (status, mode)."""

    def __init__(self, draw=None, every=3.0):
        import threading
        self.draw, self.every = draw or frame, every
        self.view, self.ready, self.lock = None, [], threading.Lock()
        self.base, self.strip, self.crawl, self.crawl_from = None, None, None, 0.0
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        last, said = None, None
        while not self.stopped.is_set():
            if self.view is not None:
                st, mode = self.view
                try:
                    new = self.draw(st, time.time(), mode)
                    # A new picture crossfades in over FADE pictures rather than jumping.
                    out = [Image.blend(last, new, (i + 1) / (FADE + 1)).tobytes() for i in range(FADE)] \
                        if last is not None and last.size == new.size else []
                    out.append(new.tobytes())
                    crawl = new.info.get("crawl")
                    with self.lock:
                        self.ready = out
                        self.base = np.asarray(new) if crawl else None
                        if crawl and crawl != self.crawl:
                            import streamlook
                            self.strip, self.crawl, self.crawl_from = streamlook.crawl_strip(crawl), crawl, time.time()
                        elif not crawl:
                            self.strip, self.crawl = None, None
                    last = new
                except Exception as error:          # one bad picture never ends the stream
                    if str(error) != said:              # said once, not every 3 s
                        print(f"picture not drawn, the last one stays: {error}", flush=True)
                        said = str(error)
            self.stopped.wait(self.every)

    def next(self, current):
        """The next picture's bytes: the next of a fade, else the newest with
        the crawl moved along, else `current`."""
        import streamlook
        with self.lock:
            if len(self.ready) > 1:
                return self.ready.pop(0)
            if self.strip is not None and self.base is not None:
                moved = streamlook.crawled(self.base, self.strip, time.time() - self.crawl_from)
                if moved is not None:
                    return moved.tobytes()
                self.strip = None                       # it has run out at the left
            return self.ready[0] if self.ready else current

    def stop(self):
        self.stopped.set()


def passed_on(process, keys, say=print):
    """Pass ffmpeg's own messages on, on their own thread, with every key
    taken out: its errors name the address, key and all (a tee destination
    that fails is printed whole)."""
    import threading
    pipe = getattr(process, "stderr", None)
    if pipe is None:
        return

    def run():
        for line in iter(pipe.readline, b""):
            text = line.decode("utf-8", "replace").rstrip()
            if text:
                say(hidden(text, keys))
    threading.Thread(target=run, daemon=True).start()


def watch(to=None,say=print, sleep=time.sleep, clock=time.time, run=subprocess.Popen, wait=True):
    """Stream while a run is imaging, until stopped. While streaming is off
    or there is no key it waits, looking again each minute, so switching it
    on is all it takes (`wait` False: say why and return)."""
    told = None
    while True:
        s = settings()
        found, left = ([("file", to, None)], []) if to else (destinations(s) if s["enabled"] else ([], []))
        if found:
            break
        why = ("Streaming is off ([stream] enabled in config.toml); nothing is sent." if not s["enabled"]
               else " ".join(w for _, w in left) + " Nothing is sent.")
        if why != told:
            say(why)
            told = why
        if not wait:
            return
        sleep(60)
    for _, why in left:
        say(why)
    names = [name for name, _, _ in found]
    target = to or [address for _, address, _ in found]
    stream_keys = [k for _, _, k in found]
    twitch_on = to is None and "twitch" in names
    device = working_device()
    say(f"Video encoding on {device or 'the processors (no working video hardware)'}")
    size = (WIDTH, HEIGHT)
    process, quiet_since, shown, retry_at = None, None, None, 0.0
    reports, drops, frames, breaks, measuring, measured_at, announced = [], [], [], [], None, 0.0, None
    tested = False
    chatting = None
    composer = Composer(draw=lambda st, now, mode: frame(st, now, mode).resize(size)
                        if size != (WIDTH, HEIGHT) else frame(st, now, mode))
    tick = clock()
    segment, segment_state, active, looked_at, tones = None, None, False, -1e9, None
    try:
        while True:
            st, now = status(), clock()
            if now - looked_at >= LOOK_S:
                # Focusing or polar alignment going on: read from their files, not every picture.
                segment, segment_state, active = broadcasting(now)
                looked_at = now
                if tones is not None and segment == "focus":
                    tones.hear(segment_state)
            between = not imaging(st) and runner_alive() and due_soon(st, now)
            ending = not imaging(st) and not between and night_over(st)
            action, quiet_since = decide(process is not None, st, quiet_since, now, between, ending, active)
            composer.view = (st, segment or ("imaging" if imaging(st) else ("between" if between else
                                                                            ("end" if ending else "imaging"))))
            if action == "start":
                if now < retry_at:
                    sleep(1)
                    continue
                if not tested and to is None:
                    size, tested = bandwidth_test(target, device), True
                    with composer.lock:
                        composer.ready = []
                doing = {"focus": "focusing", "polar": "polar aligning"}.get(segment) \
                    or (f"imaging {st.get('name')}" if imaging(st) else "at work")
                say(f"{time.strftime('%H:%M')} {doing}: streaming {size[0]}x{size[1]} to "
                    f"{to or ' and '.join(NAMES[n] for n in names)} "
                    f"({hidden(' '.join([target] if isinstance(target, str) else target), stream_keys)})")
                PROGRESS.parent.mkdir(parents=True, exist_ok=True)
                PROGRESS.write_text("")
                listen = os.pipe() if s["tones"] and os.name == "posix" else None
                process, reports, drops, frames = run(
                    command(target, device, size, audio_fd=listen and listen[0]), stdin=subprocess.PIPE,
                    stderr=subprocess.PIPE, **({"pass_fds": (listen[0],)} if listen else {})), [], [], []
                if listen:
                    os.close(listen[0])                 # ffmpeg has its own copy
                    tones = Tones(listen[1]).start()
                passed_on(process, stream_keys, say)
            elif action == "stop":
                say(f"{time.strftime('%H:%M')} nothing new for {(END_S if ending else STOP_S) // 60} minutes: "
                    "stream stopped")
                process.stdin.close()
                tones = quiet(tones)
                process.wait(timeout=30)
                process, quiet_since, shown = None, None, None
            if process is not None and twitch_on and chatting is None:
                chatting = chat(say)
            if process is not None and twitch_on and imaging(st) \
                    and st.get("name") != announced:
                announced = st.get("name")
                announce(st, now, say)
            if process is not None:
                if imaging(st) and now - measured_at > MEASURE_S:
                    measuring, measured_at = measure_transit(st, measuring, say), now
                shown = composer.next(shown)
                if shown is None:
                    sleep(0.2)                         # the first picture is still being drawn
                    continue
                try:
                    process.stdin.write(shown)
                except (BrokenPipeError, OSError):
                    # Never a tight loop: wait, and the next try is a fresh start.
                    say(f"{time.strftime('%H:%M')} the stream broke off; trying again in 30 s")
                    process, retry_at, tones = None, now + 30, quiet(tones)
                    breaks = [t for t in breaks if now - t <= BREAKS_S] + [now]
                    if size == (WIDTH, HEIGHT) and falling_behind([], now, breaks=breaks):
                        size = FALLBACK
                        say(f"{time.strftime('%H:%M')} it broke off {len(breaks)} times in "
                            f"{BREAKS_S // 60} minutes: going down to {size[0]}x{size[1]}")
                        with composer.lock:
                            composer.ready = []
                    continue
                try:
                    progress = PROGRESS.read_text()
                except OSError:
                    progress = ""
                found, lost, sent = speed(progress), reported(progress, "drop_frames"), reported(progress, "frame")
                if found is not None and (not reports or now - reports[-1][0] >= 5):
                    reports = (reports + [(now, found)])[-30:]
                    if lost is not None:
                        drops = (drops + [(now, lost)])[-30:]
                    if sent is not None:
                        frames = (frames + [(now, sent)])[-30:]
                if size == (WIDTH, HEIGHT) and falling_behind(reports, now, drops=drops, frames=frames):
                    size = FALLBACK
                    say(f"{time.strftime('%H:%M')} the stream is falling behind (speed {reports[-1][1]:.2f}): "
                        f"going down to {size[0]}x{size[1]}")
                    process.stdin.close()
                    tones = quiet(tones)
                    process.wait(timeout=30)
                    process, shown = None, None
                    with composer.lock:
                        composer.ready = []            # pictures of the old size would not fit
                    continue
                # Paced by the clock, not by how long the writing took.
                tick = max(tick + 1 / INPUT_FPS, clock() - 1)
                sleep(max(0.0, tick - clock()))
            else:
                sleep(10)
    except KeyboardInterrupt:
        pass
    finally:
        composer.stop()
        quiet(tones)
        if process is not None:
            process.stdin.close()
            process.wait(timeout=30)


def quiet(tones):
    """Stop the tones' thread, if there is one; None, for what it was."""
    if tones is not None:
        tones.stop()
    return None


def working_device(devices=None, test=None):
    """The first video device whose hardware encoder really works, tried
    with a second of encoding; None if none does. This laptop has two:
    renderD128 (Intel, no driver for its encoder) failed, renderD129 (the
    AMD Radeon) worked (20 October 2026)."""
    devices = devices if devices is not None else sorted(Path("/dev/dri").glob("renderD*"))
    test = test or (lambda d: subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-vaapi_device", str(d), "-f", "lavfi",
         "-i", "testsrc=size=320x240:rate=5", "-t", "1", "-vf", "format=nv12,hwupload", "-c:v", "h264_vaapi",
         "-f", "null", "-"], capture_output=True, timeout=30).returncode == 0)
    for device in devices:
        try:
            if test(device):
                return device
        except (OSError, subprocess.SubprocessError):
            continue
    return None


def unit(root=None, python=None, data=None):
    """The systemd user service that keeps `watch` running."""
    root = Path(root or Path(__file__).resolve().parent)
    python = python or sys.executable
    env = f"Environment=TY_DATA={data}\n" if data else ""
    return (f"[Unit]\nDescription=telescopeyoke: stream the telescope live while it images\n\n"
            f"[Service]\nWorkingDirectory={root}\n{env}ExecStart={python} -u {root / 'stream.py'} watch\n"
            f"Restart=always\nRestartSec=30\nNice=10\n\n[Install]\nWantedBy=default.target\n")


def install(say=print, run=subprocess.run, home=None):
    place = Path(home or Path.home()) / ".config" / "systemd" / "user"
    place.mkdir(parents=True, exist_ok=True)
    (place / "ty-stream.service").write_text(unit(data=os.environ.get("TY_DATA")), encoding="utf-8")
    run(["systemctl", "--user", "daemon-reload"], check=True)
    run(["systemctl", "--user", "enable", "--now", "ty-stream.service"], check=True)
    say(f"Installed {place / 'ty-stream.service'}: it streams while a run is imaging, once [stream] enabled is on "
        f"and a key is in {KEY_FILE.parent}. Stop it: systemctl --user disable --now ty-stream.service")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", nargs="?", choices=["watch", "frame", "preview", "key", "twitch-login"])
    ap.add_argument("service", nargs="?", choices=sorted(NAMES), help="with key: whose key it is")
    ap.add_argument("--to", help="with watch: stream into this file instead, to try it")
    ap.add_argument("--install", action="store_true", help="with watch: run it as a systemd user service")
    args = ap.parse_args(argv)
    if args.action == "watch" and args.install:
        return install()
    if args.action == "watch":
        return watch(args.to)
    if args.action == "twitch-login":
        import twitch
        return 0 if twitch.login() else 1
    if args.service and args.action != "key":
        ap.error("a service is named only with key")
    if args.action == "key":
        whose = f"{NAMES[args.service]} stream key" if args.service else "Stream key"
        text = getpass.getpass(f"{whose} (not shown): ") if sys.stdin.isatty() else sys.stdin.readline()
        print(f"Kept in {key_file(args.service)}." if keep_key(text, args.service)
              else "Nothing pasted: the key is unchanged.")
        return
    if args.action == "preview":
        import streamlook
        streamlook.preview(config.DATA / "cache" / "stream-preview", WEB)
        return
    if args.action == "frame":
        PREVIEW.parent.mkdir(parents=True, exist_ok=True)
        frame(status()).save(PREVIEW, quality=90)
        print(f"saved {PREVIEW}")
        return
    s, st = settings(), status()
    names = services(s)
    print(f"Streaming is {'on' if s['enabled'] else 'off'}; to {' and '.join(names)}.")
    found, left = destinations(s)
    for name in names:
        if any(n == name for n, _, _ in found):
            print(f"  {name}: stream key in place ({key_path(name, alone=len(names) == 1)}).")
        else:
            print("  " + next(why for n, why in left if n == name))
    print(f"A run is {'imaging now: it would stream' if imaging(st) else 'not imaging: it would wait'}.")
    device = working_device()
    print(f"Video encoding: {device or 'the processors'}; "
          f"ffmpeg {'found' if shutil.which('ffmpeg') else 'NOT found'}.")


if __name__ == "__main__":
    sys.exit(main())
