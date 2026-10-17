#!/usr/bin/env python3
"""The project's safety hooks for Claude Code: one rule each, all here.

    python3 .claude/hooks/guard.py RULE      the tool call's JSON on stdin

Claude Code runs this before a tool call (.claude/settings.json). Exit 0
lets the call through; exit 2 refuses it, and what is printed on stderr is
the reason Claude is given. Anything this cannot read, and any failure in
it, also exits 2: every rule fails closed, and .claude/settings.json sets
onFailure "block" as well, for the failures this script cannot catch (not
starting, a timeout). The rules (docs/skills-and-agents.md):

- motion-lock: nothing removes, moves, empties or replaces MOTION_LOCKED,
  by any path or pattern that would reach it, and no edit takes the code
  that reads it out.
- no-inline-hardware: no python -c, python -, or here-document that imports
  the mount, the focuser, the camera or the serial port: hardware only
  through the project's commands.
- no-motion: a subagent runs nothing policy.py calls hardware or external.
- no-self-kill: no pkill -f or pgrep -f, which match their own command line.
- no-secrets-out: nothing prints config.toml whole, its Telegram section,
  or a token from the environment.
"""
import fnmatch
import json
import os
import re
import shlex
import sys
from pathlib import Path

PROJECT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(PROJECT))
import policy  # noqa: E402

LOCK = "MOTION_LOCKED"
SHELL_TOOLS = ("Bash", "PowerShell")
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
HARDWARE_MODULES = ("mount", "direct", "focuser", "camera", "indi", "altair", "serial", "simulator")
READERS = {"cat", "ls", "stat", "test", "[", "head", "tail", "grep", "rg", "file", "wc", "less", "more",
           "git", "gc", "get-content", "get-item", "test-path", "dir", "type", "echo"}
CHANGERS = {"rm", "unlink", "mv", "cp", "ln", "truncate", "shred", "install", "dd", "tee", "touch", "chmod",
            "chattr", "del", "erase", "ren", "rename", "move", "copy", "rmdir", "remove-item", "ri", "move-item",
            "mi", "rename-item", "rni", "copy-item", "cpi", "set-content", "sc", "clear-content", "clc",
            "out-file", "new-item", "ni", "add-content", "ac", "set-itemproperty", "rsync", "find"}
SEPARATORS = (";", "&&", "||", "|", "&")
KEYWORDS = {"until", "while", "if", "then", "do", "else", "elif", "!", "time", "{", "("}
SETTINGS_FILE = re.compile(r"(^|[/@=])(config|rigs/[^/\s]+)\.toml$")    # an argument that is the settings file
WHOLE = {"cat", "less", "more", "bat", "head", "tail", "nl", "xxd", "od", "strings", "type", "gc", "get-content",
         "cp", "scp", "rsync", "curl", "base64", "tee", "copy", "copy-item", "vim", "vi", "nano", "view"}
SEARCHERS = {"grep", "egrep", "rg", "sed", "awk", "select-string", "sls", "findstr"}


class Refused(Exception):
    pass


def lock_path():
    return (PROJECT / LOCK).resolve()


def tokens(command):
    """The command line's words and operators. A line the shell's rules
    cannot split (an unmatched quote) is split more loosely instead, so it
    is still checked, word by word, rather than waved through or refused
    for its quoting alone."""
    # A here-document's text is what a command reads, not commands: a commit
    # message or a script's source. Rules that care what it says (inline
    # code naming the lock, importing the mount) read the raw line instead.
    command = re.sub(r"<<-?\s*(['\"]?)(\w+)\1([^\n]*)\n.*?\n\s*\2\s*(\n|$)", r"<< HEREDOC\3\n", command,
                     flags=re.S)
    command = command.replace("\\", "/").replace("\n", " ;\n")    # each line its own command
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>")
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return [w.strip("'\"") for w in re.findall(r"[;&|<>]+|[^\s;&|<>]+", command)]


def parts(command):
    """The command line as a list of commands, each a list of words."""
    found, part = [], []
    for w in tokens(command):
        if w in SEPARATORS:
            found.append(part)
            part = []
        else:
            part.append(w)
    found.append(part)
    return [p for p in found if p]


