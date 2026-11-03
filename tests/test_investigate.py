"""The research director: a lead taken without being told which, every
check's answer kept with its source, the verdict by fixed rules, and the
dashboard counting each survey and lead. Nothing touches the network."""
import json
from datetime import date

import pytest

import config
import interface
import investigate
from test_interface import valid


class Reply:
    def __init__(self, text="", body=None):
        self.text, self.body = text, body

    def json(self):
        return self.body

    def raise_for_status(self):
        pass


def dip(depth, seen="both", asym=0.4):
    return {"verdict": "dip", "depth_percent": depth, "hours": 30.0, "asymmetry": asym, "seen_in": seen,
            "date": "2011-03-05"}


def star(dips, tabby_like=True, crowd=0.99, mag=11.9):
    return {"star": "KIC 1234567", "kic": 1234567, "ra": 290.0, "dec": 44.0, "mag": mag, "mag_band": "Kepler",
            "crowdsap": crowd, "dips": dips, "real_dips": sum(d["verdict"] == "dip" for d in dips),
            "deepest_percent": max([d["depth_percent"] for d in dips], default=0.0), "tabby_like": tabby_like,
            "scatter_percent": 0.05, "source": "https://archive.stsci.edu/x", "trend": {"sap": None}}


def checks(simbad=None, vsx=None, eb=None, gaia=None, errors=()):
    def c(name, answer):
        return investigate._asked(name, "https://x", answer, error="not answered (Timeout)" if name in errors else None)
    return {"simbad": c("SIMBAD", simbad), "vsx": c("VSX (via VizieR)", vsx), "villanova": c("Villanova", eb),
            "gaia": c("Gaia DR3", gaia or {"star": {"g": 12.0, "ruwe": 1.0, "source_id": "1", "separation_arcsec": 0.1},
                                          "class": None, "neighbours": []}),
            "ztf": c("ZTF", {"points": 0}), "other_mission": c("TESS", None)}


def test_a_catalogue_that_accounts_for_the_dips_explains_them():
    v = investigate.judge(star([dip(8.0), dip(7.5)]), checks(eb={"period_days": 13.68, "primary_depth": 0.08}))
    assert v["verdict"] == "explained" and "period 13.68 days" in v["explained_by"][0]
    v = investigate.judge(star([dip(8.0)]), checks(gaia={"star": {"g": 12.0, "ruwe": 2.1}, "neighbours": [],
                                                          "class": {"name": "YSO", "score": 0.8}}))
    assert v["verdict"] == "explained" and "young star" in v["explained_by"][0]
    assert any("RUWE 2.10" in n for n in v["notes"])


def test_a_neighbour_bright_enough_to_make_the_dip_or_one_flux_only_makes_it_an_artefact():
    near = {"star": {"g": 12.0, "ruwe": 1.0}, "class": None,
            "neighbours": [{"g": 13.0, "separation_arcsec": 4.2, "ruwe": 1.0, "source_id": "2"}]}
    v = investigate.judge(star([dip(8.0), dip(9.0)]), checks(gaia=near))     # G 13 next to G 12: up to 28%
    assert v["verdict"] == "artefact" and "G 13.0 at 4.2\"" in v["artefact_because"][0]
    faint = dict(near, neighbours=[dict(near["neighbours"][0], g=17.0)])     # G 17: up to 1%, not 8%
    assert investigate.judge(star([dip(8.0), dip(9.0)]), checks(gaia=faint))["verdict"] != "artefact"
    v = investigate.judge(star([dip(8.0, "PDCSAP only")]), checks())
    assert v["verdict"] == "artefact" and "PDCSAP" in v["artefact_because"][0]
    v = investigate.judge(star([dip(3.0)], crowd=0.9), checks())             # 10% of the light is others': a 3% dip
    assert v["verdict"] == "artefact" and "CROWDSAP" in v["artefact_because"][0]


