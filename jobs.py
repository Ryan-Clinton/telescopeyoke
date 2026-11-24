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
KINDS = ("finite", "service", "routine", "remote")
NEEDS = ("camera", "mount", "cpu", "gpu")
CURRENT = None              # this process's job, once it has one


def home():
    return Path(config.DATA) / "cache" / "jobs"


def folder(job_id):
    return home() / job_id


def new_id(name):
    clean = "".join(c if c.isalnum() or c in "-_" else "-" for c in name)[:40] or "job"
    return f"{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}-{clean}-{secrets.token_hex(3)}"


def started_at(pid):
    """The process's start time as the kernel counts it (Linux), so a process
    number given to another process since is not taken for this one."""
    try:
        return Path(f"/proc/{int(pid)}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, ValueError, IndexError):
        return None


def boot_id():
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return None


def running(pid, start=None):
    if not pid or not host.alive(pid):
        return False
    try:
        if Path(f"/proc/{int(pid)}/stat").read_text().rsplit(")", 1)[1].startswith(" Z"):
            return False        # ended, not yet reaped
    except (OSError, ValueError):
        pass
    return start is None or started_at(pid) in (None, start)


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
                      "after": [], "needs": [], "why": None, "queued": None, "started": time.time()}
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
            self.progress["operation"] = str(words)
            self.progress["operation_since"] = time.time()
            self.progress["deadline_s"] = None
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
        self._save()
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

def launch(name, command, after=(), needs=(), kind="finite", why=None, wait=False, cwd=None, log=None):
    """Start COMMAND as a job; returns its ID (or its exit code with wait).
    `log`: a file of its own for its lines (a session's patrol.log, which
    others read), instead of the job's log.txt."""
    if not command:
        raise SystemExit("no command given after --")
    prune()
    job_id = new_id(name)
    folder(job_id).mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, str(Path(__file__).resolve()), "_supervise", job_id, name, kind,
            ",".join(after), ",".join(needs), why or "", "1" if wait else "0", "--", *command]
    if wait:
        return supervise(job_id, name, kind, list(after), list(needs), why, True, command, log)
    options = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
               "cwd": str(cwd or os.getcwd()), "env": dict(os.environ, TY_JOB_LOG=str(log or ""))}
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
                       "log": str(self.dir / "log.txt")}
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
              "log": str(log_path or d / "log.txt")}
    log_path = Path(record["log"])

    def put(**fields):
        record.update(fields)
        try:
            records.write(d / "process.json", record, indent=None)
        except Exception:
            pass

    put()
    while True:
        verdict = ready(job_id, after, needs, record["queued"])
        if verdict is True:
            break
        if isinstance(verdict, str):
            put(phase="blocked", blocked=verdict, ended=time.time())
            return 1
        time.sleep(QUEUE_EVERY_S)

    env = dict(os.environ, PYTHONUNBUFFERED="1", TY_JOB=job_id, TY_JOB_ADOPT=str(os.getpid()))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = open(log_path, "ab", buffering=0)
    try:
        child = subprocess.Popen(command, stdin=subprocess.DEVNULL, env=env,
                                 stdout=subprocess.PIPE if wait else log, stderr=subprocess.STDOUT)
    except OSError as problem:
        log.write(f"could not start: {problem}\n".encode())
        put(phase="exited", exit_code=127, started=time.time(), ended=time.time())
        return 127
    put(phase="running", pid=child.pid, pid_start=started_at(child.pid), started=time.time())
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
                    signal.signal(sig, lambda number, _frame: child.send_signal(number))
                except (OSError, ValueError):
                    pass
        for line in child.stdout:
            log.write(line)
            try:
                sys.stdout.buffer.write(line)
                sys.stdout.flush()
            except (OSError, ValueError):
                pass
        child.wait()
    else:
        while _wait_for(child, 60) is None:
            cap(log_path)
    log.close()
    put(phase="exited", exit_code=child.returncode, ended=time.time())
    return child.returncode


def _wait_for(child, seconds):
    try:
        return child.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        return None


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
    named = sorted((p.name for p in home().glob(f"*-{word}-*") if p.is_dir()), reverse=True)
    return named[0] if named else None


def holds_now(listing=None):
    """{need: who holds it} for camera and mount, from the camera's lock,
    the mount's owner and the jobs that say they hold something."""
    held = {}
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
            for h in j.get("holds") or []:
                held.setdefault(h, f"job {j['name']}")
    return held


