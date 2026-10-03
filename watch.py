#!/usr/bin/env python3
"""Photograph the telescope with a webcam.

Uses an external USB webcam if one is plugged in, else the laptop's own.

    ./watch.py          save one frame to web/scope.jpg (shown on the web page)

mount.py also uses this to keep the picture fresh while the mount is moving.
Frames are only taken on request or during a slew, never continuously.
"""
import glob
import os
import subprocess
import threading
from pathlib import Path

ROOT = Path(__file__).parent
PICTURE = ROOT / "web" / "scope.jpg"
BUILT_IN = "HP_HD_Camera"


def device():
    cameras = sorted(glob.glob("/dev/v4l/by-id/*-video-index0"))
    external = [c for c in cameras if BUILT_IN not in c]
    return (external or cameras or ["/dev/video0"])[0]


def capture(path=PICTURE):
    """Save one frame; returns True if the camera delivered one."""
    path.parent.mkdir(exist_ok=True)
    partial = path.with_suffix(".part.jpg")
    # Skip the first frames: the camera needs a moment to set its exposure.
    done = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "v4l2",
         "-input_format", "mjpeg", "-video_size", "1280x720", "-i", device(),
         "-frames:v", "30",
         "-update", "1", "-y", str(partial)],
        capture_output=True, timeout=20)
    if done.returncode != 0 or not partial.exists():
        return False
    os.replace(partial, path)  # so the web page never loads a half-written file
    return True


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
