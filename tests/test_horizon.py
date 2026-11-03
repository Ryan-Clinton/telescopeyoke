"""The skyline: reading it from a frame, following it with the telescope,
taking it from a phone panorama, and the planner keeping targets above it."""
import json
import math
import shutil
import time

import numpy as np
import pytest
from PIL import Image

import config
import horizon
import interface
import panorama


@pytest.fixture
def kept(tmp_path, monkeypatch):
    """Somewhere of this test's own for the skyline and the panoramas."""
    monkeypatch.setattr(horizon, "RESULTS", tmp_path / "cache" / "horizon.json")
    monkeypatch.setattr(panorama, "FOLDER", tmp_path / "horizon")
    monkeypatch.setattr(panorama, "STATE", tmp_path / "horizon" / "panorama.json")
    monkeypatch.setattr(panorama, "MARKED", tmp_path / "horizon" / "skyline.jpg")
    return tmp_path


# --- one frame -----------------------------------------------------------------

def frame(level=1300, rows=640, cols=960):
    return np.full((rows, cols), level, np.uint16)


def test_a_daytime_frame_is_read_square_by_square():
    sky = frame()
    dusty = sky.copy()
    dusty[100:110, 200:210] = 300            # a dust speck is not a wall
    assert horizon.read_day(sky, 1300)["view"] == "sky" and horizon.read_day(dusty, 1300)["view"] == "sky"
    assert horizon.read_day(frame(780), 1300)["view"] == "sky"       # sky is dimmer low down
    assert horizon.read_day(frame(250), 1300)["view"] == "blocked"

    # A roof across the middle: the frame holds the top, in the middle.
    rooftop = sky.copy()
    rooftop[320:] = 250
    seen = horizon.read_day(rooftop, 1300)
    assert seen["view"] == "edge" and seen["share"] == 0.5 and abs(seen["offset"]) < 0.05
    # A roof across the lowest quarter: the top is a quarter of a frame below the middle.
    low_roof = sky.copy()
    low_roof[480:] = 250
    seen = horizon.read_day(low_roof, 1300)
    assert seen["view"] == "edge" and seen["offset"] == pytest.approx(-0.25, abs=0.05)
    # The same roof whichever way up the camera sits: the sky's side counts as up.
    assert horizon.read_day(low_roof[::-1], 1300)["offset"] == pytest.approx(-0.25, abs=0.05)
    # On its side, the frame is narrower that way: the same roof is a smaller share of its height off.
    assert horizon.read_day(low_roof.T, 1300)["offset"] == pytest.approx(-0.25 * 640 / 960, abs=0.05)


def test_a_burnt_out_daytime_frame_is_never_sky():
    # 2 November 2026: with the Sun low, every look came back burnt out and
    # was read as sky, walls and all. Burnt out says only "too bright to read".
    from camera import WHITE
    burnt = frame(WHITE)
    seen = horizon.read_day(burnt, 1300)
    assert seen["view"] == "burnt" and seen["share"] == 0.0
    # A bright patch in a frame of sky is still sky: only a frame mostly burnt is unread.
    patch = frame(1300)
    patch[:100] = WHITE
    assert horizon.read_day(patch, 1300)["view"] == "sky"


def test_a_view_metered_again_is_compared_with_the_same_high_sky():
    today = {"level": 1300.0, "grain": 0.01, "blue": None}
    # A tenth of the time: the high sky would read a tenth as bright.
    shorter = horizon.at_exposure(today, 0.002, 0.0002)
    assert shorter["level"] == pytest.approx(130.0) and today["level"] == 1300.0
    # The same reading of 250: at a tenth of the time it is sky twice as
    # bright as the high sky; at the high sky's own time it is a wall.
    assert horizon.read_day(frame(250), shorter)["view"] == "sky"
    assert horizon.read_day(frame(250), today)["view"] == "blocked"


def test_branches_against_the_sky_are_not_sky_and_colour_only_tips_the_balance():
    rng = np.random.default_rng(1)
    # Blue sky: the blue pixels of each colour cell twice the red ones.
    sky = frame(1000).astype(np.float32)
    sky[1::2, 1::2], sky[0::2, 0::2] = 1500, 750
    sky = (sky + rng.normal(0, 8, sky.shape)).astype(np.uint16)
    today = horizon.sky_reference(sky)
    assert today["blue"] == pytest.approx(2.0, abs=0.05) and horizon.read_day(sky, today)["view"] == "sky"
    # Twigs: as bright as sky on average and as blue, but nothing like smooth.
    twigs = sky.copy()
    twigs[rng.random(sky.shape) < 0.3] = 150
    assert horizon.read_day(twigs, today)["view"] == "blocked"
    # Overcast: grey, not blue, and still sky.
    grey = (frame(1000) + rng.normal(0, 8, sky.shape)).astype(np.uint16)
    assert horizon.read_day(grey, today)["view"] == "sky"
    # A wall in shade, lit by the sky and so as blue as it: too dark all the same.
    assert horizon.read_day((sky * 0.2).astype(np.uint16), today)["view"] == "blocked"
    # Dim sky low down counts if its colour is the sky's, and not if it is brick's.
    dim = (sky * 0.3).astype(np.uint16)
    brick = dim.copy()
    brick[1::2, 1::2], brick[0::2, 0::2] = dim[0::2, 0::2], dim[1::2, 1::2]
    assert horizon.read_day(dim, today)["view"] == "sky" and horizon.read_day(brick, today)["view"] == "blocked"


