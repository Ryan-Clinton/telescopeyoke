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
import random
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import config

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
from camera import Camera, stretch

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
CLOUD_STOP = 20     # with --frames 0, stop after this many rejected frames in a row
PREVIEW_EVERY = 3.0  # seconds between updates of the picture on the web page
FINISH_FROM = 5      # accepted frames before the live picture is finished like the final one
BACKLOG = 8         # frames allowed to wait for the live stack before it skips some


class Session:
    """One run on one target: the folder, the running stack and the log."""

    def __init__(self, name, exposure, gain, save=True, frames=None, preview_every=PREVIEW_EVERY):
        self.name = stacking.folder_name(name)
        self.folder = config.DATA / "frames" / self.name / f"{datetime.now():%Y%m%d-%H%M%S}"
        self.folder.mkdir(parents=True, exist_ok=True)
        # What was asked for, so the web page can say "frame 31 of 200".
        records.write(self.folder / "session.json",
                      {"name": self.name, "frames": frames, "exposure": exposure, "gain": gain}, indent=None)
        self.exposure, self.gain, self.save = exposure, gain, save
        self.calibration = stacking.Calibration(exposure, gain)
        self.reference, self.stack = None, None
        self.accepted, self.log = [], []
        self.drift = 0.0   # how far the newest frame was from the first, in frame heights
        self.track = []    # (time, x shift, y shift) of accepted frames since the last trim
        self.timings = stacking.Timings()
        self.preview_every, self.published = preview_every, 0.0

    def job(self, index, mosaic, header):
        """Arguments for stacking.live_frame for this frame, as things stand."""
        cards = {k: header[k] for k in ("EXPTIME", "GAIN", "DATE-OBS", "BAYERPAT") if k in header}
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
                self.drift = float(np.hypot(*entry["shift"])) / frame.shape[0]
                self.track.append((taken or time.time(), *entry["shift"]))
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
        entry = {"index": index, "accepted": False, "fwhm": None, "stars": 0,
                 "reason": "live stack behind; kept for the quality pass"}
        self.log.append(entry)
        stacking.append_log(self.folder, entry)
        return f"{index:03d} LATER   {entry['reason']}"

    def publish(self, force=False):
        """Update the picture on the web page, at most every few seconds: when
        frames arrive quickly the page does not need every one. It is drawn
        in the background from a copy of the stack, so the camera never waits
        for it: finishing the picture takes half a minute, and on 18 October
        2026 every panel lost that much after its fifth frame. While one is
        being drawn the next is skipped; the last one (`force`) waits for it
        and is drawn in full."""
        drawing = getattr(self, "drawing", None)
        if drawing is not None and drawing.is_alive():
            if not force:
                return
            drawing.join()
        if not force and time.monotonic() - self.published < self.preview_every:
            return
        stacked, count = self.stack.result(), len(self.accepted)
        self.published = time.monotonic()
        if force:
            self.draw(stacked, count)
        else:
            self.drawing = threading.Thread(target=self.draw, args=(stacked, count), daemon=True)
            self.drawing.start()

    def draw(self, stacked, count):
        with self.timings.phase("update the web page"):
            image = Image.fromarray(self.picture(stacked, count))
            WEB.mkdir(exist_ok=True)
            # The stack has its own picture; web/latest.jpg stays the newest
            # single frame, so the page shows both.
            image.resize((1600, round(1600 * image.height / image.width)), Image.LANCZOS) \
                 .save(WEB / "stack.part.jpg", quality=88)
            host.replace_preview(WEB / "stack.part.jpg", WEB / "stack.jpg")
            image.save(WEB / f"{self.name}.jpg", quality=92)
            seconds = self.exposure * count
            snap.label(f"live stack of {self.name}", f"{count} accepted frames · "
                       f"{seconds:.0f} s integration", WEB, name="stack")

    def picture(self, stacked=None, count=None):
        """The stack so far as a picture to show. With enough frames in it,
        it is finished the way the final picture will be (the sky's glow and
        slope taken out, the colours balanced), so that what is watched looks
        like what will be kept; before that, or if that fails, plainly
        brightened. Finishing takes a few seconds, so the page is then
        updated less often: no more than a fifth of the time goes on it."""
        stacked = self.stack.result() if stacked is None else stacked
        if (len(self.accepted) if count is None else count) >= FINISH_FROM:
            began = time.monotonic()
            try:
                shown = process.process(stacked, background=process.sky_for(self.name))
                self.preview_every = max(self.preview_every, 5 * (time.monotonic() - began))
                return shown
            except Exception as problem:     # never lose a run to its preview
                print(f"  (live picture left plain: {problem})", flush=True)
        return stretch(stacked)

    def finish(self):
        records.write((self.folder / "frames.json"), self.log)
        if not self.accepted:
            return
        self.publish(force=True)
        stacking.write_stack(self.folder / "live.fits", self.stack.result(),
                             {"OBJECT": self.name, "NFRAMES": len(self.accepted),
                              "EXPTIME": self.exposure * len(self.accepted), "GAIN": self.gain})


