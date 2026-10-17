"""Alerts to the person's phone: nothing is sent without a bot set up, or
from the tests; long text is split, pictures follow it, and a failure to
send never stops the caller. Nothing here touches the network."""
import pytest
import requests

import notify


class Reply:
    def raise_for_status(self):
        pass


@pytest.fixture
def bot(monkeypatch):
    monkeypatch.setenv("TY_TELEGRAM_TOKEN", "123:abc")
    monkeypatch.setenv("TY_TELEGRAM_CHAT", "42")
    monkeypatch.setattr(notify, "quiet", lambda: False)


def test_nothing_is_sent_without_a_bot(monkeypatch):
    monkeypatch.delenv("TY_TELEGRAM_TOKEN", raising=False)
    monkeypatch.setattr(notify.config, "FILE", notify.config.ROOT / "no-such-config.toml")
    assert notify.settings() == (None, None)
    assert notify.send("hello", post=lambda *a, **k: pytest.fail("sent")) == 0


def test_nothing_is_sent_from_the_tests(monkeypatch):
    monkeypatch.setenv("TY_TELEGRAM_TOKEN", "123:abc")
    monkeypatch.setenv("TY_TELEGRAM_CHAT", "42")
    assert notify.send("hello", post=lambda *a, **k: pytest.fail("sent")) == 0


def test_long_text_is_split_and_pictures_follow(bot, tmp_path):
    picture = tmp_path / "p.png"
    picture.write_bytes(b"png")
    calls = []
    sent = notify.send("x" * (notify.LONGEST + 10), pictures=[(picture, "cut-out")], animations=[(tmp_path / "gone.gif", "")],
                       post=lambda url, **k: calls.append((url, k)) or Reply())
    assert sent == 3 and [c[0].rsplit("/", 1)[1] for c in calls] == ["sendMessage", "sendMessage", "sendPhoto"]
    assert calls[0][0].startswith("https://api.telegram.org/bot123:abc/") and calls[0][1]["data"]["chat_id"] == "42"


def test_a_failure_to_send_does_not_stop_the_caller(bot):
    def post(*a, **k):
        raise requests.ConnectionError("no network")
    said = []
    assert notify.send("hello", post=post, say=said.append) == 0 and "not sent" in said[0]
