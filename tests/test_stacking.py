"""The imaging pipeline, on made-up star fields where the right answer is known."""
import config
import json

import numpy as np
import pytest

import calibrate
import camera_test
import depth
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
    r, t, matched, residual = stacking.align(stacking.find_stars(lum), reference["stars"], rough)
    assert matched >= 40 and residual < 0.2
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
    r, t, matched, residual = stacking.align(stars, stars, (2.5, -4.0))
    assert matched == 0 and residual is None
    assert np.allclose(r, np.eye(2)) and np.allclose(t, [-4.0, 2.5])


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


def test_edges_that_only_some_frames_reached_are_trimmed():
    stack = stacking.Stack((100, 120, 3))
    full = np.full((100, 120, 3), 100, np.float32)
    for i in range(10):
        part = full.copy()
        if i < 4:                   # a second session framed lower and to the left
            part[:8] = np.nan
            part[:, -5:] = np.nan
        stack.add(part)
    rows, cols = stack.covered()
    assert (rows.start, rows.stop, cols.start, cols.stop) == (8, 100, 0, 115)


def test_the_trim_never_takes_more_than_a_little_of_a_side():
    stack = stacking.Stack((100, 100, 3))
    full = np.full((100, 100, 3), 100, np.float32)
    half = full.copy()
    half[50:] = np.nan
    stack.add(full)
    stack.add(half)
    rows, cols = stack.covered()
    assert (rows.start, rows.stop) == (0, 85) and (cols.start, cols.stop) == (0, 100)


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


def test_sharper_rounder_clearer_cleaner_frames_weigh_more():
    best = good(fwhm=3.0)
    assert stacking.weight(best, best) == 1.0
    assert stacking.weight(good(fwhm=4.0), best) == pytest.approx(0.5625)
    assert stacking.weight(good(fwhm=3.0, flux=4e4), best) == pytest.approx(0.8)      # hazier
    assert stacking.weight(good(fwhm=3.0, roundness=0.72), best) == pytest.approx(0.8)  # trailed
    assert stacking.weight(good(fwhm=9.0), best) == 0.25   # never ignored entirely


def test_a_half_cloudy_session_is_judged_against_its_good_half():
    clear = [dict(good(), file=f"clear-{i}") for i in range(10)]
    hazy = [dict(good(flux=2.6e4, stars=80), file=f"hazy-{i}") for i in range(10)]
    # Against the session's own average, the hazy frames would look normal.
    assert stacking.judge(hazy[0], clear + hazy)[0]
    kept = restack.select(clear + hazy, keep=1.0)
    assert {f["file"] for f in kept} == {f["file"] for f in clear}


def test_two_stars_are_never_matched_to_the_same_reference_star():
    reference = np.array([[100.0, 100.0], [200.0, 100.0], [300.0, 100.0]])
    crowded = np.array([[100.4, 100.0], [101.2, 100.0], [200.3, 100.0]])   # two near the first
    mine, theirs = stacking.pair_up(crowded, reference, 4.0)
    assert list(mine) == [0, 2] and list(theirs) == [0, 1]


def test_a_wrongly_matched_star_does_not_bend_the_alignment():
    xy, flux = field(60)
    reference = np.column_stack([xy, flux, np.full(60, 4.0), np.ones(60)]).astype(np.float32)
    frame = reference.copy()
    frame[:, :2] = moved(xy, 2.0, -1.0, degrees=0.3)
    frame[0, :2] += [1.5, 1.5]   # one star in the wrong place, still within matching range
    r, t, matched, residual = stacking.align(frame, reference, (1.0, -2.0))
    assert matched == 59 and residual < 0.01
    assert np.degrees(np.arctan2(r[1, 0], r[0, 0])) == pytest.approx(-0.3, abs=0.005)


def test_flats_are_filed_by_camera_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(stacking, "CALIBRATION", tmp_path)
    assert stacking.master_path("flat").name == "flat-default.fits"
    monkeypatch.setattr(stacking, "setup_name", lambda: "rotated-90")
    assert stacking.master_path("flat").name == "flat-rotated-90.fits"
    calibrate.save(stacking.master_path("flat"), np.full((4, 4), 0.5))
    assert stacking.Calibration(2, 1500).flat is not None
    monkeypatch.setattr(stacking, "setup_name", lambda: "refitted")
    assert stacking.Calibration(2, 1500).flat is None   # the old flat no longer applies


