#!/usr/bin/env python3
"""Photograph the telescope with a webcam.

On Linux it uses an external USB webcam if one is plugged in, else the
laptop's own. On Windows it uses the one named under [webcam] in config.toml.

    ./watch.py          save one frame to web/scope.jpg (shown on the web page)

mount.py also uses this to keep the picture fresh while the mount is moving.
Frames are only taken on request or during a slew, never continuously.
"""
import subprocess
import threading
from pathlib import Path

import host

import config

ROOT = Path(__file__).parent
PICTURE = config.DATA / "web" / "scope.jpg"


def device():
    return host.webcam_device()


def capture(path=PICTURE):
    """Save one frame; returns True if the camera delivered one."""
    source = host.webcam_input()
    if source is None:
        return False   # no webcam configured
    path.parent.mkdir(exist_ok=True)
    partial = path.with_suffix(".part.jpg")
    # Skip the first frames: the camera needs a moment to set its exposure.
    done = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", *source,
         "-frames:v", "30",
         "-update", "1", "-y", str(partial)],
        capture_output=True, timeout=20, **host.QUIET)
    if done.returncode != 0 or not partial.exists():
        return False
    # So the web page never loads a half-written file.
    return host.replace_preview(partial, path)


class Watching:
    """Keep web/scope.jpg fresh for as long as the with-block runs."""

    def __enter__(self):
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return self

    def _run(self):
        while not self.stop.is_set():
            try:
                capture()
            except (OSError, subprocess.SubprocessError):
                return  # no camera; the slew carries on without pictures
            self.stop.wait(1)

    def __exit__(self, *exc):
        self.stop.set()
        self.thread.join(timeout=25)
        try:
            capture()  # a final frame of where it ended up
        except (OSError, subprocess.SubprocessError):
            pass


if __name__ == "__main__":
    print(f"saved {PICTURE} from {device()}" if capture() else "The webcam gave no picture.")
