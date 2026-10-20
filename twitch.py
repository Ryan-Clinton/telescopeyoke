"""The Twitch channel's title, category and tags, set from what the telescope
is doing, each time the stream starts and each time it moves to a new target.

    ./stream.py twitch-login       once: sign this laptop in to the channel (a code to enter at twitch.tv/activate)

Twitch only lets an app change a channel with the owner's permission. The app
is "TelescopeYoke", registered at dev.twitch.tv as a public client: its
client ID goes in config.toml as [stream] twitch_client_id, and it is not a
secret. The person signs in once with Twitch's device code (they type a short
code at twitch.tv/activate), granting only channel:manage:broadcast (title,
category and tags). The tokens are kept in ~/.config/telescopeyoke/twitch.json,
readable only by them, never shown and never logged. A public client's sign-in
lasts while it is used at least once a month.

Nothing here may stop the stream: every failure is said once and the stream
goes on with the channel's info as it was.
"""
import json
import os
import time
from pathlib import Path

import requests

import config

TOKEN_FILE = Path(os.path.expanduser("~/.config/telescopeyoke/twitch.json"))
SCOPE = "channel:manage:broadcast"
DEVICE = "https://id.twitch.tv/oauth2/device"
TOKEN = "https://id.twitch.tv/oauth2/token"
API = "https://api.twitch.tv/helix"
SCIENCE = "509670"          # Twitch's "Science & Technology" category
BASE_TAGS = ["Astronomy", "Telescope", "Space", "Science", "Astrophotography"]
SITE = "TelescopeYoke"


def client_id():
    return str(config.hardware().get("stream", {}).get("twitch_client_id", "")).strip() or None


def describe(state, targets=None):
    """(title, tags) for the channel, from the stream's picture state
    (streamlook.from_status). Nothing that names the place."""
    if targets is None:
        import streamlook
        targets = streamlook.targets()
    target = state.get("target") or ""
    entry = targets.get("targets", {}).get(target, {})
    name = f"{entry['common']} ({target})" if entry.get("common") else target
    kind = state.get("kind")
    if kind == "transit":
        title = f"Live telescope: timing a transit of the exoplanet {state['transit']['planet']}, as it happens"
        extra = ["Exoplanet"]
    elif kind == "patrol":
        title = f"Live telescope: nova patrol of the {name}, searching for new stars"
        extra = ["Nova", "Galaxy"]
    else:
        title = f"Live telescope: imaging {name}, one exposure at a time"
        extra = []
    title = f"{title} | {SITE}"
    tags = [t for t in BASE_TAGS + extra if " " not in t and len(t) <= 25][:10]
    return title[:140], tags


def _keep(tokens):
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as out:
        json.dump(tokens, out)
    os.chmod(TOKEN_FILE, 0o600)


def _tokens():
    try:
        return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def login(say=print, post=requests.post, get=requests.get, sleep=time.sleep, client=None):
    """Sign the laptop in with Twitch's device code: say where to go and
    the code to type, then wait for the person to approve."""
    client = client or client_id()
    if not client:
        say("No [stream] twitch_client_id in config.toml: register the app at dev.twitch.tv first "
            "(docs/live-page.md).")
        return False
    start = post(DEVICE, data={"client_id": client, "scopes": SCOPE}, timeout=30).json()
    say(f"Go to {start['verification_uri']} and approve TelescopeYoke (the code is {start['user_code']}). "
        f"Waiting up to {start['expires_in'] // 60} minutes.")
    deadline = time.time() + start["expires_in"]
    while time.time() < deadline:
        sleep(start.get("interval", 5))
        reply = post(TOKEN, data={"client_id": client, "scopes": SCOPE, "device_code": start["device_code"],
                                  "grant_type": "urn:ietf:params:oauth:grant-type:device_code"}, timeout=30)
        found = reply.json()
        if reply.status_code == 200 and found.get("access_token"):
            user = get(f"{API}/users", headers={"Authorization": f"Bearer {found['access_token']}",
                                                 "Client-Id": client}, timeout=30).json()["data"][0]
            _keep({"access_token": found["access_token"], "refresh_token": found["refresh_token"],
                   "broadcaster_id": user["id"], "login": user["login"]})
            say(f"Signed in as {user['login']}: the stream will set the channel's title, category and tags.")
            return True
        if found.get("message") not in ("authorization_pending", "slow_down"):
            say(f"Twitch refused the sign-in: {found.get('message', reply.status_code)}")
            return False
    say("The code ran out before it was approved: run it again.")
    return False


def _refresh(tokens, client, post=requests.post):
    reply = post(TOKEN, data={"client_id": client, "grant_type": "refresh_token",
                              "refresh_token": tokens["refresh_token"]}, timeout=30)
    found = reply.json()
    if reply.status_code != 200 or not found.get("access_token"):
        return None
    tokens = dict(tokens, access_token=found["access_token"], refresh_token=found.get("refresh_token",
                                                                                         tokens["refresh_token"]))
    _keep(tokens)
    return tokens


def set_channel(title, tags, say=print, patch=requests.patch, post=requests.post):
    """The channel's title, category (Science & Technology) and tags. True
    when Twitch took them; never raises."""
    client, tokens = client_id(), _tokens()
    if not client or not tokens:
        say("The channel's info was left as it is: this laptop is not signed in to Twitch "
            "(./stream.py twitch-login).")
        return False
    body = {"title": title, "game_id": SCIENCE, "tags": tags}
    try:
        for _ in range(2):
            reply = patch(f"{API}/channels", params={"broadcaster_id": tokens["broadcaster_id"]}, json=body,
                          headers={"Authorization": f"Bearer {tokens['access_token']}", "Client-Id": client},
                          timeout=30)
            if reply.status_code == 204:
                say(f"Channel title set: {title}")
                return True
            if reply.status_code != 401:
                break
            tokens = _refresh(tokens, client, post)
            if tokens is None:
                say("The Twitch sign-in has lapsed: ./stream.py twitch-login")
                return False
        say(f"Twitch did not take the channel's info ({reply.status_code}); left as it is.")
    except (requests.RequestException, ValueError, KeyError) as error:
        say(f"The channel's info was left as it is: {error}")
    return False
