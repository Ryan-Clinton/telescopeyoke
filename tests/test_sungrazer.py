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


def test_a_narrow_noisy_strip_is_not_buried_in_its_block():
    # On 26 October 2026 CCOR-1's noise 50-60 pixels beside the arm was six
    # times the sky's, inside a 64-pixel block that averaged it down, and
    # a track of noise there was sent as a possible comet.
    rng = np.random.default_rng(3)
    images = [rng.normal(0, 1.0, (256, 256)).astype(np.float32) for _ in range(30)]
    for i in images:
        i[:, 100:110] *= 6                                            # the strip of glare
    mask = np.ones((256, 256), bool)
    found = sungrazer.points(images, mask)
    assert not [p for p in found if 100 <= p[1] < 110]
    spread = sungrazer.pixel_spread([i - images[0] for i in images[1:]])
    assert spread[128, 105] > 4 * spread[128, 200]


def test_each_pixels_noise_needs_pictures_enough():
    few = [np.ones((8, 8), np.float32)] * (sungrazer.PIXEL_PICTURES - 1)
    assert not sungrazer.pixel_spread(few).any()


def test_ccor1s_blanked_arm_and_its_edges_are_left_out():
    images = [np.ones((512, 512), np.float32) for _ in range(5)]
    for i in images:
        i[:256, 248:264] = 0                                          # the arm, blanked
    mask = sungrazer.usable((512, 512), "ccor1", images)
    assert not mask[60, 256] and not mask[60, 233] and not mask[60, 278] and mask[60, 200]


def test_ccor1s_glare_beside_its_arm_is_left_out():
    # On 25 October 2026 the arm's glare 18-34 pixels out made thirteen
    # tracks "heading in towards the Sun" along one line in a day.
    images = [np.ones((960, 1024), np.float32) for _ in range(5)]
    for i in images:
        i[:400, 472:530] = 0                                          # the arm, blanked, as in the real pictures
    mask = sungrazer.usable((960, 1024), "ccor1", images)
    assert not mask[200, 472 - 34] and not mask[200, 530 + 34]       # where the false tracks ran
    assert mask[200, 472 - 60] and mask[200, 530 + 60]                # sky further out is still searched


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


def test_the_timer_runs_the_ccor1_hunt_every_6_hours_and_lasco_is_refused(tmp_path):
    ran = []
    answer = sungrazer.install("ccor1", say=lambda *_: None, run=lambda cmd, check: ran.append(cmd), home=tmp_path)
    place = tmp_path / ".config" / "systemd" / "user"
    service = (place / "ty-sungrazer.service").read_text()
    assert "sungrazer.py hunt --camera ccor1" in service and "Nice=19" in service
    # A detached checkout kept for the timer follows the pushed code; a branch is left alone.
    assert "symbolic-ref -q HEAD" in service and "checkout -q --detach origin/main" in service
    assert service.index("ExecStartPre") < service.index("ExecStart=")
    assert "OnUnitActiveSec=6h" in (place / "ty-sungrazer.timer").read_text()
    assert ran[-1] == ["systemctl", "--user", "enable", "--now", "ty-sungrazer.timer"] and answer["installed"]
    with pytest.raises(sungrazer.interface.Refusal):
        sungrazer.install("c3", say=lambda *_: None, run=lambda cmd, check: None, home=tmp_path)


def piece(start_minute, count, x, y, vx, vy, first_picture=0):
    """A made-up track: (picture, x, y, strength, minute), every 15 minutes."""
    return [(first_picture + i, x + vx * 15 * i, y + vy * 15 * i, 50.0, start_minute + 15 * i) for i in range(count)]


