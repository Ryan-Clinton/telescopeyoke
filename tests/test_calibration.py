"""Calibration by camera (docs/calibration.md): the 183C's darks scaled to the
night as always, the cooled 183M's matched on every setting and never
scaled, its masters versioned and never overwritten, and science refusing a
183M frame or stack whose masters are missing (fail closed)."""
import numpy as np
import pytest
from astropy.io import fits

import calibrate
import config
import interface
import stacking

SHAPE = (40, 60)
CARDS = {"INSTRUME": "183m", "TELESCOP": "183m-cc", "FILTER": "L", "FILTPOS": 1, "EXPTIME": 16.0, "GAIN": 800,
         "OFFSET": 50, "XBINNING": 1, "READSPD": 0, "SET-TEMP": -5.0}


@pytest.fixture
def both(tmp_path, monkeypatch):
    """The 183C and a cooled 183M profile; the 183M's masters in a folder of their own."""
    plain = config.hardware()
    cameras = dict(plain["cameras"], **{"183m": dict(plain["camera"], name="183m", cooled=True, mono=True)})
    monkeypatch.setattr(config, "hardware", lambda: dict(plain, cameras=cameras))
    folder = tmp_path / "183m-calibration"
    monkeypatch.setattr(stacking, "library", lambda camera: folder if camera == "183m" else stacking.CALIBRATION)
    monkeypatch.setattr(stacking, "CALIBRATION", tmp_path / "183c-calibration")
    return folder


def keep(folder, stem, data, **cards):
    return stacking.keep_master(folder, stem, np.asarray(data, np.float32), dict(CARDS, **cards))


def full_set(folder, dark_level=100.0):
    keep(folder, stacking.dark_stem(CARDS), np.full(SHAPE, dark_level))
    flat = np.full(SHAPE, 1200.0)
    flat[:, :20] = 600 + 200                               # the left third darker (vignetting), plus the flat-dark
    keep(folder, stacking.flat_stem(CARDS), flat, EXPTIME=2.0)
    keep(folder, stacking.dark_stem(dict(CARDS, EXPTIME=2.0)), np.full(SHAPE, 200.0), EXPTIME=2.0)
    mask = np.zeros(SHAPE, np.uint8)
    mask[5, 45] = 1
    keep(folder, "badpixels", mask)


def test_the_183c_keeps_its_scaled_calibration_and_permits_missing_masters(both):
    for header in (None, {"EXPTIME": 2.0}, {"INSTRUME": "183c"}):
        cal = stacking.Calibration(2.0, 1500, header)
        assert type(cal) is stacking.Calibration and cal.missing == () and not cal.matched
        assert stacking.require(cal, "Photometry") is cal                 # science takes it as it always did


def test_a_183m_frame_with_no_masters_is_uncalibrated_and_science_refuses_it(both):
    cal = stacking.Calibration(16.0, 800, CARDS)
    assert isinstance(cal, stacking.MatchedCalibration) and not cal.calibrated
    assert any(m.startswith("a dark at EXPTIME 16.0") for m in cal.missing)
    assert any("flat for 183m-cc in L" in m for m in cal.missing) and "a bad-pixel map" in cal.missing
    assert cal.describe().startswith("UNCALIBRATED, quick look only")
    with pytest.raises(interface.Refusal) as refused:
        stacking.require(cal, "A difference image")
    assert refused.value.code_name == "CALIBRATION_MISSING" and "a dark at" in str(refused.value)


def test_a_183m_dark_is_matched_never_scaled(both):
    full_set(both)
    cal = stacking.Calibration(16.0, 800, CARDS)
    assert cal.calibrated and set(cal.masters) == {"dark", "flat", "flat-dark", "bad-pixel map"}
    raw = np.full(SHAPE, 1100.0)
    raw[10, 40] = 5000                                   # a hot pixel twice as hot as the dark's: not scaled to it
    out = cal.apply(raw.astype(np.uint16))
    assert out[0, 40] == pytest.approx(1000.0)                          # (1100 - 100) / 1.0
    assert out[0, 10] == pytest.approx(1000.0 / (600 / 1000))           # the flat less its flat-dark
    assert out[10, 40] == pytest.approx(4900.0) and cal.scale == 1.0


