"""Vetting candidates: the catalogues' answers are read, each candidate is
matched to what is known at its place, and the verdict follows the
evidence. The answers here are copied from the services as they replied on
16 October 2026; nothing touches the network."""
import pytest

import vet

SKYBOT = """# Flag: 1
# Ticket: 187924698000603808
# Num | Name | RA(h) | DE(deg) | Class | Mv | Err(arcsec) | d(arcsec) | dRA(arcsec/h) | dDEC(arcsec/h) | Dg(ua) | Dh(ua)
 - | 2015 UZ106 | 00 43 19.6079 | +41 15 1.911 | Hungaria | 20.9 | 0.063 | 416.470 | -35.3172 | -16.958 | 0.937 | 1.850
 368945 | 2006 WP197 | 00 43 10.9308 | +41 31 22.358 | Hungaria | 19.6 | 0.021 | 962.356 | -40.5749 | -7.320 | 0.817 | 1.736
"""


def test_skybots_answer_is_read_with_each_bodys_motion():
    rows = vet.read_skybot(SKYBOT)
    assert [r["name"] for r in rows] == ["2015 UZ106", "2006 WP197"]
    assert rows[0]["ra"] == pytest.approx(15 * (43 / 60 + 19.6079 / 3600), abs=1e-6)
    assert rows[0]["dec"] == pytest.approx(41 + 15 / 60 + 1.911 / 3600, abs=1e-6)
    assert rows[0]["v"] == 20.9 and rows[0]["motion"] == pytest.approx(39.2, abs=0.1)


def test_a_designation_gives_its_position():
    found = vet.read_designations("(= PSP26E) (= PNV J00425223+4101447) (= M31N 2026-01c)")
    (name, ra, dec), = found
    assert name == "J00425223+4101447"
    assert ra == pytest.approx(15 * (42 / 60 + 52.23 / 3600), abs=1e-6)
    assert dec == pytest.approx(41 + 1 / 60 + 44.7 / 3600, abs=1e-6)
    assert vet.read_designations("TCP J18035290-3127298")[0][2] < 0


def candidate(**extra):
    return dict({"x": 100, "y": 200, "ra": 10.7, "dec": 41.3, "score": 9.0, "as_strong_fading": 0, "mag": 17.4},
                **extra)


def test_a_candidate_on_a_known_asteroid_is_that_asteroid():
    rows = [{"name": "2006 WP197", "ra": 10.7 + 20 / 3600 / 0.75, "dec": 41.3, "v": 17.5, "motion": 41.2}]
    (e,) = vet.vet({"candidates": [candidate()]}, {"asteroids": rows})
    assert e["asteroid"]["name"] == "2006 WP197" and e["verdict"] == "known asteroid 2006 WP197"
    assert e["kinds"]["asteroid"] == "reported" and e["kinds"]["score"] == "measured"


def test_the_verdict_follows_the_strongest_evidence():
    nothing = {"asteroids": [], "variables": [], "reported": [], "gaia": []}
    (fine,) = vet.vet({"candidates": [candidate()]}, nothing, half_scores=[[6.1, 6.4]])
    assert fine["verdict"] == "unexplained: worth a person's eyes"
    (brief,) = vet.vet({"candidates": [candidate()]}, nothing, half_scores=[[8.9, 0.4]])
    assert brief["verdict"] == "in one half of the night only"
    # A Gaia star beside it is a clue, not an explanation: a transient can
    # sit next to a catalogued star.
    star = dict(nothing, gaia=[{"ra": 10.7, "dec": 41.3 + 0.5 / 3600, "g": 18.2}])
    (beside,) = vet.vet({"candidates": [candidate()]}, star, half_scores=[[6.0, 6.0]])
    assert beside["verdict"] == "unexplained: worth a person's eyes"
    assert beside["clues"] and "Gaia star G 18.2 0.5\" away" in beside["clues"][0]
    listed = dict(nothing, reported=[{"name": "J00424800+4118000", "ra": 10.7, "dec": 41.3}])
    (old,) = vet.vet({"candidates": [candidate()]}, listed, half_scores=[[6.0, 6.0]])
    assert old["verdict"] == "already reported: J00424800+4118000"


def test_a_check_not_made_is_said_to_be_unknown_not_clear():
    (e,) = vet.vet({"candidates": [candidate()]}, {})
    assert e["kinds"]["asteroid"] == "not known" and "asteroid" not in e
    assert e["verdict"] == "unexplained: worth a person's eyes"
    assert e["clues"] == ["the halves of the night were not checked"]


def test_distances_on_the_sky():
    assert vet.separation(10.0, 41.0, 10.0, 41.0 + 1 / 3600) == pytest.approx(1.0, abs=1e-6)
    assert vet.separation(10.0, 60.0, 10.0 + 2 / 3600, 60.0) == pytest.approx(1.0, abs=1e-3)
