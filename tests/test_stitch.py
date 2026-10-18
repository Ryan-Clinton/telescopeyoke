"""stitch.py: every night's frames of a mosaic as one picture. Made-up panels
with known plate solves stand in for the real stacks."""
import json

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

import config
import interface
import stitch


def panel_wcs(ra, dec, shape, scale=1.32 / 3600):
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [ra, dec]
    w.wcs.crpix = [(shape[1] + 1) / 2, (shape[0] + 1) / 2]
    w.wcs.cdelt = [-scale, scale]
    return w


def sky_with_star(wcs, shape, star, level, rng):
    """Colour planes: a flat sky at `level`, grain, and one star at `star` (RA, Dec)."""
    planes = level + rng.normal(0, 1, (3,) + shape).astype(np.float32)
    x, y = wcs.world_to_pixel_values(*star)
    yy, xx = np.indices(shape)
    planes += 200 * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 2.0 ** 2))
    return planes.astype(np.float32)


def test_two_overlapping_panels_join_with_the_star_once_and_no_step_in_the_sky():
    rng = np.random.default_rng(1)
    shape = (120, 200)
    left, right = panel_wcs(10.0, 41.0, shape), panel_wcs(10.0 + 150 * 1.32 / 3600 / np.cos(np.radians(41)), 41.0, shape)
    star = left.pixel_to_world_values(180, 60)          # in the overlap
    inputs = [(sky_with_star(left, shape, star, 50, rng), left, 100.0),
              (sky_with_star(right, shape, star, 80, rng), right, 300.0)]   # a brighter sky on the second
    out_wcs, out_shape = stitch.grid([(left, shape), (right, shape)])
    assert out_shape[1] >= 330 and out_shape[0] >= 115     # both panels' width, less the overlap
    joined, weights = stitch.blend(inputs, out_wcs, out_shape, feather=20)
    x, y = out_wcs.world_to_pixel_values(*star)
    lum = joined.sum(axis=0)
    assert lum[int(round(float(y))), int(round(float(x)))] > 300          # the star, once, where it belongs
    covered = weights > 0
    sky = np.where(covered, lum, np.nan)
    rows = slice(20, 100)
    # The two skies are levelled: no step across the seam.
    assert abs(np.nanmedian(sky[rows, 40:120]) - np.nanmedian(sky[rows, 230:310])) < 3


def test_only_fields_with_a_new_session_are_restacked(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    for field, nights in (("M31-P1", ["20261017-230000", "20261018-221000"]), ("M31-P2", ["20261018-221500"])):
        for night in nights:
            folder = tmp_path / "frames" / field / night
            folder.mkdir(parents=True)
            (folder / "light-0001.fits").write_bytes(b"")
            (folder / "final.fits").write_bytes(b"")
    (tmp_path / "frames" / "M31-P1" / "combined").mkdir()
    (tmp_path / "frames" / "M31-P1" / "combined" / "final.fits").write_bytes(b"")
    kept = {"M31-P1": ["20261017-230000"], "M31-P2": ["20261018-221500"]}
    assert stitch.stale("M31", "M31-P1", kept)                  # a night added since
    assert not stitch.stale("M31", "M31-P2", kept)
    assert stitch.stack_of("M31-P2") == tmp_path / "frames" / "M31-P2" / "20261018-221500" / "final.fits"
    assert stitch.stack_of("M31-P1") == tmp_path / "frames" / "M31-P1" / "combined" / "final.fits"


def test_a_whole_run_restacks_what_is_new_and_writes_the_picture(tmp_path, monkeypatch):
    import mosaic
    rng = np.random.default_rng(2)
    shape = (60, 90)
    monkeypatch.setattr(config, "DATA", tmp_path)
    wcs = {"M31-P1": panel_wcs(10.0, 41.0, shape), "M31-P2": panel_wcs(10.02, 41.0, shape)}
    monkeypatch.setattr(mosaic, "load", lambda name: {"panels": [{"id": "M31-P1"}, {"id": "M31-P2"}]})
    for field, w in wcs.items():
        folder = tmp_path / "frames" / field / "20261018-221000"
        folder.mkdir(parents=True)
        (folder / "light-0001.fits").write_bytes(b"")
        fits.PrimaryHDU(sky_with_star(w, shape, w.pixel_to_world_values(45, 30), 40, rng)).writeto(folder / "final.fits")
        (folder / "restack.json").write_text(json.dumps({"summary": {"total_exposure_s": 256}}))
    restacked = []
    answer = stitch.run("M31", say=lambda *_: None, solver=lambda lum, field: wcs[field],
                        restacker=lambda field, host: restacked.append(field))
    assert restacked == ["M31-P1", "M31-P2"] and answer["joined"] == 2
    assert (tmp_path / "mosaics" / "M31-mosaic.fits").exists() and (tmp_path / "web" / "M31-mosaic.jpg").exists()
    restacked.clear()
    stitch.run("M31", say=lambda *_: None, solver=lambda lum, field: wcs[field],
               restacker=lambda field, host: restacked.append(field))
    assert restacked == []                                       # nothing new: nothing restacked again


def test_a_mosaic_with_no_plan_is_refused(tmp_path, monkeypatch):
    import mosaic
    import pytest
    monkeypatch.setattr(mosaic, "load", lambda name: None)
    with pytest.raises(interface.Refusal):
        stitch.fields("M101")
