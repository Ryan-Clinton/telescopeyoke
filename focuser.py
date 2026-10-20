#!/usr/bin/env python3
"""The focuser's motor: a 28BYJ-48 stepper driven by an Arduino Nano.

    ./focuser.py flash         load firmware/focuser onto the Nano
    ./focuser.py test          a quarter turn one way, then back
    ./focuser.py move 200      that many half-steps (4096 to a turn): plus takes the
                               drawtube out on the 150P, minus brings it in
    ./focuser.py bench --watch http://PHONE:4747/video
                               the step, the slack and how it comes back, off a
                               camera watching a stick on the shaft; no stars
    ./focuser.py load-test --watch http://PHONE:4747/video
                               on the telescope, the stick on the other knob: how
                               much of each turn reaches the focuser, each way

Building and wiring it: docs/focuser.md. `./focus.py --motor` uses it to
bring the stars to focus with nobody touching the telescope.
"""
import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

import config
import host

ROOT = Path(__file__).parent
SKETCH = ROOT / "firmware" / "focuser"
MATCH = "1a86"              # the CH340 chip on a Nano clone, as /dev/serial/by-id names it
TURN = 4096                 # half-steps to one turn of the motor's shaft
MOST = 10 * TURN            # the firmware refuses more in one order
STEP_SECONDS = 0.020       # as the firmware's STEP_MS
# A Nano clone usually has the old bootloader; a genuine one the new.
BOARDS = ("arduino:avr:nano:cpu=atmega328old", "arduino:avr:nano:cpu=atmega328")


def find_port(port=None):
    """The Nano's port: the one named, or the one whose USB adapter matches.
    Never a guess, since the handset's lead is a serial port too."""
    match = config.hardware().get("focuser", {}).get("serial_match", MATCH)
    found = port or host.serial_port(match)
    if not found:
        seen = ", ".join(f"{device} ({name})" for device, name in host.serial_ports())
        sys.exit(f"No serial port matches \"{match}\". Ports seen: {seen or 'none'}. "
                 "Plug in the Nano, or name its port with --port.")
    return found


class Focuser:
    """The Nano, once it runs firmware/focuser."""

    def __init__(self, link):
        self.link = link
        self.step_seconds = STEP_SECONDS

    @classmethod
    def open(cls, port=None):
        import serial
        link = serial.Serial(find_port(port), 9600, timeout=1)
        time.sleep(2)               # opening the port restarts a Nano; let it come up
        link.reset_input_buffer()
        focuser = cls(link)
        if focuser.ask(":?", 2) != "TY focuser 1":
            link.close()
            sys.exit("The Nano did not answer as a focuser. Load the firmware with ./focuser.py flash")
        return focuser

    def ask(self, order, wait):
        self.link.write(order.encode() + b"\n")
        until = time.monotonic() + wait
        reply = b""
        while time.monotonic() < until and not reply.endswith(b"\n"):
            reply += self.link.read(1)
        return reply.decode(errors="replace").strip()

    def move(self, steps):
        """Turn the motor by `steps` half-steps and wait for it to finish."""
        if not steps or abs(steps) > MOST:
            raise ValueError(f"a move is 1 to {MOST} half-steps, not {steps}")
        reply = self.ask(f":M{steps:+d}", abs(steps) * self.step_seconds + 3)
        if reply != f"OK {steps}":
            raise RuntimeError(f"the focuser answered {reply!r} to a move of {steps}")

    def speed(self, ms):
        """Step every `ms` milliseconds until the Nano next restarts, which
        opening its port does: slower is stronger, for trying what the
        drawtube needs (19 October 2026)."""
        if not 2 <= ms <= 200:
            raise ValueError(f"a step takes 2 to 200 ms, not {ms}")
        reply = self.ask(f":S{ms}", 2)
        if reply != f"OK S{ms}":
            raise RuntimeError(f"the focuser answered {reply!r} to a speed of {ms} ms: load the firmware "
                               "with ./focuser.py flash")
        self.step_seconds = ms / 1000

    def close(self):
        self.link.close()


