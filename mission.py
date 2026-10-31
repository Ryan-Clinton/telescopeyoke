"""What the telescope is trying to achieve, for the stream: each programme
as a mission a stranger can follow.

The director (director.py) says what the telescope is doing. This says why,
how far it has got and what is still unknown:

- the goal, in one plain sentence ("Find a star that wasn't there before");
- its milestones, each done, now or still to come, from what has been
  measured (the patrol's panels searched, the colour videos taken, the
  transit's baseline before and after);
- the open question, a real one ("Will anything survive the second look?",
  "Can it reach the usual best of 2.3 HFR?"): its figures are tonight's
  own and a question whose figure is not known is asked without it;
- a confidence label for a result (PRELIMINARY, CONSISTENT, NOT SEEN
  TONIGHT), never stronger than the measurement;
- WHAT / WHY / NOW / NEXT, one at a time across the top of the picture,
  so that someone arriving knows within a quarter of a minute what they
  are watching.

The words are curated in stream-targets.toml ([missions.NAME]); nothing is
made up, and a figure that is not known is left out.
"""
import json
import time

import config

CONTEXT_S = 12            # each of WHAT, WHY, NOW and NEXT stays this long across the top
FRESH_S = 120             # lucky.json older than this says nothing about now


def missions():
    import streamlook
    return streamlook.targets().get("missions", {})


