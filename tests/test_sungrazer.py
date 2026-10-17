"""Comets in SOHO's pictures: in a made-up C3 sequence, with a corona, an
occulter, drifting stars and noise, the one point moving towards the Sun
is the candidate and no star is. Nothing here touches the network."""
import datetime

import numpy as np
import pytest

import sungrazer
from test_depth import render

SHAPE = (512, 512)


def sequence(frames=12, seed=1, comet=True):
    rng = np.random.default_rng(seed)
    yy, xx = np.indices(SHAPE)
    r = np.hypot(xx - 256, yy - 256)
    corona = 4000 / np.maximum(r, 20) ** 1.2
    stars = rng.uniform(40, 470, (300, 2))
    flux = 10 ** rng.uniform(2.3, 3.5, 300)
    drift = np.array([0.55, 0.05])
    start, step = np.array([430.0, 120.0]), np.array([-3.0, 2.5])     # in towards the middle
    images = []
    for i in range(frames):
        image = corona * (1 + 0.02 * np.sin(i)) + render(SHAPE, stars + i * drift, flux, fwhm=2.0)
        if comet:
            image += render(SHAPE, np.array([start + i * step]), np.array([600.0]), fwhm=2.2)
        image += rng.normal(0, 2.0, SHAPE)
        images.append(image.astype(np.float32))
    return images, start, step


def test_a_comet_heading_for_the_sun_is_found_and_the_stars_are_not():
    images, start, step = sequence()
    mask = sungrazer.usable(SHAPE, "c3")
    found = sungrazer.points(images, mask)
    linked = sungrazer.tracks(found, len(images))
    drift = sungrazer.star_drift(linked)
    assert drift == pytest.approx([0.55, 0.05], abs=0.15)          # measured from the stars themselves
    candidates = sungrazer.judge(linked, drift, SHAPE)
    assert len(candidates) >= 1
    best = candidates[0]
    assert best["towards_sun"] > 0.8 and best["pixels_per_12_min"] == pytest.approx(np.hypot(*step), abs=0.4)
    first = best["pictures"][0]
    assert best["track"][0] == pytest.approx(list(start + first * step), abs=1.5)
    # No candidate moves like the stars.
    assert all(abs(c["pixels_per_12_min"] - np.hypot(0.55, 0.05)) > 0.3 for c in candidates)


def test_without_a_comet_nothing_but_stars_moves():
    images, _, _ = sequence(comet=False, seed=4)
    mask = sungrazer.usable(SHAPE, "c3")
    linked = sungrazer.tracks(sungrazer.points(images, mask), len(images))
    assert sungrazer.judge(linked, sungrazer.star_drift(linked), SHAPE) == []


def test_the_middle_edges_and_writing_are_left_out():
    mask = sungrazer.usable((1024, 1024), "c3")
    assert not mask[512, 512] and not mask[5, 500] and not mask[1000, 500] and mask[300, 300]


def test_a_pictures_time_is_read_from_its_name():
    assert sungrazer.stamp("20261015_0042_c3_1024.jpg") == datetime.datetime(2026, 10, 15, 0, 42, tzinfo=datetime.timezone.utc)


def test_fetching_takes_only_what_is_not_kept(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "DATA", tmp_path)
    listing = "".join(f'<a href="20261015_{h:02d}06_c3_1024.jpg">' for h in range(24))
    asked = []

    class Reply:
        def __init__(self, text="", content=b"jpg"):
            self.text, self.content, self.status_code = text, content, 200

        def raise_for_status(self):
            pass

    def get(url, timeout=None):
        asked.append(url)
        return Reply(listing) if url.endswith("/") else Reply()
    now = datetime.datetime(2026, 10, 15, 23, 59, tzinfo=datetime.timezone.utc)
    first = sungrazer.fetch(6, "c3", say=lambda *_: None, get=get, now=now, pause=0)
    pictures = [u for u in asked if u.endswith(".jpg")]
    assert len(first) == 6 and len(pictures) == 6
    asked.clear()
    sungrazer.fetch(6, "c3", say=lambda *_: None, get=get, now=now, pause=0)
    assert [u for u in asked if u.endswith(".jpg")] == []         # kept: never fetched twice


