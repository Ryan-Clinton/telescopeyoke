"""realbogus.py: told stars from the subtraction's leavings, tested night by night."""
import argparse
import json

import numpy as np
import pytest

import config
import realbogus

FWHM = 4.8


def star(shape, x, y, peak, fwhm=FWHM):
    yy, xx = np.mgrid[:shape[0], :shape[1]]
    s = fwhm / 2.3548
    return peak * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * s * s))


def night(rng, planted=40, junk=40, shape=(400, 400)):
    """A significance map with planted stars (round, the stars' width) and
    junk: hot pixels (one pixel), trails (long) and residuals on stars."""
    sig = rng.normal(0, 1, shape)
    ref = rng.normal(100, 3, shape)
    spots = rng.uniform(30, shape[0] - 30, (planted, 2))
    for x, y in spots:
        sig += star(shape, x, y, rng.uniform(6, 15))
    for i in range(junk):
        x, y = rng.integers(30, shape[0] - 30, 2)
        kind = i % 3
        if kind == 0:
            sig[y, x] += rng.uniform(6, 15)                                   # a hot pixel
        elif kind == 1:
            for t in range(-6, 7):
                sig[y, x + t] += rng.uniform(5, 9)                            # a trail
        else:
            ref += star(shape, x, y, 3000)                                   # a bright star...
            sig += star(shape, x, y, rng.uniform(6, 12), fwhm=1.6)            # ...badly subtracted
    usable = np.zeros(shape, bool)
    usable[20:-20, 20:-20] = True
    return sig, usable, ref, (spots, np.full(len(spots), 17.0))


def test_the_measurements_tell_a_star_from_a_hot_pixel():
    shape = (60, 60)
    sig = star(shape, 30, 30, 10.0)
    ref = np.full(shape, 100.0)
    good = dict(zip(realbogus.FEATURES, realbogus.features(sig, ref, 30, 30, FWHM)))
    hot = np.zeros(shape)
    hot[30, 30] = 10.0
    bad = dict(zip(realbogus.FEATURES, realbogus.features(hot, ref, 30, 30, FWHM)))
    assert good["score"] == pytest.approx(10.0)
    assert good["width"] > 3 * bad["width"] and bad["sharpness"] > good["sharpness"]


def test_examples_are_the_planted_stars_found_and_every_other_peak():
    sig, usable, ref, planted = night(np.random.default_rng(1))
    X, y = realbogus.examples_from(sig, usable, ref, FWHM, planted)
    assert X.shape[1] == len(realbogus.FEATURES)
    assert 30 <= y.sum() <= 40 and (y == 0).sum() >= 25


def test_trained_on_some_nights_it_sets_aside_the_junk_of_another_and_keeps_its_stars():
    rng = np.random.default_rng(2)
    sets = [realbogus.examples_from(*night(rng)[:3], FWHM, night(rng)[3]) for _ in range(1)]
    train = [night(rng) for _ in range(3)]
    X = np.vstack([realbogus.examples_from(s, u, r, FWHM, p)[0] for s, u, r, p in train])
    y = np.concatenate([realbogus.examples_from(s, u, r, FWHM, p)[1] for s, u, r, p in train])
    model = realbogus.fit(X, y)
    cut = realbogus.threshold_for(model, X[y == 1])
    s, u, r, p = night(rng)
    result = realbogus.judged(model, cut, *realbogus.examples_from(s, u, r, FWHM, p))
    assert result["planted_kept"] >= 0.85 * result["planted"]
    assert result["bogus_set_aside"] >= 0.6 * result["bogus"]
    assert sets


