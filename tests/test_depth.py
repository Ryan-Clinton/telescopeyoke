"""How faint a stack reaches: the zero point against a catalogue, the
5-sigma limit from empty sky, and planted stars found again. A star field
is made here with every star's magnitude known, so the answers can be
checked against the truth. Nothing here touches the network."""
import json
import math

import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS

import config
import depth
import interface
import stacking

ZP = 22.0           # the field's true zero point, for the whole of a star's light
FWHM = 4.0          # pixels
NOISE = 5.0         # per pixel
# The share of a round star's light inside an aperture as wide as the star:
# the zero point measured through it is fainter than ZP by this much.
INSIDE = 2.5 * math.log10(1 - math.exp(-4 * math.log(2)))


def render(shape, xy, flux, fwhm=FWHM):
    """Round stars of the given total flux."""
    s = fwhm / 2.355
    yy, xx = np.indices(shape, dtype=np.float32)
    image = np.zeros(shape, np.float32)
    for (x, y), f in zip(xy, flux):
        r = int(4 * s) + 2
        ix, iy = int(x), int(y)
        sl = (slice(max(iy - r, 0), iy + r + 1), slice(max(ix - r, 0), ix + r + 1))
        image[sl] += f / (2 * math.pi * s * s) * np.exp(
            -((xx[sl] - x) ** 2 + (yy[sl] - y) ** 2) / (2 * s * s))
    return image


def star_field(shape=(500, 700), count=220, seed=3, glow=None):
    """(image, wcs, catalogue): stars of known G, sky with grain, and the
    catalogue that names them."""
    rng = np.random.default_rng(seed)
    xy = rng.uniform((20, 20), (shape[1] - 20, shape[0] - 20), (count, 2))
    mags = rng.uniform(12.0, 18.5, count)
    image = 100 + render(shape, xy, 10 ** (-0.4 * (mags - ZP)))
    if glow is not None:
        image += glow
    image += rng.normal(0, NOISE, shape).astype(np.float32)
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [10.0, 41.0]
    w.wcs.crpix = [(shape[1] + 1) / 2, (shape[0] + 1) / 2]
    scale = 1.32 / 3600
    w.wcs.cd = np.array([[-scale, 0.0], [0.0, scale]])
    ra, dec = w.pixel_to_world_values(xy[:, 0], xy[:, 1])
    return image.astype(np.float32), w, np.column_stack([ra, dec, mags])


@pytest.fixture(scope="module")
def measured():
    image, wcs, catalogue = star_field()
    return depth.measure(image, wcs, catalogue, plant_stars=True, trials=3)


def test_the_zero_point_is_the_true_one_through_the_aperture(measured):
    assert measured["zeropoint"] == pytest.approx(ZP + INSIDE, abs=0.05)
    assert measured["calibration_stars"] >= 20


def test_the_5_sigma_limit_follows_from_the_grain_of_the_sky(measured):
    pixels = math.pi * measured["aperture_px"] ** 2
    expected = measured["zeropoint"] - 2.5 * math.log10(5 * NOISE * math.sqrt(pixels))
    assert measured["limit_5sigma"]["sky"] == pytest.approx(expected, abs=0.25)


def test_planted_stars_are_found_when_bright_and_missed_when_faint(measured):
    curve = {row["mag"]: row["share"] for row in measured["completeness"]["all"]["curve"]}
    assert curve[15.0] > 0.85 and curve[19.5] == 0.0
    # Where half are found agrees with the formula's limit.
    assert measured["completeness"]["all"]["mag_50"] == pytest.approx(
        measured["limit_5sigma"]["sky"], abs=0.6)


def test_each_figure_says_what_kind_of_figure_it_is(measured):
    assert measured["kinds"] == {"zeropoint": "measured", "limit_5sigma": "inferred",
                                 "completeness": "simulated"}


def test_a_shifted_plate_solve_still_matches_the_catalogue():
    image, wcs, catalogue = star_field()
    wcs.wcs.crpix = [wcs.wcs.crpix[0] + 4, wcs.wcs.crpix[1] - 3]
    found = depth.measure(image, wcs, catalogue)
    assert found["zeropoint"] == pytest.approx(ZP + INSIDE, abs=0.05)


def test_saturated_stars_are_left_out_of_the_zero_point():
    image, wcs, catalogue = star_field()
    np.minimum(image, 600, out=image)     # the brightest stars flatten off
    found = depth.measure(image, wcs, catalogue)
    assert found["zeropoint"] == pytest.approx(ZP + INSIDE, abs=0.08)


