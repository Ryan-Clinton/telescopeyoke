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


def youtube_sky(streams, broadcasts):
    """A pretend YouTube: GET answers from these lists, POST records what is sent."""
    sent = []

    def get(url, params=None, headers=None, timeout=None):
        if url.endswith("/liveStreams"):
            return Reply({"items": streams})
        return Reply({"items": broadcasts})

    def post(url, params=None, headers=None, json=None, data=None, timeout=None):
        sent.append((url.rsplit("/", 1)[-1], params, json))
        if url.endswith("/liveBroadcasts"):
            return Reply({"id": "NEW"})
        return Reply({})
    return get, post, sent


def stream(id_, status):
    return {"id": id_, "snippet": {"title": "stream"}, "status": {"streamStatus": status,
                                                                 "healthStatus": {"status": "good"}}}


def cast(id_, life, bound):
    return {"id": id_, "snippet": {"title": "old"}, "status": {"lifeCycleStatus": life, "privacyStatus": "public"},
            "contentDetails": {"boundStreamId": bound, "enableAutoStart": True}}


def test_a_healthy_stream_with_every_broadcast_complete_gets_a_new_one(signed):
    """2 November 2026: the fourth night the laptop sent a healthy stream to
    YouTube while every broadcast was complete and the channel showed nothing."""
    youtube._keep({"refresh_token": "r", "access_token": "a", "expires_at": time.time() + 3600})
    get, post, sent = youtube_sky([stream("S1", "active")], [cast("old1", "complete", "S1")])
    said = []
    assert youtube.ensure_broadcast("Nova hunt LIVE", "text", say=said.append, get=get, post=post) == "NEW"
    made, bound = sent
    assert made[0] == "liveBroadcasts" and made[2]["contentDetails"]["enableAutoStart"]
    assert made[2]["status"]["privacyStatus"] == "public" and made[2]["snippet"]["title"] == "Nova hunt LIVE"
    assert bound[0] == "bind" and bound[1]["streamId"] == "S1" and bound[1]["id"] == "NEW"
    assert "opened NEW" in said[0]


def test_an_open_broadcast_or_no_stream_arriving_opens_nothing(signed):
    youtube._keep({"refresh_token": "r", "access_token": "a", "expires_at": time.time() + 3600})
    get, post, sent = youtube_sky([stream("S1", "active")], [cast("on", "live", "S1")])
    assert youtube.ensure_broadcast("t", "d", say=lambda s: None, get=get, post=post) == "on" and not sent
    get, post, sent = youtube_sky([stream("S1", "ready")], [cast("old", "complete", "S1")])
    assert youtube.ensure_broadcast("t", "d", say=lambda s: None, get=get, post=post) is None and not sent
    get, post, sent = youtube_sky([], [])
    youtube.TOKEN_FILE.unlink()
    assert youtube.ensure_broadcast("t", "d", say=lambda s: None, get=get, post=post) is None   # not signed in


def test_a_ready_broadcast_on_an_arriving_stream_is_started(signed):
    """Auto-start never fires for a stream that was already arriving."""
    youtube._keep({"refresh_token": "r", "access_token": "a", "expires_at": time.time() + 3600})
    get, post, sent = youtube_sky([stream("S1", "active")], [cast("B", "ready", "S1")])
    assert youtube.ensure_broadcast("t", "d", say=lambda s: None, get=get, post=post) == "B"
    assert [(name, params["broadcastStatus"]) for name, params, _ in sent] == [("transition", "live")]


def test_before_the_stream_starts_a_broadcast_is_opened_on_the_channels_stream(signed):
    """The broadcast must wait for the stream: auto-start acts when the
    stream begins, and one made after sat at "ready" (2 November 2026)."""
    youtube._keep({"refresh_token": "r", "access_token": "a", "expires_at": time.time() + 3600})
    get, post, sent = youtube_sky([stream("Default", "ready"), stream("S1", "inactive")],
                                  [cast("old1", "complete", "S1"), cast("old2", "complete", "S1")])
    assert youtube.ensure_broadcast("t", "d", say=lambda s: None, get=get, post=post, before_start=True) == "NEW"
    assert sent[1][0] == "bind" and sent[1][1]["streamId"] == "S1"
    # Already one waiting: nothing new, and it is not started by hand.
    get, post, sent = youtube_sky([stream("S1", "inactive")], [cast("B", "ready", "S1")])
    assert youtube.ensure_broadcast("t", "d", say=lambda s: None, get=get, post=post, before_start=True) == "B"
    assert not sent


def test_a_stopped_stream_ends_the_broadcast_still_on_air(signed):
    """4 November 2026: broadcasts are opened with auto-stop off, so nothing
    ended them when the night was over and the channel stayed "live"."""
    youtube._keep({"refresh_token": "r", "access_token": "a", "expires_at": time.time() + 3600})
    get, post, sent = youtube_sky([stream("S1", "inactive")], [cast("B", "live", "S1"), cast("old", "complete", "S1")])
    said = []
    assert youtube.end_broadcasts(say=said.append, get=get, post=post) == 1
    assert [(name, params["broadcastStatus"], params["id"]) for name, params, _ in sent] == [("transition", "complete", "B")]
    youtube.TOKEN_FILE.unlink()
    assert youtube.end_broadcasts(say=said.append, get=get, post=post) == 0      # not signed in: nothing sent
