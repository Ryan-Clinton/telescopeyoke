"""The agent is shown what went to the person's phone since it last looked:
each message once, the newest first look covering the last two days."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".claude" / "hooks"))
import news  # noqa: E402


def test_each_message_to_the_phone_is_shown_to_the_agent_once(tmp_path):
    log = tmp_path / "cache" / "sent.jsonl"
    log.parent.mkdir()
    now = 1792470000.0
    rows = [{"time": now - 5 * 86400, "sent": 1, "text": "old news", "pictures": [], "animations": []},
            {"time": now - 3600, "sent": 1, "text": "Comet hunt, CCOR1: 3 heading in towards the Sun.",
             "pictures": [], "animations": ["sungrazer/x/candidate-1.gif"]},
            {"time": now - 60, "sent": 0, "text": "The telescope needs you", "pictures": [], "animations": []}]
    log.write_text("".join(json.dumps(r) + "\n" for r in rows))
    lines = news.news(tmp_path, now=now)
    text = "\n".join(lines)
    assert "Comet hunt" in text and "candidate-1.gif" in text and "(not delivered)" in text
    assert "old news" not in text and lines[0].startswith("Sent to the person's phone since you last looked (2)")
    assert news.news(tmp_path, now=now) == []
    with log.open("a") as f:
        f.write(json.dumps({"time": now + 10, "sent": 1, "text": "Observation is over"}) + "\n")
    assert "Observation is over" in "\n".join(news.news(tmp_path, now=now + 20))


def test_no_log_means_nothing_said(tmp_path):
    assert news.news(tmp_path) == []
