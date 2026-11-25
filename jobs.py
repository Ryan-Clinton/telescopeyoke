#!/usr/bin/env python3
"""Every long job's record, its queue, and the progress report (docs/job-reporting-spec.md).

    ./ty bg NAME [--after JOB[:released|:MILESTONE]] [--needs camera,mount,cpu,gpu]
                 [--kind finite|service|routine] [--why WORDS] [--wait] -- COMMAND ...
                                 start COMMAND as a job, now or once what it waits for is done
    ./ty jobs                    the progress report: what needs the agent, what runs, what waits,
                                 what is queued, the computer, the camera and the mount
    ./ty jobs NAME --tail 20     one job's last lines
    ./ty jobs --watch            one line for each event that needs the agent, nothing else
    ./ty jobs --ack EVENT WORDS  what was done about an event ("all" for every open one)
    ./ty jobs --busy-until 08:00 WORDS   the owner asked for work until then: an idle event when none runs
    ./ty jobs --stop JOB         end a job as a kill would (its own warm-up and tidying run)

A job is one run of a command, kept in cache/jobs/ID/: process.json (the
launcher's alone), progress.json and heartbeat (the job's own), events.jsonl
(the job's own), log.txt (what it printed, as it printed it). The reader
decides from those whether it is queued, running, waiting, done, failed,
stalled or vanished. In code: `with activity.job("darktest", steps=[...]) as job:`.

24 November 2026: the colder dark test's log was empty for 30 minutes (its
output held back), and when its darks were done at 03:18 nothing said so
until it exited at 07:28; the Moon video meant to follow never started.
Moves nothing itself: a queued command keeps every protection of its own.
"""
import argparse
import atexit
import contextlib
import json
import os
import secrets
import signal
import shutil
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

import config
import host
import records

HEARTBEAT_S = 30            # how often a job's heartbeat file is touched
NOT_RESPONDING_S = 180      # a heartbeat this old in a live process: hung (a library call holding it)
QUIET_S = 600               # no output or progress for this long, with no deadline given: stalled
DEADLINE_MARGIN = (1.2, 60)  # a deadline is overrun past deadline x 1.2 + 60 s
QUEUE_EVERY_S = 5           # a queued job looks this often whether it can start
KEEP_DAYS = {"routine": 2}  # a finished job's folder is kept this long (30 days otherwise)
LOG_CAP_MB, LOG_CAP_LOW_MB, LOW_DISK_GB = 20, 2, 5
IDLE_AFTER_S = 120          # nothing running for this long, while busy-until stands: idle
REOPEN_S = 1800             # an acked waiting, stall or idle still there this long after: open again,
                            # then after twice as long each time (30, 60, 120 min...)
EXCLUSIVE = ("camera", "mount", "gpu")


def exclusive():
    return EXCLUSIVE
KINDS = ("finite", "service", "routine", "remote")
NEEDS = ("camera", "mount", "cpu", "gpu")
CURRENT = None              # this process's job, once it has one
SCHEMA = 1                  # the shape of the records; readers accept older ones
# The generic core this carries: Ryan-Clinton/common's jobs/jobs.py is its
# authoritative copy for every other project (private); a fix there is
# carried here, and this names the revision (docs/job-reporting-spec.md).
CORE = "2026-11-25.2"


def home():
    return Path(config.DATA) / "cache" / "jobs"


def folder(job_id):
    return home() / job_id


def new_id(name):
    clean = "".join(c if c.isalnum() or c in "-_" else "-" for c in name)[:40] or "job"
    return f"{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}-{clean}-{secrets.token_hex(3)}"