def resolved(word, cwd):
    p = Path(os.path.expanduser(word))
    return (p if p.is_absolute() else Path(cwd) / p).resolve()


def reaches_lock(word, cwd, recursive=False):
    """Whether a path or pattern as written would name the lock, or hold it."""
    lock = lock_path()
    try:
        target = resolved(word, cwd)
    except (OSError, RuntimeError, ValueError):
        return True
    if target == lock:
        return True
    if any(c in word for c in "*?[") and target.parent == lock.parent and fnmatch.fnmatch(LOCK, target.name):
        return True
    return recursive and target in lock.parents    # rm -r of a folder that holds it


def motion_lock(payload):
    tool, data = payload.get("tool_name"), payload.get("tool_input") or {}
    cwd = payload.get("cwd") or str(PROJECT)
    if tool in EDIT_TOOLS:
        path = data.get("file_path") or data.get("notebook_path") or ""
        if path and resolved(path, cwd) == lock_path():
            raise Refused(f"{LOCK} is a person's to remove or change, never an agent's.")
        if path.endswith(".py"):
            before = Path(path).read_text(encoding="utf-8") if Path(path).exists() else ""
            if tool == "Write":
                after = data.get("content", "")
            else:
                edits = data.get("edits") or [data]
                after = before
                for e in edits:
                    after = after.replace(e.get("old_string", ""), e.get("new_string", ""), 1) \
                        if e.get("old_string") else after
            for marker in (LOCK, "LOCK_FILE"):
                if after.count(marker) < before.count(marker):
                    raise Refused(f"This edit takes {marker} out of {Path(path).name}: the motion lock's "
                                  f"checks are never removed by an agent. A person changes them by hand.")
        return
    if tool not in SHELL_TOOLS:
        return
    command = data.get("command", "")
    for words in parts(command):
        name = Path(words[0]).name.lower()
        rest = words[1:]
        if name == "git" and rest[:1] == ["clean"] and any("x" in w.lower() for w in rest if w.startswith("-")):
            raise Refused(f"git clean -x would delete {LOCK} with the other ignored files.")
        if name == "git" and rest[:1] in (["checkout"], ["restore"], ["stash"], ["rm"]) and \
                any(LOCK in w for w in rest):
            raise Refused(f"{LOCK} is a person's to remove, never an agent's.")
        if name in policy.LAUNCHERS or name in ("perl", "ruby", "node", "bash", "sh", "pwsh", "powershell"):
            if LOCK in command:
                raise Refused(f"A command that runs code naming {LOCK} is refused: it is a person's to change.")
        if name in CHANGERS:
            recursive = any(w.startswith("-") and ("r" in w.lower() or w in ("--recursive", "-Recurse"))
                            for w in rest)
            targets = [w for w in rest if not w.startswith("-")]
            if name in ("cp", "copy", "copy-item", "cpi", "install", "rsync") and targets:
                targets = targets[-1:]
            if name == "find":
                if any(w in ("-delete", "-exec", "-execdir", "-ok") for w in rest):
                    patterns = [rest[i + 1] for i, w in enumerate(rest[:-1]) if w in ("-name", "-iname")]
                    if any(LOCK in w for w in rest) or any(fnmatch.fnmatch(LOCK, p) for p in patterns) or \
                            (not patterns and reaches_lock(targets[0] if targets else ".", cwd, True)):
                        raise Refused(f"find with -delete or -exec here could reach {LOCK}.")
                continue
            for t in targets:
                if (t.startswith("of=") and reaches_lock(t[3:], cwd)) or reaches_lock(t, cwd, recursive):
                    raise Refused(f"{name} would remove or change {LOCK}: a person's to do, never an agent's.")
        elif name not in READERS and any(LOCK in w for w in words):
            raise Refused(f"Only reading {LOCK} is allowed to an agent.")
    # Redirection into it: > MOTION_LOCKED, >> MOTION_LOCKED
    words = tokens(command)
    for i, w in enumerate(words[:-1]):
        if set(w) <= set("<>&|0123456789") and ">" in w and reaches_lock(words[i + 1], cwd):
            raise Refused(f"Writing into {LOCK} is a person's to do, never an agent's.")