def test_a_frame_of_stars_with_a_roof_across_it_holds_the_top():
    rng = np.random.default_rng(2)
    shape = (1824, 2720)
    spread = rng.random((30, 2)) * shape
    assert horizon.read_night(spread, shape) == {"view": "sky", "stars": 30, "share": 1.0}
    assert horizon.read_night(spread[:5], shape)["view"] == "blocked"
    # Thirty stars, none in the lowest 60% of the frame: that is not chance.
    crowded = spread * (0.4, 1)
    seen = horizon.read_night(crowded, shape)
    assert seen["view"] == "edge" and 0.3 < seen["share"] <= 0.4 and seen["offset"] > 0.1
    # Eight stars that happen to leave a fifth of the frame empty: that is.
    assert horizon.read_night(spread[:8] * (0.8, 1), shape)["view"] == "sky"


def test_the_star_counter_says_where_the_stars_are():
    import skywatch
    lum = np.random.default_rng(3).normal(100, 3, (400, 600)).astype(np.float32)
    for row, col in ((50, 80), (300, 500), (200, 300)):
        lum[row - 1:row + 2, col - 1:col + 2] += 400
    places = skywatch.star_places(lum)
    assert skywatch.count_stars(lum) == len(places) == 3
    assert sorted(tuple(int(round(v)) for v in p) for p in places) == [(50, 80), (200, 300), (300, 500)]


# --- following it with the telescope ---------------------------------------------

def garden(az):
    """A house to the south 40° high, a tree at 300° reaching 58°, a fence
    below the lowest look everywhere else."""
    return 40 if 140 <= az <= 220 else 58 if 295 <= az <= 305 else 10


def watcher(skyline=garden, in_view=0.0):
    """A look that answers from a made-up skyline. A top within `in_view`
    degrees of where it looks is in the frame, and its height is the answer."""
    seen = []

    def look(az, alt):
        seen.append((az, alt))
        if abs(alt - skyline(az)) <= in_view:
            return float(skyline(az))
        return alt > skyline(az)
    look.seen = seen
    return look


def test_bearings_are_added_only_where_the_skyline_needs_them():
    look = watcher()
    found, warnings = horizon.trace(look, sorted(range(0, 360, horizon.START), key=horizon.side), low=20)
    assert not warnings
    bearings = [f["az"] for f in found]
    # Twelve to start with; more at the house's ends and round the tree, none along the fence.
    assert 12 < len(bearings) <= 24 and not any(30 < az < 120 for az in bearings if az % 30)
    assert any(120 < az < 150 for az in bearings) and any(210 < az < 240 for az in bearings)
    assert len(look.seen) < 70
    skyline = horizon.skyline_from(found, 20)
    # Never lower than what is really there, and right except within a bearing's width of a corner.
    off = [float(horizon.limit(skyline, [az])[0]) - max(garden(az), 20) for az in range(360)]
    assert min(off) >= 0 and np.mean(np.array(off) > horizon.FINE) < 0.15


def test_a_bump_between_level_neighbours_gets_a_look_each_side():
    # No two neighbours differ by a corner's worth, but 90° stands off the line through its neighbours.
    bump = lambda az: 25 + 5 * max(0, 1 - abs(az - 90) / 25)
    found, _ = horizon.trace(watcher(bump), sorted(range(0, 360, 30), key=horizon.side), low=20)
    assert {75, 105} <= {f["az"] for f in found} and len(found) <= 16


def test_a_survey_starts_from_the_skyline_already_known():
    start = sorted(range(0, 360, 30), key=horizon.side)
    fresh = watcher()
    found, _ = horizon.trace(fresh, start, low=20)
    known = horizon.skyline_from(found, 20)
    again = watcher()
    checked, warnings = horizon.trace(again, start, low=20, known=known)
    assert not warnings and len(checked) == 12 and len(again.seen) < len(fresh.seen) / 2
    # The detail the first survey found survives the check.
    assert len(horizon.skyline_from(checked, 20, known)) >= len(known)

    # The hedge to the east has grown since: only there does it look further.
    grown = lambda az: 35 if 80 <= az <= 100 else garden(az)
    changed, _ = horizon.trace(watcher(grown), start, low=20, known=known)
    extra = {f["az"] for f in changed} - set(start)
    assert extra and all(60 <= az <= 120 for az in extra)
    now = horizon.skyline_from(changed, 20, known)
    assert float(horizon.limit(now, [90])[0]) >= 35 and float(horizon.limit(now, [180])[0]) >= 40


def test_a_top_seen_in_the_frame_ends_the_search_there():
    look = watcher(lambda az: 37.2, in_view=0.33)
    found = horizon.top_of(look, 90, 37, low=20)
    assert found == {"az": 90, "state": "edge", "shut": 37.2, "clear": 37.2, "in_view": True}
    assert look.seen == [(90, 37)]
    # From further off it is searched for as before, and still ends on the frame that shows it.
    look = watcher(lambda az: 38.0, in_view=0.33)
    assert horizon.top_of(look, 90, 20, low=20)["clear"] == 38.0


