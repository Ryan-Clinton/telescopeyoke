"""The mineral Moon (mineral.py): the faint colour turned up honestly, with
the camera's own colour, clipping and slopes kept out of it; and the Moon's
orientation (lunar.py) that places the named seas for the check."""
import json
from datetime import datetime, timezone

import numpy as np
import pytest
from scipy import ndimage

import config
import lucky
import lunar
import mineral


def surface(size=256, seed=1):
    rng = np.random.default_rng(seed)
    texture = ndimage.gaussian_filter(rng.random((size, size)), 2.0)
    texture = (texture - texture.min()) / np.ptp(texture)
    yy, xx = np.indices((size, size))
    disc = np.hypot(yy - size / 2, xx - size / 2) < size * 0.45
    return (1000 + 2500 * texture) * disc + 40


def tinted(truth, blue=1.02, red=1.02):
    rgb = np.stack([truth] * 3, -1).astype(np.float32)
    rgb[96:160, 40:90, 2] *= blue        # a sea a little bluer on the left
    rgb[96:160, 166:216, 0] *= red       # one a little redder on the right
    return rgb


def test_the_faint_colour_is_turned_up_by_the_stated_factor_and_the_detail_kept():
    rng = np.random.default_rng(5)
    truth = surface()
    noisy = lambda a: a + rng.normal(0, 0.002, a.shape).astype(np.float32)    # noqa: E731
    colour = tinted(truth)
    moved = ndimage.shift(colour, (3, -2, 0), order=1, mode="nearest")
    out = mineral.mineral([noisy(colour), noisy(moved), noisy(colour)],
                          [truth, ndimage.shift(truth, (3, -2), order=1)], strength="standard", blur=2.0)
    image = out["picture"]
    assert out["facts"]["display_gain"] == mineral.STRENGTHS["standard"]
    left, right = image[96:160, 40:90], image[96:160, 166:216]
    assert left[..., 2].mean() > left[..., 0].mean() * 1.1
    assert right[..., 0].mean() > right[..., 2].mean() * 1.1
    assert lucky.sharpness(image.mean(axis=-1)) > 0.5 * lucky.sharpness(truth)
    # what was measured is kept apart from how far it was turned up
    assert 0.3 < out["facts"]["native_colour"]["p99_percent"] < 3
    assert out["facts"]["agreement"] and min(out["facts"]["agreement"]) > 0.5


def test_named_strengths_auto_and_numbers():
    safe = np.zeros((10, 10, 3))
    safe[..., 0] = 0.01
    everywhere = np.ones((10, 10), bool)
    assert mineral.gain_for("mild", safe, everywhere) == 8
    assert mineral.gain_for("12.5", safe, everywhere) == 12.5
    assert mineral.gain_for("auto", safe, everywhere) == pytest.approx(35)
    with pytest.raises(SystemExit):
        mineral.gain_for("loud", safe, everywhere)


def test_colour_that_does_not_repeat_from_video_to_video_is_turned_down():
    truth = surface()
    real = tinted(truth)
    rng = np.random.default_rng(3)
    stray = []
    for n in range(3):                     # a different false patch in each: the sensor's, not the Moon's
        c = real.copy()
        y = 40 + 50 * n
        c[y:y + 30, 120:150, 2] *= 1.03
        stray.append(c + rng.normal(0, 0.5, c.shape).astype(np.float32))
    out = mineral.mineral(stray, [truth], blur=2.0)
    s = out["picture"]
    false = s[45:65, 125:145]
    true = s[100:150, 45:85]
    assert (true[..., 2] - true[..., 0]).mean() > 3 * abs((false[..., 2] - false[..., 0]).mean())
    assert out["facts"]["repeatability"] == "measured"
    one = mineral.mineral(stray[:1], [truth], blur=2.0)
    assert one["facts"]["repeatability"].startswith("one video")


