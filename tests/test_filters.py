"""Filters in the light path (filters.py): the filter a step asks for, the
change as one transaction, focus offsets from L and their use, and what a
filter's magnitudes are called. No wheel, focuser or camera: made-up ones."""
import pytest

import filters
import interface
import sxwheel

NAMES = ["L", "R", "G", "B", "Ha", "SII", "OIII"]


@pytest.fixture(autouse=True)
def named(monkeypatch):
    monkeypatch.setattr(sxwheel, "names", lambda cfg=None: list(NAMES))


class Wheel(sxwheel.Wheel):
    def __init__(self, at=1, total=7, arrives=True, log=None):
        self.at, self.total, self.arrives, self.log = at, total, arrives, log if log is not None else []

    def status(self):
        return self.at, self.total

    def move(self, wanted, **_):
        number = self.position(wanted, self.total)
        self.log.append(("wheel", number))
        if self.arrives:
            self.at = number
        return number

    def close(self):
        pass


class Motor:
    def __init__(self, log):
        self.log = log

    def move(self, n):
        self.log.append(("focuser", n))

    def close(self):
        pass


def measured(where, name, values):
    """Measurements on nights after any already kept for `name`."""
    already = sum(m["filter"] == name for m in filters.load(where)["measurements"])
    for i, v in enumerate(values):
        filters.keep_measurement(name, v, temperature=5.0, night=f"2026-11-{already + i + 1:02d}", where=where)


def test_blocks_are_one_filter_and_count_each():
    assert filters.blocks("L:10,R:5,G:5,B:5") == [("L", 10), ("R", 5), ("G", 5), ("B", 5)]
    for bad in ("L", "L:0", "L:x", ""):
        with pytest.raises(ValueError):
            filters.blocks(bad)


def test_an_offset_is_used_only_from_three_nights_inward_within_the_tolerance(tmp_path):
    where = tmp_path / "ff.json"
    measured(where, "R", [40, 44])
    assert filters.offsets(filters.load(where), tolerance=16)["R"]["usable"] is False
    measured(where, "R", [42])
    found = filters.offsets(filters.load(where), tolerance=16)["R"]
    assert found["usable"] and found["mean"] == 42.0 and found["count"] == 3 and found["spread"] == 2.0
    assert found["temperatures_c"] == [5.0, 5.0, 5.0]
    measured(where, "Ha", [10, 60, 110])                      # spread 50 > 16
    assert "spread 50" in filters.offsets(filters.load(where), tolerance=16)["Ha"]["why"]


def test_three_measurements_on_one_night_are_not_enough(tmp_path):
    where = tmp_path / "ff.json"
    for v in (40, 41, 42):
        filters.keep_measurement("R", v, night="2026-11-05", where=where)
    assert "on 1 night" in filters.offsets(filters.load(where), tolerance=16)["R"]["why"]


def test_steps_between_filters_are_the_difference_of_their_offsets(tmp_path):
    where = tmp_path / "ff.json"
    measured(where, "R", [40, 42, 44])
    measured(where, "Ha", [-20, -22, -18])
    store = filters.load(where)
    assert filters.steps_between("L", "R", store, 16) == 42
    assert filters.steps_between("R", "Ha", store, 16) == -62
    assert filters.steps_between("Ha", "Ha", store, 16) == 0
    with pytest.raises(interface.Refusal) as refused:
        filters.steps_between("L", "OIII", store, 16)
    assert refused.value.code_name == "REFOCUS_NEEDED" and "its own walk-in" in str(refused.value)


def test_a_change_moves_reads_back_then_focuses_with_the_last_move_inward(tmp_path):
    where, log, naps = tmp_path / "ff.json", [], []
    measured(where, "R", [40, 42, 44])
    filters.set_focused("L", where)
    done = filters.change("R", say=lambda *_: None, open_wheel=lambda: Wheel(1, log=log),
                          open_focuser=lambda: Motor(log), sleep=naps.append, where=where, backlash=30)
    assert log == [("wheel", 2), ("focuser", 72), ("focuser", -30)]       # out past it, then in by the slack
    assert done == {"position": 2, "name": "R", "from": "L", "steps": 42, "changed": True}
    assert naps == [filters.SETTLE_S] and filters.load(where)["focused_for"]["filter"] == "R"
    log.clear()
    filters.change("L", say=lambda *_: None, open_wheel=lambda: Wheel(2, log=log),
                   open_focuser=lambda: Motor(log), sleep=naps.append, where=where, backlash=30)
    assert log == [("wheel", 1), ("focuser", -42)]                          # inward: no overshoot


