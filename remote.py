"""Heavy work on another computer: restack.py --on HOST.

The laptop at the telescope has four slow cores and goes to sleep on
battery; a desktop in the house may have sixteen. This sends the sessions'
raw frames, the calibration masters and the code to HOST over SSH, runs
restack.py there, and brings the picture back to where it would have been
written here. HOST is a name from ~/.ssh/config (which says the address,
port and user). The SSH login there must be a Unix-like shell with rsync:
on the Windows desktop it is Ubuntu under WSL, reached through a port
forwarded from Windows. It needs Python with the project's packages: its
~/telescopeyoke-laptop/venv, ~/telescopeyoke/.venv, or python3.

Everything goes under ~/telescopeyoke-laptop/remote on HOST, apart from any
checkout of the project there, so nothing being worked on is touched. Raw
frames already sent are not sent again (rsync), so a second stack of the
same sessions starts at once.
"""
import json
import secrets
import shlex
import subprocess
import sys
import time
from pathlib import Path

import config
import interface
import jobs
import records
import stacking

ROOT = Path(__file__).parent
PLACE = "telescopeyoke-laptop/remote"     # under HOST's home folder
PYTHONS = ("telescopeyoke-laptop/venv/bin/python", "telescopeyoke/.venv/bin/python", "python3")
BACK = ("final.fits", "final.jpg", "restack.json")


def ssh(host, command, **kwargs):
    return subprocess.run(["ssh", "-o", "BatchMode=yes", host, command], **kwargs)


def rsync(sources, target, *options):
    done = subprocess.run(["rsync", "-a", "--partial", *options, *map(str, sources), target])
    if done.returncode:
        raise interface.Refusal("REMOTE_FAILED", f"Copying to or from {target.split(':')[0]} failed "
                                f"(rsync exit {done.returncode}).")


def there(path):
    """Where a file under config.DATA goes on HOST, relative to its home."""
    return f"{PLACE}/data/{Path(path).resolve().relative_to(config.DATA.resolve()).as_posix()}"   # HOST's shell is Unix-like


def python_on(host):
    for python in PYTHONS:
        found = ssh(host, f"cd && {python} -c 'import astropy, scipy, numpy, PIL' 2>/dev/null && echo {python}",
                    capture_output=True, text=True, timeout=60)
        if found.returncode == 0 and found.stdout.strip():
            return found.stdout.strip()
    raise interface.Refusal("REMOTE_FAILED", f"{host} has no Python with astropy, scipy, numpy and Pillow: "
                            "make ~/telescopeyoke-laptop/venv there, or install them for python3.")


def equipment():
    """This rig's camera and light-path settings as TOML, and nothing else: no
    site, no keys, no serial numbers. Without them the copy there took the
    183M for a camera with scaled darks, used no dark, and still labelled the
    stack calibrated (22 November 2026)."""
    given = config._read(config.FILE) if config.FILE.exists() else {}
    lines = []

    def table(name, values):
        lines.append(f"[{name}]")
        lines.extend(f"{k} = {json.dumps(v)}" for k, v in values.items() if not isinstance(v, dict) and k != "serial"
                     and v is not None)
        for k, v in values.items():
            if isinstance(v, dict):
                table(f"{name}.{k}", v)
    for section in ("scope", "camera", "cameras", "trains"):
        if section in given:
            table(section, given[section])
    return "\n".join(lines) + "\n"


