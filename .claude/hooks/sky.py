#!/usr/bin/env python3
"""When the user's message is about the sky, the satellite's answer comes with it.

A UserPromptSubmit hook. A message that mentions cloud, a gap, clear sky,
the forecast, rain or the stars gets `./clouds.py --approach` (the nearest
clear sky, the cloud's movement, when clear sky gets here) added before the
reply is written, so the reply starts from the satellite and not from the
camera's star count.

12 November 2026: told "a big gap in the clouds coming from Scotland", the
reply gave the camera's star count; the satellite was looked at only when
asked why not. The cloud data was already automatic for the camera's own
events (cd79d85), never for what the user says.

Never blocks: any failure, or no match, adds nothing.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

WORDS = re.compile(r"\b(cloud\w*|gaps?|clear\w*|overcast|rain\w*|showers?|forecast|met office|"
                   r"sky|skies|haze|hazy|stars?)\b", re.I)


def main():
    try:
        prompt = json.load(sys.stdin).get("prompt") or ""
    except ValueError:
        return
    if not WORDS.search(prompt):
        return
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
    try:
        # The satellite timer keeps an answer every 10 minutes: one up to 15
        # minutes old is read at once, and the two together stay inside the
        # hook's 45 s (13 November 2026: 40 s and 30 s in a row could lose both).
        done = subprocess.run([sys.executable, str(root / "clouds.py"), "--approach", "--fresh", "900"],
                              cwd=root, capture_output=True, text=True, timeout=25)
    except (OSError, subprocess.TimeoutExpired):
        return
    lines = done.stdout.strip()
    if not lines and done.stderr.strip():
        # Said, not swallowed: on 12 November 2026 a message got the radar and no satellite, with no word why.
        lines = "satellite: clouds.py --approach failed: " + done.stderr.strip().splitlines()[-1]
    try:
        wet = subprocess.run([sys.executable, str(root / "rain.py"), "--fresh", "600"], cwd=root,
                             capture_output=True, text=True, timeout=15).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        wet = ""
    lines = "\n".join(part for part in (lines, wet) if part)
    if not lines:
        return
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": ("The user's message is about the sky. The satellite now (./clouds.py --approach); "
                              "answer from this, with the arrival time, before anything the camera saw:\n" + lines)}}))


if __name__ == "__main__":
    main()
