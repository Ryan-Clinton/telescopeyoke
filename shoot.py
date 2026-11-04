#!/usr/bin/env python3
"""Take a picture: many short exposures, checked, lined up and averaged.

    ./shoot.py M27                          60 frames of 2 s
    ./shoot.py M27 --frames 300 --exposure auto
    ./shoot.py M27 --no-recentre            never move the mount
    ./shoot.py M27 --assist                 also trim the Dec motor's creep as it goes
    ./shoot.py M27 --frames 0 --through-cloud   cloud pauses it; it ends at dawn or
                                            when the target is too far past the meridian

Short exposures keep the stars round on a mount that drifts; averaging many
of them brings out faint detail and smooths the grain. For each frame it:
keeps the raw file, applies the dark and flat frames if calibrate.py has made
them, measures the stars, drops the frame if cloud or a knock spoiled it,
lines it up to a fraction of a pixel (rotation included), and adds it to a
running stack that leaves out satellite trails. The picture on the web page
updates as it goes.

At the end restack.py goes back over all the raw frames for the best result.
Everything is kept under frames/NAME/<date-time>/.

With --assist, the frames themselves act as a slow tracking sensor: every
so often the drift measured from how far frames had to be shifted is used to
trim the Dec motor's creep (see ./mount.py drift). It corrects the steady
slide from a rough polar alignment, not the gears' wobble; it is drift
assist, not guiding.

When the target has drifted well off centre the mount is sent back to it,
which needs serial access:
    sudo -u $USER -g dialout ./shoot.py M27 --frames 300
"""
import argparse
import json
import math
import os
import random
import subprocess
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import activity
import config
import live

import numpy as np
from PIL import Image

import host
import interface
import records
import process
import restack
import snap
import stacking
import tracking
import sxwheel
from camera import Camera, is_mono, stretch
from indi import IndiError as CameraError

ROOT = Path(__file__).parent
WEB = config.DATA / "web"
# Send the mount back to the target once it has drifted this far off centre,
# as a fraction of the frame's height. The drift up to then is welcome: it
# spreads the sensor's fixed pattern around, which averaging then removes.
DRIFT_LIMIT = 0.2
TRIAL_EXPOSURES = (2, 4, 8, 16, 30)   # the tracking test's lengths, in seconds
ASSIST_EVERY = 15   # accepted frames between trims of the Dec creep
# A running run looks here after every frame for an order from "ty run ...".
ORDERS = config.DATA / "cache" / "run_order.txt"
KNOWN_ORDERS = ("stop", "recentre", "assist-on", "assist-off")
RETAKE_GIVE_UP = 3  # with --frames N, no more retakes after this many rejected frames in a row
CLOUD_STOP = 20     # with --frames 0, stop after this many rejected frames in a row
JAM_REOPENS = 3     # a jammed camera is opened again this many times in a row before the run stops
JAM_WAIT_S = 20     # seconds before it is opened again
PREVIEW_EVERY = 3.0  # seconds between updates of the picture on the web page
FINISH_FROM = 5      # accepted frames before the live picture is finished like the final one
BACKLOG = 8         # frames allowed to wait for the live stack before it skips some


