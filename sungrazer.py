#!/usr/bin/env python3
"""Comets near the Sun in SOHO's pictures: the cloudy-night hunt.

    ./sungrazer.py fetch                the last 12 hours of LASCO C3 pictures
    ./sungrazer.py fetch --hours 24 --camera c2
    ./sungrazer.py look                 moving points in what has been fetched, as tracks and movies
    ./sungrazer.py look --json
    ./sungrazer.py fetch --until 2025-01-25T18:00 --hours 24    a day in the past
    ./sungrazer.py look --until 2025-01-25T18:00 --hours 24     a known comet, to see it is found

SOHO's LASCO coronagraphs photograph the sky round the Sun every 12 minutes
or so, and volunteers have found most of the 5,000 and more comets in them
(the Sungrazer Project, sungrazer.nrl.navy.mil). No telescope is needed and
no clear sky: this is what to do on a cloudy night.

`fetch` takes the project's public pictures (1024 pixels, from
soho.nascom.nasa.gov), one at a time with a pause between, each only once:
the project asks hunters not to load its servers.

`look` takes each picture less the median of the pictures either side of
it, so the corona and its slow streamers go and what moves stays; leaves
out the occulter in the middle and the writing along the edge; finds faint
points in each; and links them from picture to picture into tracks of at
least TRACK_LEN pictures moving in a straight line at a steady rate. The
background stars all drift together as SOHO goes round the Sun: that drift
is measured from the tracks themselves, and a track moving with it is a
star. What is left is listed with an animation of each, kept under
sungrazer/DATE/, for a person to watch. A comet is usually faint, moves
steadily, and in C3 most often heads in towards the Sun.

Nothing is reported for you: a comet is reported through the project's
own form (sungrazer.nrl.navy.mil/report), with your name, the pictures'
times and the comet's positions in them, once you have watched it and
checked the project's list of recent finds. Nothing here moves the mount
or uses the camera.
"""
import argparse
import datetime
import io
import json
import math
import re
import time
from pathlib import Path

import numpy as np
import requests
from scipy import ndimage
from scipy.spatial import cKDTree

import config
import interface

BASE = "https://soho.nascom.nasa.gov/data/REPROCESSING/Completed"
NAME = re.compile(r"(\d{8})_(\d{4})_(c2|c3)_1024\.jpg")
PAUSE = 1.0          # seconds between pictures fetched
WINDOW = 3           # pictures either side making the background a picture is taken less
SIGMA = 5.0          # a point stands this many times the noise above its background
MOST = 400           # the strongest points kept from each picture: more is noise lining up by chance
TRACK_LEN = 5        # pictures a track must run through
STAR_TRACK = 10      # a track this long is a star: the stars' drift is measured from these
STEADY = 3.0         # a track's brightest point at most this many times its faintest
REACH = 14.0         # pixels a point may move in CADENCE minutes (C3: about 0.2°)
CADENCE = 12.0       # minutes between pictures, as a rule: motion is given per this long
MOST_GAP = 3.0       # a track bridges a gap of at most this many times CADENCE
STRAIGHT = 1.0       # pixels a track's points may sit off its straight line
STAR_LIKE = 0.6      # pixels in CADENCE minutes: a track this close to the stars' common drift is a star
EDGE = 30            # pixels round the edge left out
OCCULTER = {"c3": 80, "c2": 150}   # pixels round the middle left out (the occulter and its pylon)
CAPTION = 60         # pixels along the bottom left out: the date and time written there


def folder():
    return config.DATA / "sungrazer"


# --- fetching ----------------------------------------------------------------

def day_list(day, camera, get=requests.get):
    """The pictures there are for one day (UTC), as their file names."""
    reply = get(f"{BASE}/{day[:4]}/{camera}/{day}/", timeout=60)
    if reply.status_code == 404:
        return []
    reply.raise_for_status()
    return sorted(set(m.group(0) for m in NAME.finditer(reply.text) if m.group(3) == camera))


def stamp(name):
    """When a picture was taken, UTC, from its name."""
    m = NAME.match(name)
    return datetime.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M").replace(tzinfo=datetime.timezone.utc)


