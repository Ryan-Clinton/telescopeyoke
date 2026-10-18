"""Naming the satellite in a frame: the streak found on made frames, made-up
satellites matched to it or not, the kept orbits chosen by date, and the
places SGP4 gives checked against astropy's own route. Nothing touches the
network."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from astropy.io import fits

import config
import depth
import interface
import streak

START = datetime(2026, 10, 18, 21, 47, 59, 404000, tzinfo=timezone.utc)
SHAPE = (912, 1368)     # a brightness image half the 183C's size again: 1.32" x 2 a pixel


def sky(seed=1, stars=150):
    """A made brightness image: sky, noise and round stars."""
    rng = np.random.default_rng(seed)
    image = rng.normal(300, 10, SHAPE)
    yy, xx = np.mgrid[:SHAPE[0], :SHAPE[1]]
    for x, y, flux in zip(rng.uniform(0, SHAPE[1], stars), rng.uniform(0, SHAPE[0], stars),
                          rng.uniform(200, 4000, stars)):
        near = (abs(xx - x) < 12) & (abs(yy - y) < 12)
        image[near] += flux * np.exp(-((xx[near] - x) ** 2 + (yy[near] - y) ** 2) / (2 * 2.0 ** 2))
    return image


def line(image, a, b, level=60, width=1.5):
    """A straight streak from a to b (x, y)."""
    yy, xx = np.mgrid[:SHAPE[0], :SHAPE[1]]
    a, b = np.array(a, float), np.array(b, float)
    d = b - a
    f = np.clip(((xx - a[0]) * d[0] + (yy - a[1]) * d[1]) / (d @ d), 0, 1)
    gap = np.hypot(xx - (a[0] + f * d[0]), yy - (a[1] + f * d[1]))
    return image + level * np.exp(-gap ** 2 / (2 * width ** 2))


def test_a_line_among_stars_is_found_with_its_ends():
    found = streak.find_streaks(line(sky(), (300, 200), (900, 600)))
    assert len(found) == 1
    (x1, y1), (x2, y2) = sorted(found[0]["ends"])
    assert (x1, y1) == pytest.approx((300, 200), abs=12) and (x2, y2) == pytest.approx((900, 600), abs=12)
    assert found[0]["at_edge"] == [False, False]
    assert all(0.8 < v < 1.2 for v in found[0]["profile"])    # even along its length


def test_a_line_off_the_edge_says_that_end_may_go_on():
    found = streak.find_streaks(line(sky(), (700, 0), (600, 450)))
    assert len(found) == 1
    edge = [e for e, at in zip(found[0]["ends"], found[0]["at_edge"]) if at]
    assert len(edge) == 1 and edge[0][1] < 8


def test_stars_alone_have_no_streak():
    assert streak.find_streaks(sky()) == []


def test_stars_trailed_by_poor_tracking_are_not_a_streak():
    image = np.random.default_rng(2).normal(300, 10, SHAPE)
    rng = np.random.default_rng(3)
    for x, y in zip(rng.uniform(40, SHAPE[1] - 40, 80), rng.uniform(40, SHAPE[0] - 40, 80)):
        image = line(image, (x, y), (x + 20, y + 6), level=400)   # every star a short dash the same way
    assert streak.find_streaks(image) == []


# --- matching ---------------------------------------------------------------

def frame_wcs():
    scale = config.field_height() / SHAPE[0]
    return depth.wcs_from({"ra": 10.2, "dec": 40.6, "cd": [[-scale, 0], [0, scale]]}, SHAPE), scale * 3600


def times(seconds=16.0):
    return [START + timedelta(seconds=s) for s in
            np.arange(-streak.SLACK - streak.STEP, seconds + streak.STEP + streak.SLACK, streak.STEP)]


def crossing(wcs, through, heading, at=8.0, speed=300.0, steps=None):
    """A made-up satellite's (ra, dec) at each time: through a pixel at `at`
    seconds after the shutter opened, going `heading` at `speed` pixels a second."""
    steps = steps or times()
    t = np.array([(s - START).total_seconds() for s in steps])
    heading = np.array(heading, float) / np.hypot(*heading)
    xs, ys = through[0] + heading[0] * speed * (t - at), through[1] + heading[1] * speed * (t - at)
    return wcs.pixel_to_world_values(xs, ys)


def placed(*paths):
    """A stand-in for streak.places: these paths, 1,000 km away, in sunlight."""
    def places(satellites, steps, site):
        ra = np.array([p[0] for p in paths])
        dec = np.array([p[1] for p in paths])
        return ra, dec, np.full(ra.shape, 1000.0), np.ones(ra.shape, bool)
    return places


STREAK = {"ends": [[300.0, 200.0], [900.0, 600.0]], "at_edge": [False, False], "pixels": 721.0}


def test_a_satellite_along_the_streak_fits_and_one_elsewhere_does_not(monkeypatch):
    wcs, scale = frame_wcs()
    along = crossing(wcs, (600, 400), (600, 400), speed=721 / 16 * 1.1)    # crosses it while the shutter is open
    away = crossing(wcs, (600, 0), (600, 400))                            # parallel, 0.24° off
    monkeypatch.setattr(streak, "places", placed(along, away))
    found = streak.match(STREAK, wcs, scale, [("SAT-A", 1, None), ("SAT-B", 2, None)], times(), START, 16.0, {})
    named = {m["name"]: m for m in found}
    assert named["SAT-A"]["fits"] and named["SAT-A"]["angle_deg"] < 1
    assert not named["SAT-B"]["fits"] and named["SAT-B"]["offset_deg"] > streak.WITHIN
    assert "SAT-A" in streak.verdict(STREAK, found, scale)


def test_a_satellite_across_the_streak_does_not_fit(monkeypatch):
    wcs, scale = frame_wcs()
    monkeypatch.setattr(streak, "places", placed(crossing(wcs, (600, 400), (-400, 600))))
    found = streak.match(STREAK, wcs, scale, [("SAT-A", 1, None)], times(), START, 16.0, {})
    assert not found[0]["fits"] and found[0]["angle_deg"] > 45


def test_a_satellite_there_before_the_shutter_opened_does_not_fit(monkeypatch):
    wcs, scale = frame_wcs()
    # Along the streak, but at it 10 s before the exposure began.
    monkeypatch.setattr(streak, "places", placed(crossing(wcs, (600, 400), (600, 400), at=-10.0)))
    found = streak.match(STREAK, wcs, scale, [("SAT-A", 1, None)], times(), START, 16.0, {})
    assert found[0]["angle_deg"] < 1 and not found[0]["fits"]


def test_two_satellites_that_both_fit_are_neither_named(monkeypatch):
    wcs, scale = frame_wcs()
    monkeypatch.setattr(streak, "places", placed(crossing(wcs, (600, 400), (600, 400), speed=50),
                                                 crossing(wcs, (602, 403), (600, 400), speed=50)))
    found = streak.match(STREAK, wcs, scale, [("SAT-A", 1, None), ("SAT-B", 2, None)], times(), START, 16.0, {})
    assert all(m["fits"] for m in found)
    said = streak.verdict(STREAK, found, scale)
    assert "2 satellites fit" in said and "neither can be named" in said


def test_with_no_satellite_it_says_so_without_guessing():
    _, scale = frame_wcs()
    said = streak.verdict(STREAK, [], scale)
    assert "No satellite in the list accounts for it" in said


def test_a_frame_with_a_streak_is_checked_whole(tmp_path, monkeypatch):
    path = tmp_path / "light-0004.fits"
    header = fits.Header({"EXPTIME": 16.0, "DATE-OBS": START.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]})
    fits.PrimaryHDU(line(sky(), (300, 200), (900, 600)).astype(np.float32), header).writeto(path)
    wcs, scale = frame_wcs()
    monkeypatch.setattr(streak, "solved", lambda p, image: (wcs, scale))
    monkeypatch.setattr(streak, "orbits_for", lambda when, offline: (tmp_path / "active-20261018-2155.csv",
                                                                      START + timedelta(minutes=7)))
    monkeypatch.setattr(streak, "read_orbits", lambda p: [("ONEWEB-0331", 47273, None)])
    monkeypatch.setattr(streak, "sgp4_or_refuse", lambda: None)
    monkeypatch.setattr(streak, "places", placed(crossing(wcs, (600, 400), (600, 400), speed=50)))
    monkeypatch.setattr(config, "load", config.example)
    answer, warnings = streak.check(path, say=lambda *_: None)
    assert answer["start"].startswith("2026-10-18T21:47:59.404") and answer["exposure_s"] == 16.0
    assert answer["streaks"][0]["named"] == "ONEWEB-0331" and warnings == []


# --- times and orbits ---------------------------------------------------------

def test_a_frame_without_its_own_time_is_placed_from_when_it_arrived(tmp_path):
    (tmp_path / "frames.jsonl").write_text('{"index": 4, "taken": %f}\n' % (START.timestamp() + 16.9))
    start, seconds, how = streak.exposure(tmp_path / "light-0004.fits", fits.Header({"EXPTIME": 16.0}))
    assert abs((start - START).total_seconds() - 0.9) < 0.01 and "arrived" in how
    with pytest.raises(interface.Refusal):
        streak.exposure(tmp_path / "light-0005.fits", fits.Header({"EXPTIME": 16.0}))


def test_the_orbits_nearest_the_frame_are_used_and_fetched_only_when_none_are_near(tmp_path, monkeypatch):
    monkeypatch.setattr(streak, "ORBITS", tmp_path)
    for name in ("active-20261012-2000.csv", "active-20261018-2155.csv"):
        (tmp_path / name).write_text("OBJECT_NAME\n")
    fetched = []
    monkeypatch.setattr(streak, "fetch_orbits", lambda now: fetched.append(now) or tmp_path / "new.csv")
    path, when = streak.orbits_for(START, now=START + timedelta(hours=1))
    assert path.name == "active-20261018-2155.csv" and not fetched
    path, _ = streak.orbits_for(datetime(2026, 10, 13, 21, tzinfo=timezone.utc), now=START)
    assert path.name == "active-20261012-2000.csv" and not fetched     # an old frame: no fetch
    later = START + timedelta(days=4)
    streak.orbits_for(later, now=later + timedelta(minutes=5))
    assert fetched                                                     # a recent frame with none near: fetch
    fetched.clear()
    path, _ = streak.orbits_for(later, offline=True, now=later)
    assert not fetched and path.name == "active-20261018-2155.csv"


ISS = ("OBJECT_NAME,OBJECT_ID,EPOCH,MEAN_MOTION,ECCENTRICITY,INCLINATION,RA_OF_ASC_NODE,ARG_OF_PERICENTER,"
       "MEAN_ANOMALY,EPHEMERIS_TYPE,CLASSIFICATION_TYPE,NORAD_CAT_ID,ELEMENT_SET_NO,REV_AT_EPOCH,BSTAR,"
       "MEAN_MOTION_DOT,MEAN_MOTION_DDOT\n"
       "ISS (ZARYA),1998-067A,2026-10-18T11:12:47.041632,15.48923373,.00067835,51.6327,50.0298,279.2532,"
       "80.7689,0,U,25544,999,59086,.14361462E-3,.7452E-4,0\n")


def test_sgp4_places_agree_with_astropys_own_route(tmp_path):
    pytest.importorskip("sgp4")
    from astropy import units as u
    from astropy.coordinates import ITRS, TEME, AltAz, CartesianRepresentation, EarthLocation, SkyCoord
    from astropy.time import Time
    (tmp_path / "o.csv").write_text(ISS)
    satellites = streak.read_orbits(tmp_path / "o.csv")
    assert satellites[0][:2] == ("ISS (ZARYA)", 25544)
    site = config.example()["site"]
    ra, dec, distance, _ = streak.places(satellites, [START], site)
    t = Time(START)
    place = EarthLocation(lon=site["longitude"] * u.deg, lat=site["latitude"] * u.deg,
                          height=site.get("elevation_m", 0) * u.m)
    _, r, _ = satellites[0][2].sgp4(t.utc.jd1, t.utc.jd2)
    itrs = TEME(CartesianRepresentation(r * u.km), obstime=t).transform_to(ITRS(obstime=t))
    seen = ITRS(itrs.cartesian - place.get_itrs(t).cartesian, obstime=t, location=place)
    frame = AltAz(obstime=t, location=place)
    mine = SkyCoord(ra[0, 0] * u.deg, dec[0, 0] * u.deg).transform_to(frame)
    # Within the 20" of the Earth's motion (aberration), which the stars carry too.
    assert seen.transform_to(frame).separation(mine).arcsec < 30
    assert distance[0, 0] == pytest.approx(np.linalg.norm(seen.cartesian.xyz.to_value(u.km)), rel=1e-4)


def test_the_answer_matches_its_schema(tmp_path, monkeypatch):
    from test_interface import valid
    test_a_frame_with_a_streak_is_checked_whole(tmp_path, monkeypatch)
    answer, warnings = streak.check(tmp_path / "light-0004.fits", say=lambda *_: None)
    valid(interface.run("streak", lambda: (answer, warnings)), "streak")