def test_a_field_with_no_catalogue_stars_is_refused():
    image, wcs, catalogue = star_field()
    with pytest.raises(interface.Refusal) as refused:
        depth.measure(image, wcs, catalogue[:0])
    assert refused.value.code_name == "PLATE_SOLVE_FAILED"


def test_a_blank_stack_is_refused():
    image = np.random.default_rng(1).normal(100, NOISE, (300, 400)).astype(np.float32)
    _, wcs, catalogue = star_field()
    with pytest.raises(interface.Refusal) as refused:
        depth.measure(image, wcs, catalogue)
    assert refused.value.code_name == "NO_STARS"


def test_a_galaxys_glow_is_told_apart_from_open_sky():
    shape = (500, 700)
    yy, xx = np.indices(shape)
    glow = 4000 * np.exp(-((xx - 350) ** 2 + (yy - 250) ** 2) / (2 * 60 ** 2))
    kinds = depth.regions(100 + glow, 100, ZP, 1.32)
    names = [name for name, _ in depth.REGIONS]
    assert names[kinds[250, 350]] == "core"
    assert names[kinds[10, 10]] == "sky"
    # Brightness falls away outwards through each kind in turn.
    along = [kinds[250, x] for x in range(350, 700, 5)]
    assert along == sorted(along, reverse=True)


def test_the_curve_is_read_from_the_faint_end_so_a_bright_dip_does_not_end_it():
    mags = (15.0, 15.5, 16.0, 16.5, 17.0, 17.5)
    share = (1.0, 0.85, 1.0, 0.95, 0.5, 0.0)
    assert depth.crossing(mags, share, 0.9) == pytest.approx(16.56, abs=0.01)
    assert depth.crossing(mags, share, 0.5) == 17.0
    assert depth.crossing(mags, (0.2,) * 6, 0.5) is None
    assert depth.crossing(mags, (1.0,) * 6, 0.9) == 17.5


def test_what_crowding_costs_is_taken_from_the_brightest_planted_stars():
    assert depth.plateau([0.9, 0.95, 0.85, 0.2, 0.0]) == pytest.approx(0.9)
    assert depth.plateau([None, None, None]) is None


def test_planted_stars_never_crowd_each_other():
    xy = depth.places((500, 700), 200, np.random.default_rng(2))
    gaps = np.hypot(*(xy[:, None, :] - xy[None, :, :]).transpose(2, 0, 1))
    np.fill_diagonal(gaps, np.inf)
    assert gaps.min() >= depth.SPACING


def test_a_planted_star_on_top_of_a_real_one_is_not_counted_as_found():
    before = np.array([[100.0, 100.0, 1, 4, 1]])
    after = np.array([[100.3, 100.2, 1, 4, 1], [300.0, 200.0, 1, 4, 1]])
    hit = depth.found_again(before, after, np.array([[100.5, 100.0], [300.2, 200.1], [50.0, 50.0]]))
    assert hit.tolist() == [False, True, False]


def test_vizier_answers_are_read_and_rows_with_no_magnitude_skipped():
    text = ("#comment\n\nRA_ICRS\tDE_ICRS\tGmag\ndeg\tdeg\tmag\n---\t---\t---\n"
            "010.1\t+41.2\t15.5\n010.2\t+41.3\t\n010.3\t+41.4\t17.25\n")
    rows = depth.read_tsv(text)
    assert rows.tolist() == [[10.1, 41.2, 15.5], [10.3, 41.4, 17.25]]