def started_at(pid):
    """The process's start time as the system counts it (Linux's /proc,
    Windows' process times), so a process number given to another process
    since is not taken for this one."""
    if host.WINDOWS:
        try:
            import ctypes
            kernel = ctypes.windll.kernel32
            handle = kernel.OpenProcess(0x1000, False, int(pid))     # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return None
            try:
                times = [ctypes.c_ulonglong() for _ in range(4)]
                if kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
                    return str(times[0].value)
            finally:
                kernel.CloseHandle(handle)
        except Exception:
            return None
        return None
    try:
        return Path(f"/proc/{int(pid)}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, ValueError, IndexError):
        return None


def boot_id():
    """This boot of the computer: Linux's boot ID; on Windows the boot time
    to the minute, from how long it has been up."""
    if host.WINDOWS:
        try:
            import ctypes
            up = ctypes.windll.kernel32.GetTickCount64() / 1000
            return f"boot-{int((time.time() - up) // 60)}"
        except Exception:
            return None
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return None


def running(pid, start=None, boot=None):
    """Whether the process recorded (its number, start time and the boot it
    ran in) is the one running now."""
    if boot and boot_id() and boot != boot_id():
        return False            # recorded before the computer restarted
    if not pid or not host.alive(pid):
        return False
    try:
        if Path(f"/proc/{int(pid)}/stat").read_text().rsplit(")", 1)[1].startswith(" Z"):
            return False        # ended, not yet reaped
    except (OSError, ValueError):
        pass
    return start is None or started_at(pid) in (None, start)


def session():
    """The Claude Code session this process works for (the agent's own
    commands carry it, and their children inherit it), or None: a person at
    a terminal, a timer, the console."""
    return os.environ.get("CLAUDE_CODE_SESSION_ID") or None


def mine(j, sid, strict=False):
    """Whether a job is this session's to answer for: its own, and (unless
    strict) the house's, which no session started. With no session (a
    person at a terminal) every job is."""
    if sid is None:
        return True
    owner = j.get("session")
    return owner == sid or (not strict and owner is None)


# ---------------------------------------------------------------- this computer's reservations
# The reservation protocol (version 1), the same in common's jobs.py and
# telescopeyoke's, so every project on a computer, in WSL or native Windows,
# sees what the others hold. The register is a folder: held/JOB.json, one a
# job, written under one lock (a folder made with mkdir, which is atomic on
# Linux, WSL's view of C: and Windows alike, broken when older than
# LOCK_STALE_S). A reservation is alive while its launcher's process is,
# judged by its number, start time and boot on the same system, and by its
# heartbeat (`beat`, every RESERVE_BEAT_S) from the other one: neither system
# can see the other's processes.
REGISTER = 1
RESERVE_BEAT_S = 30
RESERVE_DEAD_S = 120         # a reservation not beaten for this long, from the other system: gone
LOCK_STALE_S = 120


def _system():
    return "windows" if host.WINDOWS else "linux"


def machine():
    """This computer's register, shared by every project on it and, on the
    PC, by WSL and native Windows: JOBS_MACHINE; else, in WSL, the Windows
    user's .local/state/common-jobs (through /mnt/c), so both systems use
    the one; else ~/.local/state/common-jobs."""
    given = os.environ.get("JOBS_MACHINE")
    if given:
        return Path(given)
    if os.environ.get("WSL_DISTRO_NAME"):
        windows = _windows_home()
        if windows:
            return windows / ".local" / "state" / "common-jobs"
    state = os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
    return Path(state) / "common-jobs"


def _windows_home():
    """The Windows user's folder as WSL sees it (/mnt/c/Users/NAME), asked
    of Windows once and kept."""
    kept = Path.home() / ".local" / "state" / "common-jobs-windows-home"
    try:
        found = Path(kept.read_text().strip())
        if found.is_dir():
            return found
    except OSError:
        pass
    try:
        win = subprocess.run(["cmd.exe", "/c", "echo %USERPROFILE%"], capture_output=True, text=True,
                             timeout=10, cwd="/mnt/c").stdout.strip()
        unix = subprocess.run(["wslpath", "-u", win], capture_output=True, text=True, timeout=5).stdout.strip()
        if unix and Path(unix).is_dir():
            kept.parent.mkdir(parents=True, exist_ok=True)
            kept.write_text(unix)
            return Path(unix)
    except (OSError, subprocess.SubprocessError):
        pass
    return None


@contextlib.contextmanager
def machine_lock(wait_s=60):
    """The register's lock, the same for WSL and Windows: a folder made with
    mkdir. One left by a process that died is broken after LOCK_STALE_S."""
    lock = machine() / "lock.d"
    lock.parent.mkdir(parents=True, exist_ok=True)
    until = time.time() + wait_s
    while True:
        try:
            os.mkdir(lock)
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > LOCK_STALE_S:
                    os.rmdir(lock)
                    continue
            except OSError:
                pass
            if time.time() > until:
                raise TimeoutError(f"this computer's job register is locked ({lock})") from None
            time.sleep(0.2)
    try:
        yield
    finally:
        try:
            os.rmdir(lock)
        except OSError:
            pass


def _held_file(job_id):
    return machine() / "held" / f"{job_id}.json"


def reserve(job_id, name, held, pid):
    """This job's exclusive needs in the register, before it starts. Raises
    OSError when it cannot be kept: the job must not start then."""
    if not held:
        return
    records.write(_held_file(job_id),
                  {"register": REGISTER, "job": job_id, "name": name, "project": project_name(),
                   "resources": list(held), "system": _system(), "host": _hostname(), "pid": pid,
                   "pid_start": started_at(pid), "boot": boot_id(), "session": session(),
                   "at": time.time(), "beat": time.time()}, indent=None)


def _held_change(job_id, how):
    """Change a job's reservation under the register's lock (its launcher
    beats it, the job itself may release part of it)."""
    try:
        with machine_lock():
            f = _held_file(job_id)
            r = _read(f)
            if not r:
                return
            how(r)
            if r.get("resources"):
                records.write(f, r, indent=None)
            else:
                f.unlink()
    except (OSError, TimeoutError):
        pass


def beat_reservation(job_id):
    _held_change(job_id, lambda r: r.update(beat=time.time()))


def release_reservation(job_id, what):
    _held_change(job_id, lambda r: r.update(resources=[x for x in r.get("resources", []) if x not in what]))


def unreserve(job_id):
    try:
        with machine_lock():
            _held_file(job_id).unlink()
    except (OSError, TimeoutError):
        pass


def _reservation_alive(r, now):
    if r.get("system") == _system() and r.get("host") == _hostname():
        return running(r.get("pid"), r.get("pid_start"), r.get("boot"))
    return now - (r.get("beat") or 0) < RESERVE_DEAD_S


def machine_holds(now=None):
    """{resource: who} from the register, every project's on this computer
    (WSL's and Windows' alike); a reservation found dead is cleared."""
    now = now or time.time()
    held = {}
    try:
        entries = list((machine() / "held").glob("*.json"))
    except OSError:
        return held
    for f in entries:
        r = _read(f, {}) or {}
        if not _reservation_alive(r, now):
            try:
                f.unlink()
            except OSError:
                pass
            continue
        for resource in r.get("resources") or []:
            held.setdefault(resource, f"{r.get('project')}'s job {r.get('name')} ({r.get('system')})")
    return held


def project_name():
    return "telescopeyoke"


def redact(words):
    try:
        import agentlog
        return agentlog.redact(words)
    except Exception:
        return "(not shown)"


def _read(path, empty=None):
    try:
        return records.read(path, empty)
    except (OSError, ValueError):
        return empty


def _lines(path):
    out = []
    try:
        for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    except OSError:
        pass
    return out


def _mtime(path):
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return None


def _append(path, row):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


# ---------------------------------------------------------------- the job's own side

class Job:
    """One job, from inside the process doing it. Every method is safe to
    call from the main thread; none raises (a record lost is never the
    work's failure)."""

    def __init__(self, name, steps=None, expect_s=None, kind="finite", lazy_s=None):
        launcher = os.environ.get("TY_JOB_ADOPT")
        adopt = launcher and launcher == str(os.getppid()) and os.environ.get("TY_JOB")
        os.environ.pop("TY_JOB_ADOPT", None)
        self.parent = None if adopt else os.environ.get("TY_JOB")
        self.id = adopt or new_id(name)
        self.launched = bool(adopt)
        self.dir = folder(self.id)
        self.name, self.kind = name, kind if kind in KINDS else "finite"
        self.count = len(_lines(self.dir / "events.jsonl"))
        self._lock = threading.Lock()
        now = time.time()
        steps = [str(s) for s in steps] if steps else None
        self.progress = {"name": name, "kind": self.kind if kind != "finite" else None, "steps": steps, "step": None, "of": len(steps) if steps else None,
                         "text": "", "operation": None, "deadline_s": None, "operation_since": None,
                         "waiting": None, "holds": [], "reading": None, "result": None,
                         "last_progress": now, "last_output": now, "started": now,
                         "expect_end": now + expect_s if expect_s else None}
        self._beating = None
        self._ended = False
        # lazy_s: kept only once it has run this long, so a quick look run by
        # hand leaves no record and no event (a launched job is always kept).
        self._shown = not (lazy_s and not adopt)
        self._lazy_s = lazy_s or 0
        self._buffered = []

    # -- starting and ending
    def __enter__(self):
        global CURRENT
        try:
            for stream in (sys.stdout, sys.stderr):
                if hasattr(stream, "reconfigure"):
                    stream.reconfigure(line_buffering=True)
            os.environ["TY_JOB"] = self.id          # what this starts is this job's child
            if self._shown:
                self._show(first=True)
            self._beating = threading.Thread(target=self._heart, daemon=True)
            self._beating.start()
            atexit.register(self._at_exit)
        except Exception:
            pass
        CURRENT = self
        return self

    def __exit__(self, kind, error, tb):
        global CURRENT
        if kind is None or (kind is SystemExit and error.code in (None, 0)):
            self._end(0, self.progress.get("result") or "done")
        elif kind is SystemExit and isinstance(error.code, str):
            self._end(1, f"failed: {error.code}")
        elif kind is KeyboardInterrupt:
            self._end(130, "stopped by hand")
        else:
            last = "".join(traceback.format_exception_only(kind, error)).strip().splitlines()
            self._end(1, f"failed: {last[-1] if last else kind.__name__}")
        CURRENT = None
        return False

    def _at_exit(self):
        self._end(0, self.progress.get("result") or "done")

    def _show(self, first=False):
        """Write the job's record for the first time (at once, or once a
        lazy job has run long enough)."""
        with self._lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            if not self.launched:
                self._process(phase="running", exit_code=None)
            self._shown = True
            for row in self._buffered:
                _append(self.dir / "events.jsonl", row)
            self._buffered = []
        self._save()
        self._beat()

    def _end(self, code, result):
        if self._ended:
            return
        self._ended = True
        if not self._shown:
            return              # a quick run: nothing was kept, nothing to end
        self.progress["result"] = result
        self.progress["waiting"] = None
        self.progress["holds"] = []
        self._save()
        if not self.launched:
            self._process(phase="exited", exit_code=code, ended=time.time())

    def _process(self, **fields):
        # Only a job no launcher started writes its own process record.
        record = _read(self.dir / "process.json", {}) or {}
        if not record:
            record = {"id": self.id, "name": self.name, "kind": self.kind, "own": True,
                      "command": redact(" ".join(sys.argv)), "host": _hostname(), "pid": os.getpid(),
                      "pid_start": started_at(os.getpid()), "boot": boot_id(), "parent": self.parent,
                      "after": [], "needs": [], "why": None, "queued": None, "started": time.time(),
                      "session": session(), "schema": SCHEMA, "core": CORE}
        record.update(fields)
        try:
            records.write(self.dir / "process.json", record, indent=None)
        except Exception:
            pass

    def _heart(self):
        while not self._ended:
            if not self._shown and time.time() - self.progress["started"] >= self._lazy_s:
                try:
                    self._show()
                except Exception:
                    pass
            self._beat()
            time.sleep(HEARTBEAT_S if self._shown else min(HEARTBEAT_S, max(1, self._lazy_s / 4)))

    def _beat(self):
        if not self._shown:
            return
        try:
            (self.dir / "heartbeat").touch()
        except OSError:
            pass

    def _save(self):
        if not self._shown:
            return
        try:
            with self._lock:
                records.write(self.dir / "progress.json", self.progress, indent=None)
        except Exception:
            pass

    def _event(self, kind, words, wake=False, **extra):
        try:
            with self._lock:
                self.count += 1
                row = {"id": f"{self.id}:{self.count}", "job": self.id, "kind": kind, "words": str(words),
                       "wake": wake, "at": time.time(), **extra}
                if self._shown:
                    _append(self.dir / "events.jsonl", row)
                else:
                    self._buffered.append(row)
        except Exception:
            pass

    def _progressed(self):
        self.progress["last_progress"] = self.progress["last_output"] = time.time()

    # -- what the job says
    def say(self, line):
        """A line for the log only."""
        print(line, flush=True)
        self.progress["last_output"] = time.time()

    def step(self, k, text=""):
        """Step k of the job's steps (1 = the first)."""
        self.progress.update(step=k, text=str(text))
        self._progressed()
        self._save()

    def expect(self, seconds, operation):
        """What it is doing now and the longest that should take: past it
        (with a margin) and nothing done, the job has stalled."""
        self.progress.update(operation=str(operation), deadline_s=float(seconds), operation_since=time.time())
        self._progressed()
        self._save()

    def reading(self, text):
        """A measurement (the sensor at -6.2 °C): progress only when it changes."""
        if text != self.progress.get("reading"):
            self.progress["reading"] = str(text)
            self._progressed()
            self._save()

    def note(self, words):
        """activity.py's line for this process, kept as the operation's text."""
        if words != self.progress.get("operation"):
            # A new description keeps the deadline expect() gave: only
            # expect() sets or ends one.
            self.progress["operation"] = str(words)
            self._progressed()
            self._save()

    def milestone(self, words, name=None, wake=True):
        """A point a plan may go on from: wakes the agent (unless `wake` is
        False: an imaging run's blocks); a queued job `--after ID:NAME`
        starts from it."""
        self._progressed()
        self._save()
        self._event("milestone", words, wake=wake, name=name)

    def waiting(self, why, ask=None, holds=(), most_s=None):
        """Waiting on a person or another command, from now: wakes the agent,
        saying what ends the wait and what it holds meanwhile."""
        self.progress.update(waiting={"why": str(why), "ask": ask, "since": time.time(), "most_s": most_s},
                             holds=list(holds))
        self._save()
        self._event("waiting", why, wake=True, ask=ask, holds=list(holds))

    def resumed(self, words=""):
        self.progress.update(waiting=None)
        self._progressed()
        self._save()
        self._event("resumed", words)

    def release(self, *what):
        """Lets go of what a queued job may need (camera, mount)."""
        self.progress["holds"] = [h for h in self.progress.get("holds", []) if h not in what]
        self.progress["released"] = sorted(set(self.progress.get("released") or []) | set(what))
        self._save()
        release_reservation(self.id, what)      # the computer's register too
        self._event("released", ", ".join(what), released=list(what))

    def result(self, words):
        """The job's answer in one line, kept for the end."""
        self.progress["result"] = str(words)
        self._save()


def job(name, steps=None, expect_s=None, kind="finite", lazy_s=None):
    """This process's job (the one already open, if any)."""
    return CURRENT if CURRENT is not None else Job(name, steps, expect_s, kind, lazy_s)


def run_as(name, work, lazy_s=60):
    """work() as this process's job, kept only if it runs a minute or more:
    for scripts whose long runs said nothing until the end, without a
    record for every quick look at them."""
    with job(name, lazy_s=lazy_s):
        return work()


class _NoJob:
    """Stands in when no job is open: every call does nothing."""

    def __getattr__(self, _name):
        return lambda *args, **kwargs: None


def current():
    """This process's job, or one that ignores every call: code deep in a
    script reports through this without being handed the job."""
    return CURRENT if CURRENT is not None else _NoJob()


def _hostname():
    try:
        import socket
        return socket.gethostname()
    except Exception:
        return None


# ---------------------------------------------------------------- the launcher and the queue

def launch(name, command, after=(), needs=(), kind="finite", why=None, wait=False, cwd=None, log=None, replaces=None,
           quiet_s=None):
    """Start COMMAND as a job; returns its ID (or its exit code with wait).
    `log`: a file of its own for its lines (a session's patrol.log, which
    others read), instead of the job's log.txt."""
    if not command:
        raise SystemExit("no command given after --")
    if os.environ.get("CLAUDECODE") and not session():
        # Started by an agent that did not say which session it is: the job
        # would pass for the house's, and isolation would fail silently.
        print("ty bg: this agent's session is not known (no CLAUDE_CODE_SESSION_ID): the job is kept "
              "as the house's, shown to every session", file=sys.stderr)
    prune()
    job_id = new_id(name)
    folder(job_id).mkdir(parents=True, exist_ok=True)
    if quiet_s:
        # How long it may run without a line (--quiet), written before it
        # starts, so a foreground (--wait) or queued-again job keeps it too.
        records.write(folder(job_id) / "quiet.json", {"seconds": float(quiet_s)})
    argv = [sys.executable, str(Path(__file__).resolve()), "_supervise", job_id, name, kind,
            ",".join(after), ",".join(needs), why or "", "1" if wait else "0", "--", *command]
    if wait:
        return supervise(job_id, name, kind, list(after), list(needs), why, True, command, log)
    options = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
               "cwd": str(cwd or os.getcwd()),
               "env": dict(os.environ, TY_JOB_LOG=str(log or ""), TY_JOB_REPLACES=replaces or "")}
    if host.WINDOWS:
        options["creationflags"] = 0x00000008 | 0x00000200      # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    subprocess.Popen(argv, **options)
    for _ in range(50):
        if (folder(job_id) / "process.json").exists():
            break
        time.sleep(0.1)
    return job_id


