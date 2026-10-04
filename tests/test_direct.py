"""The mount reached without its handset (Wi-Fi adapter or EQDIR lead), run
against a simulated motor board: nothing here can move a real telescope."""
import argparse
import socket
import threading

import pytest

import config
import direct
import interface
import mount
from simulator import SimulatedBoard

SITE = config.example()["site"]
HOME = 0x800000
COUNTS = SimulatedBoard.COUNTS


def rig(tmp_path, monkeypatch, board=None, dec_sign=None):
    """A Mount on a simulated board. `dec_sign` is what a direction check
    would have recorded; None leaves it unchecked."""
    for name in ("CLOCK_FILE", "POINTING_FILE", "DRIFT_FILE"):
        monkeypatch.setattr(mount, name, tmp_path / f"{name}.json")
    monkeypatch.setattr(mount, "LOCK_FILE", tmp_path / "MOTION_LOCKED")
    board = board or SimulatedBoard()
    hand = direct.DirectHandset(direct.Board(board), lambda: mount.true_sidereal(SITE),
                                state_file=tmp_path / "direct.json")
    if dec_sign:
        hand.set_dec_sign(dec_sign)
    return mount.Mount(handset=hand), board


def truly(board, dec_sign):
    """Where this pretend mount is really aimed: (hour angle, Dec) in degrees,
    from its counts and the way its Dec motor really turns."""
    ra_axis = 360 * (board.axes["1"]["pos"] - HOME) / COUNTS
    dec_axis = 90 + dec_sign * 360 * (board.axes["2"]["pos"] - HOME) / COUNTS
    if dec_axis <= 90:
        return mount.wrap(ra_axis - 90), dec_axis
    return mount.wrap(ra_axis + 90), 180 - dec_axis


def test_numbers_are_written_low_byte_first():
    assert direct.encode(0x123456) == "563412" and direct.decode("563412") == 0x123456
    assert direct.encode(4576000) == "00D345"          # as a real EQ3 answered
    assert direct.decode("958A00") == 35477


def test_it_reads_the_board_as_a_real_one_answered(tmp_path, monkeypatch):
    scope, board = rig(tmp_path, monkeypatch)
    seen = direct.describe(board)
    assert seen["model"] == "EQ3" and seen["firmware"] == "1.07" and seen["counts_per_turn"] == 4576000
    assert not board.orders                            # reading gave no orders


def test_a_board_just_switched_on_is_at_home(tmp_path, monkeypatch):
    scope, board = rig(tmp_path, monkeypatch)
    assert scope.at_home() and scope.axes() == pytest.approx([0, 90], abs=0.01)
    assert not board.orders


def test_a_board_whose_counts_were_changed_must_be_told_where_home_is(tmp_path, monkeypatch):
    # As found on the real mount: another program had left the counts a quarter turn off.
    quarter = COUNTS // 4
    scope, board = rig(tmp_path, monkeypatch, SimulatedBoard(start=(HOME - quarter, HOME + quarter)))
    for work in (scope.axes, lambda: scope.tracking(True), lambda: scope.rate(mount.RA, mount.POSITIVE, 5)):
        with pytest.raises(interface.Refusal) as refusal:
            work()
        assert refusal.value.code_name == "HANDSET_NOT_SET_UP" and "sethome" in refusal.value.message
    assert not board.orders
    scope.set_home()
    assert scope.at_home() and not board.orders        # recording home moves nothing
    # A fresh Mount on the same board remembers it.
    again, _ = rig(tmp_path, monkeypatch, board)
    assert again.at_home()


def test_a_goto_is_refused_until_the_dec_direction_has_been_checked(tmp_path, monkeypatch):
    scope, board = rig(tmp_path, monkeypatch)
    with pytest.raises(interface.Refusal) as refusal:
        scope.goto(mount.true_sidereal(SITE) + 30, 40)
    assert refusal.value.code_name == "GOTO_REFUSED" and "directions" in refusal.value.message
    assert not board.orders


@pytest.mark.parametrize("real_sign", [1, -1])
def test_the_direction_check_and_then_gotos_on_both_kinds_of_mount(tmp_path, monkeypatch, real_sign):
    scope, board = rig(tmp_path, monkeypatch)
    tipped = []

    def person(question):
        # What someone watching would see: the tube 5° off the pole, to the east or the west.
        hour_angle, dec = truly(board, real_sign)
        tipped.append((hour_angle, dec))
        return "east" if hour_angle < 0 else "west"
    scope.check_directions(ask=person)
    assert tipped[0][1] == pytest.approx(85, abs=0.01) and abs(tipped[0][0]) == pytest.approx(90, abs=0.01)
    assert scope.at_home() and scope.s.state["dec_sign"] == real_sign

    sidereal = mount.true_sidereal(SITE)
    for hour_angle, dec in ((-40.0, 35.0), (50.0, 10.0), (-5.0, 70.0), (20.0, -15.0)):
        scope.goto((sidereal - hour_angle) % 360, dec)
        got_ha, got_dec = truly(board, real_sign)
        # The sky moves on while the test runs: a few arcminutes of hour angle.
        assert got_dec == pytest.approx(dec, abs=0.05)
        assert mount.wrap(got_ha - hour_angle) == pytest.approx(0, abs=0.3)
        ra_axis, dec_axis = scope.axes()
        assert (dec_axis > 90) == (hour_angle > 0.5)             # west: the tube over the pole
        assert -91 < mount.wrap(ra_axis) < 91                    # never the long way round
        ra, dec_said = scope.radec()
        assert mount.wrap(dec_said) == pytest.approx(dec, abs=0.05)
        assert mount.wrap(ra - (sidereal - hour_angle)) == pytest.approx(0, abs=0.3)
    # It follows the sky afterwards: the RA motor turns forward at the sidereal rate.
    status = direct.Board(board).status(direct.RA)
    assert status["running"] and not status["goto"] and not status["backward"] and not status["fast"]
    rate = SimulatedBoard.CLOCK / board.axes["1"]["period"] * 360 / COUNTS      # degrees a second
    assert rate == pytest.approx(direct.SIDEREAL, rel=0.002)

    scope.stop()
    assert not board.axes["1"]["running"] and not board.axes["2"]["running"]


