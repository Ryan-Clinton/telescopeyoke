"""The stream's presenter: what the side panel and the picture say, minute by
minute, so that someone arriving knows within a minute what they are
watching, why, how it works and what is coming (docs/stream-look.md, "The
story").

`plan(state, now)` decides, for one picture:

- the side panel's chapter, in a loose broadcast clock (CLOCK): NOW (the
  programme and its mission, mission.py), then SCIENCE, HOW IT WORKS (the
  chat's chosen topic first, streamchat.vote), SO FAR TONIGHT, COMING UP
  and RAW → RESULT (once something has been made) in turn, each for about
  half a minute between spells of NOW;
- a LOOK CLOSELY or TELESCOPEYOKE line across the picture, between chapters;
- a larger explainer drawn over the picture, every EXPLAINER_EVERY;
- a slow crawl along the bottom, every CRAWL_EVERY.

Every word is curated (stream-targets.toml) or made from the night's own
measurements; nothing is generated or guessed, and a number that is not
known is left out, never filled in. A card shown is not shown again until
the rest of its pool has been. A candidate's follow-up, a paused run or a
transition takes the screen instead (streamlook.PRIORITY).
"""
import math
import time
from pathlib import Path

# The broadcast clock: (chapter, seconds), round and round from the stream's start.
CLOCK = [("NOW", 45), ("SCIENCE", 25), ("NOW", 45), ("HOW IT WORKS", 25), ("NOW", 45), ("TONIGHT", 20),
         ("NOW", 45), ("COMING UP", 20), ("NOW", 45), ("RESULT", 20)]
CYCLE = sum(s for _, s in CLOCK)
LINE_EVERY, LINE_S = 90, 10           # a LOOK CLOSELY / TELESCOPEYOKE line, during NOW
EXPLAINER_EVERY, EXPLAINER_S = 300, 12
CRAWL_EVERY, CRAWL_S = 600, 45
NAKED_EYE = 6.0                       # the faintest stars an eye sees under a dark sky (magnitude)
FULLISH = 90                          # % lit from which the Moon is told as near full (short shadows)
COMET_HOURS = 36                     # a comet the hunt recovered is told for this long after the hunt
# While the telescope focuses or is polar aligned: the card's title, its
# pool in [stories], and how long each card stays.
SEGMENTS = {"focus": "HOW FOCUSING WORKS", "polar": "HOW POLAR ALIGNMENT WORKS"}
SEGMENT_S = 25


class Story:
    """What has been shown, so a viewer does not see the same card every few minutes."""

    def __init__(self, start=None):
        self.start = start
        self.turn = {}                # pool name -> next index
        self.chosen = {}              # (slot, pool) -> the card chosen for that slot

    def pick(self, pool, items, slot):
        """The next of `items` not yet shown, the same all through `slot`."""
        if not items:
            return None
        key = (slot, pool)
        if key not in self.chosen:
            n = self.turn.get(pool, 0)
            self.chosen[key] = items[n % len(items)]
            self.turn[pool] = n + 1
            if len(self.chosen) > 200:
                self.chosen = dict(list(self.chosen.items())[-50:])
        return self.chosen[key]


STORY = Story()


def chapter_at(elapsed):
    """(chapter, its number in the run of chapters so far) at `elapsed` seconds."""
    cycle, into = divmod(elapsed, CYCLE)
    for i, (name, seconds) in enumerate(CLOCK):
        if into < seconds:
            return name, int(cycle) * len(CLOCK) + i
        into -= seconds
    return "NOW", 0


def fainter(mag):
    """How many times fainter than the faintest naked-eye star, in plain words."""
    times = 10 ** (0.4 * (mag - NAKED_EYE))
    rounded = round(times, -int(math.floor(math.log10(times))))
    return f"{int(rounded):,}"


def plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def made(s, live):
    """Cards made from the night's own measurements: (pool, text). Only what
    is measured is said."""
    out = []
    combined, exposure = s.get("combined"), s.get("exposure")
    moon = s.get("kind") == "moon"
    if combined and exposure and moon:
        out.append(("made-stack", f"This picture combines {plural(combined, 'exposure')} of {exposure:g} s each: "
                                  "short enough to freeze the shimmer of the air in each one."))
    elif combined and exposure:
        out.append(("made-stack", f"This picture combines {plural(combined, 'exposure')} of {exposure:g} s each: "
                                  f"{combined * exposure / 60:.0f} minutes of light from this one patch of sky."))
    rejected = (live.get("rejected") or 0)
    if rejected and live.get("reasons"):
        reason = next(iter(live["reasons"]))
        out.append(("made-rejected", f"{plural(rejected, 'frame')} set aside so far, mostly: {reason}. "
                                     "A spoiled frame would only add noise."))
    if s.get("fwhm_arcsec") and not moon:
        out.append(("made-stars", f"The stars measure about {s['fwhm_arcsec']:.0f} arcseconds across: "
                                  "mostly the blurring of the air, not the telescope."))
    depth = None if moon else live.get("depth_mag")
    if depth:
        out.append(("made-depth", f"Tonight's search can find a new star down to about magnitude {depth:.1f}: "
                                  f"some {fainter(depth)} times fainter than the faintest star the eye can see."))
    return out


