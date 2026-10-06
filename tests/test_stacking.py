"""The imaging pipeline, on made-up star fields where the right answer is known."""
import config
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
