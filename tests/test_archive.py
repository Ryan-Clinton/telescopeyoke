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


def test_two_dips_alike_and_symmetric_are_a_possible_repeated_eclipse():
    t, f, q, quarter = curve()
    f = dip(t, f, 20.0, 0.013, fall=0.25, rise=0.25)
    f = dip(t, f, 75.1, 0.013, fall=0.25, rise=0.25)
    f = dip(t, f, 50.0, 0.08, fall=0.3, rise=1.5)          # and one like neither: a Tabby dip stays
    found, _ = archive.find_dips(t, f, q, quarter)
    verdicts = {round(d["middle"]): d["verdict"] for d in found}
    assert verdicts == {20: archive.REPEAT, 75: archive.REPEAT, 50: "dip"}
    assert [d["separation_days"] for d in found if d["verdict"] == archive.REPEAT] == [pytest.approx(55.1, abs=0.03)] * 2


PAGE = """<p>Showing 1 to 50 of 52 results</p><table><tr class="odd">
								<td><a href="/overview/?k={kic}">{kic}</a></td>

								<td>{period}</td>
								<td>0.0000001</td>
								<td>54964.696236</td>
								<td>0.013589</td>
								<td>{morph}</td>
								<td>78.7688</td></tr></table>"""


def test_the_binary_catalogue_is_read_from_its_own_table_and_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    asked = []

    def get(url, timeout=None):
        asked.append(url)
        page = int(url.rsplit("=", 1)[1])
        return Reply(text=PAGE.format(kic=9221398 if page == 1 else 8129189,
                                      period="13.7875200" if page == 1 else "53.6470815", morph="0.04"))
    listed = archive.villanova(get)
    assert listed == {9221398: {"period": 13.78752, "morph": 0.04}, 8129189: {"period": 53.6470815, "morph": 0.04}}
    assert asked == ["https://keplerebs.villanova.edu/?page=1", "https://keplerebs.villanova.edu/?page=2"]
    assert archive.villanova(get=None) == listed                            # kept


def test_a_possible_repeat_is_a_known_binary_only_when_a_catalogue_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(archive, "villanova", lambda get=None: {9221398: {"period": 13.78752, "morph": 0.04}})
    answer = {"real_dips": 0, "possible_repeats": 2}
    known = archive.checked(answer, 9221398, (290.0, 45.0), variables=lambda ra, dec, r: [])
    assert known["known_binary"] == "Villanova Kepler EB catalogue, period 13.7875 d"
    by_vsx = archive.checked(answer, 1, (290.0, 45.0), variables=lambda ra, dec, r: [
        {"name": "V2083 Cyg", "type": "EA/DM", "ra": 290.0, "dec": 45.0}])
    assert by_vsx["known_binary"] == "VSX V2083 Cyg, type EA/DM"
    lead = archive.checked(answer, 1, (290.0, 45.0), variables=lambda ra, dec, r: [
        {"name": "V1 Cyg", "type": "ROT", "ra": 290.0, "dec": 45.0}])
    assert lead["known_binary"] is None and lead["catalogues"]["vsx"] == [{"name": "V1 Cyg", "type": "ROT"}]
    quiet = archive.checked({"real_dips": 0, "possible_repeats": 0}, 1, None, variables=None)
    assert quiet["catalogues"] is None                                       # nothing to check: nothing asked


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


def test_the_screen_goes_on_where_it_stopped_and_ranks_everything_screened(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)

    class Listed:
        text = "kepid,kepmag\n11,9.0\n22,9.5\n11,9.6\n33,10.0\n44,11.0\n"

        def raise_for_status(self):
            pass
    lists = []

    def get(url, params=None, timeout=None):
        lists.append(params["query"])
        return Listed()

    def analyse(kic, get=None, say=None):
        (archive.store(kic)).mkdir(parents=True, exist_ok=True)
        if kic == 33:
            raise archive.interface.Refusal("INVALID_REQUEST", "Kepler has no light curves of KIC 33.")
        deep = kic == 22
        return {"score": 30.0 if deep else 1.0, "tabby_like": deep, "real_dips": 1, "deepest_percent": 15.0 if deep else 1.2,
                "scatter_percent": 0.03, "sap_only": []}
    first = archive.screen(2, get=get, say=lambda *_: None, analyse_star=analyse)
    assert first["this_run"] == 2 and first["screened"] == 2 and [r["kic"] for r in first["top"]] == [22, 11]
    assert archive.store(22).exists() and not archive.store(11).exists()     # only a Tabby-like star's files kept
    second = archive.screen(5, get=get, say=lambda *_: None, analyse_star=analyse)
    assert second["this_run"] == 2 and second["screened"] == 4                 # 33 and 44; 11 once only
    assert archive.screened()["33"] == {"missed": "Kepler has no light curves of KIC 33."}
    assert [r["kic"] for r in second["top"]] == [22, 11, 44] and len(lists) == 1   # the list fetched once


