import json
import os
import time

import pytest

import youtube


class Reply:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def json(self):
        return self.data


@pytest.fixture
def signed(tmp_path, monkeypatch):
    monkeypatch.setattr(youtube, "TOKEN_FILE", tmp_path / "youtube.json")
    youtube._SENT["listing"] = None
    return tmp_path


def test_the_listing_names_the_subject_the_plan_and_the_science(signed):
    """1 November 2026: the YouTube title and description were set by hand;
    they come from the stream's own title and tonight's schedule."""
    state = {"kind": "transit", "target": "TOI-2046", "mission": {"goal": "Measure a planet crossing its star."}}
    title, text, tags = youtube.listing("Exoplanet transit LIVE: timing TOI-2046 b crossing its star | TelescopeYoke",
                                        state, ["00:10-04:20 TOI-2046 b transit"], "Timing the transit.")
    assert title == "Exoplanet transit LIVE: timing TOI-2046 b crossing its star | TelescopeYoke"
    assert len(title) <= youtube.TITLE_MOST
    assert "Tonight's plan (UK time):\n- 00:10-04:20 TOI-2046 b transit" in text and "Timing the transit." in text
    assert "#exoplanet" in text and tags[0] == "exoplanet" and "TOI-2046" in tags
    long_title, _, _ = youtube.listing("x" * 150, {"kind": "picture"})
    assert len(long_title) == youtube.TITLE_MOST


def test_the_plan_lines_come_from_the_schedule():
    start = time.mktime((2026, 11, 2, 0, 10, 0, 0, 0, -1))
    lines = youtube.plan_lines({"steps": [
        {"label": "M31 nova patrol", "status": "done", "start": start - 4000, "end": start - 1000},
        {"label": "TOI-2046 b transit", "status": "queued", "start": start, "end": start + 15000},
        {"label": "gone", "status": "failed", "start": start, "end": start}]})
    assert lines[0].endswith("M31 nova patrol (done)") and lines[1].startswith("00:10-04:20 TOI-2046 b")
    assert len(lines) == 2


def test_nothing_is_sent_until_signed_in(signed):
    assert youtube.set_broadcast("t", "d", ["a"], get=lambda *a, **k: pytest.fail("sent")) is False
    assert not youtube.signed_in()


def test_the_live_broadcast_gets_the_title_and_keeps_its_other_fields(signed):
    youtube._keep({"client_id": "c", "client_secret": "s", "access_token": "A", "refresh_token": "R",
                   "expires_at": time.time() + 3600})
    sent = []

    def get(url, params=None, **k):
        if url.endswith("liveBroadcasts"):
            return Reply({"items": [{"id": "VID"}]})
        return Reply({"items": [{"snippet": {"title": "old", "defaultLanguage": "en-GB", "thumbnails": {}}}]})

    def put(url, params=None, json=None, **k):
        sent.append(json)
        return Reply({}, 200)
    said = []
    assert youtube.set_broadcast("New title", "words", ["nova"], say=said.append, get=get, put=put)
    snippet = sent[0]["snippet"]
    assert sent[0]["id"] == "VID" and snippet["title"] == "New title" and snippet["categoryId"] == "28"
    assert snippet["defaultLanguage"] == "en-GB" and "thumbnails" not in snippet
    assert youtube.set_broadcast("New title", "words", ["nova"], get=pytest.fail)     # unchanged: nothing sent
    assert "YouTube title set" in said[0]


def test_youtube_trouble_never_raises(signed):
    youtube._keep({"client_id": "c", "client_secret": "s", "access_token": "A", "refresh_token": "R",
                   "expires_at": time.time() + 3600})

    def broken(*a, **k):
        raise ConnectionError("down")
    said = []
    assert youtube.set_broadcast("t", "d", [], say=said.append, get=broken) is False
    assert "left as it is" in said[0]


def test_sign_in_with_a_device_code(signed):
    client = signed / "client.json"
    client.write_text(json.dumps({"installed": {"client_id": "CID", "client_secret": "SEC"}}))
    replies = iter([Reply({"device_code": "D", "user_code": "ABC-DEF", "verification_url": "https://google.com/device",
                           "expires_in": 600, "interval": 0}),
                    Reply({"error": "authorization_pending"}),
                    Reply({"access_token": "A", "refresh_token": "R", "expires_in": 3600})])
    said = []
    assert youtube.login(client, say=said.append, post=lambda *a, **k: next(replies), sleep=lambda s: None)
    assert "ABC-DEF" in said[0] and youtube.signed_in()
    if os.name != "nt":                      # Windows has no such file modes
        assert oct(youtube.TOKEN_FILE.stat().st_mode & 0o777) == "0o600"


def test_a_long_title_loses_the_next_step_not_half_a_name():
    title, _, _ = youtube.listing("Nova hunt LIVE: Andromeda Galaxy (M31). Is there a star that wasn't there before?"
                                  " · then TOI-2046 b transit at 00:10 | TelescopeYoke", {"kind": "patrol"})
    assert title == "Nova hunt LIVE: Andromeda Galaxy (M31). Is there a star that wasn't there before? | TelescopeYoke"