def test_between_two_bearings_the_top_is_tried_at_one_height_and_then_the_other():
    look = watcher(lambda az: 10)
    assert horizon.top_of(look, 45, 40, low=20, or_else=20)["state"] == "open"
    assert look.seen == [(45, 40), (45, 37), (45, 20)]
    look = watcher(lambda az: 39)
    assert horizon.top_of(look, 45, 40, low=20, or_else=20)["clear"] == 40 and len(look.seen) == 2


# --- the skyline the planner uses --------------------------------------------------

SKYLINE = [{"az": 0, "alt": 20, "open": True}, {"az": 90, "alt": 40}, {"az": 180, "alt": 40},
           {"az": 270, "alt": 20, "open": True}]


def test_the_margin_goes_on_what_was_measured_and_not_on_open_sky():
    assert list(horizon.limit(SKYLINE, [0, 45, 90, 135, 300])) == [20, 30, 40, 40, 20]
    assert list(horizon.limit(SKYLINE, [0, 45, 90, 135, 300], margin=2)) == [20, 31, 42, 42, 20]
    assert list(horizon.limit([{"az": 10, "alt": 89, "extra": 5}], [10], 2)) == [90]
    assert list(horizon.limit([], [10, 20])) == [0, 0]


def test_the_planner_keeps_targets_above_the_measured_skyline():
    import sky
    cfg = config.example()
    cfg["horizon"].update(skyline=SKYLINE, margin=3, blocked=[{"from": 80, "to": 100, "altitude": 50}])
    night = sky.Night(cfg)
    assert list(night.horizon(np.array([0.0, 90.0, 180.0, 300.0]), 20)) == [20, 50, 43, 20]
    # Without one, nothing changes.
    assert list(sky.Night(config.example()).horizon(np.array([180.0]), 20)) == [20]


def test_the_settings_say_whether_the_measured_skyline_is_used(kept, monkeypatch):
    settings = kept / "config.toml"
    shutil.copy(config.EXAMPLE, settings)
    monkeypatch.setattr(config, "FILE", settings)
    monkeypatch.setattr(config, "DEMO", False)
    assert config.load()["horizon"]["skyline"] == [] and config.load()["horizon"]["margin"] == 2
    horizon.keep(SKYLINE, "telescope")
    assert config.load()["horizon"]["skyline"] == SKYLINE
    assert "skyline" not in config.example()["horizon"]         # the example is not that garden
    config.save({("horizon", "use_survey"): False, ("horizon", "margin"): 4.5})
    assert "skyline" not in config.load()["horizon"] and config.load()["horizon"]["margin"] == 4.5
    assert config.checked("horizon", "margin", "3") == 3
    with pytest.raises(ValueError):
        config.checked("horizon", "margin", 30)


def test_show_and_forget(kept, capsys):
    assert horizon.show(20, 2) == {"skyline": None}
    horizon.keep(SKYLINE, "panorama", warnings=["look south"])
    told = horizon.show(20, 2)
    out = capsys.readouterr().out
    assert told["source"] == "panorama" and {"az": 90, "alt": 42.0} in told["usable"]
    assert "a phone panorama" in out and "usable from 42°" in out and "CHECK: look south" in out
    # An older file, from before skylines were kept as points, is not mistaken for one.
    horizon.RESULTS.write_text(json.dumps({"skyline": [{"az": 0, "state": "open", "clear": 20}]}), encoding="utf-8")
    assert horizon.measured() == {}


# --- a phone panorama ----------------------------------------------------------------

WIDE, TALL = 1800, 300          # a made-up panorama: 0.2° a pixel, once round the compass
RADIUS = 1 / math.radians(0.2)  # so this many pixels to the cylinder it was taken on
LEVEL = 280                     # the row the true horizon is at


def top_at(az):
    """What stands in the made-up garden: a house, a tree and a low fence."""
    return 35 if 100 <= az <= 160 else 30 - abs(az - 250) / 2 if 210 <= az <= 290 else 5


def row_of(alt):
    return LEVEL - RADIUS * math.tan(math.radians(alt))


def made_up(path, start=20.0, wide=WIDE, tall=TALL, level=LEVEL):
    """The garden as a phone would stitch it, starting at bearing `start`."""
    rng = np.random.default_rng(4)
    rows = np.arange(tall)[:, None]
    picture = np.zeros((tall, wide, 3), np.float32)
    picture[...] = (120, 160, 225)                                  # blue sky
    picture += (rows / tall * 60)[..., None] * (1, 0.6, 0.2)        # paler towards the horizon
    for col in range(wide):
        top = max(round(level - RADIUS * math.tan(math.radians(top_at((start + col * 0.2) % 360)))), 0)
        picture[top:, col] = rng.normal(70, 25, (tall - top, 3)) if top < tall else 0
    Image.fromarray(np.clip(picture, 0, 255).astype(np.uint8)).save(path, quality=95)
    return path


