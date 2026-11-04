"""Setting the Twitch channel's title, category and tags from what the telescope is doing."""
import types
import sys

import twitch

TARGETS = {"targets": {"M31": {"common": "Andromeda Galaxy"}}}


def test_the_title_and_tags_follow_the_programme():
    title, tags = twitch.describe({"kind": "transit", "target": "WASP-12", "transit": {"planet": "WASP-12 b"}},
                                  TARGETS)
    assert "WASP-12 b" in title and title.endswith("| TelescopeYoke") and "Exoplanet" in tags
    title, tags = twitch.describe({"kind": "patrol", "target": "M31"}, TARGETS)
    assert "Andromeda Galaxy (M31)" in title and "Nova" in tags
    title, tags = twitch.describe({"kind": "picture", "target": "M42"}, TARGETS)
    assert "imaging M42" in title
    assert len(title) <= 140 and len(tags) <= 10 and all(" " not in t and len(t) <= 25 for t in tags)


def test_it_sets_the_channel_and_signs_in_again_when_the_token_has_lapsed(tmp_path, monkeypatch):
    monkeypatch.setattr(twitch, "_SENT", {"info": None, "wait_until": 0.0})
    monkeypatch.setattr(twitch, "TOKEN_FILE", tmp_path / "twitch.json")
    monkeypatch.setattr(twitch, "client_id", lambda: "app")
    twitch._keep({"access_token": "old", "refresh_token": "r1", "broadcaster_id": "42", "login": "x"})
    sent = []

    def patch(url, params, json, headers, timeout):
        sent.append((headers["Authorization"], json))
        return types.SimpleNamespace(status_code=401 if headers["Authorization"] == "Bearer old" else 204)

    def post(url, data, timeout):
        assert data["grant_type"] == "refresh_token" and "client_secret" not in data
        return types.SimpleNamespace(status_code=200, json=lambda: {"access_token": "new", "refresh_token": "r2"})
    said = []
    assert twitch.set_channel("A title", ["Astronomy"], say=said.append, patch=patch, post=post)
    assert [a for a, _ in sent] == ["Bearer old", "Bearer new"]
    assert sent[-1][1] == {"title": "A title", "game_id": twitch.SCIENCE, "tags": ["Astronomy"]}
    assert twitch._tokens()["refresh_token"] == "r2"
    assert sys.platform == "win32" or (twitch.TOKEN_FILE.stat().st_mode & 0o777) == 0o600   # Windows has no such modes
    assert not any("new" in s or "r2" in s for s in said)           # tokens are never said


def test_without_a_sign_in_it_leaves_the_channel_alone_and_never_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(twitch, "_SENT", {"info": None, "wait_until": 0.0})
    monkeypatch.setattr(twitch, "TOKEN_FILE", tmp_path / "none.json")
    monkeypatch.setattr(twitch, "client_id", lambda: "app")
    said = []
    assert not twitch.set_channel("t", [], say=said.append, patch=None, post=None)
    assert "twitch-login" in said[0]


def test_unchanged_info_is_not_sent_again_and_too_many_waits(tmp_path, monkeypatch):
    monkeypatch.setattr(twitch, "_SENT", {"info": None, "wait_until": 0.0})
    monkeypatch.setattr(twitch, "TOKEN_FILE", tmp_path / "twitch.json")
    monkeypatch.setattr(twitch, "client_id", lambda: "app")
    twitch._keep({"access_token": "a" * 20, "refresh_token": "r" * 20, "broadcaster_id": "42", "login": "x"})
    calls = []
    answers = iter([429, 204])

    def patch(url, params, json, headers, timeout):
        calls.append(json["title"])
        return types.SimpleNamespace(status_code=next(answers), headers={})
    now = [1000.0]
    assert not twitch.set_channel("t", ["A"], say=lambda m: None, patch=patch, clock=lambda: now[0])
    assert not twitch.set_channel("t", ["A"], say=lambda m: None, patch=patch, clock=lambda: now[0] + 10)
    assert len(calls) == 1                                       # waited after the 429
    assert twitch.set_channel("t", ["A"], say=lambda m: None, patch=patch, clock=lambda: now[0] + 61)
    assert twitch.set_channel("t", ["A"], say=lambda m: None, patch=patch, clock=lambda: now[0] + 62)
    assert len(calls) == 2                                       # the same info is not sent again


def test_a_token_never_shows_in_what_is_said():
    tokens = {"access_token": "secret-access-123456", "refresh_token": "secret-refresh-123456"}
    assert "secret" not in twitch.redacted("failed with secret-access-123456 and secret-refresh-123456", tokens)


def test_the_title_says_what_comes_next_in_tonight_s_plan():
    """1 November 2026: the streams named after the night's plan."""
    title, _ = twitch.describe({"kind": "patrol", "target": "M31",
                                "next": "TOI-2046 b transit at 00:10 UTC"}, TARGETS)
    assert title.endswith("· then TOI-2046 b transit at 00:10 | TelescopeYoke") and len(title) <= 140
    long_next = "x" * 200
    title, _ = twitch.describe({"kind": "patrol", "target": "M31", "next": long_next}, TARGETS)
    assert long_next not in title and len(title) <= 140


def test_titles_lead_with_the_subject_and_tags_with_the_mission():
    """1 November 2026: a searcher types "nova", "exoplanet transit" or a
    planet's name; the titles now lead with what is observed, and each
    mission's own tags come before the channel's general ones."""
    import mission
    patrol = mission.of({"kind": "patrol", "target": "M31", "now": 1e9, "patrol": {"panels": []}}, 1e9, {})
    assert patrol["stream_title"].startswith("Nova hunt LIVE: Andromeda Galaxy (M31)")
    transit = mission.of({"kind": "transit", "target": "TOI-2046", "now": 1e9, "last_age": 5, "exposure": 4,
                          "transit": {"planet": "TOI-2046 b", "ingress": 1e9 + 600, "egress": 1e9 + 6000}}, 1e9, {})
    assert transit["stream_title"] == "Exoplanet transit LIVE: timing TOI-2046 b crossing its star"
    _, tags = twitch.describe({"kind": "transit", "target": "TOI-2046", "transit": {"planet": "TOI-2046 b"}}, TARGETS)
    assert tags[0] == "Exoplanet" and "CitizenScience" in tags and len(tags) <= 10


def test_the_title_says_it_is_waiting_for_the_cloud():
    import twitch
    title, tags = twitch.describe({"target": "NGC 869", "kind": "picture", "cloud": True,
                                   "mission": {"stream_title": "Live telescope: imaging NGC 869"}},
                                  targets={"targets": {}})
    assert title.startswith("Live telescope: waiting for the cloud to clear at NGC 869 |")
    named, _ = twitch.describe({"target": "M31", "kind": "picture", "cloud": True},
                               targets={"targets": {"M31": {"common": "Andromeda Galaxy"}}})
    assert named.startswith("Live telescope: waiting for the cloud to clear over the Andromeda Galaxy (M31)")
    assert "Clouds" in tags


def test_the_title_says_the_telescope_is_getting_ready_while_the_setup_card_shows():
    import twitch
    title, _ = twitch.describe({"target": "NGC 869", "kind": "picture", "setup": True}, targets={"targets": {}})
    assert title.startswith("Live telescope: getting ready for the night")
    title, _ = twitch.describe({"target": "NGC 869", "kind": "picture", "setup": True, "cloud": True},
                               targets={"targets": {}})
    assert "waiting for the cloud" in title
