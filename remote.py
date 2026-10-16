"""Heavy work on another computer: restack.py --on HOST.

The laptop at the telescope has four slow cores and goes to sleep on
battery; a desktop in the house may have sixteen. This sends the sessions'
raw frames, the calibration masters and the code to HOST over SSH, runs
restack.py there, and brings the picture back to where it would have been
written here. HOST is a name from ~/.ssh/config (which says the address,
port and user), and needs Python with the project's packages: its
~/telescopeyoke/.venv, or python3.

Everything goes under ~/telescopeyoke-remote on HOST, apart from any
checkout of the project there, so nothing being worked on is touched. Raw
frames already sent are not sent again (rsync), so a second stack of the
same sessions starts at once.
"""
import json
import shlex
import subprocess
import sys
from pathlib import Path

import config
import interface
import stacking

ROOT = Path(__file__).parent
PLACE = "telescopeyoke-remote"     # under HOST's home folder
PYTHONS = ("telescopeyoke/.venv/bin/python", "python3")
BACK = ("final.fits", "final.jpg", "restack.json", "discovery.fits", "discovery.json")


def ssh(host, command, **kwargs):
    return subprocess.run(["ssh", "-o", "BatchMode=yes", host, command], **kwargs)


def rsync(sources, target, *options):
    done = subprocess.run(["rsync", "-a", "--partial", *options, *map(str, sources), target])
    if done.returncode:
        raise interface.Refusal("REMOTE_FAILED", f"Copying to or from {target.split(':')[0]} failed "
                                f"(rsync exit {done.returncode}).")


def there(path):
    """Where a file under config.DATA goes on HOST, relative to its home."""
    return f"{PLACE}/data/{Path(path).resolve().relative_to(config.DATA.resolve()).as_posix()}"   # HOST runs Linux


def python_on(host):
    for python in PYTHONS:
        found = ssh(host, f"cd && {python} -c 'import astropy, scipy, numpy, PIL' 2>/dev/null && echo {python}",
                    capture_output=True, text=True, timeout=60)
        if found.returncode == 0 and found.stdout.strip():
            return found.stdout.strip()
    raise interface.Refusal("REMOTE_FAILED", f"{host} has no Python with astropy, scipy, numpy and Pillow: "
                            "make ~/telescopeyoke/.venv there, or install them for python3.")


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
        rsync([f"{s}/"], f"{host}:{there(s)}/", "--include=light-*.fits", "--include=*.json",
              "--include=*.jsonl", "--exclude=*")
    if stacking.CALIBRATION.is_dir():
        rsync([f"{stacking.CALIBRATION}/"], f"{host}:{PLACE}/data/calibration/")
    runner = python if python == "python3" else f"~/{python}"
    command = (f"cd ~/{PLACE}/code && TY_DATA=~/{PLACE}/data TY_NO_WATCH=1 {runner} restack.py "
               + " ".join(shlex.quote(f"../{there(s)[len(PLACE) + 1:]}") for s in sessions)
               + "".join(f" {shlex.quote(o)}" for o in options))
    say(f"stacking on {host}")
    ran = ssh(host, command)
    if ran.returncode:
        raise interface.Refusal("REMOTE_FAILED", f"restack.py failed on {host} (exit {ran.returncode}).")
    folder = sessions[0].parent / "combined" if len(sessions) > 1 else sessions[0]
    folder.mkdir(exist_ok=True)
    rsync([f"{host}:{there(folder)}/{name}" for name in BACK], f"{folder}/", "--ignore-missing-args")
    web = config.DATA / "web"
    web.mkdir(exist_ok=True)
    rsync([f"{host}:{PLACE}/data/web/{folder.parent.name}-final.jpg"], f"{web}/", "--ignore-missing-args")
    # The record says where things are here, not there.
    for name in ("restack.json", "discovery.json"):
        record = folder / name
        if record.exists():
            text = record.read_text(encoding="utf-8")
            home = ssh(host, "echo $HOME", capture_output=True, text=True).stdout.strip()
            for there_data in (f"{home}/{PLACE}/data", "../data"):    # as restack.py was given them
                text = text.replace(f'"{there_data}/', f'"{config.DATA}/')
            record.write_text(text, encoding="utf-8")
    say(f"brought back to {folder}")
    return folder


if __name__ == "__main__":
    sys.exit("Use restack.py --on HOST.")