def test_unexplained_is_strong_only_with_deep_dips_in_both_fluxes_a_quiet_star_and_every_catalogue_answering():
    v = investigate.judge(star([dip(15.0), dip(20.0)]), checks(simbad={"name": "KIC 1234567", "type": "*", "papers": 3}))
    assert v["verdict"] == "unexplained, strong" and not v["known_to_science"]
    v = investigate.judge(star([dip(15.0), dip(20.0)]), checks(errors=("VSX (via VizieR)",)))
    assert v["verdict"] == "unexplained, weak" and any("not every catalogue answered" in n for n in v["notes"])
    v = investigate.judge(star([dip(6.0)]), checks())
    assert v["verdict"] == "unexplained, weak"
    v = investigate.judge(star([dip(15.0), dip(20.0)]), checks(simbad={"name": "TYC 3162-665-1", "type": "*", "papers": 300}))
    assert v["known_to_science"] and any("300 papers" in n for n in v["notes"])


def test_the_catalogues_answers_are_read():
    simbad_reply = Reply(body={"data": [["TYC 3162-665-1", "*", 412, 0.0001]]})
    s = investigate.simbad(301.56, 44.46, get=lambda *a, **k: simbad_reply)
    assert s["answer"] == {"name": "TYC 3162-665-1", "type": "*", "papers": 412} and s["asked"] == date.today().isoformat()
    tsv = "#\n#\nName\tType\tPeriod\n \t \td\n----\t----\t----\nV1234 Cyg\tEA\t2.5\n"   # names, units, dashes, rows
    v = investigate.vsx(290.0, 44.0, get=lambda *a, **k: Reply(tsv))
    assert v["answer"] == {"name": "V1234 Cyg", "type": "EA", "period": "2.5"}
    page = ("<tbody><tr><td>True</a></td><td>53.6470815</td><td>0.0003133</td><td>54985.971403</td>"
            "<td>0.122454</td><td>0.2157</td><td>0.0209</td></tr>")
    assert investigate.villanova(8129189, get=lambda *a, **k: Reply(page))["answer"] == {
        "period_days": 53.6470815, "primary_depth": 0.2157}
    absent = "This entry is not currently in the EB Catalog"
    assert investigate.villanova(8462852, get=lambda *a, **k: Reply(absent))["answer"] is None
    gaia_csv = "source_id,ra,dec,phot_g_mean_mag,ruwe,sep\n1,290,44,12.1,1.05,0.2\n2,290,44,15.3,0.98,5.1\n"
    classes = "best_class_name,best_class_score\nECL,0.91\n"
    answers = iter([Reply(gaia_csv), Reply(classes)])
    g = investigate.gaia(290.0, 44.0, get=lambda *a, **k: next(answers))["answer"]
    assert g["star"]["g"] == 12.1 and g["class"] == {"name": "ECL", "score": 0.91}
    assert [n["separation_arcsec"] for n in g["neighbours"]] == [5.1]
    lc = ("oid,mjd,mag,catflags,filtercode\n1,58300,12.90,0,zr\n1,58400,12.92,0,zr\n1,58500,13.50,0,zr\n"
          "1,58600,12.91,32768,zr\n")
    z = investigate.ztf(290.0, 44.0, get=lambda *a, **k: Reply(lc))["answer"]
    assert z["points"] == 3 and z["zr"]["faintest_below_mag"] == pytest.approx(0.58, abs=0.01)


def test_a_service_that_does_not_answer_is_said_so_never_taken_for_nothing_found():
    import requests

    def down(*a, **k):
        raise requests.ConnectionError("down")
    s = investigate.simbad(1.0, 2.0, get=down)
    assert s["answer"] is None and s["error"].startswith("not answered")


