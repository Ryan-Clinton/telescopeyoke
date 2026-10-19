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


def test_every_session_is_placed_on_its_own_and_only_unstacked_ones_are_stacked(tmp_path, monkeypatch):
    """Each session lines up only with itself: on 18 October 2026, after the
    camera had been off for cleaning, a panel's nights restacked together
    matched to 6 px. A session with no stack yet is stacked on its own."""
    import mosaic
    rng = np.random.default_rng(2)
    shape = (60, 90)
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(mosaic, "load", lambda name: {"panels": [{"id": "M31-P1"}, {"id": "M31-P2"}], "angle_deg": 37.5})
    wcs = {"M31-P1": panel_wcs(10.0, 41.0, shape), "M31-P2": panel_wcs(10.02, 41.0, shape)}
    made = []
    for field, w in wcs.items():
        for night, stacked in (("20261017-230000", True), ("20261018-221000", field == "M31-P1")):
            folder = tmp_path / "frames" / field / night
            folder.mkdir(parents=True)
            (folder / "light-0001.fits").write_bytes(b"")
            if stacked:
                fits.PrimaryHDU(sky_with_star(w, shape, w.pixel_to_world_values(45, 30), 40, rng)).writeto(
                    folder / "final.fits")
                (folder / "restack.json").write_text(json.dumps({"summary": {"total_exposure_s": 256}}))

    def restacker(session, host):
        made.append(f"{session.parent.name} {session.name}")
        w = wcs[session.parent.name]
        fits.PrimaryHDU(sky_with_star(w, shape, w.pixel_to_world_values(45, 30), 40, rng)).writeto(session / "final.fits")
    answer = stitch.run("M31", say=lambda *_: None, solver=lambda lum, field: wcs[field], restacker=restacker)
    assert made == ["M31-P2 20261018-221000"] and answer["joined"] == 4
    assert (tmp_path / "mosaics" / "M31-mosaic.fits").exists() and (tmp_path / "web" / "M31-mosaic.jpg").exists()


def test_a_tilted_mosaic_gets_a_turned_grid_with_less_empty_corner():
    shape = (100, 300)
    tilted = []
    for k in range(3):
        w = panel_wcs(10.0 + k * 0.08, 41.0 + k * 0.06, shape)
        c, s_ = np.cos(np.radians(37)), np.sin(np.radians(37))
        w.wcs.cd = 1.32 / 3600 * np.array([[-c, s_], [s_, c]])
        tilted.append((w, shape))
    _, upright = stitch.grid(tilted)
    _, turned = stitch.grid(tilted, angle=37)
    assert turned[0] * turned[1] < 0.8 * upright[0] * upright[1]


def test_a_mosaic_with_no_plan_is_refused(tmp_path, monkeypatch):
    import mosaic
    import pytest
    monkeypatch.setattr(mosaic, "load", lambda name: None)
    with pytest.raises(interface.Refusal):
        stitch.fields("M101")


def test_a_session_with_a_colour_cast_is_matched_to_its_neighbour_in_the_overlap(monkeypatch):
    """18 October 2026: some panels came out purple beside the others."""
    rng = np.random.default_rng(3)
    shape = (120, 200)
    left = panel_wcs(10.0, 41.0, shape)
    right = panel_wcs(10.0 + 100 * 1.32 / 3600 / np.cos(np.radians(41)), 41.0, shape)
    star = left.pixel_to_world_values(60, 60)
    a = sky_with_star(left, shape, star, 50, rng)
    b = sky_with_star(right, shape, star, 50, rng)
    b[2] += 30 * np.linspace(0, 1, shape[1])[None, :]      # a blue cast growing across the second panel
    monkeypatch.setattr(stitch, "MATCH_FROM", 500)
    out_wcs, out_shape = stitch.grid([(left, shape), (right, shape)])
    joined, weights = stitch.blend([(a, left, 100.0), (b, right, 100.0)], out_wcs, out_shape, feather=10)
    x, y = out_wcs.world_to_pixel_values(*left.pixel_to_world_values(150, 60))
    overlap = joined[:, 40:80, int(x) - 10:int(x) + 10]
    assert abs(float(np.median(overlap[2] - overlap[0]))) < 4    # blue matches red where they meet
