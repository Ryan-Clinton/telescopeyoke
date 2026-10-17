"""Exoplanet transits: tonight's list keeps a transit that is whole in the
dark and leaves out one that is not, and a night's light curve gives back
the depth and the timing put into it. Nothing here touches the network."""
import datetime

import numpy as np
import pytest
from astropy.time import Time

import config
import transits

NOW = datetime.datetime(2026, 10, 16, 18, 0, tzinfo=datetime.timezone.utc)
MIDNIGHT = Time("2026-10-17T00:00:00").jd


def planet(name="TEST-1 b", ra=15.0, dec=50.0, middle=MIDNIGHT, period=3.0, hours=2.5, depth=1.5, v=11.0):
    return {"planet": name, "star": name[:-2], "ra": ra, "dec": dec, "v": v, "period": period,
            "epoch": middle - 100 * period, "hours": hours, "depth": depth}


def test_the_transits_between_two_times_follow_the_period():
    p = planet(period=2.0)
    assert transits_close(transits.transits_between(p, MIDNIGHT - 3, MIDNIGHT + 3), [MIDNIGHT - 2, MIDNIGHT, MIDNIGHT + 2])


def transits_close(a, b):
    return len(a) == len(b) and np.allclose(a, b, atol=1e-6)


def test_tonight_keeps_a_whole_transit_in_the_dark_and_leaves_out_the_rest():
    rows = [planet(),                                                     # overhead at midnight
            planet("DAY-1 b", middle=MIDNIGHT + 0.5),                     # at noon
            planet("SHALLOW-1 b", depth=0.4),
            planet("FAINT-1 b", v=14.5)]
    answer = transits.tonight(config.example(), rows, now=NOW, say=lambda *_: None)
    assert [t["planet"] for t in answer["transits"]] == ["TEST-1 b"]
    t = answer["transits"][0]
    assert t["middle"] == pytest.approx(MIDNIGHT, abs=1e-4) and t["altitude"] > 40 and t["exposure"] == 4   # V 11
    assert answer["bright_and_deep"] == 2


def light_curve(depth=1.5, late_min=10.0, hours=2.5, scatter=0.003, seed=1):
    rng = np.random.default_rng(seed)
    jd = MIDNIGHT + np.arange(-3, 3, 0.1) / 24
    inside = np.abs(jd - (MIDNIGHT + late_min / 1440)) <= hours / 48
    mag = 11.0 - 2.5 * np.log10(np.where(inside, 1 - depth / 100, 1.0)) + rng.normal(0, scatter, len(jd))
    return jd, mag


def test_the_fit_gives_back_the_depth_and_how_late_it_came():
    jd, mag = light_curve()
    result = transits.fit(jd, mag, MIDNIGHT, 2.5)
    assert result["depth"] == pytest.approx(1.5, abs=0.2) and result["early_late_min"] == pytest.approx(10, abs=4)
    assert 1 < result["scatter_mmag"] < 4                              # 3 mmag put in


def test_a_nights_star_is_found_among_the_stars_measured_and_its_transit_fitted(tmp_path):
    jd, mag = light_curve(late_min=-6)
    p = planet()
    others = np.full((len(jd), 1), 12.0)
    night = {"jd": list(jd), "stars": np.array([[p["ra"] + 0.01, p["dec"], 12.0, 0.8], [p["ra"], p["dec"], 11.0, 0.9]]),
             "mags": np.column_stack([others, mag])}
    session = tmp_path / "TEST-1" / "20261016-220000"
    session.mkdir(parents=True)
    answer = transits.measure(session, "test-1 b", say=lambda *_: None, rows=[p], night=night)
    assert answer["fit"]["early_late_min"] == pytest.approx(-6, abs=4) and answer["expected_depth"] == 1.5
    assert (session / "transit-TEST-1b.json").exists()


def test_a_star_not_in_the_picture_is_refused(tmp_path):
    p = planet()
    night = {"jd": [MIDNIGHT], "stars": np.array([[p["ra"] + 1, p["dec"], 12.0, 0.8]]), "mags": np.array([[12.0]])}
    with pytest.raises(transits.interface.Refusal):
        transits.measure(tmp_path, "TEST-1 b", say=lambda *_: None, rows=[p], night=night)
