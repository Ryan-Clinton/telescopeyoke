#!/usr/bin/env python3
"""Image the Moon: one command for the whole of it.

    ./ty moon                    the full disc: centred, exposed, a video, stacked
    ./ty moon --dry-run          what it would do, and whether the Moon is up
    ./ty moon --frames 2000 --bursts 4 --keep 5 10 20 40 --colour
    ./ty moon --mineral          the detail video, then three 16-bit colour videos
                                 with the disc moved across the sensor, then the
                                 mineral Moon from them (mineral.py)

It goes to the Moon, finds the disc in the camera's own picture and centres
it from that (plate solving needs stars, and there are none beside a bright
Moon), sets the exposure from the surface's brightness, reads only the part
of the sensor round the disc (a smaller part is a faster video), then takes
the video in bursts. Between bursts it finds the disc again and moves the
mount back onto it: the Moon moves against the stars by about its own width
an hour, and the mount tracks the stars. Last, lucky.py stacks the video.

The first centring move measures how a move on the sky shows in the picture
(which way is east, how many pixels an arcminute), once for each side of the
pier; it is kept, so later nights skip it.

Focus is not done here: the motor focuser can only walk in (docs/focuser.md),
so a focus that has gone soft needs the drawtube set a touch out by hand.
`--focus-check STAR` measures it on a star field first and stops if it is
soft. 24 October 2026: the Moon centred by hand-reckoned aim-offs, a fixed
exposure and a hand-typed region; this does all three from the picture.
"""
import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

import activity
import config
import lucky
import lunar

ROOT = Path(__file__).parent
CALIBRATION = config.DATA / "cache" / "moon_calibration.json"
TEST_MOVE = 5.0          # arcminutes east, then north, for the first centring's measurement
CENTRED = 0.04           # within this share of the radius of the middle is centred
HEADROOM = 3e9           # bytes of disk always left free
FIRST_EXPOSURE = 0.005
MINERAL_LEVEL = 0.55      # the colour videos put the bright surface this far up: well clear of clipping


def free_disk(path=None):
    path = Path(path or lucky.OUT)
    while not path.exists():
        path = path.parent
    return shutil.disk_usage(path).free