def test_the_skyline_is_found_in_a_panorama(tmp_path):
    line = panorama.skyline_in(Image.open(made_up(tmp_path / "garden.jpg")))
    assert len(line) == panorama.POINTS
    above = [row_of(top_at((20 + x * WIDE * 0.2) % 360)) - y * TALL for x, y in line
             if min(abs((20 + x * WIDE * 0.2) % 360 - corner) for corner in (100, 160, 210, 290)) > 3]
    # In pixels, five to a degree. Each point takes the highest thing in its
    # strip, so it errs upwards, on the tree's slopes most.
    assert min(above) > -2 and max(above) < 12


def test_two_marks_tie_a_panorama_to_the_compass(kept, tmp_path):
    def run(*words, **more):
        args = panorama.argparse.Namespace(values=list(words), picture=more.get("picture", 1),
                                           landmark=more.get("landmark"), telescope=False)
        return panorama.COMMANDS[words[0]](argparse_tail(args))

    def argparse_tail(args):
        args.values = args.values[1:]
        return args

    told = run("use", str(made_up(tmp_path / "garden.jpg")))
    assert not told["ready"] and told["pictures"][0]["fit"] is None
    with pytest.raises(interface.Refusal):
        run("save")
    # The house's corner at bearing 100°, 35° up; the tree's top at 250°, 30° up.
    run("mark", str((100 - 20) / 0.2), str(row_of(35)), "100", "35")
    told = run("mark", f"{(250 - 20) / 0.2 / WIDE:.4f}", f"{row_of(30) / TALL:.4f}", "250", "30")
    fit = told["pictures"][0]["fit"]
    assert told["ready"] and fit["degrees_wide"] == pytest.approx(360, abs=2)
    (result, warnings) = run("save")
    assert not warnings and horizon.measured()["source"] == "panorama"
    skyline = horizon.measured()["skyline"]
    for az in (60, 130, 190, 230, 250, 270, 330):
        assert float(horizon.limit(skyline, [az])[0]) == pytest.approx(top_at(az), abs=2), az
    assert (kept / "horizon" / "skyline.jpg").exists() and (kept / "horizon" / "panorama-1.jpg").exists()

    # A third mark that agrees says so; one in the wrong place is told on.
    told = run("mark", str((130 - 20) / 0.2), str(row_of(10)), "130", "10")
    assert told["pictures"][0]["fit"]["worst_deg"] < 1
    run("mark", str((330 - 20) / 0.2), str(row_of(5)), "330", "25")
    assert any("disagree on height" in w for w in run("save")[1])
    run("unmark", "4")

    # Putting the line right by hand: the nearest point of it goes where it is told.
    told = run("move", f"{(190 - 20) / 0.2:.0f},{row_of(20):.0f}")
    assert told["pictures"][0]["changed"] == 1
    run("save")
    assert float(horizon.limit(horizon.measured()["skyline"], [190])[0]) == pytest.approx(20, abs=3)

    # Marks above one another say nothing about how wide the picture is.
    run("clear")
    run("use", str(tmp_path / "garden.jpg"))
    run("mark", "0.5", "0.2", "100", "35")
    assert "almost above one another" in run("mark", "0.505", "0.6", "100", "5")["pictures"][0]["fit"]["problem"]


def test_part_of_the_compass_is_left_unknown_not_guessed(kept, tmp_path):
    # A panorama of the south-east only: bearings 80° to 200°, the house in the middle of it.
    made_up(tmp_path / "part.jpg", start=80, wide=600)
    now = {"pictures": []}
    picture = panorama.take(tmp_path / "part.jpg", now)
    picture["marks"] = [{"x": 100 / 600, "y": row_of(35) / TALL, "az": 100, "alt": 35, "from": "typed in"},
                        {"x": 400 / 600, "y": row_of(35) / TALL, "az": 160, "alt": 35, "from": "typed in"}]
    panorama.keep(now)
    args = panorama.argparse.Namespace(values=[], picture=1)
    _, warnings = panorama.save(args)
    assert any("not in the picture" in w for w in warnings)
    skyline = horizon.measured()["skyline"]
    assert float(horizon.limit(skyline, [130], 2)[0]) == pytest.approx(37, abs=2)
    assert list(horizon.limit(skyline, [0, 60, 220, 300], 2)) == [0, 0, 0, 0]
    # The telescope, checking it, finds a wall the picture did not reach, and keeps the house's detail.
    whole = lambda az: 45 if 280 <= az <= 320 else top_at(az)
    found, _ = horizon.trace(watcher(whole), sorted(range(0, 360, 30), key=horizon.side), low=20, known=skyline)
    both = horizon.skyline_from(found, 20, skyline)
    assert float(horizon.limit(both, [300])[0]) >= 45 and float(horizon.limit(both, [130])[0]) == pytest.approx(35, abs=3)
    assert not any(p.get("unseen") for p in both)


