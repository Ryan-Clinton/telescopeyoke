#!/usr/bin/env python3
"""Tell the house when the sky turns: a Hue light changes colour and a Google
Home speaker says so.

    ./alert.py watch           keep watching; alert when cloud or rain arrives, and when it clears
    ./alert.py check           look once and say what it finds; alerts as watch would
    ./alert.py test cloud      make the alert for cloud now (also: clouded, rain, clear)
    ./alert.py say "words"     say something on the speaker
    ./alert.py pair            press the button on the Hue bridge, then run this once
    ./alert.py lights          the lights the bridge has, and which do colour
    ./alert.py speakers        the speakers found on the network

--dry-run on any of them says what would be done and touches nothing.

What it watches: the stars in the frames of an imaging run that is going
(real cloud, as the telescope sees it), and the forecast for the next hour
(rain, and cloud when no run is going). Setting it up: docs/alerts.md. The
Hue and speaker code follows pastie's (github.com/Ryan-Clinton/pastie-hon).
"""
import argparse
import hashlib
import http.server
import json
import secrets
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

import config

CACHE = config.DATA / "cache"
PAIRING = CACHE / "hue.json"            # the bridge's address and the key it issued
STATE = CACHE / "alerts.json"           # what was last announced, so each change is told once
SPEECH = CACHE / "speech"               # rendered sentences, by what they say
FRAMES = config.DATA / "frames"

# Colours as CIE xy, which is what the bridge's current interface speaks:
# unmistakable from the next room, not colour management.
COLOURS = {"Green": (0.17, 0.70), "Red": (0.675, 0.322), "Orange": (0.55, 0.41), "Yellow": (0.45, 0.48),
           "Blue": (0.167, 0.04), "Purple": (0.28, 0.11), "Pink": (0.40, 0.19), "Cyan": (0.17, 0.34)}
# What each thing worth telling looks and sounds like, unless [alerts] says otherwise.
EVENTS = {
    "cloud": ("Orange", "Getting cloudy."),
    "clouded": ("Red", "Clouded out. The telescope has lost the stars."),
    "rain": ("Blue", "Rain is on the way. Cover the telescope."),
    "clear": ("Green", "The sky has cleared."),
}
DEFAULTS = {"seconds": 20, "brightness": 100, "restore": True, "every": 60}

# The sky as the run's frames show it: the light of each frame's measured
# stars, set against the best the run has managed. Cloud dims the stars long
# before it hides them, and the count of stars is no guide, since a rich field
# is counted only up to a limit (every frame of 13 October 2026 said 300,
# while their light held steady to within a tenth).
RECENT = 5              # frames judged together, so one gust or satellite decides nothing
ENOUGH = 12             # frames a run needs before its best count means anything
THIN, GONE, BACK = 0.6, 0.2, 0.85       # shares of the best light: getting cloudy, clouded out, clear again
STALE = 180             # seconds without a frame after which a run is not "going"
SETTLED = 5             # looks in a row the sky must read clear before "cleared" is said: broken
                        # cloud on 14 October 2026 said cloud, clear and cloud again inside four minutes
# The forecast for the hour ahead.
RAIN_CHANCE, RAIN_MM = 50, 0.1
CLOUD_NOW, CLOUD_NEXT = 40, 70          # per cent: clear enough now, and cloudy enough next hour, to say so


TRIES = 4               # times the bridge is asked before giving up


class AlertError(RuntimeError):
    pass


def settings():
    """[alerts] from config.toml over the defaults, with the pairing kept by `pair`."""
    found = dict(DEFAULTS)
    if PAIRING.exists():
        found.update(json.loads(PAIRING.read_text(encoding="utf-8")))
    found.update(config.hardware().get("alerts", {}))
    return found


# --- the Hue bridge -----------------------------------------------------------

