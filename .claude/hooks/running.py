#!/usr/bin/env python3
"""Claude Code's SessionStart and UserPromptSubmit hook: the jobs that are
running, waiting or queued, and every event still open, put in front of the
agent with each of the person's messages (jobs.py, docs/job-reporting-spec.md).

24 November 2026: asked for a progress report, the agent said it could not
tell how the dark test was going until it finished; and the test's darks had
ended four hours before anyone noticed. With this, "progress report" is
answered from the state of that moment, and an event raised while no
session was watching is still here until it is dealt with.

Prints nothing when nothing is going on, and never blocks: whatever goes
wrong here, it exits 0.
"""
import json
import os
import re
import sys
from pathlib import Path

PROJECT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
SHOWN = 12      # lines of the report at most; ./ty jobs has the rest
# The owner asking for work to go on unattended: "keep going until they are
# all done", "fill the next 8 to 10 hours", "keep yourself busy for 6-8 hours".
KEEP_GOING = re.compile(r"keep (going|busy|yoursel)|until (they are|it'?s|its|all) (all )?(done|finished)|"
                        r"fill the next|next \d+ ?(-|to) ?\d+ hours|busy fo?r? \d|while you wait|"
                        r"shedule|schedule (them|it|up)", re.I)


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        payload = {}
    if KEEP_GOING.search(str(payload.get("prompt") or "")):
        print("The owner is asking for work to go on until it is all done. Record it: ./ty jobs --busy-until "
              "HH:MM \"their words\" (the Stop hook then sends you back whenever nothing runs or is queued), "
              "queue each piece with ./ty bg, and ask any question the moment it arises while the rest goes on.")
    try:
        sys.path.insert(0, str(PROJECT))
        import jobs
        r = jobs.report()
        if not r["jobs"] and not r["open_events"]:
            return 0
        lines = jobs.text(r).splitlines()
        cut = [ln for ln in lines if not ln.startswith(("Finished", "  ")) or ln.startswith("  !")
               or any(ln.startswith(f"  {j['name']} (") for j in r["jobs"])]
        print("Jobs now (./ty jobs for all of it; act on and ack each open event):")
        print("\n".join(cut[:SHOWN] + ([f"... and {len(cut) - SHOWN} more lines"] if len(cut) > SHOWN else [])))
    except Exception:   # a report missed is better than work stopped
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
