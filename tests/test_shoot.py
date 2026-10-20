"""shoot.py on its own: what a session records about itself."""
import shoot


def test_a_session_records_whether_the_clock_was_kept_to_time():
    import types
    assert shoot.clock_state(lambda *a, **k: types.SimpleNamespace(stdout="yes\n"))["synchronized"] is True
    assert shoot.clock_state(lambda *a, **k: types.SimpleNamespace(stdout="no\n"))["synchronized"] is False

    def missing(*a, **k):
        raise FileNotFoundError("timedatectl")
    assert shoot.clock_state(missing)["synchronized"] == "unknown"


def test_the_hold_learns_how_moves_shift_the_frames_then_keeps_the_target_still():
    import math
    import numpy as np
    import mount
    columns = {mount.RA: np.array([3.0, 1.0]), mount.DEC: np.array([-1.0, 2.0])}   # px per second of move
    sky = {"offset": np.zeros(2), "time": 0.0}
    shifts = []

    def frames(n, drift=np.array([0.4, -0.3])):
        for _ in range(n):
            sky["time"] += 5
            sky["offset"] = sky["offset"] + drift
            shifts.append((sky["time"], *sky["offset"]))

    def pulse(axis, rate, seconds):
        sky["offset"] = sky["offset"] + columns[axis] * seconds * math.copysign(1, rate)

    hold = shoot.Hold(5.0, pulse)
    said = []
    frames(3)
    for _ in range(200):
        if hold.due(shifts):
            hold.step(shifts, said.append)
        frames(1)
    assert hold.state == "hold"
    assert np.allclose(hold.columns[mount.RA], columns[mount.RA], atol=0.3)
    assert np.allclose(hold.columns[mount.DEC], columns[mount.DEC], atol=0.3)
    late = [math.hypot(x, y) for _, x, y in shifts[-100:]]
    assert max(late) < 8 and any("moving" in s for s in said)


def test_a_hold_whose_moves_do_nothing_switches_itself_off():
    shifts = [(t, 0.0, 0.0) for t in range(5)]
    hold = shoot.Hold(5.0, lambda *a: None)
    said = []
    hold.step(shifts, said.append)
    shifts += [(t, 0.0, 0.0) for t in range(5, 10)]
    hold.step(shifts, said.append)
    assert hold.state == "off" and not hold.due(shifts) and "the hold is off" in said[-1]