def test_a_dark_at_any_other_setting_does_not_match(both):
    full_set(both)
    for change in ({"SET-TEMP": 0.0}, {"READSPD": 1}, {"OFFSET": 40}, {"XBINNING": 2}, {"GAIN": 300},
                   {"EXPTIME": 8.0}):
        cal = stacking.Calibration(16.0, 800, dict(CARDS, **change))
        assert not cal.calibrated and any("dark at" in m for m in cal.missing)


def test_a_flat_is_per_filter_and_needs_its_flat_dark(both):
    full_set(both)
    assert any("flat for 183m-cc in R" in m for m in stacking.Calibration(16.0, 800, dict(CARDS, FILTER="R")).missing)
    for path in both.glob("dark-2s-*"):
        path.unlink()
    cal = stacking.Calibration(16.0, 800, CARDS)
    assert any("flat-dark" in m for m in cal.missing)


def test_masters_are_versioned_never_overwritten_and_the_newest_matching_is_used(both):
    first = keep(both, stacking.dark_stem(CARDS), np.full(SHAPE, 100.0))
    second = keep(both, stacking.dark_stem(CARDS), np.full(SHAPE, 90.0))
    assert first.name.endswith("-v1.fits") and second.name.endswith("-v2.fits")
    assert fits.getdata(first)[0, 0] == 100.0 and fits.getheader(second)["TY_VER"] == 2
    cal = stacking.Calibration(16.0, 800, CARDS)
    assert cal.masters["dark"] == second.name


def test_bad_pixels_are_replaced_by_their_neighbours(both):
    full_set(both)
    raw = np.full(SHAPE, 1100, np.uint16)
    raw[5, 45] = 4000
    assert stacking.Calibration(16.0, 800, CARDS).apply(raw)[5, 45] == pytest.approx(1000.0)
    dark = np.full(SHAPE, 100.0)
    dark[3, 4] = 2000
    assert calibrate.bad_pixels(dark)[3, 4] == 1 and calibrate.bad_pixels(dark).sum() == 1


def test_a_stack_says_how_it_was_calibrated_and_an_uncalibrated_183m_stack_enters_no_science(both, tmp_path):
    cal = stacking.Calibration(16.0, 800, CARDS)
    cards = stacking.stack_cards(cal, CARDS)
    assert cards["TY_CALIB"] is False and cards["INSTRUME"] == "183m" and cards["FILTER"] == "L"
    stack = tmp_path / "final.fits"
    stacking.write_stack(stack, np.zeros((*SHAPE, 3), np.float32), {"EXPTIME": 16, **cards})
    with pytest.raises(interface.Refusal) as refused:
        stacking.require_stack(stack, "A depth measurement")
    assert refused.value.code_name == "CALIBRATION_MISSING"
    full_set(both)
    good = stacking.stack_cards(stacking.Calibration(16.0, 800, CARDS), CARDS)
    stacking.write_stack(stack, np.zeros((*SHAPE, 3), np.float32), {"EXPTIME": 16, **good})
    assert stacking.require_stack(stack, "A depth measurement")["TY_DARK"].startswith("dark-16s")
    old = tmp_path / "old.fits"                                      # a 183C stack from before any of this
    stacking.write_stack(old, np.zeros((*SHAPE, 3), np.float32), {"EXPTIME": 16})
    stacking.require_stack(old, "A difference image")


def test_a_worker_chooses_the_183c_s_calibration_by_exposure_and_gain_alone(both):
    stacking._calibration.cache_clear()
    cal = stacking._calibration(2.0, 1500, stacking.worker_cards({"EXPTIME": 2.0, "GAIN": 1500}))
    assert type(cal) is stacking.Calibration
    cal = stacking._calibration(16.0, 800, stacking.worker_cards(CARDS))
    assert isinstance(cal, stacking.MatchedCalibration)
    stacking._calibration.cache_clear()
