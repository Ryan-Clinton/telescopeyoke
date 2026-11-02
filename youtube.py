#!/usr/bin/env python3
"""The YouTube broadcast's title, description, category, tags and thumbnail,
set from what the telescope is doing, as twitch.py does for Twitch.

    ./stream.py youtube-login --client FILE   once: sign this laptop in to the channel
                                              (a code to enter at google.com/device)
    ./youtube.py status                       what YouTube sees: the stream's ingest and
                                              every broadcast with its state
    ./youtube.py open                         open a broadcast on the arriving stream if
                                              none is open (the stream does this itself)

YouTube only lets an app change a channel's broadcasts with the owner's
permission. The app is "TelescopeYoke", a Google Cloud OAuth client of the
"TVs and limited input devices" kind, so that this laptop can sign in with a
short code typed on any computer. Its JSON (client ID and secret) is given
once with --client and kept, with the sign-in's tokens, in
~/.config/telescopeyoke/youtube.json, readable only by the person, never
shown and never logged. The scope is youtube (manage the channel's
broadcasts and videos).

Until it is signed in nothing is sent, and nothing here may stop the
stream: every failure is said once and the broadcast keeps what it had.
Built on 1 November 2026, when the YouTube title had to be set by hand in
Studio ("TelescopeYoke Live Stream" until then). A custom thumbnail needs
the channel to be phone-verified on YouTube's side; until it is, that one
step is refused and said.
"""
import json
import os
import time
from pathlib import Path

import requests

TOKEN_FILE = Path(os.path.expanduser("~/.config/telescopeyoke/youtube.json"))
SCOPE = "https://www.googleapis.com/auth/youtube"
DEVICE = "https://oauth2.googleapis.com/device/code"
TOKEN = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3"
SCIENCE = "28"               # YouTube's "Science & Technology" category
TITLE_MOST = 100             # YouTube's limit
DESCRIPTION_MOST = 5000
TAGS_MOST = 500              # characters, all tags together
SITE = "TelescopeYoke"

KIT = ("Kit: Sky-Watcher 150P (150 mm f/5 Newtonian) on an EQ3 Pro GoTo mount, Altair 183C camera; "
       "plate solving and stacking done live by TelescopeYoke's own software.")
HASHTAGS = {"transit": "#exoplanet #exoplanettransit #citizenscience",
            "patrol": "#nova #citizenscience #galaxy",
            "moon": "#moon #lunar #luckyimaging"}


def _keep(found):
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as out:
        json.dump(found, out)
    os.chmod(TOKEN_FILE, 0o600)


