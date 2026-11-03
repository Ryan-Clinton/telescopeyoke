#!/usr/bin/env python3
"""Room on the laptop's disk: finished raw files moved to the storage disk.

    ./storage.py                 free space here and on the storage disk
    ./storage.py --tidy          move finished Moon videos and old raw frames there now
    ./storage.py --tidy --dry-run   what would be moved

A Moon video is 0.3 to 12 GB and is finished once its picture is stacked.
Moved, it keeps its path here as a link, so nothing that reads it changes.
The storage disk is [storage] archive in config.toml; with none set,
nothing is moved. 2 November 2026: a 12 GB video filled the laptop's disk
at 06:12 and the Moon time-lapse stopped at its third picture; the same
had been moved by hand on 30 October.

A night's raw frames (light-*.fits, 16 MB each) are moved once nothing
has been written in their session for SESSION_SETTLED_S; the stacked
picture and the session's records stay here. 2 November 2026: a five-hour
transit at 4 s needs about 50 GB, with 15 GB free and 115 GB of old
frames on the laptop.
"""
import argparse
import shutil
import time
from pathlib import Path

import config

LOW = 20e9          # bytes free below which a schedule step is warned of, and tidying starts
SETTLED_S = 600     # a video untouched this long is not being written
SESSION_SETTLED_S = 12 * 3600   # a session with nothing written this long is finished


def archive(settings=None):
    """The storage disk's folder for this data, or None when none is set."""
    if settings is None:
        settings = config.load() if config.FILE.exists() and not config.DEMO else config.example()
    folder = (settings.get("storage") or {}).get("archive")
    return Path(folder).expanduser() if folder else None


def free(path=None):
    """Bytes free on the disk holding `path` (the data folder by default)."""
    path = Path(path or config.DATA)
    while not path.exists():
        path = path.parent
    return shutil.disk_usage(path).free


def move(path, store, data=None):
    """Move one file to the same place under `store`, leaving a link where
    it was. Returns the new path, or None if it was already moved."""
    path, data = Path(path), Path(data or config.DATA)
    if path.is_symlink() or not path.is_file():
        return None
    target = Path(store) / path.resolve().relative_to(data.resolve())
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(target))
    path.symlink_to(target)
    return target


def finished_videos(data=None, now=None):
    """Moon videos with their picture made and no longer being written."""
    lucky = Path(data or config.DATA) / "frames" / "lucky"
    now = time.time() if now is None else now
    out = []
    for video in sorted(lucky.glob("*.ser")):
        if video.is_symlink() or now - video.stat().st_mtime < SETTLED_S:
            continue
        if any(lucky.glob(video.stem + ".best*.fits")):
            out.append(video)
    return out


def finished_frames(data=None, now=None):
    """Raw frames of sessions nothing has been written in for
    SESSION_SETTLED_S, as {session folder: [light frames]}."""
    frames = Path(data or config.DATA) / "frames"
    now = time.time() if now is None else now
    out = {}
    for session in sorted(p for p in frames.glob("*/*") if p.is_dir() and p.parent.name != "lucky"):
        lights = [f for f in sorted(session.glob("light-*.fits")) if not f.is_symlink()]
        if not lights:
            continue
        newest = max(f.stat().st_mtime for f in session.iterdir() if not f.is_symlink())
        if now - newest >= SESSION_SETTLED_S:
            out[session] = lights
    return out


def tidy(store=None, data=None, say=print, dry_run=False, now=None):
    """Every finished Moon video and old session's raw frames moved to the
    storage disk. Returns bytes moved."""
    store = archive() if store is None else store
    if not store:
        say("no storage disk set ([storage] archive in config.toml): nothing moved")
        return 0
    if not Path(store).exists() and not dry_run:
        Path(store).mkdir(parents=True, exist_ok=True)
    moved = 0
    for video in finished_videos(data, now):
        size = video.stat().st_size
        if not dry_run:
            move(video, store, data)
        moved += size
        say(f"{'would move' if dry_run else 'moved'} {video.name} ({size / 1e9:.1f} GB)")
    for session, lights in finished_frames(data, now).items():
        size = sum(f.stat().st_size for f in lights)
        if not dry_run:
            for f in lights:
                move(f, store, data)
        moved += size
        say(f"{'would move' if dry_run else 'moved'} {session.parent.name}/{session.name}: "
            f"{len(lights)} frames ({size / 1e9:.1f} GB)")
    return moved


def words(data=None, low=LOW):
    """A warning when the data disk is low, else None."""
    room = free(data)
    if room >= low:
        return None
    return f"only {room / 1e9:.0f} GB free on the laptop's disk: a Moon video can take 12 GB"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tidy", action="store_true", help="move finished Moon videos and old raw frames to the storage disk")
    ap.add_argument("--dry-run", action="store_true", help="say what would be moved")
    args = ap.parse_args(argv)
    store = archive()
    print(f"laptop: {free() / 1e9:.0f} GB free"
          + (f"; storage disk {store}: {free(store) / 1e9:.0f} GB free" if store else "; no storage disk set"))
    if args.tidy:
        tidy(store, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
