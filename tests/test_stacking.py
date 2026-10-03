"""The imaging pipeline, on made-up star fields where the right answer is known."""
import json

import numpy as np
import pytest
from scipy import ndimage

import calibrate
import camera_test
import restack
import shoot
import stacking

SHAPE = (1100, 1300)   # half-size frame; big enough for the 1024 line-up square


def field(count=120, seed=1):
    rng = np.random.default_rng(seed)
    xy = np.column_stack([rng.uniform(40, SHAPE[1] - 40, count), rng.uniform(40, SHAPE[0] - 40, count)])
    return xy, rng.uniform(2e4, 2e5, count)


def render(xy, flux, sigma=1.6, stretch_x=1.0, sky=300.0, noise=4.0, seed=0):
    """A brightness image with a Gaussian star at each (x, y)."""
    image = np.zeros(SHAPE, np.float32)
    reach = int(6 * sigma * max(stretch_x, 1))
    for (x, y), f in zip(xy, flux):
        x0, y0 = int(round(x)), int(round(y))
        if not (reach < x0 < SHAPE[1] - reach and reach < y0 < SHAPE[0] - reach):
            continue
        yy, xx = np.mgrid[y0 - reach:y0 + reach + 1, x0 - reach:x0 + reach + 1]
        spot = np.exp(-((xx - x) ** 2 / (2 * (sigma * stretch_x) ** 2) + (yy - y) ** 2 / (2 * sigma ** 2)))
        image[y0 - reach:y0 + reach + 1, x0 - reach:x0 + reach + 1] += f * spot / spot.sum()
    return image + sky + np.random.default_rng(seed).normal(0, noise, SHAPE).astype(np.float32)


def moved(xy, dx, dy, degrees=0.0):
    """Star positions after rotating about the frame centre and shifting."""
    a = np.radians(degrees)
    centre = np.array([SHAPE[1] / 2, SHAPE[0] / 2])
    rotation = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
    return (xy - centre) @ rotation.T + centre + [dx, dy]


def as_rgb(lum):
    return np.dstack([lum / 3] * 3).astype(np.float32)


def as_mosaic(lum):
    """A raw Bayer frame whose 2x2 cells all hold a quarter of the brightness."""
    return np.repeat(np.repeat(lum / 4, 2, axis=0), 2, axis=1).astype(np.uint16)


def reference_for(lum):
    return {"square": stacking.centre_square(lum), "stars": stacking.find_stars(lum)}


def test_stars_are_found_where_they_are():
    xy, flux = field(40)
    stars = stacking.find_stars(render(xy, flux))
    assert len(stars) >= 35
    brightest = xy[np.argmax(flux)]
    assert np.hypot(*(stars[0, :2] - brightest)) < 0.3


def test_blurred_stars_measure_wider_and_trailed_stars_less_round():
    xy, flux = field(60)
    sharp = stacking.quality(*(lambda l: (l, stacking.find_stars(l)))(render(xy, flux, sigma=1.5)))
    soft = stacking.quality(*(lambda l: (l, stacking.find_stars(l)))(render(xy, flux, sigma=3.0)))
    trailed = stacking.quality(*(lambda l: (l, stacking.find_stars(l)))(render(xy, flux, stretch_x=2.5)))
    assert soft["fwhm"] > 1.4 * sharp["fwhm"]
    assert sharp["roundness"] > 0.9
    assert trailed["roundness"] < 0.6


def test_the_rough_line_up_is_good_to_a_fraction_of_a_pixel():
    xy, flux = field()
    reference = stacking.centre_square(render(xy, flux))
    for dx, dy in ((3.4, -7.3), (-12.6, 20.2)):
        got = stacking.offset(reference, stacking.centre_square(render(moved(xy, dx, dy), flux, seed=5)))
        # The shift to apply is the opposite of how far the frame moved.
        assert got == pytest.approx((-dy, -dx), abs=0.35)


def test_the_sensors_fixed_pattern_does_not_fool_the_line_up():
    xy, flux = field()
    pattern = np.random.default_rng(9).normal(0, 8, SHAPE)   # same in every frame
    reference = stacking.centre_square(render(xy, flux) + pattern)
    got = stacking.offset(reference, stacking.centre_square(render(moved(xy, 12, -7), flux) + pattern))
    assert got == pytest.approx((7, -12), abs=0.4)