def frames_that_fit(frames, frame_bytes, free):
    """`frames`, or fewer if they would not leave HEADROOM of the disk free."""
    room = max(0, int((free - HEADROOM) // max(frame_bytes, 1)))
    return min(frames, room)


def plan(args, site):
    """What `./ty moon` would do, with nothing moved."""
    import mount
    sky = lunar.state(site)
    goto = mount.plan_goto("Moon", site)
    full = config.hardware()["camera"]
    width, height = full.get("width", 5440), full.get("height", 3648)
    scale = 206.265 * full["pixel_size_um"] / config.hardware()["scope"]["focal_length_mm"]
    across = sky["size_deg"] * 3600 / scale * (1 + 2 * 0.08)
    side = int(min(max(across, 64), min(width, height)))
    frame_bytes = side * side * (1 if args.depth == 8 else 2)
    fit = frames_that_fit(args.frames, frame_bytes, free_disk())
    warnings = list(goto.get("warnings", []))
    if fit < args.frames:
        warnings.append(f"only {fit} frames of {side} px fit on the disk with {HEADROOM / 1e9:.0f} GB left free")
    return {"would_move": True, "moon": sky, "goto": {k: goto[k] for k in goto if k != "warnings"},
            "frames": fit, "region_px": side, "bursts": args.bursts, "keep": args.keep,
            "colour": args.colour, "warnings": warnings}


def load_calibration(side):
    try:
        return json.loads(CALIBRATION.read_text(encoding="utf-8"))[side]["matrix"]
    except (OSError, ValueError, KeyError):
        return None


def save_calibration(side, matrix):
    try:
        kept = json.loads(CALIBRATION.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        kept = {}
    kept[side] = {"matrix": np.asarray(matrix).tolist(), "saved": time.time()}
    CALIBRATION.parent.mkdir(parents=True, exist_ok=True)
    CALIBRATION.write_text(json.dumps(kept, indent=1), encoding="utf-8")


class Session:
    """The mount, the camera and where on the Moon the mount is aimed."""

    def __init__(self, scope, cam, site, say=print):
        self.scope, self.cam, self.site, self.say = scope, cam, site, say
        self.aim = [0.0, 0.0]
        self.log = []

    def go(self):
        self.scope.goto_target("Moon", self.site, aim_off=tuple(self.aim))

    def look(self, exposure):
        mosaic, _ = self.cam.frame(exposure)
        image = lucky.green(mosaic)
        return image, lunar.find_disc(image)

    def side(self):
        return "west" if self.scope.west() else "east"

    def calibrate(self, exposure, disc, shape):
        """Two test moves, east then north, and how far the disc went in the picture."""
        start = lunar.offset(disc, shape)
        moves = []
        for east, north in ((TEST_MOVE, 0.0), (0.0, TEST_MOVE)):
            self.aim = [self.aim[0] + east, self.aim[1] + north]
            self.go()
            _, moved = self.look(exposure)
            if moved is None:
                raise SystemExit("The Moon left the frame during the test move: centre it nearer first "
                                 "(./ty mount goto Moon --aim-off EAST NORTH).")
            now = lunar.offset(moved, shape)
            moves.append(((east, north), (now[0] - start[0], now[1] - start[1])))
            start, disc = now, moved
        matrix = lunar.calibration(moves)
        save_calibration(self.side(), matrix)
        self.say(f"measured the picture's directions: {np.round(matrix, 1).tolist()} px an arcminute")
        return matrix, disc

    def centre(self, exposure, disc, shape, matrix, tries=4):
        """Move until the disc is within CENTRED of the middle. Returns the disc."""
        for _ in range(tries):
            down, right = lunar.offset(disc, shape)
            self.log.append({"down": round(down), "right": round(right), "aim": list(self.aim)})
            if np.hypot(down, right) <= CENTRED * disc["r"]:
                return disc
            east, north = lunar.correction(matrix, down, right)
            self.aim = [self.aim[0] + east, self.aim[1] + north]
            self.go()
            _, found = self.look(exposure)
            if found is None:
                raise SystemExit("The Moon left the frame while centring: cloud, or the mount slipped.")
            disc = found
        self.say(f"centred to within {np.hypot(*lunar.offset(disc, shape)):.0f} px after {tries} moves")
        return disc


def video(s, cam, path, frames, bursts_wanted, exposure, region, depth, matrix, white, say):
    """One video in bursts, the Moon put back in the middle of the region
    between them; its notes written beside it. Returns the notes."""
    writer, bursts = None, []
    per = max(1, frames // bursts_wanted)
    try:
        for b in range(bursts_wanted):
            count = per if b < bursts_wanted - 1 else frames - per * (bursts_wanted - 1)
            with activity.doing("Taking a lucky-imaging video", f"burst {b + 1} of {bursts_wanted}"):
                writer, came = lucky.capture_into(cam, path, count, exposure, roi=region, depth=depth,
                                                  writer=writer)
            last = came.pop("last")
            bursts.append(came)
            say(f"burst {b + 1}: {came['frames']} frames, {came['fps']} a second, {came['dropped']} dropped")
            if b < bursts_wanted - 1 and last is not None:
                # The lunar hold: the disc found in the region, put back in its middle.
                found = lunar.find_disc(lucky.green(last))
                if found is None:
                    say("disc not found after the burst (cloud?): carrying on without a correction")
                    continue
                down, right = lunar.offset(found, last.shape)
                if np.hypot(down, right) > CENTRED * found["r"]:
                    east, north = lunar.correction(matrix, down, right)
                    s.aim = [s.aim[0] + east, s.aim[1] + north]
                    s.go()
                    s.log.append({"hold": b + 1, "down": round(down), "right": round(right), "aim": list(s.aim)})
    finally:
        if writer:
            writer.close()
    took = sum(b["seconds"] for b in bursts)
    notes = {"target": "Moon", "moon": lunar.state(s.site), "exposure": exposure, "gain": s.cam.gain,
             "roi": region, "depth": depth, "white_level": white if depth > 8 else 255,
             "frames": writer.count if writer else 0, "bursts": bursts,
             "fps": round(sum(b["frames"] for b in bursts) / max(took, 1e-6), 1),
             "dropped": sum(b["dropped"] for b in bursts), "centring": s.log, "aim": s.aim}
    lucky.write_notes(path, notes)
    say(f"{notes['frames']} frames at {notes['fps']} a second ({notes['dropped']} dropped): {path}")
    return notes


def dither_steps(count, room):
    """Where each colour video puts the disc across the sensor, pixels right
    of the middle: spread over 80 % of the `room` either side, so a pattern
    of the sensor's (its flat's errors, a colour gradient) lands on a
    different part of the Moon in each video and fails to repeat."""
    if count < 2 or room <= 0:
        return [0.0] * count
    return [float(v) for v in np.linspace(-0.8 * room, 0.8 * room, count)]


def colour_videos(s, cam, stamp, args, exposure, shape, matrix, white, say):
    """The mineral Moon's colour: `args.colour_videos` 16-bit videos (the
    camera's 12 bits whole: the Moon's colours are a step or two of 8 bits),
    exposed lower so that nothing clips, each with the disc somewhere else
    on the sensor. Returns their notes."""
    level = exposure * MINERAL_LEVEL / lunar.TARGET_LEVEL
    start = list(s.aim)
    _, disc = s.look(exposure)
    if disc is None:
        raise SystemExit("The Moon was lost before the colour videos: cloud?")
    room = (shape[1] - lunar.roi(disc, shape)[2]) / 2
    out = []
    for n, right in enumerate(dither_steps(args.colour_videos, room)):
        east, north = lunar.correction(matrix, 0.0, -right)
        s.aim = [start[0] + east, start[1] + north]
        s.go()
        _, disc = s.look(level)
        if disc is None:
            say(f"colour video {n + 1}: no Moon (cloud?), skipped")
            continue
        region = lunar.roi(disc, shape) if not args.full_frame else None
        side = (region[2], region[3]) if region else (shape[1], shape[0])
        frames = frames_that_fit(args.colour_frames, side[0] * side[1] * 2, free_disk())
        if frames < min(20, args.colour_frames):
            say(f"colour video {n + 1}: no room on the disk, skipped")
            continue
        path = lucky.OUT / f"Moon-{stamp}-colour{n + 1}.ser"
        say(f"colour video {n + 1} of {args.colour_videos}: {level * 1000:.1f} ms, 16-bit, disc {right:+.0f} px "
            f"across the sensor")
        notes = video(s, cam, path, frames, 2, level, region, 16, matrix, white, say)
        notes["dither_px"] = right
        lucky.write_notes(path, notes)
        out.append({"video": str(path), **notes})
    s.aim = start
    if not out:
        raise SystemExit("No colour video was taken: cloud, or no room on the disk.")
    return out


@activity.during("Imaging the Moon", "{args.frames} frames")
def run(args, scope=None, cam=None, site=None, say=print):
    import shoot
    site = site or config.load()["site"]
    _rig = shoot.hold_the_rig("Moon")
    white = 2 ** config.hardware()["camera"]["bit_depth"] - 1
    if args.focus_check:
        if scope is None:
            import mount
            scope = mount.Mount(watch=False)
        scope.goto_target(args.focus_check, site)
        checked = subprocess.run([sys.executable, str(ROOT / "focus.py"), "--check"], capture_output=True, text=True)
        say(checked.stdout.strip().splitlines()[-1] if checked.stdout.strip() else "focus check gave no answer")
        if "soft" in checked.stdout:
            raise SystemExit("Focus is soft: set the drawtube a touch out by hand, then ./focus.py --walk-in "
                             "on a star field, before the Moon.")
    if scope is None:
        import mount
        scope = mount.Mount(watch=False)
    if cam is None:
        from camera import Camera
        cam = Camera(gain=args.gain)
    s = Session(scope, cam, site, say)
    s.aim = list(args.aim)
    s.go()
    lucky.progress("centring")
    exposure = args.exposure or FIRST_EXPOSURE
    image, disc = s.look(exposure)
    if disc is None:
        image, disc = s.look(exposure * 8)
        exposure *= 8
    if disc is None:
        raise SystemExit("No Moon in the frame: cloud, or the GoTo is far off "
                         "(./ty mount goto Moon --aim-off EAST NORTH to bring it in).")
    shape = image.shape
    matrix = load_calibration(s.side())
    if matrix is None:
        matrix, disc = s.calibrate(exposure, disc, shape)
    disc = s.centre(exposure, disc, shape, matrix)
    if not args.exposure:
        for _ in range(2):
            exposure, cam.gain = lunar.exposure_for(disc, exposure, white, cam.gain)
            _, found = s.look(exposure)
            disc = found or disc
    region = lunar.roi(disc, shape) if not args.full_frame else None
    side_px = (region[2], region[3]) if region else (shape[1], shape[0])
    frame_bytes = side_px[0] * side_px[1] * (1 if args.depth == 8 else 2)
    frames = frames_that_fit(args.frames, frame_bytes, free_disk())
    if frames < min(50, args.frames):
        raise SystemExit(f"Only {frames} frames fit on the disk: free some space first.")
    say(f"Moon centred; {exposure * 1000:.1f} ms at gain {cam.gain}, region {side_px[0]}x{side_px[1]} px; "
        f"{frames} frames in {args.bursts} bursts")
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    path = lucky.OUT / f"Moon-{stamp}.ser"
    try:
        notes = video(s, cam, path, frames, args.bursts, exposure, region, args.depth, matrix, white, say)
        if args.mineral:
            colours = colour_videos(s, cam, stamp, args, exposure, shape, matrix, white, say)
    finally:
        close = getattr(cam, "close", None)
        if close:
            close()
    if args.mineral:
        notes["colour_videos"] = [c["video"] for c in colours]
    if args.no_stack:
        return {"video": str(path), **notes}
    done = lucky.stack_file(path, keeps=args.keep, in_colour=args.colour, pixels=args.pixels)
    if not args.mineral:
        return {"video": str(path), **notes, "stack": done}
    import mineral
    for c in colours:
        lucky.stack_file(c["video"], keeps=(10, 40), in_colour=True, publish=False, flat=True)
    jpg, facts = mineral.run([c["video"] for c in colours], details=[path], strength=args.strength)
    return {"video": str(path), **notes, "stack": done, "mineral": str(jpg), "mineral_facts": facts}


def parse(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--frames", type=int, default=1000, help="frames in the whole video")
    ap.add_argument("--bursts", type=int, default=4, help="the video in this many parts, re-centred between")
    ap.add_argument("--exposure", type=float, help="seconds a frame (default: set from the Moon's brightness)")
    ap.add_argument("--gain", type=int, default=100)
    ap.add_argument("--depth", type=int, choices=(8, 16), default=8)
    ap.add_argument("--keep", type=float, nargs="+", default=list(lucky.KEEPS), help="shares to stack, per cent")
    ap.add_argument("--colour", action="store_true", help="natural colour rather than green detail")
    ap.add_argument("--pixels", choices=("green", "all"), default="green",
                    help="the detail picture from the greens filled in, or every pixel balanced")
    ap.add_argument("--full-frame", action="store_true", help="the whole sensor rather than the region round the disc")
    ap.add_argument("--aim", type=float, nargs=2, default=[0.0, 0.0], metavar=("EAST", "NORTH"),
                    help="arcminutes off the Moon's centre to aim at first")
    ap.add_argument("--focus-check", metavar="STAR", help="measure focus on this star field first")
    ap.add_argument("--no-stack", action="store_true", help="take the video only")
    ap.add_argument("--mineral", action="store_true",
                    help="a mineral Moon: the detail video, then 16-bit colour videos, then mineral.py")
    ap.add_argument("--colour-videos", type=int, default=3, help="--mineral: colour videos, the disc moved between")
    ap.add_argument("--colour-frames", type=int, default=200, help="--mineral: frames in each colour video")
    ap.add_argument("--strength", default="standard", help="--mineral: mild, standard, strong, auto or a number")
    ap.add_argument("--dry-run", action="store_true", help="say what it would do; nothing moves")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse(argv)
    if args.dry_run:
        site = (config.example() if config.DEMO else config.load())["site"]
        out = plan(args, site)
        print(json.dumps(out, indent=1))
        return 0
    run(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