def test_one_object_split_by_a_gap_is_joined_and_a_different_one_is_not():
    # 19 Oct 2026, CCOR-1: one comet seen 16:45-20:00 and again 20:45-23:45, a 45-minute gap between.
    before = piece(0, 14, 979.0, 295.0, -0.272, 0.087)
    after = piece(240, 13, 979.0 - 0.272 * 240, 295.0 + 0.087 * 240, -0.272, 0.087, first_picture=16)
    other = piece(240, 6, 600.0, 400.0, 0.1, 0.6, first_picture=16)
    joined = sungrazer.stitch([after, other, before])
    assert len(joined) == 2
    whole = next(t for t in joined if len(t) == 27)
    assert whole[0] == before[0] and whole[-1] == after[-1]
    assert sungrazer.gaps(["2026-10-19 19:45", "2026-10-19 20:00", "2026-10-19 20:45"]) == ["20:00-20:45"]


def test_a_track_that_turns_or_comes_too_late_is_not_joined():
    first = piece(0, 8, 900.0, 300.0, -0.27, 0.09)
    turned = piece(150, 8, 900.0 - 0.27 * 150, 300.0 + 0.09 * 150, -0.27, -0.3, first_picture=10)
    late = piece(105 + 300, 8, 900.0 - 0.27 * 405, 300.0 + 0.09 * 405, -0.27, 0.09, first_picture=30)
    assert len(sungrazer.stitch([first, turned])) == 2
    assert len(sungrazer.stitch([first, late])) == 2


def test_ccor1_positions_are_given_as_the_project_measures_them():
    # A kept level-3 picture is 1024 x 960, bottom row first; the project's reports measure 2048 x 1920 from the top.
    assert sungrazer.native(1016.0, 283.0, "ccor1", (960, 1024)) == (2032.0, 1354.0)
    assert sungrazer.native(500.0, 300.0, "c3", (1024, 1024)) == (500.0, 300.0)


REPORTS_PAGE = """
<tr class="sungrazer-reports-table table__row odd">
<td headers="view-title-table-column" class="views-field views-field-title table__cell"><a href="/report/x">report_ms_20261019125628</a>  </td>
<td headers="c" class="views-field views-field-field-contributor table__cell">Michael Stark  </td>
<td headers="d" class="views-field views-field-field-report-date table__cell"><time datetime="2026-10-19T12:00:00Z" class="datetime">2026-10-19</time>
</td>
<td headers="s" class="views-field views-field-field-sighting-type table__cell">Known Comet Now Entering  </td>
<td headers="g" class="views-field views-field-field-comet-group table__cell">Kreutz  </td>
<td headers="k" class="views-field views-field-field-camera table__cell">CCOR1  </td>
<td headers="f" class="views-field views-field-field-frames table__cell">1430 2029 1352<br>1445 2021 1349<br>1500 2013 1346  </td>
</tr>
<tr class="sungrazer-reports-table table__row even">
<td headers="view-title-table-column" class="views-field views-field-title table__cell"><a href="/report/y">report_bc_20261019233808</a>  </td>
<td headers="c" class="views-field views-field-field-contributor table__cell">Bill Collins  </td>
<td headers="d" class="views-field views-field-field-report-date table__cell"><time datetime="2026-10-19T12:00:00Z" class="datetime">2026-10-19</time>
</td>
<td headers="s" class="views-field views-field-field-sighting-type table__cell">Potential Comet  </td>
<td headers="g" class="views-field views-field-field-comet-group table__cell">Kreutz  </td>
<td headers="k" class="views-field views-field-field-camera table__cell">CCOR1  </td>
<td headers="f" class="views-field views-field-field-frames table__cell">1945 897 924<br>2000 892 920<br>2130 875 902  </td>
</tr>
<tr class="sungrazer-reports-table table__row odd">
<td headers="view-title-table-column" class="views-field views-field-title table__cell"><a href="/report/z">report_nu_20261019163827</a>  </td>
<td headers="c" class="views-field views-field-field-contributor table__cell">NEW USER  </td>
<td headers="d" class="views-field views-field-field-report-date table__cell"><time datetime="2026-10-19T12:00:00Z" class="datetime">2026-10-19</time>
</td>
<td headers="s" class="views-field views-field-field-sighting-type table__cell">Potential Comet  </td>
<td headers="g" class="views-field views-field-field-comet-group table__cell">Kreutz  </td>
<td headers="k" class="views-field views-field-field-camera table__cell">C3  </td>
<td headers="f" class="views-field views-field-field-frames table__cell">1406 803 747<br>1430 800 744  </td>
</tr>
"""