def _saved():
    try:
        return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def client_from(path):
    """(client_id, client_secret) from the JSON Google Cloud gives for an
    OAuth client ({"installed": {...}} or the fields themselves)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    data = data.get("installed") or data.get("web") or data
    return data["client_id"], data["client_secret"]


def login(client_file, say=print, post=requests.post, sleep=time.sleep):
    """Sign the laptop in with Google's device code: say where to go and the
    code to type, then wait for the person to approve."""
    client, secret = client_from(client_file)
    start = post(DEVICE, data={"client_id": client, "scope": SCOPE}, timeout=30).json()
    if "user_code" not in start:
        say(f"Google refused to start the sign-in: {start.get('error_description') or start.get('error')}")
        return False
    say(f"Go to {start['verification_url']} and enter the code {start['user_code']} to let TelescopeYoke "
        f"set the broadcast's title and description. Waiting up to {start['expires_in'] // 60} minutes.")
    deadline = time.time() + start["expires_in"]
    while time.time() < deadline:
        sleep(start.get("interval", 5))
        found = post(TOKEN, data={"client_id": client, "client_secret": secret, "device_code": start["device_code"],
                                  "grant_type": "urn:ietf:params:oauth:grant-type:device_code"}, timeout=30).json()
        if found.get("access_token"):
            _keep({"client_id": client, "client_secret": secret, "access_token": found["access_token"],
                   "refresh_token": found.get("refresh_token"), "expires_at": time.time() + found.get("expires_in", 0)})
            say("Signed in: the stream will set the YouTube broadcast's title, description and tags.")
            return True
        if found.get("error") not in ("authorization_pending", "slow_down"):
            say(f"Google refused the sign-in: {found.get('error_description') or found.get('error')}")
            return False
    say("The code ran out before it was approved: run it again.")
    return False


def _access(post=requests.post, clock=time.time):
    """A working access token, refreshed when it is near its end; None when
    not signed in or the refresh is refused."""
    saved = _saved()
    if not saved or not saved.get("refresh_token"):
        return None
    if clock() < saved.get("expires_at", 0) - 120:
        return saved["access_token"]
    found = post(TOKEN, data={"client_id": saved["client_id"], "client_secret": saved["client_secret"],
                              "refresh_token": saved["refresh_token"], "grant_type": "refresh_token"},
                 timeout=30).json()
    if not found.get("access_token"):
        return None
    _keep(dict(saved, access_token=found["access_token"], expires_at=clock() + found.get("expires_in", 0)))
    return found["access_token"]


def signed_in():
    saved = _saved()
    return bool(saved and saved.get("refresh_token"))


def listing(title, state, plan_lines=(), science=None):
    """(title, description, tags) for the broadcast: the title as the stream
    gives it, cut to YouTube's 100 characters; a description of tonight's
    plan from the schedule, what the observation is for, the kit and the
    mission's hashtags. Only what is measured or planned; nothing that names
    the place."""
    title = title.replace(f" | {SITE}", "")
    if len(title) > TITLE_MOST and " · then " in title:
        # Never cut mid-name ("· then TOI-2046 b", 1 November 2026): the plan's
        # next step goes first; the description has the whole plan.
        title = title.split(" · then ")[0]
    if len(f"{title} | {SITE}") <= TITLE_MOST:
        title = f"{title} | {SITE}"
    lines = ["A small automatic backyard telescope, live: every picture on screen is real and comes straight "
             "from the camera."]
    if (state.get("mission") or {}).get("goal"):
        lines += ["", f"Now: {state['mission']['goal']}"]
    if science:
        lines += ["", science]
    if plan_lines:
        lines += ["", "Tonight's plan (UK time):"] + [f"- {line}" for line in plan_lines]
    kind = state.get("kind")
    lines += ["", KIT, "", f"#astronomy #telescope #astrophotography #livestream {HASHTAGS.get(kind, '#space')}"]
    words = {"transit": ["exoplanet", "exoplanet transit", "citizen science"],
             "patrol": ["nova", "galaxy", "citizen science"],
             "moon": ["moon", "lunar", "lucky imaging"]}.get(kind, ["deep sky"])
    tags, total = [], 0
    for tag in words + [str(state.get("target") or ""), "astronomy", "telescope", "astrophotography",
                        "live telescope", "space"]:
        if tag and tag not in tags and total + len(tag) + 1 <= TAGS_MOST:
            tags.append(tag)
            total += len(tag) + 1
    return title[:TITLE_MOST], "\n".join(lines)[:DESCRIPTION_MOST], tags


def plan_lines(schedule):
    """Tonight's steps from the schedule (schedule.view), as "00:10-04:20
    TOI-2046 b transit": what the night is doing and will do."""
    out = []
    for s in (schedule or {}).get("steps") or []:
        if s.get("status") in ("failed", "skipped") or not s.get("start"):
            continue
        end = f"-{time.strftime('%H:%M', time.localtime(s['end']))}" if s.get("end") else ""
        done = " (done)" if s.get("status") == "done" else ""
        out.append(f"{time.strftime('%H:%M', time.localtime(s['start']))}{end} {s['label']}{done}")
    return out


_SENT = {"listing": None}


