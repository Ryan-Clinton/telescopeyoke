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


def _try_lock(handle):
    """True if this open file now holds the lock, False if another does."""
    if sys.platform == "win32":
        import msvcrt
        try:
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
        if not _try_lock(handle):
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