def test_a_time_in_the_past_bounds_what_is_looked_at(tmp_path, monkeypatch):
    import config
    from PIL import Image
    monkeypatch.setattr(config, "DATA", tmp_path)
    store = tmp_path / "sungrazer" / "pictures" / "c3"
    store.mkdir(parents=True)
    images, _, _ = sequence()
    names = [f"20250125_{h:02d}06_c3_1024.jpg" for h in range(len(images))] + ["20250127_0006_c3_1024.jpg"]
    for name, image in zip(names, images + images[:1]):
        Image.fromarray(np.clip(image, 0, 255).astype(np.uint8)).save(store / name, quality=95)
    when = sungrazer.moment("2025-01-26T00:00")
    assert when == datetime.datetime(2025, 1, 26, tzinfo=datetime.timezone.utc)
    answer = sungrazer.look("c3", hours=24, say=lambda *_: None, until=when)
    assert answer["pictures"] == len(images) and answer["to"] == names[len(images) - 1]


def test_a_missing_picture_stretches_the_step_not_the_track():
    images, start, step = sequence(frames=14, seed=2)
    kept = [i for i in range(14) if i not in (5, 6)]                 # 36 minutes with no picture
    images = [images[i] for i in kept]
    minutes = [i * sungrazer.CADENCE for i in kept]
    mask = sungrazer.usable(SHAPE, "c3")
    linked = sungrazer.tracks(sungrazer.points(images, mask), len(images), minutes=minutes)
    drift = sungrazer.star_drift(linked)
    assert drift == pytest.approx([0.55, 0.05], abs=0.15)            # per 12 minutes, gap or no gap
    best = sungrazer.judge(linked, drift, SHAPE)[0]
    assert best["pixels_per_12_min"] == pytest.approx(np.hypot(*step), abs=0.4) and best["towards_sun"] > 0.8


HEADERS = """\
33891726.fts    2026/10/16  01:31:14   C3    17.6   1024   1024     20      1  Clear   Clear   Normal       0.0000  4180
33891727.fts    2026/10/16  01:42:25   C3    17.6   1024   1024     20      1  Clear   Clear   Normal       0.0000  4180
33891730.fts    2026/10/16  01:50:02   C3    17.6    512    512     20      1  Clear   Clear   Normal       0.0000  4197
33891731.fts    2026/10/16  01:51:02   C3    17.6   1024   1024     20      1  Clear   +60deg  Normal       0.0000  4195
33891732.fts    2026/10/16  01:52:02   C3    17.6   1024   1024     20      1  Blue    Clear   Normal       0.0000  4214
"""


class Reply:
    def __init__(self, text="", content=b"", status_code=200):
        self.text, self.content, self.status_code = text, content, status_code

    def raise_for_status(self):
        pass


def test_only_the_days_full_size_plain_raw_pictures_are_wanted():
    asked = []

    def get(url, timeout=None):
        asked.append(url)
        if "lasco_level05" in url:
            return Reply("<h1>Not Found</h1>", status_code=404)      # not in the archive yet
        return Reply(HEADERS)
    wanted = sungrazer.raw_day_list("20261016", "c3", get)
    assert [n for _, n in wanted] == ["20261016_013114_c3.fts", "20261016_014225_c3.fts"]
    assert wanted[0][0] == "https://umbra.nascom.nasa.gov/pub/lasco/lastimage/level_05/261016/c3/33891726.fts"
    assert asked[0].startswith(sungrazer.RAW[0])                      # the archive is asked first
    assert sungrazer.stamp(wanted[1][1]) == datetime.datetime(2026, 10, 16, 1, 42, 25, tzinfo=datetime.timezone.utc)


def test_raw_pictures_are_fetched_once_under_their_times(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "DATA", tmp_path)
    asked = []

    def get(url, timeout=None):
        asked.append(url)
        return Reply(HEADERS) if url.endswith("img_hdr.txt") else Reply(content=b"fits")
    now = datetime.datetime(2026, 10, 16, 3, 0, tzinfo=datetime.timezone.utc)
    kept = sungrazer.fetch(3, "c3", say=lambda *_: None, get=get, now=now, pause=0, raw=True)
    assert [p.name for p in kept] == ["20261016_013114_c3.fts", "20261016_014225_c3.fts"]
    asked.clear()
    sungrazer.fetch(3, "c3", say=lambda *_: None, get=get, now=now, pause=0, raw=True)
    assert [u for u in asked if u.endswith(".fts")] == []


