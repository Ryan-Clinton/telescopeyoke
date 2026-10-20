"""Setting the Twitch channel's title, category and tags from what the telescope is doing."""
import types

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
    assert (twitch.TOKEN_FILE.stat().st_mode & 0o777) == 0o600
    assert not any("new" in s or "r2" in s for s in said)           # tokens are never said


def test_without_a_sign_in_it_leaves_the_channel_alone_and_never_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(twitch, "TOKEN_FILE", tmp_path / "none.json")
    monkeypatch.setattr(twitch, "client_id", lambda: "app")
    said = []
    assert not twitch.set_channel("t", [], say=said.append, patch=None, post=None)
    assert "twitch-login" in said[0]