def reports_get(*_, **__):
    return Reply(REPORTS_PAGE, status_code=200)


def test_the_projects_reports_are_read_for_one_camera():
    found = sungrazer.public_reports("ccor1", get=reports_get)
    assert [r["id"] for r in found] == ["report_ms_20261019125628", "report_bc_20261019233808"]
    assert found[0]["who"] == "Michael Stark" and found[0]["type"] == "Known Comet Now Entering"
    assert found[0]["date"] == "2026-10-19" and found[0]["points"][0] == ("1430", 2029.0, 1352.0)


def test_a_candidate_is_matched_to_a_report_carried_along_its_track_and_never_rejected():
    reports = sungrazer.public_reports("ccor1", get=reports_get)
    times = [f"2026-10-19 {h:02d}:{m:02d}" for h, m in [(16, 45), (17, 0), (17, 15), (17, 30), (17, 45)]]
    known = {"times": times, "sungrazer_xy": [[1958.0 - 8.16 * i, 1330.0 - 2.6 * i] for i in range(5)]}
    assert sungrazer.public_match(known, reports) == {
        "state": "known comet", "report": "report_ms_20261019125628", "who": "Michael Stark",
        "type": "Known Comet Now Entering", "group": "Kreutz"}
    collins = {"times": ["2026-10-19 19:45", "2026-10-19 20:00"], "sungrazer_xy": [[898.0, 923.0], [893.0, 919.0]]}
    assert sungrazer.public_match(collins, reports)["state"] == "possible public match"
    alone = {"times": times, "sungrazer_xy": [[1158.0, 1250.0 + 9 * i] for i in range(5)]}
    assert sungrazer.public_match(alone, reports) == {"state": "no matching public report found"}


def comet_seen():
    """19 Oct 2026's CCOR-1 hunt: the known comet and the weak rim track."""
    comet = {"pictures": [1, 2], "towards_sun": 1.0, "times": ["2026-10-19 16:45", "2026-10-19 17:00"],
             "files": ["a.fits", "b.fits"], "track": [[979.0, 295.0], [975.0, 296.0]],
             "sungrazer_xy": [[1958.0, 1330.0], [1950.0, 1328.0]], "gaps": ["20:00-20:45"],
             "pixels_per_12_min": 3.47, "strength": 110.0, "movie": "m1.gif", "rim": False}
    weak = {"pictures": [1], "towards_sun": 0.82, "times": ["2026-10-19 11:30"], "files": ["c.fits"],
            "track": [[579.0, 335.0]], "pixels_per_12_min": 7.72, "strength": 6.8, "movie": "m3.gif", "rim": True}
    away = {"pictures": [1], "towards_sun": -0.8, "times": ["2026-10-19 02:00"], "files": ["d.fits"],
            "track": [[300.0, 300.0]], "pixels_per_12_min": 6.0, "strength": 12.0, "movie": "m2.gif"}
    return {"pictures": 74, "folder": "f", "candidates": [comet, weak, away]}


def run_hunt(tmp_path, seen, get, now=datetime.datetime(2026, 10, 20, 5, 5, tzinfo=datetime.timezone.utc)):
    sent = []
    answer = sungrazer.hunt("ccor1", 24, say=lambda *_: None, now=now, get=get, looker=lambda: seen,
                            send=lambda text, animations=(), say=None, **k: sent.append((text, list(animations))))
    return answer, sent


