#!/usr/bin/env python3
"""Take a picture: many short exposures, checked, lined up and averaged.

    ./shoot.py M27                          60 frames of 2 s
    ./shoot.py M27 --frames 300 --exposure auto
    ./shoot.py M27 --no-recentre            never move the mount
    ./shoot.py M27 --assist                 also trim the Dec motor's creep as it goes

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
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

import restack
import snap
import stacking
import tracking
from camera import Camera, stretch

ROOT = Path(__file__).parent
WEB = ROOT / "web"
# Send the mount back to the target once it has drifted this far off centre,
# as a fraction of the frame's height. The drift up to then is welcome: it
# spreads the sensor's fixed pattern around, which averaging then removes.
DRIFT_LIMIT = 0.2
TRIAL_EXPOSURES = (1, 2, 3, 4)
ASSIST_EVERY = 15   # accepted frames between trims of the Dec creep
PREVIEW_EVERY = 3.0  # seconds between updates of the picture on the web page
BACKLOG = 8         # frames allowed to wait for the live stack before it skips some


class Session:
    """One run on one target: the folder, the running stack and the log."""

    def __init__(self, name, exposure, gain, save=True, frames=None, preview_every=PREVIEW_EVERY):
        self.name = name.replace(" ", "")
        self.folder = ROOT / "frames" / self.name / f"{datetime.now():%Y%m%d-%H%M%S}"
        self.folder.mkdir(parents=True, exist_ok=True)
        # What was asked for, so the web page can say "frame 31 of 200".
        (self.folder / "session.json").write_text(json.dumps(
            {"name": self.name, "frames": frames, "exposure": exposure, "gain": gain}))
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
        frames arrive quickly the page does not need every one."""
        if not force and time.monotonic() - self.published < self.preview_every:
            return
        with self.timings.phase("update the web page"):
            image = Image.fromarray(stretch(self.stack.result()))
            WEB.mkdir(exist_ok=True)
            # The stack has its own picture; web/latest.jpg stays the newest
            # single frame, so the page shows both.
            image.resize((1600, round(1600 * image.height / image.width)), Image.LANCZOS) \
                 .save(WEB / "stack.part.jpg", quality=88)
            (WEB / "stack.part.jpg").replace(WEB / "stack.jpg")
            image.save(WEB / f"{self.name}.jpg", quality=92)
            seconds = self.exposure * len(self.accepted)
            snap.label(f"live stack of {self.name}", f"{len(self.accepted)} accepted frames · "
                       f"{seconds:.0f} s integration", WEB, name="stack")
        self.published = time.monotonic()

    def finish(self):
        (self.folder / "frames.json").write_text(json.dumps(self.log, indent=1))
        if not self.accepted:
            return
        self.publish(force=True)
        stacking.write_stack(self.folder / "live.fits", self.stack.result(),
                             {"OBJECT": self.name, "NFRAMES": len(self.accepted),
                              "EXPTIME": self.exposure * len(self.accepted), "GAIN": self.gain})


def recentre(target):
    """Put the target back in the middle of the frame by plate solving.
    Returns False if the mount cannot be reached."""
    import config
    import mount
    try:
        scope = mount.Mount(watch=False)
    except (OSError, SystemExit) as problem:
        print(f"  mount not available ({problem}); carrying on without re-centring", flush=True)
        return False
    try:
        scope.goto_target(target, config.load()["site"], solve=True)
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
    cd = json.loads(mount.LAST_SOLVE.read_text()).get("cd")
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
        raise SystemExit("No stars in any trial exposure: cloud, or badly out of focus.")
    print(f"Selected exposure: {chosen} s")
    return float(chosen)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("name", help="what it is a picture of; a catalogue name allows re-centring")
    ap.add_argument("--frames", type=int, default=60)
    ap.add_argument("--exposure", default="2",
                    help="seconds per frame, or 'auto' to test what the tracking allows")
    ap.add_argument("--gain", type=int, default=1500)
    ap.add_argument("--recentre", type=int, metavar="N", default=0,
                    help="also re-centre every N frames, whatever the drift")
    ap.add_argument("--no-recentre", action="store_true", help="never move the mount")
    ap.add_argument("--assist", action="store_true",
                    help="trim the Dec motor's creep from the drift the frames show")
    ap.add_argument("--no-save", action="store_true", help="do not keep the raw frames")
    ap.add_argument("--no-restack", action="store_true", help="skip the final quality pass")
    ap.add_argument("--profile", action="store_true", help="report where the time went")
    args = ap.parse_args()

    moving = not args.no_recentre
    if moving:
        moving = recentre(args.name)
    if args.exposure == "auto":
        exposure = pick_exposure(args.gain, lambda s: stacking.Calibration(s, args.gain))
    else:
        exposure = float(args.exposure)

    session = Session(args.name, exposure, args.gain, save=not args.no_save, frames=args.frames)
    workers = max(1, stacking.cores() - 1)   # one core stays free for the camera and the stack
    print(f"{session.name}: {args.frames} frames of {exposure:g} s at gain {args.gain}; "
          f"calibration: {session.calibration.describe()}; {workers} workers", flush=True)
    index, since_centre, started = 0, 0, time.monotonic()
    shown = 0.0   # when the newest raw frame was last put on the web page
    waiting = deque()   # (future, time taken) for frames being processed, oldest first

    def collect(everything=False):
        """Take finished frames into the stack, in the order they were taken.
        With `everything`, wait for all of them."""
        while waiting and (everything or waiting[0][0].done()
                           or session.reference is None):
            future, taken = waiting.popleft()
            print(session.absorb(future.result(), taken), flush=True)

    with stacking.worker_pool(workers) as pool:
        while index < args.frames:
            due = args.recentre and since_centre >= args.recentre
            if moving and (session.drift > DRIFT_LIMIT or due):
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
                while index < args.frames:
                    mosaic, header = cam.frame(exposure)
                    index += 1
                    since_centre += 1
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
                    due = args.recentre and since_centre >= args.recentre
                    if moving and (session.drift > DRIFT_LIMIT or due):
                        break
                    if args.assist and moving and len(session.track) >= ASSIST_EVERY:
                        break
        collect(everything=True)

    session.finish()
    used = len(session.accepted)
    if not used:
        raise SystemExit("No usable frames.")
    minutes = (time.monotonic() - started) / 60
    print(f"\n{index} captured, {used} accepted, {index - used} rejected "
          f"({100 * used / index:.0f}% kept) in {minutes:.0f} min")
    print(f"Total accepted exposure: {used * exposure:.0f} s")
    if args.profile:
        print("Where the processing time went (summed over the workers):")
        print(session.timings.report(time.monotonic() - started))
    if session.save and not args.no_restack:
        print("\nQuality pass over the raw frames:")
        restack.run(session.folder, profile=args.profile)
    print(f"Session folder: {session.folder}")


if __name__ == "__main__":
    main()