def no_inline_hardware(payload):
    if payload.get("tool_name") not in SHELL_TOOLS:
        return
    command = payload.get("tool_input", {}).get("command", "")
    inline = re.search(r"\b(python3?|py)(\.exe)?\b[^;&|]*(\s-c\b|\s-\s|\s-$|<<|<\s*\S+\.py)", command) or \
        re.search(r"\|\s*(python3?|py)(\.exe)?\b(\s+-\w+)*\s*(-\s*)?($|[;&|])", command)
    imports = re.search(r"\b(import|from)\s+(" + "|".join(HARDWARE_MODULES) + r")\b|"
                        r"(__import__|import_module)\(\s*['\"](" + "|".join(HARDWARE_MODULES) + r")['\"]", command)
    if inline and imports:
        raise Refused("Hardware only through the project's commands (CLAUDE.md: no one-off scripts for the "
                      "mount, focuser or camera). Use or write a command, with its test.")


def no_motion(payload):
    if not payload.get("agent_id") or payload.get("tool_name") not in SHELL_TOOLS:
        return
    kind = policy.classify_text(payload.get("tool_input", {}).get("command", ""))
    if kind in ("hardware", "external"):
        raise Refused(f"A subagent never starts a physical action or reaches outside ({kind}): "
                      f"say what should be run, and the main session asks the person.")


def no_self_kill(payload):
    if payload.get("tool_name") not in SHELL_TOOLS:
        return
    for words in parts(payload.get("tool_input", {}).get("command", "")):
        # where it is the command run: first, or after until, while, !, sudo...
        at = [i for i, w in enumerate(words) if Path(w).name in ("pkill", "pgrep") and
              all(v in KEYWORDS or Path(v).name in policy.LAUNCHERS or v.startswith("-") for v in words[:i])]
        if any(any(w.startswith("-") and not w.startswith("--") and "f" in w for w in words[i + 1:]) for i in at):
            raise Refused("pkill -f and pgrep -f match their own command line: wait on the PID (kill -0 PID).")


def no_secrets_out(payload):
    tool, data = payload.get("tool_name"), payload.get("tool_input") or {}
    if tool == "Read":
        if Path(data.get("file_path", "")).name == "config.toml" or \
                re.search(r"rigs/[^/]+\.toml$", data.get("file_path", "").replace("\\", "/")):
            raise Refused("config.toml holds the Telegram bot's token: read the setting you need with a command "
                          "that prints only that (config.py, ./doctor.py), never the whole file.")
        return
    if tool not in SHELL_TOOLS:
        return
    command = data.get("command", "")
    if re.search(r"TELEGRAM_TOKEN|\bprintenv\b|^\s*env\s*$|\bset\s*$|Get-ChildItem\s+env:|\bls\s+env:", command,
                 re.I):
        raise Refused("That would print the environment or the Telegram token.")
    refusal = ("That would show config.toml's Telegram token. Ask for the one setting needed, "
               "e.g. grep -n '^latitude' config.toml.")
    for words in parts(command):
        bare = policy.unwrapped(words) or words
        name = Path(bare[0]).name.lower()
        files = [w for w in bare[1:] if SETTINGS_FILE.search(w)]
        if files and name in WHOLE:
            raise Refused(refusal)
        if files and name in SEARCHERS and any(re.search(r"telegram|token|chat", w, re.I)
                                               for w in bare[1:] if w not in files):
            raise Refused(refusal)
    # Code run inline that opens the file: python3 -c "print(open('config.toml').read())"
    if re.search(r"(open|Path|read_text|load)\s*\(\s*['\"][^'\"]*(config|rigs/[^'\"/]+)\.toml['\"]", command):
        raise Refused(refusal)


# The two below are for agents only, set in their own frontmatter
# (.claude/agents/), and are allowlists: what is not named is refused.
LOOKERS = {"ls", "cat", "head", "tail", "wc", "grep", "rg", "stat", "file", "pwd", "echo", "sort", "uniq", "cut",
           "jq", "find", "diff", "tr", "column", "nl"}