class Bridge:
    """The few calls of the bridge's current interface (CLIP v2) this needs.
    A key from the old interface is accepted as it is."""

    def __init__(self, address, key):
        if not address or not key:
            raise AlertError("No Hue bridge is set up: press its button and run ./alert.py pair")
        self.base, self.key = f"https://{address}/clip/v2/resource", key
        # The bridge's certificate names its own id, not its address, and it
        # is a device on this network told to make a light orange: it is not
        # checked.
        self.context = ssl.create_default_context()
        self.context.check_hostname, self.context.verify_mode = False, ssl.CERT_NONE

    def ask(self, path, method="GET", body=None):
        request = urllib.request.Request(
            self.base + path, method=method, data=None if body is None else json.dumps(body).encode(),
            headers={"hue-application-key": self.key, "Content-Type": "application/json"})
        # Tried a few times: on 14 October 2026, over a weak Wi-Fi link, a
        # light was turned green and the call to put it back timed out, so
        # it stayed green.
        for attempt in range(TRIES):
            try:
                with urllib.request.urlopen(request, timeout=10, context=self.context) as answer:
                    return json.load(answer).get("data", [])
            except urllib.error.HTTPError as error:
                raise AlertError("The Hue bridge refused the key: run ./alert.py pair again" if error.code in (401, 403)
                                 else f"The Hue bridge answered {error.code}") from error
            except (urllib.error.URLError, OSError) as error:
                if attempt == TRIES - 1:
                    raise AlertError(f"Could not reach the Hue bridge: {error}") from error
                time.sleep(2)

    def lights(self):
        return self.ask("/light")

    def light(self, light_id):
        found = self.ask(f"/light/{light_id}")
        if not found:
            raise AlertError("That light is no longer on the bridge.")
        return found[0]

    def put(self, light_id, body):
        self.ask(f"/light/{light_id}", "PUT", body)


def does_colour(light):
    return isinstance(light.get("color"), dict)


def state_of(light):
    """The parts of a light's state worth putting back."""
    state = {"on": {"on": bool(light.get("on", {}).get("on", False))}}
    if "brightness" in (light.get("dimming") or {}):
        state["dimming"] = {"brightness": light["dimming"]["brightness"]}
    if isinstance((light.get("color") or {}).get("xy"), dict):
        state["color"] = {"xy": dict(light["color"]["xy"])}
    return state


def still_shows(light, wanted):
    """Whether a light still shows what it was set to. Someone who switched
    it off or changed it during an alert meant to: it is then left alone."""
    if bool(light.get("on", {}).get("on")) is not bool(wanted["on"]["on"]):
        return False
    level = light.get("dimming", {}).get("brightness")
    if level is None or abs(float(level) - float(wanted["dimming"]["brightness"])) > 5:
        return False
    if "color" in wanted:
        xy = (light.get("color") or {}).get("xy") or {}
        return all(abs(float(xy.get(axis, 0)) - float(wanted["color"]["xy"][axis])) <= 0.05 for axis in "xy")
    return True


def find_light(bridge, name):
    lights = bridge.lights()
    for light in lights:
        if name in (light.get("id"), light.get("metadata", {}).get("name")):
            return light
    known = ", ".join(sorted(light.get("metadata", {}).get("name", "?") for light in lights))
    raise AlertError(f"No light called '{name}' on the bridge. It has: {known}")


def colour_light(bridge, light, colour, brightness=100, seconds=20, restore=True, sleep=time.sleep):
    """Show `colour` on one light for `seconds`, breathing so it is noticed,
    then put the light back as it was if nobody has changed it meanwhile.
    A white-only light pulses instead. Returns what was done, in words."""
    before = state_of(light)
    wanted = {"on": {"on": True}, "dimming": {"brightness": float(brightness)}}
    if does_colour(light):
        x, y = COLOURS.get(colour, COLOURS["Orange"])
        wanted["color"] = {"xy": {"x": x, "y": y}}
    name = light.get("metadata", {}).get("name", light["id"])
    bridge.put(light["id"], {**wanted, "alert": {"action": "breathe"}})
    sleep(seconds)
    if not restore:
        return f"{name} set {colour.lower()} and left so"
    if not still_shows(bridge.light(light["id"]), wanted):
        return f"{name} went {colour.lower()}; it was changed meanwhile, so it was left alone"
    bridge.put(light["id"], before)
    return f"{name} went {colour.lower()} for {seconds:g} s and was put back"