def test_the_top_out_of_the_picture_is_at_least_that_high(kept, tmp_path):
    # Held too low: the house goes off the top of the picture.
    made_up(tmp_path / "low.jpg", tall=150, level=150)
    now = {"pictures": []}
    picture = panorama.take(tmp_path / "low.jpg", now)
    picture["marks"] = [{"x": 0.1, "y": 0.5, "az": 56, "alt": math.degrees(math.atan((150 - 75) / RADIUS)), "from": "typed in"},
                        {"x": 0.6, "y": 0.5, "az": 236, "alt": math.degrees(math.atan((150 - 75) / RADIUS)), "from": "typed in"}]
    panorama.keep(now)
    assert panorama.describe(now)["pictures"][0]["above_picture"] > 10
    _, warnings = panorama.save(panorama.argparse.Namespace(values=[], picture=1))
    assert any("above the picture" in w for w in warnings)
    assert any(p.get("least") for p in horizon.measured()["skyline"])


def test_another_height_adds_doubt_where_its_skyline_differs():
    first = [{"az": az, "alt": 30.0} for az in range(1, 360, 2)]
    other = [{"az": az, "alt": 34.0 if 100 < az < 140 else 30.4} for az in range(1, 360, 2)]
    most, where = panorama.doubt(first, [other])
    assert most == 4 and 100 < where < 140
    assert all(p.get("extra") == 4 for p in first if 100 < p["az"] < 140)
    assert not any("extra" in p for p in first if not 100 < p["az"] < 140)
    assert float(horizon.limit(first, [120], 2)[0]) == 36


def test_a_torch_along_the_tube_tells_a_wall_from_cloud():
    """Stars alone cannot: no stars is a house or it is cloud. Lit by the
    torch it is in the way, however many "stars" a burnt-out frame claims;
    dark with no stars it cannot be told, and is never taken for open sky."""
    sky = {"view": "sky", "stars": 40, "share": 1.0}
    none = {"view": "blocked", "stars": 0, "share": 0.0}
    assert horizon.read_torch(sky, 51, 0.0, None) == dict(sky, level=51.0)
    wall = horizon.read_torch(none, 2186, 0.0, 51)
    assert wall["view"] == "blocked" and wall["lit"]
    thin = horizon.read_torch(sky, 138, 0.0, 51)                            # bright, but stars show: thin cloud
    assert thin["view"] == "sky" and not thin.get("lit")
    # Bright with no stars high overhead is no tree: cloud has come over,
    # and the survey must stop, not call the sky blocked.
    assert horizon.overcast(75, horizon.read_torch(none, 420, 0.0, 55))
    assert not horizon.overcast(31, horizon.read_torch(none, 312, 0.0, 61))   # a tree, low down
    assert not horizon.overcast(75, horizon.read_torch(sky, 60, 0.0, 55))
    burnt = horizon.read_torch(dict(sky, stars=6780), 4094, 0.9, None)      # a 3 s frame of the same wall
    assert burnt["view"] == "blocked" and burnt["lit"]
    cloud = horizon.read_torch(none, 60, 0.0, 51)
    assert cloud["view"] == "unknown" and cloud["share"] == 0.0
    # Before any frame of stars has said how dark the sky is, only a burnt
    # frame can be called lit.
    assert horizon.read_torch(none, 400, 0.0, None)["view"] == "unknown"


def test_the_profile_prints_a_bearing_blocked_as_far_up_as_it_looked():
    # 17 October 2026: the first real trace was kept, then failed printing
    # this, as every state's words were made, the missing top among them.
    found = [{"az": 0, "state": "open", "clear": 66}, {"az": 90, "state": "edge", "clear": 39.0},
             {"az": 300, "state": "blocked", "clear": None}, {"az": 330, "state": "unreachable", "clear": None}]
    text = horizon.profile(found, 20)
    assert "open down to 66°" in text and "blocked up to 39°" in text
    assert "blocked as far up as it looked" in text and "not reachable" in text


def test_a_wall_seen_from_further_away_is_lower_and_from_nearer_higher():
    # A wall 10 m north of the old spot, 45° up from there: 10 m high.
    wall = [{"az": float(az), "alt": 45.0 if az in (0, 350, 10) else 0.0} for az in range(0, 360, 10)]
    everywhere = [(0, 359.9, 10)]
    back = horizon.moved(wall, 5, 180, everywhere)        # 5 m further south: 15 m from the wall
    near = horizon.moved(wall, 5, 0, everywhere)           # 5 m nearer: 5 m from it
    at = lambda sky, az: next(p["alt"] for p in sky if p["az"] == az)
    assert at(back, 0) == pytest.approx(math.degrees(math.atan2(10, 15)), abs=0.6)
    assert at(near, 0) == pytest.approx(math.degrees(math.atan2(10, 5)), abs=0.6)
    assert all(p["moved"] and p["extra"] == horizon.MOVED_DOUBT for p in back)


def test_moving_a_skyline_needs_a_distance_all_round():
    with pytest.raises(interface.Refusal):
        horizon.moved([{"az": 0.0, "alt": 30.0}], 5, 90, [(0, 90, 10)])