def fetch(hours, camera, say=print, get=requests.get, now=None, pause=PAUSE):
    """Fetch the last `hours` of pictures not already kept. Returns the paths."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    since = now - datetime.timedelta(hours=hours)
    days = sorted({(since + datetime.timedelta(days=d)).strftime("%Y%m%d")
                   for d in range((now.date() - since.date()).days + 1)})
    wanted = [n for d in days for n in day_list(d, camera, get) if since <= stamp(n) <= now]
    kept = []
    store = folder() / "pictures" / camera
    store.mkdir(parents=True, exist_ok=True)
    fresh = 0
    for name in wanted:
        path = store / name
        if not path.exists():
            reply = get(f"{BASE}/{name[:4]}/{camera}/{name[:8]}/{name}", timeout=60)
            reply.raise_for_status()
            path.write_bytes(reply.content)
            fresh += 1
            time.sleep(pause)
        kept.append(path)
    say(f"{len(kept)} {camera.upper()} pictures from the {hours:g} h to {now:%Y-%m-%d %H:%M} ({fresh} fetched, the rest already kept)")
    return kept


# --- looking -------------------------------------------------------------------

def load(path):
    from PIL import Image
    return np.asarray(Image.open(path).convert("L"), dtype=np.float32)


def usable(shape, camera, images=None):
    """Where a point can be trusted: away from the edge, the occulter in the
    middle and the writing along the bottom; with the pictures given, also
    away from what is always dark in them (the occulter's pylon), whose
    edge flickers from picture to picture."""
    h, w = shape
    yy, xx = np.indices(shape)
    ok = (xx >= EDGE) & (yy >= EDGE) & (xx < w - EDGE) & (yy < h - CAPTION)
    ok &= np.hypot(xx - w / 2, yy - h / 2) > OCCULTER.get(camera, 80)
    if images is not None and len(images) >= 3:
        middle = np.median(np.array(images), axis=0)
        dark = middle <= np.percentile(middle[ok], 3)
        ok &= ~ndimage.binary_dilation(dark, iterations=10)
    return ok


def points(images, mask, sigma=SIGMA, window=WINDOW):
    """Faint points in each picture once the pictures either side are taken
    off: rows of (picture, x, y, brightness) for each picture that has
    neighbours enough."""
    out = []
    stack = np.array(images)
    for i in range(len(images)):
        lo, hi = max(0, i - window), min(len(images), i + window + 1)
        others = np.concatenate([stack[lo:i], stack[i + 1:hi]])
        if len(others) < 2:
            continue
        diff = stack[i] - np.median(others, axis=0)
        diff = ndimage.gaussian_filter(diff, 1.0)
        spread = 1.4826 * float(np.median(np.abs(diff[mask] - np.median(diff[mask])))) + 1e-6
        peak = (diff == ndimage.maximum_filter(diff, size=5)) & (diff > sigma * spread) & mask
        ys, xs = np.nonzero(peak)
        strongest = np.argsort(-diff[ys, xs])[:MOST]
        for x, y in zip(xs[strongest], ys[strongest]):
            out.append((i, float(x), float(y), float(diff[y, x] / spread)))
    return out


def tracks(found, frames, reach=REACH, length=TRACK_LEN, straight=STRAIGHT, minutes=None):
    """Points linked from picture to picture into straight, steady tracks.
    `minutes` gives each picture's time (default: every CADENCE minutes),
    so a gap in the pictures stretches the step, not the track. Each track
    is a list of (picture, x, y, strength, minute)."""
    minutes = list(minutes) if minutes is not None else [i * CADENCE for i in range(frames)]
    by = {}
    for row in found:
        by.setdefault(row[0], []).append(tuple(row[:4]) + (minutes[row[0]],))
    trees = {i: cKDTree([(r[1], r[2]) for r in rows]) for i, rows in by.items()}
    out, used = [], set()
    for start in sorted(by):
        if start + 1 not in trees:
            continue
        gap = (minutes[start + 1] - minutes[start]) / CADENCE
        if gap > MOST_GAP:
            continue
        for a in by[start]:
            if (start, a[1], a[2]) in used:
                continue
            for b_i in trees[start + 1].query_ball_point((a[1], a[2]), reach * max(gap, 1.0)):
                b = by[start + 1][b_i]
                track = [a, b]
                vx, vy = (b[1] - a[1]) / (b[4] - a[4]), (b[2] - a[2]) / (b[4] - a[4])
                k = start + 2
                while k in trees and (minutes[k] - track[-1][4]) / CADENCE <= MOST_GAP:
                    dt = minutes[k] - track[-1][4]
                    guess = (track[-1][1] + vx * dt, track[-1][2] + vy * dt)
                    d, j = trees[k].query(guess, distance_upper_bound=straight * 2)
                    if not np.isfinite(d):
                        break
                    track.append(by[k][j])
                    span = track[-1][4] - track[0][4]
                    vx, vy = (track[-1][1] - track[0][1]) / span, (track[-1][2] - track[0][2]) / span
                    k += 1
                if len(track) >= length and fits_line(track, straight) and steady(track):
                    out.append(track)
                    used.update((p[0], p[1], p[2]) for p in track)
                    break
    return out


def steady(track, most=STEADY):
    """Whether a track's brightness holds steady enough to be one thing:
    chance alignments of noise jump about."""
    strength = [p[3] for p in track]
    return max(strength) <= most * min(strength)


def fits_line(track, straight):
    """Whether a track's points lie within `straight` pixels of a steady
    straight motion in time."""
    t = np.array([p[4] for p in track], float)
    xy = np.array([(p[1], p[2]) for p in track])
    for axis in (0, 1):
        slope, start = np.polyfit(t, xy[:, axis], 1)
        if np.max(np.abs(xy[:, axis] - (start + slope * t))) > straight:
            return False
    return True


def velocity(track):
    """Pixels each CADENCE minutes, x and y."""
    t = np.array([p[4] for p in track], float)
    return CADENCE * np.array([np.polyfit(t, [p[1] for p in track], 1)[0], np.polyfit(t, [p[2] for p in track], 1)[0]])


def star_drift(all_tracks, long=STAR_TRACK):
    """The stars' common drift, pixels each CADENCE minutes: the middle of the long
    tracks' velocities. Only a star stays in view, steady, for so many
    pictures; short tracks include noise lined up by chance."""
    longest = [t for t in all_tracks if len(t) >= long] or [t for t in all_tracks if len(t) >= TRACK_LEN + 2]
    if not longest:
        return None
    v = np.array([velocity(t) for t in longest])
    return np.median(v, axis=0)


def judge(all_tracks, drift, shape):
    """The tracks that do not move like the stars, as candidates."""
    out = []
    centre = np.array([shape[1] / 2, shape[0] / 2])
    for t in all_tracks:
        v = velocity(t)
        if drift is not None and np.hypot(*(v - drift)) < STAR_LIKE:
            continue
        start = np.array([t[0][1], t[0][2]])
        inward = float(np.dot(v, centre - start) / (np.linalg.norm(v) * np.linalg.norm(centre - start) + 1e-9))
        out.append({"pictures": [p[0] for p in t], "track": [[round(p[1], 1), round(p[2], 1)] for p in t],
                    "pixels_per_12_min": round(float(np.hypot(*v)), 2),
                    "towards_sun": round(inward, 2), "strength": round(float(np.median([p[3] for p in t])), 1)})
    return sorted(out, key=lambda c: (-c["towards_sun"], -c["strength"]))


def movie(paths, candidate, out, half=40):
    """A small animation of the pictures round a track, the track's points
    marked, each picture less its neighbours' median so it stands out."""
    from PIL import Image, ImageDraw
    images = [load(p) for p in paths]
    xs, ys = zip(*candidate["track"])
    cx, cy = int(np.mean(xs)), int(np.mean(ys))
    frames = []
    first, last = max(0, candidate["pictures"][0] - 2), min(len(images), candidate["pictures"][-1] + 3)
    for i in range(first, last):
        cut = images[i][max(cy - half, 0):cy + half, max(cx - half, 0):cx + half]
        lo, hi = np.percentile(cut, [1, 99.5])
        pic = Image.fromarray(np.clip((cut - lo) / (hi - lo + 1e-9) * 255, 0, 255).astype(np.uint8)).resize(
            (cut.shape[1] * 4, cut.shape[0] * 4), Image.NEAREST).convert("RGB")
        if i in candidate["pictures"]:
            k = candidate["pictures"].index(i)
            x, y = candidate["track"][k]
            px, py = (x - max(cx - half, 0)) * 4, (y - max(cy - half, 0)) * 4
            ImageDraw.Draw(pic).ellipse([px - 14, py - 14, px + 14, py + 14], outline=(255, 80, 80), width=2)
        frames.append(pic)
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=400, loop=0)
    return str(out)


