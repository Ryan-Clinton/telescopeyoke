"""shoot.py on its own: what a session records about itself."""
import shoot


def test_a_session_records_whether_the_clock_was_kept_to_time():
    import types
    assert shoot.clock_state(lambda *a, **k: types.SimpleNamespace(stdout="yes\n"))["synchronized"] is True
    assert shoot.clock_state(lambda *a, **k: types.SimpleNamespace(stdout="no\n"))["synchronized"] is False

    def missing(*a, **k):
        raise FileNotFoundError("timedatectl")
    assert shoot.clock_state(missing)["synchronized"] == "unknown"


class Sky:
    """A pretend sky for the hold: the frames' shift drifts, and a move of
    the mount shifts it by its own strength in each direction (a move one
    way can be stronger than the other, as when the handset replaces
    tracking with the move's rate instead of adding to it)."""

    def __init__(self, strengths, drift=(0.4, -0.3)):
        import numpy as np
        self.strengths = {k: np.array(v, float) for k, v in strengths.items()}
        self.drift = np.array(drift, float)
        self.offset = np.zeros(2)
        self.time = 0.0
        self.shifts = []
        self.moved = []

    def frames(self, n=1):
        for _ in range(n):
            self.time += 5
            self.offset = self.offset + self.drift
            self.shifts.append((self.time, *self.offset))

    def pulse(self, axis, rate, seconds):
        import mount
        name = "RA" if axis == mount.RA else "Dec"
        self.offset = self.offset + self.strengths[(name, 1 if rate > 0 else -1)] * seconds
        self.moved.append((name, rate, seconds))


def run_hold(sky, hold, frames=200):
    said = []
    sky.frames(3)
    for _ in range(frames):
        if hold.due(sky.shifts):
            hold.step(sky.shifts, said.append)
        sky.frames()
    return said


def test_the_hold_learns_each_direction_then_keeps_the_target_still():
    import math
    # +RA moves the frames seven times as far as -RA does: the "replaces tracking" case.
    sky = Sky({("RA", 1): (3.5, 1.2), ("RA", -1): (-0.5, -0.17), ("Dec", 1): (-1.0, 2.0), ("Dec", -1): (1.0, -2.0)})
    hold = shoot.Hold(5.0, sky.pulse)
    said = run_hold(sky, hold)
    assert hold.state == "hold" and len(hold.columns) == 4
    assert abs(hold.columns[("RA", -1)][0] - (-0.5)) < 0.3 and abs(hold.columns[("RA", 1)][0] - 3.5) < 0.3
    late = [math.hypot(x, y) for _, x, y in sky.shifts[-100:]]
    assert max(late) < 8 and any("moving" in s for s in said)
    assert hold.moved < shoot.HOLD_MOST


def test_a_hold_that_does_not_help_stops_itself():
    # Dec moves the frames the opposite way to what it learnt, as after an unnoticed swing over the pole.
    sky = Sky({("RA", 1): (3.0, 1.0), ("RA", -1): (-3.0, -1.0), ("Dec", 1): (-1.0, 2.0), ("Dec", -1): (1.0, -2.0)},
              drift=(0.0, 1.5))
    hold = shoot.Hold(5.0, sky.pulse)
    run_hold(sky, hold, frames=40)
    assert hold.state == "hold"
    sky.strengths[("Dec", 1)], sky.strengths[("Dec", -1)] = -sky.strengths[("Dec", 1)], -sky.strengths[("Dec", -1)]
    said = run_hold(sky, hold, frames=200)
    assert hold.state == "off" and any("no smaller" in s or "more than a move" in s for s in said)


def test_a_hold_stops_at_its_total_and_after_a_recentring_learns_again():
    sky = Sky({("RA", 1): (3.0, 1.0), ("RA", -1): (-3.0, -1.0), ("Dec", 1): (-1.0, 2.0), ("Dec", -1): (1.0, -2.0)})
    hold = shoot.Hold(5.0, sky.pulse)
    run_hold(sky, hold, frames=40)
    hold.reset()
    assert hold.state == "learn" and hold.columns == {}
    hold.moved = shoot.HOLD_MOST - 1
    said = run_hold(sky, hold, frames=20)
    assert hold.state == "off" and "moved" in said[-1]


def test_a_hold_whose_moves_do_nothing_switches_itself_off():
    shifts = [(t, 0.0, 0.0) for t in range(5)]
    hold = shoot.Hold(5.0, lambda *a: None)
    said = []
    hold.step(shifts, said.append)
    shifts += [(t, 0.0, 0.0) for t in range(5, 10)]
    hold.step(shifts, said.append)
    assert hold.state == "off" and not hold.due(shifts) and "the hold is off" in said[-1]
