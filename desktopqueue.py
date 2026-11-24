#!/usr/bin/env python3
"""A queue of long jobs for the desktop, so one finishing or failing never leaves it idle.

    ./desktopqueue.py add NAME --lane cpu|gpu --cores N --ram GB [--after NAME ...] -- COMMAND
    ./desktopqueue.py run       start whatever can run, for as long as anything is left
    ./desktopqueue.py status    each job and where its log is
    ./desktopqueue.py report    jobs finished, and how busy the CPU, GPU and disk were

The GPU runs one job at a time. CPU jobs run together while their cores and memory fit.
A failed job stops only the jobs waiting on it. Jobs survive the runner being restarted;
one lost with the computer runs once more. Runs only what was added: no camera, no mount.
"""
import argparse
import csv
import fcntl
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import records

HOME = Path(os.environ.get("TY_QUEUE", Path.home() / "telescopeyoke-laptop" / "queue"))
JOBS = HOME / "jobs.json"
USAGE = HOME / "usage.csv"
KEEP_FREE_GB = 4        # for Windows' share of WSL and the page cache
EVERY = 5
SAMPLE_EVERY = 30
MOST_TRIES = 2


def memory():
    info = {ln.split(":")[0]: int(ln.split()[1]) / 2 ** 20 for ln in open("/proc/meminfo")}
    return info["MemTotal"], info["MemAvailable"]


def alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return not Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].startswith(" Z")


def exit_file(name):
    return HOME / "logs" / f"{name}.exit"


def add(args):
    command = args.command
    if not command:
        sys.exit("no command given")

    def put(jobs):
        if args.name in jobs:
            sys.exit(f"{args.name} is already in the queue")
        missing = [a for a in args.after if a not in jobs]
        if missing:
            sys.exit(f"not in the queue: {', '.join(missing)}")
        jobs[args.name] = {"lane": args.lane, "cores": args.cores, "ram": args.ram, "after": args.after,
                           "command": " ".join(command) if len(command) == 1 else shlex.join(command),
                           "state": "waiting", "tries": 0, "added": time.time()}
    records.change(JOBS, put, empty={})


def start(name, job):
    logs = HOME / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    exit_file(name).unlink(missing_ok=True)
    # A job in the desktop's own records too (jobs.py), its lines kept as they come.
    tracked = f'{shlex.quote(sys.executable)} {shlex.quote(str(Path(__file__).with_name("jobs.py")))} bg ' \
              f'{shlex.quote(name)} --wait -- bash -c {shlex.quote(job["command"])}'
    wrapped = f'( {tracked} ); echo $? > "{exit_file(name)}"'
    with open(logs / f"{name}.log", "a") as log:
        return subprocess.Popen(["bash", "-c", wrapped], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                start_new_session=True)


def step(children):
    """Bring every job up to date and start what now fits."""
    for p in children:
        p.poll()
    children[:] = [p for p in children if p.returncode is None]

    def advance(jobs):
        for name, j in jobs.items():
            if j["state"] != "running":
                continue
            if exit_file(name).exists():
                code = exit_file(name).read_text().strip()
                j.update(state="done" if code == "0" else "failed", exit=code, ended=time.time())
            elif not alive(j["pid"]):
                j.update(state="waiting" if j["tries"] < MOST_TRIES else "failed", pid=None)
        changed = True
        while changed:
            changed = False
            for j in jobs.values():
                if j["state"] == "waiting" and any(jobs[a]["state"] in ("failed", "blocked") for a in j["after"]):
                    j["state"] = "blocked"
                    changed = True
        total, available = memory()
        running = [j for j in jobs.values() if j["state"] == "running"]
        cores = sum(j["cores"] for j in running)
        ram = sum(j["ram"] for j in running)
        gpu = any(j["lane"] == "gpu" for j in running)
        for name, j in jobs.items():
            if j["state"] != "waiting" or any(jobs[a]["state"] != "done" for a in j["after"]):
                continue
            if (j["lane"] == "gpu" and gpu) or cores + j["cores"] > os.cpu_count():
                continue
            if ram + j["ram"] > total - KEEP_FREE_GB or j["ram"] > available - KEEP_FREE_GB:
                continue
            p = start(name, j)
            children.append(p)
            j.update(state="running", pid=p.pid, tries=j["tries"] + 1, started=time.time())
            cores, ram, gpu = cores + j["cores"], ram + j["ram"], gpu or j["lane"] == "gpu"
        return any(j["state"] in ("waiting", "running") for j in jobs.values())
    return records.change(JOBS, advance, empty={})[1]