def set_broadcast(title, description, tags, thumbnail=None, say=print, get=requests.get, put=requests.put,
                  post=requests.post):
    """The live broadcast's title, description, category and tags, and its
    thumbnail from `thumbnail` (a JPEG) when given. True when YouTube took
    them, or already had them; never raises. Nothing is sent when they are
    unchanged or when not signed in."""
    if (title, description, tuple(tags)) == _SENT["listing"]:
        return True
    try:
        token = _access(post)
        if not token:
            return False
        auth = {"Authorization": f"Bearer {token}"}
        live = get(f"{API}/liveBroadcasts", params={"part": "id", "broadcastStatus": "active",
                                                    "broadcastType": "all"}, headers=auth, timeout=30).json()
        items = live.get("items") or []
        if not items:
            say("YouTube has no live broadcast on this channel now: its title is left as it is.")
            return False
        video = items[0]["id"]
        current = get(f"{API}/videos", params={"part": "snippet", "id": video}, headers=auth, timeout=30).json()
        snippet = dict((current.get("items") or [{}])[0].get("snippet") or {})
        # Kept as YouTube has them: only these four fields are ours.
        snippet.update(title=title, description=description, categoryId=SCIENCE, tags=list(tags))
        for gone in ("thumbnails", "localized", "publishedAt", "channelId", "channelTitle", "liveBroadcastContent"):
            snippet.pop(gone, None)
        reply = put(f"{API}/videos", params={"part": "snippet"}, headers=auth,
                    json={"id": video, "snippet": snippet}, timeout=30)
        if reply.status_code != 200:
            say(f"YouTube kept the broadcast's title as it was ({reply.status_code}).")
            return False
        _SENT["listing"] = (title, description, tuple(tags))
        say(f"YouTube title set: {title}")
        if thumbnail and Path(thumbnail).exists():
            picture = post(f"{UPLOAD}/thumbnails/set", params={"videoId": video},
                           headers=dict(auth, **{"Content-Type": "image/jpeg"}),
                           data=Path(thumbnail).read_bytes(), timeout=60)
            if picture.status_code != 200:
                say("YouTube refused the thumbnail (a custom thumbnail needs the channel phone-verified).")
        return True
    except Exception as error:      # the stream goes on whatever YouTube says
        say(f"The YouTube broadcast's info was left as it is: {type(error).__name__}")
        return False


def state(get=requests.get, post=requests.post):
    """What YouTube sees now: {"streams": [{id, title, status, health}],
    "broadcasts": [{id, title, life, privacy, bound, auto_start}]}, or None
    when not signed in. 2 November 2026: the fourth night running the laptop
    sent to YouTube while the channel showed nothing, and nothing said why."""
    token = _access(post)
    if not token:
        return None
    auth = {"Authorization": f"Bearer {token}"}
    streams = get(f"{API}/liveStreams", params={"part": "id,snippet,status", "mine": "true", "maxResults": 10},
                  headers=auth, timeout=30).json().get("items") or []
    casts = get(f"{API}/liveBroadcasts", params={"part": "id,snippet,status,contentDetails", "mine": "true",
                                                 "maxResults": 10}, headers=auth, timeout=30).json().get("items") or []
    return {"streams": [{"id": x["id"], "title": x["snippet"].get("title"),
                         "status": x["status"].get("streamStatus"),
                         "health": (x["status"].get("healthStatus") or {}).get("status")} for x in streams],
            "broadcasts": [{"id": b["id"], "title": b["snippet"].get("title"),
                            "life": b["status"].get("lifeCycleStatus"), "privacy": b["status"].get("privacyStatus"),
                            "bound": b["contentDetails"].get("boundStreamId"),
                            "auto_start": b["contentDetails"].get("enableAutoStart")} for b in casts]}


OPEN = ("created", "ready", "testStarting", "testing", "liveStarting", "live")