def find_pointer(picture, marked=None):
    """The protractor and the stick laid across the motor's shaft, in a
    picture looking down on them (docs/focuser.md, "Checking the motor on
    the bench"): {"angle", "centre", "radius", "stick_pixels"}, or None if
    either is missing. The protractor is the largest white patch that is
    round, so a pale floor or a wall is passed over; the stick is the
    warm-coloured line inside it, wood against white paper and blue print.
    Its angle, 0 to 180 degrees, is the long axis of those pixels fitted
    along the stick's whole length, to about a fifth of a degree in one picture.
    It is measured against the picture's own rows: a phone that switches
    lens shifts and scales the picture but does not turn it. With `marked`,
    a copy of the picture is saved there with the protractor ringed and
    the stick's line drawn, to see what was found."""
    import numpy as np
    from PIL import Image, ImageDraw
    from scipy import ndimage
    image = Image.open(picture).convert("RGB")
    rgb = np.asarray(image, dtype=np.float32)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    grey = (r + g + b) / 3
    bright = ndimage.binary_opening(grey > np.percentile(grey, 60) + 20, iterations=2)
    bright = ndimage.binary_fill_holes(bright)
    patches, count = ndimage.label(bright)
    paper, best = None, 0
    for i, box in enumerate(ndimage.find_objects(patches), start=1):
        h, w = box[0].stop - box[0].start, box[1].stop - box[1].start
        area = float((patches[box] == i).sum())
        # A disc fills pi/4 of its square box; a floor or a strip of wall does not.
        if area > best and area > 0.005 * patches.size and 0.75 < h / w < 1.33 \
                and 0.65 < area / (h * w) < 0.9:
            paper, best = (patches == i), area
    if paper is None:
        return None
    ys, xs = np.nonzero(paper)
    cy, cx, radius = ys.mean(), xs.mean(), np.sqrt(paper.sum() / np.pi)
    yy, xx = np.indices(paper.shape)
    inside = np.hypot(yy - cy, xx - cx) < 0.95 * radius
    # The stick is blacked with a marker: pale wood was too like the paper
    # and the protractor's shaded wedges to be told apart by its colour
    # (19 October 2026: a run read a stick at 34° as -15°). How much darker
    # than the paper each pixel is, within the paper.
    paper_level = float(np.median(grey[inside]))
    dark = np.where(inside, np.clip(paper_level - ndimage.uniform_filter(grey, 3), 0, None), 0)
    # Not the printed scale: its lines are blue, and far thinner than the
    # stick, so an opening wider than they are clears them.
    bar = ndimage.binary_opening((dark > 0.35 * paper_level) & (b < r + 15), iterations=2)
    dark = np.where(bar, dark, 0)
    # The darkest straight bar, at any angle and any offset: the paper is
    # cut by hand, so its middle is not the shaft, and a search only through
    # the middle flipped between two near misses 12° apart, picture by
    # picture (19 October 2026). Every dark pixel votes, by its darkness,
    # for the lines through it (a Radon transform), and the strongest wins.
    ys, xs = np.nonzero(dark)
    if len(xs) < 50:
        return None
    vote = dark[ys, xs]
    best, best_off, best_score = 0.0, 0.0, -1.0
    for trial in np.arange(0.0, 180.0, 0.5):
        t = np.radians(trial)
        offsets = -(xs - cx) * np.sin(t) + (ys - cy) * np.cos(t)
        counts, edges = np.histogram(offsets, bins=np.arange(-radius, radius + 3, 3), weights=vote)
        i = int(np.argmax(counts))
        if counts[i] > best_score:
            best, best_off, best_score = trial, float(edges[i] + 1.5), float(counts[i])
    # Then the line itself: the middle of the bar found across it at many
    # points along it, away from the hub, and a straight line fitted through
    # those middles, leaving out any a crossing printed line has pulled
    # aside. Every pixel of the bar's width and length counts, so a fraction
    # of a degree shows.
    t = np.radians(best)
    along, aside = np.array([np.cos(t), np.sin(t)]), np.array([-np.sin(t), np.cos(t)])
    # Measured from the point of that line nearest the paper's middle.
    ox, oy = cx + best_off * aside[0], cy + best_off * aside[1]
    width = np.linspace(-0.07, 0.07, 29) * radius
    points = []
    for d in np.concatenate([np.linspace(0.32, 0.86, 40), -np.linspace(0.32, 0.86, 40)]) * radius:
        xs_ = ox + d * along[0] + width * aside[0]
        ys_ = oy + d * along[1] + width * aside[1]
        profile = ndimage.map_coordinates(dark, [ys_, xs_], order=1)
        peak = int(np.argmax(profile))
        if profile[peak] < 0.35 * paper_level:                  # no bar here
            continue
        # Only the bar's own core: the run darker than half its peak, up to
        # the first gap, so a printed line lying alongside adds nothing.
        lo = hi = peak
        while lo > 0 and profile[lo - 1] > profile[peak] / 2:
            lo -= 1
        while hi < len(profile) - 1 and profile[hi + 1] > profile[peak] / 2:
            hi += 1
        core = profile[lo:hi + 1] - profile[peak] / 2
        points.append((d, float((core * width[lo:hi + 1]).sum() / core.sum()), hi - lo + 1))
    if len(points) < 12:
        return None
    d, off, wide = np.array(points).T
    # Where a printed line touches the bar their cores merge, and the bar
    # looks wider there than anywhere else: those places are left out.
    keep = wide <= np.median(wide) + 1
    for _ in range(3):
        slope, icept = np.polyfit(d[keep], off[keep], 1)
        resid = off - (slope * d + icept)
        spread = 1.4826 * np.median(np.abs(resid[keep])) + 0.05
        keep = (np.abs(resid) < 3 * spread) & (wide <= np.median(wide) + 1)
    angle = float((best + np.degrees(np.arctan(slope))) % 180)
    xs = ox + d[keep] * along[0] + (slope * d[keep] + icept) * aside[0]
    ys = oy + d[keep] * along[1] + (slope * d[keep] + icept) * aside[1]
    x, y = np.cos(np.radians(angle)), np.sin(np.radians(angle))
    weight = np.ones(len(xs))
    if marked:
        d = ImageDraw.Draw(image)
        d.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], outline=(0, 255, 0), width=3)
        mx, my = np.average(xs, weights=weight), np.average(ys, weights=weight)
        d.line([mx - radius * x, my - radius * y, mx + radius * x, my + radius * y], fill=(255, 0, 255), width=2)
        image.save(marked)
    return {"angle": angle, "centre": [round(float(cx), 1), round(float(cy), 1)],
            "radius": round(float(radius), 1), "stick_pixels": int(len(xs))}


