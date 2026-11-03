import os
import time

import requests

import feeds


def test_each_feed_says_whether_its_data_is_fresh_kept_or_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(feeds, "CACHE", tmp_path)
    feeds.used.clear()
    assert feeds._cached("seeing_1.000_2.000", 3, lambda: [1]) == [1]
    assert feeds.freshness()[0]["state"] == "fresh"
    assert feeds.freshness()[0]["source"] == "7Timer ASTRO"

    feeds._cached("seeing_1.000_2.000", 3, lambda: [2])
    assert feeds.freshness()[0]["state"] == "cached"

    # The source fails and the kept copy is older than its time: it is
    # still given, and said to be stale with the day it was fetched.
    old = time.time() - 5 * 3600
    os.utime(tmp_path / "seeing_1.000_2.000.json", (old, old))

    def broken():
        raise requests.ConnectionError("no Wi-Fi")
    assert feeds._cached("seeing_1.000_2.000", 3, broken) == [1]
    row = feeds.freshness()[0]
    assert row["state"] == "stale"
    assert row["fetched"].startswith(time.strftime("%Y-%m-%d", time.gmtime(old)))

    feeds._cached("supernovae", 12, broken)
    states = {r["source"]: r["state"] for r in feeds.freshness()}
    assert states["Rochester active supernovae"] == "unavailable"