def ensure_broadcast(title, description, say=print, get=requests.get, post=requests.post, clock=time.time):
    """A broadcast open on the stream YouTube is receiving: the one already
    there, or a new public one bound to it that starts by itself. Returns
    its id, or None (not signed in, no stream arriving, or YouTube said
    no); never raises. YouTube ends a broadcast when the stream pauses (the
    stream stops after five quiet minutes) and does not always open the
    next: on 2 November 2026 every broadcast was "complete" while the
    laptop sent a healthy stream, the fourth night the channel showed
    nothing."""
    try:
        token = _access(post)
        if not token:
            return None
        found = state(get, post)
        arriving = [x["id"] for x in found["streams"] if x["status"] == "active"]
        if not arriving:
            return None
        auth = {"Authorization": f"Bearer {token}"}
        for b in found["broadcasts"]:
            if b["life"] in OPEN and b["bound"] in arriving:
                if b["life"] == "ready":
                    # Auto-start waits for the stream to begin, and one already
                    # arriving never does: start it now.
                    went = post(f"{API}/liveBroadcasts/transition", params={"broadcastStatus": "live",
                                "id": b["id"], "part": "status"}, headers=auth, timeout=30)
                    if went.status_code == 200:
                        say(f"YouTube broadcast {b['id']} started: youtube.com/watch?v={b['id']}")
                    else:       # 2 November 2026: 403 here, and auto-start took it live a minute later
                        why = ((went.json().get("error") or {}).get("errors") or [{}])[0].get("reason")
                        say(f"YouTube broadcast {b['id']} is ready; it starts with the stream "
                            f"({went.status_code} {why} on starting it now).")
                return b["id"]
        start = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(clock() + 30))
        made = post(f"{API}/liveBroadcasts", params={"part": "snippet,status,contentDetails"}, headers=auth,
                    json={"snippet": {"title": title[:TITLE_MOST], "description": description[:DESCRIPTION_MOST],
                                      "scheduledStartTime": start},
                          "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
                          # Kept open through a pause between steps: an ended broadcast is
                          # never reopened by YouTube, and the channel goes blank.
                          "contentDetails": {"enableAutoStart": True, "enableAutoStop": False,
                                             "monitorStream": {"enableMonitorStream": False}}},
                    timeout=30)
        if made.status_code != 200:
            say(f"YouTube would not open a new broadcast ({made.status_code}): the channel shows nothing.")
            return None
        video = made.json()["id"]
        bound = post(f"{API}/liveBroadcasts/bind", params={"id": video, "part": "id,contentDetails",
                                                           "streamId": arriving[0]}, headers=auth, timeout=30)
        if bound.status_code != 200:
            say(f"YouTube opened broadcast {video} but would not join it to the stream ({bound.status_code}).")
            return None
        say(f"YouTube had no open broadcast: opened {video}, starting by itself, at youtube.com/watch?v={video}")
        return video
    except Exception as error:      # the stream goes on whatever YouTube says
        say(f"YouTube's broadcast was not checked: {type(error).__name__}")
        return None


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="What YouTube sees of the channel's live stream.")
    ap.add_argument("action", choices=["status", "open"])
    args = ap.parse_args(argv)
    if args.action == "open":
        return 0 if ensure_broadcast("TelescopeYoke: live from the telescope",
                                     "Live from a 150 mm telescope in a back garden.") else 1
    found = state()
    if found is None:
        print("Not signed in to YouTube: ./stream.py youtube-login --client FILE")
        return 1
    for x in found["streams"]:
        print(f"stream {x['id']}: {x['title']!r}, {x['status']}, health {x['health']}")
    for b in found["broadcasts"]:
        print(f"broadcast {b['id']}: {b['title']!r}, {b['life']}, {b['privacy']}, "
              f"bound to {b['bound']}, auto-start {b['auto_start']}")
    if not found["broadcasts"]:
        print("no broadcasts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