GIT_LOOKS = {"log", "diff", "show", "status", "blame", "ls-files", "rev-parse", "describe"}


def inside_project(word, cwd):
    try:
        target = resolved(word, cwd)
    except (OSError, RuntimeError, ValueError):
        return False
    return target == PROJECT.resolve() or PROJECT.resolve() in target.parents


def read_only_bash(payload):
    """An agent's shell: project commands policy.py calls read_only, and a
    short list of ways to look at files inside the checkout. Nothing else."""
    if payload.get("tool_name") not in SHELL_TOOLS:
        return
    cwd = payload.get("cwd") or str(PROJECT)
    command = payload.get("tool_input", {}).get("command", "")
    if any(m in command for m in ("$(", "`", "<(", ">(")):
        raise Refused("An agent's shell runs no command inside another.")
    words = tokens(command)
    if any(">" in w and set(w) <= set("<>&|0123456789") for w in words):
        raise Refused("An agent's shell writes no file.")
    for part in parts(command):
        name = Path(part[0]).name.lower()
        if policy.script_of(part[0]) or name in ("ty", "ty.cmd") or Path(part[0]).name in policy.LAUNCHERS:
            if policy.classify(part) != "read_only":
                raise Refused(f"{' '.join(part[:3])} is {policy.classify(part)}: an agent only looks.")
            continue
        if name == "git":
            if len(part) < 2 or part[1] not in GIT_LOOKS:
                raise Refused(f"git {part[1] if len(part) > 1 else ''} changes things: an agent only looks.")
            continue
        if name not in LOOKERS:
            raise Refused(f"{name} is not on an agent's list of ways to look.")
        if name == "find" and any(w in ("-delete", "-exec", "-execdir", "-ok", "-fprint") for w in part):
            raise Refused("find here may only look.")
        for w in part[1:]:
            if not w.startswith("-") and ("/" in w or Path(cwd, w).exists()) and not inside_project(w, cwd):
                raise Refused(f"{w} is outside the checkout.")
            if SETTINGS_FILE.search(w):
                raise Refused("config.toml holds the Telegram token: not for an agent to read.")


def docs_only(payload):
    """docs-keeper's pen: docs/, README.md and CHANGELOG.md, nothing else."""
    if payload.get("tool_name") not in EDIT_TOOLS:
        return
    data = payload.get("tool_input") or {}
    target = resolved(data.get("file_path") or data.get("notebook_path") or "", payload.get("cwd") or str(PROJECT))
    root = PROJECT.resolve()
    if not (root / "docs" in target.parents or target in (root / "README.md", root / "CHANGELOG.md")):
        raise Refused(f"docs-keeper edits docs/, README.md and CHANGELOG.md only, not {target.name}.")


RULES = {"motion-lock": motion_lock, "no-inline-hardware": no_inline_hardware, "no-motion": no_motion,
         "no-self-kill": no_self_kill, "no-secrets-out": no_secrets_out,
         "read-only-bash": read_only_bash, "docs-only": docs_only}
AGENT_RULES = {"read-only-bash", "docs-only"}


def check(rule, payload):
    """None if the call may go ahead, else the reason it may not."""
    try:
        RULES[rule](payload)
    except Refused as refusal:
        return str(refusal)
    return None


def main():
    try:
        rule = sys.argv[1]
        if rule not in RULES:
            raise KeyError(rule)
        payload = json.loads(sys.stdin.read())
        reason = check(rule, payload)
    except Exception as problem:   # fail closed: anything not understood is refused
        print(f"telescopeyoke's {(sys.argv[1:2] or ['guard'])[0]} hook could not check this "
              f"({type(problem).__name__}: {problem}), so it is refused.", file=sys.stderr)
        return 2
    if reason:
        print(f"telescopeyoke ({rule}): {reason}", file=sys.stderr)
        try:   # into the decision record; the refusal stands whether or not it is written
            import agentlog
            if not os.environ.get("PYTEST_CURRENT_TEST"):
                agentlog.write(agentlog.refusal(rule, payload, reason))
        except Exception:
            pass
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
