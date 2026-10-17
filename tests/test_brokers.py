"""Public alerts: of the broker's new transients, the ones bright enough and
up in the dark here are kept, a reported one is named and put last, and
nothing touches the network."""
import datetime

import pytest

import brokers
import config

NOW = datetime.datetime(2026, 10, 16, 21, 0, tzinfo=datetime.timezone.utc)   # an October evening
OBJECTS = [
    {"oid": "ZTF26bright", "meanra": 10.9, "meandec": 41.4, "firstmjd": 61328.9, "ndet": 4, "probability": 0.9},
    {"oid": "ZTF26south", "meanra": 10.9, "meandec": -80.0, "firstmjd": 61328.9, "ndet": 3, "probability": 0.8},
    {"oid": "ZTF26faint", "meanra": 12.0, "meandec": 40.0, "firstmjd": 61328.9, "ndet": 2, "probability": 0.7},
    {"oid": "ZTF26known", "meanra": 23.5, "meandec": 30.7, "firstmjd": 61328.9, "ndet": 6, "probability": 0.6},
]
STATS = {"ZTF26bright": [{"fid": 1, "maglast": 16.4, "magfirst": 17.1}, {"fid": 2, "maglast": 16.6, "magfirst": 16.9}],
         "ZTF26south": [{"fid": 2, "maglast": 15.0, "magfirst": 15.0}],
         "ZTF26faint": [{"fid": 2, "maglast": 19.2, "magfirst": 19.0}],
         "ZTF26known": [{"fid": 2, "maglast": 16.0, "magfirst": 15.8}]}
REPORTED = [{"name": "SN 2026xyz", "ra": 23.5, "dec": 30.7 + 1 / 3600}]


class Reply:
    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body

    def raise_for_status(self):
        pass


def get(url, timeout=None, params=None):
    if url.endswith("/magstats"):
        return Reply(STATS[url.split("/")[-2]])
    return Reply({"items": OBJECTS})


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr(brokers, "PAUSE", 0)


def test_only_what_is_bright_enough_and_up_here_is_kept():
    answer = brokers.search(config.example(), 5, 17.5, say=lambda *_: None, get=get, reported=REPORTED, now=NOW)
    names = [p["oid"] for p in answer["worth_a_look"]]
    assert names == ["ZTF26bright", "ZTF26known"]            # the reported one last
    assert answer["not_up"] == 1 and answer["too_faint"] == 1 and answer["already_reported"] == 1
    bright = answer["worth_a_look"][0]
    assert bright["mag"] == 16.4 and bright["band"] == "ZTF g" and bright["brightening"]
    assert bright["reported"] is None and bright["highest"] > 60 and bright["minutes_up"] >= brokers.MIN_MINUTES
    assert "wis-tns.org" in bright["links"]["tns"]
    assert answer["worth_a_look"][1]["reported"] == "SN 2026xyz"


def test_older_objects_than_asked_for_are_left_out():
    old = dict(OBJECTS[0], oid="ZTF26old", firstmjd=61300.0)
    found = brokers.new_objects(5, NOW, lambda *a, **k: Reply({"items": [OBJECTS[0], old]}))
    assert [o["oid"] for o in found] == ["ZTF26bright"]
