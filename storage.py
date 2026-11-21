#!/usr/bin/env python3
"""Room on the laptop's disk: finished raw files moved to the storage disk.

    ./storage.py                 free space here and on the storage disk
    ./storage.py --tidy          move finished Moon videos and old raw frames there now
    ./storage.py --tidy --dry-run   what would be moved
    ./storage.py --processed     the same for sessions already stacked, unless
                                 the camera or mount is in use
    ./storage.py --processed --install   do that every hour (a systemd user timer)

Raw frames are already Rice-compressed by shoot.py, which is lossless: about
15 MB of a 40 MB frame, and gzip on top saves nothing (21 November 2026).

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
import fcntl
import os
import shutil
import subprocess
import sys
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


def digest(path):
    """The file's SHA-256, read in pieces."""
    import hashlib
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            sha.update(block)
    return sha.hexdigest()


def move(path, store, data=None):
    """Move one file to the same place under `store`, leaving a link where
    it was. Returns the new path, or None if it was already moved."""
    path, data = Path(path), Path(data or config.DATA)
    if path.is_symlink() or not path.is_file():
        return None
    target = Path(store).expanduser().resolve() / path.resolve().relative_to(data.resolve())   # absolute: the link works from anywhere
    target.parent.mkdir(parents=True, exist_ok=True)
    # Copied whole under another name and checked, renamed into place, the
    # link made beside the original and swapped in for it: at every moment
    # the frame is at its own path, the original or the link to a whole copy.
    partial = target.with_name(f".{target.name}.partial")
    shutil.copy2(str(path), str(partial))
    with open(partial, "rb") as written:
        os.fsync(written.fileno())          # on the disk before the original goes
    if digest(partial) != digest(path):
        partial.unlink(missing_ok=True)
        raise OSError(f"the copy of {path.name} on the storage disk does not match it; the original stays")
    partial.replace(target)
    link = path.with_name(f".{path.name}.link")
    link.unlink(missing_ok=True)
    link.symlink_to(target)
    link.replace(path)              # the original's name now the link; its data on the storage disk
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


def finished_frames(data=None, now=None, stacked=False):
    """Raw frames of sessions nothing has been written in for
    SESSION_SETTLED_S, as {session folder: [light frames]}; with `stacked`,
    only sessions that have their stacked picture."""
    frames = Path(data or config.DATA) / "frames"
    now = time.time() if now is None else now
    out = {}
    for session in sorted(p for p in frames.glob("*/*") if p.is_dir() and p.parent.name != "lucky"):
        lights = [f for f in sorted(session.glob("light-*.fits")) if not f.is_symlink()]
        if not lights or (stacked and not (session / "final.fits").exists()):
            continue
        newest = max(f.stat().st_mtime for f in session.iterdir() if not f.is_symlink())
        if now - newest >= SESSION_SETTLED_S:
            out[session] = lights
    return out


def tidy(store=None, data=None, say=print, dry_run=False, now=None, stacked=False):
    """Every finished Moon video and old session's raw frames moved to the
    storage disk (with `stacked`, only sessions with their picture made).
    Returns bytes moved. One tidy at a time: the hourly timer and a schedule
    step could otherwise copy the same file at once."""
    store = archive() if store is None else store
    if not store:
        say("no storage disk set ([storage] archive in config.toml): nothing moved")
        return 0
    if not Path(store).exists() and not dry_run:
        Path(store).mkdir(parents=True, exist_ok=True)
    lock_path = Path(data or config.DATA) / "cache" / "storage-tidy.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            say("another tidy is running: nothing moved by this one")
            return 0
        return _tidy(store, data, say, dry_run, now, stacked)


def processed(say=print):
    """Stacked sessions moved to the storage disk, when it is there and
    nothing is using the camera or mount. An unmounted disk is left alone:
    making its folder would put the archive on the laptop."""
    import keeper
    import schedule
    store = archive()
    if not store or not store.exists():
        say(f"storage disk {store or '(none set)'} is not there: nothing moved")
        return 0
    if schedule.busy() or keeper.SOCKET.exists():     # the keeper holds the camera from setup to the night's end
        say("the camera or mount is in use: nothing moved")
        return 0
    return tidy(store, say=say, stacked=True)


def install(say=print):
    """processed() every hour, as a systemd user timer."""
    place = Path.home() / ".config" / "systemd" / "user"
    place.mkdir(parents=True, exist_ok=True)
    (place / "ty-archive.service").write_text(
        "[Unit]\nDescription=TelescopeYoke: stacked sessions' raw frames to the storage disk\n\n"
        f"[Service]\nType=oneshot\nWorkingDirectory={config.ROOT}\n"
        f"ExecStart={sys.executable} {config.ROOT / 'storage.py'} --processed\nNice=15\nIOSchedulingClass=idle\n",
        encoding="utf-8")
    (place / "ty-archive.timer").write_text(
        "[Unit]\nDescription=TelescopeYoke: archive stacked sessions every hour\n\n"
        "[Timer]\nOnBootSec=15min\nOnUnitActiveSec=1h\n\n[Install]\nWantedBy=timers.target\n",
        encoding="utf-8")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", "ty-archive.timer"], check=True)
    say("Stacked sessions are archived every hour. Stop it: systemctl --user disable --now ty-archive.timer")


def _tidy(store, data, say, dry_run, now, stacked):
    """tidy()'s moves, with its lock held."""
    moved = 0
    for video in finished_videos(data, now):
        size = video.stat().st_size
        if not dry_run:
            move(video, store, data)
        moved += size
        say(f"{'would move' if dry_run else 'moved'} {video.name} ({size / 1e9:.1f} GB)")
    for session, lights in finished_frames(data, now, stacked).items():
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
    ap.add_argument("--processed", action="store_true",
                    help="move sessions already stacked, unless the camera or mount is in use")
    ap.add_argument("--install", action="store_true", help="with --processed: do it every hour (a systemd user timer)")
    args = ap.parse_args(argv)
    if args.processed and args.install:
        return install()
    if args.processed and not args.dry_run:
        return processed()
    store = archive()
    print(f"laptop: {free() / 1e9:.0f} GB free"
          + (f"; storage disk {store}: {free(store) / 1e9:.0f} GB free" if store else "; no storage disk set"))
    if args.tidy or args.processed:
        tidy(store, dry_run=args.dry_run, stacked=args.processed)


if __name__ == "__main__":
    main()