def test_a_clipped_stack_gives_no_colour_where_it_clipped():
    truth = surface()
    grey = np.stack([truth] * 3, -1).astype(np.float32)
    grey[..., 1] *= 1.27                    # the camera's green takes in more light, so it tops out first
    clipped = np.minimum(grey * 2, 8000)    # every colour stops at the camera's top
    out = mineral.mineral([grey, clipped], [truth, truth], blur=2.0, ceilings=[8000, 8000],
                          detail_ceilings=[8000, 8000])
    image = out["picture"]
    bright = truth > np.percentile(truth[truth > 100], 80)
    r, g, b = (image[..., k][bright].mean() for k in range(3))
    assert g > 0.97 * r                     # not magenta where the second stack clipped
    assert out["facts"]["clipped_share"][0] == 0 and out["facts"]["clipped_share"][1] > 0.05
    assert (out["confidence"][truth < 100] == 0).all()


def test_the_white_level_is_the_camera_s_not_the_container_s(tmp_path):
    for name, depth, recorded in (("a", 8, None), ("b", 12, None), ("c", 16, None), ("d", 12, 1023.0)):
        writer = lucky.SerWriter(tmp_path / f"{name}.ser", 4, 4, depth=8 if depth == 8 else 16,
                                 white=4095 if depth != 16 else 65535)
        writer.close()
        if depth == 16:              # an old 16-bit video, its header saying 16
            raw = bytearray((tmp_path / "c.ser").read_bytes())
            raw[34:38] = (16).to_bytes(4, "little")
            (tmp_path / "c.ser").write_bytes(bytes(raw))
        (tmp_path / f"{name}.stack.json").write_text(json.dumps({"white_level": recorded} if recorded else {}))
    camera = 2 ** config.hardware()["camera"]["bit_depth"] - 1
    assert mineral.white_level(tmp_path / "a") == 255
    assert mineral.white_level(tmp_path / "b") == 4095
    assert mineral.white_level(tmp_path / "c") == camera
    assert mineral.white_level(tmp_path / "d") == 1023
    assert lucky.ser_facts(tmp_path / "b.ser")[0] == 12


def test_the_colour_slope_is_fitted_on_the_uplands_so_a_great_sea_keeps_its_colour():
    yy, xx = np.indices((64, 64))
    tint = np.zeros((64, 64, 3), np.float32)
    tint[..., 0] = 0.02 * xx / 64            # redder towards one side, as on 30 October 2026
    tint[:, :24, 2] += 0.01                  # a great bluer sea over a third of the disc
    uplands = np.zeros((64, 64), bool)
    uplands[:, 30:] = True
    flat = mineral.flattened(tint, uplands)
    assert np.ptp(flat[..., 0]) < 1e-4
    assert flat[:, :24, 2].mean() - flat[:, 30:, 2].mean() > 0.009


def test_log_tint_takes_out_the_camera_s_balance_and_works_on_blocks():
    rgb = np.ones((16, 16, 3), np.float32) * (0.72, 1.0, 0.53)
    rgb[:8, :8, 2] *= 1.05
    t = mineral.log_tint(rgb, np.ones((16, 16), bool), bin=2)
    assert t.shape == (16, 16, 3)
    assert np.allclose(t.sum(axis=-1), 0, atol=1e-6)
    assert t[2, 2, 2] > 0.02 and abs(t[12, 12, 2]) < 0.01


def test_red_and_blue_are_moved_onto_green():
    truth = surface()
    rgb = np.stack([ndimage.shift(truth, (0, 2), order=1), truth, ndimage.shift(truth, (-1.5, 0), order=1)], -1)
    lined = mineral.channels_lined_up(rgb)
    inner = (slice(20, -20), slice(20, -20))
    assert np.abs(lined[..., 0][inner] - truth[inner]).mean() < 0.3 * np.abs(rgb[..., 0][inner] - truth[inner]).mean()


