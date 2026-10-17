#!/usr/bin/env python3
"""Claude Code's PostToolUse hook: one line in the decision record
(agentlog.py) for each shell command, skill and agent that has run.

It enforces nothing, so it never blocks: whatever goes wrong here, it exits
0 and the work goes on. What it writes is redacted first (agentlog.redact).
"""
import json
import os
import sys
from pathlib import Path

PROJECT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(PROJECT))


def main():
    try:
        import agentlog
        payload = json.loads(sys.stdin.read())
        if payload.get("tool_name") in ("Bash", "PowerShell", "Skill", "Agent", "Task"):
            agentlog.write(agentlog.event(payload))
    except Exception:   # a record lost is better than work stopped
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
