#!/usr/bin/env python3
"""What each command may do, in one place: read only, write files here,
use the hardware, or reach the outside world.

    ./policy.py ./mount.py goto M27            hardware
    ./policy.py ./mount.py goto M27 --dry-run  read_only
    ./policy.py --json ./patrol.py --sweep

Every command a person or an agent can run is classed once, here, and
everything that needs to know asks this: the safety hooks an agent works
behind, the tests that check a skill only pre-approves what is safe, and
the commands page. A new script fails the tests until it is given its
class, so nothing is left out by being new.

- read_only: looks, plans, dry-runs; changes nothing anywhere.
- local_write: writes files on this computer (stacks, records, caches,
  settings), or another computer of the person's own (restack.py --on).
  Nothing turns and no frame is taken.
- hardware: moves the mount or the focuser, takes frames with the camera,
  or talks to the handset or the motor board in a way that changes them.
- external: reaches someone or something outside: a message to the
  person's phone, lights and a speaker in the house, a published release.

A command is its script's class unless one of its words says otherwise;
--dry-run, --plan and --help make any command read_only, since every
script that takes them promises nothing is touched. Anything not known is
hardware: an unknown command is treated as the worst it could be.
Nothing here moves the mount or uses the camera.
"""
import argparse
import json
import shlex
import sys
from pathlib import Path

CLASSES = ("read_only", "local_write", "hardware", "external")
SAFE = ("--dry-run", "--plan", "--help", "-h")

# script: (its class, {a word in the command: the class it gives instead}).
# A word is a subcommand or a flag; the first that matches decides.
COMMANDS = {
    "agent.py": ("read_only", {}),
    "alert.py": ("external", {"--test": "external"}),
    "app.py": ("hardware", {}),                 # the application drives the rig on request
    "brokers.py": ("local_write", {"--follow": "hardware"}),
    "build_catalogue.py": ("local_write", {}),
    "calibrate.py": ("hardware", {}),
    "camera_setup.py": ("local_write", {"--check": "read_only"}),
    "camera_test.py": ("hardware", {}),
    "candidates.py": ("read_only", {"--dismiss": "local_write", "--reopen": "local_write"}),
    "clouds.py": ("read_only", {}),
    "compare.py": ("local_write", {}),
    "console.py": ("hardware", {}),             # its server runs the other scripts on request
    "depth.py": ("local_write", {}),
    "difference.py": ("local_write", {}),
    "doctor.py": ("read_only", {}),
    "focus.py": ("hardware", {"--report": "read_only"}),
    "focuser.py": ("hardware", {}),
    "forced.py": ("local_write", {}),
    "horizon.py": ("hardware", {"--show": "read_only", "--forget": "local_write"}),
    "landmark.py": ("hardware", {"list": "read_only"}),
    "liveview.py": ("hardware", {}),
    "mcp_server.py": ("read_only", {}),
    "mosaic.py": ("local_write", {}),
    "mount.py": ("hardware", {"status": "read_only"}),
    "notify.py": ("external", {}),
    "panorama.py": ("local_write", {"show": "read_only"}),
    "patrol.py": ("hardware", {"--analyse": "local_write", "--sweep": "local_write"}),
    "planet.py": ("hardware", {"--restack": "local_write"}),
    "plant.py": ("local_write", {}),
    "polaralign.py": ("hardware", {}),
    "polaris.py": ("hardware", {}),
    "policy.py": ("read_only", {}),
    "process.py": ("local_write", {}),
    "recover.py": ("local_write", {}),
    "reference.py": ("read_only", {"--make": "local_write"}),
    "release.py": ("local_write", {"--publish": "external"}),
    "remote.py": ("local_write", {}),
    "replay.py": ("local_write", {}),
    "report.py": ("local_write", {}),
    "restack.py": ("local_write", {}),
    "serve.py": ("local_write", {}),            # the status page: read-only to its visitors
    "shoot.py": ("hardware", {}),
    "skywatch.py": ("hardware", {}),
    "snap.py": ("hardware", {}),
    "solve.py": ("local_write", {}),
    "starwatch.py": ("hardware", {"--measure": "local_write", "--history": "read_only"}),
    "sungrazer.py": ("local_write", {}),
    "tonight.py": ("read_only", {}),
    "tour.py": ("local_write", {}),
    "transits.py": ("local_write", {}),
    "variables.py": ("local_write", {}),
    "vet.py": ("local_write", {}),
    "watch.py": ("hardware", {}),
}