class Recorded:
    """A job whose process its parent starts itself, kept in the same
    records: the console, whose Stop must kill the very process holding the
    mount's port. The parent is the one writer of process.json; the child
    adopts the job (its env()). Never raises: the record is a help."""

    def __init__(self, name, command, kind="finite", why=None):
        self.id = new_id(name)
        self.dir = folder(self.id)
        self.log = None
        self.record = {"id": self.id, "name": name, "kind": kind, "own": False,
                       "command": redact(" ".join(map(str, command))), "host": _hostname(), "boot": boot_id(),
                       "supervisor": os.getpid(), "supervisor_start": started_at(os.getpid()),
                       "parent": os.environ.get("TY_JOB"), "after": [], "needs": [], "why": why,
                       "pid": None, "pid_start": None, "queued": time.time(), "started": None,
                       "phase": "running", "exit_code": None, "ended": None, "blocked": None,
                       "log": str(self.dir / "log.txt"), "session": session(), "schema": SCHEMA, "core": CORE}
        self.lines = 0
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            self.log = open(self.dir / "log.txt", "ab", buffering=0)
        except OSError:
            pass

    def env(self, base=None):
        return dict(base or os.environ, TY_JOB=self.id, TY_JOB_ADOPT=str(os.getpid()), PYTHONUNBUFFERED="1")

    def _put(self, **fields):
        self.record.update(fields)
        try:
            records.write(self.dir / "process.json", self.record, indent=None)
        except Exception:
            pass

    def started(self, pid):
        self._put(pid=pid, pid_start=started_at(pid), started=time.time())

    def line(self, text):
        try:
            if self.log:
                self.log.write((str(text).rstrip("\n") + "\n").encode("utf-8", "replace"))
                self.lines += 1
                if self.lines % 500 == 0:
                    cap(self.dir / "log.txt")     # this process is the log's one writer
        except OSError:
            pass

    def ended(self, code):
        self._put(phase="exited", exit_code=code, ended=time.time())
        try:
            if self.log:
                self.log.close()
        except OSError:
            pass


