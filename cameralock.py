"""Only one command at a time may have the camera, and a second is told who.

On 2 November 2026 a dark run that was thought stopped was still holding
the 183C, and the skyline survey started after it could only say the camera
"would not be set up", which looked like the camera's jam. The camera's
library cannot say who has it, so each command that opens it takes this
lock first and writes its process number and command line into it. The
lock is the operating system's, on an open file: it goes when the command
ends however it ends, killed outright included, so it can never be left
behind to block the next one.
"""
import os
import sys

import config
from interface import Refusal

PATH = config.DATA / "cache" / "camera.lock"
_HELD = {}          # path -> [open file, how many CameraLocks of this process share it]


WIN_LOCK_AT = 1 << 20     # the byte locked on Windows; the text is one short line


def _try_lock(handle):
    """True if this open file now holds the lock, False if another does."""
    if sys.platform == "win32":
        import msvcrt
        try:
            # Always the same byte, past the text: Windows locks a byte range, and
            # one at wherever the file then ended let a second command lock its
            # own byte, think it held the camera, and be refused writing its name
            # over the first one's; holder() still reads the text before it.
            handle.seek(WIN_LOCK_AT)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    import fcntl
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True


GIVE_WAY_S = 15      # seconds a live view is given to close the camera when a run wants it


def _live_view_gives_way(handle, path, wait=GIVE_WAY_S):
    """When the camera is held by a live view (liveview.py), which only fills
    time between runs, ask it to stop and take the lock once it has. True
    when the lock is now this command's. 3 November 2026: cloud ended the
    transit at 00:49, its after-run live view kept the camera, and the next
    step failed three times and woke the house: the live view was waiting for
    a run to log a frame, and the run could not open the camera to log one."""
    import signal
    import time
    found = holder(path)
    if not found or "liveview.py" not in found[1] or not _alive(found[0]):
        return False
    try:
        os.kill(found[0], signal.SIGTERM)
    except OSError:
        return False
    end = time.monotonic() + wait
    while time.monotonic() < end:
        if _try_lock(handle):
            print(f"The live view (process {found[0]}) gave the camera up for this command.", flush=True)
            return True
        time.sleep(0.5)
    return False


def holder(path=None):
    """(process number, command line) written by whoever has the camera, or None."""
    try:
        text = (path or PATH).read_text(encoding="utf-8").strip()
        pid, _, command = text.partition(" ")
        return int(pid), command
    except (OSError, ValueError):
        return None


class CameraLock:
    """Held from when a command opens the camera until it has finished with
    it (release(), or the process ending). Closing and opening the camera
    again inside one command keeps it, and so does opening a second
    camera object in the same command: the lock is between commands."""

    def __init__(self, path=None, command=None):
        self.path = path or PATH
        self.held = False
        shared = _HELD.get(self.path)
        if shared:
            shared[1] += 1
            self.held = True
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+", encoding="utf-8")
        if not _try_lock(handle) and not _live_view_gives_way(handle, self.path):
            handle.close()
            found = holder(self.path)
            who = (f"process {found[0]} ({found[1]})" if found and _alive(found[0])
                   else "another command")
            raise Refusal("CAMERA_BUSY",
                          f"The camera is in use by {who}. Only one command can have it: "
                          "let that one finish, or stop it, then try again.")
        handle.seek(0)
        handle.truncate()
        handle.write(f"{os.getpid()} {command or ' '.join(sys.argv)}\n")
        handle.flush()
        _HELD[self.path] = [handle, 1]
        self.held = True

    def release(self):
        if not self.held:
            return
        self.held = False
        shared = _HELD[self.path]
        shared[1] -= 1
        if shared[1] == 0:
            handle = _HELD.pop(self.path)[0]
            try:
                handle.seek(0)
                handle.truncate()
            except OSError:
                pass
            handle.close()      # closing the file is what lets the lock go