def test_shift_and_rotation_are_recovered_from_the_stars():
    xy, flux = field()
    reference = reference_for(render(xy, flux))
    lum = render(moved(xy, 5.3, -8.6, degrees=0.4), flux, seed=3)
    rough = stacking.offset(reference["square"], stacking.centre_square(lum))
    r, t, matched = stacking.align(stacking.find_stars(lum), reference["stars"], rough)
    assert matched >= 40
    assert np.degrees(np.arctan2(r[1, 0], r[0, 0])) == pytest.approx(-0.4, abs=0.03)


def test_registered_stars_land_on_the_reference_stars():
    xy, flux = field()
    reference = reference_for(render(xy, flux))
    lum = render(moved(xy, 5.3, -8.6, degrees=0.4), flux, seed=3)
    registered, info = stacking.register(as_rgb(lum), lum, stacking.find_stars(lum), reference)
    assert info["matched"] >= 40 and info["rotation"] == pytest.approx(-0.4, abs=0.03)
    after = stacking.find_stars(np.nan_to_num(registered.sum(axis=2), nan=300.0))
    from scipy.spatial import cKDTree
    distance, _ = cKDTree(reference["stars"][:, :2]).query(after[:40, :2])
    assert np.median(distance) < 0.15


def test_too_few_stars_falls_back_to_the_rough_shift():
    stars = np.array([[10.0, 10.0, 1, 3, 1]], np.float32)
    r, t, matched = stacking.align(stars, stars, (2.5, -4.0))
    assert matched == 0 and np.allclose(r, np.eye(2)) and np.allclose(t, [-4.0, 2.5])


def test_a_satellite_trail_in_one_frame_is_left_out_of_the_stack():
    xy, flux = field(60)
    stack = stacking.Stack((*SHAPE, 3))
    for i in range(12):
        frame = as_rgb(render(xy, flux, seed=i))
        if i == 9:
            frame[500, :, :] += 3000   # a bright streak right across
        stack.add(frame)
    result = stack.result()
    assert abs(float(np.median(result[500])) - float(np.median(result[520]))) < 5


def test_the_empty_edges_of_a_shifted_frame_do_not_dilute_the_stack():
    stack = stacking.Stack((4, 4, 3))
    full = np.full((4, 4, 3), 100, np.float32)
    part = full.copy()
    part[:, :2] = np.nan
    stack.add(full)
    stack.add(part)
    assert np.allclose(stack.result(), 100)


def good(**changes):
    return dict({"fwhm": 4.0, "roundness": 0.9, "stars": 100, "flux": 5e4, "background": 300,
                 "noise": 5.0}, **changes)


def test_frames_spoiled_by_cloud_wind_or_light_are_rejected():
    accepted = [good() for _ in range(5)]
    assert stacking.judge(good(), accepted) == (True, "")
    assert "stars down 60% (cloud)" == stacking.judge(good(stars=40), accepted)[1]
    assert "star brightness down 50% (cloud)" == stacking.judge(good(flux=2.5e4), accepted)[1]
    assert "bloated" in stacking.judge(good(fwhm=7.5), accepted)[1]
    assert "trailed" in stacking.judge(good(roundness=0.55), accepted)[1]
    assert "sky brightened" in stacking.judge(good(background=520), accepted)[1]
    assert not stacking.judge(good(stars=3), [])[0]


def test_sharper_cleaner_frames_weigh_more():
    best = good(fwhm=3.0)
    assert stacking.weight(best, best) == 1.0
    assert stacking.weight(good(fwhm=4.0), best) == pytest.approx(0.5625)
    assert stacking.weight(good(fwhm=9.0), best) == 0.25   # never ignored entirely


def test_calibration_is_raw_minus_dark_over_flat(tmp_path, monkeypatch):
    monkeypatch.setattr(stacking, "CALIBRATION", tmp_path)
    calibrate.save(stacking.master_path("dark", 2, 1500), np.full((4, 4), 100.0))
    calibrate.save(stacking.master_path("flat"), np.full((4, 4), 0.5))
    calibration = stacking.Calibration(2, 1500)
    assert calibration.describe() == "dark, flat"
    assert np.allclose(calibration.apply(np.full((4, 4), 300, np.uint16)), 400)
    # A different exposure has no matching dark, so only the flat applies.
    assert np.allclose(stacking.Calibration(5, 1500).apply(np.full((4, 4), 300, np.uint16)), 600)


def test_with_no_calibration_frames_the_raw_frame_passes_through(tmp_path, monkeypatch):
    monkeypatch.setattr(stacking, "CALIBRATION", tmp_path)
    calibration = stacking.Calibration(2, 1500)
    assert calibration.describe().startswith("none")
    assert np.allclose(calibration.apply(np.full((4, 4), 300, np.uint16)), 300)