def test_only_blue_against_orange_is_kept_in_the_safe_picture():
    tint = np.zeros((4, 4, 3), np.float32)
    tint[0, 0] = (0.01, -0.02, 0.01)         # magenta: the camera
    tint[1, 1] = (0.01, 0.0, -0.01)          # orange: the Moon
    kept = mineral.blue_to_orange(tint)
    assert np.allclose(kept[0, 0], 0) and np.allclose(kept[1, 1], (0.01, 0, -0.01))


def test_a_stack_fades_out_towards_where_it_clipped_rather_than_stopping():
    good = np.ones((80, 80), bool)
    good[:, 50:] = False
    weight = mineral.feathered(good, width=8)
    assert weight[40, 10] > 0.99 and weight[40, 49] < 0.05
    assert np.abs(np.diff(weight[40, 20:50])).max() < 0.3 and mineral.feathered(np.ones((5, 5), bool)).min() == 1


# --- the Moon's orientation, and the check against the seas -------------------------

WHEN = datetime(2026, 10, 30, 2, 11, tzinfo=timezone.utc)


def test_the_moon_s_librations_stay_within_their_known_bounds():
    site = config.example()["site"]
    lats, lons = [], []
    for day in range(0, 28, 2):
        look = lunar.view(site, datetime(2026, 10, 1 + day, tzinfo=timezone.utc))
        lat, lon = look["under_us"]
        lats.append(float(lat))
        lons.append(float(lon))
    assert max(map(abs, lats)) < 7.6 and max(map(abs, lons)) < 9.0       # optical librations, plus parallax
    assert np.ptp(lats) > 8 and np.ptp(lons) > 8                          # and they do swing over a month
    pole_ra, pole_dec, _ = lunar.orientation(WHEN)
    assert abs(pole_dec - 66.5) < 2 and abs(pole_ra - 270) < 5


def test_the_sun_stands_over_the_right_longitude_for_the_phase():
    look = lunar.view(config.example()["site"], WHEN)       # 19 days old, waning: the Sun 50-odd degrees west
    assert -60 < float(look["under_sun"][1]) < -45


def moon_picture(look, turn, mirrored, size=240):
    disc = {"cy": size / 2, "cx": size / 2, "r": size * 0.4}
    g = lunar.surface(disc, (size, size), look, turn, mirrored)
    albedo = np.full((size, size), 0.12)
    for la, lo in lunar.SEAS.values():
        albedo[lunar.near(g, la, lo, 9)] = 0.07
    shade = np.where(g["inside"] & (g["cos_i"] > 0),
                     g["cos_i"] / np.maximum(g["cos_i"] + g["cos_e"], 1e-6), 0)
    return albedo * shade * 3000 + 10, disc, g


@pytest.mark.parametrize("turn,mirrored", [(213, False), (40, True)])
def test_the_picture_s_turn_and_mirroring_are_found_from_the_terminator_and_the_seas(turn, mirrored):
    look = lunar.view(config.example()["site"], WHEN)
    image, disc, _ = moon_picture(look, turn, mirrored)
    found, flipped, score = lunar.fit_turn(image, disc, look, shrink=2)
    assert flipped == mirrored and score > 1.2
    assert min(abs(found - turn), 360 - abs(found - turn)) < 5


def test_the_check_says_whether_tranquillitatis_is_bluer():
    look = lunar.view(config.example()["site"], WHEN)
    _, disc, g = moon_picture(look, 213, False)
    usable = g["inside"]
    orange = np.zeros(usable.shape)
    orange[lunar.near(g, *lunar.SEAS["Mare Tranquillitatis"], 6)] = -0.01
    maps = [orange + n * 1e-4 for n in range(3)]
    checks = mineral.check_seas(maps, [np.ones(usable.shape)] * 3, usable, g)
    assert [c["result"] for c in checks] == ["agrees", "agrees"]
    assert checks[0]["bluer_by_percent"] == pytest.approx(1.0, abs=0.05)
    reversed_ = mineral.check_seas([-m for m in maps], [np.ones(usable.shape)] * 3, usable, g)
    assert reversed_[0]["result"] == "disagrees"
