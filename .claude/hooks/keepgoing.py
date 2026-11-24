#!/usr/bin/env python3
"""Claude Code's Stop hook: the agent does not end its turn with the owner's
work undone (docs/job-reporting-spec.md).

It sends the agent back once, with the reason, when:
- the owner asked for work until a time (`./ty jobs --busy-until`) and
  nothing is running or queued; or
- an event that needs the agent (a job done, failed, waiting, stalled,
  vanished, blocked) has not been dealt with and acked.

Once only: when Claude Code says this turn has already been sent back
(stop_hook_active), it lets the turn end, so it can never hold a session
in a loop. Any failure here lets the turn end too.

24 November 2026: a session told to "schedule them and keep going until
they are all done" stopped with three of four tests done and its two
questions saved for the end; the same morning another sat four hours
after its dark test finished.
"""
import json
import os
import sys
import time
from pathlib import Path

PROJECT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])


def reason(now=None):
    sys.path.insert(0, str(PROJECT))
    import jobs
    now = now or time.time()
    listing = jobs.look_all(now)
    events = jobs.open_events(listing, now)
    said = []
    idle = [e for e in events if e["kind"] == "idle"]
    others = [e for e in events if e["kind"] != "idle"]
    if idle:
        b = jobs.busy() or {}
        said.append(f"The owner asked for work until {jobs._clock(b.get('until'))} ({b.get('why')}), and nothing "
                    "is running or queued. Start or queue the next piece of work (./ty bg NAME [--after JOB] -- "
                    "COMMAND). A question for the owner is asked now, in one line, while the work that does not "
                    "need the answer goes on: never saved for the end.")
    if others:
        listed = "; ".join(f"{e['name']} {e['kind']}: {e['words'][:100]} [{e['id']}]" for e in others[:5])
        said.append(f"{len(others)} job event{'s' if len(others) != 1 else ''} not dealt with: {listed}. Act on "
                    "each (start what follows, report it, or say why nothing is needed) and ack it: "
                    "./ty jobs --ack EVENT \"what was done\".")
    return " ".join(said)


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if payload.get("stop_hook_active"):
            return 0
        why = reason()
        if why:
            print(json.dumps({"decision": "block", "reason": why}))
    except Exception:   # never hold a turn on a fault of this hook's own
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
