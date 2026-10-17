"""Watching Tabby's star: each night's brightness is kept, a usual level is
trusted only after a few nights, and a night clearly fainter than usual is
called a dip while an ordinary one is not. Nothing moves, nothing touches
the network."""
import numpy as np
import pytest

import config
import starwatch

TABBY = starwatch.STARS["tabby"]


def night(mag, session, scatter=0.005, seed=0):
    rng = np.random.default_rng(seed)
    batches = mag + rng.normal(0, scatter, 4)
    stars = np.array([[TABBY["ra"] + 0.01, TABBY["dec"], 12.5, 0.8], [TABBY["ra"], TABBY["dec"], 11.6, 0.9]])
    return {"jd": [2461330.5 + k / 100 for k in range(4)], "stars": stars,
            "mags": np.column_stack([np.full(4, 12.5), batches])}


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    return tmp_path


def measured(data, mag, name, seed=0):
    session = data / "frames" / "Tabby" / name
    session.mkdir(parents=True, exist_ok=True)
    return starwatch.measure("tabby", session, say=lambda *_: None, night=night(mag, name, seed=seed))


def test_a_usual_level_waits_for_enough_nights(data):
    first = measured(data, 11.60, "20261018-193000")
    assert first["baseline"] is None and not first["dipping"] and first["night"]["mag"] == pytest.approx(11.60, abs=0.01)


def test_a_clearly_fainter_night_is_a_dip_and_an_ordinary_one_is_not(data):
    for k, name in enumerate(("20261018-193000", "20261019-193000", "20261020-193000")):
        measured(data, 11.60 + 0.004 * k, name, seed=k)
    ordinary = measured(data, 11.61, "20261021-193000", seed=5)
    assert ordinary["baseline"] == pytest.approx(11.604, abs=0.005) and not ordinary["dipping"]
    dip = measured(data, 11.70, "20261022-193000", seed=6)                 # 9% fainter
    assert dip["dipping"] and dip["dimmer"] == pytest.approx(0.096, abs=0.01)
    again = measured(data, 11.70, "20261022-193000", seed=6)               # measured again: replaced, not added
    assert again["nights_measured"] == 5


def test_following_the_star_runs_the_patrol_on_it_and_a_plan_measures_nothing(data):
    import mount
    asked = []
    answer = starwatch.look("tabby", plan=True, say=lambda *_: None, patrol_run=lambda a: asked.append(a) or {"p": 1})
    assert asked[0].programme == "Tabby" and asked[0].minutes == starwatch.MINUTES and answer["patrol"] == {"p": 1}
    target = mount.find_target("tabby")
    assert (target["ra"], target["dec"]) == (TABBY["ra"], TABBY["dec"])


def test_an_unknown_star_is_refused():
    with pytest.raises(starwatch.interface.Refusal):
        starwatch.star("vega")