def ready(job_id, after, needs, queued_at):
    """True when the job may start, a reason when it never will, else None."""
    for condition in after:
        word, _, what = condition.partition(":")
        other = find(word)
        if other is None:
            return f"no job {word}"
        o = look(other)
        if what == "ended":
            if o["phase"] in ("done", "failed", "vanished", "blocked"):
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
        if o["phase"] in ("failed", "vanished", "blocked") or (o["phase"] == "done" and what):
            return f"{o['name']} {o['phase']} before {condition}"
        return None
    if needs:
        listing = look_all()
        held = holds_now(listing)
        if any(n in held for n in needs if n in ("camera", "mount")):
            return None
        if "gpu" in needs and any(j["phase"] == "running" and "gpu" in (j.get("needs") or [])
                                  and j["id"] != job_id for j in listing):
            return None
        if "cpu" in needs:
            try:
                if os.getloadavg()[0] > max(1, (os.cpu_count() or 2) - 1):
                    return None
            except (OSError, AttributeError):
                pass
        # First come, first served among jobs queued for the same thing.
        if any(j["phase"] == "queued" and j["id"] != job_id and (j.get("queued") or 0) < queued_at
               and set(j.get("needs") or []) & set(needs) & {"camera", "mount", "gpu"} for j in listing):
            return None
    return True


def wanted(need):
    """Whether any queued job waits for `need` (a hold can end early for it)."""
    return any(j["phase"] == "queued" and need in (j.get("needs") or []) for j in look_all())


def stop(word):
    job_id = find(word)
    if not job_id:
        raise SystemExit(f"no job {word}")
    j = look(job_id)
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
         "stall": None, "log": str(log_path)}
    phase = p.get("phase")
    alive = running(p.get("pid"), p.get("pid_start"))
    if phase == "queued":
        phase = "queued" if running(p.get("supervisor"), p.get("supervisor_start")) else "vanished"
    elif phase == "blocked":
        pass
    elif p.get("exit_code") is not None:
        failed = p["exit_code"] != 0 or str(g.get("result") or "").startswith("failed")
        phase = "failed" if failed else "done"
    elif phase == "running" and alive:
        phase = "waiting" if g.get("waiting") else "running"
    elif phase == "running" and p.get("own") and g.get("result") and not alive:
        phase = "failed" if str(g["result"]).startswith("failed") else "done"
    elif phase == "running" and not p.get("pid") and running(p.get("supervisor"), p.get("supervisor_start")):
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
        since = j["last_progress"] or j.get("started") or now
        limit = g["deadline_s"] * DEADLINE_MARGIN[0] + DEADLINE_MARGIN[1]
        if now - since > limit:
            return f"no progress for {_ago(now - since)} on \"{g.get('operation')}\" (it said {_ago(g['deadline_s'])})"
        return None
    last = max(filter(None, (j["last_output"], j["last_progress"], j.get("started"))), default=now)
    if now - last > QUIET_S:
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
                     "vanished": "its process is gone and no ending was recorded",
                     "blocked": "what it was queued behind will not happen"}[j["phase"]]
            out.append({"id": f"{j['id']}:end", "job": j["id"], "name": j["name"], "kind": j["phase"],
                        "words": "; ".join(w for w in (words, result) if w) or "finished", "wake": True,
                        "at": j.get("ended") or j["last_output"] or now})
    if j["stall"]:
        since = int(j["last_progress"] or j["last_output"] or 0)
        out.append({"id": f"{j['id']}:stall:{since}", "job": j["id"], "name": j["name"], "kind": "stalled",
                    "words": j["stall"], "wake": True, "at": now})
    return out


def busy():
    return _read(home() / "busy.json")


def idle_event(listing, now=None):
    """An idle event while the owner's busy-until stands and nothing runs."""
    now = now or time.time()
    b = busy()
    if not b or now > b.get("until", 0):
        return None
    if any(j["phase"] in ("queued", "running", "waiting", "stalled") and j["kind"] in ("finite", "remote")
           for j in listing):
        return None
    since = max([b.get("set", 0)] + [j.get("ended") or 0 for j in listing])
    if now - since < IDLE_AFTER_S:
        return None
    return {"id": f"idle:{int(since)}", "job": None, "name": "idle", "kind": "idle", "wake": True, "at": now,
            "words": f"nothing running or queued for {_ago(now - since)}, and the owner asked for work until "
                     f"{_clock(b['until'])} ({b.get('why') or 'no reason given'})"}


def _acked():
    return {a.get("event"): a for a in _lines(home() / "acks.jsonl")}