def test_training_runs_night_by_night_and_keeps_its_proof(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    folders = []
    for n in range(3):
        f = tmp_path / "frames" / "M31" / f"2026101{n}-220000"
        f.mkdir(parents=True)
        folders.append((f, {"candidates": [], "new": "n", "reference": "r"}))
    rng = np.random.default_rng(3)
    monkeypatch.setattr(realbogus, "nights", lambda: folders)

    def subtraction_of(folder, record, count, seed):
        s, u, r, p = night(rng)
        return {"significance": s, "usable": u, "ref": r, "fwhm": FWHM, "planted": p}
    monkeypatch.setattr(realbogus, "subtraction_of", subtraction_of)
    answer = realbogus.train(plant_count=40, runs=1, say=lambda s: None)
    assert len(answer["tested"]) == 3 and answer["summary"]["share_kept"] >= 0.85
    assert answer["summary"]["share_set_aside"] >= 0.5
    kept = json.loads(realbogus.path().read_text(encoding="utf-8"))
    assert kept["model"]["cut"] == answer["model"]["cut"] and "provenance" in kept


def test_too_few_nights_is_a_refusal(tmp_path, monkeypatch):
    import interface
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(realbogus, "nights", lambda: [])
    with pytest.raises(interface.Refusal, match="two nights"):
        realbogus.train(say=lambda s: None)


def test_vetting_gives_the_probability_as_advice_and_dismisses_nothing(tmp_path, monkeypatch):
    from astropy.io import fits
    import vet
    monkeypatch.setattr(config, "DATA", tmp_path)
    rng = np.random.default_rng(4)
    train = [night(rng) for _ in range(2)]
    X = np.vstack([realbogus.examples_from(s, u, r, FWHM, p)[0] for s, u, r, p in train])
    y = np.concatenate([realbogus.examples_from(s, u, r, FWHM, p)[1] for s, u, r, p in train])
    model = realbogus.fit(X, y)
    model["cut"] = realbogus.threshold_for(model, X[y == 1])
    realbogus.path().parent.mkdir(parents=True)
    realbogus.path().write_text(json.dumps({"model": model}), encoding="utf-8")
    shape = (100, 100)
    sig = rng.normal(0, 1, shape) + star(shape, 30, 30, 9.0)
    sig[70, 70] += 9.0
    fits.PrimaryHDU(sig.astype(np.float32)).writeto(tmp_path / "difference.fits")
    evidence = [{"x": 30, "y": 30, "kinds": {}, "verdict": vet.UNEXPLAINED, "clues": []},
                {"x": 70, "y": 70, "kinds": {}, "verdict": vet.UNEXPLAINED, "clues": []}]
    cut = vet.classify(evidence, tmp_path, np.full(shape, 100.0), FWHM)
    assert cut == model["cut"] and evidence[0]["real_bogus"] > evidence[1]["real_bogus"]
    assert evidence[1]["kinds"]["real_bogus"] == "inferred"
    assert any("classifier" in c for c in evidence[1]["clues"]) and not evidence[0]["clues"]
    assert all(e["verdict"] == vet.UNEXPLAINED for e in evidence)


def test_no_model_leaves_vetting_as_it_was(tmp_path, monkeypatch):
    import vet
    monkeypatch.setattr(config, "DATA", tmp_path)
    evidence = [{"x": 3, "y": 3, "kinds": {}, "verdict": vet.UNEXPLAINED}]
    assert vet.classify(evidence, tmp_path, np.zeros((10, 10)), FWHM) is None and "real_bogus" not in evidence[0]


def test_show_needs_a_model(tmp_path, monkeypatch):
    import interface
    monkeypatch.setattr(config, "DATA", tmp_path)
    with pytest.raises(interface.Refusal, match="No classifier"):
        realbogus.run(argparse.Namespace(action="show", session=None))


def test_score_reads_a_colour_reference_as_one_plane(tmp_path, monkeypatch):
    from astropy.io import fits
    monkeypatch.setattr(config, "DATA", tmp_path)
    rng = np.random.default_rng(6)
    s, u, r, p = night(rng)
    X, y = realbogus.examples_from(s, u, r, FWHM, p)
    model = realbogus.fit(X, y)
    model["cut"] = realbogus.threshold_for(model, X[y == 1])
    realbogus.path().parent.mkdir(parents=True)
    realbogus.path().write_text(json.dumps({"model": model}), encoding="utf-8")
    session = tmp_path / "frames" / "M31" / "s"
    session.mkdir(parents=True)
    fits.PrimaryHDU(s.astype(np.float32)).writeto(session / "difference.fits")
    fits.PrimaryHDU(np.stack([r, r, r]).astype(np.float32)).writeto(tmp_path / "ref.fits")
    (session / "candidates.json").write_text(json.dumps({"reference": str(tmp_path / "ref.fits"), "fwhm_px": FWHM,
                                                        "candidates": [{"x": 100, "y": 100, "score": 6.0}]}))
    answer = realbogus.run(argparse.Namespace(action="score", session=str(session)), say=lambda s: None)
    assert 0 <= answer["candidates"][0]["real_bogus"] <= 1
