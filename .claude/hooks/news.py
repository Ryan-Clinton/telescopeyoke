#!/usr/bin/env python3
"""Claude Code's SessionStart and UserPromptSubmit hook: whatever went to
the person's phone (notify.py's copy of every message, cache/sent.jsonl)
since the agent last looked, put in front of the agent.

20 October 2026: the comet hunt's alert reached the phone at 06:12 and the
agent only heard of it when the person said so; a candidate seen again on a
second night went the same way. Prints nothing when there is nothing new,
and never blocks: whatever goes wrong here, it exits 0.
"""
import json
import os
import sys
import time
from pathlib import Path

PROJECT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
SHOWN = 900          # characters of each message shown
FIRST_DAYS = 2       # with nothing seen before, the messages of this many days


def news(data, now=None):
    """The messages since the last look, as lines; remembers this look."""
    now = now or time.time()
    log, seen = data / "cache" / "sent.jsonl", data / "cache" / "news.seen"
    try:
        last = float(seen.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        last = now - FIRST_DAYS * 86400
    fresh = []
    try:
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("time", 0) > last:
                fresh.append(row)
    except OSError:
        return []
    try:
        seen.write_text(str(max([last] + [r["time"] for r in fresh])), encoding="utf-8")
    except OSError:
        pass
    if not fresh:
        return []
    lines = [f"Sent to the person's phone since you last looked ({len(fresh)}); act on any that need it:"]
    for r in fresh:
        when = time.strftime("%d %b %H:%M", time.localtime(r["time"]))
        text = " ".join(str(r.get("text", "")).split())
        lines.append(f"- {when}{'' if r.get('sent') else ' (not delivered)'}: {text[:SHOWN]}")
        for path in r.get("pictures", []) + r.get("animations", []):
            lines.append(f"    with {path}")
    return lines


def main():
    try:
        sys.path.insert(0, str(PROJECT))
        import config
        lines = news(Path(config.DATA))
        if lines:
            print("\n".join(lines))
    except Exception:   # news missed is better than work stopped
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