def test_an_answer_that_is_not_east_or_west_records_nothing(tmp_path, monkeypatch):
    scope, board = rig(tmp_path, monkeypatch)
    with pytest.raises(interface.Refusal):
        scope.check_directions(ask=lambda question: "not sure")
    assert scope.at_home() and scope.s.state["dec_sign"] is None     # put back, and still unchecked
    with pytest.raises(interface.Refusal):
        scope.goto(0, 40)


def test_the_direction_check_starts_from_home(tmp_path, monkeypatch):
    board = SimulatedBoard()
    scope, _ = rig(tmp_path, monkeypatch, board)
    board.axes["2"]["pos"] += COUNTS / 36          # 10° off
    asked = []
    with pytest.raises(interface.Refusal) as refusal:
        scope.check_directions(ask=asked.append)
    assert "home" in refusal.value.message and not asked and not board.orders


@pytest.mark.parametrize("real_sign", [1, -1])
def test_home_is_found_by_the_readout_from_either_side(tmp_path, monkeypatch, real_sign):
    scope, board = rig(tmp_path, monkeypatch, dec_sign=real_sign)
    sidereal = mount.true_sidereal(SITE)
    scope.goto((sidereal + 82) % 360, 84)          # a short way from home, east of the meridian
    assert not scope.at_home()
    scope.home()
    assert scope.at_home()
    assert truly(board, real_sign)[1] == pytest.approx(90, abs=0.3)
    assert not board.axes["1"]["running"] and not board.axes["2"]["running"]


@pytest.mark.parametrize("real_sign", [1, -1])
def test_dec_creep_raises_the_readout_whichever_way_the_motor_counts(tmp_path, monkeypatch, real_sign):
    scope, board = rig(tmp_path, monkeypatch, dec_sign=real_sign)
    assert scope.dec_creep(1.5) == 1.5
    axis = board.axes["2"]
    assert axis["running"] and axis["mode"] == "1" and axis["back"] == (real_sign < 0)
    rate = SimulatedBoard.CLOCK / axis["period"] * 1296000 / COUNTS            # arcseconds a second
    assert rate == pytest.approx(1.5, rel=0.01)
    scope.dec_creep(0)
    assert not axis["running"]


def test_fast_slews_use_the_high_speed_mode_and_stop_before_changing(tmp_path, monkeypatch):
    scope, board = rig(tmp_path, monkeypatch, dec_sign=1)
    scope.rate(mount.DEC, mount.POSITIVE, 9)
    axis = board.axes["2"]
    assert axis["running"] and axis["mode"] == "3"
    scope.rate(mount.DEC, mount.NEGATIVE, 3)
    assert axis["running"] and axis["mode"] == "1" and axis["back"]
    # The board refuses a change of mode while turning, so each was stopped first: no refusal reached us.
    scope.rate(mount.DEC, mount.NEGATIVE, 0)
    assert not axis["running"]


def test_the_wifi_link_asks_again_when_a_packet_is_lost():
    board, dropped = SimulatedBoard(), []
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", 0))
    server.settimeout(5)

    def answer():
        try:
            while True:
                message, who = server.recvfrom(256)
                if message == b":j1\r" and not dropped:
                    dropped.append(message)       # lose the first one
                    continue
                server.sendto(board.exchange(message), who)
        except OSError:
            pass
    threading.Thread(target=answer, daemon=True).start()
    link = direct.Udp("127.0.0.1", server.getsockname()[1], timeout=0.3)
    try:
        assert direct.Board(link).position(direct.RA) == HOME and dropped
    finally:
        link.close()
        server.close()


def test_nothing_answering_is_a_refusal_with_advice():
    quiet = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    quiet.bind(("127.0.0.1", 0))
    link = direct.Udp("127.0.0.1", quiet.getsockname()[1], timeout=0.1)
    with pytest.raises(interface.Refusal) as refusal:
        direct.Board(link)
    assert refusal.value.code_name == "HANDSET_NOT_ANSWERING"
    link.close()
    quiet.close()


def test_the_lock_refuses_the_direction_check_before_the_mount_is_opened(tmp_path, monkeypatch):
    monkeypatch.setattr(mount, "LOCK_FILE", tmp_path / "MOTION_LOCKED")
    mount.LOCK_FILE.write_text("testing", encoding="utf-8")
    monkeypatch.setattr(mount, "Mount", lambda *a, **k: pytest.fail("the mount was opened"))
    args = argparse.Namespace(command="directions", port=None, no_watch=True, demo=False, record=None)
    with pytest.raises(interface.Refusal) as refusal:
        mount.act(args, SITE)
    assert refusal.value.code_name == "MOTION_LOCKED"


def test_these_commands_mean_nothing_with_a_real_handset(tmp_path, monkeypatch):
    from simulator import SimulatedHandset
    scope = mount.Mount(handset=SimulatedHandset(slew_seconds=0))
    for work in (scope.set_home, scope.check_directions):
        with pytest.raises(interface.Refusal) as refusal:
            work()
        assert refusal.value.code_name == "INVALID_REQUEST"
