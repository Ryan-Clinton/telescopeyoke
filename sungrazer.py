#!/usr/bin/env python3
"""Comets near the Sun in SOHO's pictures: the cloudy-night hunt.

    ./sungrazer.py fetch                the last 12 hours of LASCO C3 pictures
    ./sungrazer.py fetch --hours 24 --camera c2
    ./sungrazer.py look                 moving points in what has been fetched, as tracks and movies
    ./sungrazer.py look --json
    ./sungrazer.py fetch --until 2025-01-25T18:00 --hours 24    a day in the past
    ./sungrazer.py look --until 2025-01-25T18:00 --hours 24     a known comet, to see it is found
    ./sungrazer.py fetch --raw          the raw pictures instead, for fainter comets
    ./sungrazer.py look --raw
    ./sungrazer.py fetch --camera ccor1 GOES-19's coronagraph, where most comets are found now
    ./sungrazer.py look --plant 120     how faint a comet is found: fakes planted in the real pictures
    ./sungrazer.py hunt --camera ccor1  fetch the last day, look, keep only what heads for the Sun, tidy up
    ./sungrazer.py hunt --install       run that every 6 hours (a systemd user timer)

SOHO's LASCO coronagraphs photograph the sky round the Sun every 12 minutes
or so, and volunteers have found most of the 5,000 and more comets in them
(the Sungrazer Project, sungrazer.nrl.navy.mil). No telescope is needed and
no clear sky: this is what to do on a cloudy night.

`fetch` takes the project's public pictures (1024 pixels, from
soho.nascom.nasa.gov), one at a time with a pause between, each only once:
the project asks hunters not to load its servers. With --raw it takes the
raw pictures instead (level 0.5 FITS, from umbra.nascom.nasa.gov: the
archive, or the last fortnight's while the archive catches up), about 2 MB
each against the JPEG's 100 kB, but with the faint end the JPEG's
brightness curve throws away: the full-size, unpolarised ones in the
day's usual filter only. Each is taken less its camera's offset, per
second of exposure, and its square root kept, so the noise is about the
same over the bright inner corona and the dark sky outside it; the blocks
lost in transmission are filled from the pictures either side.

`--camera ccor1` is the Compact Coronagraph on GOES-19 (NOAA, since
2025), whose pictures most new Sungrazer comets have been found in since
then: its level-3 pictures, every 15 minutes, from NOAA's open archive
(noaa-nesdis-swfo-ccor-1-pds on Amazon's S3), FITS with the corona's slow
background already taken off, about 1.7 MB each; the 5-minute bursts
in between are left out.

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

`look --plant N` measures how faint a comet can be and still be found,
as depth.py does for the telescope: N fake comets, each a point heading
in towards the Sun at 2 to 6 pixels in 12 minutes for PLANT_LEN pictures,
are put into the real pictures at a strength of each of STRENGTHS times
the noise there, and the share of each strength found is the answer
(kept in the look folder as plant.json); nothing else is listed.

A track that stops and one that starts where it was heading, moving the
same way, within STITCH_GAP minutes, are joined into one (`stitch`): on
19 October 2026 a 45-minute gap in CCOR-1's pictures split one comet in
two. Each candidate's places are also given as the Sungrazer Project
measures them (`native`): for CCOR-1, pixels of the full 2048 x 1920
frame from the top left, where a kept level-3 picture is half that and
bottom row first.

`hunt` is the hunt left running: it fetches the last HUNT_HOURS, looks,
keeps the candidates heading in towards the Sun (the rest are mostly the
corona blowing outwards) in sungrazer/hunt-CAMERA.json, and deletes
pictures older than KEEP_DAYS. A weak track (below RIM_STRENGTH) that
never leaves the occulter's flickering rim is set aside, kept in the
answer but not sent. The person hears in two messages: first what was
found, with its movies; then, once checked, what each one is. The checks:
a planet or bright star on the track (`body_on`, CCOR-1, whose pictures
carry sky coordinates), and the project's public list of reports for that
camera (`public_match`, one page a hunt): "known comet" when it lies on a
report of a known comet carried to its times, "possible public match" for
anyone else's report, "no matching public report found" otherwise, which
is offered for reporting. A candidate already sent is remembered for
TOLD_DAYS (sungrazer/told-CAMERA.json) and not sent again by the next
hunts, which look at the same hours; one still unexplained is checked
again by each, and the person told when its answer changes. 20 October
2026: the comet the hunt found was only identified once the person asked. `hunt --install` runs it every 6 hours as
a systemd user timer, from the checkout it is installed from; only for
CCOR-1, whose archive is NOAA's open one, until the Sungrazer Project has
been asked about LASCO. `systemctl --user disable --now
ty-sungrazer.timer` stops it.

Nothing is reported for you: a comet is reported through the project's
own form (sungrazer.nrl.navy.mil/report), with your name, the pictures'
times and the comet's positions in them, once you have watched it and
checked the project's list of recent finds. Nothing here moves the mount
or uses the camera.
"""
import argparse
import datetime
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import requests
from scipy import ndimage
from scipy.spatial import cKDTree

import config
import interface
import records

BASE = "https://soho.nascom.nasa.gov/data/REPROCESSING/Completed"
NAME = re.compile(r"(\d{8})_(\d{4})_(c2|c3)_1024\.jpg")
RAW = ("https://umbra.nascom.nasa.gov/pub/lasco_level05",                 # the archive
       "https://umbra.nascom.nasa.gov/pub/lasco/lastimage/level_05")      # the last fortnight
