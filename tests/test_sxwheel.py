"""The Starlight Xpress filter wheel, against a made-up HID device that
speaks its protocol as INDI's driver does (indi-sx/sxwheel.cpp)."""
import types

import pytest

import sxwheel


class FakeWheel:
    """Seven positions. Turning takes `steps` questions, reading 0 meanwhile."""

    def __init__(self, at=1, total=7, steps=3, warming=0, deaf=False):
        self.at, self.total, self.steps, self.warming, self.deaf = at, total, steps, warming, deaf
        self.written, self.going, self.left, self.closed = [], None, 0, False

    def open(self, vendor, product):
        assert (vendor, product) == (0x1278, 0x0920)

    def write(self, data):
        self.written.append(list(data))
        a, _ = data
        if a and not self.deaf:
            self.going, self.left = a & 0x7f, self.steps
        return len(data)

    def read(self, size, timeout_ms):
        if self.warming:                       # still making its power-up turn
            self.warming -= 1
            return [0, 0]
        if self.going is not None:
            if self.left:
                self.left -= 1
                return [0, self.total]
            self.at, self.going = self.going, None
        return [self.at, self.total]

    def close(self):
        self.closed = True


def hid_with(device, plugged=True):
    return types.SimpleNamespace(device=lambda: device,
                                 enumerate=lambda v, p: [{"path": b"x"}] if plugged else [])


@pytest.fixture(autouse=True)
def filters(monkeypatch):
    monkeypatch.setattr(sxwheel, "names", lambda cfg=None: ["L", "R", "G", "B", "Ha", "OIII", "SII", ""])


def test_status_is_two_bytes_out_and_current_and_total_back():
    device = FakeWheel(at=3)
    with sxwheel.Wheel.open(hid_with(device)) as wheel:
        assert wheel.status() == (3, 7)
    assert device.written == [[0, 0]]          # no report number in front, as INDI writes it
    assert device.closed


def test_move_by_name_goes_the_shorter_way_and_waits_until_it_arrives():
    device = FakeWheel(at=1)
    naps = []
    with sxwheel.Wheel.open(hid_with(device)) as wheel:
        assert wheel.move("ha", sleep=naps.append) == 5
    assert [5 + 0x80, 0] in device.written and device.at == 5
    assert naps and all(n == sxwheel.POLL for n in naps)


def test_move_by_number_and_a_move_to_where_it_is_sends_nothing():
    device = FakeWheel(at=4)
    with sxwheel.Wheel.open(hid_with(device)) as wheel:
        assert wheel.move("4", sleep=lambda s: None) == 4
        assert device.written == [[0, 0]]
        assert wheel.move("2", sleep=lambda s: None) == 2


def test_an_unknown_name_or_a_position_off_the_wheel_is_refused_before_it_turns():
    device = FakeWheel()
    with sxwheel.Wheel.open(hid_with(device)) as wheel:
        with pytest.raises(sxwheel.WheelError, match="No filter named 'Hb'.*5 Ha"):
            wheel.move("Hb", sleep=lambda s: None)
        with pytest.raises(sxwheel.WheelError, match="not on a 7-position"):
            wheel.move("8", sleep=lambda s: None)
    assert all(a == 0 for a, _ in device.written)


def test_a_wheel_that_never_arrives_is_given_up_on_and_said():
    device, now = FakeWheel(deaf=True), [0.0]

    def sleep(seconds):
        now[0] += seconds
    with sxwheel.Wheel.open(hid_with(device)) as wheel:
        with pytest.raises(sxwheel.WheelError, match="did not reach filter 3 within 2 s"):
            wheel.move("G", timeout=2, sleep=sleep, clock=lambda: now[0])


def test_a_wheel_still_making_its_power_up_turn_is_waited_for():
    device = FakeWheel(warming=3)
    with sxwheel.Wheel.open(hid_with(device)) as wheel:
        assert wheel.move("B", sleep=lambda s: None) == 4