def pointer_angle(picture):
    """The stick's angle in a picture (find_pointer), or None."""
    found = find_pointer(picture)
    return None if found is None else found["angle"]


def turned(before, after):
    """How far the stick turned between two angles, -90 to 90 degrees: a
    stick looks the same half a turn round, so each move between pictures
    must be less than a quarter turn."""
    return (after - before + 90) % 180 - 90


class Watcher:
    """The latest picture from a camera looking down on the motor: a phone
    running DroidCam (its http:// address), a webcam (/dev/video...), or a
    picture file something else keeps up to date. One connection is held
    open for the whole run and the newest frame kept: a phone left without
    a viewer locks its screen and stops sending, and the first frames of a
    fresh connection come before its focus has settled (19 October 2026)."""

    def __init__(self, source, folder):
        self.source, self.process = str(source), None
        self.latest = Path(folder) / "latest.jpg"
        if self.source.startswith(("http://", "https://", "/dev/")):
            grab = (["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "2"]
                    if self.source.startswith("http") else ["-f", "v4l2"])
            self.process = subprocess.Popen(
                ["ffmpeg", "-loglevel", "error", "-y", *grab, "-i", self.source, "-vf", "fps=4",
                 "-update", "1", "-q:v", "2", str(self.latest)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            self.latest = Path(self.source)

    def picture(self, into, wait=20):
        """A copy of the newest frame made after this call, saved at `into`."""
        asked = time.time()
        until = time.monotonic() + wait
        while time.monotonic() < until:
            try:
                if self.latest.stat().st_mtime > asked:
                    time.sleep(0.1)                  # let the file finish being written
                    shutil.copyfile(self.latest, into)
                    return into
            except OSError:
                pass
            time.sleep(0.1)
        raise RuntimeError(f"no new picture from {self.source} in {wait} s: is the camera on?")

    def close(self):
        if self.process:
            self.process.terminate()
            self.process.wait(5)


def stick_reader(focuser, picture, settle=1.5, looks=3, sleep=time.sleep):
    """The way the bench and the load test read a blacked stick against the
    protractor: `where(label, steps)` moves (if asked), waits for the camera
    to catch up and the stick to stop, and gives the stick's angle; `lag()`
    measures once how many pictures the camera runs behind the motor, on a
    move of 256 half-steps. `rows` and `spreads` keep every place and its
    measuring spread."""
    import numpy as np
    rows, spreads = [], []

    behind = [0]       # pictures the camera runs behind the motor, measured below

    def look():
        angle = pointer_angle(picture())
        sleep(0.3)
        return angle

    def where(label, steps=0):
        if steps:
            focuser.move(steps)
        sleep(settle)
        for _ in range(behind[0]):
            look()                                  # still showing before the move
        # Then pictures until `looks` in a row agree: the stick has stopped.
        angles, tries = [], 0
        while tries < 8 * looks:
            tries += 1
            angle = look()
            if angle is not None:
                angles.append(angle)
            recent = angles[-looks:]
            if len(recent) == looks and np.ptp([turned(recent[0], a) for a in recent]) < 0.5:
                break
        angles = angles[-looks:]
        if not angles:
            raise RuntimeError("the stick could not be found in the pictures: check the camera's view")
        # Unwrapped round the first, so a stick near 0 or 180 averages right.
        middle = angles[0] + float(np.median([turned(angles[0], a) for a in angles]))
        if len(angles) > 1:
            spreads.append(float(np.ptp([turned(angles[0], a) for a in angles])))
        rows.append({"label": label, "steps": steps, "angle": round(middle % 180, 3)})
        return middle % 180

    def lag():
        first = where("start")
        # How far behind the camera runs: a phone's stream is a second or two
        # late (19 October 2026: a run read 64 half-steps as 1.4°, 3.2° and then
        # 17.5°), and pictures that agree with each other may all be from
        # before a move. Counted once, on a move of 22°, then waited out on
        # every move after.
        focuser.move(256)
        sleep(settle)
        for count in range(1, 40):
            angle = look()
            if angle is not None and abs(turned(first, angle)) > 5:
                behind[0] = count - 1               # the first picture showing the move is not behind
                break
        else:
            raise RuntimeError("the stick did not move in the pictures: is the camera watching the motor?")
        say_lag = f"the camera runs {behind[0]} picture{'s' if behind[0] != 1 else ''} behind the motor"
        return first, say_lag

    return where, lag, rows, spreads


def bench(focuser, picture, settle=1.5, looks=3, say=print, sleep=time.sleep):
    """How the motor really turns, measured off a stick on its shaft against
    a printed protractor, with no stars: docs/focuser.md, "Checking the
    motor on the bench". `picture()` gives a path to a fresh picture.

    Each place is the median of `looks` pictures in a row that agree, once
    the stick has stopped, and their spread is the measuring noise. Moves are kept under a quarter turn, as a stick looks
    the same half a turn round. In order: the slack taken up; four moves
    of 512 half-steps (an eighth of a turn) for the degrees a half-step
    really is; smaller moves of 64, 16 and 4 in the same direction; then
    the direction reversed 8 half-steps at a time, each way, until the
    stick moves, for the slack; and three trips of 256 out and back, for
    how closely it comes back to the same place."""
    import numpy as np
    where, lag, rows, spreads = stick_reader(focuser, picture, settle, looks, sleep)
    _, said = lag()
    say(said)
    start = where("slack taken up")
    big = [start]
    for _ in range(4):
        big.append(where("eighth turn", 512))
    per_step = float(np.mean([turned(a, b) for a, b in zip(big, big[1:])])) / 512
    say(f"512 half-steps turned {per_step * 512:.2f}° on average: {per_step:.4f}° a half-step, "
        f"{abs(360 / per_step):.0f} to a turn (4096 on paper)")
    small = []
    last = big[-1]
    for steps in (64, 64, 64, 16, 16, 16, 4, 4, 4):
        now = where("small move", steps)
        small.append({"steps": steps, "expected_deg": round(steps * per_step, 3),
                      "measured_deg": round(turned(last, now), 3)})
        last = now
    noise = float(np.median(spreads)) if spreads else 0.0
    slack = {}
    for name, sign in (("reversing in", -1), ("reversing out", 1)):
        before, pushed, moved_at = last, 0, []
        while pushed < 400:
            now = where(f"slack, {name}", 8 * sign)
            pushed += 8
            moved = abs(turned(before, now))
            if moved > max(0.3, 4 * noise):
                moved_at.append(pushed - moved / abs(per_step))
                if len(moved_at) >= 3:
                    break
            last = now
        slack[name] = round(float(np.median(moved_at)), 1) if moved_at else None
        last = where(f"clear of the slack, {name}", 64 * sign)
    say("slack: " + ", ".join(f"{k} {v if v is not None else 'over 400'} half-steps" for k, v in slack.items()))
    homes = []
    for _ in range(3):
        where("out", 256)
        homes.append(where("back", -256))
    spread_back = float(np.ptp([turned(homes[0], h) for h in homes]))
    say(f"back to the same place within {spread_back:.2f}° over three trips of 256 out and back; "
        f"measuring noise {noise:.2f}°")
    return {"degrees_per_half_step": round(per_step, 5), "half_steps_per_turn": round(abs(360 / per_step), 1),
            "noise_deg": round(noise, 3), "small_moves": small, "slack_half_steps": slack,
            "comes_back_within_deg": round(spread_back, 3), "places": rows}


DEGREES_PER_HALF_STEP = 0.088   # the motor's own turn, measured on the bench (19 October 2026)
LOAD_MOVE = 256                 # half-steps of each load-test move: 22.5°, well inside a quarter turn
LOAD_MOVES = 3                  # moves each way, after the first, which takes up the slack


def load_test(focuser, picture, per_step=DEGREES_PER_HALF_STEP, settle=1.5, looks=3, say=print,
              sleep=time.sleep):
    """How much of the motor's turn reaches the focuser on the telescope,
    each way: the stick on the focuser's other knob, which shares the
    motor's shaft through the coupler, read against the protractor as on
    the bench (docs/focuser.md, "When the motor cannot lift the drawtube").

    LOAD_MOVES moves of LOAD_MOVE half-steps out, then the same in, then out
    again: the first move each way takes up the slack (the motion lost at
    the reversal), the rest show what share of a steady move gets through.
    A share well under 1 one way only is slip under load that way (the
    bracket swinging on its thumbscrew, or the coupler on the shaft); low
    both ways is the coupler; full shares with the camera off and not with
    it on is the motor's strength."""
    import numpy as np
    where, lag, rows, spreads = stick_reader(focuser, picture, settle, looks, sleep)
    _, said = lag()
    say(said)
    last = where("start")
    legs = []
    for name, sign in (("out", 1), ("in", -1), ("out again", 1)):
        moved = []
        for k in range(LOAD_MOVES + 1):
            now = where(f"{name} {k + 1}", sign * LOAD_MOVE)
            moved.append(turned(last, now))
            last = now
        asked = LOAD_MOVE * per_step
        steady = [abs(m) / asked for m in moved[1:]]
        legs.append({"direction": name, "asked_deg": round(asked, 2), "moved_deg": [round(m, 2) for m in moved],
                     "lost_at_reversal_deg": round(max(0.0, asked - abs(moved[0])), 2),
                     "share_through": round(float(np.median(steady)), 2)})
        say(f"{name}: {', '.join(f'{abs(m):.1f}°' for m in moved)} for {asked:.1f}° asked each time; "
            f"{legs[-1]['share_through'] * 100:.0f}% of a steady move gets through, "
            f"{legs[-1]['lost_at_reversal_deg']:.1f}° lost at the reversal")
    out, inward = legs[0]["share_through"], legs[1]["share_through"]
    if out >= 0.9 and inward >= 0.9:
        verdict = "the turn gets through both ways: no slip under this load"
    elif min(out, inward) < 0.9 <= max(out, inward):
        verdict = (f"it slips {'in' if inward < out else 'out'} only: look at the bracket swinging on its "
                   "thumbscrew and the coupler's grub screw, with marks across each joint")
    else:
        verdict = ("it slips both ways: the coupler on the shaft first; if the same test passes with the camera "
                   "off, the motor is too weak for the load")
    say(verdict)
    noise = float(np.median(spreads)) if spreads else 0.0
    return {"legs": legs, "verdict": verdict, "noise_deg": round(noise, 3), "places": rows}


def run_bench(focuser, source, test=None):
    """bench() with a camera, its pictures and its answer kept under
    config.DATA/cache: the answer in focuser-bench-DATE.json, the pictures
    in focuser-bench/ with each one's marked copy beside it."""
    import json
    stamp = time.strftime("%Y%m%d-%H%M")
    folder = config.DATA / "cache" / "focuser-bench" / stamp
    folder.mkdir(parents=True, exist_ok=True)
    watcher = Watcher(source, folder)
    count = 0

    def picture():
        nonlocal count
        count += 1
        return watcher.picture(folder / f"{count:03d}.jpg")
    try:
        answer = (test or bench)(focuser, picture)
    finally:
        watcher.close()
        focuser.close()
    answer["source"], answer["pictures"] = str(source), str(folder)
    log = config.DATA / "cache" / f"focuser-bench-{stamp}.json"
    log.write_text(json.dumps(answer, indent=1), encoding="utf-8")
    print(f"kept in {log}")
    return answer


def flash(port=None):
    """Compile firmware/focuser and load it, trying each kind of Nano."""
    cli = shutil.which("arduino-cli") or shutil.which("arduino-cli", path=str(Path.home() / ".local" / "bin"))
    if not cli:
        sys.exit("arduino-cli is not installed: see docs/focuser.md")
    port = find_port(port)
    for board in BOARDS:
        subprocess.run([cli, "compile", "-b", board, str(SKETCH)], check=True, stdout=subprocess.DEVNULL)
        try:
            loaded = subprocess.run([cli, "upload", "-b", board, "-p", port, str(SKETCH)],
                                    capture_output=True, timeout=60).returncode == 0
        except subprocess.TimeoutExpired:       # the uploader waits for ever on a port that has gone
            sys.exit(f"Loading the firmware stalled: is the Nano still plugged in at {port}?")
        if loaded:
            print(f"firmware loaded on {port} ({board})")
            return
    sys.exit(f"Could not load the firmware on {port} as either kind of Nano.")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["flash", "test", "move", "angle", "bench", "load-test"])
    ap.add_argument("steps", nargs="?", type=int, help="for move: half-steps, minus for the other way")
    ap.add_argument("--pictures", nargs="+", help="for angle: the stick's angle in each picture")
    ap.add_argument("--watch", help="for bench: the camera looking down on the motor (a DroidCam "
                                    "http:// address, a /dev/video device, or a picture file kept up to date)")
    ap.add_argument("--port", help="the Nano's serial port, if it is not found by name")
    ap.add_argument("--ms", type=int, help=f"for move and test: milliseconds a half-step (default "
                                           f"{round(STEP_SECONDS * 1000)}; slower is stronger)")
    args = ap.parse_args(argv)

    if args.command == "flash":
        return flash(args.port)
    if args.command == "angle":
        for picture in args.pictures or ap.error("angle needs --pictures"):
            marked = Path(picture).with_name(Path(picture).stem + "-found.jpg")
            found = find_pointer(picture, marked)
            print(f"{picture}: " + ("no protractor or stick found" if found is None else
                                    f"{found['angle']:.2f}°, protractor at {found['centre']} radius "
                                    f"{found['radius']}, stick {found['stick_pixels']} pixels (see {marked.name})"))
        return
    if args.command == "move" and not args.steps:
        ap.error("move needs a number of half-steps")
    if args.command in ("bench", "load-test") and not args.watch:
        ap.error(f"{args.command} needs --watch, the camera looking down on the stick")
    focuser = Focuser.open(args.port)
    if args.command == "bench":
        return run_bench(focuser, args.watch)
    if args.command == "load-test":
        return run_bench(focuser, args.watch, test=load_test)
    try:
        if args.ms:
            focuser.speed(args.ms)
        for steps in ([TURN // 4, -TURN // 4] if args.command == "test" else [args.steps]):
            focuser.move(steps)
            print(f"moved {steps:+d} half-steps")
    finally:
        focuser.close()
    if args.command == "test":
        print("The shaft should have made a quarter turn and come back. The Nano cannot "
              "tell whether it did: a motor that only buzzes has two signal wires swapped.")


if __name__ == "__main__":
    main()