def tell(order):
    """Leave an order for the run that is going."""
    if order not in KNOWN_ORDERS:
        raise interface.Refusal("INVALID_REQUEST", f"Unknown order '{order}'. Known: "
                                + ", ".join(KNOWN_ORDERS))
    ORDERS.parent.mkdir(exist_ok=True)
    ORDERS.write_text(order, encoding="utf-8")
    return {"order": order, "note": "The run acts on it after its next frame."}


def order():
    """The order left for this run, if any; it is taken, so it acts once."""
    if not ORDERS.exists():
        return None
    found = ORDERS.read_text(encoding="utf-8").strip()
    ORDERS.unlink()
    return found if found in KNOWN_ORDERS else None


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
            mosaic, _ = cam.frame(seconds)
            lum = stacking.prepare(mosaic, calibration_for(seconds)).sum(axis=2)
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


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("name", help="what it is a picture of; a catalogue name allows re-centring")
    ap.add_argument("--frames", type=int, default=60,
                    help="how many to take; 0 carries on until cloud stops it")
    ap.add_argument("--exposure", default="2",
                    help="seconds per frame, or 'auto' to test what the tracking allows")
    ap.add_argument("--gain", type=int, default=1500)
    ap.add_argument("--recentre", type=int, metavar="N", default=0,
                    help="also re-centre every N frames, whatever the drift")
    ap.add_argument("--no-recentre", action="store_true", help="never move the mount")
    ap.add_argument("--dither", type=int, metavar="N", default=0,
                    help="every N frames, re-centre a little off the target (about 1.5'), so the camera's "
                         "own pattern falls on different stars and averages away")
    ap.add_argument("--through-cloud", action="store_true",
                    help="with --frames 0: cloud pauses the run instead of ending it; it re-centres when "
                         "the stars come back, and ends at dawn or when the target nears the mount's limit")
    ap.add_argument("--assist", action="store_true",
                    help="trim the Dec motor's creep from the drift the frames show")
    ap.add_argument("--no-save", action="store_true", help="do not keep the raw frames")
    ap.add_argument("--no-restack", action="store_true", help="skip the final quality pass")
    ap.add_argument("--no-live", action="store_true",
                    help="when cloud stops the run, do not leave the live view running")
    ap.add_argument("--profile", action="store_true", help="report where the time went")
    ap.add_argument("--dry-run", action="store_true",
                    help="say what would be done; no camera, no mount")
    ap.add_argument("--json", action="store_true", help="answer in JSON once the run is over")
    args = ap.parse_args()
    if args.dither and args.no_recentre:
        ap.error("--dither moves the mount between frames; it cannot go with --no-recentre")
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
           "dither_every": getattr(args, "dither", 0) or None}
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