def clock_state(run=subprocess.run):
    """Whether the system clock is kept to time by network time (systemd's
    timedatectl), and when that was asked; "unknown" where it cannot say."""
    try:
        done = run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"], capture_output=True, text=True,
                   timeout=5)
        synced = {"yes": True, "no": False}.get(done.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        synced = None
    return {"synchronized": "unknown" if synced is None else synced,
            "checked": datetime.now(timezone.utc).isoformat(timespec="seconds")}


class Session:
    """One run on one target: the folder, the running stack and the log."""

    def __init__(self, name, exposure, gain, save=True, frames=None, preview_every=PREVIEW_EVERY):
        self.name = stacking.folder_name(name)
        self.folder = config.DATA / "frames" / self.name / f"{datetime.now():%Y%m%d-%H%M%S}"
        self.folder.mkdir(parents=True, exist_ok=True)
        # What was asked for, so the web page can say "frame 31 of 200".
        # And whether the computer's clock was kept to time, for timing transits,
        # and what kind of object it is, so the stream shows the Moon as the Moon.
        import sky
        records.write(self.folder / "session.json",
                      {"name": self.name, "frames": frames, "exposure": exposure, "gain": gain,
                       "object_kind": sky.object_kind(name), "clock": clock_state()}, indent=None)
        self.exposure, self.gain, self.save = exposure, gain, save
        self.calibration = stacking.Calibration(exposure, gain)
        self.reference, self.stack = None, None
        self.accepted, self.log = [], []
        self.drift = 0.0   # how far the newest frame was from the first since the last centring, in frame heights
        self.origin = None  # the shift of that first frame: drift is measured from it
        self.track = []    # (time, x shift, y shift) of accepted frames since the last trim
        self.shifts = []   # the same for every accepted frame of the run
        self.timings = stacking.Timings()
        self.preview_every, self.published = preview_every, 0.0

    def job(self, index, mosaic, header):
        """Arguments for stacking.live_frame for this frame, as things stand."""
        cards = {k: header[k] for k in stacking.KEPT if k in header}
        return (mosaic, cards, self.exposure, self.gain, str(self.folder), index, self.save,
                self.accepted[-30:], self.reference)

    def absorb(self, result, taken=None):
        """Add a processed frame to the stack and the log. Returns its log line."""
        entry, frame = result["entry"], result["frame"]
        entry["taken"] = round(taken or time.time(), 2)
        self.timings.add(result["timings"])
        if entry["accepted"]:
            with self.timings.phase("stack"):
                if self.reference is None:
                    self.reference = result["reference"]
                    self.stack = stacking.Stack(frame.shape)
                # Measured from the first frame since the last centring, not from the
                # reference: a GoTo past the meridian swings the tube over the pole and
                # the frames come back turned half round, a huge "shift" from the
                # reference with the target dead centre. 2 November 2026: NGC 7331 was
                # re-centred every four frames after the flip, with the aim steady to 1'.
                if self.origin is None:
                    self.origin = tuple(entry["shift"])
                self.drift = float(np.hypot(entry["shift"][0] - self.origin[0],
                                            entry["shift"][1] - self.origin[1])) / frame.shape[0]
                self.track.append((taken or time.time(), *entry["shift"]))
                self.shifts.append((taken or time.time(), *entry["shift"]))   # never cleared: the hold's
                self.stack.add(frame)
                self.accepted.append({k: entry[k] for k in
                                      ("fwhm", "roundness", "stars", "flux", "background", "noise")})
            self.publish()
        self.log.append(entry)
        stacking.append_log(self.folder, entry)
        index = entry["index"]
        if entry["accepted"]:
            return (f"{index:03d} ACCEPT  FWHM {entry['fwhm']:.1f}  round {entry['roundness']:.2f}  "
                    f"stars {entry['stars']}")
        detail = "" if entry["fwhm"] is None else f"FWHM {entry['fwhm']:.1f}  "
        return f"{index:03d} REJECT  {detail}{entry['reason']}"

    def process(self, index, mosaic, header):
        """One frame start to finish, in this process. The live run shares
        the first half between worker processes instead."""
        return self.absorb(stacking.live_frame(*self.job(index, mosaic, header)))

    def defer(self, index):
        """Note a frame the live stack had no time for; its raw file is kept
        for the quality pass."""
        entry = {"index": index, "accepted": False, "deferred": True, "fwhm": None, "stars": 0,
                 "reason": "live stack behind; kept for the quality pass"}
        self.log.append(entry)
        stacking.append_log(self.folder, entry)
        return f"{index:03d} LATER   {entry['reason']}"

    def publish(self, force=False):
        """Update the picture on the web page, at most every few seconds: when
        frames arrive quickly the page does not need every one. It is drawn
        by a separate process at low priority, from a copy of the stack, so
        the camera never waits for it: finishing the picture takes half a
        minute, and on 18 October 2026 every panel lost that much after its
        fifth frame, and still lost a minute when it was drawn in a thread of
        this process. While one is being drawn the next is skipped; the last
        one (`force`) waits for it and is drawn here, in full."""
        drawing = getattr(self, "drawing", None)
        if drawing is not None:
            if not drawing.done():
                if not force:
                    return
                drawing.result()
            spent = drawing.result() if drawing.exception() is None else None
            if spent:
                self.preview_every = max(self.preview_every, 5 * spent)
            self.drawing = None
        if not force and time.monotonic() - self.published < self.preview_every:
            return
        stacked, count = self.stack.result(), len(self.accepted)
        self.published = time.monotonic()
        if force:
            with self.timings.phase("update the web page"):
                draw_stack(stacked, count, self.name, self.exposure, WEB)
        elif getattr(self, "drawer", None) is None:
            draw_stack(stacked, count, self.name, self.exposure, WEB, False)    # only brightened: quick
        else:
            # The run's own worker pool, started before the first frame: a new
            # process started mid-run loads the whole program afresh, and the
            # camera waited for it a minute or more after the fifth frame of
            # every run (18 October 2026).
            self.drawing = self.drawer.submit(draw_stack, stacked, count, self.name, self.exposure, WEB, False)

    def picture(self, stacked=None, count=None):
        """The stack so far as a picture to show (finished_picture)."""
        stacked = self.stack.result() if stacked is None else stacked
        return finished_picture(stacked, len(self.accepted) if count is None else count, self.name)[0]

    def finish(self):
        records.write((self.folder / "frames.json"), self.log)
        if not self.accepted:
            return
        self.publish(force=True)
        stacking.write_stack(self.folder / "live.fits", self.stack.result(),
                             {"OBJECT": self.name, "NFRAMES": len(self.accepted),
                              "EXPTIME": self.exposure * len(self.accepted), "GAIN": self.gain})


def lowly():
    """A drawing process runs below the camera's: it must never hold up a frame."""
    import os
    try:
        os.nice(10)
    except (AttributeError, OSError):
        pass


def finished_picture(stacked, count, name):
    """(8-bit picture, seconds spent finishing). With enough frames in it,
    the stack is finished the way the final picture will be (the sky's glow
    and slope taken out, the colours balanced), so that what is watched
    looks like what will be kept; before that, or if that fails, plainly
    brightened."""
    if count >= FINISH_FROM:
        began = time.monotonic()
        try:
            return process.process(stacked, background=process.sky_for(name)), time.monotonic() - began
        except Exception as problem:     # never lose a run to its preview
            print(f"  (live picture left plain: {problem})", flush=True)
    return stretch(stacked), 0.0


def draw_stack(stacked, count, name, exposure, web, finish=True):
    """The live stack as the page's picture. Returns the seconds finishing
    took, so the page is updated less often when it is slow. Without
    `finish` it is only brightened: during a run the finishing loads every
    core for half a minute and starves the camera's download even from
    another process (18 October 2026: 93 s between 32 s frames), so it is
    kept for the picture at the end."""
    shown, spent = finished_picture(stacked, count if finish else 0, name)
    image = Image.fromarray(shown)
    web.mkdir(exist_ok=True)
    # The stack has its own picture; web/latest.jpg stays the newest
    # single frame, so the page shows both.
    image.resize((1600, round(1600 * image.height / image.width)), Image.LANCZOS) \
         .save(web / "stack.part.jpg", quality=88)
    host.replace_preview(web / "stack.part.jpg", web / "stack.jpg")
    image.save(web / f"{name}.jpg", quality=92)
    snap.label(f"live stack of {name}", f"{count} accepted frames · {exposure * count:.0f} s integration",
               web, name="stack", target=name)
    return spent


ORDER_STALE_S = 600    # an order not taken within this long is for a run that has gone


def tell(order, run=None):
    """Leave an order for the run that is going, or with `run` (its target)
    only for that run: on 1 November 2026 a "stop" timed for one run stopped
    the next. An order older than ORDER_STALE_S is never acted on."""
    if order not in KNOWN_ORDERS:
        raise interface.Refusal("INVALID_REQUEST", f"Unknown order '{order}'. Known: "
                                + ", ".join(KNOWN_ORDERS))
    ORDERS.parent.mkdir(exist_ok=True)
    ORDERS.write_text(json.dumps({"order": order, "run": run, "at": time.time()}), encoding="utf-8")
    return {"order": order, "run": run, "note": "The run acts on it after its next frame."}


def order(name=None, now=None):
    """The order left for this run, if any; it is taken, so it acts once. An
    order named for another run is left for it, and a stale one thrown away."""
    if not ORDERS.exists():
        return None
    text = ORDERS.read_text(encoding="utf-8").strip()
    try:
        left = json.loads(text)
    except ValueError:
        left = {"order": text, "run": None, "at": None}      # as written before 1 November 2026
    if not isinstance(left, dict):
        left = {"order": text, "run": None, "at": None}
    now = time.time() if now is None else now
    if left.get("at") is not None and now - left["at"] > ORDER_STALE_S:
        ORDERS.unlink(missing_ok=True)
        return None
    if left.get("run") and name and left["run"] != name:
        return None
    ORDERS.unlink(missing_ok=True)
    return left.get("order") if left.get("order") in KNOWN_ORDERS else None


def recentre(target, aim_off=(0.0, 0.0)):
    """Put the target back in the middle of the frame by plate solving, or
    with `aim_off` (arcminutes east and north) a little off it, for
    dithering. Returns False if the mount cannot be reached."""
    import config
    import mount
    try:
        scope = mount.Mount(watch=False)
    except (OSError, SystemExit) as problem:
        print(f"  mount not available ({problem}); carrying on without re-centring", flush=True)
        return False
    try:
        # A dither only has to land somewhere a little different: one GoTo,
        # no plate solving (17 October 2026: a solved dither took 1 to 3
        # minutes for a move of an arcminute). Centring the target solves.
        scope.goto_target(target, config.load()["site"], solve=not any(aim_off), aim_off=aim_off)
    except SystemExit as problem:
        print(f"  could not re-centre: {problem}", flush=True)
    except BaseException:
        scope.stop()
        raise
    return True


HOLD_LEARN = 4.0     # seconds of each learning move: at 20"/s, about 60 pixels
HOLD_RATE = 20.0     # arcsec/s of the hold's moves
HOLD_GAIN = 0.7      # share of the miss each correction takes back: a guider's habit, so it never overshoots
HOLD_SETTLE = 3      # frames kept after a move before the next is judged
HOLD_NO_BETTER = 3   # corrections in a row that leave the miss no smaller: the hold stops
HOLD_MOST = 600.0    # seconds of moving in all, in one run: beyond it the hold stops
HOLD_SLACK_RATIO = 1.5   # one Dec lesson this many times the other: the weaker lost its move to slack
HOLD_SLACK_MOST = 4.0    # seconds: the most slack ever taken up in one reversal
LEARNING = (("RA", +1), ("RA", -1), ("Dec", +1), ("Dec", -1))


class Hold:
    """The photometric hold: the target kept on the same pixels all night,
    for transits (20 October 2026: unguided, the field wandered 80 pixels
    and every star crossed different pixels, the first suspect for a 20 mmag
    floor in the photometry).

    It learns first, as a guider calibrates, each direction on its own: a
    move of HOLD_LEARN seconds east in RA, then back, then the same in Dec,
    each measured by how far the next frames' shifts move (the stacker's
    shift onto the first frame: `session.shifts`). Each direction is learnt
    apart because whether the handset adds a variable RA rate to tracking or
    replaces tracking with it is not known for this mount, and the two would
    make one direction several times stronger than the other. Then, when the
    frames have wandered more than `pixels`, it makes the moves that bring
    them back, HOLD_GAIN of the way. It stops itself when HOLD_NO_BETTER
    corrections in a row leave the miss no smaller, or after HOLD_MOST
    seconds of moving; it learns again after any re-centring (a GoTo may
    swing the tube over the pole, which turns the Dec response round). A
    correction is at most PULSE_LONGEST seconds on each axis, so a big miss
    is taken back over several; a frame that has drifted past DRIFT_LIMIT is
    re-centred by GoTo as in any run. No dithering."""

    def __init__(self, pixels, pulse=None):
        self.pixels = pixels
        self.pulse = pulse          # (axis, rate, seconds) -> moves the mount; set when the run starts
        self.reset()
        self.moved = 0.0            # seconds of moving so far
        self.state = "learn"

    def reset(self):
        """Learn again from the start: after a re-centring or a swing over the pole."""
        self.state = "learn"
        self.lesson = 0             # which of LEARNING is next
        self.before = None          # the shift before the learning move
        self.mark = 0               # how many frames had been kept at the last move
        self.columns = {}           # (axis name, sign) -> pixels of shift per second of move
        self.misses = []            # the miss before each correction
        self.dec_slack = 0.0        # seconds of Dec move the gears' slack swallows on a reversal
        self.dec_sign = None        # the way the Dec motor last turned

    @staticmethod
    def where(track, last=3):
        """The latest shift: the mean of the last few frames'."""
        return np.mean([(x, y) for _, x, y in track[-last:]], axis=0) if track else None

    @staticmethod
    def drifting(track, last=6):
        """The frames' own drift, pixels a second, from the last few: what a
        learning move's measurement must not count as the move's."""
        if len(track) < 3:
            return np.zeros(2)
        t = np.array([row[0] for row in track[-last:]], float)
        xy = np.array([row[1:] for row in track[-last:]], float)
        if np.ptp(t) <= 0:
            return np.zeros(2)
        return np.array([np.polyfit(t, xy[:, k], 1)[0] for k in (0, 1)])

    def due(self, track):
        """Whether a move is due now: never in the HOLD_SETTLE frames after one."""
        if self.state == "off" or len(track) - self.mark < HOLD_SETTLE:
            return False
        if self.state == "learn":
            return True
        return math.hypot(*self.where(track)) > self.pixels

    def learn_slack(self, say=print):
        """The Dec gears' slack, from the two Dec lessons. With no tracking in
        Dec the motor moves the frames as fast either way, so a lesson much
        weaker than the other lost part of its move to slack on the reversal:
        the weak direction is given the strong one's strength, and every Dec
        reversal from now on starts with the slack taken up. 2 November 2026:
        +Dec moved the frames 12.3 px a second and -Dec 2.0, the corrections
        never closed the miss, and the hold gave up mid-transit."""
        plus, minus = (float(np.hypot(*self.columns[("Dec", k)])) for k in (1, -1))
        strong, weak = max(plus, minus), min(plus, minus)
        if strong <= 0 or weak / strong > 1 / HOLD_SLACK_RATIO:
            return
        sign = 1 if plus >= minus else -1
        self.columns[("Dec", -sign)] = -self.columns[("Dec", sign)]
        self.dec_slack = min(HOLD_LEARN * (1 - weak / strong), HOLD_SLACK_MOST)
        say(f"  hold: Dec gear slack about {self.dec_slack:.1f} s of move; taken up on each reversal")

    def move(self, name, sign, seconds):
        import mount
        if name == "Dec":
            if self.dec_sign is not None and sign != self.dec_sign:
                seconds += self.dec_slack
            self.dec_sign = sign
        if self.moved + seconds > HOLD_MOST:
            raise interface.Refusal("INVALID_REQUEST", f"the hold has moved {self.moved:.0f} s in all this run")
        self.pulse(mount.RA if name == "RA" else mount.DEC, sign * HOLD_RATE, seconds)
        self.moved += seconds

    def step(self, track, say=print):
        """The next move: a learning one, or a correction."""
        try:
            self._step(track, say)
        except interface.Refusal as stopped:
            say(f"  hold: {stopped.message}; the hold is off")
            self.state = "off"

    def _step(self, track, say):
        now = self.where(track)
        if self.state == "learn":
            name, sign = LEARNING[self.lesson]
            if self.before is not None:
                then, drift, when = self.before
                elapsed = np.mean([row[0] for row in track[-3:]]) - when
                moved = (now - then - drift * elapsed) / HOLD_LEARN
                if math.hypot(*moved) < 0.2:
                    say(f"  hold: a move {'+' if sign > 0 else '-'}{name} did not move the frames; the hold is off")
                    self.state = "off"
                    return
                self.columns[(name, sign)] = moved
                say(f"  hold: {'+' if sign > 0 else '-'}{name} moves the frames {moved[0]:+.1f}, "
                    f"{moved[1]:+.1f} px a second")
                self.lesson += 1
                self.before = None
                if self.lesson == len(LEARNING):
                    self.state = "hold"
                    self.learn_slack(say)
                    say("  hold: learnt; holding from here")
                    self.mark = len(track)
                    return
                name, sign = LEARNING[self.lesson]
            # The drift from the frames since the last move only: a move's own jump is not drift.
            self.before = (now, self.drifting(track[self.mark:]), float(np.mean([row[0] for row in track[-3:]])))
            self.move(name, sign, HOLD_LEARN)
            self.mark = len(track)
            return
        self.correct(now, len(track), say)

    def solve(self, now):
        """Seconds of move in RA and Dec (signed) that take back HOLD_GAIN of
        `now`, each direction with its own learnt strength."""
        want = -HOLD_GAIN * np.asarray(now, float)
        signs = (1, 1)
        for _ in range(3):              # the signs decide the strengths, the strengths the signs
            m = np.column_stack([self.columns[("RA", signs[0])] * signs[0],
                                 self.columns[("Dec", signs[1])] * signs[1]])
            seconds = np.linalg.solve(m, want)
            new = tuple(1 if s >= 0 else -1 for s in seconds)
            if new == signs:
                break
            signs = new
        return seconds

    def correct(self, now, kept, say=print):
        """Moves that take back HOLD_GAIN of the shift `now`."""
        import mount
        miss = math.hypot(*now)
        self.misses.append(miss)                # only a correction made comes here
        recent = self.misses[-(HOLD_NO_BETTER + 1):]
        if len(recent) > HOLD_NO_BETTER and all(b >= a for a, b in zip(recent, recent[1:])):
            say(f"  hold: {HOLD_NO_BETTER} corrections left the miss no smaller ({miss:.0f} px); the hold is off")
            self.state = "off"
            return
        try:
            seconds = self.solve(now)
        except np.linalg.LinAlgError:
            say("  hold: RA and Dec move the frames the same way; the hold is off")
            self.state = "off"
            return
        longest = float(np.max(np.abs(seconds)))
        if longest > mount.PULSE_LONGEST:
            # A step of the way, the longest move the mount allows; the next corrections do the rest.
            seconds = seconds * (mount.PULSE_LONGEST / longest)
        say(f"  hold: {miss:.1f} px off; moving {seconds[0]:+.1f} s in RA, {seconds[1]:+.1f} s in Dec")
        for name, s in (("RA", seconds[0]), ("Dec", seconds[1])):
            if abs(s) >= 0.1:
                self.move(name, 1 if s > 0 else -1, abs(s))
        self.mark = kept


def hold_mover(name):
    """The hold's moves on the real mount, each through mount.Mount.pulse
    (its rate and length limits, and the motion lock), refused once the
    target is near the mount's limit or the Sun is up (night_over), with the
    Dec creep the tracking assist set put back after each Dec move."""
    import mount
    scope = mount.Mount(watch=False)
    site = config.load()["site"]

    def pulse(axis, rate, seconds):
        why = night_over(name, site)
        if why:
            raise interface.Refusal("INVALID_REQUEST", f"no more holding moves: {why}")
        try:
            creep = scope.drift_model(site).creep or 0.0
        except (OSError, KeyError, AttributeError, ValueError):
            if axis == mount.DEC:
                print("  hold: the Dec creep is not known; a Dec move leaves the creep off", flush=True)
            creep = 0.0
        return scope.pulse(axis, rate, seconds, creep=creep)
    return pulse


def assist(session):
    """Trim the Dec motor's creep from the drift the frames themselves show.
    Returns False if it cannot be done (no mount, or no plate solve to tell
    which way up the camera is)."""
    import config
    import mount
    if not mount.LAST_SOLVE.exists():
        print("  drift assist needs a plate solve first; skipped", flush=True)
        return False
    cd = json.loads(mount.LAST_SOLVE.read_text(encoding="utf-8")).get("cd")
    if not cd:
        return False
    times = [t for t, _, _ in session.track]
    residual, sigma = tracking.drift_from_shifts(times, [(x, y) for _, x, y in session.track], cd)
    try:
        scope = mount.Mount(watch=False)
    except (OSError, SystemExit):
        return False
    site = config.load()["site"]
    west = scope.west()
    model = scope.drift_model(site)
    creep = model.creep if model.creep is not None else 0.0
    model.observe(scope.true_hour_angle(site), mount.wrap(scope.radec()[1]),
                  residual - tracking.creep_effect(creep, west), sigma)
    wanted, decided = tracking.next_creep(creep, residual, sigma, west)
    new = scope.dec_creep(wanted)
    model.creep = new
    model.save()
    sure = "" if sigma is None else f" ±{sigma:.2f}"
    print(f"  Tracking assist: Dec drift {residual:+.2f}{sure} arcsec/s; creep "
          f"{creep:+.2f} -> {new:+.2f} ({decided})", flush=True)
    session.track.clear()
    return True


def pick_exposure(gain, calibration_for):
    """Try a few exposure lengths and keep the longest whose stars are still
    round and tight: the most light per frame the tracking allows tonight."""
    trials = []
    print("Tracking test:")
    with Camera(gain=gain) as cam:
        for seconds in TRIAL_EXPOSURES:
            mosaic, header = cam.frame(seconds)
            lum = stacking.prepare(mosaic, calibration_for(seconds), mono=is_mono(header)).sum(axis=2)
            q = stacking.quality(lum, stacking.find_stars(lum))
            trials.append((seconds, q))
            shape = "no stars" if q["fwhm"] is None else \
                f"FWHM {q['fwhm']:.1f}  roundness {q['roundness']:.2f}  stars {q['stars']}"
            print(f"  {seconds} s  {shape}", flush=True)
    chosen = stacking.choose_exposure(trials)
    if chosen is None:
        raise interface.Refusal("NO_STARS", "No stars in any trial exposure: cloud, or "
                                "badly out of focus.")
    print(f"Selected exposure: {chosen} s")
    return float(chosen)


def short_changed(taken, exposure):
    """The typical time between frames, if it is less than the exposure
    asked for, which no camera doing as it is told can manage; None
    otherwise. On 6 October 2026 the 183C delivered a "15 s" frame every
    11.6 s: it was exposing for about two-thirds of what it was asked."""
    times = sorted(t for t in taken if t)
    gaps = [b - a for a, b in zip(times, times[1:])]
    if len(gaps) < 5:
        return None
    typical = float(np.median(gaps))
    return typical if typical < 0.97 * exposure else None


def restack_later(folder, start=subprocess.Popen, say=lambda line: print(line, flush=True)):
    """The quality pass (restack.py, which then searches the session) in the
    background at low priority, so the run ends as soon as its frames are in
    and the telescope goes on to the next step. 2 November 2026: the
    person had said many times that processing goes on in the background
    while the scope does the next job; the pass and the search still held
    it after every run. Its lines go to the session's restack.log."""
    folder = Path(folder)
    lowly = {"creationflags": subprocess.BELOW_NORMAL_PRIORITY_CLASS} if os.name == "nt" else \
        {"preexec_fn": lambda: os.nice(19), "start_new_session": True}
    try:
        with open(folder / "restack.log", "w", encoding="utf-8") as log:
            start([sys.executable, str(ROOT / "restack.py"), str(folder)], cwd=ROOT, stdout=log,
                  stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **lowly)
        say(f"The quality pass and the search go on in the background ({folder / 'restack.log'}); "
            "the telescope is free.")
    except OSError as problem:
        say(f"  (the quality pass would not start in the background: {problem}; restack.py {folder} later)")


LIVE_MINUTES = 120  # how long the live view carries on after cloud has stopped a run


def watch_on():
    """Leave the live view running after cloud has stopped the run, so the
    page shows the sky as it is and not the last spoiled frame. It uses the
    camera only, ends by itself, and gives way to the next run."""
    command = [sys.executable, str(ROOT / "liveview.py"), "--after-run", "--exposure", "5",
               "--minutes", str(LIVE_MINUTES)]
    try:
        subprocess.Popen(command, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=not host.WINDOWS, **host.QUIET)
        print(f"Live view left running for up to {LIVE_MINUTES} minutes: the page shows the sky now.",
              flush=True)
    except OSError as problem:
        print(f"  (the live view would not start: {problem})", flush=True)


DAWN_SUN = -15.0    # degrees: the Sun higher than this ends a --through-cloud run
LIMIT_MARGIN = 0.25  # hours inside the mount's hour-angle limit at which it ends
NIGHT_CHECK = 300   # seconds between checks of the Sun and the target


def night_over(name, site, when=None):
    """Why a --through-cloud run must end now, or None: the Sun nearly up,
    or the target too far past the meridian for the mount to follow."""
    import mount
    from astropy.coordinates import AltAz, get_sun
    from astropy.time import Time
    when = when or Time.now()
    sun = get_sun(when).transform_to(AltAz(obstime=when, location=mount.location(site))).alt.deg
    if sun > DAWN_SUN:
        return f"the Sun is {sun:.0f}° up"
    try:
        hour_angle, _, _ = mount.where(mount.find_target(name), site, when)
    except interface.Refusal:
        return None                      # not a catalogue name: only dawn ends it
    if hour_angle / 15 > mount.MAX_HOUR_ANGLE - LIMIT_MARGIN:
        return f"{name} is {hour_angle / 15:.1f} h past the meridian, near the mount's limit"
    return None


DITHER = 1.5        # arcminutes a dither aims off the target: tens of pixels, so the
                    # camera's pattern lands on other stars, small enough to keep the framing


def dither_offset(rng, size=DITHER):
    """Arcminutes east and north to aim off the target: a random direction,
    between half and all of `size` away, so no two dithers sit together."""
    angle = rng.uniform(0, 2 * math.pi)
    reach = rng.uniform(size / 2, size)
    return reach * math.cos(angle), reach * math.sin(angle)


SKY_LIT = 1.3       # the sky this much brighter than in the kept frames: cloud lit by the town, or a light
ALL_GONE = 0.05     # stars below this share of their kept brightness: gone, not dimmed
PAUSED_NOTE = 900   # seconds between reminders that a --through-cloud run is still paused


def retakes(log, asked):
    """Frames to take over the `asked` count, one for each frame rejected,
    so a run ends with as many good frames as it can (the person asked for
    this on 18 October 2026, rather than making do with fewer). At most a
    quarter more, and none once RETAKE_GIVE_UP frames in a row have been
    rejected: that is cloud, not bad luck."""
    measured = judged(log)
    latest = measured[-RETAKE_GIVE_UP:]
    if len(latest) == RETAKE_GIVE_UP and not any(f["accepted"] for f in latest):
        return 0
    lost = sum(1 for f in measured if not f["accepted"])
    return min(lost, max(2, asked // 4))


def stop_for(index, frames, log, elapsed_s, minutes=None, cloud_stop=CLOUD_STOP):
    """Why a run takes no more frames after `index` of them, or None to take
    another: "time", its minutes are up, however many frames were lost on
    the way (1 November 2026: lost frames stretched a 75-minute patrol
    towards three hours and the plan's next targets); "frames", its frames
    and their retakes are in; "cloud", with no fixed number, the last
    `cloud_stop` measured frames were all rejected. The run's loop and
    nightreplay.py both ask this."""
    if minutes and elapsed_s >= 60 * minutes:
        return "time"
    if frames:
        return None if index < frames + retakes(log, frames) else "frames"
    latest = judged(log)[-cloud_stop:]
    if len(latest) == cloud_stop and not any(f["accepted"] for f in latest):
        return "cloud"
    return None


def judged(log):
    """The frames that were measured. A frame the live stack had no time for
    is logged with no figures and no verdict: it says nothing about cloud,
    and counting it as rejected would stop a clear night's run whenever the
    laptop fell behind."""
    return [f for f in log if f.get("flux") is not None]


def what_dimmed(log, last=CLOUD_STOP):
    """What the last rejected frames say about why, against the frames kept:
    the stars' brightness and the sky's, in words, with what to look at.
    The frames cannot tell high haze from dew on the mirrors (both dim the
    stars and leave the sky no brighter); the person outside can, by
    looking up. On 15 October 2026 it was haze, not dew."""
    log = judged(log)
    kept = [f for f in log if f["accepted"]]
    recent = log[-last:]
    if len(kept) < 3 or not recent:
        return "cloud?"
    stars = float(np.median([f["flux"] for f in recent])) / max(float(np.median([f["flux"] for f in kept])), 1e-6)
    sky = float(np.median([f["background"] for f in recent])) / max(float(np.median([f["background"] for f in kept])), 1e-6)
    levels = f"stars at {100 * stars:.0f}% of their kept brightness, sky at {100 * sky:.0f}%"
    if sky > SKY_LIT:
        return f"{levels}: cloud lit by the town, or a light shining in"
    if stars < ALL_GONE:
        return f"{levels}: thick cloud, or something in front of the telescope"
    return (f"{levels}: haze or thin cloud, or dew on the mirrors. Look up: if the sky is clear, "
            "look down the tube for dew")


def capture_rule(args):
    """--accepted's rule (goals.capture_rule's shape): accepted frames
    wanted, the time cap (--minutes) and the frame cap (--most)."""
    import goals
    most = getattr(args, "most", None) or \
        args.accepted + max(2, math.ceil(goals.REJECT_ALLOWANCE * args.accepted))
    return {"accepted": args.accepted, "cap_minutes": args.minutes, "most_frames": most}


def goal_stop(log, taken, elapsed_s, rule):
    """Why a run given a goal (goals.capture_rule's rule) stops now, or None
    to go on: the frame log as the run keeps it. shoot.py and nightreplay.py
    both stop by this.

    A frame the live stack had no time to measure is counted with the
    accepted only at the share of measured frames that were accepted, so
    reaching the goal is not taken on trust. Frames lost to cloud are told
    apart from other rejections (outcome.cause): cloud costs time, the
    others cost frames."""
    import goals
    import outcome
    measured = judged(log)
    kept = sum(1 for f in measured if f["accepted"])
    unmeasured = len(log) - len(measured)
    rate = kept / len(measured) if measured else 1.0
    accepted = kept + int(unmeasured * rate)
    cloud = sum(1 for f in measured if not f["accepted"] and outcome.cause(f) == "cloud")
    in_row = 0
    for f in reversed(measured):
        if f["accepted"]:
            break
        if outcome.cause(f) != "cloud":
            in_row += 1
    go, why = goals.keep_capturing(accepted, taken, in_row, elapsed_s, rule, cloud)
    return None if go else why


def goal_reached(session, taken, elapsed_s, args, keep=True):
    """(go on?, why it stops) for a run given --accepted (Phase 2 of
    docs/observing-plan-spec.md): it keeps going until that many frames are
    accepted. A camera stall costs time, which runs to --minutes; a rejected
    frame costs a frame, which runs to --most. A frame set aside while the
    live stack was behind counts with the accepted: the quality pass judges
    it, and the stacked share is measured over both. When it stops, why is
    kept in capture.json beside the frames."""
    rule = capture_rule(args)
    log = session.log
    why = goal_stop(log, taken, elapsed_s, rule)
    go = why is None
    if not go and keep:
        import outcome
        measured = judged(log)
        rejected = [f for f in measured if not f["accepted"]]
        # Kept apart as the run knew them: the quality pass (restack.json)
        # says how many were stacked, which is what the goal is judged on.
        records.write(session.folder / "capture.json",
                      {"rule": rule, "stopped_by": why, "taken": taken,
                       "accepted": sum(1 for f in measured if f["accepted"]),
                       "unmeasured": len(log) - len(measured),
                       "rejected": len(rejected),
                       "cloud": sum(1 for f in rejected if outcome.cause(f) == "cloud"),
                       "seconds": round(elapsed_s, 1)}, indent=None)
    return go, why


def frames_asked(frames, minutes):
    """The frames a run is asked for: as given; with only --minutes, as many
    as the minutes allow (0: until the time is up or cloud stops it); else
    60. On 4 November 2026 "./shoot.py NGC 3310 --minutes 90" took the
    default 60 frames and their retakes, and would have stopped after half
    an hour had the plan started it on time (found by nightreplay.py)."""
    if frames is not None:
        return frames
    return 0 if minutes else 60


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("name", help="what it is a picture of; a catalogue name allows re-centring")
    ap.add_argument("--frames", type=int, default=None,
                    help="how many to take; 0 carries on until cloud stops it (default: 60, or with --minutes "
                         "and no --frames, as many as the minutes allow)")
    ap.add_argument("--minutes", type=float,
                    help="stop after this many minutes of imaging, however many frames were lost on the way")
    ap.add_argument("--accepted", type=int, metavar="N",
                    help="keep going until N frames are accepted: camera stalls run to --minutes (needed), "
                         "rejected frames to --most; the two counted apart (goals.py)")
    ap.add_argument("--most", type=int, metavar="N",
                    help="with --accepted: the most frames to take (default: half as many again, at least 2 more)")
    ap.add_argument("--exposure", default="2",
                    help="seconds per frame, or 'auto' to test what the tracking allows")
    ap.add_argument("--gain", type=int, default=1500)
    ap.add_argument("--recentre", type=int, metavar="N", default=0,
                    help="also re-centre every N frames, whatever the drift")
    ap.add_argument("--no-recentre", action="store_true", help="never move the mount")
    ap.add_argument("--dither", type=int, metavar="N", default=0,
                    help="every N frames, re-centre a little off the target (about 1.5'), so the camera's "
                         "own pattern falls on different stars and averages away")
    ap.add_argument("--dither-first", action="store_true",
                    help="re-centre a little off the target before the first frame, so a second look at a "
                         "candidate puts it on different pixels from the first")
    ap.add_argument("--through-cloud", action="store_true",
                    help="with --frames 0: cloud pauses the run instead of ending it; it re-centres when "
                         "the stars come back, and ends at dawn or when the target nears the mount's limit")
    ap.add_argument("--assist", action="store_true",
                    help="trim the Dec motor's creep from the drift the frames show")
    ap.add_argument("--hold", type=float, metavar="PX",
                    help="for transits: keep the target within PX pixels of where the first frame had it, "
                         "learning first how small moves shift the frames; no dithering")
    ap.add_argument("--no-save", action="store_true", help="do not keep the raw frames")
    ap.add_argument("--no-restack", action="store_true", help="skip the final quality pass")
    ap.add_argument("--no-live", action="store_true",
                    help="when cloud stops the run, do not leave the live view running")
    ap.add_argument("--profile", action="store_true", help="report where the time went")
    ap.add_argument("--dry-run", action="store_true",
                    help="say what would be done; no camera, no mount")
    ap.add_argument("--json", action="store_true", help="answer in JSON once the run is over")
    args = ap.parse_args()
    if args.accepted is not None:
        if args.accepted < 1 or not args.minutes:
            ap.error("--accepted needs a count of 1 or more and --minutes, the time it may run to")
        if args.frames is not None:
            ap.error("--accepted takes the place of --frames")
        # What the page shows as asked; the run ends by goal_reached().
        args.frames = capture_rule(args)["most_frames"]
    args.frames = frames_asked(args.frames, args.minutes)
    if args.dither and args.no_recentre:
        ap.error("--dither moves the mount between frames; it cannot go with --no-recentre")
    if args.hold and (args.dither or args.dither_first or args.no_recentre):
        ap.error("--hold keeps the stars on the same pixels: not with --dither or --no-recentre")
    work = (lambda: plan(args)) if args.dry_run else (lambda: run(args))
    return interface.main("shoot.dry_run" if args.dry_run else "shoot", work, args.json)


def plan(args):
    """What a run would do, checked against the mount's limits, with nothing
    touched."""
    import config
    import mount
    out = {"target": args.name, "frames": args.frames, "exposure": args.exposure,
           "gain": args.gain, "keeps_raw_frames": not args.no_save,
           "quality_pass": not (args.no_save or args.no_restack), "would_move": False,
           "dither_every": getattr(args, "dither", 0) or None,
           # The hold moves the mount in small steps all through the run.
           "hold_px": getattr(args, "hold", None)}
    if not args.no_recentre:
        site = (config.load() if config.FILE.exists() else config.example())["site"]
        try:
            goto = mount.plan_goto(args.name, site)
            goto.pop("side_note", None)
            out.update(would_move=True, goto=goto)
        except interface.Refusal as refusal:
            # shoot.py carries on without the mount when it cannot be moved.
            out["goto"] = {"would_move": False, "error": refusal.as_error()}
    for key, value in out.items():
        print(f"{key}: {value}")
    return out


RUN_LOCK = config.DATA / "cache" / "imaging.lock"
# A run stops itself with this much disk left: the stack, the quality pass
# and every other program still need room. 24 October 2026: a run of the
# Moon at a frame a second kept 33 MB a frame and left 5 GB in 25 minutes.
MIN_FREE = 3e9


def disk_full(folder, least=None):
    """True when the disk holding `folder` has less than MIN_FREE free."""
    import shutil
    path = Path(folder)
    while not path.exists() and path != path.parent:
        path = path.parent
    return shutil.disk_usage(path).free < (MIN_FREE if least is None else least)


def warm(cam, say=None):
    """The end of a run, however it ended: a cooled camera's sensor brought up
    gently before its cooler goes off (altair.py's warm_up, which is bounded
    in time and turns the cooler off whatever happens); nothing for any other
    camera. Never raises: a run that stopped on an error keeps that error."""
    say = say or (lambda line: print(f"  {line}", flush=True))
    warm_up = getattr(cam, "warm_up", None)
    if not warm_up:
        return
    try:
        warm_up(say=say)
    except Exception as problem:
        say(f"camera: the warm-up failed ({problem}); closing the camera turns the cooler off")


def hold_the_rig(name, path=None):
    """The mount and camera for this run alone: an open file locked for as
    long as the run lives (the lock goes with the process, however it ends).
    A second run refuses to start rather than share them: on 18 October 2026
    a patrol's second look at M33 started while M34 was imaging, and its
    GoTo swung the tube over the pole in the middle of M34's frames."""
    path = Path(path or RUN_LOCK)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+", encoding="utf-8")
    try:
        if os.name == "nt":
            import msvcrt
            # Windows locks are enforced on reading as well, so the byte
            # locked lies well past the holder's name, which another run
            # must still be able to read to say who has the rig.
            handle.seek(1 << 20)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        try:
            handle.seek(0)
            holder = handle.read().strip() or "another run"
        except OSError:
            holder = "another run"
        handle.close()
        raise interface.Refusal("INVALID_REQUEST", f"Another imaging run has the mount and camera ({holder}); "
                                "it must finish or be stopped (./ty run stop) first.")
    handle.seek(0)
    handle.truncate()
    handle.write(f"{name}, process {os.getpid()}, since {time.strftime('%H:%M:%S')}")
    handle.flush()
    return handle


def run(args):
    rig = hold_the_rig(args.name)     # kept open, so locked, for the whole run
    try:
        return held(args)
    finally:
        # Let go as the run ends, however it ends: on 1 November 2026 a run
        # stopped by a jammed camera kept the lock while anything still held
        # its error, and the next run in the same process was refused.
        rig.close()


def held(args):
    moving = not args.no_recentre
    if moving:
        moving = recentre(args.name)
    holding = None
    if moving and getattr(args, "hold", None):
        try:
            holding = Hold(args.hold, hold_mover(args.name))
            print(f"  hold: keeping {args.name} within {args.hold:g} px; learning from the first frames", flush=True)
        except (OSError, SystemExit, interface.Refusal) as problem:
            print(f"  hold: mount not available ({problem}); imaging without it", flush=True)
    if args.exposure == "auto":
        exposure = pick_exposure(args.gain, lambda s: stacking.Calibration(s, args.gain))
    else:
        exposure = float(args.exposure)

    session = Session(args.name, exposure, args.gain, save=not args.no_save, frames=args.frames or None)
    # "Imaging M31-P6: 4 of 19 frames of 16 s" on the status page for as long
    # as the run lives, and a camera that has stopped sending said plainly.
    with activity.imaging(session.name, args.frames or None, exposure, session.folder) as tracker:
        return image(args, session, exposure, moving, holding, tracker)


def image(args, session, exposure, moving, holding, tracker):
    """The run's frames, from the first to the quality pass."""
    workers = max(1, stacking.cores() - 1)   # one core stays free for the camera and the stack
    print(f"{session.name}: {args.frames or 'an open-ended run of'} frames of {exposure:g} s at gain {args.gain}; "
          f"calibration: {session.calibration.describe()}; {workers} workers", flush=True)
    index, since_centre, since_dither, started = 0, 0, 0, time.monotonic()
    jams = 0          # times in a row the camera was opened again without a frame
    if getattr(args, "dither_first", False):
        args.dither = args.dither or 10 ** 9      # a dither before the first frame, then none unless asked
        since_dither = args.dither
    rng = random.Random()
    ORDERS.unlink(missing_ok=True)   # an order left for an earlier run is not for this one
    told = {"stop": False, "recentre": False, "cloud": False, "cloudy": False}
    checked = [0.0]   # when the Sun and the target were last checked
    paused = [0.0]    # when the run last said it was paused for cloud
    site = None
    if args.through_cloud:
        site = (config.load() if config.FILE.exists() else config.example())["site"]
    shown = 0.0   # when the newest raw frame was last put on the web page
    waiting = deque()   # (future, time taken) for frames being processed, oldest first

    def more():
        """Whether to take another frame. With no fixed number, carry on
        until a run of frames in a row has been lost, which means cloud (or
        dawn, or dew) has ended the session."""
        if told["stop"]:
            return False
        cloud_stop = live.get("shoot.cloud_stop", CLOUD_STOP)
        stop = stop_for(index, args.frames, session.log, time.monotonic() - started,
                        getattr(args, "minutes", None), cloud_stop)
        if stop == "time":
            if not told.get("timed"):
                told["timed"] = True
                print(f"  {args.minutes:g} minutes taken: finishing", flush=True)
            return False
        if getattr(args, "accepted", None):
            go, why = goal_reached(session, index, time.monotonic() - started, args)
            if not go:
                print(f"  {why}: finishing", flush=True)
            return go
        if args.frames:
            return stop is None
        if args.through_cloud and time.monotonic() - checked[0] >= NIGHT_CHECK:
            checked[0] = time.monotonic()
            why = night_over(args.name, site)
            if why:
                print(f"  {why}; stopping", flush=True)
                return False
        if stop == "cloud":
            if not args.through_cloud:
                print(f"  the last {cloud_stop} frames were all rejected ({what_dimmed(session.log)}); stopping",
                      flush=True)
                told["cloud"] = True
                return False
            if not told["cloudy"]:
                print(f"  the last {cloud_stop} frames were all rejected ({what_dimmed(session.log)}); "
                      "carrying on until it clears", flush=True)
                told["cloudy"], paused[0] = True, time.monotonic()
            elif time.monotonic() - paused[0] >= PAUSED_NOTE:
                # A pause nobody hears about looks like a run that is working.
                kept = sum(f["accepted"] for f in session.log)
                print(f"  still paused, {kept} frames kept so far ({what_dimmed(session.log)})", flush=True)
                paused[0] = time.monotonic()
        elif told["cloudy"] and session.log and session.log[-1]["accepted"]:
            # The mount kept tracking, but drift went unmeasured: centre again.
            print("  stars again; re-centring", flush=True)
            told["cloudy"], told["recentre"] = False, True
        return True

    asked_more = {}

    def go_on():
        """more(), asked once a frame: the camera block asks it before it
        pauses (so a run whose last frame falls on a re-centre or a dither
        ends warmed, not paused), and the loops ask it again for the same
        frame without saying anything twice."""
        key = (index, told["stop"])
        if asked_more.get("key") != key:
            asked_more.update(key=key, answer=more())
        return asked_more["answer"]

    def collect(everything=False):
        """Take finished frames into the stack, in the order they were taken.
        With `everything`, wait for all of them."""
        while waiting and (everything or waiting[0][0].done()
                           or session.reference is None):
            future, taken = waiting.popleft()
            print(session.absorb(future.result(), taken), flush=True)

    with stacking.worker_pool(workers) as pool:
        session.drawer = pool       # the page's picture is drawn by these workers, never a new process
        while go_on():
            tracker.pause()      # re-centring or catching up is not the camera keeping it waiting
            due = (args.recentre and since_centre >= args.recentre) or told["recentre"]
            if moving and args.dither and since_dither >= args.dither:
                # A dither centres the target again too, a little off.
                told["recentre"] = False
                collect(everything=True)
                aim = dither_offset(rng)
                print(f"  dithering: re-centring {aim[0]:+.1f}' east, {aim[1]:+.1f}' north of {args.name}", flush=True)
                recentre(args.name, aim)
                session.drift, session.origin, since_centre, since_dither = 0.0, None, 0, 0
                session.track.clear()
            elif moving and (session.drift > DRIFT_LIMIT or due):
                told["recentre"] = False
                collect(everything=True)
                print(f"  drifted {session.drift * 100:.0f}% of the frame; re-centring", flush=True)
                recentre(args.name)
                session.drift, session.origin, since_centre = 0.0, None, 0
                session.track.clear()   # the slew, not drift, moved the next frames
                if holding and holding.state != "off":
                    holding.reset()     # a GoTo may have swung the tube over the pole
                    holding.mark = len(session.shifts)
            elif args.assist and moving and len(session.track) >= live.get("shoot.assist_every", ASSIST_EVERY):
                collect(everything=True)
                if not assist(session):
                    args.assist = False
            elif holding and moving and holding.due(session.shifts):
                collect(everything=True)
                try:
                    holding.step(session.shifts)
                except (OSError, SystemExit) as problem:
                    print(f"  hold: the mount would not move ({problem}); the hold is off", flush=True)
                    holding.state = "off"
            tracker.waiting()
            jammed = None
            # The filter in the light path, when the train has the wheel in it:
            # each frame says the position the wheel confirmed (FILTPOS, FILTER).
            # Asked here, as the wheel moves only when told to (sxwheel.py
            # move), never during a run. A train with no wheel (the 183C's) is
            # never asked, and its frames carry no FILTER, as before.
            in_path = (sxwheel.confirmed(say=lambda line: print(f"  {line}", flush=True))
                       if config.hardware()["train"].get("filterwheel") else None)
            with Camera(gain=args.gain) as cam:
                # True only when this block ends to be opened again at once: a
                # re-centre, a dither, a trim of the creep, a hold, or a jam that
                # still has reopens left. Every other way out (the run's end, a
                # stop, the disk, an error, Ctrl-C) warms a cooled sensor first.
                reopening = False
                try:
                    # A cooled camera keeps no frame until its sensor is within
                    # 1 °C of its target (altair.py); every other camera, at once.
                    settle = getattr(cam, "settle", None)
                    if settle:
                        settle(say=lambda line: print(f"  {line}", flush=True))
                    while go_on():
                        try:
                            mosaic, header = cam.frame(exposure)
                        except CameraError as problem:
                            jammed = problem          # the camera is closed on the way out of this block
                            reopening = jams < JAM_REOPENS
                            break
                        sxwheel.cards(header, in_path)
                        jams = 0
                        index += 1
                        tracker.took(index)
                        since_centre += 1
                        since_dither += 1
                        if time.monotonic() - shown >= PREVIEW_EVERY:
                            snap.publish(mosaic, kind="newest frame", quick=True, mono=is_mono(header),
                                         detail=f"frame {index} · {exposure:g} s")
                            shown = time.monotonic()
                        collect()
                        if len(waiting) >= BACKLOG:
                            # Capture never waits for processing: this frame's raw
                            # file is kept and the quality pass will use it.
                            cards = {k: header[k] for k in stacking.KEPT if k in header}
                            if session.save:
                                pool.submit(stacking.save_only, mosaic, cards, str(session.folder), index)
                            print(session.defer(index), flush=True)
                        else:
                            # Until the first good frame has become the reference
                            # the others cannot be lined up, so collect() waits for it.
                            waiting.append((pool.submit(stacking.live_frame,
                                                        *session.job(index, mosaic, header)), time.time()))
                        asked = order(args.name)
                        if asked:
                            print(f"  told to {asked}", flush=True)
                        if disk_full(session.folder):
                            print(f"  stopping: under {MIN_FREE / 1e9:.0f} GB left on the disk", flush=True)
                            asked = "stop"
                        if asked == "stop":
                            told["stop"] = True
                            break
                        if asked in ("assist-on", "assist-off"):
                            args.assist = asked == "assist-on"
                        told["recentre"] = told["recentre"] or asked == "recentre"
                        due = (args.recentre and since_centre >= args.recentre) or told["recentre"]
                        reopening = bool(
                            (moving and (session.drift > DRIFT_LIMIT or due))
                            or (holding and moving and holding.due(session.shifts))
                            or (moving and args.dither and since_dither >= args.dither)
                            or (args.assist and moving
                                and len(session.track) >= live.get("shoot.assist_every", ASSIST_EVERY)))
                        if reopening:
                            reopening = go_on()      # the last frame on a pause is the run's end
                            break
                finally:
                    if not reopening:
                        warm(cam)
            if jammed is not None:
                # A jammed camera is opened again and the run goes on in the same
                # session: on 1 November 2026 a jam ended a transit run, and its
                # restart began a new session from frame 0 ("i dont think we should
                # restart at square 1 and the code should handle it more gracefully").
                jams += 1
                if jams > JAM_REOPENS:
                    raise jammed
                print(f"  the camera stopped sending frames ({jammed}); opening it again in {JAM_WAIT_S} s, "
                      f"the run goes on ({jams} of {JAM_REOPENS})", flush=True)
                tracker.pause()
                time.sleep(JAM_WAIT_S)
        collect(everything=True)

    session.finish()
    used = len(session.accepted)
    if not used:
        raise interface.Refusal("NO_USABLE_FRAMES", "No usable frames.")
    minutes = (time.monotonic() - started) / 60
    print(f"\n{index} captured, {used} accepted, {index - used} rejected "
          f"({100 * used / index:.0f}% kept) in {minutes:.0f} min")
    print(f"Total accepted exposure: {used * exposure:.0f} s")
    short = None if config.DEMO else short_changed([f.get("taken") for f in session.log], exposure)
    if short:
        print(f"  But a frame arrived every {short:.1f} s, less than the {exposure:g} s each was meant to "
              f"take: the camera is exposing for less than it is asked, and the true total is nearer "
              f"{used * short:.0f} s at most. See the README's current status.")
    if args.profile:
        print("Where the processing time went (summed over the workers):")
        print(session.timings.report(time.monotonic() - started))
    if told["cloud"] and not args.no_live and not config.DEMO:
        watch_on()
    if session.save and not args.no_restack:
        if os.environ.get("TY_PATROL") or args.profile or config.DEMO:
            # A patrol holding the telescope for its search (--wait) needs the
            # picture before it searches; a profile wants the timings here;
            # the demo has no telescope to free, and ends on its picture.
            print("\nQuality pass over the raw frames:")
            restack.run(session.folder, profile=args.profile)
            import patrol
            patrol.search_later(session.folder)
        else:
            restack_later(session.folder)
    print(f"Session folder: {session.folder}")
    final = session.folder / "final.jpg"
    return {"target": session.name, "folder": str(session.folder), "exposure_s": exposure,
            "captured": index, "accepted": used, "rejected": index - used,
            "integration_s": used * exposure, "minutes": round(minutes, 1),
            "picture": str(final if final.exists() else session.folder / "live.fits")}


if __name__ == "__main__":
    main()