def pair(address=None):
    """Ask the bridge for a key. Its button must have been pressed in the last
    half minute; the key and the address are kept in cache/hue.json."""
    if not address:
        with urllib.request.urlopen("https://discovery.meethue.com/", timeout=10) as answer:
            bridges = json.load(answer)
        if not bridges:
            raise AlertError("No Hue bridge was found on this network. Give its address with --address.")
        address = bridges[0]["internalipaddress"]
    context = ssl.create_default_context()
    context.check_hostname, context.verify_mode = False, ssl.CERT_NONE
    request = urllib.request.Request(f"https://{address}/api", method="POST",
                                     data=json.dumps({"devicetype": "telescopeyoke#laptop"}).encode())
    with urllib.request.urlopen(request, timeout=10, context=context) as answer:
        reply = json.load(answer)[0]
    if "error" in reply:
        raise AlertError(f"The bridge at {address} said: {reply['error'].get('description', reply['error'])}. "
                         "Press the round button on top of it and run this again within half a minute.")
    PAIRING.parent.mkdir(parents=True, exist_ok=True)
    PAIRING.write_text(json.dumps({"hue_address": address, "hue_key": reply["success"]["username"]}), encoding="utf-8")
    return address


# --- the speaker ---------------------------------------------------------------

def spoken(text, render=None):
    """The sentence as MP3, rendered once and kept: rendering is the slow part."""
    path = SPEECH / (hashlib.sha256(text.encode()).hexdigest()[:16] + ".mp3")
    if path.exists() and path.stat().st_size:
        return path.read_bytes()
    if render is None:
        try:
            from gtts import gTTS
        except ImportError as error:
            raise AlertError("Speech needs gTTS: sudo apt install python3-gtts") from error
        from io import BytesIO

        def render(words):
            out = BytesIO()
            gTTS(text=words, lang="en", tld="co.uk").write_to_fp(out)
            return out.getvalue()
    audio = render(text)
    if not audio:
        raise AlertError("The speech service returned nothing.")
    SPEECH.mkdir(parents=True, exist_ok=True)
    path.write_bytes(audio)
    return audio