def cpu_ticks():
    v = list(map(int, open("/proc/stat").readline().split()[1:8]))
    return sum(v), v[3] + v[4]


def disk_busy_ms():
    return sum(int(p[12]) for p in map(str.split, open("/proc/diskstats")) if p[2].startswith("sd") and not p[2][-1].isdigit())


def gpu_now():
    tool = shutil.which("nvidia-smi") or "/usr/lib/wsl/lib/nvidia-smi"
    try:
        out = subprocess.run([tool, "--query-gpu=utilization.gpu,memory.used,power.draw", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout
        return [x.strip() for x in out.split(",")][:3]
    except (OSError, subprocess.SubprocessError):
        return ["", "", ""]


def sample(last):
    now, ticks, idle, busy = time.time(), *cpu_ticks(), disk_busy_ms()
    if last:
        total, available = memory()
        cpu = 100 * (1 - (idle - last[2]) / max(ticks - last[1], 1))
        disk = min(100, (busy - last[3]) / max(10 * (now - last[0]), 1))
        fresh = not USAGE.exists()
        with open(USAGE, "a", newline="") as f:
            w = csv.writer(f)
            if fresh:
                w.writerow(["time", "cpu_pct", "ram_used_gb", "disk_busy_pct", "gpu_pct", "gpu_mem_mb", "gpu_watts"])
            w.writerow([round(now), round(cpu, 1), round(total - available, 1), round(disk, 1), *gpu_now()])
    return now, ticks, idle, busy


def run(_args):
    HOME.mkdir(parents=True, exist_ok=True)
    lock = open(HOME / "runner.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit("a runner is already going")
    children, last, sampled = [], None, 0.0
    while step(children):
        if time.time() - sampled >= SAMPLE_EVERY:
            last, sampled = sample(last), time.time()
        time.sleep(EVERY)


def status(_args):
    for name, j in records.read(JOBS, {}).items():
        took = f"{((j.get('ended') or time.time()) - j['started']) / 60:.0f} min" if j.get("started") else ""
        print(f"{j['state']:8} {j['lane']:3} {name:32} {took:>8}  {HOME / 'logs' / (name + '.log')}")


def report(_args):
    jobs = records.read(JOBS, {})
    states = {}
    for j in jobs.values():
        states[j["state"]] = states.get(j["state"], 0) + 1
    print("jobs:", ", ".join(f"{v} {k}" for k, v in sorted(states.items())) or "none")
    if not USAGE.exists():
        return
    rows = list(csv.DictReader(open(USAGE)))
    if rows:
        mean = lambda k: sum(float(r[k]) for r in rows if r[k]) / max(sum(bool(r[k]) for r in rows), 1)
        low = lambda k, under: 100 * sum(float(r[k]) < under for r in rows if r[k]) / max(sum(bool(r[k]) for r in rows), 1)
        print(f"{len(rows)} samples over {(int(rows[-1]['time']) - int(rows[0]['time'])) / 3600:.1f} h")
        print(f"CPU mean {mean('cpu_pct'):.0f}%, under 25% for {low('cpu_pct', 25):.0f}% of the time")
        print(f"GPU mean {mean('gpu_pct'):.0f}%, under 25% for {low('gpu_pct', 25):.0f}% of the time")
        print(f"disk busy {mean('disk_busy_pct'):.0f}%, RAM used {mean('ram_used_gb'):.1f} GB")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="what", required=True)
    a = sub.add_parser("add")
    a.add_argument("name")
    a.add_argument("--lane", choices=("cpu", "gpu"), required=True)
    a.add_argument("--cores", type=int, required=True)
    a.add_argument("--ram", type=float, required=True, help="GB")
    a.add_argument("--after", nargs="*", default=[])
    for name in ("run", "status", "report"):
        sub.add_parser(name)
    argv = sys.argv[1:]
    cut = argv.index("--") if "--" in argv else len(argv)
    args = ap.parse_args(argv[:cut])
    args.command = argv[cut + 1:]
    {"add": add, "run": run, "status": status, "report": report}[args.what](args)


if __name__ == "__main__":
    main()
