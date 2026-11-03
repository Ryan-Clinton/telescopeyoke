"""Dips in Kepler light curves: a deep lopsided dip is found and kept, an
eclipse that repeats is called periodic, one at a gap is an edge, a short
one on a momentum dump is the spacecraft's, and a star's own wobble is
its variability. Nothing here touches the network."""
import io

import numpy as np
import pytest

import archive
import config

STEP = 30 / 1440          # Kepler's long cadence, in days


def curve(days=90.0, noise=0.0003, seed=1):
    rng = np.random.default_rng(seed)
    t = np.arange(0, days, STEP)
    return t, 1 + rng.normal(0, noise, len(t)), np.zeros(len(t), int), np.ones(len(t), int)


def dip(t, f, middle, depth, fall, rise):
    """A dip falling over `fall` days to `depth`, recovering over `rise`."""
    shape = np.where(t <= middle, np.clip(1 - (middle - t) / fall, 0, 1), np.clip(1 - (t - middle) / rise, 0, 1))
    return f - depth * shape


def test_a_deep_lopsided_dip_is_found_with_its_shape():
    t, f, q, quarter = curve()
    f = dip(t, f, 40.0, 0.10, fall=0.5, rise=2.0)
    found, scatter = archive.find_dips(t, f, q, quarter)
    assert len(found) == 1 and found[0]["verdict"] == "dip"
    d = found[0]
    assert d["middle"] == pytest.approx(40.0, abs=STEP) and d["depth_percent"] == pytest.approx(10, abs=0.3)
    assert d["asymmetry"] > 0.4                      # the recovery is the slower
    assert scatter == pytest.approx(0.0003, rel=0.1)
    assert archive.score(found) > 10


def test_an_eclipse_that_repeats_is_periodic_not_a_dipper():
    t, f, q, quarter = curve()
    for middle in np.arange(5.0, 90.0, 7.3):
        f = dip(t, f, middle, 0.03, fall=0.06, rise=0.06)
    found, _ = archive.find_dips(t, f, q, quarter)
    assert len(found) >= 3 and {d["verdict"] for d in found} == {"periodic"}
    assert found[0]["period_days"] == pytest.approx(7.3, abs=0.05)
    assert archive.score(found) == 0


def test_a_dip_at_a_gap_is_an_edge():
    t, f, q, quarter = curve()
    f = dip(t, f, 49.9, 0.05, fall=0.3, rise=0.3)
    keep = (t < 50.0) | (t > 52.0)                   # the data stop at the dip's faintest
    found, _ = archive.find_dips(t[keep], f[keep], q[keep], quarter[keep])
    assert [d["verdict"] for d in found] == ["edge"]


def test_a_short_dip_on_a_momentum_dump_is_the_spacecraft():
    t, f, q, quarter = curve()
    f = dip(t, f, 30.0, 0.02, fall=0.15, rise=0.15)  # seven hours: short enough to be the spacecraft's
    q[np.argmin(np.abs(t - 30.0)) + 1] = 32          # a reaction-wheel desaturation beside its faintest
    found, _ = archive.find_dips(t, f, q, quarter)
    assert [d["verdict"] for d in found] == ["spacecraft"]


def test_a_stars_own_wobble_is_not_taken_for_dips():
    t, f, q, quarter = curve()
    f = f - 0.03 * np.sin(2 * np.pi * t / 3.17) * (1 + 0.3 * np.sin(t / 7))    # a spotted star turning
    found, _ = archive.find_dips(t, f, q, quarter)
    assert not [d for d in found if d["verdict"] == "dip"]     # its scatter is its wobble


def test_dips_over_much_of_the_curve_are_the_stars_variability():
    t, f, q, quarter = curve()
    rng = np.random.default_rng(2)
    for middle in rng.uniform(2, 88, 40):                       # forty dips of varied depth: a restless star
        f = dip(t, f, middle, rng.uniform(0.02, 0.06), fall=0.1, rise=0.1)
    found, _ = archive.find_dips(t, f, q, quarter)
    assert found and not [d for d in found if d["verdict"] == "dip"]
    assert "variability" in {d["verdict"] for d in found}