def test_no_wheel_and_a_wheel_that_may_not_be_opened_are_told_apart():
    class Closed(FakeWheel):
        def open(self, vendor, product):
            raise OSError("open failed")
    with pytest.raises(sxwheel.WheelError, match="No Starlight Xpress filter wheel found"):
        sxwheel.Wheel.open(hid_with(Closed(), plugged=False))
    with pytest.raises(sxwheel.WheelError, match="udev rule"):
        sxwheel.Wheel.open(hid_with(Closed(), plugged=True))


def test_a_frame_s_filter_is_only_a_position_the_wheel_confirmed_and_never_raises(monkeypatch):
    monkeypatch.setattr(sxwheel.config, "DEMO", False)
    said = []
    assert sxwheel.confirmed(hid_with(FakeWheel(at=6))) == (6, "OIII")
    assert sxwheel.confirmed(hid_with(FakeWheel(at=8, total=8))) == (8, "position 8")   # no name for it
    turning = FakeWheel(at=1)
    turning.going, turning.left = 3, 5
    assert sxwheel.confirmed(hid_with(turning), say=said.append) is None
    assert sxwheel.confirmed(hid_with(FakeWheel(warming=2)), say=said.append) is None   # power-up turn

    class Gone(FakeWheel):
        def open(self, vendor, product):
            raise OSError("open failed")
    assert sxwheel.confirmed(hid_with(Gone(), plugged=False), say=said.append) is None
    assert said[0] == said[1] == "the filter wheel is turning: frames carry no FILTER"
    assert said[2].startswith("the filter wheel did not answer")
    header = sxwheel.cards({}, (6, "OIII"))
    assert header == {"FILTPOS": 6, "FILTER": "OIII"} and sxwheel.cards({}, None) == {}


def test_with_no_names_set_the_positions_go_by_number(monkeypatch, capsys):
    monkeypatch.setattr(sxwheel, "names", lambda cfg=None: [""])
    device = FakeWheel(at=2)
    with sxwheel.Wheel.open(hid_with(device)) as wheel:
        assert wheel.move("5", sleep=lambda s: None) == 5
        with pytest.raises(sxwheel.WheelError, match="positions have no names yet"):
            wheel.move("Ha", sleep=lambda s: None)
    monkeypatch.setattr(sxwheel.config, "DEMO", False)
    assert sxwheel.confirmed(hid_with(FakeWheel(at=3))) == (3, "position 3")


def test_the_names_come_from_the_setting_with_gaps_kept(monkeypatch):
    monkeypatch.undo()
    assert sxwheel.names({"filterwheel": {"filters": "L, R,G,B,SII,Ha,OIII"}}) == \
        ["L", "R", "G", "B", "SII", "Ha", "OIII"]
    assert sxwheel.names({"filterwheel": {"filters": "L,,G"}}) == ["L", "", "G"]
    import config
    assert sxwheel.names(config.example()) == [""]          # no order guessed before anyone has looked


def test_the_command_says_where_the_wheel_is_and_moves_it(monkeypatch, capsys):
    device = FakeWheel(at=1)
    monkeypatch.setattr(sxwheel, "_hid", lambda: hid_with(device))
    monkeypatch.setattr(sxwheel, "POLL", 0)
    assert sxwheel.main(["status"]) == 0
    assert "Filter 1 (L) of 7." in capsys.readouterr().out
    assert sxwheel.main(["move", "SII"]) == 0
    assert "At filter 7 (SII)." in capsys.readouterr().out
    def missing():
        raise sxwheel.WheelError("The Python hidapi module is missing")
    monkeypatch.setattr(sxwheel, "_hid", missing)
    assert sxwheel.main(["status"]) == 1
    assert "hidapi module is missing" in capsys.readouterr().err


def test_the_hidraw_module_is_preferred(monkeypatch):
    # Debian's python3-hid: `hidraw` opens /dev/hidraw (which the udev rule
    # opens up); `hid` goes through libusb and could not open the wheel.
    import sys
    import types
    hidraw, hid = types.ModuleType("hidraw"), types.ModuleType("hid")
    monkeypatch.setitem(sys.modules, "hidraw", hidraw)
    monkeypatch.setitem(sys.modules, "hid", hid)
    assert sxwheel._hid() is hidraw
    monkeypatch.setitem(sys.modules, "hidraw", None)      # only pip's `hid`
    assert sxwheel._hid() is hid