def test_a_raw_picture_is_read_less_its_offset_per_second_with_lost_blocks_filled(tmp_path):
    from astropy.io import fits
    data = np.full((64, 64), 500, np.int16)
    data[10:20, 10:20] = 0                                            # a block lost in transmission
    data[40, 40] = 500 + 4 * 400
    head = fits.Header({"OFFSET": 400.0, "EXPTIME": 4.0})
    fits.PrimaryHDU(data, head).writeto(tmp_path / "20261016_013114_c3.fts")
    image = sungrazer.load(tmp_path / "20261016_013114_c3.fts")
    assert image[0, 0] == pytest.approx(5.0)                          # sqrt((500 - 400) / 4)
    assert image[40, 40] == pytest.approx(np.sqrt(425))
    assert np.isnan(image[15, 15])
    other = np.full((64, 64), 7.0, np.float32)
    filled = sungrazer.fill([image, other, other])
    assert filled[0][15, 15] == pytest.approx(7.0) and filled[0][0, 0] == pytest.approx(5.0)
    assert not np.isnan(filled[0]).any()


def test_ccor1s_days_list_keeps_the_15_minute_pictures_only():
    listing = "".join(f"<Key>SWFO/GOES-19/CCOR-1/ccor1-l3/2026/10/16/CCOR1_3_20261016T{t}_V00_{k}.fits</Key>"
                      for t, k in (("000025", "NC"), ("055516", "EC"), ("061516", "NC")))
    asked = []

    def get(url, timeout=None, params=None):
        asked.append(params)
        return Reply(listing)
    wanted = sungrazer.ccor_day_list("20261016", get)
    assert [n for _, n in wanted] == ["CCOR1_3_20261016T000025_V00_NC.fits", "CCOR1_3_20261016T061516_V00_NC.fits"]
    assert asked[0]["prefix"] == "SWFO/GOES-19/CCOR-1/ccor1-l3/2026/10/16/"
    assert sungrazer.stamp(wanted[1][1]) == datetime.datetime(2026, 10, 16, 6, 15, 16, tzinfo=datetime.timezone.utc)


def test_the_noise_is_measured_where_it_is():
    rng = np.random.default_rng(0)
    diff = rng.normal(0, 1.0, (256, 256)).astype(np.float32)
    diff[:, :128] *= 10                                               # a noisy inner corona on the left
    spread = sungrazer.local_spread(diff, np.ones(diff.shape, bool))
    assert spread[128, 20] == pytest.approx(10, rel=0.15) and spread[128, 236] == pytest.approx(1, rel=0.15)


def test_ccor1s_blanked_arm_and_its_edges_are_left_out():
    images = [np.ones((512, 512), np.float32) for _ in range(5)]
    for i in images:
        i[:256, 248:264] = 0                                          # the arm, blanked
    mask = sungrazer.usable((512, 512), "ccor1", images)
    assert not mask[60, 256] and not mask[60, 245] and not mask[60, 268] and mask[60, 200]


def test_planted_comets_are_found_when_strong_and_counted_by_strength():
    images, _, _ = sequence(frames=16, comet=False, seed=5)
    mask = sungrazer.usable(SHAPE, "c3")
    fakes = sungrazer.plant(images, mask, 6, seed=1, strengths=(2, 30))
    found = sungrazer.points(images, mask)
    linked = sungrazer.tracks(found, len(images))
    hits = sungrazer.recovered(fakes, sungrazer.judge(linked, sungrazer.star_drift(linked), SHAPE))
    strong = [h for f, h in zip(fakes, hits) if f["strength"] == 30]
    weak = [h for f, h in zip(fakes, hits) if f["strength"] == 2]
    assert len(strong) == 3 and all(strong) and sum(weak) <= 1