RAW_NAME = re.compile(r"(\d{8})_(\d{6})_(c2|c3)\.fts")                # as kept here
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
OCCULTER = {"c3": 80, "c2": 150, "ccor1": 110}   # pixels round the middle left out (the occulter and its pylon)
ARM = {"ccor1": 20}  # pixels left out beside the occulter's arm, where its edge flickers (10 elsewhere)
CCOR = "https://noaa-nesdis-swfo-ccor-1-pds.s3.amazonaws.com"
CCOR_LEVEL = "SWFO/GOES-19/CCOR-1/ccor1-l3"
CCOR_NAME = re.compile(r"CCOR1_3_(\d{8})T(\d{6})_V\d+_NC\.fits")
CCOR_SCALE = 1e12    # CCOR-1's mean solar brightness units are about 1e-12: brought nearer 1
STRENGTHS = (3, 4, 6, 8, 12, 16)   # fake comets' peak, times the noise of a picture less its neighbours
PLANT_LEN = 12       # pictures a fake comet runs through
HUNT_HOURS = 24      # hunt: the last this many hours
KEEP_DAYS = 3        # hunt: pictures older than this are deleted
TOWARDS = 0.5        # hunt: a candidate heading in towards the Sun at least this squarely
BLOCK = 64           # pixels square in which the noise is measured on its own
CAPTION = 60         # pixels along the bottom left out: the date and time written there
STITCH_GAP = 120.0   # minutes: a track that stops and one that starts this soon after may be one thing
STITCH_NEAR = 3.0    # pixels between where the first track was heading and where the second starts
STITCH_SAME = 0.6    # pixels in CADENCE minutes the two tracks' motions may differ
REPORTS = "https://sungrazer.nrl.navy.mil/index.php/reports"
REPORT_CAMERA = {"ccor1": "CCOR1", "c3": "C3", "c2": "C2"}
NATIVE = {"ccor1": (2048, 1920)}   # the full frame the project's reports measure, where a kept picture is smaller
MATCH_PX = 12.0      # pixels of the report's frame: a reported point this near the track at its time is a match
MATCH_HOURS = 6.0    # hours a track is carried on, either way, to meet a report's times
RIM = {"ccor1": 70}  # pixels beyond the occulter where its bright edge flickers (40 elsewhere)
RIM_STRENGTH = 20.0  # hunt: a track wholly in the rim this weak is set aside, not sent


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


def raw_day_list(day, camera, get=requests.get):
    """The raw pictures for one day (UTC) worth looking at, as (address,
    name kept here): the full-size, unpolarised ones in the day's usual
    filter, read from the day's list of headers."""
    for base in RAW:
        folder_url = f"{base}/{day[2:]}/{camera}/"
        reply = get(folder_url + "img_hdr.txt", timeout=60)
        if reply.status_code == 200 and ".fts" in reply.text:
            break
    else:
        return []
    rows = [r.split() for r in reply.text.splitlines()]
    rows = [r for r in rows if len(r) >= 11 and r[0].endswith(".fts") and r[5] == r[6] == "1024" and r[10] == "Clear"]
    if not rows:
        return []
    usual = max({r[9] for r in rows}, key=lambda f: sum(r[9] == f for r in rows))
    return sorted((folder_url + r[0], f"{r[1].replace('/', '')}_{r[2][:8].replace(':', '')}_{camera}.fts")
                  for r in rows if r[9] == usual)


def ccor_day_list(day, get=requests.get):
    """CCOR-1's level-3 pictures for one day (UTC), every 15 minutes, as
    (address, name)."""
    reply = get(f"{CCOR}/", timeout=60, params={"list-type": "2", "prefix": f"{CCOR_LEVEL}/{day[:4]}/{day[4:6]}/{day[6:]}/"})
    if reply.status_code == 404:
        return []
    reply.raise_for_status()
    keys = re.findall(r"<Key>([^<]+)</Key>", reply.text)
    return sorted((f"{CCOR}/{k}", k.rsplit("/", 1)[-1]) for k in keys if CCOR_NAME.match(k.rsplit("/", 1)[-1]))


def stamp(name):
    """When a picture was taken, UTC, from its name."""
    m = RAW_NAME.match(name) or CCOR_NAME.match(name)
    if m:
        return datetime.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc)
    m = NAME.match(name)
    return datetime.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M").replace(tzinfo=datetime.timezone.utc)