def test_gaia_is_asked_once_per_field(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA", tmp_path)
    asked = []

    class Reply:
        text = "RA_ICRS\tDE_ICRS\tGmag\ndeg\tdeg\tmag\n-\t-\t-\n10.0\t41.0\t14.0\n"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(depth.requests, "get", lambda *a, **k: asked.append(k) or Reply())
    assert depth.gaia(10.0, 41.0, 0.6).tolist() == [[10.0, 41.0, 14.0]]
    assert depth.gaia(10.0, 41.0, 0.6).tolist() == [[10.0, 41.0, 14.0]]
    assert len(asked) == 1


def test_a_session_with_no_stack_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA", tmp_path)
    session = tmp_path / "frames" / "M31" / "20261016-220000"
    session.mkdir(parents=True)
    (session / "light-0001.fits").touch()
    with pytest.raises(interface.Refusal) as refused:
        depth.find_stack("M31")
    assert refused.value.code_name == "NO_SESSION"
    assert depth.object_name(session / "final.fits") == "M31"
    assert depth.object_name(tmp_path / "frames" / "M31" / "combined" / "final.fits") == "M31"


def test_the_demo_does_not_pretend(monkeypatch):
    monkeypatch.setattr(config, "DEMO", True)
    with pytest.raises(interface.Refusal) as refused:
        depth.run(type("Args", (), {"target": "M31"})())
    assert refused.value.code_name == "DEMO_UNSUPPORTED"


def test_the_sweep_stacks_the_first_frames_onto_one_grid(tmp_path):
    """Three raw frames of one field, each a little shifted: stacks of one
    and of three frames come back the same size, lined up with the first."""
    rng = np.random.default_rng(5)
    half = (1100, 1100)
    xy = rng.uniform(40, 1060, (300, 2))
    flux = 10 ** rng.uniform(3, 4.5, 300)
    paths = []
    for n, (dx, dy) in enumerate([(0, 0), (3, -2), (-4, 1)]):
        lum = 200 + render(half, xy + (dx, dy), flux) + rng.normal(0, 3, half)
        # Each colour cell gets a quarter of the light.
        mosaic = np.repeat(np.repeat(lum / 4, 2, axis=0), 2, axis=1).astype(np.uint16)
        paths.append(stacking.save_light(tmp_path, n + 1, mosaic,
                                         fits.Header({"EXPTIME": 2.0, "GAIN": 100})))
    stacks = depth.sweep_stacks(paths, (2, 6), say=lambda *_: None)
    assert sorted(stacks) == [2, 6]
    (one, used_one), (three, used_three) = stacks[2], stacks[6]
    assert (used_one, used_three) == (2.0, 6.0) and one.shape == three.shape == half
    # The third frame's stars sit where the first's do.
    first = stacking.find_stars(one)[:20, :2]
    all_three = stacking.find_stars(three)[:20, :2]
    d = np.min(np.hypot(*(first[:, None] - all_three[None]).transpose(2, 0, 1)), axis=1)
    assert np.median(d) < 0.5


def test_depth_is_modelled_from_star_size_sky_and_time(tmp_path):
    """Measurements made to follow the model exactly give back its terms,
    and the prediction for new conditions follows."""
    truth = {"constant": 5.0, "time": 0.8, "fwhm": -2.5, "sky": 0.5}
    rows = []
    for seconds, width, sky in [(60, 6.0, 19.0), (300, 6.0, 19.0), (600, 5.0, 18.5), (3000, 7.0, 19.2)]:
        rows.append({"stack": "x", "seconds": seconds, "fwhm_arcsec": width, "sky": sky,
                     "mag_50": depth.predict(truth, width, sky, seconds)})
    model, rows = depth.fit(rows)
    assert model["constant"] == pytest.approx(5.0, abs=1e-3) and model["time"] == pytest.approx(0.8, abs=1e-3)
    assert model["scatter"] < 1e-3 and all(abs(r["off_by"]) < 0.01 for r in rows)
    # Sharper stars go deeper: half the width is 2.5 log10(2) = 0.75 mag.
    assert depth.predict(model, 3.0, 19.0, 300) - depth.predict(model, 6.0, 19.0, 300) == pytest.approx(0.753, abs=0.01)


def test_the_model_reads_every_kept_measurement_and_each_step_of_a_sweep(tmp_path):
    folder = tmp_path / "frames" / "M31" / "20261013-232632"
    folder.mkdir(parents=True)
    (folder / "depth.json").write_text(json.dumps({
        "stack": "s", "exposure_s": 3232.0, "fwhm_arcsec": 6.4, "sky_mag_per_arcsec2": 19.1,
        "completeness": {"all": {"mag_50": 17.6}},
        "sweep": [{"exposure_s": 64.0, "mag_50": {"all": 16.34}}, {"exposure_s": 608.0, "mag_50": {"all": None}}]}))
    rows = depth.measurements(tmp_path / "frames")
    assert [(r["seconds"], r["mag_50"]) for r in rows] == [(3232.0, 17.6), (64.0, 16.34)]


def test_too_few_measurements_are_refused():
    with pytest.raises(interface.Refusal) as refused:
        depth.fit([{"stack": "x", "seconds": 60, "fwhm_arcsec": 6, "sky": 19, "mag_50": 16}])
    assert refused.value.code_name == "INVALID_REQUEST"


def test_each_stack_keeps_its_own_record():
    assert depth.record_path("frames/M31/x/final.fits").name == "depth.json"
    assert depth.record_path("frames/M31/x/discovery.fits").name == "discovery-depth.json"
