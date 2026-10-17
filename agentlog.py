#!/usr/bin/env python3
"""The decision record: what Claude and its agents ran, who asked, and what
the safety hooks refused.

    ./ty agent-report             the record summed up: by skill, by agent, refusals
    ./ty agent-report --days 10   the last ten days
    ./ty agent-report --json

Claude Code's hooks write it (.claude/hooks/log.py after each shell command,
skill and agent, on each message from the person and at the end of each
turn; .claude/hooks/guard.py on each refusal), one line per event
in cache/agent-log.jsonl, which git ignores. Each line has when, the session,
the agent (none for the main session), the skill last loaded in that session,
the tool, the command as policy.py read it after redaction, its class, and
for anything that uses the hardware, the authorisation as data: its scope
(mount.goto), its target (Vega), whether the person had spoken since the
last such command (`present`), and their last few words.

Never prompts, never secrets: tokens, keys and passwords, the Telegram
bot's token wherever it appears, environment values (NAME=value) and URL
query strings are replaced by *** before anything is written.
Nothing here moves the mount or uses the camera.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

import config
import interface
import policy

INTERRUPTED = "[Request interrupted by user"
CORRECTION = re.compile(r"^\s*(no\b|nope|stop|don'?t|do not|wrong|not that|that'?s (wrong|not)|why (did|are|have) "
                        r"you|wtf|what the (hell|fuck)|i (said|told you|asked)|undo|cancel|hang on|wait\b)", re.I)
WORDS = 120          # characters of the person's last words kept with a hardware command
SECRET_FLAGS = r"--?(token|key|api[-_]?key|password|passwd|secret|auth|bearer|chat)"
REDACTIONS = [
    (re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b"), "***"),                     # a Telegram bot's token
    (re.compile(SECRET_FLAGS + r"(=|\s+)(\S+)", re.I), lambda m: f"{m.group(0)[:-len(m.group(3))]}***"),
    (re.compile(r"(?<![-\w])(token|key|password|secret|chat)\s*=\s*(?!\*\*\*)\S+", re.I),
     lambda m: m.group(1) + " = ***"),
    (re.compile(r"(?<![\w-])([A-Z][A-Z0-9_]{2,})=\S+"), r"\1=***"),               # TY_TELEGRAM_TOKEN=...
    (re.compile(r"(https?://[^\s?'\"]+)\?[^\s'\"]+"), r"\1?***"),                # query strings
    (re.compile(r"(api\.telegram\.org/bot)[^/\s]+"), r"\1***"),
]


def path():
    return config.DATA / "cache" / "agent-log.jsonl"


def redact(text):
    text = str(text or "")
    for pattern, replacement in REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def read(days=None, now=None):
    p = path()
    if not p.exists():
        return []
    since = (now or time.time()) - days * 86400 if days else 0
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("time", 0) >= since:
            rows.append(row)
    return rows


def write(row):
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def last_words(transcript):
    """(the person's last message, when) from Claude Code's transcript."""
    try:
        lines = Path(transcript).read_text(encoding="utf-8").splitlines()
    except (OSError, TypeError, ValueError):
        return None, None
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isSidechain"):
            continue
        content = (entry.get("message") or {}).get("content")
        if isinstance(content, list):
            content = " ".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
        if isinstance(content, str) and content.strip() and not content.lstrip().startswith(("<", INTERRUPTED)):
            return content.strip(), entry.get("timestamp")
    return None, None


def entries(transcript):
    try:
        lines = Path(transcript).read_text(encoding="utf-8").splitlines()
    except (OSError, TypeError, ValueError):
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def texts(entry):
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    return " ".join(c.get("text", "") for c in content or [] if isinstance(c, dict) and c.get("type") == "text")


def interrupted_before(transcript):
    """Whether the person stopped Claude mid-turn just before their message."""
    for entry in reversed(entries(transcript)):
        if entry.get("type") == "user" and not entry.get("isMeta"):
            text = texts(entry)
            if INTERRUPTED in text:
                return True
            if text.strip() and not text.lstrip().startswith("<"):
                return False
        elif entry.get("type") == "assistant":
            return False
    return False


def asked(transcript):
    """Whether Claude's last reply put a question to the person: a sentence
    of its own ending in a question mark, outside quotes and code."""
    for entry in reversed(entries(transcript)):
        if entry.get("type") == "assistant" and not entry.get("isSidechain"):
            text = re.sub(r"```.*?```|`[^`]*`|\"[^\"]*\"", "", texts(entry), flags=re.S)
            if text.strip():
                return bool(re.search(r"\?\s*($|\n)", text))
    return False


def scope_of(command):
    """(scope, target) of the first hardware command in a line: mount.goto, Vega."""
    for part in policy.parts_of(command):
        if policy.classify(part) != "hardware":
            continue
        words = policy.unwrapped(part)
        script = policy.script_of(words[0]) or ""
        rest = [w for w in words[1:] if not w.startswith("-")]
        if script == "ty" and rest and rest[0] in policy.TY_PASSES:
            script, rest = policy.TY_PASSES[rest[0]], rest[1:]
        name = script.removesuffix(".py")
        if name in ("mount", "landmark", "focuser", "polaris", "panorama") and rest:
            return f"{name}.{rest[0]}", (rest[1] if len(rest) > 1 else None)
        return name, (rest[0] if rest else None)
    return None, None


def event(payload, now=None):
    """The record's line for one tool call that has run (PostToolUse)."""
    now = now or time.time()
    tool = payload.get("tool_name")
    data = payload.get("tool_input") or {}
    session = payload.get("session_id")
    row = {"time": now, "session": session, "agent": payload.get("agent_type"), "tool": tool}
    earlier = [r for r in read(days=2, now=now) if r.get("session") == session]
    if tool == "Skill":
        row.update(event="skill", skill=data.get("skill") or data.get("name"))
        return row
    row["skill"] = next((r["skill"] for r in reversed(earlier) if r.get("event") == "skill"), None)
    if tool in ("Agent", "Task"):
        row.update(event="agent", started=data.get("subagent_type") or "general-purpose")
        return row
    command = data.get("command", "")
    kind = policy.classify_text(command)
    row.update(event="ran", command=redact(command)[:500], cls=kind)
    if kind == "hardware":
        words, said_at = last_words(payload.get("transcript_path"))
        before = next((r for r in reversed(earlier) if r.get("cls") == "hardware"), None)
        fresh = bool(words) and (before is None or (said_at or "") > before.get("said_at", ""))
        scope, target = scope_of(command)
        row["authorisation"] = {"present": fresh and not payload.get("agent_type"), "scope": scope,
                                "target": target, "words": redact(words or "")[:WORDS]}
        row["said_at"] = said_at
    return row


def person(payload, now=None):
    """The record's line for a message from the person (UserPromptSubmit):
    whether it stopped or corrected what was going on, and whether they had
    interrupted Claude first. Their words are not kept, only these."""
    now = now or time.time()
    session = payload.get("session_id")
    earlier = [r for r in read(days=2, now=now) if r.get("session") == session]
    words = payload.get("prompt") or ""
    return {"time": now, "session": session, "agent": None, "tool": None, "event": "person",
            "skill": next((r["skill"] for r in reversed(earlier) if r.get("event") == "skill"), None),
            "correction": bool(CORRECTION.search(words)),
            "interrupted": interrupted_before(payload.get("transcript_path"))}


def turn_end(payload, now=None):
    """The record's line at the end of Claude's turn (Stop): whether it
    ended on a question to the person."""
    now = now or time.time()
    session = payload.get("session_id")
    earlier = [r for r in read(days=2, now=now) if r.get("session") == session]
    return {"time": now, "session": session, "agent": None, "tool": None, "event": "turn",
            "skill": next((r["skill"] for r in reversed(earlier) if r.get("event") == "skill"), None),
            "asked": asked(payload.get("transcript_path"))}


def refusal(rule, payload, reason, now=None):
    """The record's line for a call a safety hook refused (PreToolUse)."""
    data = payload.get("tool_input") or {}
    return {"time": now or time.time(), "session": payload.get("session_id"), "agent": payload.get("agent_type"),
            "tool": payload.get("tool_name"), "event": "refused", "rule": rule, "reason": reason,
            "command": redact(data.get("command") or data.get("file_path") or "")[:500]}


def report(rows):
    """The record summed up."""
    by_skill, by_agent, refused = {}, {}, {}

    def skill(name):
        return by_skill.setdefault(name, {"loaded": 0, "ran": 0, "refused": 0, "turns": 0, "questions": 0,
                                          "corrected": 0, "interrupted": 0})
    moves = [r for r in rows if r.get("cls") == "hardware"]
    for r in rows:
        if r.get("event") == "skill":
            skill(r["skill"])["loaded"] += 1
        if r.get("event") in ("ran", "refused") and r.get("skill"):
            skill(r["skill"])["ran" if r["event"] == "ran" else "refused"] += 1
        if r.get("event") == "turn" and r.get("skill"):
            skill(r["skill"])["turns"] += 1
            skill(r["skill"])["questions"] += int(bool(r.get("asked")))
        if r.get("event") == "person" and r.get("skill"):
            skill(r["skill"])["corrected"] += int(bool(r.get("correction")))
            skill(r["skill"])["interrupted"] += int(bool(r.get("interrupted")))
        if r.get("agent"):
            by_agent.setdefault(r["agent"], {"ran": 0, "refused": 0})[
                "refused" if r.get("event") == "refused" else "ran"] += 1
        if r.get("event") == "refused":
            refused[r["rule"]] = refused.get(r["rule"], 0) + 1
    unasked = [r for r in moves if not (r.get("authorisation") or {}).get("present")]
    return {"events": len(rows), "hardware_commands": len(moves),
            "hardware_without_the_person_speaking_first": len(unasked),
            "unasked": [{"time": r["time"], "command": r.get("command"),
                         "words": (r.get("authorisation") or {}).get("words")} for r in unasked[-10:]],
            "skills": by_skill, "agents": by_agent, "refused": refused}


def run(args, say=print):
    rows = read(args.days)
    answer = report(rows)
    say(f"{answer['events']} events; {answer['hardware_commands']} hardware commands, "
        f"{answer['hardware_without_the_person_speaking_first']} without the person speaking first")
    for name, s in sorted(answer["skills"].items()):
        say(f"  skill {name}: loaded {s['loaded']}, ran {s['ran']}, refused {s['refused']}; {s['turns']} turns, "
            f"{s['questions']} ending on a question, corrected {s['corrected']}, interrupted {s['interrupted']}")
    for name, s in sorted(answer["agents"].items()):
        say(f"  agent {name}: ran {s['ran']}, refused {s['refused']}")
    for rule, n in sorted(answer["refused"].items()):
        say(f"  refused by {rule}: {n}")
    return answer


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=float, help="only the last N days")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("agent-report", lambda: run(args), args.json)


if __name__ == "__main__":
    sys.exit(main())
