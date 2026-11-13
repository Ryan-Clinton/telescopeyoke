#!/usr/bin/env python3
"""When the user's message is about the sky, the satellite's answer comes with it.

A UserPromptSubmit hook. A message that mentions cloud, a gap, clear sky,
the forecast, rain or the stars gets the last saved `./clouds.py --approach`
(the nearest clear sky, the cloud's movement, when clear sky gets here) and
`./rain.py` answers added before the reply is written, with their ages, so
the reply starts from the satellite and not from the camera's star count.
It only reads: an old or missing answer starts a fresh look in the
background for the next message.

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
import time
from pathlib import Path

WORDS = re.compile(r"\b(cloud\w*|gaps?|clear\w*|overcast|rain\w*|showers?|forecast|met office|"
                   r"sky|skies|haze|hazy|stars?)\b", re.I)


FRESH_MIN = {"satellite": 15, "radar": 15}     # an answer older than this is said as old, and a new look started
STALE_PICTURE_MIN = 40                          # clouds.SATELLITE_STALE_MIN: an older picture is not tonight's sky


def _kept(path, name, script, args, root, picture_key):
    """The saved answer's lines with its age said, and a fresh look started
    in the background when it is old or missing. Never fetches itself: the
    timers and watches own the network, so this always answers at once
    (13 November 2026: a slow fetch here could lose the whole briefing, the
    radar's with the satellite's)."""
    import datetime as dt
    try:
        kept = json.loads(path.read_text(encoding="utf-8"))
        lines, made = kept.get("lines") or [], float(kept["t"])
    except (OSError, ValueError, KeyError, TypeError):
        kept, lines, made = None, [], None
    age = None if made is None else (time.time() - made) / 60
    out = list(lines)
    picture_age = None
    try:
        picture_age = (time.time() - dt.datetime.fromisoformat(kept[picture_key]).timestamp()) / 60
    except (TypeError, KeyError, ValueError):
        pass
    if kept is None:
        out = [f"{name}: no saved answer"]
    elif picture_age is not None and picture_age > STALE_PICTURE_MIN:
        out = [f"{name}: the saved answer is from a picture {picture_age:.0f} min old: history, not the sky now"] + out
    elif age is not None and age > FRESH_MIN[name]:
        out = [f"{name}: the saved answer is {age:.0f} min old"] + out
    if kept is None or age is None or age > FRESH_MIN[name] or (picture_age or 0) > STALE_PICTURE_MIN:
        try:
            subprocess.Popen([sys.executable, str(root / script), *args], cwd=root, start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            out.append(f"{name}: a fresh look has been started; it is in the next message's briefing")
        except OSError as problem:
            out.append(f"{name}: a fresh look could not be started ({problem})")
    return out


def main():
    try:
        prompt = json.load(sys.stdin).get("prompt") or ""
    except ValueError:
        return
    if not WORDS.search(prompt):
        return
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
    sys.path.insert(0, str(root))
    try:
        import config
        cache = config.DATA / "cache"
    except Exception:      # noqa: BLE001 - never blocks
        cache = root / "cache"
    lines = _kept(cache / "cloud_approach.json", "satellite", "clouds.py", ["--approach"], root, "picture")
    lines += _kept(cache / "rain.json", "radar", "rain.py", [], root, "picture_at")
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": ("The user's message is about the sky. The satellite and the radar, as last saved "
                              "(./clouds.py --approach, ./rain.py); answer from this, with the arrival time and "
                              "the answers' ages, before anything the camera saw:\n" + "\n".join(lines))}}))


if __name__ == "__main__":
    main()
