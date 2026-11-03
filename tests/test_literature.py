"""The literature watch: arXiv's answer read, each topic's recent papers
kept, the old left out, and nothing touches the network."""
from datetime import datetime, timezone

import feeds
import interface
import literature
from test_interface import valid

ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><id>http://arxiv.org/abs/2607.01234v1</id><published>2026-10-30T12:00:00Z</published>
<title>Evidence for a giant
  companion orbiting Tabby's star</title>
<author><name>A One</name></author><author><name>B Two</name></author><author><name>C Three</name></author>
<author><name>D Four</name></author></entry>
<entry><id>http://arxiv.org/abs/2501.00001v1</id><published>2025-01-02T00:00:00Z</published>
<title>An old one</title><author><name>E Five</name></author></entry>
</feed>"""


class Reply:
    text = ATOM

    def raise_for_status(self):
        pass


def test_each_topics_recent_papers_are_listed_and_the_old_left_out(tmp_path, monkeypatch):
    monkeypatch.setattr(feeds, "CACHE", tmp_path)
    asked = []

    def get(url, params=None, timeout=None, headers=None):
        asked.append(params["search_query"])
        return Reply()
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    found = literature.recent(30, now=now, get=get, topics=["Tabby's star"])
    assert asked == [literature.TOPICS["Tabby's star"]]
    papers = found[0]["papers"]
    assert [p["id"] for p in papers] == ["2607.01234v1"]
    assert papers[0]["title"] == "Evidence for a giant companion orbiting Tabby's star"
    assert papers[0]["authors"] == "A One, B Two, C Three et al."
    literature.recent(30, now=now, get=None, topics=["Tabby's star"])      # kept a day: not asked again
    assert {r["source"]: r["state"] for r in feeds.freshness()}["arXiv"] == "cached"
    valid(interface.envelope("literature", {"days": 30, "topics": found, "kind": "inferred"}), "literature")


def test_a_paper_stays_listed_until_it_is_marked_read_however_old(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(feeds, "CACHE", tmp_path)
    monkeypatch.setattr(config, "DATA", tmp_path)
    get = lambda url, params=None, timeout=None, headers=None: Reply()          # noqa: E731
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    first = literature.unread(now=now, get=get, topics=["Tabby's star"])[0]["papers"]
    assert [p["id"] for p in first] == ["2607.01234v1"]          # before any marking: the last 14 days only
    assert first[0]["abstract"] == ""
    literature.mark_read(["2607.01234"])                         # read, under any version
    later = literature.unread(now=datetime(2027, 6, 1, tzinfo=timezone.utc), get=get, topics=["Tabby's star"])
    assert [p["id"] for p in later[0]["papers"]] == ["2501.00001v1"]     # the old one, never read, still listed
