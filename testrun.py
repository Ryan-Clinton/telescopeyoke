#!/usr/bin/env python3
"""Run the tests on the desktop and bring back only what failed.

    ./ty test-run                      the whole suite on the desktop (about 12 minutes)
    ./ty test-run tests/test_mount.py  some of it
    ./ty test-run -k meridian          the tests matching a word
    ./ty test-run --here               on this computer instead
    ./ty test-run --json

The checkout as it is now, committed or not, is copied to the desktop
(~/telescopeyoke-laptop/tests, tracked and new files, nothing git ignores) and the
tests run there with its own Python (~/telescopeyoke/.venv). The answer is
the counts and, for each failure, its name and its first lines: what an
agent needs to start on it, without the run's whole output. Run it in the
background; nothing waits on it.

Nothing here moves the mount or uses the camera, and the real night's
files are never copied: the tests make their own.
"""
import argparse
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

import interface
import remote

ROOT = Path(__file__).parent
HOST = "desktop"
PLACE = "telescopeyoke-laptop/tests"
PYCACHE = "telescopeyoke-laptop/pycache"   # Python's compiled files for the test run
FIRST_LINES = 8      # of each failure, kept
WIDE = "1000"        # columns pytest is told it has, so it never trims a failure's reason


def files():
    """The checkout as it is: tracked files and new ones git does not ignore."""
    listed = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                            capture_output=True)
    if listed.returncode:
        raise interface.Refusal("REMOTE_FAILED", f"{ROOT} is not a git checkout: test-run sends what git "
                                "tracks, so it runs from one.")
    listed = listed.stdout
    return b"\0".join(p for p in listed.split(b"\0") if p and (ROOT / p.decode()).is_file())


def summary(output):
    """(counts, failures) from pytest's -q -rf output."""
    counts = {k: 0 for k in ("passed", "failed", "skipped", "errors")}
    tail = output.strip().splitlines()[-1] if output.strip() else ""
    for n, word in re.findall(r"(\d+) (passed|failed|skipped|errors?)", tail):
        counts["errors" if word.startswith("error") else word] = int(n)
    seconds = re.search(r"in ([\d.]+)s", tail)
    failures = []
    for line in output.splitlines():
        found = re.match(r"(FAILED|ERROR) (\S+)(?: - (.*))?", line)
        if found:
            name = found.group(2)
            block = output.split(f"_ {name.split('::')[-1]} _", 1)
            detail = block[1].strip().splitlines()[:FIRST_LINES] if len(block) > 1 else []
            # With no terminal pytest trims the reason to fit 80 columns, or
            # leaves it out; then the exception's own line stands in for it.
            why = (found.group(3) or "").strip() or next((d[1:].strip() for d in detail if d.startswith("E ")), "")
            failures.append({"test": name, "why": why, "first_lines": detail})
    return dict(counts, seconds=float(seconds.group(1)) if seconds else None), failures


def run(args, say=print, runner=subprocess.run):
    chosen = [*args.tests, *(["-k", args.k] if args.k else [])]
    began = time.monotonic()
    if args.here:
        done = runner([sys.executable, "-m", "pytest", "-q", "-rfE", "-p", "no:cacheprovider", *chosen], cwd=ROOT,
                      capture_output=True, text=True, env={**os.environ, "COLUMNS": WIDE})
        where = "here"
    else:
        python = remote.python_on(HOST)
        say(f"copying the checkout to {HOST}")
        sent = runner(["rsync", "-a", "--delete", "--from0", "--files-from=-", "./", f"{HOST}:{PLACE}/"], cwd=ROOT,
                      input=files())
        if sent.returncode:
            raise interface.Refusal("REMOTE_FAILED", f"Copying the checkout to {HOST} failed.")
        runner_python = python if python == "python3" else f"~/{python}"
        say(f"running the tests on {HOST}")
        done = runner(["ssh", "-o", "BatchMode=yes", HOST,
                       # Compiled files kept apart from the copy: ones left in it name the folder they
                       # were made in (20 October 2026: after a move, a traceback test read the old one).
                       f"cd ~/{PLACE} && COLUMNS={WIDE} PYTHONPYCACHEPREFIX=~/{PYCACHE} "
                       f"{runner_python} -m pytest -q -rfE -p no:cacheprovider "
                       + " ".join(shlex.quote(c) for c in chosen)], capture_output=True, text=True)
        where = HOST
    counts, failures = summary(done.stdout)
    if not any(counts[k] for k in ("passed", "failed", "skipped", "errors")):
        raise interface.Refusal("REMOTE_FAILED", f"The tests did not run on {where}: "
                                f"{(done.stderr or done.stdout).strip()[-300:]}")
    answer = dict(counts, where=where, failures=failures, ok=not failures and not counts["failed"],
                  wall_seconds=round(time.monotonic() - began))
    say(f"{where}: {counts['passed']} passed, {counts['failed']} failed, {counts['skipped']} skipped"
        + (f", {counts['errors']} errors" if counts["errors"] else "") + f" in {answer['wall_seconds']} s")
    for f in failures:
        say(f"  {f['test']}: {f['why']}")
    return answer


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("tests", nargs="*", help="test files or tests (default: all)")
    ap.add_argument("-k", help="only tests matching this expression")
    ap.add_argument("--here", action="store_true", help="on this computer, not the desktop")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("test-run", lambda: run(args), args.json)


if __name__ == "__main__":
    sys.exit(main())