def test_the_dark_is_scaled_to_a_warmer_sensor(tmp_path, monkeypatch):
    monkeypatch.setattr(stacking, "CALIBRATION", tmp_path)
    rng = np.random.default_rng(4)
    bias = np.full((400, 400), 100.0, np.float32)
    current = np.zeros((400, 400), np.float32)
    hot = rng.choice(160000, 400, replace=False)
    current.ravel()[hot] = rng.uniform(200, 900, 400)      # hot pixels
    calibrate.save(stacking.master_path("bias", gain=1500), bias)
    calibrate.save(stacking.master_path("dark", 2, 1500), bias + current)
    calibration = stacking.Calibration(2, 1500)
    # Tonight the sensor is warmer: the hot pixels are 1.6 times as strong.
    light = (bias + 1.6 * current + 300).astype(np.uint16)
    cleaned = calibration.apply(light)
    assert calibration.scale == pytest.approx(1.6, abs=0.02)
    assert abs(float(cleaned.ravel()[hot].mean()) - 300) < 2    # hot pixels gone
    assert np.median(cleaned) == pytest.approx(300, abs=1)


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


def test_master_frames_average_with_outliers_left_out():
    rng = np.random.default_rng(6)
    frames = [(1000 + rng.normal(0, 10, (600, 8))).astype(np.float32) for _ in range(20)]
    frames[7][100, 3] = 4000    # a cosmic ray in one frame
    result = calibrate.master(frames)
    assert result[100, 3] == pytest.approx(1000, abs=10)
    # Averaging the survivors is steadier than a plain median.
    plain = np.median(frames, axis=0)
    assert result.std() < plain.std()


def test_flats_average_one_per_colour():
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


def test_longer_frames_are_not_held_to_the_shortest_frames_frozen_seeing():
    # 13 October 2026: round stars to 16 s, a little wider at each length.
    trials = [(s, good(fwhm=w, roundness=0.87)) for s, w in
              ((2, 2.87), (4, 3.43), (8, 3.77), (16, 4.17))]
    assert stacking.choose_exposure(trials) == 16
    trials.append((30, good(fwhm=4.5, roundness=0.62)))     # trailing at last
    assert stacking.choose_exposure(trials) == 16


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
        patch.setattr(config, "DATA", tmp_path)
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
    log = json.loads((run.folder / "frames.json").read_text(encoding="utf-8"))
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
    summary = json.loads((run.folder / "restack.json").read_text(encoding="utf-8"))
    assert "light-0007.fits" not in summary["kept"]
    assert 6 <= len(summary["kept"]) <= 9
    assert not (run.folder / "registered").exists()   # working files tidied away


def test_the_discovery_stack_is_written_beside_the_picture_and_leaves_it_alone(session):
    run, _ = session
    restack.run(run.folder, say=lambda *_: None)
    before = (run.folder / "final.fits").read_bytes(), (run.folder / "restack.json").read_text(encoding="utf-8")
    said = []
    made = restack.run(run.folder, say=said.append, discovery=True)
    assert made == run.folder / "discovery.fits" and made.exists()
    after = (run.folder / "final.fits").read_bytes(), (run.folder / "restack.json").read_text(encoding="utf-8")
    assert after == before
    summary = json.loads((run.folder / "discovery.json").read_text(encoding="utf-8"))["summary"]
    assert summary["picture"] is None and summary["stack"].endswith("discovery.fits")
    assert any("discovery stack:" in line for line in said)
    # The cloudy frame failed the checks and is in neither stack.
    assert "light-0007.fits" not in json.loads((run.folder / "discovery.json").read_text(encoding="utf-8"))["kept"]


def frame(fwhm=4.0, noise=10.0, flux=1000.0):
    return {"fwhm": fwhm, "noise": noise, "flux": flux}


def test_frames_of_one_quality_count_the_same_in_the_discovery_stack():
    assert stacking.point_weights([frame() for _ in range(5)]) == [1.0] * 5


def test_for_faint_stars_a_soft_or_grainy_frame_counts_for_less():
    sharp, soft, grainy, dim = stacking.point_weights(
        [frame(), frame(fwhm=5.0), frame(noise=12.0), frame(flux=800.0)] + [frame()] * 8)[:4]
    assert sharp == 1.0
    assert soft == pytest.approx((4 / 5) ** 2, abs=0.01)
    assert grainy == pytest.approx((10 / 12) ** 2, abs=0.01)
    assert dim == pytest.approx(0.8, abs=0.01)


