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


def test_a_document_goes_as_the_file_itself(bot, tmp_path):
    """30 October 2026: "full res image as an attachment please"."""
    picture = tmp_path / "Moon.jpg"
    picture.write_bytes(b"jpg")
    calls = []
    sent = notify.send("Stack finished", pictures=[(picture, "Moon")], documents=[(picture, "Moon (full size)")],
                       post=lambda url, **k: calls.append((url, k)) or Reply())
    assert sent == 3 and [c[0].rsplit("/", 1)[1] for c in calls] == ["sendMessage", "sendPhoto", "sendDocument"]
    assert "document" in calls[2][1]["files"] and calls[2][1]["data"]["caption"] == "Moon (full size)"


def test_a_failure_to_send_does_not_stop_the_caller(bot):
    def post(*a, **k):
        raise requests.ConnectionError("no network")
    said = []
    assert notify.send("hello", post=post, say=said.append) == 0 and "not sent" in said[0]


def test_a_busy_telegram_is_waited_for_and_tried_again(bot):
    class Busy(Reply):
        status_code = 429

        def json(self):
            return {"ok": False, "parameters": {"retry_after": 7}}
    replies, waits = [Busy(), Reply()], []
    sent = notify.send("hello", post=lambda *a, **k: replies.pop(0), sleep=waits.append)
    assert sent == 1 and waits == [8] and not replies


def test_every_message_is_kept_on_the_laptop_as_well(bot, tmp_path, monkeypatch):
    """20 October 2026: alerts reached the phone with nothing on the laptop
    to say so, and the agent watching the night could not comment on them."""
    import json
    monkeypatch.setattr(notify, "SENT_LOG", tmp_path / "sent.jsonl")
    notify.send("M31-P8: 4 unexplained candidates", post=lambda url, **k: Reply())
    kept = [json.loads(line) for line in (tmp_path / "sent.jsonl").read_text().splitlines()]
    assert kept[0]["text"].startswith("M31-P8") and kept[0]["sent"] == 1


def test_a_finished_stack_sends_its_picture(monkeypatch, tmp_path):
    """30 October 2026: "whenever the stacks finish send me the pics on Telegram"."""
    import restack
    sent = []
    documents = []

    def send(text, pictures=(), documents=(), **kw):
        sent.append((text, list(pictures)))
        attached.extend(documents)
        return 3
    attached = documents
    monkeypatch.setattr(notify, "send", send)
    picture = tmp_path / "Moon.best10.sharp.jpg"
    assert notify.stack_ready("Moon, the best 100 of 1000 frames", picture) == 3
    assert sent[-1] == ("Stack finished: Moon, the best 100 of 1000 frames", [(picture, "Moon, the best 100 of 1000 frames")])
    assert documents == [(picture, "Moon, the best 100 of 1000 frames (full size)")]
    full = tmp_path / "Moon.best10.sharp.fullsize.jpg"
    notify.stack_ready("Moon", picture, full=full)
    assert documents[-1] == (full, "Moon (full size)") and sent[-1][1] == [(picture, "Moon")]
    session = tmp_path / "M34" / "20261030-025230"
    restack.tell(session, {"stacked": 12, "total_exposure_s": 192})
    assert sent[-1][0] == "Stack finished: M34, 12 frames, 3 min of light"
    assert sent[-1][1][0][0] == session / "final.jpg"


def test_the_command_sends_a_picture_after_its_message(monkeypatch, tmp_path):
    import argparse
    sent = []
    monkeypatch.setattr(notify, "settings", lambda: ("token", "chat"))
    monkeypatch.setattr(notify, "send", lambda text, pictures=(), documents=(), **kw:
                        sent.append((text, pictures, documents)) or 3)
    args = argparse.Namespace(test=False, text=["Stack", "finished"], picture=[str(tmp_path / "m.jpg")],
                              file=[str(tmp_path / "m.fits")], json=False)
    assert notify.run(args, say=lambda m: None) == {"sent": 3}
    assert sent == [("Stack finished", [(str(tmp_path / "m.jpg"), "Stack finished")],
                     [(str(tmp_path / "m.fits"), "Stack finished")])]