# ty's own subcommands; the ones it passes straight to a script are classed
# as that script.
TY = {"run": "hardware"}
TY_PASSES = {"mount": "mount.py", "tonight": "tonight.py", "shoot": "shoot.py", "focus": "focus.py",
             "solve": "solve.py", "restack": "restack.py", "console": "console.py"}


def script_of(word):
    """The script a command's first word names, or None: ./mount.py,
    mount.py, python3 mount.py and a full path are all mount.py."""
    name = word.replace("\\", "/").rsplit("/", 1)[-1]
    if name in ("ty", "ty.cmd"):
        return "ty"
    return name if name.endswith(".py") else None


LAUNCHERS = {"python", "python3", "python.exe", "python3.exe", "py", "py.exe", "systemd-inhibit", "nohup",
             "timeout", "env", "exec"}


SHELLS = {"bash", "sh", "zsh", "dash", "powershell", "powershell.exe", "pwsh", "pwsh.exe", "cmd", "cmd.exe",
          "xargs", "eval", "source", "."}


def unwrapped(words):
    """The command without what launches it: python3 -u, systemd-inhibit
    --what=sleep, timeout 900 and the like."""
    words = list(words)
    while words and Path(words[0]).name.lower() in LAUNCHERS:
        words = words[1:]
        while words and (words[0].startswith("-") or words[0].replace(".", "").isdigit() or "=" in words[0]):
            words = words[1:]
    return words


def classify(argv):
    """The class of one command, as its words: ["./mount.py", "goto", "M27"]."""
    words = unwrapped(argv)
    if not words:
        return "hardware"
    script, rest = script_of(words[0]), words[1:]
    if script == "ty":
        if rest and rest[0] in TY_PASSES:
            script, rest = TY_PASSES[rest[0]], rest[1:]
        elif rest and not rest[0].startswith("-"):
            return TY.get(rest[0], "read_only")
        else:
            return "read_only"
    if script not in COMMANDS:
        return "hardware"
    if any(w in SAFE for w in rest):
        return "read_only"
    default, instead = COMMANDS[script]
    for w in rest:
        if w.split("=", 1)[0] in instead:
            return instead[w.split("=", 1)[0]]
    return default


def classify_text(command):
    """The worst class among the project commands in a shell line, split at
    ;, &&, || and |; None if it runs none of them. A line that cannot be
    read is hardware."""
    command = command.replace("\\", "/")   # a Windows path: C:\telescopeyoke\mount.py
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        words = list(lexer)
    except ValueError:
        return "hardware"
    parts, part = [], []
    for w in words:
        if w and set(w) <= set(";&|"):
            parts.append(part)
            part = []
        else:
            part.append(w)
    parts.append(part)
    found = [classify(p) for p in parts if unwrapped(p) and script_of(unwrapped(p)[0])]
    # A command run inside another (bash -c "...", $(...), xargs, eval)
    # cannot be read word by word here: if one of ours might be in it, it
    # is taken to be the worst it could be.
    hidden = any(Path(p[0]).name.lower() in SHELLS for p in parts if p) or any(m in command for m in ("$(", "`", "<("))
    if hidden and any(name in command for name in [*COMMANDS, "ty "]):
        found.append("hardware")
    return max(found, key=CLASSES.index) if found else None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", nargs=argparse.REMAINDER, help="the command, as it would be typed")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    if not args.command:
        ap.error("give a command")
    kind = classify(args.command)
    print(json.dumps({"command": args.command, "class": kind}) if args.json else kind)


if __name__ == "__main__":
    sys.exit(main())
