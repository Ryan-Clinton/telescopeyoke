"""A report packet: assembled from what is on file, with every figure's
kind, the last non-detection, and what is still wanting before anyone
sends it. Nothing is sent, and nothing here touches the network."""
import pytest

import report


def candidate(nights):
    return {"id": "M31-20261020-221500-001", "ra": 11.105545, "dec": 41.576699, "open": True, "nights": nights}


SEEN = {"night": "20261020-221500", "seen": True, "score": 9.0, "mag": 17.2, "verdict": "unexplained"}
RECORDS = {
    "depth": {"fwhm_arcsec": 6.0, "scale_arcsec_per_px": 1.32, "limit_5sigma": {"sky": 17.8}},
    "candidates": {"alignment_residual_px": 0.18, "reference": "ref.fits", "new": "new.fits"},
    "vetted": {"candidates": [{"ra": 11.105545, "dec": 41.576699, "halves": [6.1, 6.6], "asteroid": None,
                               "variable": None, "reported": None, "gaia": None, "in_reference": None,
                               "verdict": "unexplained: worth a person's eyes"}]},
}


def test_the_packet_has_what_a_report_asks_for():
    earlier = {"night": "20261018-221000", "seen": False, "limit": 18.1}
    p = report.assemble("M31", candidate([earlier, SEEN, dict(SEEN, night="20261021-220000", mag=17.0)]),
                        None, RECORDS, "2026-10-20T22:40:12")
    assert (p["ra_hms"], p["dec_dms"]) == ("00:44:25.33", "+41:34:36.1")
    assert p["position_error_arcsec"] == pytest.approx(0.7, abs=0.05)
    assert p["mag"] == 17.2 and p["limit_5sigma"] == 17.8 and p["discovered_utc"] == "2026-10-20T22:40:12"
    assert p["last_non_detection"] == {"night": "20261018-221000", "limit": 18.1}
    assert p["nights_seen"] == 2 and p["kinds"]["checks"] == "reported" and p["kinds"]["mag"] == "measured"
    # Nothing wanting but the search a person must make themselves.
    assert p["not_yet"] == ["the Transient Name Server not searched here (it needs an account): search it by hand first"]
    text = report.text(p)
    assert "NOT YET SENT" in text and "Last non-detection 20261018-221000: fainter than 18.1" in text


def test_a_one_night_candidate_at_the_limit_says_what_is_still_wanting():
    faint = dict(SEEN, mag=18.2, score=5.4)
    p = report.assemble("M31", candidate([faint]), None, dict(RECORDS, vetted={"candidates": []}), None)
    wanting = " ".join(p["not_yet"])
    assert "one night only" in wanting and "no earlier measurement" in wanting
    assert "not shown in both halves" in wanting and "fainter than that night's 5-sigma limit" in wanting


def test_an_earlier_stack_without_it_is_the_last_non_detection():
    earlier = [{"session": "20261013-232632", "in_picture": True, "mag": None, "limit": 18.0},
               {"session": "20261014-020539", "in_picture": True, "mag": None, "limit": 16.5},
               {"session": "20261099", "in_picture": True, "mag": None, "limit": 18.3}]
    p = report.assemble("M31", candidate([dict(SEEN, night="20261014-021118")]), None, RECORDS, None, earlier)
    assert p["last_non_detection"] == {"night": "20261014-020539", "limit": 16.5}


def test_sexagesimal_positions():
    assert report.hms(11.105545 / 15) == "00:44:25.33"
    assert report.dms(-0.5) == "-00:30:00.0"


def test_a_panels_candidate_is_looked_for_in_the_panels_book():
    assert report.field_of("M31-20261014-021118-001") == "M31"
    assert report.field_of("M31-P3-20261020-213000-002") == "M31-P3"
