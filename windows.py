"""Protected windows (docs/observing-plan-spec.md, Phase 3).

What is protected is a window, not a kind of object. A step in the schedule
is one of:

- hard ("protect": "hard"): an occultation, a transit with its baseline, a
  transient whose science is in the next hour. Its frames start on time
  whatever ran before.
- deadline ("deadline": "HH:MM"): it must be finished by then, and may
  move earlier.
- person: any step the person gave a start time (not_before) or a window.
- flexible: everything else, chosen by value and never protected.

A protected start reserves its setup before it (GoTo, centring, a focus
check), estimated from measured history: the 90th percentile before a hard
window, the median elsewhere. A window covers its event's uncertainty as
well as its length ("uncertainty": minutes before the start). Flexible
steps are timed back from the next protected start, so none can take it.

The window is a reservation of time, never permission: cloud, a mount
limit, the motion lock or an unrecoverable fault stop a protected step in
the execution layer whatever its class. Nothing here moves anything; the
runner (schedule.py) asks it which step goes now, with [plan] windows on.
"""
import time

FOCUS_CHECK_S = 120     # a focus check before a protected window: "a 2-minute job" (4 Nov 2026), assumed until measured
SETUP_FALLBACK_S = 150  # the GoTo, solves and camera start when history has no moves: patrol.OVERHEAD's 2.5 minutes
MIN_FLEXIBLE_S = 10 * 60  # a flexible step given less than this before a protected start waits instead: 2 minutes
                         # of its own and schedule.BACKSTOP_S taken off for the hard stop, with room to spare
CLASSES = ("hard", "deadline", "person", "flexible")
_COSTS = {"at": 0.0, "costs": None}
COSTS_FRESH_S = 3600


def costs():
    """history.costs(), kept for an hour: it reads every night's frames."""
    if _COSTS["costs"] is None or time.time() - _COSTS["at"] > COSTS_FRESH_S:
        import history
        _COSTS["costs"], _COSTS["at"] = history.costs(), time.time()
    return _COSTS["costs"]


def protection(step):
    """A step's class: hard, deadline, person or flexible."""
    if step.get("protect") == "hard":
        return "hard"
    if step.get("deadline"):
        return "deadline"
    if step.get("not_before") or step.get("protect") == "person":
        return "person"
    return "flexible"


def setup_seconds(c, hard):
    """Seconds a protected start reserves before it: the move between
    targets (GoTo, plate solves, camera start, from every night's gaps
    between sessions) and a focus check. The 90th percentile before a hard
    window, the median elsewhere."""
    move = (c or {}).get("move_s")
    if move:
        seconds = move["p90"] if hard else move["median"]
    else:
        seconds = SETUP_FALLBACK_S
    return float(seconds) + FOCUS_CHECK_S


def _clock(text, now, when=None):
    import schedule
    return schedule.not_before(text, now) if when is None else when(text, now)


def frames_from(step, now, when=None):
    """When a protected step's frames must start (unix seconds): its start
    time less the event's uncertainty. None for one with no start time."""
    if not step.get("not_before"):
        return None
    return _clock(step["not_before"], now, when) - 60 * float(step.get("uncertainty") or 0)


def launch_at(step, now, c, when=None):
    """When the runner starts a protected step: its frames' start less its
    setup. A deadline step: the latest start that still finishes by its
    deadline. None for a flexible step."""
    kind = protection(step)
    if kind in ("hard", "person") and step.get("not_before"):
        return frames_from(step, now, when) - setup_seconds(c, kind == "hard")
    if kind == "deadline":
        return _clock(step["deadline"], now, when) - 60 * float(step["minutes"]) - setup_seconds(c, False)
    return None


def cutoff(steps, now, c, when=None):
    """The latest moment a flexible step may run to: the earliest protected
    launch among the queued steps. A deadline step may go earlier, so it is
    timed back from the protected step after it (it must end before that
    one's launch); a hard or the person's window never moves. None when
    nothing queued is protected."""
    blocks, movable = [], []
    for s in steps:
        if s.get("status") not in (None, "queued"):
            continue
        at = launch_at(s, now, c, when)
        if at is None:
            continue
        length = 60 * float(s["minutes"]) + setup_seconds(c, protection(s) == "hard")
        (movable if protection(s) == "deadline" else blocks).append([at, at + length])
    # Each deadline step at its latest start, moved earlier past any block
    # it would overlap, latest deadline first; once placed it is a block too.
    for at, end in sorted(movable, key=lambda b: -b[1]):
        length = end - at
        moved = True
        while moved:
            moved = False
            for b in blocks:
                if at < b[1] and b[0] < at + length:
                    at, moved = b[0] - length, True
        blocks.append([at, at + length])
    return min((b[0] for b in blocks), default=None)


def choose(steps, now, c=None, when=None, among=None):
    """Which queued step goes now, and until when: (step, until, wait).

    - A protected step whose launch time has come goes first (hard, then
      deadline, then the person's, earliest first).
    - Otherwise the first queued flexible step (or the first of `among`, the
      dispatcher's order) that has at least MIN_FLEXIBLE_S before the cutoff
      goes, told to end at the cutoff (`until`, unix seconds).
    - Otherwise nothing yet: `wait` seconds until the next launch.

    (None, None, None) when nothing is queued."""
    c = costs() if c is None else c
    queued = [s for s in steps if s.get("status") in (None, "queued")]
    if not queued:
        return None, None, None
    rank = {"hard": 0, "deadline": 1, "person": 2}
    due = sorted(((launch_at(s, now, c, when), rank[protection(s)], i, s) for i, s in enumerate(queued)
                  if protection(s) != "flexible" and launch_at(s, now, c, when) is not None
                  and launch_at(s, now, c, when) <= now), key=lambda x: (x[1], x[0], x[2]))
    if due:
        return due[0][3], None, None
    order = among if among is not None else queued
    for s in order:
        kind = protection(s)
        if kind not in ("flexible", "deadline"):
            continue
        # A deadline step may go early, ended by its own deadline; it is not
        # timed back from itself.
        cut = cutoff([q for q in queued if q is not s], now, c, when)
        own = _clock(s["deadline"], now, when) if kind == "deadline" else None
        ends = [x for x in (cut, own) if x is not None]
        if not ends:
            return s, None, None
        if min(ends) - now >= MIN_FLEXIBLE_S:
            return s, min(ends), None
    nexts = [launch_at(s, now, c, when) for s in queued if launch_at(s, now, c, when) is not None]
    return None, None, max(0.0, min(nexts) - now) if nexts else None


def words(step, now, c=None, when=None):
    """How the runner treats a step, in words."""
    c = costs() if c is None else c
    kind = protection(step)
    if kind == "flexible":
        return "flexible: chosen by value, timed back from the next protected start"
    at = launch_at(step, now, c, when)
    started = time.strftime("%H:%M", time.localtime(at)) if at else "?"
    if kind == "deadline":
        return f"deadline {step['deadline']}: starts by {started} at the latest"
    reserve = setup_seconds(c, kind == "hard") / 60
    return (f"{kind}: frames from {time.strftime('%H:%M', time.localtime(frames_from(step, now, when)))}, "
            f"started {started} with {reserve:.0f} minutes for its setup")
