"""The skyline: reading it from a frame, following it with the telescope,
taking it from a phone panorama, and the planner keeping targets above it."""
import json
import math
import shutil

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
    dark with no stars it is cloud, and the garden is open that way."""
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
    assert cloud["view"] == "sky" and cloud["cloud"]
    # Before any frame of stars has said how dark the sky is, only a burnt
    # frame can be called lit.
    assert horizon.read_torch(none, 400, 0.0, None)["view"] == "sky"