def test_a_survey_mostly_too_bright_to_read_is_not_kept():
    seen = [{"az": 0, "alt": 75, "open": True}, {"az": 30, "alt": 66, "open": False}]
    glare = [{"az": a, "alt": 20, "open": None, "glare": True} for a in (120, 150, 180)]
    refused = [{"az": 90, "alt": 10, "open": None}]               # out of the mount's reach: not counted
    assert horizon.glare_share(seen + refused) == 0.0
    assert horizon.glare_share(seen + glare + refused) == pytest.approx(0.6)
    assert horizon.glare_share(seen + glare) > horizon.GLARE_MOST
    assert horizon.glare_share([]) == 0.0
    # A night look that could not be told counts the same as glare.
    assert horizon.glare_share(seen + [{"az": 9, "alt": 40, "open": None, "unread": True}]) == pytest.approx(1 / 3)


def test_a_bearing_not_measured_is_blocked_not_open():
    # 2 November 2026: what could not be seen was taken for sky. A bearing
    # the survey could not measure must never borrow its neighbours' sky.
    found = [{"az": 0, "state": "open", "clear": 20, "shut": None},
             {"az": 90, "state": "unreachable", "clear": None, "shut": None},
             {"az": 180, "state": "open", "clear": 20, "shut": None},
             {"az": 270, "state": "open", "clear": 20, "shut": None}]
    skyline = horizon.skyline_from(found, 20)
    assert any(p.get("unmeasured") and p["az"] == 90 for p in skyline)
    assert horizon.limit(skyline, [90])[0] == 90                 # nothing planned where nothing was seen
    assert horizon.limit(skyline, [225])[0] == pytest.approx(20)   # between two measured bearings: as measured


def test_a_look_it_could_not_read_is_tried_again_before_anything_is_kept():
    # 2 November 2026: unread looks were taken for sky. Now a bearing that
    # could not be read is looked at again once the rest is done: what
    # cleared (cloud gone, the Sun moved on) is measured, what did not is
    # kept as not measured.
    first_time = {90}
    log = []

    def look(az, alt):
        if az == 150 or az in first_time:
            first_time.discard(az)
            log.append({"az": az, "alt": alt, "open": None, "glare": True})
            return None
        log.append({"az": az, "alt": alt, "open": alt > 30})
        return alt > 30
    look.log = log
    found, warnings = horizon.trace(look, sorted(range(0, 360, 30), key=horizon.side), low=20)
    state = {f["az"]: f["state"] for f in found}
    assert state[90] in ("edge", "open") and state[150] == "unreachable"
    assert any("still unread at 150°" in w for w in warnings)
    skyline = horizon.skyline_from(found, 20)
    assert horizon.limit(skyline, [150])[0] == 90                # never seen: nothing planned there
    blind = [e for e in log if e.get("glare") and not e.get("resolved")]
    assert blind and all(e["az"] == 150 for e in blind)          # only what never cleared counts against it
    assert all(e.get("resolved") for e in log if e["az"] == 90 and e.get("glare"))


@pytest.mark.parametrize("angle", [0, 30, 45, 60, 90, 135, 180, 270])
def test_a_top_in_the_frame_is_read_the_same_however_the_camera_is_turned(angle):
    # A roof whose top is a quarter of a frame below the middle. Things in
    # the way stand on the ground, so the sky's side is up whatever way the
    # camera sits on the mount; the height comes out within 0.15 of a frame
    # (a tenth of a degree), far inside the planner's 2° margin.
    rows, cols = 640, 960
    y, x = np.indices((rows, cols))
    turn = math.radians(angle)
    up = (rows / 2 - y) * math.cos(turn) + (x - cols / 2) * math.sin(turn)
    seen = horizon.read_day(np.where(up > -0.25 * rows, 1300, 250).astype(np.uint16), 1300)
    assert seen["view"] == "edge" and seen["offset"] == pytest.approx(-0.25, abs=0.15)


def test_each_point_says_what_measured_it_and_a_panorama_stands_where_the_telescope_could_not_look():
    known = [{"az": az, "alt": 30.0} for az in range(0, 360, 10)]
    known[9] = {"az": 90, "alt": 50.0}                          # the panorama saw a roof at 90°
    found = [{"az": 0, "state": "open", "clear": 20, "shut": None},
             {"az": 90, "state": "unreachable", "clear": None, "shut": None},
             {"az": 180, "state": "edge", "clear": 35, "shut": 34},
             {"az": 270, "state": "open", "clear": 20, "shut": None}]
    skyline = horizon.skyline_from(found, 20, known)
    at = {p["az"]: p for p in skyline}
    assert at[180]["by"] == "telescope" and at[180]["alt"] == 35
    assert at[90]["alt"] == 50.0 and at[90]["by"] == "earlier skyline, not rechecked"   # not pushed to 90°
    assert any(p["by"].startswith("earlier skyline, moved") for p in skyline)
    # With nothing known before, the same bearing is blocked and says so.
    alone = {p["az"]: p for p in horizon.skyline_from(found, 20)}
    assert alone[90]["alt"] == 90.0 and alone[90]["by"] == "nothing: not measured"