def run(args):
    moving = not args.no_recentre
    if moving:
        moving = recentre(args.name)
    if args.exposure == "auto":
        exposure = pick_exposure(args.gain, lambda s: stacking.Calibration(s, args.gain))
    else:
        exposure = float(args.exposure)

    session = Session(args.name, exposure, args.gain, save=not args.no_save, frames=args.frames or None)
    workers = max(1, stacking.cores() - 1)   # one core stays free for the camera and the stack
    print(f"{session.name}: {args.frames or 'an open-ended run of'} frames of {exposure:g} s at gain {args.gain}; "
          f"calibration: {session.calibration.describe()}; {workers} workers", flush=True)
    index, since_centre, since_dither, started = 0, 0, 0, time.monotonic()
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
        if args.frames:
            return index < args.frames
        if args.through_cloud and time.monotonic() - checked[0] >= NIGHT_CHECK:
            checked[0] = time.monotonic()
            why = night_over(args.name, site)
            if why:
                print(f"  {why}; stopping", flush=True)
                return False
        latest = judged(session.log)[-CLOUD_STOP:]
        if len(latest) == CLOUD_STOP and not any(f["accepted"] for f in latest):
            if not args.through_cloud:
                print(f"  the last {CLOUD_STOP} frames were all rejected ({what_dimmed(session.log)}); stopping",
                      flush=True)
                told["cloud"] = True
                return False
            if not told["cloudy"]:
                print(f"  the last {CLOUD_STOP} frames were all rejected ({what_dimmed(session.log)}); "
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

    def collect(everything=False):
        """Take finished frames into the stack, in the order they were taken.
        With `everything`, wait for all of them."""
        while waiting and (everything or waiting[0][0].done()
                           or session.reference is None):
            future, taken = waiting.popleft()
            print(session.absorb(future.result(), taken), flush=True)

    with stacking.worker_pool(workers) as pool:
        while more():
            due = (args.recentre and since_centre >= args.recentre) or told["recentre"]
            if moving and args.dither and since_dither >= args.dither:
                # A dither centres the target again too, a little off.
                told["recentre"] = False
                collect(everything=True)
                aim = dither_offset(rng)
                print(f"  dithering: re-centring {aim[0]:+.1f}' east, {aim[1]:+.1f}' north of {args.name}", flush=True)
                recentre(args.name, aim)
                session.drift, since_centre, since_dither = 0.0, 0, 0
                session.track.clear()
            elif moving and (session.drift > DRIFT_LIMIT or due):
                told["recentre"] = False
                collect(everything=True)
                print(f"  drifted {session.drift * 100:.0f}% of the frame; re-centring", flush=True)
                recentre(args.name)
                session.drift, since_centre = 0.0, 0
                session.track.clear()   # the slew, not drift, moved the next frames
            elif args.assist and moving and len(session.track) >= ASSIST_EVERY:
                collect(everything=True)
                if not assist(session):
                    args.assist = False
            with Camera(gain=args.gain) as cam:
                while more():
                    mosaic, header = cam.frame(exposure)
                    index += 1
                    since_centre += 1
                    since_dither += 1
                    if time.monotonic() - shown >= PREVIEW_EVERY:
                        snap.publish(mosaic, kind="newest frame", quick=True,
                                     detail=f"frame {index} · {exposure:g} s")
                        shown = time.monotonic()
                    collect()
                    if len(waiting) >= BACKLOG:
                        # Capture never waits for processing: this frame's raw
                        # file is kept and the quality pass will use it.
                        cards = {k: header[k] for k in ("EXPTIME", "GAIN", "DATE-OBS", "BAYERPAT")
                                 if k in header}
                        if session.save:
                            pool.submit(stacking.save_only, mosaic, cards, str(session.folder), index)
                        print(session.defer(index), flush=True)
                    else:
                        # Until the first good frame has become the reference
                        # the others cannot be lined up, so collect() waits for it.
                        waiting.append((pool.submit(stacking.live_frame,
                                                    *session.job(index, mosaic, header)), time.time()))
                    asked = order()
                    if asked:
                        print(f"  told to {asked}", flush=True)
                    if asked == "stop":
                        told["stop"] = True
                        break
                    if asked in ("assist-on", "assist-off"):
                        args.assist = asked == "assist-on"
                    told["recentre"] = told["recentre"] or asked == "recentre"
                    due = (args.recentre and since_centre >= args.recentre) or told["recentre"]
                    if moving and (session.drift > DRIFT_LIMIT or due):
                        break
                    if moving and args.dither and since_dither >= args.dither:
                        break
                    if args.assist and moving and len(session.track) >= ASSIST_EVERY:
                        break
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
        print("\nQuality pass over the raw frames:")
        restack.run(session.folder, profile=args.profile)
        import patrol
        patrol.search_later(session.folder)
    print(f"Session folder: {session.folder}")
    final = session.folder / "final.jpg"
    return {"target": session.name, "folder": str(session.folder), "exposure_s": exposure,
            "captured": index, "accepted": used, "rejected": index - used,
            "integration_s": used * exposure, "minutes": round(minutes, 1),
            "picture": str(final if final.exists() else session.folder / "live.fits")}


if __name__ == "__main__":
    main()