def test_frames_that_would_lower_a_faint_stars_signal_to_noise_are_left_out():
    good = [frame() for _ in range(10)]
    # Hazy, bright-skied and soft: worth so little that the wider stars
    # they bring cost more than their light gives.
    poor = [frame(fwhm=9.0, noise=25.0, flux=400.0) for _ in range(3)]
    weights = stacking.point_weights(good + poor)
    assert all(w == 1.0 for w in weights[:10]) and all(w == 0.0 for w in weights[10:])


def test_the_web_page_can_be_told_how_far_a_run_has_got(session):
    run, _ = session
    status = stacking.run_status(run.folder)
    assert status["name"] == "Test" and status["exposure"] == 2.0
    assert (status["captured"], status["accepted"], status["rejected"]) == (10, 9, 1)
    assert status["reasons"] == {"star brightness down (cloud)": 1}
    assert status["last"].startswith("accepted, FWHM")
    assert status["finished"]


def saved_session(folder, name, exposure, turned=0.0, count=6, seed=0):
    """Raw frames of the same field, as shoot.py leaves them. A longer
    exposure collects proportionally more light from stars and sky alike."""
    session = folder / "frames" / "Test" / name
    session.mkdir(parents=True)
    xy, flux = field()
    for i in range(count):
        lum = render(moved(xy, 1.5 * i + seed, -1.0 * i, degrees=turned), flux * exposure / 2,
                     sky=150.0 * exposure, seed=seed + i)
        stacking.save_light(session, i + 1, as_mosaic(lum), {"EXPTIME": exposure, "GAIN": 1500.0})
    return session


def test_sessions_of_different_lengths_combine_into_one_picture(tmp_path, monkeypatch):
    monkeypatch.setattr(restack, "ROOT", tmp_path)
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(stacking, "CALIBRATION", tmp_path / "calibration")
    first = saved_session(tmp_path, "20261003-230000", exposure=2.0)
    second = saved_session(tmp_path, "20261004-010000", exposure=4.0, seed=40)
    turned = saved_session(tmp_path, "20261005-220000", exposure=2.0, turned=25.0, seed=80)
    # After the mount swings over the pole the same field arrives upside down.
    flipped = saved_session(tmp_path, "20261004-030000", exposure=2.0, turned=180.0, seed=120)
    assert restack.all_sessions("Test") == [first, second, flipped, turned]

    said = []
    picture = restack.run([first, second, flipped, turned], keep=1.0, say=said.append, workers=2)
    assert picture == tmp_path / "frames" / "Test" / "combined" / "final.jpg" and picture.exists()
    summary = json.loads((picture.parent / "restack.json").read_text(encoding="utf-8"))
    kept = summary["kept"]
    # Both nights with the camera as it was are in; the night it was turned is not.
    assert sum(k.startswith("20261003") for k in kept) == 6
    assert sum(k.startswith("20261004-01") for k in kept) == 6
    assert sum(k.startswith("20261004-03") for k in kept) == 6
    assert any("turned the right way up" in line for line in said)
    assert not any(k.startswith("20261005") for k in kept)
    assert any("would not line up" in line for line in said)
    assert summary["summary"]["total_exposure_s"] == 6 * 2.0 + 6 * 4.0 + 6 * 2.0
    # The 4 s frames were scaled to match the 2 s ones, so the stars are not doubled up or smeared.
    from astropy.io import fits
    lum = fits.getdata(picture.parent / "final.fits").astype(np.float32).sum(axis=0)
    q = stacking.quality(lum, stacking.find_stars(lum))
    assert q["roundness"] > 0.85 and q["fwhm"] < 5.5
    # The combined folder is not mistaken for a session, and one session alone still works.
    assert restack.all_sessions("Test") == [first, second, flipped, turned]
    assert restack.find_session("Test") == turned


def test_sessions_at_different_gains_are_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(stacking, "CALIBRATION", tmp_path / "calibration")
    one = saved_session(tmp_path, "a", exposure=2.0, count=1)
    other = tmp_path / "frames" / "Test" / "b"
    other.mkdir()
    stacking.save_light(other, 1, as_mosaic(render(*field())), {"EXPTIME": 2.0, "GAIN": 300.0})
    with pytest.raises(SystemExit, match="different gains"):
        restack.run([one, other], say=lambda *_: None)