def lan_address():
    """This computer's address as the speaker sees it. Nothing is sent: the
    socket only asks which way the traffic would go."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


class Served:
    """One file, held in memory, at a path nobody could guess, for as long as
    the speaker needs to fetch it. A speaker cannot be handed sound, only an
    address to fetch it from, and this is the whole of what is offered."""

    def __init__(self, body, kind="audio/mp3"):
        path = "/" + secrets.token_urlsafe(24) + ".mp3"

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != path:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer((lan_address(), 0), Handler)
        self.url = f"http://{self.server.server_address[0]}:{self.server.server_address[1]}{path}"

    def __enter__(self):
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self.url

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def cast():
    try:
        import pychromecast
    except ImportError as error:
        raise AlertError("The speaker needs pychromecast: sudo apt install python3-pychromecast") from error
    return pychromecast


def speakers():
    found, browser = cast().get_chromecasts(timeout=8)
    try:
        return sorted((s.cast_info.friendly_name, s.cast_info.model_name or "", s.cast_info.host) for s in found)
    finally:
        browser.stop_discovery()


def connect(name, address=None):
    """The named speaker: straight to its address if that is known, since
    finding speakers by name fails on some networks, and by searching if not."""
    import uuid
    pychromecast = cast()
    # Tried three times: from the garden the laptop's Wi-Fi is weak, and on
    # 14 October one try in two failed there, while from the house on the
    # 16th every one of three found it in under three seconds.
    for _ in range(3 if address else 0):
        try:
            speaker = pychromecast.get_chromecast_from_host((address, 8009, uuid.UUID(int=0), "", name), timeout=8)
            speaker.wait(timeout=15)
            return speaker
        except Exception:       # the address may have changed; look for it by name after
            time.sleep(2)
    found, browser = pychromecast.get_chromecasts(timeout=10)
    try:
        for speaker in found:
            if speaker.cast_info.friendly_name == name:
                speaker.wait(timeout=15)
                return speaker
    finally:
        browser.stop_discovery()
    raise AlertError(f"Could not find a speaker called '{name}'. ./alert.py speakers lists them.")


def announce(text, name, address=None, volume=None):
    """Say `text` on the speaker and let go of it, so what was playing can resume."""
    audio = spoken(text)
    speaker = connect(name, address)
    before = None
    with Served(audio) as url:
        try:
            if volume is not None:
                before = speaker.status.volume_level
                speaker.set_volume(float(volume))
            media = speaker.media_controller
            media.play_media(url, "audio/mp3")
            media.block_until_active(timeout=15)
            started = time.time()
            while time.time() - started < 8 and media.status.player_state != "PLAYING":
                time.sleep(0.2)
            while time.time() - started < 45 and media.status.player_state not in ("IDLE", "UNKNOWN"):
                time.sleep(0.3)
        finally:
            if before is not None:
                speaker.set_volume(before)
            try:
                speaker.quit_app()
            except Exception:   # tidying up must not hide what went before
                pass
    return f"said on {name}: {text}"


# --- what is worth telling -----------------------------------------------------

def sky_from_frames(stars):
    """'clear', 'cloud' or 'clouded' from the light of a run's stars, frame
    by frame, oldest first, or None while there are too few frames to say.
    The last few are set against the best the run has shown. A frame with no
    stars measured counts as none."""
    stars = [s or 0 for s in stars]
    if len(stars) < ENOUGH:
        return None
    best = float(np.percentile(stars[:-RECENT], 90))
    if best <= 0:
        return None
    share = float(np.median(stars[-RECENT:])) / best
    return "clouded" if share <= GONE else "cloud" if share <= THIN else "clear" if share >= BACK else None


def run_going(now=None, frames=FRAMES):
    """The light of the stars in each frame of the imaging run that is going,
    or None: the newest session with a frame in the last few minutes."""
    now = now or time.time()
    logs = sorted(frames.glob("*/*/frames.jsonl"), key=lambda p: p.stat().st_mtime) if frames.exists() else []
    if not logs or now - logs[-1].stat().st_mtime > STALE:
        return None
    counts = []
    for line in logs[-1].read_text(encoding="utf-8").splitlines():
        try:
            counts.append(json.loads(line).get("flux"))
        except ValueError:
            pass
    return counts


def forecast(weather, now=None):
    """(rain coming, cloud coming) for the hour ahead, from feeds.weather()."""
    now = now or time.time()
    t = np.array(weather["time"], dtype=float)
    here = int(np.searchsorted(t, now, side="right")) - 1
    if here < 0 or here + 1 >= len(t):
        return False, False
    ahead = (here, here + 1)
    rain = any((weather["precipitation_probability"][i] or 0) >= RAIN_CHANCE
               or (weather["precipitation"][i] or 0) >= RAIN_MM for i in ahead)
    cloud = weather["cloud_cover"][here] <= CLOUD_NOW and weather["cloud_cover"][here + 1] >= CLOUD_NEXT
    return rain, cloud


def decide(before, sky, rain, cloud_forecast):
    """What to tell, as a list of events, and what to remember: `before` is
    {"sky": ..., "rain": ...} from last time. Each change is told once. With
    a run going the frames say what the sky is doing; with none, the forecast
    may say cloud is coming, and never that it has cleared."""
    events, now = [], dict(before)
    if rain and not before.get("rain"):
        events.append("rain")
    now["rain"] = bool(rain)
    if sky is None and cloud_forecast and before.get("sky") in (None, "clear"):
        sky = "cloud"
    was = before.get("sky")
    if sky == "clear" and was in ("cloud", "clouded"):
        # Clearing is said only once it has lasted, and only after cloud.
        now["clear_looks"] = before.get("clear_looks", 0) + 1
        if now["clear_looks"] < SETTLED:
            return events, now
        events.append("clear")
    elif sky is not None and sky != was and sky != "clear":
        # Cloud after clear, or worse cloud; thinning from clouded out to cloud is not news.
        if not (was == "clouded" and sky == "cloud"):
            events.append(sky)
    if sky is not None:
        now["sky"], now["clear_looks"] = sky, 0
    return events, now


def tell(event, dry_run=False, say_it=print):
    """Make the alert for one event: the light, then the speaker. Each is done
    if it is set up; one failing does not stop the other."""
    s = settings()
    colour, words = EVENTS[event]
    colour, words = s.get(f"{event}_colour", colour), s.get(f"{event}_words", words)
    if dry_run or config.DEMO:
        say_it(f"Would turn {s.get('light', 'no light chosen')} {colour.lower()} and say \"{words}\" "
               f"on {s.get('speaker', 'no speaker chosen')}.")
        return
    done = []
    thread = None
    if s.get("light"):
        def lit():
            try:
                bridge = Bridge(s.get("hue_address"), s.get("hue_key"))
                done.append(colour_light(bridge, find_light(bridge, s["light"]), colour,
                                         s["brightness"], s["seconds"], s["restore"]))
            except AlertError as error:
                done.append(f"light: {error}")
        thread = threading.Thread(target=lit)
        thread.start()          # the light holds its colour while the speaker talks
    if s.get("speaker"):
        try:
            done.append(announce(words, s["speaker"], s.get("speaker_address"), s.get("volume")))
        except AlertError as error:
            done.append(f"speaker: {error}")
    if thread:
        thread.join()
    for line in done or ["Nothing is set up to tell: see docs/alerts.md."]:
        say_it(line)


def check(dry_run=False, say_it=print):
    """Look once: the run's frames and the forecast. Tells what has changed
    since last time and returns the events told."""
    import feeds
    before = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    counts = run_going()
    sky = sky_from_frames(counts) if counts else None
    try:
        site = config.load()["site"]
        rain, cloud = forecast(feeds.weather(site["latitude"], site["longitude"]))
    except Exception as error:      # no network, no site: the frames still count
        say_it(f"forecast not read: {error}")
        rain, cloud = False, False
    events, now = decide(before, sky, rain, cloud)
    watching = "no run going" if counts is None else f"a run going, {len(counts)} frames, sky {sky or 'not yet judged'}"
    say_it(f"{time.strftime('%H:%M')}  {watching}; rain in the next hour: {'yes' if rain else 'no'}"
           + (f"  -> {', '.join(events)}" if events else ""))
    for event in events:
        tell(event, dry_run, say_it)
    if not dry_run:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(now), encoding="utf-8")
    return events


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["watch", "check", "test", "say", "pair", "lights", "speakers"])
    ap.add_argument("what", nargs="?", help="for test: cloud, clouded, rain or clear; for say: the words")
    ap.add_argument("--address", help="for pair: the bridge's address, if it is not found by itself")
    ap.add_argument("--dry-run", action="store_true", help="say what would be done; no light, no speaker")
    args = ap.parse_args(argv)
    try:
        if args.command == "pair":
            print(f"Paired with the bridge at {pair(args.address)}. ./alert.py lights shows what it has.")
        elif args.command == "lights":
            s = settings()
            for light in Bridge(s.get("hue_address"), s.get("hue_key")).lights():
                print(f"{light.get('metadata', {}).get('name', '?'):28} {'colour' if does_colour(light) else 'white only'}")
        elif args.command == "speakers":
            for name, model, host in speakers():
                print(f"{name:28} {model:20} {host}")
        elif args.command == "say":
            s = settings()
            if not args.what:
                ap.error("say needs the words")
            if not s.get("speaker"):
                raise AlertError("No speaker is chosen: see docs/alerts.md")
            print(f"Would say \"{args.what}\" on {s['speaker']}." if args.dry_run
                  else announce(args.what, s["speaker"], s.get("speaker_address"), s.get("volume")))
        elif args.command == "test":
            if args.what not in EVENTS:
                ap.error("test needs one of: " + ", ".join(EVENTS))
            tell(args.what, args.dry_run)
        elif args.command == "check":
            check(args.dry_run)
        else:
            every = settings()["every"]
            print(f"Watching the sky every {every:g} s. Ctrl+C to stop.")
            while True:
                try:
                    check(args.dry_run)
                except AlertError as error:
                    print(error)
                time.sleep(every)
    except AlertError as error:
        sys.exit(str(error))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
