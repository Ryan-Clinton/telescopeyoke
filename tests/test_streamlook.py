"""The live stream's picture (docs/stream-look.md): every state draws, keeps
inside the safe margins, reads clearly, and never names the place or shows
a candidate's position."""
import re

import numpy as np

import pytest

import config
import streamlook

STATES = streamlook.examples()


@pytest.fixture(scope="module")
def drawn():
    stack, single = streamlook.example_pictures()
    return {name: streamlook.compose(state, stack, single) for name, state in STATES.items()}


def test_each_state_draws_a_full_picture(drawn):
    assert set(drawn) == {"patrol", "transit", "between", "candidate", "end"}
    for canvas in drawn.values():
        assert canvas.image.size == (streamlook.WIDTH, streamlook.HEIGHT)
        assert canvas.written


def test_every_word_is_inside_the_safe_margins(drawn):
    for name, canvas in drawn.items():
        for w in canvas.written:
            x0, y0, x1, y1 = w["box"]
            assert streamlook.MARGIN_X <= x0 and x1 <= streamlook.WIDTH - streamlook.MARGIN_X, (name, w["words"])
            assert streamlook.MARGIN_Y <= y0 and y1 <= streamlook.HEIGHT - streamlook.MARGIN_Y, (name, w["words"])


def test_every_word_reads_clearly_against_what_it_is_on(drawn):
    for name, canvas in drawn.items():
        for w in canvas.written:
            assert streamlook.contrast(w["colour"], w["on"]) >= 7, (name, w["words"])
            assert w["size"] >= 18, (name, w["words"])


def test_no_word_names_the_place_or_gives_a_position(drawn):
    place = config.example()["site"]["name"]
    for canvas in drawn.values():
        for w in canvas.written:
            assert place not in w["words"]
            assert not re.search(r"\bRA\b|\bDec\b|\d+h\s?\d+m|[+-]\d+°", w["words"]), w["words"]


def test_times_are_utc_and_say_so(drawn):
    clocks = [w["words"] for c in drawn.values() for w in c.written if re.search(r"\d\d:\d\d", w["words"])]
    assert clocks and all("UTC" in words for words in clocks)


def test_the_candidate_states_show_no_cut_out_or_place():
    stack, single = streamlook.example_pictures()
    for stage in ("detected", "second", "result"):
        state = dict(STATES["candidate"], candidate={"stage": stage, "result": "Not confirmed: it did not appear again"})
        words = " ".join(w["words"] for w in streamlook.compose(state, stack, single).written)
        assert "POSSIBLE CHANGE" in words or "SECOND LOOK" in words or "RESULT" in words


def test_each_target_entry_has_its_facts_and_fits():
    found = streamlook.targets()
    for name, entry in found["targets"].items():
        assert entry["words"] and entry["distance"] and entry["magnitude"], name
        assert len(entry["words"]) <= 160, name
        assert all(len(caption) <= 120 for caption in entry.get("captions", [])), name
    assert set(found["programmes"]) >= {"patrol", "transit", "picture"}


def test_the_display_stretch_keeps_the_sky_dark_and_the_picture_its_size():
    stack, single = streamlook.example_pictures()
    for picture in (stack, single):
        shown = streamlook.display(picture)
        assert shown.size == picture.size
        sky = float(np.median(np.asarray(shown.convert("L"))))
        assert 5 < sky < 60                    # dark, but not crushed to black


def test_a_picture_is_fitted_whole_never_cropped():
    stack, _ = streamlook.example_pictures()        # 1500 x 1000 into a wider box
    fitted = streamlook.fit(stack, (1274, 600))
    assert fitted.size == (1274, 600)
    assert fitted.getpixel((0, 300)) == streamlook.COLOURS["background"]      # letterboxed at the sides


PLANET = {"planet": "WASP-12 b", "star": "WASP-12", "period": 1.091418901, "epoch": 2457607.519305,
          "hours": 3.0, "depth": 1.5}


def test_the_light_curve_shows_only_once_it_is_long_and_steady(tmp_path, monkeypatch):
    import json
    import numpy as np
    now = 1792460464.0
    t = streamlook.transit_state(PLANET, None, now)
    assert t["state"] in ("baseline", "measuring") and "points" not in t

    def write(minutes, scatter):
        jd = [(now - 60 * m) / 86400 + 2440587.5 for m in range(minutes, 0, -2)]
        rng = np.random.default_rng(0)
        mags = [11.6 + rng.normal(0, scatter) for _ in jd]
        (tmp_path / "transit-WASP-12b.json").write_text(json.dumps({"jd": jd, "mag": mags}))
    before = t["ingress"] - 60                       # a time before the transit: all baseline
    write(20, 0.001)
    assert streamlook.transit_state(PLANET, tmp_path, before)["state"] == "baseline"
    write(60, 0.03)                                  # long enough, far too ragged
    assert streamlook.transit_state(PLANET, tmp_path, now)["state"] != "live"
    write(60, 0.001)
    steady = streamlook.transit_state(PLANET, tmp_path, now)
    assert steady["state"] == "live" and len(steady["points"]) > 20


def test_a_patrol_panel_is_laid_out_as_the_night_s_mosaic():
    discovery = {"mosaics": [{"name": "M31", "columns": 4, "rows": 2, "panels": [
        {"panel": n, "state": "done" if n < 4 else "planned"} for n in range(1, 9)]}],
        "sessions": [{"field": "M31-P2", "finished": True, "unexplained": 1}]}
    patrol, candidate = streamlook.patrol_state("M31-P4", discovery)
    assert patrol["field"] == "Andromeda" and patrol["possible"] == 1
    states = {p["id"]: (p["col"], p["row"], p["state"]) for p in patrol["panels"]}
    assert states["P1"] == (0, 0, "done") and states["P4"] == (3, 0, "current") and states["P5"] == (0, 1, "open")
    assert candidate is None
    _, candidate = streamlook.patrol_state("M31-P2", discovery)
    assert candidate == {"stage": "second"}


def test_the_state_follows_what_is_running(monkeypatch):
    status = {"name": "M42", "age": 5, "exposure": 16, "accepted": 10, "captured": 11, "integration": 160}
    monkeypatch.setattr(streamlook, "transit_for", lambda name: None)
    assert streamlook.from_status(status, now=1.0)["kind"] == "picture"
    monkeypatch.setattr(streamlook, "transit_for", lambda name: PLANET if name == "WASP-12" else None)
    assert streamlook.from_status(dict(status, name="WASP-12"), now=1792460464.0)["kind"] == "transit"