def test_a_field_that_has_turned_a_few_degrees_is_still_lined_up():
    """With the polar axis well out the field turns over an hour; the stars
    far from the centre move too far for a plain shift to pair them."""
    xy, flux = field()
    reference = render(xy, flux)
    later = render(moved(xy, 14.0, -9.0, degrees=4.0), flux, seed=5)
    stars, reference_stars = stacking.find_stars(later), stacking.find_stars(reference)
    rough = stacking.offset(stacking.centre_square(reference), stacking.centre_square(later))
    plain = stacking.align(stars, reference_stars, rough)
    centre = (SHAPE[1] / 2, SHAPE[0] / 2)
    r, t, matched, residual = stacking.align(stars, reference_stars, rough, centre)
    assert matched > 60 and matched > 2 * plain[2] and residual < 0.3
    assert np.degrees(np.arctan2(r[1, 0], r[0, 0])) == pytest.approx(-4.0, abs=0.05)


def test_a_frame_that_has_drifted_past_the_rough_line_up_is_still_matched():
    """The rough line-up sees no further than half its 1024-pixel square. A
    live frame that had drifted further used to match no stars and go into
    the stack out of place, with the drift under-read."""
    xy, flux = field()
    reference = reference_for(render(xy, flux))
    lum = render(moved(xy, -600.0, 30.0), flux, seed=3)
    _, info = stacking.register(as_rgb(lum), lum, stacking.find_stars(lum), reference)
    assert info["matched"] >= 15
    assert info["shift"] == pytest.approx([600.0, -30.0], abs=0.5)


def test_the_picture_is_framed_where_most_frames_sat_not_where_the_sharpest_did():
    xy, _ = field(40)
    sharpest = xy + [300.0, -200.0]                    # the one frame that had drifted
    others = [xy + [dx, 0.0] for dx in (-4.0, 0.0, 3.0, 5.0)]
    middle = stacking.framing(others + [sharpest], sharpest)
    assert middle == pytest.approx([-300.0, 200.0], abs=4.1)
    # Frames all in one place leave the picture where it is, and stars that
    # agree on nothing say nothing.
    assert stacking.framing([xy, xy, xy], xy) is None
    assert stacking.apart(xy[:3], xy) is None
    assert stacking.apart(xy + [50.0, 7.0], xy) == pytest.approx([-50.0, -7.0])


def test_cloud_stopping_a_run_leaves_the_live_view_running(monkeypatch, tmp_path):
    """The run starts the live view as it goes, and the live view does not
    take that run's last frame for a run it must give way to."""
    import liveview
    started = []
    monkeypatch.setattr(shoot.subprocess, "Popen", lambda command, **options: started.append((command, options)))
    shoot.watch_on()
    command, options = started[0]
    assert command[1].endswith("liveview.py") and "--after-run" in command
    assert options["stdout"] == shoot.subprocess.DEVNULL       # nothing left holding the run's output open

    monkeypatch.setattr(liveview.config, "DATA", tmp_path)
    log = tmp_path / "frames" / "M31" / "20261006-214958" / "frames.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text("{}\n", encoding="utf-8")
    assert liveview.run_active()                                 # a frame just logged: a run is going
    assert not liveview.run_active(since=log.stat().st_mtime + 1)   # ...but it was before this live view began


def test_an_object_that_fills_the_frame_keeps_its_glow_and_its_colour():
    """With only a level taken off the sky, a broad glow across the whole
    frame is still there afterwards, white stars leave it and the sky without
    a tint though the sensor sees far more green, and a small object is
    finished as before."""
    import process
    rows, cols = 700, 900
    rng = np.random.default_rng(4)
    yy, xx = np.mgrid[0:rows, 0:cols]
    glow = 400 * np.exp(-(((xx - 450) / 500) ** 2 + ((yy - 350) / 260) ** 2))
    stars = np.zeros((rows, cols))
    for x, y in zip(rng.integers(20, cols - 20, 400), rng.integers(20, rows - 20, 400)):
        stars[y - 1:y + 2, x - 1:x + 2] += 3000
    seen = np.array([0.6, 1.5, 0.8])                      # how strongly the sensor answers in each colour
    rgb = ((glow + stars + 200)[..., None] * seen + rng.normal(0, 3, (rows, cols, 3))).astype(np.float32)

    kept = process.process(rgb, background=0).astype(float)
    bowl = process.process(rgb, background=2).astype(float)
    middle, corner = (slice(300, 400), slice(400, 500)), (slice(0, 60), slice(0, 60))
    assert kept[middle].mean() > bowl[middle].mean() + 20          # the bowl took the glow for sky
    assert kept[middle].mean() > kept[corner].mean() + 40          # brighter in the middle, as it is
    for part in (middle, corner):
        colour = kept[part].reshape(-1, 3).mean(axis=0)
        assert colour.max() - colour.min() < 6                     # no tint
    assert process.sky_for("M31") == 0 and process.sky_for("M27") == 2 and process.sky_for("no such thing") == 2