def restack(host, sessions, options, say=print):
    """Stack `sessions` (folders under config.DATA) on HOST with restack.py
    `options`, and bring the result back. Returns the folder it is in here."""
    sessions = [Path(s).resolve() for s in sessions]
    for s in sessions:
        try:
            s.relative_to(config.DATA.resolve())
        except ValueError:
            raise interface.Refusal("INVALID_REQUEST", f"{s} is not under {config.DATA}: only saved "
                                    "sessions can be stacked elsewhere.") from None
    reach = ssh(host, "true", capture_output=True, text=True, timeout=30)
    if reach.returncode:
        raise interface.Refusal("REMOTE_FAILED", f"Cannot reach {host} by SSH: {reach.stderr.strip()}")
    python = python_on(host)
    say(f"sending the code and {len(sessions)} session(s) to {host}")
    ssh(host, f"mkdir -p {PLACE}/code " + " ".join(shlex.quote(there(s)) for s in sessions), check=True)
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    sent = subprocess.run(["rsync", "-a", "--from0", "--files-from=-", "./", f"{host}:{PLACE}/code/"],
                          cwd=ROOT, input=tracked)
    if sent.returncode:
        raise interface.Refusal("REMOTE_FAILED", f"Sending the code to {host} failed.")
    for s in sessions:
        rsync([f"{s}/"], f"{host}:{there(s)}/", "--copy-links", "--include=light-*.fits", "--include=*.json",
              "--include=*.jsonl", "--exclude=*")
    ssh(host, f"cat > {PLACE}/code/config.toml", input=equipment(), text=True, check=True)
    camera = config.camera_name()
    if stacking.CALIBRATION.is_dir():
        masters = "calibration" if stacking.CALIBRATION.parent == config.DATA else f"{camera}/calibration"
        ssh(host, f"mkdir -p {PLACE}/data/{masters}", check=True)
        rsync([f"{stacking.CALIBRATION}/"], f"{host}:{PLACE}/data/{masters}/", "--copy-links")
    runner = python if python == "python3" else f"~/{python}"
    # The copy there has no git history: say which commit it is, so its
    # records' provenance names the code that really ran.
    sha, changed = records.commit()
    code = f"TY_CODE_COMMIT={sha}{'+changed' if changed else ''} " if sha else ""
    # A job of its own there (jobs.py, in the foreground under nohup): its
    # lines come back as they are printed, and if the connection drops it
    # carries on there and is followed until it ends (docs/job-reporting-spec.md).
    name = f"restack-remote-{secrets.token_hex(3)}"
    data = f"TY_DATA=~/{PLACE}/data"
    command = (f"cd ~/{PLACE}/code && {data} TY_CAMERA={shlex.quote(camera)} TY_NO_WATCH=1 PYTHONUNBUFFERED=1 "
               f"{code}nohup {runner} jobs.py bg {name} --wait -- {runner} restack.py "
               + " ".join(shlex.quote(f"../{there(s)[len(PLACE) + 1:]}") for s in sessions)
               + "".join(f" {shlex.quote(o)}" for o in options))
    say(f"stacking on {host} (its job there: {name})")
    jobs.current().expect(6 * 3600, f"stacking on {host}")
    ran = ssh(host, command)
    if ran.returncode == 255:          # the connection, not the stack: follow the job there
        ran = follow(host, f"cd ~/{PLACE}/code && {data} {runner} jobs.py --state {name}", say)
    if ran.returncode:
        raise interface.Refusal("REMOTE_FAILED", f"restack.py failed on {host} (exit {ran.returncode}).")
    folder = sessions[0]
    if len(sessions) > 1:     # the folder restack.py chose there: one filter's goes to combined-FILTER
        heads = [stacking.load_light(stacking.one_setting(stacking.on_target(sorted(s.glob("light-*.fits")),
                                                                             lambda *_: None),
                                                          lambda *_: None)[0])[1] for s in sessions]
        bands = {str(h.get("FILTER")) for h in heads if h.get("FILTER")}
        folder = sessions[0].parent / ("combined" + (f"-{bands.pop()}" if len(bands) == 1 else ""))
    folder.mkdir(exist_ok=True)
    rsync([f"{host}:{there(folder)}/{name}" for name in BACK], f"{folder}/", "--ignore-missing-args")
    web = config.DATA / "web"
    web.mkdir(exist_ok=True)
    rsync([f"{host}:{PLACE}/data/web/{folder.parent.name}-final.jpg"], f"{web}/", "--ignore-missing-args")
    # The record says where things are here, not there.
    record = folder / "restack.json"
    if record.exists():
        text = record.read_text(encoding="utf-8")
        home = ssh(host, "echo $HOME", capture_output=True, text=True).stdout.strip()
        for there_data in (f"{home}/{PLACE}/data", "../data"):    # as restack.py was given them
            text = text.replace(f'"{there_data}/', f'"{config.DATA}/')
        record.write_text(text, encoding="utf-8")
    say(f"brought back to {folder}")
    return folder


def follow(host, ask, say, every=120):
    """The job on HOST after the connection dropped: asked every two minutes
    until it ends, however long HOST cannot be reached."""
    say(f"the connection to {host} dropped; the stack goes on there, asked every {every // 60} minutes")
    jobs.current().reading(f"{host} unreachable; its stack goes on there")
    while True:
        time.sleep(every)
        try:
            got = ssh(host, ask, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            continue
        if got.returncode:
            continue
        try:
            state = json.loads(got.stdout)
        except ValueError:
            continue
        jobs.current().reading(f"on {host}: {state.get('phase')}, {state.get('last_line') or ''}"[:200])
        if state.get("phase") in ("done", "failed", "vanished", "blocked"):
            say(f"the stack on {host} ended: {state.get('phase')}")
            return subprocess.CompletedProcess(ask, 0 if state["phase"] == "done" else 1)


if __name__ == "__main__":
    sys.exit("Use restack.py --on HOST.")
