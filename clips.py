"""Clips of the stream's big moments, cut from what was sent.

While the stream is on air, ffmpeg also writes what it sends into a rolling
buffer of SEGMENT_S pieces (cache/stream-buffer/, the newest WRAP of them:
ten minutes, overwritten as it goes). For each moment of the night
(cache/events.jsonl, director.event: a target reached, a stage begun, a
result, a decision), once AFTER_S has passed, the pieces from BEFORE_S
before it to AFTER_S after are joined, without encoding again, into
clips/DATE-TIME-WORDS.mp4: material for a highlight, a Short or the next
night's "previously". Moments closer together than AFTER_S share one clip.
The newest KEEP clips are kept.

On by default; [stream] clips = false in config.toml turns it off.
"""
import json
import re
import subprocess
import time
from pathlib import Path

import config

BUFFER = config.DATA / "cache" / "stream-buffer"
CLIPS = config.DATA / "clips"
DONE = config.DATA / "cache" / "clips-done.json"
SEGMENT_S = 10
WRAP = 60                  # pieces kept: ten minutes
BEFORE_S, AFTER_S = 20, 60
KEEP = 40


def output():
    """The tee muxer's entry that writes the rolling buffer (stream.command)."""
    BUFFER.mkdir(parents=True, exist_ok=True)
    return (f"[f=segment:segment_time={SEGMENT_S}:segment_wrap={WRAP}:reset_timestamps=1:"
            f"segment_format=mpegts:onfail=ignore]{BUFFER / 'seg%03d.ts'}")


def slug(words):
    return re.sub(r"[^a-z0-9]+", "-", words.lower()).strip("-")[:40] or "moment"


def _done():
    try:
        found = json.loads(DONE.read_text(encoding="utf-8"))
        return set(found) if isinstance(found, list) else set()
    except (OSError, ValueError):
        return set()


def due(events, now, done=()):
    """The events ready to be cut: AFTER_S past, still in the buffer, not
    yet cut, and not within AFTER_S of an earlier one (that clip has it)."""
    out, last = [], None
    for e in sorted(events, key=lambda e: e["at"]):
        if last is not None and e["at"] - last < AFTER_S:
            continue
        last = e["at"]
        if str(e["at"]) in done:
            continue
        if now - e["at"] >= AFTER_S + SEGMENT_S and now - e["at"] <= WRAP * SEGMENT_S - BEFORE_S:
            out.append(e)
    return out


def pieces(at, buffer=None):
    """The buffer's pieces covering BEFORE_S before `at` to AFTER_S after, oldest first."""
    found = []
    for p in (buffer or BUFFER).glob("seg*.ts"):
        try:
            ended = p.stat().st_mtime
        except OSError:
            continue
        if at - BEFORE_S <= ended and ended - SEGMENT_S <= at + AFTER_S:
            found.append((ended, p))
    return [p for _, p in sorted(found)]


def cut(event, run=subprocess.run, buffer=None, out=None):
    """One clip round `event`, or None if the buffer had nothing for it."""
    parts = pieces(event["at"], buffer)
    if not parts:
        return None
    out = out or CLIPS
    out.mkdir(parents=True, exist_ok=True)
    clip = out / f"{time.strftime('%Y%m%d-%H%M%S', time.localtime(event['at']))}-{slug(event['words'])}.mp4"
    listing = clip.with_suffix(".txt")
    listing.write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
    try:
        done = run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-c", "copy", str(clip)], capture_output=True, timeout=120)
    finally:
        listing.unlink(missing_ok=True)
    return clip if done.returncode == 0 else None


def tidy(out=None, keep=KEEP):
    """Only the newest `keep` clips stay."""
    found = sorted((out or CLIPS).glob("*.mp4"), key=lambda p: p.stat().st_mtime)
    for p in found[:-keep] if keep else found:
        p.unlink(missing_ok=True)


def cut_due(now=None, say=print, run=subprocess.run):
    """Cut every clip that is due (stream.py, on a thread of its own)."""
    import director
    import records
    now = now or time.time()
    done = _done()
    made = []
    for e in due(director.events(now - WRAP * SEGMENT_S), now, done):
        clip = cut(e, run)
        done.add(str(e["at"]))
        if clip:
            made.append(clip)
            say(f"{time.strftime('%H:%M')} clip kept: {Path(clip).name}")
    if made:
        tidy()
    try:
        records.write(DONE, sorted(done)[-500:])
    except OSError:
        pass
    return made