def test_frames_arriving_faster_than_their_exposure_are_noticed():
    """A camera cannot deliver 15 s exposures every 11.6 s. One that does is
    exposing for less than it was asked, and the run says so."""
    every = lambda gap, n=12: [1000.0 + gap * i for i in range(n)]
    assert shoot.short_changed(every(11.6), 15) == pytest.approx(11.6)
    assert shoot.short_changed(every(16.5), 15) is None         # exposure and download: as it should be
    assert shoot.short_changed(every(11.6, n=4), 15) is None    # too few to say
    assert shoot.short_changed([None, None], 15) is None


def test_a_picture_of_one_star_among_many_is_labelled(tmp_path, monkeypatch):
    """Tabby's star is one dot in a field of hundreds, so its finished picture
    names it, placed by plate solving the stack; a galaxy's does not."""
    import interface
    import process
    from PIL import Image
    monkeypatch.setattr(config, "DATA", tmp_path)
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "transients.json").write_text(json.dumps(
        {"Tabby": {"ra": 301.564392, "dec": 44.456839, "kept_by": "starwatch.py", "id": "KIC 8462852"}}))
    ra, dec, text = process.point_of("Tabby")
    assert (ra, dec, text) == (301.564392, 44.456839, "Tabby's star (KIC 8462852)")
    assert process.point_of("Vega")[2] == "Vega"
    assert process.point_of("M31") is None and process.point_of("Saturn") is None
    assert process.point_of("no such thing") is None

    rgb = np.zeros((300, 450, 3), dtype=np.float32)
    picture = Image.fromarray(np.zeros((300, 450, 3), dtype=np.uint8))
    # A solve that puts the star at column 200, row 120.
    found = {"ra": ra, "dec": dec, "cd": [[-1e-3, 0], [0, 1e-3]]}
    wcs = depth.wcs_from(found, rgb.shape[:2])
    wcs.wcs.crpix = [201, 121]
    seen = {}
    monkeypatch.setattr(depth, "plate", lambda lum, name: seen.update(shape=lum.shape, name=name) or wcs)
    said = []
    marked = np.asarray(process.mark(picture, rgb, "Tabby", said.append))
    assert seen == {"shape": (300, 450), "name": "Tabby"} and "labelled" in said[0]
    assert marked[120, 200].max() == 0                      # the star's own light is left alone
    assert marked[120, 170:195].max() > 200                 # the tick to its left
    assert marked[125:150, 200].max() > 200                 # the tick below it
    assert marked[:115, 205:].max() > 200                   # its name, up and to the right

    assert process.mark(picture, rgb, "M31", said.append) is picture
    def fails(lum, name):
        raise interface.Refusal("PLATE_SOLVE_FAILED", "no")
    monkeypatch.setattr(depth, "plate", fails)
    assert process.mark(picture, rgb, "Tabby", said.append) is picture and "not labelled" in said[-1]


def test_a_sky_below_the_bias_level_is_not_taken_for_a_brightening_one():
    """18 October 2026: with the camera on another port the calibrated sky sat
    near -55, and "half as much again" of that rejected 16 of 19 clear frames."""
    accepted = [good(background=-55.0) for _ in range(5)]
    for level in (-56.4, -54.2, -53.6):
        assert stacking.judge(good(background=level), accepted) == (True, "")
    assert "sky brightened" in stacking.judge(good(background=60.0), accepted)[1]