def comet_hunt(now, data=None):
    """The comet hunt's latest find worth telling (sungrazer.py's
    hunt-ccor1.json): a known comet it found by itself, in the last
    COMET_HOURS. A track nobody has reported is never told: it is the
    person's to check first, as a nova candidate is."""
    import datetime
    import json
    import config
    path = Path(data or config.DATA) / "sungrazer" / "hunt-ccor1.json"
    try:
        hunt = json.loads(path.read_text(encoding="utf-8"))
        when = datetime.datetime.strptime(hunt["when"], "%Y-%m-%d %H:%M").replace(tzinfo=datetime.timezone.utc)
    except (OSError, ValueError, KeyError):
        return None
    if not 0 <= now - when.timestamp() <= COMET_HOURS * 3600:
        return None
    for c in hunt.get("towards_sun", []):
        match = c.get("public") or {}
        if match.get("state") == "known comet" and c.get("times"):
            first, last = (datetime.datetime.strptime(t, "%Y-%m-%d %H:%M") for t in (c["times"][0], c["times"][-1]))
            return {"pictures": hunt.get("pictures"), "seen": len(c["times"]), "group": match.get("group") or "",
                    "hours": (last - first).total_seconds() / 3600, "day": f"{first.day} {first:%B}",
                    "movie": c.get("movie")}
    return None


def comet_words(hunt):
    kind = f"a known {hunt['group']} sungrazing comet" if hunt["group"] == "Kreutz" else "a known comet"
    return (f"On {hunt['day']} the comet hunt found {kind} by itself in {hunt['pictures']} pictures "
            f"from the GOES-19 satellite: {hunt['seen']} of them, over {hunt['hours']:.0f} hours.")


def tonight_lines(s, live):
    """The TONIGHT card: what the night has done so far, from its sessions."""
    lines = []
    sessions = (live.get("discovery") or {}).get("sessions") or []
    for m in (live.get("discovery") or {}).get("mosaics", []):
        done = sum(p.get("state") == "done" for p in m["panels"])
        lines.append(f"{done} of {len(m['panels'])} {m['name']} fields searched")
    kept = sum(x.get("kept") or 0 for x in sessions) + (live.get("accepted") or 0)
    if kept:
        lines.append(f"{kept:,} frames kept")
    awaiting = (s.get("patrol") or {}).get("awaiting")
    if awaiting:
        lines.append(f"{plural(awaiting, 'candidate')} awaiting private review")
    elif sessions:
        lines.append("No confirmed new star yet: most nights find none, and that is still a result")
    if s.get("stage"):
        lines.append(s["stage"])
    import mission
    return lines + mission.so_far(s.get("now") or time.time())


def coming_up(steps, now, targets):
    """(title, words) for what comes next on tonight's schedule, in plain words."""
    upcoming = [x for x in steps if x.get("status") == "queued"
                and not x["label"].lower().startswith(("goto", "focus", "keep going"))]
    if not upcoming:
        return None
    step = upcoming[0]
    label = step["label"].split(",")[0]
    minutes = round(((step.get("start") or now) - now) / 60)
    title = f"COMING UP IN ~{minutes} MIN" if minutes > 1 else "COMING UP NEXT"
    words = [label]
    for name, entry in targets.get("targets", {}).items():
        if name.lower() in label.lower() and entry.get("words"):
            words.append(entry["words"])
            break
    if len(upcoming) > 1:
        words.append("Then: " + ", ".join(x["label"].split(",")[0] for x in upcoming[1:3]))
    return title, words


def moon_line(m):
    """"THE MOON · 97% illuminated · altitude 31° · 371,200 km away", from
    what is known now; None when nothing is."""
    if m.get("illumination") is None:
        return None
    parts = ["THE MOON", f"{m['illumination']}% illuminated"]
    if m.get("altitude") is not None:
        parts.append(f"altitude {m['altitude']}°")
    if m.get("distance_km"):
        parts.append(f"{m['distance_km']:,.0f} km away")
    return " · ".join(parts)


def moon_notices(entry, m):
    """What to look for on the Moon tonight: near full, the short shadows,
    the rays and the maria; otherwise the terminator, where the shadows are
    long. Each from its own list in stream-targets.toml."""
    full = (m.get("illumination") or 0) >= FULLISH
    return entry.get("notice_full" if full else "notice_terminator", []) + entry.get("notice", [])


def crawl_text(s, live, now, targets):
    parts = ["TONIGHT"]
    if s.get("kind") == "moon":
        parts.append(moon_line(s.get("moon") or {}) or "imaging the Moon")
    elif s.get("kind") == "patrol":
        parts.append(f"{s.get('target')} nova patrol")
    elif s.get("kind") == "transit":
        parts.append(f"{s['transit']['planet']} transit")
    else:
        parts.append(f"imaging {s.get('target')}")
    parts += tonight_lines(s, live)[:2]
    nxt = coming_up((live.get("schedule") or {}).get("steps") or [], now, targets)
    if nxt:
        parts.append("next: " + nxt[1][0])
    return "   ·   ".join(parts)