def test_the_next_lead_is_taken_without_being_told_and_one_looked_into_is_not_taken_again(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    (tmp_path / "cache" / "kepler").mkdir(parents=True)
    (tmp_path / "cache" / "kepler" / "screened.json").write_text(json.dumps({
        "111": {"score": 3.0, "tabby_like": False, "real_dips": 1}, "222": {"score": 1.0, "tabby_like": True, "real_dips": 2},
        "333": {"missed": "timeout"}, "444": {"score": 0.0, "tabby_like": False, "real_dips": 0}}))
    (tmp_path / "cache" / "seti").mkdir(parents=True)
    (tmp_path / "cache" / "seti" / "KIC8462852-AGBT17A_999_68.json").write_text(json.dumps({"blocks": [[1, 2]], "done": {
        "0": {"events": [{"frequency_mhz": 2266.8, "drift_hz_s": 0.0, "snr": 30.0, "label": "candidate"}]}}}))
    order = [investigate.lead_id(lead) for lead in investigate.leads()]
    assert order == ["KIC-222", "KIC-111", "SETI-KIC8462852-2266.800000"]       # Tabby-like first; no dip, no lead
    assert investigate.lead_id(investigate.next_lead()) == "KIC-222"
    (tmp_path / "cache" / "research").mkdir(parents=True)
    (tmp_path / "cache" / "research" / "KIC-222.json").write_text("{}")
    assert investigate.lead_id(investigate.next_lead()) == "KIC-111"


def test_a_seti_candidate_with_signs_of_interference_is_likely_interference_never_a_proven_artefact():
    r = investigate.investigate_seti({"kind": "seti", "target": "KIC8462852", "session": "S", "in_on": [1, 1, 1],
                                      "in_off": [0, 0, 0], "frequency_mhz": 2266.8, "drift_hz_s": 0.31, "snr": 30.0})
    assert r["verdict"] == "likely interference" and not r["artefact_because"]
    assert "space operation" in r["likely_because"][0] and "does not name one" in r["likely_because"][0]
    assert "all 3 ON looks and none of the 3 OFF" in r["notes"][0] and "another session" in r["notes"][1]
    r = investigate.investigate_seti({"kind": "seti", "target": "X", "frequency_mhz": 1420.4, "drift_hz_s": 0.0, "snr": 12})
    assert r["verdict"] == "likely interference" and "not proof" in r["likely_because"][0]
    r = investigate.investigate_seti({"kind": "seti", "target": "X", "frequency_mhz": 1420.4, "drift_hz_s": 0.2, "snr": 12})
    assert r["verdict"] == "unexplained, weak" and not r["likely_because"]
    r = investigate.investigate_seti({"kind": "seti", "target": "X", "frequency_mhz": 2266.8, "drift_hz_s": 0.0, "snr": 12})
    assert "# X: likely interference" in investigate.report(r) and "- sign of interference:" in investigate.report(r)


def test_a_catalogue_explanation_with_a_catalogue_unanswered_is_only_likely():
    eb = {"period_days": 13.68}
    assert investigate.judge(star([dip(5.0)]), checks(eb=eb))["verdict"] == "explained"
    v = investigate.judge(star([dip(5.0)]), checks(eb=eb, errors=("VSX (via VizieR)",)))
    assert v["verdict"] == "likely explained" and any("VSX (via VizieR)" in n for n in v["notes"])


def test_only_seti_candidates_and_the_screens_own_leads_reach_the_queue(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    (tmp_path / "cache" / "kepler").mkdir(parents=True)
    (tmp_path / "cache" / "kepler" / "screened.json").write_text(json.dumps({
        "1": {"state": "done", "score": 1.0, "tabby_like": False, "real_dips": 0, "possible_repeats": 1},
        "2": {"state": "done", "score": 2.0, "tabby_like": False, "real_dips": 2, "known_binary": "EB 3.1 d"},
        "3": {"state": "failed", "why": "timeout", "attempts": 1}}))
    (tmp_path / "cache" / "tess").mkdir(parents=True)
    (tmp_path / "cache" / "tess" / "screened.json").write_text(json.dumps({
        "9": {"state": "done", "score": 0.5, "tabby_like": False, "real_dips": 0, "short_real": 1}}))
    (tmp_path / "cache" / "seti").mkdir(parents=True)
    (tmp_path / "cache" / "seti" / "T-S.json").write_text(json.dumps({"blocks": [[1, 2]], "done": {"0": {"events": [
        {"frequency_mhz": 1.0, "drift_hz_s": 0.1, "snr": 50.0, "label": "interference"},
        {"frequency_mhz": 2.0, "drift_hz_s": 0.1, "snr": 40.0, "label": "unconfirmed"},
        {"frequency_mhz": 3.0, "drift_hz_s": 0.1, "snr": 20.0, "label": "candidate"}]}}}))
    order = [investigate.lead_id(lead) for lead in investigate.leads()]
    assert order == ["KIC-1", "TIC-9", "SETI-T-3.000000"]    # a possible repeat and a short dip are leads; a known binary is not


def test_an_investigation_with_a_check_unanswered_is_asked_again_before_new_leads_then_given_up(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    (tmp_path / "cache" / "kepler").mkdir(parents=True)
    (tmp_path / "cache" / "kepler" / "screened.json").write_text(json.dumps({
        "111": {"score": 3.0, "tabby_like": True, "real_dips": 1}, "222": {"score": 1.0, "tabby_like": False, "real_dips": 2}}))
    (tmp_path / "cache" / "research").mkdir(parents=True)
    down = {"vsx": {"source": "VSX (via VizieR)", "answer": None, "error": "not answered (HTTPError)"},
            "villanova": {"source": "Villanova", "answer": None, "error": None}}
    (tmp_path / "cache" / "research" / "KIC-111.json").write_text(json.dumps({
        "lead": "KIC-111", "kind": "kepler", "checks": down, "investigated": "2026-11-03T14:00:00+00:00"}))
    assert investigate.unanswered(json.loads((tmp_path / "cache" / "research" / "KIC-111.json").read_text())) == ["VSX (via VizieR)"]
    assert investigate.lead_id(investigate.next_lead()) == "KIC-111"         # unfinished comes first
    tess_na = {"villanova": {"source": "Villanova", "answer": None, "error": "a TESS star: not in it"}}
    assert investigate.unanswered({"checks": tess_na}) == []                # not applying is not unanswered
    (tmp_path / "cache" / "research" / "KIC-111.json").write_text(json.dumps({
        "lead": "KIC-111", "kind": "kepler", "checks": down, "attempts": investigate.RECHECKS}))
    assert investigate.lead_id(investigate.next_lead()) == "KIC-222"         # given up after RECHECKS tries


def test_a_whole_investigation_keeps_its_record_and_report_and_matches_its_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)

    def get(url, params=None, timeout=None, headers=None):
        if "sim-tap" in url:
            return Reply(body={"data": [["KIC 1234567", "*", 2, 0.0]]})
        if "viz-bin" in url:
            return Reply("#\nName\tType\tPeriod\n----\t----\t----\n")
        if "villanova" in url:
            return Reply("This entry is not currently in the EB Catalog")
        if "gea.esac" in url:
            if "vari_classifier" in params["QUERY"]:
                return Reply("best_class_name,best_class_score\n")
            return Reply("source_id,ra,dec,phot_g_mean_mag,ruwe,sep\n1,290,44,11.8,1.0,0.1\n")
        return Reply("oid,mjd,mag,catflags,filtercode\n")
    lead = {"kind": "kepler", "kic": 1234567}
    other = investigate._asked("TESS (MAST)", "https://mast.stsci.edu/", {"tic": 1, "dips": 0})
    r = investigate.investigate_star(lead, get=get, say=lambda *_: None, star=star([dip(15.0), dip(20.0)]),
                                     other=other, cfg=config.example())
    assert r["verdict"] == "unexplained, strong" and r["follow_up"]["up"] and len(r["follow_up"]["up"]) == investigate.MONTHS
    assert r["follow_up"]["can_watch"] is True       # magnitude 11.9, a 20% dip, Cygnus is up
    path = investigate.keep(r, reports=tmp_path / "docs")
    text = path.read_text(encoding="utf-8")
    assert "# KIC 1234567: unexplained, strong" in text and "not a discovery" in text and "asked " in text
    assert (tmp_path / "cache" / "research" / "KIC-1234567.json").exists()
    valid(interface.envelope("investigate", r), "investigate")


def test_the_research_dashboard_counts_each_survey_and_each_lead_by_where_it_stands(tmp_path, monkeypatch):
    import agent
    import feeds
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(feeds, "CACHE", tmp_path / "feeds")
    kepler = tmp_path / "cache" / "kepler"
    kepler.mkdir(parents=True)
    (kepler / "targets.csv").write_text("kepid,kepmag\n" + "".join(f"{k},{k}\n" for k in range(1, 201)))
    (kepler / "screened.json").write_text(json.dumps({
        "1": {"score": 3.0, "tabby_like": True, "real_dips": 2}, "2": {"score": 0.0, "tabby_like": False, "real_dips": 0},
        "3": {"missed": "timeout"}, "4": {"score": 1.0, "tabby_like": False, "real_dips": 1}}))
    tess = tmp_path / "cache" / "tess"
    tess.mkdir(parents=True)
    (tess / "targets-s0014.json").write_text(json.dumps(list(range(100, 150))))     # what archive.py keeps
    (tess / "screened.json").write_text(json.dumps({"100": {"state": "done", "score": 0.2, "tabby_like": False,
                                                            "real_dips": 0, "possible_repeats": 1}}))
    (tmp_path / "cache" / "seti").mkdir(parents=True)
    (tmp_path / "cache" / "seti" / "KIC8462852-S.json").write_text(json.dumps({
        "blocks": [[1, 2]] * 308, "done": {"0": {"from_mhz": 1.0, "to_mhz": 3.9, "candidates": 0}}}))
    (tmp_path / "cache" / "research").mkdir(parents=True)
    (tmp_path / "cache" / "research" / "KIC-1.json").write_text(json.dumps({
        "lead": "KIC-1", "kind": "kepler", "star": "KIC 1", "verdict": "unexplained, weak", "known_to_science": False,
        "checks": {"vsx": {"source": "VSX", "answer": None, "error": "not answered (HTTPError)"}},
        "follow_up": {"can_watch": False}, "investigated": "2026-11-03T14:00:00+00:00"}))
    (tmp_path / "feeds").mkdir()
    (tmp_path / "feeds" / "arxiv_tabby-s-star.json").write_text(json.dumps([{"id": "2610.34806v1"}, {"id": "2607.01234v2"}]))
    (tmp_path / "cache" / "literature-read.json").write_text(json.dumps(["2607.01234"]))
    answer = valid(interface.run("research", lambda: agent.research(html=True)), "research")["data"]
    k = answer["surveys"][0]
    assert (k["screened"], k["failed"], k["of"], k["leads"], k["tabby_like"]) == (3, 1, 200, 2, 1)
    assert k["covered_percent"] == 2.0
    assert answer["surveys"][2]["searched"] == 1 and answer["surveys"][2]["of"] == 308
    t = answer["surveys"][1]
    assert (t["screened"], t["of"], t["leads"], t["covered_percent"]) == (1, 50, 1, 2.0)    # a possible repeat is a lead
    assert answer["leads"]["waiting"] == 2 and answer["leads"]["unexplained_weak"] == 1     # KIC-4 and TIC-100
    assert answer["leads"]["to_recheck"] == 1
    assert answer["papers_unread"] == 1
    page = (tmp_path / "web" / "research.html").read_text(encoding="utf-8")
    assert "Leads waiting: <b>2</b>, 1 to ask again" in page and "docs/research/KIC-1.md" in page


def test_this_months_hours_are_tonights_not_a_night_already_gone():
    import datetime
    import config
    import investigate
    star = {"star": "KIC 6448574", "ra": 293.663, "dec": 41.874, "mag": 12.0, "mag_band": "Kepler"}
    # 3 November: the 1st has gone; a star at +42° is up in the west after dark
    w = investigate.follow_up(star, 10.0, cfg=config.example(), months=2, today=datetime.date(2026, 11, 3))
    up = {u["month"]: u["dark_hours_up"] for u in w["up"]}
    assert up["2026-11"] > 0 and up["2026-12"] > 0


def test_a_red_giants_shallow_dips_are_its_own_and_a_deep_one_is_not():
    # KIC 6448574: Gaia G 8.11, BP-RP 1.6 (V-J 3.9, B-V 1.5), parallax 1.33 mas: absolute G about -1.3
    red = {"g": 8.11, "ruwe": 1.19, "bp_rp": 1.6, "parallax_mas": 1.326, "parallax_over_error": 55.0,
           "abs_g": -1.28, "source_id": "2077618484452244480", "separation_arcsec": 0.19}
    v = investigate.judge(star([dip(3.2), dip(5.0)]), checks(gaia={"star": red, "class": None, "neighbours": []}))
    assert v["verdict"] == "likely explained" and any("red giant" in r for r in v["explained_by"])
    assert any("on the star's class" in n for n in v["notes"])   # a class fits; no catalogue names its variability
    deep = investigate.judge(star([dip(15.0), dip(20.0)]), checks(gaia={"star": red, "class": None, "neighbours": []}))
    assert deep["verdict"].startswith("unexplained")         # far deeper than a giant's pulsation
    dwarf = dict(red, abs_g=6.5)                              # as red, but on the main sequence
    assert investigate.judge(star([dip(5.0)]), checks(gaia={"star": dwarf, "class": None,
                                                            "neighbours": []}))["verdict"] == "unexplained, weak"
