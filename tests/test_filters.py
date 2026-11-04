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
    already = len(filters.load(where)["measurements"])
    for i, v in enumerate(values):
        filters.keep_measurement(name, v, temperature=5.0, night=f"2026-11-{already + i + 1:02d}", where=where)


def test_blocks_are_one_filter_and_count_each():
    assert filters.blocks("L:10,R:5,G:5,B:5") == [("L", 10), ("R", 5), ("G", 5), ("B", 5)]
    for bad in ("L", "L:0", "L:x", ""):
        with pytest.raises(ValueError):
            filters.blocks(bad)


SHO = "set SII,Ha,OIII"


def test_the_sets_are_a_setting_and_filters_in_l_s_set_need_no_offset(tmp_path):
    store = filters.load(tmp_path / "ff.json")
    assert filters.sets() == [["L", "R", "G", "B"], ["SII", "Ha", "OIII"]]
    assert filters.offset_of("R", store) == (0.0, None) and filters.offset_of("B", store) == (0.0, None)
    assert filters.key_of("Ha", store) == filters.key_of("OIII", store) == SHO
    assert filters.offset_of("Ha", store)[0] is None


def test_the_set_offset_is_used_only_from_three_nights_inward_within_the_tolerance(tmp_path):
    where = tmp_path / "ff.json"
    measured(where, "Ha", [40, 44])
    assert filters.offsets(filters.load(where), tolerance=16)[SHO]["usable"] is False
    measured(where, "OIII", [42])                          # any filter of the set measures the set
    found = filters.offsets(filters.load(where), tolerance=16)[SHO]
    assert found["usable"] and found["mean"] == 42.0 and found["nights"] == 3 and found["spread"] == 2.0
    assert found["temperatures_c"] == [5.0, 5.0, 5.0]
    measured(where, "SII", [200, 300, 400])                 # three more nights, spread far over 16
    assert "spread" in filters.offsets(filters.load(where), tolerance=16)[SHO]["why"]


def test_three_measurements_on_one_night_are_one_night(tmp_path):
    where = tmp_path / "ff.json"
    for v in (40, 41, 42):
        filters.keep_measurement("Ha", v, night="2026-11-05", where=where)
    assert "on 1 night" in filters.offsets(filters.load(where), tolerance=16)[SHO]["why"]


def test_steps_between_filters_are_the_difference_of_their_sets_offsets(tmp_path):
    where = tmp_path / "ff.json"
    measured(where, "Ha", [40, 42, 44])
    store = filters.load(where)
    assert filters.steps_between("L", "R", store, 16) == 0
    assert filters.steps_between("R", "OIII", store, 16) == 42
    assert filters.steps_between("SII", "G", store, 16) == -42
    assert filters.steps_between("Ha", "SII", store, 16) == 0


def test_the_proving_night_confirms_the_sets_or_gives_a_filter_its_own_offset(tmp_path):
    where = tmp_path / "ff.json"
    proved = filters.prove_sets({"L": 0, "R": 4, "G": -3, "B": 60, "SII": 100, "Ha": 104, "OIII": 98},
                                tolerance=16, where=where, night="2026-11-05")
    assert proved["confirmed"] == ["SII,Ha,OIII"] and proved["own"] == ["B"]
    store = filters.load(where)
    assert filters.key_of("B", store) == "B" and filters.key_of("R", store) == "set L,R,G,B"
    assert store["proof"]["positions"]["B"] == 60
    with pytest.raises(interface.Refusal) as refused:
        filters.steps_between("L", "B", store, 16)           # B now needs offsets of its own
    assert refused.value.code_name == "REFOCUS_NEEDED"
    assert filters.offsets(store, 16)[SHO]["nights"] == 1   # the proving night counts once for the set


def test_the_proving_run_walks_in_every_filter_from_the_same_side(tmp_path):
    where, turned, moves = tmp_path / "ff.json", [], []

    class Drive:
        moved = 0

        def move(self, n):
            moves.append(n)
            self.moved += n
    bests = iter([-100, -256, -256, -256, -256 + 90, -256, -256])   # LRGB at -100, SHO 90 further out

    def walk(d):
        at = next(bests)
        d.moved += at
        return {"best_at": at, "best_hfr": 2.0}
    proved = filters.prove_all(Drive(), walk, turned.append, say=lambda *_: None, back=256, where=where)
    assert turned == ["L", "R", "G", "B", "SII", "Ha", "OIII"] and moves == [256] * 6
    assert proved["own"] == [] and len(proved["confirmed"]) == 2
    assert proved["positions"]["Ha"] - proved["positions"]["L"] == 90


def test_a_change_moves_reads_back_then_focuses_with_the_last_move_inward(tmp_path):
    where, log, naps = tmp_path / "ff.json", [], []
    measured(where, "Ha", [40, 42, 44])
    filters.set_focused("L", where)
    done = filters.change("Ha", say=lambda *_: None, open_wheel=lambda: Wheel(1, log=log),
                          open_focuser=lambda: Motor(log), sleep=naps.append, where=where, backlash=30)
    assert log == [("wheel", 5), ("focuser", 72), ("focuser", -30)]       # out past it, then in by the slack
    assert done == {"position": 5, "name": "Ha", "from": "L", "steps": 42, "changed": True}
    assert naps == [filters.SETTLE_S] and filters.load(where)["focused_for"]["filter"] == "Ha"
    log.clear()
    filters.change("R", say=lambda *_: None, open_wheel=lambda: Wheel(5, log=log),
                   open_focuser=lambda: Motor(log), sleep=naps.append, where=where, backlash=30)
    assert log == [("wheel", 2), ("focuser", -42)]                          # inward: no overshoot
    log.clear()
    filters.change("G", say=lambda *_: None, open_wheel=lambda: Wheel(2, log=log),
                   open_focuser=lambda: pytest.fail("no focus move within a set"), sleep=naps.append, where=where)
    assert log == [("wheel", 3)]


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
    out = filters.measure_offset("Ha", drive, walk, turned.append, say=lambda *_: None, temperature=4.5,
                                 back=256, where=where)
    # L best at -100; out 256 to +156; Ha best 180 further in, at -24: 76 out from L.
    assert turned == ["L", "Ha"] and out["offset"] == 76 and out["usable"] is False
    kept = filters.load(where)
    assert kept["measurements"][0]["approach"] == "in" and kept["measurements"][0]["temperature_c"] == 4.5
    assert kept["focused_for"]["filter"] == "Ha"
    with pytest.raises(interface.Refusal):
        filters.measure_offset("R", drive, walk, turned.append, where=where)      # in L's set: no offset to measure


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