def host_line(s):
    """The machine's own status, said as a presenter would."""
    name = s.get("target")
    if s.get("kind") == "transit":
        return (f"TELESCOPEYOKE · I'm measuring {name}'s brightness every few seconds, "
                "waiting for the planet's shadow.")
    if s.get("kind") == "moon":
        return ("TELESCOPEYOKE · I'm taking a fast video: only the sharpest frames will be kept."
                if s.get("lucky") else "TELESCOPEYOKE · I'm taking short exposures of the Moon and combining them.")
    if s.get("kind") == "patrol":
        return f"TELESCOPEYOKE · I'm searching this part of {name} for any star that wasn't here before."
    exposure = s.get("exposure")
    return (f"TELESCOPEYOKE · I'm building a deeper picture of {name}"
            + (f": another {exposure:g} s exposure is on its way." if exposure else "."))


def plan(s, live, now=None, story=None, targets=None):
    """What the presenter adds to this picture (see the module's words)."""
    story = story or STORY
    now = now or time.time()
    if targets is None:
        import streamlook
        targets = streamlook.targets()
    out = {"chapter": "NOW", "card": None, "line": None, "explainer": None, "crawl": None}
    if s.get("kind") in SEGMENTS:
        # Focusing or polar alignment: one card at a time from its own pool,
        # each held SEGMENT_S, beside the live graphics.
        if story.start is None:
            story.start = now
        text = story.pick(f"segment-{s['kind']}", targets.get("stories", {}).get(s["kind"], []),
                          int((now - story.start) // SEGMENT_S))
        out.update(chapter="HOW IT WORKS", card=(SEGMENTS[s["kind"]], [text]) if text else None)
        return out
    if s.get("candidate") or (s.get("last_age") or 0) > 120 or s.get("kind") not in ("patrol", "transit", "picture", "moon"):
        return out                    # a follow-up or a warning has the screen
    if story.start is None:
        story.start = now
    elapsed = now - story.start
    entry = targets.get("targets", {}).get(s.get("target"), {})
    prog = targets.get("programmes", {}).get(s["kind"], {})
    stories = targets.get("stories", {})
    chapter, slot = chapter_at(elapsed)
    out["chapter"] = chapter
    if chapter == "SCIENCE":
        text = story.pick(f"science-{s.get('target')}-{s['kind']}",
                          entry.get("facts", []) + entry.get("why", []) + prog.get("explainers", []), slot)
        out["card"] = ("SCIENCE", [text]) if text else None
    elif chapter == "HOW IT WORKS":
        pool = prog.get("method", []) + [t for _, t in made(s, live)] + stories.get("stacking", []) \
            + stories.get("discovery", []) + stories.get("plate_solving", []) + stories.get("focus", []) \
            + stories.get("telescope", [])
        hunt = comet_hunt(now)
        if hunt:
            pool.append(comet_words(hunt))
        import streamchat
        voted = streamchat.tally(now)
        topic = streamchat.VOTE_TOPICS.get(voted[0][0]) if voted else None
        if topic and stories.get(topic):
            # The chat's choice (!vote): its pool first.
            text = story.pick(f"how-voted-{topic}", stories[topic], slot)
            out["card"] = ("HOW IT WORKS · CHOSEN BY CHAT", [text]) if text else None
        else:
            text = story.pick(f"how-{s['kind']}", pool, slot)
            out["card"] = ("HOW IT WORKS", [text]) if text else None
    elif chapter == "TONIGHT":
        lines = tonight_lines(s, live)
        out["card"] = ("SO FAR TONIGHT", lines) if lines else None
    elif chapter == "RESULT":
        # One raw frame and what has been made of it (mission.reveal), when something has.
        import mission
        out["card"] = ("RAW → RESULT", []) if s.get("reveal") or mission.reveal(s, now) else None
    elif chapter == "COMING UP":
        nxt = coming_up((live.get("schedule") or {}).get("steps") or [], now, targets)
        out["card"] = nxt if nxt else ("COMING UP", ["This is the last target tonight: it carries on until dawn."])
    if out["card"] is None:
        out["chapter"] = "NOW"
    # A line across the picture, while the panel shows NOW: what to look for, or the presenter.
    if chapter == "NOW" and elapsed % LINE_EVERY < LINE_S and elapsed >= LINE_EVERY / 2:
        notices = moon_notices(entry, s.get("moon") or {}) if s["kind"] == "moon" else entry.get("notice", [])
        pool = [f"LOOK CLOSELY · {t}" for t in notices] + [host_line(s)]
        if s["kind"] == "moon" and moon_line(s.get("moon") or {}):
            pool.append(moon_line(s["moon"]))
        out["line"] = story.pick("line", pool, int(elapsed // LINE_EVERY))
    # No explainer drawn over the picture: what the telescope sees is never
    # covered (30 October 2026: "I don't see the point in broadcasting 'we
    # are stacking' when the scope is seeing stuff"). The side panel tells it.
    if elapsed % CRAWL_EVERY < CRAWL_S and elapsed >= CRAWL_EVERY / 2:
        out["crawl"] = crawl_text(s, live, now, targets)
    return out