def fetch(hours, camera, say=print, get=requests.get, now=None, pause=PAUSE, raw=False):
    """Fetch the last `hours` of pictures not already kept. Returns the paths."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    since = now - datetime.timedelta(hours=hours)
    days = sorted({(since + datetime.timedelta(days=d)).strftime("%Y%m%d")
                   for d in range((now.date() - since.date()).days + 1)})
    if camera == "ccor1":
        wanted = [(url, n) for d in days for url, n in ccor_day_list(d, get) if since <= stamp(n) <= now]
    elif raw:
        wanted = [(url, n) for d in days for url, n in raw_day_list(d, camera, get) if since <= stamp(n) <= now]
    else:
        wanted = [(f"{BASE}/{n[:4]}/{camera}/{n[:8]}/{n}", n) for d in days for n in day_list(d, camera, get)
                  if since <= stamp(n) <= now]
    kept = []
    store = folder() / "pictures" / camera
    store.mkdir(parents=True, exist_ok=True)
    fresh = 0
    for url, name in wanted:
        path = store / name
        if not path.exists():
            reply = get(url, timeout=60)
            reply.raise_for_status()
            path.write_bytes(reply.content)
            fresh += 1
            time.sleep(pause)
        kept.append(path)
    say(f"{len(kept)} {'raw ' if raw else ''}{camera.upper()} pictures from the {hours:g} h to {now:%Y-%m-%d %H:%M} "
        f"({fresh} fetched, the rest already kept)")
    return kept


# --- looking -------------------------------------------------------------------

def load(path):
    """A picture as brightness: a JPEG as it is; a raw picture less its
    offset, per second, square-rooted, with what was lost as NaN; a CCOR-1
    picture as it is, its background already gone."""
    if Path(path).name.startswith("CCOR1_"):
        from astropy.io import fits
        with fits.open(path) as f:
            hdu = next(h for h in f if h.data is not None)
            return np.asarray(hdu.data, dtype=np.float32) * CCOR_SCALE
    if str(path).endswith(".fts"):
        from astropy.io import fits
        with fits.open(path) as f:
            data, head = f[0].data.astype(np.float32), f[0].header
        lost = data <= 0
        data = np.sqrt(np.clip(data - float(head.get("OFFSET", 0)), 0, None) / float(head.get("EXPTIME") or 1))
        data[lost] = np.nan
        return data
    from PIL import Image
    return np.asarray(Image.open(path).convert("L"), dtype=np.float32)


def fill(images):
    """The blocks a raw picture lost in transmission, filled from the
    middle of all the pictures, so they neither show nor hide a point."""
    stack = np.array(images)
    if not np.isnan(stack).any():
        return images
    middle = np.nanmedian(stack, axis=0)
    middle = np.where(np.isfinite(middle), middle, 0)
    return [np.where(np.isfinite(i), i, middle).astype(np.float32) for i in images]


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
        # CCOR-1 blanks its occulter's arm and the corners outside its view
        # to exactly 0; in LASCO's pictures they are the darkest part.
        dark = middle == 0 if camera == "ccor1" else middle <= np.percentile(middle[ok], 3)
        ok &= ~ndimage.binary_dilation(dark, iterations=ARM.get(camera, 10))
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
        spread = local_spread(diff, mask)
        peak = (diff == ndimage.maximum_filter(diff, size=5)) & (diff > sigma * spread) & mask
        ys, xs = np.nonzero(peak)
        strongest = np.argsort(-diff[ys, xs])[:MOST]
        for x, y in zip(xs[strongest], ys[strongest]):
            out.append((i, float(x), float(y), float(diff[y, x] / spread[y, x])))
    return out


def local_spread(diff, mask, block=BLOCK):
    """The noise at each pixel, measured in each BLOCK-pixel square on its
    own: the inner corona is far noisier than the sky at the edge, and one
    figure for the whole picture would bury the faint points there or
    flood the inner part with false ones."""
    h, w = diff.shape
    rows, cols = -(-h // block), -(-w // block)
    grid = np.full((rows, cols), np.nan)
    for r in range(rows):
        for c in range(cols):
            cut = diff[r * block:(r + 1) * block, c * block:(c + 1) * block]
            ok = mask[r * block:(r + 1) * block, c * block:(c + 1) * block]
            if ok.sum() >= block * block // 8:
                v = cut[ok]
                grid[r, c] = 1.4826 * float(np.median(np.abs(v - np.median(v))))
    if np.isnan(grid).all():
        v = diff[mask] if mask.any() else diff.ravel()
        return np.full(diff.shape, 1.4826 * float(np.median(np.abs(v - np.median(v)))) + 1e-12, np.float32)
    grid = np.where(np.isnan(grid), np.nanmedian(grid), grid)
    full = np.kron(grid, np.ones((block, block)))[:h, :w]
    return (ndimage.uniform_filter(full, block) + 1e-12).astype(np.float32)


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


def stitch(all_tracks, most_gap=STITCH_GAP, near=STITCH_NEAR, same=STITCH_SAME):
    """Tracks joined across a gap: one that stops, and one that starts
    within `most_gap` minutes where the first was heading (within `near`
    pixels) and moving the same way (within `same` pixels in CADENCE
    minutes), are one thing seen twice (a missing picture or a faint
    spell). The longer gaps the linking itself cannot bridge."""
    out = sorted((list(t) for t in all_tracks), key=lambda t: t[0][4])
    joined = True
    while joined:
        joined = False
        for a in out:
            va = velocity(a) / CADENCE
            for b in out:
                gap = b[0][4] - a[-1][4]
                if b is a or not 0 < gap <= most_gap:
                    continue
                guess = np.array([a[-1][1], a[-1][2]]) + va * gap
                if np.hypot(*(guess - (b[0][1], b[0][2]))) <= near and \
                        np.hypot(*(velocity(b) - va * CADENCE)) <= same:
                    a.extend(b)
                    out.remove(b)
                    joined = True
                    break
            if joined:
                break
    return out


def gaps(times, most=MOST_GAP * CADENCE):
    """The gaps in a track longer than its linking bridges: ["20:00-20:45"]."""
    when = [datetime.datetime.strptime(t, "%Y-%m-%d %H:%M") for t in times]
    return [f"{a:%H:%M}-{b:%H:%M}" for a, b in zip(when, when[1:]) if (b - a).total_seconds() / 60 > most]


def native(x, y, camera, shape):
    """A point in the project's own convention: pixels of the camera's full
    frame from the top left. A CCOR-1 level-3 picture is half the full
    frame each way and kept bottom row first (FITS); the JPEGs are as the
    project measures them."""
    if camera not in NATIVE:
        return round(x, 1), round(y, 1)
    w, h = NATIVE[camera]
    sx, sy = w / shape[1], h / shape[0]
    return round(x * sx, 1), round(h - y * sy, 1)


def public_reports(camera, get=requests.get):
    """The project's recent reports for `camera`, from its public list:
    [{"id", "who", "date", "type", "group", "points": [(HHMM, x, y)]}]. One page,
    fetched once a hunt."""
    page = get(REPORTS, params={"field_camera_value": REPORT_CAMERA[camera]}, timeout=30,
               headers={"User-Agent": "telescopeyoke comet hunt"})
    page.raise_for_status()
    out = []
    for row in re.findall(r"<tr class=\"sungrazer-reports-table.*?</tr>", page.text, re.S):
        cell = {k: re.sub(r"<[^>]+>", " ", v).strip()
                for k, v in re.findall(r'views-field-(?:field-)?([a-z-]+) table__cell">(.*?)</td>', row, re.S)}
        frames = re.findall(r'views-field-field-frames table__cell">(.*?)</td>', row, re.S)
        date = re.search(r'datetime="(\d{4}-\d{2}-\d{2})', row)
        if cell.get("camera") != REPORT_CAMERA[camera] or not date or not frames:
            continue
        points = [(h + m, float(x), float(y))
                  for h, m, x, y in re.findall(r"(\d{2}):?(\d{2})\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)", frames[0])]
        out.append({"id": cell.get("title", ""), "who": cell.get("contributor", ""), "date": date[1],
                    "type": cell.get("sighting-type", ""), "group": cell.get("comet-group", ""), "points": points})
    return out


def public_match(c, reports, near=MATCH_PX, hours=MATCH_HOURS):
    """How a candidate stands against the project's reports: "known comet"
    (it matches a report of a known one), "possible public match" (it
    matches someone's report), or "no matching public report found". A
    report matches when one of its points lies within `near` pixels of the
    track carried to that point's time. Nothing is rejected for it."""
    when = [datetime.datetime.strptime(t, "%Y-%m-%d %H:%M") for t in c["times"]]
    t = np.array([(w - when[0]).total_seconds() / 60 for w in when])
    xy = np.array(c["sungrazer_xy"], float)
    fit = [np.polyfit(t, xy[:, k], 1) for k in (0, 1)] if len(t) > 1 else None
    for r in reports:
        day = datetime.datetime.strptime(r["date"], "%Y-%m-%d")
        for hhmm, x, y in r["points"]:
            for d in (day - datetime.timedelta(days=1), day):     # a report sent after midnight
                m = (d.replace(hour=int(hhmm[:2]), minute=int(hhmm[2:])) - when[0]).total_seconds() / 60
                if fit is None or m < t[0] - hours * 60 or m > t[-1] + hours * 60:
                    continue
                if np.hypot(np.polyval(fit[0], m) - x, np.polyval(fit[1], m) - y) <= near:
                    state = "known comet" if "known" in r["type"].lower() else "possible public match"
                    return {"state": state, "report": r["id"], "who": r["who"], "type": r["type"],
                            "group": r.get("group", "")}
    return {"state": "no matching public report found"}


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


def judge(all_tracks, drift, shape, camera=None):
    """The tracks that do not move like the stars, as candidates; `rim`
    marks one that never leaves the occulter's flickering edge."""
    out = []
    centre = np.array([shape[1] / 2, shape[0] / 2])
    for t in all_tracks:
        v = velocity(t)
        if drift is not None and np.hypot(*(v - drift)) < STAR_LIKE:
            continue
        start = np.array([t[0][1], t[0][2]])
        inward = float(np.dot(v, centre - start) / (np.linalg.norm(v) * np.linalg.norm(centre - start) + 1e-9))
        reach = OCCULTER.get(camera, 80) + RIM.get(camera, 40)
        out.append({"pictures": [p[0] for p in t], "track": [[round(p[1], 1), round(p[2], 1)] for p in t],
                    "pixels_per_12_min": round(float(np.hypot(*v)), 2),
                    "rim": bool(max(np.hypot(p[1] - centre[0], p[2] - centre[1]) for p in t) <= reach),
                    "towards_sun": round(inward, 2), "strength": round(float(np.median([p[3] for p in t])), 1)})
    return sorted(out, key=lambda c: (-c["towards_sun"], -c["strength"]))


def movie(images, candidate, out, half=40):
    """A small animation of the pictures round a track, the track's points
    marked."""
    from PIL import Image, ImageDraw
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


def plant(images, mask, count, seed=0, strengths=STRENGTHS, window=WINDOW):
    """Fake comets put into the pictures (in place): points heading in
    towards the middle, each at one of `strengths` times the noise where it
    is. Returns each fake's strength and place in each picture."""
    rng = np.random.default_rng(seed)
    h, w = images[0].shape
    middle = len(images) // 2
    lo, hi = max(0, middle - window), min(len(images), middle + window + 1)
    near = np.median(np.array(images[lo:middle] + images[middle + 1:hi]), axis=0)
    noise = local_spread(images[middle] - near, mask)
    yy, xx = np.indices((h, w))
    centre = np.array([w / 2, h / 2])
    fakes = []
    tries = 0
    while len(fakes) < count and tries < 100 * count:
        tries += 1
        strength = strengths[len(fakes) % len(strengths)]
        first = int(rng.integers(0, max(1, len(images) - PLANT_LEN)))
        angle = rng.uniform(0, 2 * np.pi)
        radius = rng.uniform(0.3, 0.85) * min(h, w) / 2
        start = centre + radius * np.array([np.cos(angle), np.sin(angle)])
        step = -(start - centre) / np.linalg.norm(start - centre) * rng.uniform(2, 6)
        places = [start + k * step for k in range(PLANT_LEN)]
        if not all(0 <= x < w and 0 <= y < h and mask[int(y), int(x)] for x, y in places):
            continue
        peak = strength * float(noise[int(start[1]), int(start[0])])
        s = 2.5 / 2.355
        for k, (x, y) in enumerate(places):
            i = first + k
            if i >= len(images):
                break
            r = 6
            ys, xs = slice(int(y) - r, int(y) + r + 1), slice(int(x) - r, int(x) + r + 1)
            images[i][ys, xs] += peak * np.exp(-((xx[ys, xs] - x) ** 2 + (yy[ys, xs] - y) ** 2) / (2 * s * s))
        fakes.append({"strength": strength, "at": {first + k: (float(x), float(y)) for k, (x, y) in enumerate(places)
                                                   if first + k < len(images)}})
    return fakes


def recovered(fakes, candidates, within=3.0):
    """For each fake, whether a candidate's track passes through it."""
    out = []
    for f in fakes:
        hit = False
        for c in candidates:
            for i, (x, y) in zip(c["pictures"], c["track"]):
                if i in f["at"] and math.hypot(x - f["at"][i][0], y - f["at"][i][1]) <= within:
                    hit = True
                    break
            if hit:
                break
        out.append(hit)
    return out


def look(camera, hours=None, say=print, paths=None, until=None, raw=False, planted=0):
    """Look through the kept pictures for moving points that are not stars:
    the `hours` before `until`, or before the newest picture kept."""
    if paths is None:
        pattern = "CCOR1_3_*_NC.fits" if camera == "ccor1" else f"*_{camera}.fts" if raw else f"*_{camera}_1024.jpg"
        paths = sorted((folder() / "pictures" / camera).glob(pattern))
        if until:
            paths = [p for p in paths if stamp(p.name) <= until]
        if hours and paths:
            newest = stamp(paths[-1].name)
            paths = [p for p in paths if newest - stamp(p.name) <= datetime.timedelta(hours=hours)]
    if len(paths) < TRACK_LEN + 2:
        raise interface.Refusal("NO_SESSION", f"Too few {camera.upper()} pictures kept ({len(paths)}): "
                                f"./sungrazer.py fetch{' --raw' if raw else ''} first.")
    images = [load(p) for p in paths]
    shape = images[0].shape
    if any(i.shape != shape for i in images):
        keep = [p for p, i in zip(paths, images) if i.shape == shape]
        images = [i for i in images if i.shape == shape]
        paths = keep
    images = fill(images)
    mask = usable(shape, camera, images)
    fakes = plant(images, mask, planted) if planted else None
    found = points(images, mask)
    start = stamp(paths[0].name)
    minutes = [(stamp(p.name) - start).total_seconds() / 60 for p in paths]
    linked = stitch(tracks(found, len(images), minutes=minutes))
    drift = star_drift(linked)
    candidates = judge(linked, drift, shape, camera)
    day = stamp(paths[-1].name).strftime("%Y%m%d-%H%M") + ("-raw" if raw else "")
    out = folder() / day
    out.mkdir(parents=True, exist_ok=True)
    if fakes is not None:
        hits = recovered(fakes, candidates)
        rows = [{"strength": st, "planted": sum(f["strength"] == st for f in fakes),
                 "found": sum(h for f, h in zip(fakes, hits) if f["strength"] == st)} for st in STRENGTHS]
        answer = {"camera": camera, "raw": raw, "pictures": len(paths), "from": paths[0].name, "to": paths[-1].name,
                  "planted": rows, "folder": str(out)}
        records.write(out / "plant.json", answer, schema="sungrazer", stamp=True)
        say(f"{len(fakes)} fake comets planted in {len(paths)} {camera.upper()}{' raw' if raw else ''} pictures:")
        for r in rows:
            say(f"  {r['strength']:>3} times the noise: {r['found']} of {r['planted']} found")
        return answer
    for n, c in enumerate(candidates[:20], 1):
        c["times"] = [stamp(paths[i].name).strftime("%Y-%m-%d %H:%M") for i in c["pictures"]]
        c["files"] = [paths[i].name for i in c["pictures"]]
        c["gaps"] = gaps(c["times"])
        c["sungrazer_xy"] = [list(native(x, y, camera, shape)) for x, y in c["track"]]
        c["movie"] = movie(images, c, out / f"candidate-{n}.gif")
    answer = {"camera": camera, "raw": raw, "pictures": len(paths), "from": paths[0].name, "to": paths[-1].name,
              "points": len(found), "tracks": len(linked),
              "star_drift": None if drift is None else [round(float(v), 2) for v in drift],
              "candidates": candidates[:20], "folder": str(out)}
    records.write(out / "look.json", answer, schema="sungrazer", stamp=True)
    say(f"{len(paths)} pictures, {len(found)} points, {len(linked)} tracks; the stars drift "
        f"{answer['star_drift']} pixels in 12 minutes")
    if not candidates:
        say("No track moves other than as the stars do.")
    for n, c in enumerate(candidates[:20], 1):
        say(f"  {n}. {len(c['pictures'])} pictures from {c['times'][0]}, {c['pixels_per_12_min']} px in 12 min, "
            f"{'towards' if c['towards_sun'] > 0.5 else 'not towards'} the Sun, strength {c['strength']}"
            + (f", one track across {', '.join(c['gaps'])}" if c["gaps"] else "") + f": {c['movie']}")
    if candidates:
        say("Watch each movie. A comet is faint and moves steadily; check the project's recent finds, then "
            "report through sungrazer.nrl.navy.mil/report with your name, the times and its positions.")
    return answer


def prune(camera, days=KEEP_DAYS, now=None):
    """Delete the kept pictures older than `days`. Returns how many."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    gone = 0
    for path in (folder() / "pictures" / camera).glob("*"):
        try:
            old = now - stamp(path.name) > datetime.timedelta(days=days)
        except (AttributeError, ValueError):
            continue
        if old:
            path.unlink()
            gone += 1
    return gone


def report_text(c, camera):
    """What the Sungrazer Project's report form asks, filled from a
    candidate: the camera, and each picture's time with the point's place in
    it, as the project measures it (`native`: pixels from the top left of
    the full frame), and how it stands against the project's own reports."""
    instrument = {"c3": "LASCO C3", "c2": "LASCO C2", "ccor1": "GOES-19 CCOR-1"}.get(camera, camera)
    lines = [f"Instrument: {instrument}", f"Motion: {c['pixels_per_12_min']} pixels in 12 minutes, "
             f"{'towards' if c['towards_sun'] > 0.5 else 'not towards'} the Sun"
             + (f"; one track across the gap {', '.join(c['gaps'])}" if c.get("gaps") else "")]
    match = c.get("public")
    if match:
        lines.append("Public reports: " + match["state"]
                     + (f" ({match['report']}, {match['who']}, {match['type']})" if match.get("report") else ""))
    lines.append("Positions (UTC, x, y from the top left of the full frame):")
    for t, f, (x, y) in zip(c.get("times", []), c.get("files", []), c.get("sungrazer_xy") or c["track"]):
        lines.append(f"  {t}  {x:.1f}  {y:.1f}  ({f})")
    return "\n".join(lines)


BODY_NEAR = 10.0     # pixels: a track this near a planet or bright star at its first and last pictures is that
TOLD_DAYS = 4        # days a candidate already sent is remembered, so the next hunts do not send it again
BRIGHT_STARS = {     # stars bright enough to leave a track near the Sun (RA, Dec in degrees, J2000)
    "Spica": (201.298, -11.161), "Regulus": (152.093, 11.967), "Antares": (247.352, -26.432),
    "Aldebaran": (68.980, 16.509), "Pollux": (116.329, 28.026), "Castor": (113.650, 31.888),
    "Elnath": (81.573, 28.608), "Nunki": (283.816, -26.297), "Zubenelgenubi": (222.720, -16.042),
    "Deneb Algedi": (326.760, -16.127), "Alcyone": (56.871, 24.105), "Sabik": (257.595, -15.725)}


def solar_p(t):
    """The position angle of the Sun's north pole from celestial north, in
    degrees (Meeus, chapter 29): CCOR-1's sky is measured from solar north."""
    jd = t.jd
    T = (jd - 2451545.0) / 36525
    K = 73.6667 + 1.3958333 * (jd - 2396758) / 36525
    L = (280.46646 + 36000.76983 * T) % 360
    M = math.radians(357.52911 + 35999.05029 * T)
    C = (1.914602 - 0.004817 * T) * math.sin(M) + 0.019993 * math.sin(2 * M)
    omega = math.radians(125.04 - 1934.136 * T)
    lam = L + C - 0.00569 - 0.00478 * math.sin(omega)
    eps = 23.4392911 - 0.0130042 * T + 0.00256 * math.cos(omega)
    x = math.degrees(math.atan(-math.cos(math.radians(lam)) * math.tan(math.radians(eps))))
    y = math.degrees(math.atan(-math.cos(math.radians(lam - K)) * math.tan(math.radians(7.25))))
    return x + y


def where_bodies(path):
    """Where each planet and bright star is in a CCOR-1 picture: {name:
    (x, y)} in its pixels. Checked on 19 October 2026: Spica, predicted at
    779, 380, was the brightest point within 4 pixels."""
    import warnings
    from astropy.coordinates import SkyCoord, get_body
    from astropy.io import fits
    from astropy.time import Time
    from astropy.wcs import WCS
    import astropy.units as u
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with fits.open(path) as f:
            head = next(h for h in f if h.data is not None).header
        wcs, t = WCS(head), Time(head["DATE-OBS"])
        sun, tilt = get_body("sun", t), solar_p(Time(head["DATE-OBS"]))
        bodies = {name.title(): get_body(name, t) for name in
                  ("mercury", "venus", "mars", "jupiter", "saturn", "uranus", "neptune")}
        bodies.update({name: SkyCoord(ra * u.deg, dec * u.deg) for name, (ra, dec) in BRIGHT_STARS.items()})
        out = {}
        for name, body in bodies.items():
            sep = float(sun.separation(body).deg)
            if sep > 8:
                continue
            pa = math.radians(float(sun.position_angle(body).deg) - tilt)
            x, y = wcs.wcs_world2pix([[-sep * math.sin(pa), sep * math.cos(pa)]], 0)[0]
            out[name] = (float(x), float(y))
    return out


def body_on(c, camera):
    """The planet or bright star a CCOR-1 track lies on, at its first and
    last pictures; None for none, or for a camera whose pictures carry no
    sky coordinates."""
    if camera != "ccor1" or not c.get("files"):
        return None
    ends = []
    for k in (0, -1):
        path = folder() / "pictures" / camera / c["files"][k]
        if not path.exists():
            return None
        try:
            ends.append(where_bodies(path))
        except Exception:      # an unreadable picture: no answer, never a stopped hunt
            return None
    for name in ends[0]:
        if name in ends[1] and all(math.dist(e[name], c["track"][k]) <= BODY_NEAR for e, k in zip(ends, (0, -1))):
            return name
    return None


def verdict(c, camera):
    """What a candidate turned out to be, from the checks: {"kind", "words"}."""
    body = c.get("body")
    if body:
        kind = "star" if body in BRIGHT_STARS else "planet"
        return {"kind": kind, "words": f"not a comet: it is the {'star' if kind == 'star' else 'planet'} {body}"}
    match = c.get("public") or {}
    state = match.get("state", "public reports not checked")
    who = f"{match.get('report')}, {match.get('who')}" if match.get("report") else ""
    group = f" {match['group']}" if match.get("group") else ""
    if state == "known comet":
        return {"kind": "known comet", "words": f"a comet, but already known: a{group} comet in the "
                                                f"Sungrazer Project's reports ({who}, \"{match.get('type')}\")"}
    if state == "possible public match":
        return {"kind": "reported", "words": f"a comet someone has already reported, not yet confirmed: "
                                             f"{who}, \"{match.get('type')}\"{group}"}
    if state == "no matching public report found":
        return {"kind": "unexplained", "words": "nothing explains it: no planet or bright star, and no report "
                                                "of it in the project's list. It could be new"}
    return {"kind": "not checked", "words": "the project's reports could not be read: not checked yet"}


def headline(towards, rim):
    """The checked hunt in one line: what each track turned out to be."""
    def count(n, one, many):
        return f"{n} {one if n == 1 else many}"
    kinds = [(c.get("verdict") or verdict(c, None))["kind"] for c in towards]
    parts = []
    for kind, one, many in (("known comet", "known comet recovered", "known comets recovered"),
                            ("reported", "track matching someone's report", "tracks matching others' reports"),
                            ("planet", "planet", "planets"), ("star", "bright star", "bright stars"),
                            ("not checked", "not yet checked", "not yet checked")):
        if kinds.count(kind):
            parts.append(count(kinds.count(kind), one, many))
    left = kinds.count("unexplained")
    parts.append(count(left, "unexplained track: possibly new", "unexplained tracks: possibly new")
                 if left else "no unexplained candidates")
    if rim:
        parts.append(count(len(rim), "weak track on the occulter's rim set aside",
                           "weak tracks on the occulter's rim set aside"))
    return "; ".join(parts)


def same(a, b, near=6.0):
    """Whether two candidates are one object: a picture in common, with the
    two points in it within `near` pixels."""
    places = dict(zip(b.get("files", []), b["track"]))
    return any(f in places and math.dist(xy, places[f]) <= near for f, xy in zip(a.get("files", []), a["track"]))


def told(camera, now):
    """The candidates already sent, from the last TOLD_DAYS."""
    try:
        rows = json.loads((folder() / f"told-{camera}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [r for r in rows if now.timestamp() - r.get("told", 0) <= TOLD_DAYS * 86400]


def hunt(camera, hours=HUNT_HOURS, say=print, now=None, get=requests.get, looker=None, send=None):
    """Fetch the last `hours`, look, keep what heads in towards the Sun, and
    tidy away old pictures; tell the person in two messages: first what was
    found, then, once checked against the planets, bright stars and the
    Sungrazer Project's own reports, what each one is. A candidate already
    sent is not sent again; one still unexplained is checked again by each
    later hunt, and the person told if the answer changes. `looker` stands
    in for look (for the tests)."""
    import notify
    send = send or notify.send
    now = now or datetime.datetime.now(datetime.timezone.utc)
    fetch(hours, camera, say, get=get, now=now)
    looker = looker or (lambda: look(camera, hours, say=lambda *_: None, until=now))
    seen = looker()
    heading = [c for c in seen.get("candidates", []) if c["towards_sun"] >= TOWARDS]
    rim = [c for c in heading if c.get("rim") and c["strength"] < RIM_STRENGTH]
    towards = [c for c in heading if c not in rim]
    earlier = told(camera, now)
    new = [c for c in towards if not any(same(c, t) for t in earlier)]
    if new:
        send(f"Comet hunt, {camera.upper()} to {now:%Y-%m-%d %H:%M} UTC: "
             f"{len(new)} possible comet{'s' if len(new) > 1 else ''} heading in towards the Sun. Checking "
             f"{'them' if len(new) > 1 else 'it'} now against the planets, bright stars and the Sungrazer Project's "
             f"reports; the answer follows.",
             animations=[(c["movie"], f"possible comet {n}") for n, c in enumerate(new, 1)], say=say)
    pending = [t for t in earlier if t["verdict"]["kind"] in ("unexplained", "reported", "not checked")]
    reports = None
    if (new or pending) and camera in REPORT_CAMERA:
        try:
            reports = public_reports(camera, get)
        except (requests.RequestException, OSError) as error:
            say(f"The project's public reports could not be read ({error}): not checked")
    for c in new + pending:
        if "body" not in c:
            c["body"] = body_on(c, camera)
        c["public"] = public_match(c, reports) if reports is not None and c.get("sungrazer_xy") \
            else c.get("public") or {"state": "public reports not checked"}
        c["verdict"] = verdict(c, camera)
    for c in towards:
        twin = next((t for t in earlier if same(c, t)), None)
        if twin:
            c["verdict"], c["public"], c["body"] = twin["verdict"], twin.get("public"), twin.get("body")
    answer = {"camera": camera, "pictures": seen["pictures"], "when": now.strftime("%Y-%m-%d %H:%M"),
              "towards_sun": towards, "rim": rim, "moving": len(seen.get("candidates", [])),
              "folder": seen.get("folder"),
              "deleted": prune(camera, KEEP_DAYS, now)}
    records.write(folder() / f"hunt-{camera}.json", answer, schema="sungrazer", stamp=True)
    with (folder() / "hunt.log").open("a", encoding="utf-8") as log:
        log.write(f"{answer['when']} {camera} {answer['pictures']} pictures, {len(towards)} heading for the Sun\n")
    say(f"{answer['pictures']} {camera.upper()} pictures to {answer['when']} UTC: {len(towards)} heading in towards "
        f"the Sun ({len(new)} new), of {answer['moving']} moving other than the stars"
        + (f"; {len(rim)} weak on the occulter's rim set aside" if rim else ""))
    if new:
        lines = [f"Comet hunt checked: {headline(new, rim)}."]
        for n, c in enumerate(new, 1):
            lines.append(f"\n{n}. {c['verdict']['words']}.")
            lines.append(report_text(c, camera))
            if c["verdict"]["kind"] == "unexplained":
                lines.append(f"To report it, tell Claude \"report comet {n}\": it fills the Sungrazer form and you "
                             "press send.")
        send("\n".join(lines), say=say)
    for t in pending:
        before = t.get("said", "")
        if t["verdict"]["words"] != before:
            send(f"Comet hunt update: the possible comet first seen {t['times'][0]} UTC is {t['verdict']['words']}.",
                 say=say)
    stamp = now.timestamp()
    kept = [dict(t, said=t["verdict"]["words"]) for t in earlier]
    kept += [{"files": c.get("files", []), "track": c["track"], "times": c.get("times", []),
              "sungrazer_xy": c.get("sungrazer_xy"), "movie": c.get("movie"), "body": c.get("body"),
              "public": c.get("public"), "verdict": c["verdict"], "said": c["verdict"]["words"], "told": stamp}
             for c in new]
    records.write(folder() / f"told-{camera}.json", kept)
    return answer


def units(camera="ccor1", root=None, python=None, data=None):
    """The systemd user service and timer that run the hunt every 6 hours."""
    root = Path(root or Path(__file__).resolve().parent)
    python = python or sys.executable
    env = f"Environment=TY_DATA={data}\n" if data else ""
    # A checkout kept for the timer alone (its HEAD detached) is brought up
    # to the pushed code before each hunt; a person's own branch is left
    # alone. 20 October 2026: the timer ran three-day-old code, whose alerts
    # left no copy on the laptop, and the agent never heard of the comet.
    follow = (f"ExecStartPre=-/bin/sh -c 'git -C {root} symbolic-ref -q HEAD >/dev/null || "
              f"(git -C {root} fetch -q origin && git -C {root} checkout -q --detach origin/main)'\n")
    service = (f"[Unit]\nDescription=telescopeyoke: comets in {camera.upper()} pictures\n\n"
               f"[Service]\nType=oneshot\nWorkingDirectory={root}\n{env}{follow}"
               f"ExecStart={python} {root / 'sungrazer.py'} hunt --camera {camera}\nNice=19\n")
    timer = ("[Unit]\nDescription=telescopeyoke: the comet hunt every 6 hours\n\n"
             "[Timer]\nOnBootSec=15min\nOnUnitActiveSec=6h\nPersistent=true\n\n"
             "[Install]\nWantedBy=timers.target\n")
    return service, timer


def install(camera="ccor1", say=print, run=subprocess.run, home=None):
    """Write the service and timer, and start the timer."""
    if camera != "ccor1":
        raise interface.Refusal("INVALID_REQUEST", "Only CCOR-1 is hunted all the time: the Sungrazer Project is "
                                "to be asked before LASCO's servers are.")
    place = Path(home or Path.home()) / ".config" / "systemd" / "user"
    place.mkdir(parents=True, exist_ok=True)
    data = os.environ.get("TY_DATA")
    service, timer = units(camera, data=data)
    (place / "ty-sungrazer.service").write_text(service, encoding="utf-8")
    (place / "ty-sungrazer.timer").write_text(timer, encoding="utf-8")
    run(["systemctl", "--user", "daemon-reload"], check=True)
    run(["systemctl", "--user", "enable", "--now", "ty-sungrazer.timer"], check=True)
    say(f"The {camera.upper()} hunt runs every 6 hours ({place / 'ty-sungrazer.timer'}); its answer is "
        f"{folder() / f'hunt-{camera}.json'}. Stop it: systemctl --user disable --now ty-sungrazer.timer")
    return {"camera": camera, "pictures": 0, "installed": str(place / "ty-sungrazer.timer")}


def moment(text):
    """A time given on the command line, taken as UTC."""
    when = datetime.datetime.fromisoformat(text)
    return when if when.tzinfo else when.replace(tzinfo=datetime.timezone.utc)


def run(args, say=print):
    until = moment(args.until) if args.until else None
    args.camera = args.camera or ("ccor1" if args.action == "hunt" else "c3")
    if args.action == "hunt":
        if args.install:
            return install(args.camera, say)
        return hunt(args.camera, args.hours if args.hours != 12.0 else HUNT_HOURS, say, now=until)
    if args.action == "fetch":
        paths = fetch(args.hours, args.camera, say, now=until, raw=args.raw)
        return {"camera": args.camera, "raw": args.raw, "pictures": len(paths),
                "kept": str(folder() / "pictures" / args.camera)}
    return look(args.camera, args.hours, say, until=until, raw=args.raw, planted=args.plant)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", choices=("fetch", "look", "hunt"))
    ap.add_argument("--camera", choices=("c3", "c2", "ccor1"),
                    help="LASCO C3 (wide) or C2 (close in), or GOES-19's CCOR-1 (default: c3; ccor1 for hunt)")
    ap.add_argument("--hours", type=float, default=12.0, help="how far back (default 12)")
    ap.add_argument("--until", help="the end of the time looked at, UTC (YYYY-MM-DDTHH:MM; default now, or "
                    "the newest picture kept)")
    ap.add_argument("--raw", action="store_true", help="the raw FITS pictures, for fainter comets (about 2 MB each)")
    ap.add_argument("--plant", type=int, default=0, metavar="N",
                    help="look: plant N fake comets and count how many are found, instead of listing candidates")
    ap.add_argument("--install", action="store_true", help="hunt: run it every 6 hours as a systemd user timer")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("sungrazer", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