def test_a_bias_at_zero_is_refused_not_kept(monkeypatch, tmp_path):
    """18 October 2026: with the offset at 0 a bias read 1 and the sky's grain
    was cut off at zero. Such a bias is refused, with what to change."""
    class Cap:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *e):
            return False
    monkeypatch.setattr(calibrate, "Camera", Cap)
    monkeypatch.setattr(calibrate, "capture", lambda cam, seconds, count, label: [np.ones((64, 64))] * 3)
    monkeypatch.setattr(calibrate, "save", lambda *a, **k: pytest.fail("a bias at zero was kept"))
    args = type("A", (), {"kind": "bias", "gain": 1500, "frames": 3, "exposure": 2.0})()
    with pytest.raises(SystemExit, match="offset"):
        calibrate.run(args)


def test_the_live_picture_never_holds_up_the_next_frame(session, monkeypatch):
    """18 October 2026: finishing the live picture after the fifth frame took
    half a minute, and the camera waited for it on every panel; drawn in a
    thread of the same process it still cost a frame a minute. It is drawn
    by another process: publish hands it over and returns at once."""
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor
    run, _ = session
    started, release = threading.Event(), threading.Event()

    def slow(stacked, count, name, exposure, web, finish=True):
        assert not finish                      # during a run the picture is only brightened
        started.set()
        release.wait(5)
        return 1.0
    monkeypatch.setattr(shoot, "draw_stack", slow)
    monkeypatch.setattr(shoot, "WEB", run.folder / "web")
    run.drawer, run.drawing, run.published = ThreadPoolExecutor(max_workers=1), None, 0.0
    began = time.monotonic()
    run.publish()
    assert started.wait(2) and time.monotonic() - began < 1     # handed over, and publish has returned
    run.publish()                                               # one at a time: skipped, not queued
    release.set()
    drawn = []
    monkeypatch.setattr(shoot, "draw_stack", lambda *a: drawn.append(a) or 0.0)
    run.publish(force=True)                                     # the last waits, then draws in full
    assert len(drawn) == 1 and run.preview_every >= 5.0


def test_the_live_picture_is_drawn_by_another_process():
    from concurrent.futures import ProcessPoolExecutor
    import numpy as np
    with ProcessPoolExecutor(max_workers=1, initializer=shoot.lowly) as pool:
        picture, spent = pool.submit(shoot.finished_picture, np.ones((40, 60, 3), np.float32), 1, "M31").result()
    assert picture.shape[:2] == (40, 60) and spent == 0.0

def test_a_rejected_frame_is_retaken_but_not_into_cloud():
    """18 October 2026: the person would rather a rejected frame were taken
    again than make do with fewer."""
    good = {"accepted": True, "flux": 1.0}
    bad = {"accepted": False, "flux": 1.0}
    later = {"accepted": False, "flux": None}          # not measured: says nothing
    assert shoot.retakes([good] * 10, 19) == 0
    assert shoot.retakes([good, bad, good, later], 19) == 1
    assert shoot.retakes([good, bad, good, bad, good, bad, good, bad, good, bad, good, bad, good], 19) == 4
    assert shoot.retakes([good, bad, good, bad, good], 4) == 2      # at least two, small runs too
    assert shoot.retakes([good, good, bad, bad, bad], 19) == 0      # three in a row: cloud, stop


def test_a_second_imaging_run_refuses_while_one_holds_the_rig(tmp_path):
    """18 October 2026: a patrol's second look at M33 started while M34 was
    imaging, and its GoTo swung the tube over the pole mid-run."""
    import pytest
    import interface
    lock = tmp_path / "imaging.lock"
    first = shoot.hold_the_rig("M34", lock)
    with pytest.raises(interface.Refusal, match="M34"):
        shoot.hold_the_rig("M33", lock)
    first.close()                                   # the first run ends
    shoot.hold_the_rig("M33", lock).close()         # and the next may start


def test_row_stripes_are_taken_out_and_a_gradient_and_stars_are_kept():
    rng = np.random.default_rng(3)
    rows, cols = 800, 600
    sky = 100 + np.linspace(0, 40, rows)[:, None] * np.ones((1, cols))      # a gradient down the frame
    stripes = rng.normal(0, 2.0, rows)[:, None]                             # a new level for every row
    frame = sky + stripes + rng.normal(0, 0.5, (rows, cols))
    frame[400, 300] += 5000                                                 # a star
    out = stacking.destripe(frame)
    level = np.median(out, axis=1) - np.median(sky, axis=1)
    assert level[60:-60].std() < 0.4         # 2.0 before; what is left is as broad as the window, like sky
    assert np.median(out[-50:]) - np.median(out[:50]) == pytest.approx(37.5, abs=1.5)  # gradient kept
    assert out[400, 300] - np.median(out[400]) > 4900                       # star kept