def supervise(job_id, name, kind, after, needs, why, wait, command, log_path=None):
    """The launcher's own process: the one writer of process.json. Waits
    for what the job is queued behind, starts it, keeps its log, records
    how it ended."""
    d = folder(job_id)
    d.mkdir(parents=True, exist_ok=True)
    record = {"id": job_id, "name": name, "kind": kind if kind in KINDS else "finite", "own": False,
              "command": redact(" ".join(command)), "host": _hostname(), "boot": boot_id(),
              "supervisor": os.getpid(), "supervisor_start": started_at(os.getpid()),
              "parent": os.environ.get("TY_JOB"), "after": after, "needs": needs, "why": why or None,
              "pid": None, "pid_start": None, "queued": time.time(), "started": None,
              "phase": "queued", "exit_code": None, "ended": None, "blocked": None,
              "log": str(log_path or d / "log.txt"), "session": session(), "cwd": os.getcwd(), "schema": SCHEMA, "core": CORE,
              "replaces": os.environ.pop("TY_JOB_REPLACES", "") or None}
    log_path = Path(record["log"])

    def put(**fields):
        record.update(fields)
        try:
            records.write(d / "process.json", record, indent=None)
        except Exception:
            pass

    try:
        # The command in full, readable by this user only, for --requeue
        # after a restart (process.json keeps only the redacted words).
        records.write(d / "argv.json", {"argv": list(command)}, private=True)
    except Exception:
        pass
    put()

    def taken_off(_number, _frame):
        # ./ty jobs --stop on a job still queued: cancelled, not vanished.
        put(phase="cancelled", ended=time.time())
        raise SystemExit(0)
    try:
        signal.signal(signal.SIGTERM, taken_off)
    except (OSError, ValueError):
        pass
    env = dict(os.environ, PYTHONUNBUFFERED="1", TY_JOB=job_id, TY_JOB_ADOPT=str(os.getpid()))
    if command and Path(command[0]).name == "ssh" and len(command) > 2 and not command[-1].startswith("-"):
        # SSH does not carry the environment: the other computer's Python
        # would hold its output back, and the job here look stalled while
        # it worked (24 November 2026: clip12b, an hour "stalled" on the
        # desktop at 100% of four cores). The session goes too, so a job
        # started there is the same session's.
        owner = f" CLAUDE_CODE_SESSION_ID={session()}" if session() else ""
        command = [*command[:-1], f"export PYTHONUNBUFFERED=1{owner}; {command[-1]}"]
        if "-t" not in command and "-tt" not in command:
            # A terminal at the far end, so a stop (or a dropped link) hangs
            # the remote command up too: without one, a stopped job's
            # colour.py ran on for ten minutes on the desktop, sharing the GPU
            # with its replacement (24 November 2026). A remote job meant to
            # outlive its link runs under nohup (remote.py), which ignores it.
            command = [command[0], "-tt", *command[1:]]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = open(log_path, "ab", buffering=0)
    child = None
    while child is None:
        # Deciding and starting under one lock, the job running before the
        # lock is let go: two queued jobs never take one camera at once.
        with machine_lock(wait_s=300):
            verdict = ready(job_id, after, needs, record["queued"])
            if isinstance(verdict, str):
                put(phase="blocked", blocked=verdict, ended=time.time())
                return 1
            if verdict is True:
                exclusive_needs = [n for n in needs if n in exclusive()]
                try:
                    # Reserved before it starts, under the lock, in the name of
                    # this launcher (alive as long as the workload): if the
                    # reservation cannot be kept, the job does not start.
                    reserve(job_id, name, exclusive_needs, os.getpid())
                except OSError as problem:
                    put(phase="blocked", blocked=f"could not reserve {', '.join(exclusive_needs)}: {problem}",
                        ended=time.time())
                    return 1
                try:
                    # The output always comes through here: this process is
                    # the log's one writer, so it can cap it safely. Its own
                    # process group (POSIX), so its workers are seen to the end.
                    child = subprocess.Popen(command, stdin=subprocess.DEVNULL, env=env,
                                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                             start_new_session=not host.WINDOWS)
                except OSError as problem:
                    log.write(f"could not start: {problem}\n".encode())
                    put(phase="exited", exit_code=127, started=time.time(), ended=time.time())
                    unreserve(job_id)
                    return 127
                put(phase="running", pid=child.pid, pid_start=started_at(child.pid), started=time.time())
                try:
                    signal.signal(signal.SIGTERM, signal.SIG_DFL)
                except (OSError, ValueError):
                    pass
        if child is None:
            time.sleep(QUEUE_EVERY_S)
    beating = threading.Event()

    def beat():
        while not beating.wait(RESERVE_BEAT_S):
            beat_reservation(job_id)
    threading.Thread(target=beat, daemon=True).start()
    if wait:
        # Run in the foreground (a timer, the console, a parent job): the
        # output goes to the log and on to whoever started it, and a stop
        # sent to this launcher goes on to the command, as if it were the
        # command itself (a schedule's step stopped by its runner).
        for sig in (signal.SIGTERM, signal.SIGINT, getattr(signal, "SIGHUP", None)):
            # One ignored already (nohup: a job on another computer that must
            # outlive its SSH connection) stays ignored.
            if sig is not None and signal.getsignal(sig) is not signal.SIG_IGN:
                try:
                    signal.signal(sig, lambda number, _frame: _signal_group(child, number))
                except (OSError, ValueError):
                    pass
    written = 0
    for line in child.stdout:
        log.write(line)
        written += len(line)
        if written > 1_000_000:
            written = 0
            cap(log_path)
        if wait:
            try:
                sys.stdout.buffer.write(line)
                sys.stdout.flush()
            except (OSError, ValueError):
                pass
    child.wait()
    cap(log_path)
    log.close()
    put(phase="exited", exit_code=child.returncode, ended=time.time())
    # A workload's workers may outlive the command that started them: its
    # reservation stands until the last of its process group has gone.
    if exclusive_needs and not host.WINDOWS:
        until = time.time() + 12 * 3600
        while _group_alive(child.pid) and time.time() < until:
            time.sleep(QUEUE_EVERY_S)
    beating.set()
    unreserve(job_id)
    return child.returncode


def _signal_group(child, number):
    """A stop sent to the launcher, on to the command and its workers."""
    try:
        if host.WINDOWS:
            child.send_signal(number)
        else:
            os.killpg(child.pid, number)
    except OSError:
        pass