def test_a_slow_fade_survives_joining_the_quarters_at_their_edges():
    t = np.arange(0, 4 * 365.25, STEP)
    quarter = (t // 91).astype(int)
    star = 1 - 0.0075 * t / 365.25                          # 3% fainter over four years
    scale = np.array([1.0, 0.93, 1.08, 0.97] * 5)[quarter]  # a different CCD after each roll
    gaps = (t % 91) > 1.0                                   # a day lost at each roll
    found = archive.trend(t[gaps], (1000 * star * scale)[gaps], quarter[gaps])
    assert found["percent_per_year"] == pytest.approx(-0.75, abs=0.05)
    assert found["change_percent"] == pytest.approx(-3.0, abs=0.2)
    assert archive.trend(t[:50], np.ones(50), quarter[:50]) is None


def test_a_dip_only_the_cleaning_shows_is_said_to_be_pdcsap_only():
    t, f, q, quarter = curve()
    f = dip(t, f, 40.0, 0.10, fall=0.5, rise=2.0)
    f = dip(t, f, 70.0, 0.04, fall=0.3, rise=0.3)
    sap = dip(t, curve(seed=3)[1], 40.0, 0.10, fall=0.5, rise=2.0)      # SAP has the first only...
    sap = dip(t, sap, 20.0, 0.05, fall=0.3, rise=0.3)                  # ...and one the cleaning took out
    dips, _ = archive.find_dips(t, f, q, quarter)
    sap_dips, _ = archive.find_dips(t, sap, q, quarter)
    alone = archive.seen_in_sap(dips, {"t": t, "sap": sap, "quarter": quarter}, sap_dips)
    assert [(round(d["middle"]), d["seen_in"]) for d in dips] == [(40, "both"), (70, "PDCSAP only")]
    assert [(round(d["middle"]), d["seen_in"]) for d in alone] == [(20, "SAP only")]


def test_stars_are_named_as_people_write_them():
    assert archive.kic_number(["KIC", "8462852"]) == archive.kic_number("KIC8462852") == 8462852
    assert archive.kic_number("Tabby") == 8462852
    assert archive.stars("8462852, 7106205") == [8462852, 7106205]
    with pytest.raises(archive.interface.Refusal):
        archive.kic_number("M31")


def fits_bytes(quarter, t, flux, flags):
    from astropy.io import fits
    columns = [fits.Column(name="TIME", format="D", array=t), fits.Column(name="PDCSAP_FLUX", format="E", array=flux),
               fits.Column(name="SAP_QUALITY", format="J", array=flags)]
    primary = fits.PrimaryHDU()
    primary.header["QUARTER"] = quarter
    out = io.BytesIO()
    fits.HDUList([primary, fits.BinTableHDU.from_columns(columns)]).writeto(out)
    return out.getvalue()


class Reply:
    def __init__(self, text="", content=b"", status_code=200):
        self.text, self.content, self.status_code = text, content, status_code

    def raise_for_status(self):
        pass


def test_a_stars_quarters_are_fetched_once_kept_and_each_put_on_its_own_level(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    asked = []
    t = np.arange(0, 10, STEP)
    one = fits_bytes(1, t, np.full(len(t), 2000.0), np.zeros(len(t), int))
    flags = np.zeros(len(t), int)
    flags[5] = 128
    two = fits_bytes(2, t + 20, np.full(len(t), 500.0), flags)

    def get(url, timeout=None):
        asked.append(url)
        if url.endswith("/"):
            return Reply('<a href="kplr001234567-2009131105131_llc.fits">a</a>'
                         '<a href="kplr001234567-2009166043257_llc.fits">b</a>')
        return Reply(content=one if "2009131" in url else two)
    paths = archive.fetch(1234567, get, say=lambda *_: None)
    assert len(paths) == 2 and asked[0].endswith("/0012/001234567/")
    assert archive.fetch(1234567, get=None, say=lambda *_: None) == paths       # kept: no second fetch
    lc = archive.read(paths)
    assert np.nanmedian(lc["f"][lc["quarter"] == 1]) == 1.0 and np.nanmedian(lc["f"][lc["quarter"] == 2]) == 1.0
    assert np.isnan(lc["f"][len(t) + 5])                                         # a flagged point is not used


def test_a_search_puts_the_most_tabby_like_first_and_says_what_it_could_not_have(monkeypatch):
    def analyse(kic, get=None, say=None):
        if kic == 3:
            raise archive.interface.Refusal("INVALID_REQUEST", "Kepler has no light curves of KIC 3.")
        depth = {1: 2.0, 2: 15.0}[kic]
        d = {"middle": 1.0, "depth_percent": depth, "asymmetry": 0.5, "verdict": "dip"}
        return {"star": f"KIC {kic}", "kic": kic, "quarters": 17, "points": 60000, "scatter_percent": 0.03,
                "dips": [d], "real_dips": 1, "deepest_percent": depth, "tabby_like": depth >= 5,
                "score": archive.score([d]), "source": "x"}
    monkeypatch.setattr(archive, "analyse", analyse)
    answer = archive.search([1, 2, 3], say=lambda *_: None)
    assert [s["kic"] for s in answer["stars"]] == [2, 1] and answer["stars"][0]["tabby_like"]
    assert answer["missed"] == [{"kic": 3, "why": "Kepler has no light curves of KIC 3."}]
