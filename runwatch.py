#!/usr/bin/env python3
"""Watch an imaging run and say something only when it changes.

    ./ty watch-run                   the newest run, looked at every minute
    ./runwatch.py --session frames/M31/20261020-221500
    ./runwatch.py --once             look once, say what is wrong now, and stop

Nothing is printed while all is well. A line is printed when frames stop
coming, when frames stop being kept, when the share kept halves, when the
stars dim as under cloud (alert.py's own measure) and when they come back,
and when the run ends, which also ends the watch. It reads only the run's
own files, so it costs nothing while it waits: an agent started as a
Monitor on it is woken only by these lines (docs/skills-and-agents.md).
On 15 October a run went 65 minutes with no frame kept and nobody said.

Nothing here moves the mount or uses the camera.
"""
import argparse
import sys
import time
from pathlib import Path

import config
import interface
import stacking

STALLED = 180        # seconds with no new frame: the camera or the run has stopped
UNKEPT = 300         # seconds with frames coming but none kept
GIVE_UP = 1800       # seconds of nothing at all, after which the watch ends
RECENT = 20          # frames the share kept now is judged on
HALVED = 0.5         # the share kept now, against before, that is worth saying


def newest_session(base=None):
    base = base or config.DATA
    logs = list((base / "frames").glob("*/*/frames.jsonl"))
    if not logs:
        raise interface.Refusal("NO_SESSION", "No imaging run has been recorded yet.")
    return max(logs, key=lambda p: p.stat().st_mtime).parent


def minutes(seconds):
    return f"{seconds / 60:.0f} min"


class Watch:
    """What has been said about one run, so each change is said once."""

    def __init__(self, session):
        self.session = Path(session)
        self.said = set()
        self.ended = False

    def once(self, key, line, lines):
        if key not in self.said:
            self.said.add(key)
            lines.append(line)

    def clear(self, key, line, lines):
        if key in self.said:
            self.said.discard(key)
            lines.append(line)

    def look(self, now=None):
        """The lines worth saying now; [] while all is well."""
        import alert
        now = now or time.time()
        name = f"{self.session.parent.name} {self.session.name}"
        log = stacking.read_log(self.session)
        lines = []
        status = stacking.run_status(self.session)
        if status["finished"] or (self.session / "frames.json").exists():   # shoot.py writes it at the end
            self.ended = True
            return [f"{name}: run ended, {status['accepted']} of {status['captured']} frames kept"]
        if not log:
            return lines
        quiet = now - log[-1]["taken"]
        if quiet > GIVE_UP:
            self.ended = True
            return [f"{name}: no frame for {minutes(quiet)}; the watch is ending"]
        if quiet > STALLED:
            self.once("stalled", f"{name}: no frame for {minutes(quiet)}: the camera or the run has stopped", lines)
            return lines
        self.clear("stalled", f"{name}: frames coming again", lines)
        kept = [f for f in log if f["accepted"]]
        since = now - (kept[-1]["taken"] if kept else log[0]["taken"])
        if since > UNKEPT and len(log) >= 2:
            self.once("unkept", f"{name}: no frame kept for {minutes(since)} (the last: {log[-1]['reason']})",
                      lines)
        else:
            self.clear("unkept", f"{name}: frames being kept again", lines)
        if len(log) >= 2 * RECENT:
            before = sum(f["accepted"] for f in log[:-RECENT]) / (len(log) - RECENT)
            recent = sum(f["accepted"] for f in log[-RECENT:]) / RECENT
            if before > 0.2 and recent <= before * HALVED:
                self.once("halved", f"{name}: kept {recent:.0%} of the last {RECENT} frames, "
                                    f"against {before:.0%} before", lines)
            elif recent > before * 0.8:
                self.clear("halved", f"{name}: keeping {recent:.0%} again", lines)
        sky = alert.sky_from_frames([f.get("flux") for f in log])
        if sky in ("cloud", "clouded"):
            self.once("dim", f"{name}: the stars have dimmed ({'mostly gone' if sky == 'clouded' else 'thinly'}); "
                             f"ask what the sky looks like", lines)
        elif sky == "clear":
            self.clear("dim", f"{name}: the stars are back", lines)
        return lines


def run(args, say=print, sleep=time.sleep, clock=time.time):
    session = Path(args.session) if args.session else newest_session()
    if not (session / "frames.jsonl").exists():
        raise interface.Refusal("NO_SESSION", f"No frames.jsonl in {session}.")
    watch = Watch(session)
    said = []
    while True:
        for line in watch.look(clock()):
            say(line)
            said.append(line)
        sys.stdout.flush()
        if args.once or watch.ended:
            return {"session": str(session), "said": said, "ended": watch.ended}
        sleep(args.every)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--session", help="the run's folder (default: the newest)")
    ap.add_argument("--every", type=float, default=60, help="seconds between looks")
    ap.add_argument("--once", action="store_true", help="look once and stop")
    ap.add_argument("--json", action="store_true", help="answer in JSON (with --once)")
    args = ap.parse_args()
    interface.main("watch-run", lambda: run(args), args.json)


if __name__ == "__main__":
    sys.exit(main())