def test_a_frame_too_small_to_judge_its_rows_is_left_as_it_is():
    frame = np.arange(40 * 40, dtype=np.float32).reshape(40, 40)
    assert np.array_equal(stacking.destripe(frame), frame)


def test_a_master_frame_loses_its_row_stripes_but_keeps_its_hot_pixels():
    rng = np.random.default_rng(5)
    master = 47 + rng.normal(0, 1.0, (200, 300))[:, :1] + rng.normal(0, 0.3, (200, 300))
    master[100, 150] += 500                                                  # a hot pixel
    even = stacking.without_rows(master)
    for dy in (0, 1):
        assert np.median(even[dy::2], axis=1).std() < 0.05                  # rows level (were 1.0)
    assert even[100, 150] - np.median(even) > 490
    assert stacking.without_rows(None) is None


def test_a_stripe_that_changes_along_its_row_is_taken_out_too():
    rng = np.random.default_rng(7)
    rows, cols = 800, 800
    ramp = np.linspace(-1, 1, cols)[None, :]
    frame = 100 + rng.normal(0, 2.0, rows)[:, None] * ramp + rng.normal(0, 0.5, (rows, cols))   # green left, magenta right
    out = stacking.destripe(frame)
    left, right = np.median(out[60:-60, :200], axis=1), np.median(out[60:-60, -200:], axis=1)
    assert left.std() < 0.4 and right.std() < 0.4                          # were about 1.5 each


def test_destriping_keeps_a_galaxy_narrower_than_its_window():
    """19 October 2026: with every pixel in each row's level, a galaxy 280
    rows across lost 12% of its core and one 140 rows across 38%."""
    rng = np.random.default_rng(14)
    rows, cols = 1600, 1800
    yy, xx = np.indices((rows, cols))
    for across in (60, 120):
        glow = 400 * np.exp(-(((xx - 900) / 300) ** 2 + ((yy - 800) / across) ** 2))
        frame = 1000 + glow + rng.normal(0, 6, rows)[:, None] + rng.normal(0, 8, (rows, cols))
        taken = (frame - stacking.destripe(frame))[780:820, 600:1200].mean()
        assert taken < 0.06 * 400


def test_destriping_keeps_a_faint_galaxy_s_total_centre_and_profile():
    """Points kept are not enough: a galaxy is broad light, and what matters
    is its total, its central surface brightness and its profile. Measured
    19 October 2026 (kept, centre to outskirts): galaxies whose centres are
    2.5 times a pixel's noise keep 97% to 99% in all; one a pixel's noise
    bright keeps 90%, and 78% at four scale lengths, because its outskirts
    are below what the light finder sees and pull their rows' levels up.
    Widening the found light saved most of that but left more of a stripe
    that changes along its row, so these bounds hold it where it is."""
    rng = np.random.default_rng(21)
    rows, cols = 1600, 1800
    sky = 1000 + rng.normal(0, 8, (rows, cols))
    # scale, axis ratio, turn, central brightness; least total, centre and ring kept
    cases = ((40, 0.4, 0.0, 20.0, 0.95, 0.98, 0.9), (80, 0.7, 0.5, 20.0, 0.97, 0.98, 0.95),
             (25, 1.0, 0.0, 20.0, 0.97, 0.98, 0.94), (40, 0.4, 0.0, 8.0, 0.87, 0.95, 0.75))
    for n, (scale, ratio, angle, peak, total, centre, ring) in enumerate(cases):
        stripes = rng.normal(0, 6, rows)[:, None]
        glow, radius = depth.galaxy((rows, cols), (900, 800), scale, ratio, angle, peak)
        empty = stacking.destripe(sky + stripes)
        kept = depth.profile(stacking.destripe(sky + stripes + glow) - empty, radius)
        put = depth.profile(glow, radius)
        assert total <= kept.sum() / put.sum() <= 1.03, n
        assert centre <= kept[0] / put[0] <= 1.03, n
        assert np.all((kept / put >= ring) & (kept / put <= 1.05)), (n, kept / put)