def test_a_filter_with_no_usable_offset_stops_the_step_before_the_wheel_turns(tmp_path):
    where, log = tmp_path / "ff.json", []
    filters.set_focused("L", where)
    with pytest.raises(interface.Refusal) as refused:
        filters.change("Ha", say=lambda *_: None, open_wheel=lambda: Wheel(1, log=log),
                       open_focuser=lambda: Motor(log), sleep=lambda s: None, where=where)
    assert refused.value.code_name == "REFOCUS_NEEDED" and log == []


def test_a_wheel_that_does_not_arrive_stops_the_step_and_nothing_is_focused(tmp_path):
    where, log = tmp_path / "ff.json", []
    filters.set_focused("L", where)
    with pytest.raises(interface.Refusal) as refused:
        filters.change("L", say=lambda *_: None, open_wheel=lambda: Wheel(3, arrives=False, log=log),
                       open_focuser=lambda: Motor(log), sleep=lambda s: None, where=where)
    assert refused.value.code_name == "FILTER_NOT_CONFIRMED" and ("focuser", 0) not in log
    assert all(entry[0] == "wheel" for entry in log)


def test_no_wheel_or_an_unknown_filter_is_refused(tmp_path):
    def gone():
        raise sxwheel.WheelError("No Starlight Xpress filter wheel found")
    with pytest.raises(interface.Refusal) as refused:
        filters.change("L", say=lambda *_: None, open_wheel=gone, where=tmp_path / "ff.json")
    assert refused.value.code_name == "FILTER_NOT_CONFIRMED"
    with pytest.raises(interface.Refusal):
        filters.change("Hb", say=lambda *_: None, open_wheel=lambda: Wheel(1), where=tmp_path / "ff.json")


def test_the_first_frame_after_a_change_is_checked_against_the_last_run_in_l(tmp_path):
    where = tmp_path / "ff.json"
    store = filters.load(where)
    assert filters.size_check(4.0, store) is None                         # nothing in L to compare
    filters.keep_last_l(4.0, where)
    store = filters.load(where)
    assert filters.size_check(4.8, store, tolerance=1.25) is None
    assert "refocus" in filters.size_check(5.2, store, tolerance=1.25)


def test_one_offset_measurement_is_two_walk_ins_from_the_same_side(tmp_path):
    where, turned = tmp_path / "ff.json", []

    class Drive:
        moved = 0

        def move(self, n):
            self.moved += n
    drive = Drive()
    bests = iter([{"best_at": -100, "best_hfr": 2.1}, {"best_at": -180, "best_hfr": 2.4}])

    def walk(d):
        found = next(bests)
        d.moved += found["best_at"]
        return found
    out = filters.measure_offset("R", drive, walk, turned.append, say=lambda *_: None, temperature=4.5,
                                 back=256, where=where)
    # L best at -100; out 256 to +156; R best 180 further in, at -24: 76 out from L.
    assert turned == ["L", "R"] and out["offset"] == 76 and out["usable"] is False
    kept = filters.load(where)
    assert kept["measurements"][0]["approach"] == "in" and kept["measurements"][0]["temperature_c"] == 4.5
    assert kept["focused_for"]["filter"] == "R"


def test_a_band_is_named_for_what_took_it_and_never_gaia_or_v(monkeypatch):
    monkeypatch.setattr(filters, "settings", lambda cfg=None: {"makers": "Optolong,Optolong,Optolong,Optolong,,,"})
    assert filters.band({"FILTER": "L", "FILTPOS": 1, "INSTRUME": "183m"}) == "L (Optolong), 183M"
    assert filters.band({"FILTER": "Ha", "FILTPOS": 5, "INSTRUME": "183m"}) == "Ha, 183M"
    assert filters.band({"INSTRUME": "183c"}) is None and filters.band({}) is None
    assert filters.band_key({"FILTER": "L", "INSTRUME": "183m"}) == ("183m", "L")
    assert filters.band_key({}) == ("183c", None)


def test_a_target_s_filter_comes_from_its_goals_and_is_l_when_they_say_nothing():
    assert filters.for_target("M101") == "L"
    assert filters.for_target("M31-P3") == "L"
