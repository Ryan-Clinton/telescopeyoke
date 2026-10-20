#!/usr/bin/env python3
"""Stream the telescope live to YouTube or Twitch while it is imaging.

    ./stream.py                    what it would do now, and why; streams nothing
    ./stream.py watch              keep watching: stream while a run is imaging, stop when it is not
    ./stream.py watch --to F.mp4   the same into a file, to try it with no account and no key
    ./stream.py watch --install    run `watch` as a systemd user service, from boot; it idles while off
    ./stream.py frame              make one picture of what would be sent, as cache/stream-preview.jpg
    ./stream.py key                paste the stream key in (not shown as typed); kept readable only by you

Off unless [stream] enabled in config.toml (the Settings screen has it).
The service is [stream] service: "youtube", "twitch", or "custom" with
[stream] url. The stream key is the person's and works like a password: it
is kept in ~/.config/telescopeyoke/stream-key (readable only by them), never
in config.toml, never shown, never written to a log.

What is sent: the running stack, beside the newest frame, with the target,
how many frames, and what is next. Nothing else: no webcam, no cloud map,
nothing that names the place (the same rule as the status page and the
site's live page). The pictures change every few seconds, so a few frames a
second are sent, the picture repeating between updates, with a silent sound
track, as the services expect. The video is encoded by the laptop's own
video hardware where it has some (Intel Quick Sync, through VAAPI), so it
does not take the processors the stacking needs.

It starts when a run's newest frame is under START_S old and stops when
none has arrived for STOP_S: cloud, the end of the night, or the telescope
put away. YouTube makes and ends a broadcast by itself when its stream key
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

import config

WEB = config.DATA / "web"
KEY_FILE = Path(os.path.expanduser("~/.config/telescopeyoke/stream-key"))
PREVIEW = config.DATA / "cache" / "stream-preview.jpg"   # not web/: that goes on the pages
WIDTH, HEIGHT = 1280, 720
FPS = 5                 # frames a second sent; the picture changes every few seconds
START_S = 120           # a run whose newest frame is younger than this is imaging
STOP_S = 300            # no new frame for this long: stop streaming
INGEST = {
    "youtube": "rtmp://a.rtmp.youtube.com/live2/{key}",
    "twitch": "rtmp://live.twitch.tv/app/{key}",
}


def settings():
    found = config.hardware().get("stream", {})
    return {"enabled": bool(found.get("enabled", False)), "service": found.get("service", "youtube"),
            "url": found.get("url", "")}


def key():
    """The stream key, or None. Read only here, and only when streaming."""
    try:
        text = KEY_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def keep_key(text):
    """Keep the stream key in KEY_FILE, readable only by its owner. False when empty."""
    text = text.strip()
    if not text:
        return False
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as out:
        out.write(text + "\n")
    os.chmod(KEY_FILE, 0o600)
    return True


def destination(s, stream_key):
    if s["service"] == "custom":
        return s["url"].replace("{key}", stream_key) if s["url"] else None
    template = INGEST.get(s["service"])
    return template.format(key=stream_key) if template else None


def hidden(text, stream_key):
    """Text with the key taken out, for anything that might be shown."""
    return text.replace(stream_key, "<stream key>") if stream_key else text


def status():
    try:
        return json.loads((WEB / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def imaging(st, now=None):
    """Whether a run is imaging: it has a name and its newest frame is recent."""
    age = st.get("age")
    return bool(st.get("name")) and isinstance(age, (int, float)) and age < START_S


def decide(streaming, st, quiet_since, now):
    """("start" | "stop" | "carry on", quiet_since): start when a run is
    imaging; stop once nothing new has come for STOP_S."""
    if imaging(st):
        return ("carry on" if streaming else "start"), None
    if not streaming:
        return "carry on", None
    quiet_since = quiet_since or now
    return ("stop" if now - quiet_since >= STOP_S else "carry on"), quiet_since


def frame(st, now=None):
    """The picture sent: the stack and the newest frame side by side, and a
    caption with the target, the frames and what is next. Never anything
    that names the place."""
    from PIL import Image, ImageDraw, ImageFont
    canvas = Image.new("RGB", (WIDTH, HEIGHT), (8, 10, 16))
    draw = ImageDraw.Draw(canvas)
    big, small = ImageFont.load_default(size=30), ImageFont.load_default(size=20)
    picture_h = HEIGHT - 120
    for i, (name, label) in enumerate((("stack.jpg", "The stack so far"), ("latest.jpg", "The newest frame"))):
        box = (WIDTH // 2 * i + 10, 10, WIDTH // 2 - 20, picture_h - 40)
        try:
            with Image.open(WEB / name) as im:
                im = im.convert("RGB")
                im.thumbnail((box[2], box[3]))
                canvas.paste(im, (box[0] + (box[2] - im.width) // 2, box[1] + (box[3] - im.height) // 2))
        except OSError:
            pass
        draw.text((box[0], picture_h - 22), label, fill=(150, 160, 180), font=small)
    title = st.get("title") or st.get("name") or "telescopeyoke"
    accepted, exposure = st.get("accepted"), st.get("exposure")
    count = f"{accepted} frames" + (f" of {exposure:g} s" if isinstance(exposure, (int, float)) else "") + " kept" \
        if accepted is not None else ""
    steps = (st.get("schedule") or {}).get("steps") or []
    upcoming = next((s for s in steps if s.get("status") == "queued"), None)
    later = ""
    if upcoming and upcoming.get("start"):
        later = f"Next: {upcoming['label']} at {time.strftime('%H:%M', time.localtime(upcoming['start']))}"
    draw.text((20, picture_h + 10), str(title).replace(" — ", ", "), fill=(230, 235, 245), font=big)
    draw.text((20, picture_h + 55), "  ·  ".join(t for t in (count, later) if t), fill=(150, 160, 180), font=small)
    draw.text((WIDTH - 260, picture_h + 55), time.strftime("%H:%M:%S", time.localtime(now or time.time())),
              fill=(150, 160, 180), font=small)
    return canvas


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


def encoder(device=None):
    """ffmpeg's video encoding arguments: the laptop's video hardware where
    there is some that works, else the processors."""
    if device is not None:
        return ["-vaapi_device", str(device), "-vf", "format=nv12,hwupload", "-c:v", "h264_vaapi",
                "-b:v", "2500k", "-maxrate", "2500k", "-bufsize", "5000k", "-g", str(FPS * 2)]
    return ["-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-pix_fmt", "yuv420p",
            "-b:v", "2500k", "-maxrate", "2500k", "-bufsize", "5000k", "-g", str(FPS * 2)]


def command(target, device=None):
    """ffmpeg taking raw pictures on its input and sending them to `target`
    (an rtmp:// address, or a file to try it)."""
    out = ["-f", "flv", target] if target.startswith("rtmp") else [target]
    return ["ffmpeg", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "-",
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            *encoder(device), "-c:a", "aac", "-b:a", "64k", "-shortest", *out]


def watch(to=None, say=print, sleep=time.sleep, clock=time.time, run=subprocess.Popen, wait=True):
    """Stream while a run is imaging, until stopped. While streaming is off
    or there is no key it waits, looking again each minute, so switching it
    on is all it takes (`wait` False: say why and return)."""
    told = None
    while True:
        s = settings()
        stream_key = None if to else key()
        target = to or (destination(s, stream_key) if s["enabled"] and stream_key else None)
        if target:
            break
        why = ("Streaming is off ([stream] enabled in config.toml); nothing is sent." if not s["enabled"]
               else f"No stream key in {KEY_FILE}: nothing is sent.")
        if why != told:
            say(why)
            told = why
        if not wait:
            return
        sleep(60)
    device = working_device()
    say(f"Video encoding on {device or 'the processors (no working video hardware)'}")
    process, quiet_since, picture, made, retry_at = None, None, None, 0.0, 0.0
    try:
        while True:
            st, now = status(), clock()
            action, quiet_since = decide(process is not None, st, quiet_since, now)
            if action == "start":
                if now < retry_at:
                    sleep(1)
                    continue
                say(f"{time.strftime('%H:%M')} imaging {st.get('name')}: streaming to "
                    f"{hidden(target, stream_key)}")
                process = run(command(target, device), stdin=subprocess.PIPE)
            elif action == "stop":
                say(f"{time.strftime('%H:%M')} nothing new for {STOP_S // 60} minutes: stream stopped")
                process.stdin.close()
                process.wait(timeout=30)
                process, quiet_since = None, None
            if process is not None:
                if picture is None or now - made > 3:
                    picture, made = frame(st, now).tobytes(), now
                try:
                    process.stdin.write(picture)
                except (BrokenPipeError, OSError):
                    # Never a tight loop: wait, and the next try is a fresh start.
                    say(f"{time.strftime('%H:%M')} the stream broke off; trying again in 30 s")
                    process, retry_at = None, now + 30
                    continue
            sleep(1 / FPS if process is not None else 10)
    except KeyboardInterrupt:
        pass
    finally:
        if process is not None:
            process.stdin.close()
            process.wait(timeout=30)


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
        f"and the key is in {KEY_FILE}. Stop it: systemctl --user disable --now ty-stream.service")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", nargs="?", choices=["watch", "frame", "key"])
    ap.add_argument("--to", help="with watch: stream into this file instead, to try it")
    ap.add_argument("--install", action="store_true", help="with watch: run it as a systemd user service")
    args = ap.parse_args(argv)
    if args.action == "watch" and args.install:
        return install()
    if args.action == "watch":
        return watch(args.to)
    if args.action == "key":
        text = getpass.getpass("Stream key (not shown): ") if sys.stdin.isatty() else sys.stdin.readline()
        print(f"Kept in {KEY_FILE}." if keep_key(text) else "Nothing pasted: the key is unchanged.")
        return
    if args.action == "frame":
        PREVIEW.parent.mkdir(parents=True, exist_ok=True)
        frame(status()).save(PREVIEW, quality=90)
        print(f"saved {PREVIEW}")
        return
    s, st = settings(), status()
    print(f"Streaming is {'on' if s['enabled'] else 'off'}; service {s['service']}; "
          f"stream key {'in place' if key() else 'not set'} ({KEY_FILE}).")
    print(f"A run is {'imaging now: it would stream' if imaging(st) else 'not imaging: it would wait'}.")
    device = working_device()
    print(f"Video encoding: {device or 'the processors'}; "
          f"ffmpeg {'found' if shutil.which('ffmpeg') else 'NOT found'}.")


if __name__ == "__main__":
    sys.exit(main())