def test_a_survey_set_aside_never_replaces_the_skyline_in_use(kept):
    horizon.keep([{"az": 0, "alt": 30}], "telescope")
    before = horizon.RESULTS.read_text()
    aside = horizon.set_aside([{"az": 0, "alt": 20}], "Not repeatable: the mount slipped")
    assert horizon.RESULTS.read_text() == before
    assert aside.parent == horizon.RESULTS.parent and "not-used" in aside.name
    assert json.loads(aside.read_text())["not_used_because"].startswith("Not repeatable")


def test_a_survey_cut_short_carries_on_from_where_it_stopped(tmp_path):
    """2 November 2026: a survey stopped at its first look began again from nothing."""
    start = sorted(range(0, 360, 30), key=horizon.side)
    path = tmp_path / "partial.json"
    whole = watcher()
    complete, _ = horizon.trace(whole, start, low=20)

    class Stopped(Exception):
        pass
    kept = []

    def checkpoint(found):
        horizon.keep_partial(found, [], True, path=path)
        kept.append(len(found))
        if len(found) == 5:
            raise Stopped           # the camera jams, or it is stopped by hand
    with pytest.raises(Stopped):
        horizon.trace(watcher(), start, low=20, checkpoint=checkpoint)
    done, looks = horizon.resumable(True, path=path)
    assert len(done) == 5 and looks == []
    again = watcher()
    found, _ = horizon.trace(again, start, low=20, done=done)
    assert {f["az"] for f in found} == {f["az"] for f in complete}
    # The five already measured are not looked at again.
    assert len(again.seen) == len(whole.seen) - 5
    # Only a survey of the same kind, and only the same day.
    assert horizon.resumable(False, path=path) is None
    assert horizon.resumable(True, path=path, now=time.time() + horizon.RESUME_S + 1) is None


def test_a_lone_opening_between_high_tops_is_taken_as_blocked_to_the_lower_and_said():
    """2 November 2026: 97.5° read open to 20° between tops near 40°."""
    gap = lambda az: 10 if 95 <= az <= 100 else 40 if 60 <= az <= 135 else garden(az)
    start = sorted(set(range(0, 360, 30)) | {90, 97.5, 105}, key=horizon.side)
    found, warnings = horizon.trace(watcher(gap, in_view=1.5), start, low=20)
    # The person outside said neither due east nor due south was open low:
    # taken as blocked to the lower of its neighbours' tops.
    lone = next(f for f in found if f["az"] == 97.5)
    assert lone["state"] == "edge" and lone["read_open"] == 20 and lone.get("doubt")
    assert lone["clear"] == min(f["clear"] for f in found if f["az"] in (90, 105))
    assert any(w.startswith("Bearing 97.5°: read open down to 20°") for w in warnings)
    point = next(p for p in horizon.skyline_from(found, 20) if p["az"] == 97.5)
    assert point["alt"] == lone["clear"] and "extra" not in point and "read open" in point["by"]


def test_the_repeat_check_is_made_off_the_meridian_and_says_when_the_tube_changed_sides():
    assert not horizon.off_meridian(0) and not horizon.off_meridian(170) and horizon.off_meridian(60)
    start = sorted(range(0, 360, 30), key=horizon.side)
    look = watcher()
    horizon.trace(look, start, low=20)
    assert look.seen[-1][0] == 30           # back to 30°, not to due north

    # The second visit lands somewhere else, from the other side of the pole.
    visits = {}

    def drifting(az, alt):
        visits[az] = visits.get(az, 0) + 1
        moved = az == 30 and visits[az] > 1
        drifting.log.append({"az": az, "alt": alt, "over": moved})
        return alt > (45 if moved else garden(az))
    drifting.log = []
    _, warnings = horizon.trace(drifting, start, low=20)
    repeat = [w for w in warnings if w.startswith(horizon.NOT_SAME)]
    assert repeat and "other side of the pole" in repeat[0]


def test_a_survey_set_aside_is_kept_only_on_a_persons_word(monkeypatch, tmp_path):
    """2 November 2026: the repeat look at due north disagreed; the person
    outside said the house is due north and due east is not open low."""
    monkeypatch.setattr(horizon, "RESULTS", tmp_path / "horizon.json")
    gap = lambda az: 10 if 95 <= az <= 100 else 40 if 60 <= az <= 135 else garden(az)
    start = sorted(set(range(0, 360, 30)) | {90, 97.5, 105}, key=horizon.side)
    found, warnings = horizon.trace(watcher(gap, in_view=1.5), start, low=20)
    for f in found:                 # as an older survey kept it, before lone openings were put right
        if "read_open" in f:
            f.update(state="open", clear=f.pop("read_open"), shut=None)
            f.pop("doubt")
    aside = horizon.set_aside(horizon.skyline_from(found, 20), "Not repeatable: due north", trace=found,
                              looks=[], warnings=[])
    with pytest.raises(interface.Refusal, match="--checked"):
        horizon.use_aside(aside, None, 20, 2)
    assert not horizon.RESULTS.exists()
    kept = horizon.use_aside(aside, "house due north; east not open low", 20, 2)
    saved = json.loads(horizon.RESULTS.read_text(encoding="utf-8"))
    assert saved["checked_by_eye"] == "house due north; east not open low"
    assert saved["was_set_aside"] == aside.name and saved["set_aside_because"].startswith("Not repeatable")
    east = next(p for p in saved["skyline"] if p["az"] == 97.5)
    assert east["alt"] >= 30 and "read open" in east["by"]
    assert kept["usable"] is not None


