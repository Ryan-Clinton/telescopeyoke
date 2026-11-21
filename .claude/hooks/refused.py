#!/usr/bin/env python3
"""Claude Code's PostToolUse and PostToolUseFailure hook on web fetches: a
page that answers 403 is opened in the person's Chrome instead of being
reported as blocked (21 November 2026: PixInsight's pages were written off
as unreachable until the person pointed at Claude in Chrome). It adds a
line for the agent and never blocks: whatever goes wrong here, it exits 0.
"""
import json
import re
import sys

REFUSED = re.compile(r"\b(?:HTTP(?: error| status)?|status(?: code)?|code|returned|answered)\W{0,3}403\b|\b403\W{0,3}forbidden\b",
                     re.IGNORECASE)
ADVICE = ("That page answered HTTP 403. Open it now in the user's Chrome with Claude in Chrome "
          "(mcp__claude-in-chrome__*, loaded through ToolSearch), and do not report it as unreachable until "
          "that has been tried. A subagent without those tools says so in its report, and the main session "
          "opens the page. If Chrome is refused too, stop and say so.")


def refused(event):
    """Whether this tool's result or error says HTTP 403."""
    response = event.get("tool_response")
    if isinstance(response, dict) and response.get("code") == 403:
        return True
    return bool(REFUSED.search(json.dumps([response, event.get("error")], default=str)))


def main():
    try:
        event = json.load(sys.stdin)
        if refused(event):
            print(json.dumps({"hookSpecificOutput": {"hookEventName": event.get("hook_event_name", "PostToolUse"),
                                                     "additionalContext": ADVICE}}))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