def test_master_frames_are_medians_and_flats_average_one_per_colour():
    frames = [np.full((600, 8), v, np.uint16) for v in (10, 12, 500)]   # one outlier
    assert np.allclose(calibrate.median_stack(frames), 12)
    flat = np.ones((4, 4), np.float32)
    flat[0::2, 0::2], flat[1::2, 1::2] = 2000, 500   # red brighter, blue dimmer
    flat[0::2, 1::2] = flat[1::2, 0::2] = 1000
    assert np.allclose(calibrate.normalise_flat(flat), 1)


def test_the_longest_exposure_with_round_stars_is_chosen():
    trials = [(1, good(fwhm=3.8, roundness=0.96)), (2, good(fwhm=4.0, roundness=0.94)),
              (3, good(fwhm=4.6, roundness=0.84)), (4, good(fwhm=6.4, roundness=0.61))]
    assert stacking.choose_exposure(trials) == 3
    trials[2] = (3, good(fwhm=4.6, roundness=0.70))
    assert stacking.choose_exposure(trials) == 2
    assert stacking.choose_exposure([(1, good(stars=0))]) is None


def test_the_gain_with_most_stars_and_few_burnt_pixels_is_suggested():
    results = [(300, dict(good(stars=40), burnt=0.0)), (1500, dict(good(stars=90), burnt=0.0001)),
               (3000, dict(good(stars=120), burnt=0.01))]
    assert camera_test.recommend(results) == 1500
    assert camera_test.recommend([(300, dict(good(stars=0), burnt=0.0))]) is None


def test_raw_frames_survive_being_saved_and_loaded(tmp_path):
    mosaic = np.random.default_rng(2).integers(0, 4095, (64, 96)).astype(np.uint16)
    path = stacking.save_light(tmp_path, 7, mosaic, {"EXPTIME": 2.0, "GAIN": 1500.0, "OTHER": 1})
    assert path.name == "light-0007.fits"
    loaded, header = stacking.load_light(path)
    assert np.array_equal(loaded, mosaic) and header["EXPTIME"] == 2.0


@pytest.fixture(scope="module")
def session(tmp_path_factory):
    """A made-up run: ten drifting frames, one of them under thin cloud.
    Built once and shared, since it takes a few seconds."""
    tmp_path = tmp_path_factory.mktemp("run")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(shoot, "ROOT", tmp_path)
        patch.setattr(shoot, "WEB", tmp_path / "web")
        patch.setattr(restack, "ROOT", tmp_path)
        patch.setattr(stacking, "CALIBRATION", tmp_path / "calibration")
        xy, flux = field()
        run = shoot.Session("Test", exposure=2.0, gain=1500)
        lines = []
        for i in range(10):
            cloudy = i == 6
            lum = render(moved(xy, 1.7 * i, -0.9 * i, degrees=0.02 * i),
                         flux * (0.3 if cloudy else 1), seed=i)
            lines.append(run.process(i + 1, as_mosaic(lum), {"EXPTIME": 2.0, "GAIN": 1500.0}))
        run.finish()
        yield run, lines


def test_a_run_keeps_raw_frames_logs_each_one_and_rejects_the_cloudy_one(session):
    run, lines = session
    assert len(list(run.folder.glob("light-*.fits"))) == 10
    assert sum("ACCEPT" in line for line in lines) == 9
    assert "007 REJECT" in lines[6] and "cloud" in lines[6]
    log = json.loads((run.folder / "frames.json").read_text())
    assert [entry["accepted"] for entry in log].count(False) == 1
    assert (run.folder / "live.fits").exists()
    assert run.drift > 0


def test_the_stack_is_sharper_than_stacking_without_lining_up(session):
    run, _ = session
    stacked = stacking.quality(*(lambda l: (l, stacking.find_stars(l)))(run.stack.result().sum(axis=2)))
    assert stacked["roundness"] > 0.85 and stacked["fwhm"] < 5.5


def test_the_quality_pass_rebuilds_the_picture_from_the_raw_frames(session):
    run, _ = session
    picture = restack.run(run.folder, say=lambda *_: None)
    assert picture.exists() and (run.folder / "final.fits").exists()
    summary = json.loads((run.folder / "restack.json").read_text())
    assert "light-0007.fits" not in summary["kept"]
    assert 6 <= len(summary["kept"]) <= 9
    assert not (run.folder / "registered").exists()   # working files tidied away