def _lucky(now):
    """web/lucky.json (lucky.progress) if it is recent, else {}."""
    try:
        p = json.loads((config.DATA / "web" / "lucky.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return p if isinstance(p, dict) and now - p.get("at", 0) <= FRESH_S else {}


def key_of(s, lucky=None):
    """Which mission a picture's state (streamlook.from_status) is: lucky,
    mineral, live, patrol, transit, picture, focus or polar; None when the
    telescope is doing nothing a viewer can follow."""
    kind = s.get("kind")
    if kind in ("focus", "polar", "patrol", "transit"):
        return kind
    if kind == "moon":
        lucky = lucky or {}
        if s.get("programme_words") == "mineral Moon" or lucky.get("stage") == "colour" \
                or lucky.get("kind") == "mineral":
            return "mineral"
        return "live" if s.get("live") else "lucky"
    if kind == "picture" and s.get("target"):
        return "picture"
    return None


def _steps(labels, at, done=False):
    """[(label, "done" | "now" | "open")] with the step at index `at` under way."""
    return [(label, "done" if done or i < at else "now" if i == at else "open") for i, label in enumerate(labels)]


LUCKY_STEPS = ["Find the Moon", "Capture the frames", "Rank every frame", "Stack the sharpest", "Result"]
LUCKY_AT = {"centring": 0, "capturing": 1, "ranking": 2, "stacking": 3, "done": 4}
MINERAL_STEPS = ["Find the Moon", "Capture the colour videos", "Check the colour repeats", "Build the mineral Moon",
                 "Compare with the spacecraft maps"]


def steps(key, s, lucky=None):
    """The mission's milestones, from what has been measured."""
    lucky = lucky or {}
    stage = lucky.get("stage")
    if key == "lucky":
        at = LUCKY_AT.get(stage)
        return _steps(LUCKY_STEPS, at, done=stage == "done") if at is not None else []
    if key == "mineral":
        labels = list(MINERAL_STEPS)
        if stage == "colour":
            labels[1] = f"Capture colour video {lucky.get('done', 1)} of {lucky.get('videos', 3)}"
            return _steps(labels, 1)
        if stage == "mineral":
            return _steps(labels, 2)
        if stage == "done" and lucky.get("seas") is not None:
            return _steps(labels, 5, done=True)
        return _steps(labels, 0) if stage == "centring" else []
    if key == "patrol":
        panels = (s.get("patrol") or {}).get("panels") or []
        return [(f"Field {i + 1}", {"done": "done", "current": "now"}.get(p.get("state"), "open"))
                for i, p in enumerate(panels)]
    if key == "transit":
        t = s.get("transit") or {}
        now = s.get("now") or time.time()
        if not t.get("ingress"):
            return []
        at = 0 if now < t["ingress"] else 1 if now <= t["egress"] else 2
        return _steps(["Measure the star before", "The planet crosses", "Measure the star after", "Result"], at)
    if key == "focus":
        return list((s.get("focus") or {}).get("steps") or [])
    if key == "polar":
        return list((s.get("polar") or {}).get("pictures_steps") or [])
    return []


def question(key, s, lucky=None, entry=None):
    """The open question, with tonight's figures, or None. Never one whose
    answer is already known."""
    entry = entry or missions().get(key, {})
    lucky = lucky or {}
    if key == "patrol":
        p = s.get("patrol") or {}
        if p.get("possible") or p.get("awaiting"):
            return entry.get("question_possible")
        return entry.get("question")
    if key == "transit":
        depth = (s.get("transit") or {}).get("depth")
        return entry.get("question", "").format(depth=f"{100 * depth:.1f}") if depth else entry.get("question_plain")
    if key == "focus":
        f = s.get("focus") or {}
        if f.get("outcome"):
            return None
        usual = f.get("usual_hfr")
        return entry.get("question", "").format(usual=f"{usual:.1f}") if usual else entry.get("question_plain")
    if key == "polar":
        p = s.get("polar") or {}
        if p.get("stage") in ("complete", "failed"):
            return None
        return entry.get("question")
    if key == "lucky":
        frames = lucky.get("frames")
        if lucky.get("stage") == "done":
            return None
        return entry.get("question", "").format(frames=f"{frames:,}") if frames else entry.get("question_plain")
    if key == "mineral" and lucky.get("stage") == "done":
        return None
    return entry.get("question")


def confidence(key, lucky=None, candidate=None):
    """(label, why) for a result, as sure as the measurement and no surer,
    or None when there is no result yet."""
    lucky = lucky or {}
    if candidate:
        stage, result = candidate.get("stage"), (candidate.get("result") or "").lower()
        if stage == "detected":
            return "PRELIMINARY", "A possible change, seen once: the telescope is taking another look."
        if stage == "second":
            return "NEEDS SECOND LOOK", "A second set of pictures decides whether it is real."
        if any(w in result for w in ("artefact", "artifact", "known", "asteroid", "rejected", "bogus", "not real")):
            return "REJECTED", "It did not survive the checks, so nothing is claimed."
        return "AWAITING REVIEW", "It passed the automatic checks; a person looks before anything is claimed."
    if key == "mineral" and lucky.get("stage") == "done":
        seas = [c for c in lucky.get("seas") or [] if "bluer_by_percent" in c]
        if not seas:
            return "NOT SEEN TONIGHT", "The seas compared were dark, clipped or out of sight."
        agree = [c for c in seas if c.get("result") == "agrees"]
        if len(agree) < len(seas):
            return "DOES NOT AGREE", "The colour came out the other way from the spacecraft maps: it is kept, not claimed."
        if lucky.get("videos", 1) > 1 and all(c.get("holds_without_any_one_video") for c in agree):
            return "CONSISTENT", f"The same way round in every video, and without any one of them ({agree[0]['videos_agreeing']})."
        return "PRELIMINARY", "Seen, but not yet in more than one independent video."
    return None


def result_words(key, lucky=None):
    """The result in plain words, from the measurement, or None."""
    lucky = lucky or {}
    if key == "mineral" and lucky.get("stage") == "done":
        seas = [c for c in lucky.get("seas") or [] if "bluer_by_percent" in c]
        if seas:
            c = seas[0]
            return (f"{c['expected'].replace('Mare ', '')}: {c['result']}, by {abs(c['bluer_by_percent']):.1f} %, "
                    f"in {c['videos_agreeing']} videos")
    if key == "lucky" and lucky.get("stage") == "done" and lucky.get("frames"):
        return f"The sharpest {lucky.get('kept', 0):,} of {lucky['frames']:,} frames combined"
    return None


def of(s, now=None, lucky=None):
    """The mission for a picture's state: {"key", "title", "goal", "steps",
    "question", "next", "confidence", "result", "stream_title"}, or None."""
    now = now or s.get("now") or time.time()
    lucky = _lucky(now) if lucky is None else lucky
    key = key_of(s, lucky)
    entry = missions().get(key) if key else None
    if not entry:
        return None
    target = s.get("target") or ""
    found = steps(key, s, lucky)
    upcoming = next((label for label, state in found if state == "open"), None)
    return {"key": key, "title": entry.get("title", key.upper()).format(target=target.upper()),
            "goal": entry.get("goal", "").format(target=target),
            "steps": found, "question": question(key, s, lucky, entry), "next": upcoming,
            "confidence": confidence(key, lucky, s.get("candidate")), "result": result_words(key, lucky),
            "stream_title": entry.get("stream_title", "").format(target=target) or None}


def context(m, s, now):
    """(label, words) for the line across the top: WHAT, WHY, NOW and NEXT
    in turn, CONTEXT_S each; only those that are known."""
    target = s.get("target") or ""
    what = "THE MOON" if s.get("kind") == "moon" else target.upper() if target else None
    lines = [("WHAT", what), ("WHY", m["goal"] if m else None),
             ("NOW", s.get("activity_words") or (m["steps"] and next((label for label, st in m["steps"]
                                                                     if st == "now"), None) if m else None)),
             ("NEXT", (m["next"] if m else None) or s.get("next"))]
    lines = [(label, words) for label, words in lines if words]
    if not lines:
        return None
    return lines[int(now // CONTEXT_S) % len(lines)]


REVEAL_S = 3 * 3600       # a lucky or mineral result is shown as tonight's for this long


def reveal(s, now, lucky_file=None):
    """{"before", "after", "before_path", "after_path"}: one raw frame and
    what was made of it, for the RESULT chapter; None when nothing has been
    made yet. The labels are the measured counts, never more."""
    web = config.DATA / "web"
    raw = web / "latest.jpg"
    try:
        p = json.loads((lucky_file or web / "lucky.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        p = {}
    done = isinstance(p, dict) and p.get("stage") == "done" and now - p.get("at", 0) <= REVEAL_S
    if s.get("kind") == "moon" and done and p.get("kind") == "mineral" and p.get("picture"):
        return {"before": "ONE RAW FRAME", "after": f"MINERAL MOON · {p.get('videos', 0)} COLOUR VIDEOS",
                "before_path": str(raw), "after_path": p["picture"]}
    if s.get("kind") == "moon" and done and p.get("frames"):
        return {"before": "ONE RAW FRAME", "after": f"THE SHARPEST {p.get('kept', 0):,} OF {p['frames']:,} COMBINED",
                "before_path": str(raw), "after_path": str(web / "stack.jpg")}
    if s.get("kind") in ("picture", "patrol", "transit") and (s.get("combined") or 0) > 1:
        exposure = f"{s['exposure']:g} S " if s.get("exposure") else ""
        minutes = f" · {s['integration_s'] / 60:.0f} MIN" if s.get("integration_s") else ""
        return {"before": f"ONE {exposure}EXPOSURE", "after": f"{s['combined']:,} STACKED{minutes}",
                "before_path": str(raw), "after_path": str(web / "stack.jpg")}
    return None


def so_far(now, lucky_file=None):
    """Lines for SO FAR TONIGHT from the lucky imaging's last result, if tonight's."""
    try:
        p = json.loads((lucky_file or config.DATA / "web" / "lucky.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(p, dict) or p.get("stage") != "done" or now - p.get("at", 0) > REVEAL_S:
        return []
    if p.get("kind") == "mineral":
        lines = [f"Mineral Moon from {p.get('videos', 0)} colour videos"]
        words = result_words("mineral", p)
        label = confidence("mineral", p)
        return lines + ([f"{words} ({label[0].lower()})"] if words and label else [])
    if p.get("frames"):
        return [f"Moon: the sharpest {p.get('kept', 0):,} of {p['frames']:,} frames combined"]
    return []