def test_a_jammed_camera_is_reopened_and_the_frame_asked_for_again():
    """3 November 2026: one 'no frame' ended the daylight survey."""
    from indi import IndiError
    opened, said = [], []

    class Cam:
        def __init__(self):
            opened.append(self)
            self.closed = False

        def frame(self, seconds):
            if len(opened) < 3:
                raise IndiError("no frame within 10 s")
            return "frame", seconds

        def close(self):
            self.closed = True

    cam = horizon.Reopening(Cam, say=said.append)
    assert cam.frame(0.01) == ("frame", 0.01)
    assert len(opened) == 3 and opened[0].closed and opened[1].closed and len(said) == 2
    stuck = horizon.Reopening(lambda: type("Stuck", (), {"frame": lambda self, s: (_ for _ in ()).throw(
        IndiError("no frame")), "close": lambda self: None})(), say=said.append, tries=2)
    import pytest
    with pytest.raises(IndiError):
        stuck.frame(1)


def test_a_skyline_checked_by_eye_stands_where_a_survey_differs_and_only_there():
    """3 November 2026: glare due south read a wall above 75°, and at midday
    the sunlit house in the west read as sky down to 20°."""
    checked = {"checked_by_eye": "due south not open low; house in the west",
               "skyline": [{"az": az, "alt": 72.0 if 285 <= az <= 330 else 36.0} for az in range(0, 360, 15)]}
    new = [{"az": 165, "alt": 40.0}, {"az": 180, "alt": 90.0}, {"az": 195, "alt": 38.0},
           {"az": 300, "alt": 20.0, "open": True}]
    skyline, differ = horizon.keep_checked(new, checked)
    assert [d["az"] for d in differ] == [180, 300]
    at = {p["az"]: p for p in skyline}
    assert at[165]["alt"] == 40.0 and at[195]["alt"] == 38.0              # agreeing bearings taken
    assert at[180]["alt"] == 36.0 and at[300]["alt"] == 72.0 and "not taken" in at[300]["by"]
    assert horizon.keep_checked(new, dict(checked, checked_by_eye=None)) == (new, [])   # nobody looked
    assert horizon.keep_checked(new, {}) == (new, [])


def test_a_recheck_that_differs_with_the_mount_in_the_same_place_costs_one_bearing():
    log = [{"az": 30, "alt": 45, "axes": [344.59, 68.59]}, {"az": 30, "alt": 44.6, "axes": [343.75, 68.37]}]
    assert not horizon.slipped(log, 30)
    log[-1]["axes"] = [343.7, 98.4]                                         # 30° off in Dec: it slipped
    assert horizon.slipped(log, 30)
    assert horizon.slipped([{"az": 30, "alt": 45}], 30)                     # axes not recorded: cannot say


def test_bearings_a_person_has_looked_at_are_taken_from_a_survey_set_aside(kept):
    horizon.keep([{"az": az, "alt": 54.0} for az in range(0, 360, 15)], "telescope", checked_by_eye="first look")
    found = [{"az": az, "state": "open" if 225 <= az <= 262.5 else "edge", "clear": 20 if 225 <= az <= 262.5 else 50,
              "shut": None if 225 <= az <= 262.5 else 49} for az in range(0, 360, 15)]
    aside = horizon.set_aside(horizon.skyline_from(found, 20), "test", trace=found, looks=[], warnings=[])
    horizon.use_aside(aside, "photo of the SW gap", 20, 2, horizon.span("225-262.5"))
    saved = json.loads(horizon.RESULTS.read_text(encoding="utf-8"))
    at = {p["az"]: p["alt"] for p in saved["skyline"]}
    assert at[240] == 20 and at[90] == 54.0 and "photo of the SW gap" in saved["checked_by_eye"]
    assert "first look" in saved["checked_by_eye"]
    with pytest.raises(interface.Refusal):
        horizon.span("south-west")



def test_by_day_a_look_aimed_by_a_guess_is_not_made():
    """3 November 2026: nothing by day checks the pointing."""
    assert horizon.aim_doubt(True, [0.0, 15.0], True, True) is None            # plate-solved on this side
    assert "never plate-solved" in horizon.aim_doubt(True, [0.0, 15.0], False, True)
    assert horizon.aim_doubt(True, [0.0, 1.5], False, True) is None            # a small guess is fine
    assert horizon.aim_doubt(True, [0.0, 15.0], False, False) is None          # by night the stars check it
    assert "changed sides" in horizon.aim_doubt(False, [0.0, 0.0], True, True)


def test_a_replaced_skyline_is_kept_beside_the_new_one(kept):
    horizon.keep([{"az": 0, "alt": 30}], "telescope")
    horizon.keep([{"az": 0, "alt": 40}], "telescope")
    old = list(horizon.RESULTS.parent.glob(f"{horizon.RESULTS.stem}.replaced-*.json"))
    assert len(old) == 1 and json.loads(old[0].read_text())["skyline"][0]["alt"] == 30
