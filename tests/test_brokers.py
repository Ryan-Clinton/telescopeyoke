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


DRB = {"ZTF26bright": [0.2, 0.98], "ZTF26south": [0.9], "ZTF26faint": [0.9], "ZTF26known": [None],
       "ZTF26ghost": [0.0]}


def get(url, timeout=None, params=None):
    if url.endswith("/magstats"):
        return Reply(STATS[url.split("/")[-2]])
    if url.endswith("/detections"):
        return Reply([{"drb": d, "rb": 0.7} for d in DRB[url.split("/")[-2]]])
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


def test_the_unreported_search_keeps_what_is_not_up_and_drops_what_is_reported():
    answer = brokers.search(config.example(), 30, 17.5, say=lambda *_: None, get=get, reported=REPORTED, now=NOW,
                            unreported=True)
    assert [p["oid"] for p in answer["worth_a_look"]] == ["ZTF26south", "ZTF26bright"]   # brightest first
    south = answer["worth_a_look"][0]
    assert south["highest"] is None and south["highest_at"] is None and south["minutes_up"] == 0
    assert answer["already_reported"] == 1 and answer["too_faint"] == 1 and answer["unreported"]


def test_a_ghost_by_a_bright_star_is_left_out_by_its_real_bogus_score(monkeypatch):
    ghost = dict(OBJECTS[0], oid="ZTF26ghost", meanra=10.95)
    STATS["ZTF26ghost"] = [{"fid": 1, "maglast": 15.6, "magfirst": 15.6}]
    answer = brokers.search(config.example(), 5, 17.5, say=lambda *_: None, reported=REPORTED, now=NOW,
                            get=lambda url, timeout=None, params=None: (Reply({"items": OBJECTS + [ghost]})
                                                                        if url.endswith("/") else get(url)))
    assert answer["bogus"] == 1 and "ZTF26ghost" not in [p["oid"] for p in answer["worth_a_look"]]
    bright = next(p for p in answer["worth_a_look"] if p["oid"] == "ZTF26bright")
    assert bright["real_bogus"] == 0.98                       # the best detection's score
    known = next(p for p in answer["worth_a_look"] if p["oid"] == "ZTF26known")
    assert known["real_bogus"] == 0.7                         # no deep score: the older one


def follow_get(url, timeout=None, params=None):
    if url.endswith("/magstats"):
        return Reply([{"fid": 2, "maglast": 16.74, "magfirst": 16.78}])
    return Reply({"oid": "ZTF26acaznbf", "meanra": 163.12868, "meandec": 7.22155, "lastmjd": 61322.53})


def test_following_keeps_the_place_runs_the_patrol_on_it_and_measures_it(tmp_path, monkeypatch):
    import mount
    monkeypatch.setattr(config, "DATA", tmp_path)
    asked = []
    rows = [{"session": "20261020-053000", "in_picture": True, "mag": 16.9, "error": 0.05, "limit": 19.0}]
    answer = brokers.follow("ZTF26acaznbf", 20, say=lambda *_: None, get=follow_get,
                            patrol_run=lambda a: asked.append(a) or {"programme": {"target": a.programme}},
                            measure=lambda: rows)
    assert asked[0].programme == "ZTF26acaznbf" and asked[0].minutes == 20 and not asked[0].plan
    assert answer["measured"]["mag"] == 16.9 and answer["ztf"] == {
        "mag": 16.74, "band": "ZTF r", "brightening": False, "last_seen": "2026-10-09 12:43"}
    target = mount.find_target("ztf26acaznbf")                      # the mount and shoot.py know it by name
    assert (target["ra"], target["dec"], target["name"]) == (163.12868, 7.22155, "transient")


def test_a_plan_to_follow_measures_nothing():
    measured = []
    answer = brokers.follow("ZTF26acaznbf", 20, plan=True, say=lambda *_: None, get=follow_get,
                            patrol_run=lambda a: {"plan": a.plan}, measure=lambda: measured.append(1) or [])
    assert answer["patrol"] == {"plan": True} and answer["measured"] is None and measured == []