def test_the_person_hears_of_a_find_then_what_it_turned_out_to_be_and_only_once(tmp_path, monkeypatch):
    import config
    import json
    monkeypatch.setattr(config, "DATA", tmp_path)
    store = tmp_path / "sungrazer" / "pictures" / "ccor1"
    store.mkdir(parents=True)
    (store / "CCOR1_3_20261010T000025_V00_NC.fits").write_bytes(b"old")

    def get(url, *a, **k):
        return reports_get() if url == sungrazer.REPORTS else Reply("", status_code=200)
    answer, sent = run_hunt(tmp_path, comet_seen(), get)
    (first, movies), (checked, _) = sent
    assert "1 possible comet heading in towards the Sun" in first and movies == [("m1.gif", "possible comet 1")]
    assert checked.startswith("Comet hunt checked: 1 known comet recovered; no unexplained candidates; "
                              "1 weak track on the occulter's rim set aside.")
    assert "already known: a Kreutz comet" in checked and "report_ms_20261019125628, Michael Stark" in checked
    assert "2026-10-19 16:45  1958.0  1330.0  (a.fits)" in checked and "20:00-20:45" in checked
    assert "report comet" not in checked                                 # nothing to report
    assert [c["movie"] for c in answer["towards_sun"]] == ["m1.gif"] and answer["rim"][0]["movie"] == "m3.gif"
    assert answer["deleted"] == 1 and answer["moving"] == 3
    assert json.loads((tmp_path / "sungrazer" / "hunt-ccor1.json").read_text())["towards_sun"][0]["public"][
        "state"] == "known comet"
    # Six hours later the same comet is in the pictures again: nothing is sent.
    answer, sent = run_hunt(tmp_path, comet_seen(), get, now=datetime.datetime(2026, 10, 20, 11, 5,
                                                                               tzinfo=datetime.timezone.utc))
    assert sent == [] and answer["towards_sun"][0]["verdict"]["kind"] == "known comet"


def test_an_unexplained_find_is_offered_for_reporting_and_its_later_match_is_told(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "DATA", tmp_path)
    nobody = "<html></html>"
    answer, sent = run_hunt(tmp_path, comet_seen(), lambda url, *a, **k: Reply(nobody, status_code=200))
    checked = sent[1][0]
    assert "1 unexplained track: possibly new" in checked and "It could be new" in checked
    assert "\"report comet 1\"" in checked
    # By the next hunt someone has reported it as a known comet: one update, then quiet.
    get = lambda url, *a, **k: reports_get() if url == sungrazer.REPORTS else Reply("", status_code=200)  # noqa: E731
    later = datetime.datetime(2026, 10, 20, 11, 5, tzinfo=datetime.timezone.utc)
    _, sent = run_hunt(tmp_path, {"pictures": 70, "folder": "f", "candidates": []}, get, now=later)
    assert len(sent) == 1 and sent[0][0].startswith("Comet hunt update: the possible comet first seen 2026-10-19 16:45")
    assert "already known" in sent[0][0]
    _, sent = run_hunt(tmp_path, {"pictures": 70, "folder": "f", "candidates": []}, get, now=later)
    assert sent == []


def test_a_planet_on_the_track_is_named(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "DATA", tmp_path)
    (tmp_path / "sungrazer" / "pictures" / "ccor1").mkdir(parents=True)
    for name in ("a.fits", "b.fits"):
        (tmp_path / "sungrazer" / "pictures" / "ccor1" / name).write_bytes(b"")
    monkeypatch.setattr(sungrazer, "where_bodies", lambda path: {"Venus": (978.0, 294.0) if path.name == "a.fits"
                                                                  else (976.0, 297.0), "Mars": (10.0, 10.0)})
    answer, sent = run_hunt(tmp_path, comet_seen(), lambda url, *a, **k: Reply("<html></html>", status_code=200))
    assert "not a comet: it is the planet Venus" in sent[1][0] and "1 planet; no unexplained" in sent[1][0]


def test_the_suns_pole_angle_is_as_the_almanac_gives():
    from astropy.time import Time
    # Meeus's example 29.a: 1992 October 13.0 TD, P = +26.27 degrees.
    assert sungrazer.solar_p(Time(2448908.50068, format="jd")) == pytest.approx(26.27, abs=0.05)