# The benchmark on real Kepler light curves, where a copy of them is kept
# (TY_KEPLER_CACHE: a cache/kepler folder that `archive.py dips` filled).
# Binaries from the Villanova Kepler EB catalogue (keplerebs.villanova.edu),
# their periods and eclipse depths as it gives them; quiet stars from the
# first search near Tabby's star. docs/archive.md has the figures.
BINARIES = {8129189: 53.6470815, 10274244: 13.6836897, 5795648: 4.5533695}
TOO_SHALLOW = (7684873, 5990753)      # eclipses 0.04% and 0.00% deep: under the 1% floor
QUIET = (7849605, 7850078, 7917803)


def kept(kic):
    import os
    from pathlib import Path
    root = os.environ.get("TY_KEPLER_CACHE")
    paths = sorted((Path(root) / f"{kic:09d}").glob("*_llc.fits")) if root else []
    if not paths:
        pytest.skip(f"no kept Kepler light curves of KIC {kic} (set TY_KEPLER_CACHE)")
    lc = archive.read(paths)
    dips, scatter = archive.find_dips(lc["t"], lc["f"], lc["q"], lc["quarter"])
    return dips, scatter


def test_the_real_benchmark_tabbys_dips_are_found():
    dips, scatter = kept(8462852)
    left = {round(d["middle"]): d["depth_percent"] for d in dips if d["verdict"] == "dip"}
    assert left[793] == pytest.approx(14.3, abs=1.0) and left[1520] == pytest.approx(20.7, abs=1.0)   # D792, D1519
    assert set(left) == {793, 1520, 1540, 1568} and scatter <= archive.QUIET


@pytest.mark.parametrize("kic", sorted(BINARIES))
def test_the_real_benchmark_binaries_are_periodic(kic):
    dips, _ = kept(kic)
    periodic = [d for d in dips if d["verdict"] == "periodic"]
    assert periodic and not [d for d in dips if d["verdict"] == "dip"]
    assert any(abs(d["period_days"] / BINARIES[kic] - round(d["period_days"] / BINARIES[kic])) < 0.01 for d in periodic)


@pytest.mark.parametrize("kic", TOO_SHALLOW + QUIET)
def test_the_real_benchmark_quiet_stars_give_nothing(kic):
    dips, _ = kept(kic)
    assert not [d for d in dips if d["verdict"] == "dip"]


def test_a_tess_sector_is_read_and_binned_to_keplers_cadence(tmp_path):
    from astropy.io import fits
    t = 1730.0 + np.arange(0, 2, 2 / 1440)                         # two days of 2-minute points
    flux = np.full(len(t), 5000.0)
    flags = np.zeros(len(t), int)
    flags[:29] = 32                                                # a momentum dump over the first bin and most of the next
    columns = [fits.Column(name="TIME", format="D", array=t), fits.Column(name="PDCSAP_FLUX", format="E", array=flux),
               fits.Column(name="SAP_FLUX", format="E", array=flux * 1.1), fits.Column(name="QUALITY", format="J", array=flags)]
    primary = fits.PrimaryHDU()
    primary.header["SECTOR"] = 15
    path = tmp_path / "tess-s0015_lc.fits"
    fits.HDUList([primary, fits.BinTableHDU.from_columns(columns)]).writeto(path)
    curve = archive.binned(archive.read([path]))
    assert len(curve["t"]) == 96 and set(curve["quarter"].tolist()) == {15}        # 30-minute bins
    assert np.isnan(curve["f"][0]) and curve["q"][0] == 32 and curve["f"][2] == 1.0 and curve["q"][2] == 0
    assert archive.calendar(1730.21, archive.BTJD) == "2019-09-03"


def test_tess_stars_are_named_as_people_write_them():
    assert archive.tic_number("TIC 185336364") == archive.tic_number("Tabby") == 185336364
    with pytest.raises(archive.interface.Refusal):
        archive.tic_number("Vega")


def test_the_real_benchmark_tess_finds_the_2019_transit_of_tabbys_star():
    """Madurga-Favieres et al. (MNRAS 550, stag1273, 2026): one symmetric
    1.1% transit about 21 hours long in TESS sector 15."""
    import os
    from pathlib import Path
    root = os.environ.get("TY_TESS_CACHE")
    paths = sorted((Path(root) / "185336364").glob("*_lc.fits")) if root else []
    if not paths:
        pytest.skip("no kept TESS light curves of TIC 185336364 (set TY_TESS_CACHE)")
    curve = archive.binned(archive.read(paths))
    dips, _ = archive.find_dips(curve["t"], curve["f"], curve["q"], curve["quarter"], archive.BTJD)
    left = [d for d in dips if d["verdict"] == "dip"]
    assert [d["date"] for d in left] == ["2019-09-03"]
    assert left[0]["depth_percent"] == pytest.approx(1.2, abs=0.2) and abs(left[0]["asymmetry"]) < 0.3


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