def look(camera, hours=None, say=print, paths=None, until=None):
    """Look through the kept pictures for moving points that are not stars:
    the `hours` before `until`, or before the newest picture kept."""
    if paths is None:
        paths = sorted((folder() / "pictures" / camera).glob(f"*_{camera}_1024.jpg"))
        if until:
            paths = [p for p in paths if stamp(p.name) <= until]
        if hours and paths:
            newest = stamp(paths[-1].name)
            paths = [p for p in paths if newest - stamp(p.name) <= datetime.timedelta(hours=hours)]
    if len(paths) < TRACK_LEN + 2:
        raise interface.Refusal("NO_SESSION", f"Too few {camera.upper()} pictures kept ({len(paths)}): "
                                f"./sungrazer.py fetch first.")
    images = [load(p) for p in paths]
    shape = images[0].shape
    if any(i.shape != shape for i in images):
        keep = [p for p, i in zip(paths, images) if i.shape == shape]
        images = [i for i in images if i.shape == shape]
        paths = keep
    mask = usable(shape, camera, images)
    found = points(images, mask)
    start = stamp(paths[0].name)
    minutes = [(stamp(p.name) - start).total_seconds() / 60 for p in paths]
    linked = tracks(found, len(images), minutes=minutes)
    drift = star_drift(linked)
    candidates = judge(linked, drift, shape)
    day = stamp(paths[-1].name).strftime("%Y%m%d-%H%M")
    out = folder() / day
    out.mkdir(parents=True, exist_ok=True)
    for n, c in enumerate(candidates[:20], 1):
        c["times"] = [stamp(paths[i].name).strftime("%Y-%m-%d %H:%M") for i in c["pictures"]]
        c["files"] = [paths[i].name for i in c["pictures"]]
        c["movie"] = movie(paths, c, out / f"candidate-{n}.gif")
    answer = {"camera": camera, "pictures": len(paths), "from": paths[0].name, "to": paths[-1].name,
              "points": len(found), "tracks": len(linked),
              "star_drift": None if drift is None else [round(float(v), 2) for v in drift],
              "candidates": candidates[:20], "folder": str(out)}
    (out / "look.json").write_text(json.dumps(answer, indent=1), encoding="utf-8")
    say(f"{len(paths)} pictures, {len(found)} points, {len(linked)} tracks; the stars drift "
        f"{answer['star_drift']} pixels in 12 minutes")
    if not candidates:
        say("No track moves other than as the stars do.")
    for n, c in enumerate(candidates[:20], 1):
        say(f"  {n}. {len(c['pictures'])} pictures from {c['times'][0]}, {c['pixels_per_12_min']} px in 12 min, "
            f"{'towards' if c['towards_sun'] > 0.5 else 'not towards'} the Sun, strength {c['strength']}: {c['movie']}")
    if candidates:
        say("Watch each movie. A comet is faint and moves steadily; check the project's recent finds, then "
            "report through sungrazer.nrl.navy.mil/report with your name, the times and its positions.")
    return answer


def moment(text):
    """A time given on the command line, taken as UTC."""
    when = datetime.datetime.fromisoformat(text)
    return when if when.tzinfo else when.replace(tzinfo=datetime.timezone.utc)


def run(args, say=print):
    until = moment(args.until) if args.until else None
    if args.action == "fetch":
        paths = fetch(args.hours, args.camera, say, now=until)
        return {"camera": args.camera, "pictures": len(paths), "kept": str(folder() / "pictures" / args.camera)}
    return look(args.camera, args.hours, say, until=until)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", choices=("fetch", "look"))
    ap.add_argument("--camera", choices=("c3", "c2"), default="c3", help="LASCO C3 (wide) or C2 (close in)")
    ap.add_argument("--hours", type=float, default=12.0, help="how far back (default 12)")
    ap.add_argument("--until", help="the end of the time looked at, UTC (YYYY-MM-DDTHH:MM; default now, or "
                    "the newest picture kept)")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("sungrazer", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
