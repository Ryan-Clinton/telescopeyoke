"""precision.py: a night's frames measured every way, so the ways can be
compared on the same light."""
import math

import numpy as np
import pytest

import precision
import stacking


def test_a_star_is_found_where_the_registration_says_it_is():
    rng = np.random.default_rng(0)
    rgb = rng.normal(0, 1, (300, 300, 3)).astype(np.float32)
    r = np.array([[math.cos(math.radians(0.4)), -math.sin(math.radians(0.4))],
                  [math.sin(math.radians(0.4)), math.cos(math.radians(0.4))]])
    t = np.array([12.0, -7.5])
    first = np.array([[150.0, 140.0], [60.0, 220.0]])
    here = precision.positions(first, t, 0.4)
    # What stacking.warp does with the same rotation and shift brings each back.
    assert np.allclose(here @ r.T + t, first, atol=1e-9)
    assert rgb.shape == (300, 300, 3) and stacking.warp is not None


def test_round_apertures_take_the_stars_light_less_the_sky():
    image = np.full((200, 200), 10.0)
    yy, xx = np.mgrid[:200, :200]
    s = 5.0 / 2.355
    image += 1000 * np.exp(-((xx - 100.3) ** 2 + (yy - 99.6) ** 2) / (2 * s * s))
    total = 1000 * 2 * math.pi * s * s
    found = precision.centred(image, [(101.0, 99.0)])[0]
    assert found == pytest.approx((100.3, 99.6), abs=0.15)
    flux = precision.apertures(image, [found], 5.0)[0]
    assert flux[0] == pytest.approx(total * (1 - math.exp(-25 / (2 * s * s))), rel=0.05)
    assert flux[-1] == pytest.approx(total, rel=0.01)                     # 3 FWHM holds it all
    assert np.all(np.diff(flux) >= -1e-6)


def test_random_noise_falls_with_averaging_and_a_drift_does_not():
    rng = np.random.default_rng(0)
    scatter, beta = precision.falls(rng.normal(0, 0.02, 2000))
    assert 0.75 < beta < 1.25 and scatter[40] < scatter[1] / 4
    _, beta = precision.falls(np.sin(np.arange(2000) / 150) * 0.02 + rng.normal(0, 0.005, 2000))
    assert beta > 3


def test_the_comparison_stars_are_ranked_by_their_own_steadiness():
    rng = np.random.default_rng(3)
    flux = 1000 * (1 + rng.normal(0, 0.002, (500, 6)))
    flux[:, 4] *= 1 + rng.normal(0, 0.05, 500)                           # one noisy star
    assert precision.ranked(flux)[-1] == 4
    target = 1000 * (1 + rng.normal(0, 0.002, 500))
    mag = precision.light_curve(target, flux[:, :4])
    assert 1000 * precision.robust(mag) < 4


def test_the_ways_are_judged_on_kept_frames_and_the_slope_is_in_mmag_an_hour(tmp_path):
    import json
    rng = np.random.default_rng(4)
    frames, stars = 400, 8
    jd = 2461333.53 + np.arange(frames) * 5 / 86400                      # 4 s frames every 5 s
    light = 1000 * (1 + rng.normal(0, 0.003, (frames, stars)))
    light[:, 0] *= 10 ** (-0.4 * 0.010 * (jd - jd[0]) * 24)               # the target fades 10 mmag an hour
    flux = np.broadcast_to(light[None, None, :, :, None], (2, 4, frames, stars, len(precision.APERTURES))).copy()
    data = {"flux": flux, "jd": jd, "x": np.zeros(frames), "y": np.zeros(frames), "fwhm": np.full(frames, 5.0),
            "sky": np.full(frames, 20.0)}
    p = {"planet": "Test b", "ra": 97.6, "dec": 29.7, "hours": 0.5, "period": 100.0, "epoch": jd[0] + 50}
    stars_rows = np.column_stack([np.full(stars, 97.6), np.full(stars, 29.7), np.linspace(11.5, 12.5, stars),
                                  np.full(stars, 0.8)])
    answer = precision.judge(p, stars_rows, np.column_stack([np.arange(stars) * 50.0, np.zeros(stars)]), data)
    slope = answer["ways"][0]["baseline_slope_mmag_per_h"]
    assert slope == pytest.approx(10, abs=3)
    session = tmp_path / "s"
    session.mkdir()
    log = [{"index": i + 1, "accepted": i != 2} for i in range(4)]
    (session / "frames.jsonl").write_text("".join(json.dumps(r) + "\n" for r in log))
    paths = [session / f"light-{i + 1:04d}.fits" for i in range(4)]
    small = {k: (v[:, :, :4] if k == "flux" else v[:4]) for k, v in data.items()}
    kept = precision.accepted_only(session, small, paths)
    assert kept["flux"].shape[2] == 3 and len(kept["jd"]) == 3