def open_events(listing=None, now=None):
    now = now or time.time()
    listing = look_all(now) if listing is None else listing
    acked = _acked()
    out = [e for j in listing for e in wake_events(j, now) if e["id"] not in acked]
    # A timer's routine run that keeps failing is one event, its newest, not one every ten minutes.
    routine = {j["id"] for j in listing if j["kind"] == "routine"}
    newest = {}
    for e in out:
        if e.get("job") in routine:
            newest[e["name"]] = e
    out = [e for e in out if e.get("job") not in routine or newest.get(e["name"]) is e]
    idle = idle_event(listing, now)
    if idle and idle["id"] not in acked:
        out.append(idle)
    return sorted(out, key=lambda e: e.get("at") or 0)


def ack(event, words):
    if not words:
        raise SystemExit("say what was done about it: ./ty jobs --ack EVENT \"started the Moon video\"")
    targets = [e["id"] for e in open_events()] if event == "all" else [event]
    for t in targets:
        _append(home() / "acks.jsonl", {"event": t, "words": words, "at": time.time()})
    return len(targets)


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


def camera_state(held):
    state = _read(Path(config.DATA) / "cache" / "keeper.json") or {}
    keeper = None
    try:
        import keeper as k
        keeper = k.running()
    except Exception:
        pass
    if keeper and state:
        sensor, target = state.get("sensor_c"), state.get("target_c")
        return {"by": "the keeper", "sensor_c": sensor, "target_c": target, "ready": state.get("ready"),
                "words": f"the keeper holds it: sensor {sensor} °C, target {target} °C"}
    if "camera" in held:
        return {"by": held["camera"], "words": f"held by {held['camera']}"}
    return {"by": None, "words": "free"}


def report(now=None):
    now = now or time.time()
    listing = look_all(now)
    held = holds_now(listing)

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
    return {"open_events": [{k: e.get(k) for k in ("id", "name", "kind", "words", "at", "ask")}
                            for e in open_events(listing, now)],
            "jobs": active, "recent": recent, "computer": computer(),
            "camera": camera_state(held), "mount": {"by": held.get("mount"),
                                                    "words": f"held by {held['mount']}" if "mount" in held
                                                    else "free"},
            "busy_until": busy()}


def text(r, now=None):
    now = now or time.time()
    lines = []
    if r["open_events"]:
        lines.append("Needs the agent (ack each: ./ty jobs --ack EVENT \"what was done\"):")
        for e in r["open_events"]:
            ask = f" Ends with: {e['ask']}" if e.get("ask") else ""
            lines.append(f"  ! {_clock(e.get('at'))} {e['name']} {e['kind']}: {e['words']}{ask}  [{e['id']}]")
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
    if b and b.get("until", 0) > now:
        lines.append(f"Busy until {_clock(b['until'])}: {b.get('why')}")
    if not r["jobs"] and not r["open_events"]:
        lines.insert(0, "No job running, waiting or queued.")
    return "\n".join(lines)


def watch(every=15):
    """One line per event that needs the agent, the ones open now first;
    nothing else, ever."""
    shown = set()
    while True:
        try:
            for e in open_events():
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
        ap.add_argument("--wait", action="store_true", help="run in the foreground, its output passed on too")
        args = ap.parse_args(argv[1:cut])
        needs = [n for n in args.needs.split(",") if n]
        unknown = [n for n in needs if n not in NEEDS]
        if unknown:
            ap.error(f"unknown needs: {', '.join(unknown)}")
        result = launch(args.name, argv[cut + 1:], args.after, needs, args.kind, args.why, args.wait)
        if args.wait:
            sys.exit(result)
        j = look(result)
        print(f"{result} {j['phase']}  log: {j['log']}")
        return
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("name", nargs="?", help="a job, for --tail")
    ap.add_argument("--tail", type=int)
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--ack", nargs=2, metavar=("EVENT", "WORDS"))
    ap.add_argument("--busy-until", nargs=2, metavar=("TIME", "WORDS"))
    ap.add_argument("--stop", metavar="JOB")
    ap.add_argument("--state", metavar="JOB", help="one job's phase and last line, as JSON (remote.py asks it)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.watch:
        return watch()
    if args.ack:
        n = ack(*args.ack)
        print(f"{n} event{'s' if n != 1 else ''} marked dealt with")
        return
    if args.busy_until:
        until = until_time(args.busy_until[0])
        home().mkdir(parents=True, exist_ok=True)
        records.write(home() / "busy.json", {"until": until, "why": args.busy_until[1], "set": time.time()})
        print(f"busy until {_clock(until)}: an idle event whenever nothing runs or is queued before then")
        return
    if args.stop:
        print(stop(args.stop))
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
        return interface.emit(interface.run("jobs", report))
    print(text(report()))


if __name__ == "__main__":
    sys.exit(main())
