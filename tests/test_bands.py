"""Discovery and photometry by camera and band (docs/mono-upgrade.md, item 8):
references per band, a difference pairing only one camera and band,
magnitudes named for what took them with their errors, and a transit's
comparison ensemble. The 183C's unfiltered wording and behaviour stay."""
import argparse

import numpy as np
import pytest

import config
import depth
import difference
import filters
import forced
import interface
import reference
import stacking
import transits


@pytest.fixture
def both(monkeypatch):
    plain = config.hardware()
    cameras = dict(plain["cameras"], **{"183m": dict(plain["camera"], name="183m", cooled=True, mono=True)})
    monkeypatch.setattr(config, "hardware", lambda: dict(plain, cameras=cameras))
    monkeypatch.setattr(filters, "settings", lambda cfg=None: {"makers": "Optolong,Optolong,Optolong,Optolong,,,"})


def stack(path, **cards):
    stacking.write_stack(path, np.zeros((20, 30, 3), np.float32), {"EXPTIME": 480, **cards})
    return path


def test_a_183m_depth_record_names_its_band_and_colour_term_and_the_183c_s_stays(both):
    plain = {"band": "Gaia G (camera unfiltered)", "colour_term": 0.12, "colour_ref": 1.0}
    assert depth.named(dict(plain), {"EXPTIME": 16})["band"] == "Gaia G (camera unfiltered)"
    named = depth.named(dict(plain), {"INSTRUME": "183m", "FILTER": "L", "FILTPOS": 1})
    assert named["band"].startswith("L (Optolong), 183M, instrumental") and "+0.120 mag per mag of BP-RP" in named["band"]
    assert named["band_key"] == ["183m", "L"]
    bare = depth.named({"colour_term": None, "kinds": {"colour_term": "measured"}},
                       {"INSTRUME": "183m", "FILTER": "G", "FILTPOS": 3})
    assert "no colour term" in bare["band"] and bare["kinds"]["colour_term"] == "not known"
    for record in (named, bare):
        assert not record["band"].startswith("Gaia G") and " V" not in record["band"]


def test_a_difference_pairs_only_one_camera_and_band(both, tmp_path, monkeypatch):
    calibrated = {"TY_CALIB": True}
    new = stack(tmp_path / "new.fits", INSTRUME="183m", FILTER="L", **calibrated)
    other_band = stack(tmp_path / "r.fits", INSTRUME="183m", FILTER="R", **calibrated)
    colour = stack(tmp_path / "c.fits", INSTRUME="183c")
    monkeypatch.setattr(depth, "find_stack", lambda given: tmp_path / given)
    monkeypatch.setattr(depth, "plate", lambda *a: pytest.fail("never lined up"))
    for ref in (other_band, colour):
        args = argparse.Namespace(new=new.name, reference=ref.name, near="M31", plant=0)
        with pytest.raises(interface.Refusal) as refused:
            difference.run(args, say=lambda *_: None)
        assert refused.value.code_name == "INVALID_REQUEST" and "one camera and band" in str(refused.value)


def test_an_uncalibrated_183m_stack_never_enters_a_search(both, tmp_path, monkeypatch):
    new = stack(tmp_path / "new.fits", INSTRUME="183m", FILTER="L", TY_CALIB=False, TY_MISS="a dark at ...")
    ref = stack(tmp_path / "ref.fits", INSTRUME="183m", FILTER="L", TY_CALIB=True)
    monkeypatch.setattr(depth, "find_stack", lambda given: tmp_path / given)
    with pytest.raises(interface.Refusal) as refused:
        difference.run(argparse.Namespace(new=new.name, reference=ref.name, near="M31", plant=0), say=print)
    assert refused.value.code_name == "CALIBRATION_MISSING"


def test_references_are_kept_per_band_and_the_183c_s_stay_where_they_were(both):
    base = config.camera_folder() / "reference" / "M31"
    assert reference.folder("M31") == base                          # the 183C's train: no wheel
    assert reference.folder("M31", "L") == base / "L" and reference.folder("M31", None) == base


def test_every_new_magnitude_carries_its_error():
    from test_difference import SHAPE, night
    rng = np.random.default_rng(4)
    xy = rng.uniform(30, (SHAPE[1] - 30, SHAPE[0] - 30), (400, 2))
    flux = 10 ** rng.uniform(2.5, 4.5, 400)
    ref = night(xy, flux, fwhm=4.0, seed=1)
    new = night(xy, flux, fwhm=5.2, shift=(1.4, -0.8), scale=0.85, seed=2,
                extra=(np.array([[412.3, 287.6]]), np.array([900.0])))
    record, _ = difference.subtract(new, ref, zeropoint=22.0, zeropoint_error=0.03)
    with_mag = [c for c in record["candidates"] if "mag" in c]
    assert with_mag and all(c["mag_error"] >= 0.03 for c in with_mag)


def test_forced_photometry_never_mixes_bands_into_one_name():
    assert forced.bands_of([{"mag": 17.0}]) == "unfiltered, calibrated approximately to Gaia G"
    mixed = forced.bands_of([{"band": "L (Optolong), 183M"}, {"mag": 17.0}])
    assert mixed.startswith("instrumental, each measurement in its own band: L (Optolong), 183M")
    assert "183C" in mixed


def test_a_transit_is_measured_against_an_ensemble_of_like_stars():
    # Target (G 11.0, BP-RP 0.8), six like comparisons, one far too red, one far too faint.
    stars = np.array([[0, 0, 11.0, 0.8]] + [[i, i, 11.0 + 0.1 * i, 0.7 + 0.05 * i] for i in range(1, 7)]
                     + [[9, 9, 11.1, 2.5], [10, 10, 14.5, 0.8]], float)
    batches = 40
    haze = 0.05 * np.sin(np.linspace(0, 3, batches))                  # thin cloud dims everything together
    mags = stars[:, 2][None, :] + haze[:, None]
    dip = np.zeros(batches)
    dip[15:25] = 0.01                                                  # the planet: 1% on the target alone
    mags[:, 0] += dip
    group = transits.ensemble(stars, mags, 0)
    assert group["count"] == 6 and all(s["bp_rp"] < 1.1 for s in group["stars"])
    curve = group["curve"]
    assert np.ptp(curve[:15]) < 1e-9 and curve[20] - curve[5] == pytest.approx(0.01)
    assert group["scatter_mmag"] == pytest.approx(0.0, abs=1e-6)
    empty = transits.ensemble(stars[:1], mags[:, :1], 0)
    assert empty["count"] == 0