def _group_alive(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def cap(path):
    """A log past its cap keeps its newer half (the cap is smaller when the
    disk is low: 2 November 2026 it filled)."""
    try:
        free = shutil.disk_usage(path.parent).free / 1e9
        limit = (LOG_CAP_LOW_MB if free < LOW_DISK_GB else LOG_CAP_MB) * 1e6
        size = path.stat().st_size
        if size <= limit:
            return
        with open(path, "r+b") as f:
            f.seek(size - int(limit / 2))
            kept = f.read()
            f.seek(0)
            f.write(b"(older lines dropped: the log was over its cap)\n" + kept)
            f.truncate()
    except OSError:
        pass


def find(word):
    """A job by its ID, or the newest job with that name."""
    if (folder(word) / "process.json").exists():
        return word
    # The name exactly: YYYYMMDD-HHMMSS-NAME-xxxxxx (on 24 November "keeper"
    # found "keeper-stop", and the videos queued behind the keeper waited on it).
    try:
        named = sorted((p.name for p in home().iterdir() if p.is_dir() and p.name[16:-7] == word), reverse=True)
    except OSError:
        return None
    return named[0] if named else None


def holds_now(listing=None):
    """{need: who holds it} for camera and mount, from the camera's lock,
    the mount's owner and the jobs that say they hold something."""
    held = dict(machine_holds())       # every project's on this computer
    try:
        import cameralock
        who = cameralock.holder()
        if who and host.alive(who[0]) and "keeper.py" not in who[1]:
            held["camera"] = f"{who[1][:60]} (PID {who[0]})"
    except Exception:
        pass
    owner = _read(Path(config.DATA) / "cache" / "mount-owner.json")
    if isinstance(owner, dict) and host.alive(owner.get("pid")):
        held["mount"] = f"{' '.join(owner.get('argv') or [])[:60]} (PID {owner.get('pid')})"
    for j in listing if listing is not None else look_all():
        if j["phase"] in ("running", "waiting", "stalled"):
            # What it said it holds, and what it was started needing: a job
            # just started holds its camera before its lock is taken.
            released = set(j["progress"].get("released") or [])
            for h in (j.get("holds") or []) + [n for n in (j.get("needs") or []) if n in exclusive()
                                               and n not in released]:
                held.setdefault(h, f"job {j['name']}")
    return held


def after_ok(after):
    """True when every condition a job is queued behind holds, a reason when
    one never will, else None."""
    for condition in after:
        word, _, what = condition.partition(":")
        other = find(word)
        if other is None:
            return f"no job {word}"
        o = look(other)
        if o["phase"] == "vanished":
            # Lost with a restart and queued again (--requeue): its replacement
            # stands in for it, so a chain rebuilt job by job carries on.
            stand_in = replacement(other)
            if stand_in != other:
                o = look(stand_in)
        if what == "ended":
            if o["phase"] in ("done", "failed", "vanished", "blocked", "cancelled"):
                continue
            return None
        if what == "released":
            if o["phase"] == "done" or any(e["kind"] == "released" for e in o["events"]):
                continue
        elif what:
            if any(e["kind"] == "milestone" and e.get("name") == what for e in o["events"]):
                continue
        elif o["phase"] == "done":
            continue
        if o["phase"] in ("failed", "vanished", "blocked", "cancelled") or (o["phase"] == "done" and what):
            return f"{o['name']} {o['phase']} before {condition}"
        return None
    return True


def ready(job_id, after, needs, queued_at):
    """True when the job may start, a reason when it never will, else None."""
    waits = after_ok(after)
    if waits is not True:
        return waits
    if needs:
        listing = look_all()
        held = holds_now(listing)       # a running, waiting or stalled job keeps what it needs
        if any(n in held for n in needs if n in exclusive()):
            return None
        if "cpu" in needs:
            try:
                if os.getloadavg()[0] > max(1, (os.cpu_count() or 2) - 1):
                    return None
            except (OSError, AttributeError):
                pass
        # First come, first served among jobs queued for the same thing, of
        # those that could start now: one still waiting on its own
        # dependencies, or on another thing it needs (a camera in use), never
        # holds up a later one that could run.
        if any(j["phase"] == "queued" and j["id"] != job_id and (j.get("queued") or 0) < queued_at
               and set(j.get("needs") or []) & set(needs) & set(exclusive())
               and after_ok(j.get("after") or []) is True
               and not any(n in held for n in (j.get("needs") or []) if n in exclusive()) for j in listing):
            return None
    return True


def wanted(need):
    """Whether any queued job waits for `need` (a hold can end early for it)."""
    return any(j["phase"] == "queued" and need in (j.get("needs") or []) for j in look_all())


def owned(j, force=False):
    """A job this session may stop or queue again: its own or the house's;
    another session's only with --force (the person's say)."""
    sid = session()
    if force or j.get("session") in (None, sid):
        return
    if sid is None and not os.environ.get("CLAUDECODE"):
        return                  # the person at a terminal
    # An agent whose session is not known gets no more than any other session.
    raise SystemExit(f"{j['name']} is another session's job ({str(j.get('session'))[:8]}): "
                     "leave it to that session, or --force if the person says so")


def stop(word, force=False):
    job_id = find(word)
    if not job_id:
        raise SystemExit(f"no job {word}")
    j = look(job_id)
    owned(j, force)
    if j["phase"] == "queued" and j.get("supervisor"):
        os.kill(int(j["supervisor"]), signal.SIGTERM)
        return f"{j['name']} taken off the queue"
    if j["phase"] not in ("running", "waiting", "stalled") or not j.get("pid"):
        return f"{j['name']} is {j['phase']}: nothing to stop"
    os.kill(int(j["pid"]), signal.SIGTERM)
    return f"{j['name']} told to stop (PID {j['pid']}); its own ending runs"


def prune(now=None):
    """Finished jobs' folders past their keep (30 days; routine 2), and
    never one with an event still open."""
    now = now or time.time()
    try:
        acked = _acked()
        for d in home().iterdir():
            if not d.is_dir():
                continue
            p = _read(d / "process.json", {}) or {}
            ended = p.get("ended") or (_mtime(d) if p.get("phase") not in ("queued", "running") else None)
            days = KEEP_DAYS.get(p.get("kind"), 30)
            if not ended or now - ended < days * 86400:
                continue
            j = look(d.name, now)
            if j["phase"] in ("queued", "running", "waiting", "stalled"):
                continue
            if any(e["id"] not in acked for e in wake_events(j, now)):
                continue
            shutil.rmtree(d, ignore_errors=True)
    except OSError:
        pass


# ---------------------------------------------------------------- reading

def look(job_id, now=None):
    """One job as it stands: its records, its phase, and why."""
    now = now or time.time()
    d = folder(job_id)
    p = _read(d / "process.json", {}) or {}
    g = _read(d / "progress.json", {}) or {}
    events = _lines(d / "events.jsonl")
    log_path = Path(p.get("log") or d / "log.txt")
    beat, logged = _mtime(d / "heartbeat"), _mtime(log_path)
    j = {**p, "id": job_id, "name": p.get("name") or g.get("name") or job_id, "kind": g.get("kind") or p.get("kind", "finite"),
         "progress": g, "events": events, "holds": g.get("holds") or [], "heartbeat": beat,
         "last_output": max(filter(None, (logged, g.get("last_output"))), default=None),
         "last_progress": max(filter(None, (g.get("last_progress"), g.get("operation_since"))), default=None),
         "stall": None, "log": str(log_path), "quiet_s": (_read(d / "quiet.json", {}) or {}).get("seconds")}
    phase = p.get("phase")
    alive = running(p.get("pid"), p.get("pid_start"), p.get("boot"))
    if phase == "queued":
        phase = "queued" if running(p.get("supervisor"), p.get("supervisor_start"), p.get("boot")) else "vanished"
    elif phase in ("blocked", "cancelled"):
        pass
    elif p.get("exit_code") is not None:
        failed = p["exit_code"] != 0 or str(g.get("result") or "").startswith("failed")
        phase = "failed" if failed else "done"
    elif phase == "running" and alive:
        phase = "waiting" if g.get("waiting") else "running"
    elif phase == "running" and p.get("own") and g.get("result") and not alive:
        phase = "failed" if str(g["result"]).startswith("failed") else "done"
    elif phase == "running" and not p.get("pid") and running(p.get("supervisor"), p.get("supervisor_start"),
                                                             p.get("boot")):
        phase = "running"     # the launcher is starting it this moment
    else:
        phase = "vanished" if p or g else "unknown"
    j["phase"] = phase
    if phase == "running":
        j["stall"] = stalled(j, now)
        if j["stall"]:
            j["phase"] = "stalled"
    elif phase == "waiting":
        w = g["waiting"]
        if w.get("most_s") and now - w["since"] > w["most_s"]:
            j["stall"] = f"waiting {_ago(now - w['since'])}, longer than its {_ago(w['most_s'])}"
    return j


def stalled(j, now):
    """Why a live job has stopped making progress, or None."""
    g = j["progress"]
    if j["heartbeat"] and now - j["heartbeat"] > NOT_RESPONDING_S and (g or not j.get("pid")):
        return f"not responding: no heartbeat for {_ago(now - j['heartbeat'])}"
    if j["kind"] == "service":
        return None
    if g.get("deadline_s"):
        # The operation's own deadline, from when expect() began it: new
        # words or changing readings do not move it (a sensor wobbling round
        # its target without reaching it is alive, and still overdue).
        began = g.get("operation_since") or j.get("started") or now
        limit = g["deadline_s"] * DEADLINE_MARGIN[0] + DEADLINE_MARGIN[1]
        if now - began > limit:
            return f"\"{g.get('operation')}\" has taken {_ago(now - began)}, past its {_ago(g['deadline_s'])}"
    # Apart from any deadline: no output and no progress at all for QUIET_S,
    # or the quiet the job was started with (cj bg --quiet: a step known to
    # run that long without a line), so a quiet job does not wake its session.
    last = max(filter(None, (j["last_output"], j["last_progress"], j.get("started"))), default=now)
    if now - last > (j.get("quiet_s") or QUIET_S):
        return f"no output or progress for {_ago(now - last)}"
    return None


def look_all(now=None):
    try:
        names = sorted(p.name for p in home().iterdir() if p.is_dir())
    except OSError:
        return []
    return [look(n, now) for n in names]


def wake_events(j, now=None):
    """The events of one job that need the agent, each with a lasting ID."""
    now = now or time.time()
    out = [dict(e, name=j["name"]) for e in j["events"] if e.get("wake")]
    if j["phase"] in ("done", "failed", "vanished", "blocked"):
        if not (j["phase"] == "done" and (j["kind"] == "routine" or j.get("parent"))):
            result = j["progress"].get("result") or j.get("blocked") or _last_line(j["log"]) or ""
            words = {"done": "", "failed": f"exit {j.get('exit_code')}",
                     "vanished": "its process is gone and no ending was recorded"
                                 + (f" (a restart?); ./ty jobs --requeue {j['id']} queues it again"
                                    if (folder(j["id"]) / "argv.json").exists() else ""),
                     "blocked": "what it was queued behind will not happen"}[j["phase"]]
            out.append({"id": f"{j['id']}:end", "job": j["id"], "name": j["name"], "kind": j["phase"],
                        "words": "; ".join(w for w in (words, result) if w) or "finished", "wake": True,
                        "at": j.get("ended") or j["last_output"] or now})
    if j["stall"]:
        since = int(j["progress"].get("operation_since") or j["last_progress"] or j["last_output"] or 0)
        out.append({"id": f"{j['id']}:stall:{since}", "job": j["id"], "name": j["name"], "kind": "stalled",
                    "words": j["stall"], "wake": True, "at": now})
    return out


def busy_file(sid):
    return home() / f"busy-{sid or 'owner'}.json"


def busy(sid=None):
    """The owner's ask for work until a time, as this session recorded it."""
    return _read(busy_file(sid))


def productive(listing):
    """Whether any of these jobs is getting work done: a finite or remote
    job running, or one queued behind a job that is running (the videos
    behind the keeper cooling). Waiting, stalled and blocked jobs are not
    work getting done, however much they hold."""
    running_ids = {j["id"] for j in listing if j["phase"] == "running"}
    if any(j["phase"] == "running" and j["kind"] in ("finite", "remote") for j in listing):
        return True
    return any(j["phase"] == "queued" and any(find(c.partition(":")[0]) in running_ids for c in j.get("after") or [])
               for j in listing)


def committed(b, now=None):
    """Whether a busy-until stands: until a time, or until done (ended
    only by `./ty jobs --busy-until off`)."""
    now = now or time.time()
    return bool(b) and (bool(b.get("done")) or now <= (b.get("until") or 0))


def until_words(b):
    return "until it is all done" if b.get("done") else f"until {_clock(b.get('until'))}"


def idle_event(listing, now=None, sid=None):
    """An idle event while the owner's busy-until stands and none of this
    session's work is getting done."""
    now = now or time.time()
    b = busy(sid)
    if not committed(b, now):
        return None
    own = [j for j in listing if mine(j, sid, strict=True)]
    if productive(own):
        return None
    since = max([b.get("set", 0)] + [j.get("ended") or 0 for j in own])
    if now - since < IDLE_AFTER_S:
        return None
    # A live job that has gone quiet already has its own stall event: idle
    # is for nothing running at all, not a second alarm for the same quiet.
    if any(j["phase"] == "stalled" for j in own):
        return None
    stuck = [j for j in own if j["phase"] in ("waiting", "stalled", "queued", "blocked")]
    held = f"; {len(stuck)} job{'s' if len(stuck) != 1 else ''} waiting, stalled or queued, none moving" if stuck else ""
    return {"id": f"idle:{sid or 'owner'}:{int(since)}", "job": None, "name": "idle", "kind": "idle", "wake": True,
            "at": now, "condition": True,
            "words": f"no work getting done for {_ago(now - since)}{held}, and the owner asked for work "
                     f"{until_words(b)} ({b.get('why') or 'no reason given'})"}


def _acked():
    """The latest ack of each event, with how many times it has been acked:
    each ack of a condition still there doubles the wait before it reopens."""
    out = {}
    for a in _lines(home() / "acks.jsonl"):
        e = a.get("event")
        out[e] = dict(a, count=(out.get(e) or {}).get("count", 0) + 1)
    return out


def _condition(e, listing):
    """Whether an event's condition is still there (a job still waiting, still
    stalled; idle is judged afresh), so an ack has not resolved it."""
    if e["kind"] == "waiting":
        return any(j["id"] == e.get("job") and j["phase"] == "waiting" for j in listing)
    return e["kind"] in ("stalled", "idle")


def open_events(listing=None, now=None, sid=None, strict=False, acked_too=False):
    """The events that need this session (`strict`: only its own jobs').
    An acked waiting, stall or idle that is still there REOPEN_S after its
    ack is open again: an ack says what was done, not that it worked."""
    now = now or time.time()
    listing = look_all(now) if listing is None else listing
    acked = _acked()
    ours = [j for j in listing if mine(j, sid, strict)]
    out = []
    for e in [e for j in ours for e in wake_events(j, now)] + [i for i in [idle_event(listing, now, sid)] if i]:
        a = acked.get(e["id"])
        if a is None:
            out.append(e)
        elif _condition(e, listing) and now - a.get("at", now) > REOPEN_S * 2 ** (a.get("count", 1) - 1):
            # Reopened REOPEN_S after the first ack, then twice as long after
            # each ack after it (30, 60, 120 min...): counted by acks, since an
            # ack resets the time (25 November 2026: by the time alone, a
            # session acking each reminder still had one every 30 minutes).
            n = a.get("count", 1)
            out.append(dict(e, id=f"{e['id']}:still:{n}",
                            words=f"still, {_ago(now - a['at'])} after it was acked ({a.get('words')}): {e['words']}"))
        elif acked_too and _condition(e, listing):
            out.append(dict(e, acked=a.get("words")))
    # A timer's routine run that keeps failing is one event, its newest, not one every ten minutes.
    routine = {j["id"] for j in listing if j["kind"] == "routine"}
    newest = {}
    for e in out:
        if e.get("job") in routine:
            newest[e["name"]] = e
    out = [e for e in out if e.get("job") not in routine or newest.get(e["name"]) is e]
    return sorted(out, key=lambda e: e.get("at") or 0)


def canonical(event_id):
    """An event's lasting ID: a reopened one (ID:still:N) is the same event."""
    return event_id.split(":still:")[0]


def ack(event, words, sid=None):
    """What was done about an event; only one this session can see (its own
    jobs' and the house's), "all" being every one of those open."""
    if not words:
        raise SystemExit("say what was done about it: ./ty jobs --ack EVENT \"started the Moon video\"")
    seen = [e["id"] for e in open_events(sid=sid)]
    targets = seen if event == "all" else [event]
    if event != "all" and event not in seen:
        raise SystemExit(f"{event} is not an open event of this session's (./ty jobs)")
    # Every session writes here: one at a time, under the file's lock.
    with records.locked(home() / "acks.jsonl"):
        for t in targets:
            _append(home() / "acks.jsonl", {"event": canonical(t), "words": words, "at": time.time(),
                                            "session": sid})
    return len(targets)


def requeue(word, force=False):
    """A job lost with a restart (or ended), queued again as it was asked:
    the same command, conditions and needs. A person's or the agent's
    choice, never done by itself: a command for the camera or the mount
    keeps every protection of its own."""
    job_id = find(word)
    if not job_id:
        raise SystemExit(f"no job {word}")
    owned(look(job_id), force)
    p = _read(folder(job_id) / "process.json", {}) or {}
    argv = (_read(folder(job_id) / "argv.json", {}) or {}).get("argv")
    if not argv:
        raise SystemExit(f"{word}: its command was not kept, so it cannot be queued again")
    return launch(p.get("name") or word, argv, p.get("after") or [], p.get("needs") or [], p.get("kind", "finite"),
                  p.get("why"), cwd=p.get("cwd"), log=p.get("log") if p.get("log", "").endswith("patrol.log") else None,
                  replaces=job_id, quiet_s=(_read(folder(job_id) / "quiet.json", {}) or {}).get("seconds"))


def replacement(job_id):
    """The job queued again in place of one lost (--requeue), newest first,
    followed to the end of the chain."""
    seen = set()
    while job_id not in seen:
        seen.add(job_id)
        later = sorted((d.name for d in home().iterdir() if d.is_dir()
                        and (_read(d / "process.json", {}) or {}).get("replaces") == job_id), reverse=True)
        if not later:
            return job_id
        job_id = later[0]
    return job_id


def _last_line(path):
    try:
        with open(path, "rb") as f:
            f.seek(max(0, f.seek(0, 2) - 4000))
            lines = [ln for ln in f.read().decode("utf-8", "replace").splitlines() if ln.strip()]
        return lines[-1].strip()[:200] if lines else None
    except OSError:
        return None


def _ago(seconds):
    seconds = max(0, round(seconds))
    if seconds < 90:
        return f"{seconds} s"
    if seconds < 5400:
        return f"{round(seconds / 60)} min"
    return f"{seconds / 3600:.1f} h"


def _clock(t):
    return time.strftime("%H:%M UT", time.gmtime(t)) if t else "?"


# ---------------------------------------------------------------- the report

def computer():
    out = {}
    try:
        out["load"] = round(os.getloadavg()[0], 1)
        out["cores"] = os.cpu_count()
    except (OSError, AttributeError):
        pass
    try:
        info = {ln.split(":")[0]: int(ln.split()[1]) / 2 ** 20 for ln in open("/proc/meminfo")}
        out["memory_free_gb"], out["memory_gb"] = round(info["MemAvailable"], 1), round(info["MemTotal"], 1)
    except (OSError, KeyError, ValueError):
        pass
    try:
        out["disk_free_gb"] = round(shutil.disk_usage(config.DATA).free / 1e9, 1)
    except OSError:
        pass
    tool = shutil.which("nvidia-smi")
    if tool:
        try:
            got = subprocess.run([tool, "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=5).stdout.split(",")
            out["gpu_pct"], out["gpu_mem_mb"] = float(got[0]), float(got[1])
        except (OSError, subprocess.SubprocessError, ValueError, IndexError):
            pass
    return out


def underused(c, b, now=None):
    """While the owner's busy-until stands: the CPU or GPU mostly idle, said
    so the session can queue more. A note, not a scheduler: what runs where
    is the session's (and desktopqueue's) to decide."""
    now = now or time.time()
    if not committed(b, now):
        return []
    out = []
    if c.get("load") is not None and c.get("cores") and c["load"] < 0.25 * c["cores"]:
        out.append(f"CPU: load {c['load']} on {c['cores']} cores")
    if c.get("gpu_pct") is not None and c["gpu_pct"] < 10:
        out.append(f"GPU: {c['gpu_pct']:.0f}%")
    return out


def camera_state(held):
    # From the keeper's own state file, never by asking it: a keeper warming
    # up answers nothing, and the report must not wait on it.
    state = _read(Path(config.DATA) / "cache" / "keeper.json") or {}
    keeper = bool(state) and host.alive(state.get("pid"))
    if keeper:
        sensor, target = state.get("sensor_c"), state.get("target_c")
        return {"by": "the keeper", "sensor_c": sensor, "target_c": target, "ready": state.get("ready"),
                "words": f"the keeper holds it: sensor {sensor} °C, target {target} °C"}
    if "camera" in held:
        return {"by": held["camera"], "words": f"held by {held['camera']}"}
    return {"by": None, "words": "free"}


def report(now=None, sid=None):
    """The progress report for one session: its own jobs and the house's,
    its events and its busy-until; the computer, camera and mount, which
    every session shares; and how many jobs other sessions have going."""
    now = now or time.time()
    everything = look_all(now)
    held = holds_now(everything)
    listing = [j for j in everything if mine(j, sid)]
    others = [j for j in everything if not mine(j, sid) and j["phase"] in ("running", "stalled", "waiting", "queued")]

    def brief(j):
        g = j["progress"]
        return {"id": j["id"], "name": j["name"], "kind": j["kind"], "phase": j["phase"],
                "step": g.get("step"), "of": g.get("of"), "text": g.get("text") or None,
                "operation": g.get("operation"), "deadline_s": g.get("deadline_s"), "reading": g.get("reading"),
                "waiting": g.get("waiting"), "holds": j["holds"], "stall": j["stall"],
                "last_line": _last_line(j["log"]),
                "last_output_s": round(now - j["last_output"]) if j["last_output"] else None,
                "expect_end": g.get("expect_end"), "started": j.get("started"), "ended": j.get("ended"),
                "after": j.get("after") or [], "needs": j.get("needs") or [], "blocked": j.get("blocked"),
                "result": g.get("result"), "log": j["log"]}

    active = [brief(j) for j in listing if j["phase"] in ("running", "stalled", "waiting", "queued", "blocked")
              and not (j["phase"] == "blocked" and (j.get("ended") or 0) < now - 86400)]
    recent = [brief(j) for j in listing if j["phase"] in ("done", "failed", "vanished")
              and not (j["kind"] == "routine" and j["phase"] == "done")
              and (j.get("ended") or j["last_output"] or 0) > now - 12 * 3600]
    events = open_events(everything, now, sid, acked_too=True)
    return {"open_events": [{k: e.get(k) for k in ("id", "name", "kind", "words", "at", "ask")}
                            for e in events if "acked" not in e],
            "acked_unresolved": [{"id": e["id"], "name": e["name"], "kind": e["kind"], "words": e["words"],
                                  "acked": e["acked"]} for e in events if "acked" in e],
            "other_sessions": len(others),
            "jobs": active, "recent": recent, "computer": computer(),
            "camera": camera_state(held), "mount": {"by": held.get("mount"),
                                                    "words": f"held by {held['mount']}" if "mount" in held
                                                    else "free"},
            "busy_until": busy(sid), "underused": underused(computer(), busy(sid), now),
            "unarmed": (len(active_own(everything, sid)) if sid and active_own(everything, sid)
                        and not armed(sid, now) else 0)}


def text(r, now=None):
    now = now or time.time()
    lines = []
    if r["open_events"]:
        lines.append("Needs the agent (ack each: ./ty jobs --ack EVENT \"what was done\"):")
        for e in r["open_events"]:
            ask = f" Ends with: {e['ask']}" if e.get("ask") else ""
            lines.append(f"  ! {_clock(e.get('at'))} {e['name']} {e['kind']}: {e['words']}{ask}  [{e['id']}]")
    for e in r.get("acked_unresolved") or []:
        lines.append(f"  acked, not resolved: {e['name']} {e['kind']}: {e['words'][:100]} (acked: {e['acked']})")
    groups = (("running", ("running", "stalled")), ("waiting", ("waiting", "blocked")), ("queued", ("queued",)))
    for title, phases in groups:
        rows = [j for j in r["jobs"] if j["phase"] in phases]
        if not rows:
            continue
        lines.append(f"{title.capitalize()}:")
        for j in rows:
            bits = [f"  {j['name']} ({j['phase']})"]
            if j["step"] is not None:
                bits.append(f"step {j['step']} of {j['of']}" + (f" {j['text']}" if j["text"] else ""))
            if j["operation"]:
                bits.append(j["operation"] + (f" (up to {_ago(j['deadline_s'])})" if j["deadline_s"] else ""))
            if j["reading"]:
                bits.append(j["reading"])
            if j["stall"]:
                bits.append(f"STALLED: {j['stall']}")
            if j["waiting"]:
                w = j["waiting"]
                bits.append(f"waiting {_ago(now - w['since'])}: {w['why']}" + (f"; ends with {w['ask']}" if w.get("ask") else ""))
            if j["holds"]:
                bits.append(f"holds {', '.join(j['holds'])}")
            if j["phase"] == "queued":
                bits.append("after " + ", ".join(j["after"]) if j["after"] else "")
                bits.append("needs " + ", ".join(j["needs"]) if j["needs"] else "")
            if j["blocked"]:
                bits.append(j["blocked"])
            if j["expect_end"]:
                bits.append(f"ends about {_clock(j['expect_end'])}")
            if j["last_line"] and j["phase"] != "queued":
                bits.append(f"last line {_ago(j['last_output_s'] or 0)} ago: {j['last_line'][:120]}")
            lines.append(" · ".join(b for b in bits if b))
    if r["recent"]:
        lines.append("Finished in the last 12 h:")
        for j in r["recent"]:
            said = (j["result"] or j["last_line"] or "")[:150]
            when = j["ended"] or (now - j["last_output_s"] if j["last_output_s"] is not None else None)
            lines.append(f"  {j['name']} {j['phase']} at {_clock(when)}" + (f": {said}" if said else ""))
    c = r["computer"]
    if c:
        parts = []
        if "load" in c:
            parts.append(f"load {c['load']} on {c['cores']} cores")
        if "memory_free_gb" in c:
            parts.append(f"memory {c['memory_free_gb']} of {c['memory_gb']} GB free")
        if "disk_free_gb" in c:
            parts.append(f"disk {c['disk_free_gb']} GB free")
        if "gpu_pct" in c:
            parts.append(f"GPU {c['gpu_pct']:.0f}%")
        lines.append("Computer: " + ", ".join(parts))
    lines.append(f"Camera: {r['camera']['words']}. Mount: {r['mount']['words']}.")
    b = r["busy_until"]
    if committed(b, now):
        lines.append(f"Busy {until_words(b)}: {b.get('why')}")
    if r.get("unarmed"):
        lines.append(f"NOTHING ARMED to wake this session for its {r['unarmed']} job(s) going: run "
                     f"`./ty jobs --wait-event` in the background (or a Monitor on `./ty jobs --watch`)")
    for word in r.get("underused") or []:
        lines.append(f"Underused: {word}")
    if r.get("other_sessions"):
        lines.append(f"Other sessions have {r['other_sessions']} job{'s' if r['other_sessions'] != 1 else ''} "
                     "going (./ty jobs --all).")
    if not r["jobs"] and not r["open_events"]:
        lines.insert(0, "No job of this session's running, waiting or queued.")
    return "\n".join(lines)


TERMINAL = ("done", "failed", "vanished", "blocked", "cancelled")


def _code_stamp():
    try:
        return Path(__file__).resolve().stat().st_mtime
    except OSError:
        return None


def _code_changed(stamp, what):
    """True, said, when this file has changed since the waiter started: an
    old one goes on running the old code and may misread new records (24
    November 2026: a watch from before "until done" raised on every pass).
    Its ending wakes the session, which starts it again on the new code."""
    if stamp is None or _code_stamp() == stamp:
        return False
    print(f"jobs {what}: the job system's code has changed since this started: start it again "
          f"(./ty jobs {'--watch' if what == 'watch' else '--wait-event'})", flush=True)
    return True
WAITER_BEAT_S = 10


def _waiter(kind, sid):
    """Mark this process as something armed to wake the session (a
    --wait, --wait-event or --watch that the harness is tracking): a file
    with its process, beaten every WAITER_BEAT_S, gone when it ends."""
    folder = home() / "waiters"
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / f"{sid or 'owner'}-{os.getpid()}.json"
    record = {"session": sid, "kind": kind, "pid": os.getpid(), "start": started_at(os.getpid()), "boot": boot_id(),
              "since": time.time()}

    def beat():
        while True:
            try:
                records.write(f, dict(record, beat=time.time()), indent=None)
            except OSError:
                pass
            time.sleep(WAITER_BEAT_S)
    threading.Thread(target=beat, daemon=True).start()
    atexit.register(lambda: f.unlink(missing_ok=True))
    return f


def armed(sid, now=None):
    """Whether something tracked by the harness is waiting to wake this
    session: a --wait, --wait-event or --watch of its own still beating."""
    now = now or time.time()
    try:
        files = list((home() / "waiters").glob("*.json"))
    except OSError:
        return False
    for f in files:
        w = _read(f, {}) or {}
        if not running(w.get("pid"), w.get("start"), w.get("boot")) or now - (w.get("beat") or 0) > 3 * WAITER_BEAT_S:
            try:
                f.unlink()
            except OSError:
                pass
            continue
        if w.get("session") == sid:
            return True
    return False


def active_own(listing, sid):
    """This session's jobs still going (running, waiting, stalled, queued)."""
    return [j for j in listing if mine(j, sid, strict=True) and j["phase"] in ("running", "waiting", "stalled", "queued")]


def wait_job(word, every=5):
    """Block until the job has ended, by the reader's own phases (a finished
    job is "done": 24 November 2026, a waiter grepping for "exited" never
    ended on a success); print its ending; exit 0 only for done."""
    job_id = find(word)
    if not job_id:
        raise SystemExit(f"no job {word}")
    _waiter("wait", session())
    while True:
        j = look(job_id)
        if j["phase"] in TERMINAL:
            said = j["progress"].get("result") or j.get("blocked") or _last_line(j["log"]) or ""
            print(f"{j['name']} {j['phase']}" + (f": {said}" if said else ""), flush=True)
            sys.exit(0 if j["phase"] == "done" else 1)
        time.sleep(every)


def wait_event(sid=None, every=10):
    """Block until an event needs this session, print it and exit: run in
    the background, its ending is what wakes the session. One open already
    is printed at once."""
    _waiter("wait-event", sid)
    stamp = _code_stamp()
    while True:
        if _code_changed(stamp, "wait-event"):
            return
        try:
            events = open_events(sid=sid)
        except Exception:
            events = []
        if events:
            for e in events:
                ask = f" Ends with: {e['ask']}" if e.get("ask") else ""
                print(f"{_clock(e.get('at'))} {e['name']} {e['kind']}: {e['words']}{ask} [{e['id']}]", flush=True)
            return
        time.sleep(every)


def watch(every=15, sid=None):
    """One line per event that needs this session, the ones open now first;
    nothing else, ever. It counts as armed while it runs (a Monitor)."""
    _waiter("watch", sid)
    stamp = _code_stamp()
    shown = set()
    while True:
        if _code_changed(stamp, "watch"):
            return
        try:
            for e in open_events(sid=sid):
                if e["id"] in shown:
                    continue
                shown.add(e["id"])
                ask = f" Ends with: {e['ask']}" if e.get("ask") else ""
                print(f"{_clock(e.get('at'))} {e['name']} {e['kind']}: {e['words']}{ask} [{e['id']}]", flush=True)
        except Exception as problem:     # the watch never ends on a bad record
            print(f"jobs watch: {type(problem).__name__}: {problem}", file=sys.stderr, flush=True)
        time.sleep(every)


def until_time(words, now=None):
    """HH:MM (UT, the next one) or a number of hours."""
    now = now or time.time()
    if ":" in words:
        import calendar
        hour, minute = (int(x) for x in words.split(":"))
        day = time.gmtime(now)
        t = calendar.timegm((day.tm_year, day.tm_mon, day.tm_mday, hour, minute, 0))
        return t + 86400 if t <= now else t
    return now + float(words) * 3600


def tail(word, count):
    job_id = find(word)
    if not job_id:
        raise SystemExit(f"no job {word}")
    path = folder(job_id) / "log.txt"
    try:
        with open(path, "rb") as f:
            f.seek(max(0, f.seek(0, 2) - 200 * count))
            print("\n".join(f.read().decode("utf-8", "replace").splitlines()[-count:]))
    except OSError:
        print(f"(no log yet: {path})")


def main():
    argv = sys.argv[1:]
    if sys.argv[0].endswith(" bg"):
        argv = ["bg"] + argv              # ./ty bg NAME ... arrives without its word
    if argv[:1] == ["_supervise"]:
        cut = argv.index("--")
        job_id, name, kind, after, needs, why, wait = argv[1:cut]
        sys.exit(supervise(job_id, name, kind, [a for a in after.split(",") if a],
                           [n for n in needs.split(",") if n], why, wait == "1", argv[cut + 1:],
                           os.environ.pop("TY_JOB_LOG", "") or None))
    if argv[:1] == ["bg"]:
        cut = argv.index("--") if "--" in argv else len(argv)
        ap = argparse.ArgumentParser(prog="ty bg", description="Start a command as a job.")
        ap.add_argument("name")
        ap.add_argument("--after", action="append", default=[],
                        help="JOB (done), JOB:ended (however it ended), JOB:released (it let go of what "
                             "it held), JOB:MILESTONE")
        ap.add_argument("--needs", default="", help=f"comma-separated: {', '.join(NEEDS)}")
        ap.add_argument("--kind", default="finite", choices=KINDS)
        ap.add_argument("--why", help="what it is for (the person's ask)")
        ap.add_argument("--quiet", type=float, metavar="MINUTES",
                        help="how long a step may run without a line before it counts as stalled (default "
                             f"{QUIET_S // 60} min)")
        ap.add_argument("--wait", action="store_true", help="run in the foreground, its output passed on too")
        args = ap.parse_args(argv[1:cut])
        needs = [n for n in args.needs.split(",") if n]
        unknown = [n for n in needs if n not in NEEDS]
        if unknown:
            ap.error(f"unknown needs: {', '.join(unknown)}")
        result = launch(args.name, argv[cut + 1:], args.after, needs, args.kind, args.why, args.wait,
                        quiet_s=args.quiet * 60 if args.quiet else None)
        if args.wait:
            sys.exit(result)
        j = look(result)
        print(f"{result} {j['phase']}  log: {j['log']}")
        return
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", nargs="?", help="a job, for --tail")
    ap.add_argument("--tail", type=int)
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--wait", metavar="JOB", help="block until the job has ended (done, failed, vanished, blocked, "
                                                  "cancelled); exit 0 only for done")
    ap.add_argument("--wait-event", action="store_true",
                    help="block until an event needs this session, print it and exit: run it in the background "
                         "so its ending wakes the session")
    ap.add_argument("--ack", nargs=2, metavar=("EVENT", "WORDS"))
    ap.add_argument("--busy-until", nargs=2, metavar=("TIME", "WORDS"))
    ap.add_argument("--stop", metavar="JOB")
    ap.add_argument("--state", metavar="JOB", help="one job's phase and last line, as JSON (remote.py asks it)")
    ap.add_argument("--requeue", metavar="JOB", help="queue a job lost with a restart again, as it was asked")
    ap.add_argument("--all", action="store_true", help="every session's jobs and events, not only this one's")
    ap.add_argument("--force", action="store_true", help="with --stop or --requeue: another session's job, on the person's say")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    sid = None if args.all else session()
    if args.watch:
        return watch(sid=sid)
    if args.requeue:
        print(f"queued again as {requeue(args.requeue, args.force)}")
        return
    if args.ack:
        n = ack(*args.ack, sid=session())       # an ack is always this session's, --all or not
        print(f"{n} event{'s' if n != 1 else ''} marked dealt with")
        return
    if args.busy_until and args.busy_until[0] == "off":
        busy_file(sid).unlink(missing_ok=True)
        print("the commitment is ended: " + args.busy_until[1])
        return
    if args.busy_until and args.busy_until[0] == "done":
        home().mkdir(parents=True, exist_ok=True)
        records.write(busy_file(sid), {"until": None, "done": True, "why": args.busy_until[1], "set": time.time(),
                                       "session": sid})
        print("busy until it is all done: an idle event whenever no work is getting done, until "
              "./ty jobs --busy-until off WORDS")
        return
    if args.wait:
        return wait_job(args.wait)
    if args.wait_event:
        return wait_event(sid=session())
    if args.busy_until:
        until = until_time(args.busy_until[0])
        home().mkdir(parents=True, exist_ok=True)
        records.write(busy_file(sid), {"until": until, "why": args.busy_until[1], "set": time.time(), "session": sid})
        print(f"busy until {_clock(until)}: an idle event whenever nothing runs or is queued before then")
        return
    if args.stop:
        print(stop(args.stop, args.force))
        return
    if args.state:
        found = find(args.state)
        j = look(found) if found else {"phase": "unknown", "log": ""}
        print(json.dumps({"phase": j["phase"], "last_line": _last_line(j["log"]) if j["log"] else None}))
        return
    if args.name:
        return tail(args.name, args.tail or 20)
    import interface
    if args.json:
        return interface.emit(interface.run("jobs", lambda: report(sid=sid)))
    print(text(report(sid=sid)))


if __name__ == "__main__":
    sys.exit(main())
