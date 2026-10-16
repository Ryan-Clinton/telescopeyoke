"""Candidates followed from night to night: one object gathers its nights,
a miss deep enough to have shown it counts, explained ones and long-missing
ones close, and an artefact of one night never becomes an object."""
import pytest

import candidates
import config


@pytest.fixture
def book(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    return candidates.load("M31")


def found(ra=11.10554, dec=41.57670, verdict="unexplained: worth a person's eyes", mag=18.2, score=5.4):
    return {"ra": ra, "dec": dec, "verdict": verdict, "mag": mag, "score": score}


def test_a_detection_at_the_same_place_joins_the_candidate_on_file(book):
    candidates.add_night(book, "20261014", [found()])
    candidates.add_night(book, "20261020", [found(ra=11.10554 + 2 / 3600, mag=17.9)])
    (k,) = book["candidates"]
    assert candidates.nights_seen(k) == 2 and candidates.k_peak(k) == 17.9 and k["open"]
    candidates.add_night(book, "20261021", [found(ra=11.2)])
    assert len(book["candidates"]) == 2


def test_an_artefact_of_one_night_is_not_kept(book):
    candidates.add_night(book, "20261014", [found(verdict="not in both halves of the night: an artefact")])
    assert book["candidates"] == []


def test_an_explained_candidate_is_closed(book):
    candidates.add_night(book, "20261014", [found(verdict="known asteroid 2006 WP197")])
    (k,) = book["candidates"]
    assert not k["open"] and k["closed_because"] == "known asteroid 2006 WP197"


def test_nights_without_it_are_measured_and_enough_deep_misses_close_it(book):
    candidates.add_night(book, "20261014", [found()])
    shallow = lambda ra, dec: (None, None, 17.5)      # could not have shown an 18.2
    deep = lambda ra, dec: (None, None, 18.6)
    candidates.follow_up(book, "20261015", shallow, None)
    for night in ("20261016", "20261017"):
        candidates.follow_up(book, night, deep, None)
    (k,) = book["candidates"]
    assert k["open"] and [n["seen"] for n in k["nights"]] == [True, False, False, False]
    candidates.follow_up(book, "20261018", deep, None)
    assert not k["open"] and "3 nights" in k["closed_because"]


def test_seen_again_by_measuring_its_place_keeps_it_open(book):
    candidates.add_night(book, "20261014", [found()])
    candidates.follow_up(book, "20261020", lambda ra, dec: (18.0, 0.2, 18.6), None)
    (k,) = book["candidates"]
    assert candidates.nights_seen(k) == 2 and k["nights"][-1]["forced"]


def test_the_book_is_kept_between_runs(book):
    candidates.add_night(book, "20261014", [found()])
    candidates.save(book)
    assert candidates.load("M31")["candidates"][0]["first"] == "20261014"
