"""Variable stars: in a made-up night of batches, under haze that comes and
goes, the one star that really varies is listed, a known variable that is
flat here is listed as such, a crowded star is left out, and the steady
ones are not. Nothing here touches the network."""
import numpy as np
import pytest
from astropy.io import fits

import variables
from test_depth import render, star_field

SHAPE = (500, 700)
ZP = 22.0
BATCHES = 12


def session_with_frames(folder, frames):
    folder.mkdir(parents=True)
    for i in range(frames):
        head = fits.Header({"DATE-OBS": f"2026-10-14T01:{i // 2:02d}:{(i % 2) * 30:02d}", "EXPTIME": 16.0})
        fits.HDUList([fits.PrimaryHDU(), fits.ImageHDU(np.zeros((2, 2), np.uint16), head)]).writeto(
            folder / f"light-{i + 1:04d}.fits")
    return folder


def made_up_night(seed=3):
    """Batches of one field: every star steady but one, which swings by
    0.4 mag; each batch dimmed by haze of its own."""
    _, wcs, catalogue = star_field(SHAPE, count=150, seed=seed)
    rng = np.random.default_rng(seed)
    catalogue = catalogue[(catalogue[:, 2] >= 11.0) & (catalogue[:, 2] <= 15.5)]
    xy = np.column_stack(wcs.world_to_pixel_values(catalogue[:, 0], catalogue[:, 1]))
    inside = ((xy[:, 0] > 70) & (xy[:, 1] > 70) & (xy[:, 0] < SHAPE[1] - 70) & (xy[:, 1] < SHAPE[0] - 70))
    catalogue, xy = catalogue[inside], xy[inside]
    swinger = int(np.argmin(np.abs(catalogue[:, 2] - 13.0)))
    images = []
    for b in range(BATCHES):
        mags = catalogue[:, 2].copy()
        mags[swinger] += 0.4 * np.sin(2 * np.pi * b / 6)
        haze = 10 ** (-0.4 * rng.uniform(0, 0.5))
        image = 100 + render(SHAPE, xy, haze * 10 ** (-0.4 * (mags - ZP)))
        images.append((image + rng.normal(0, 3.0, SHAPE)).astype(np.float32))
    colour = np.full((len(catalogue), 1), 0.9)
    return images, wcs, np.hstack([catalogue, colour]), swinger


def test_batches_leave_out_a_short_last_one():
    assert [len(b) for b in variables.batches(list(range(25)), 10)] == [10, 10, 5]
    assert [len(b) for b in variables.batches(list(range(24)), 10)] == [10, 10]


def test_each_batch_is_put_on_gaias_scale_so_haze_cancels():
    g = np.array([12.0, 13.0, 14.0])
    flux = 10 ** (-0.4 * (g - 22.0))
    mags = variables.on_gaia([flux, flux * 0.5], g)
    assert mags == pytest.approx(np.array([g, g]), abs=1e-6)


def test_a_star_sharing_its_light_with_a_neighbour_is_left_out():
    _, wcs, _ = star_field(SHAPE, count=10)
    ra, dec = wcs.pixel_to_world_values([300, 305, 500], [250, 250, 300])
    stars = np.column_stack([ra, dec, [13.0, 14.0, 13.5]])            # the first two 6.6" apart
    kept, xy = variables.chosen(stars, wcs, SHAPE)
    assert kept[:, 2].tolist() == [13.5] and xy[0] == pytest.approx([500, 300], abs=0.01)


def test_the_varying_star_is_found_and_a_flat_known_one_is_named(tmp_path):
    images, wcs, catalogue, swinger = made_up_night()
    session = session_with_frames(tmp_path / "M31" / "20261014-021118", BATCHES * 10)
    night = variables.night(session, "M31", 10, say=lambda *_: None, stack=lambda groups: images,
                            solve=lambda lum: wcs, gaia=lambda ra, dec, r: catalogue)
    assert len(night["jd"]) == BATCHES and night["mags"].shape[0] == BATCHES
    assert len(night["stars"]) >= 20
    steady = next(row for row in night["stars"] if abs(row[0] - catalogue[swinger, 0]) > 1e-6)
    known = [{"name": "V1 And", "ra": steady[0], "dec": steady[1], "type": "EA"}]
    listed = variables.judge(variables.gather([night]), known)
    loud = [s for s in listed if s["variable"]]
    assert len(loud) == 1
    assert (loud[0]["ra"], loud[0]["dec"]) == pytest.approx((catalogue[swinger, 0], catalogue[swinger, 1]), abs=1e-5)
    assert loud[0]["range"] > 0.5 and loud[0]["vsx"] is None
    flat = [s for s in listed if s["vsx"]]
    assert flat[0]["vsx"]["name"] == "V1 And" and not flat[0]["variable"]
    path = variables.draw(loud[0], tmp_path / "curve.png")
    assert (tmp_path / "curve.png").stat().st_size > 0 and path.endswith("curve.png")
