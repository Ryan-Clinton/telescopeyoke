#!/usr/bin/env python3
"""Claude Code's Stop hook: the agent does not end its turn with the owner's
work undone (docs/job-reporting-spec.md).

It sends the agent back, with the reason, when:
- the owner asked for work until a time (`./ty jobs --busy-until`) and
  none of this session's work is getting done; or
- an event that needs the agent (a job done, failed, waiting, stalled,
  vanished, blocked) has not been dealt with and acked.

At most three times in one stretch of work, so it can never hold a
session in a loop; what is still undone then stays open, in front of the
agent with each message, until it is dealt with. Only this session's own
jobs and commitments count. Any failure here lets the turn end too.

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


MOST_SENDS = 3          # sends back in one stretch of work before the turn may end
STRETCH_S = 900         # a send back this long after the last one starts the count again


def reason(sid, now=None):
    sys.path.insert(0, str(PROJECT))
    import jobs
    now = now or time.time()
    listing = jobs.look_all(now)
    # Only this session's own jobs and commitments hold its turn: another
    # session's work, or the house's, never does.
    events = jobs.open_events(listing, now, sid=sid, strict=True)
    said = []
    going = jobs.active_own(listing, sid) if sid else []
    if going and not jobs.armed(sid, now):
        # 24 November 2026: a session's job ended at 20:37 with nothing armed
        # to wake its ended turn, and it sat idle until 23:31.
        said.append(f"{len(going)} job(s) of this session's are going ({', '.join(j['name'] for j in going[:4])}) "
                    "and nothing is armed to wake you when they need you: run `./ty jobs --wait-event` in the "
                    "background (or a Monitor on `./ty jobs --watch`) before ending the turn.")
    idle = [e for e in events if e["kind"] == "idle"]
    others = [e for e in events if e["kind"] != "idle"]
    if idle:
        b = jobs.busy(sid) or {}
        said.append(f"The owner asked for work {jobs.until_words(b)} ({b.get('why')}), and none of "
                    "this session's work is getting done. Start or queue the next piece of work (./ty bg NAME [--after JOB] -- "
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
        sid = payload.get("session_id") or None
        why = reason(sid)
        if not why:
            return 0
        sys.path.insert(0, str(PROJECT))
        import jobs
        import records
        count_file = jobs.home() / f"stops-{sid or 'owner'}.json"
        sent = records.read(count_file, {}) or {}
        now = time.time()
        count = sent.get("count", 0) if payload.get("stop_hook_active") and now - sent.get("at", 0) < STRETCH_S else 0
        if count >= MOST_SENDS:
            # Sent back as often as is safe in one stretch: the turn ends, and
            # what is undone stays open and in front of the agent with every
            # message (running.py) until it is dealt with.
            return 0
        records.write(count_file, {"count": count + 1, "at": now})
        print(json.dumps({"decision": "block", "reason": why}))
    except Exception:   # never hold a turn on a fault of this hook's own
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
