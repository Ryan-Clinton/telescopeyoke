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

    def __init__(self, strengths, drift=(0.4, -0.3), dec_slack=0.0):
        import numpy as np
        self.dec_slack, self.dec_sign = dec_slack, None
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
        sign = 1 if rate > 0 else -1
        if name == "Dec":
            # The gears' slack: a reversal moves nothing until it is taken up.
            if self.dec_sign is not None and sign != self.dec_sign:
                seconds = max(0.0, seconds - self.dec_slack)
            self.dec_sign = sign
        self.offset = self.offset + self.strengths[(name, sign)] * seconds
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


def test_a_run_knows_when_the_disk_is_nearly_full(tmp_path, monkeypatch):
    """24 October 2026: the Moon at a frame a second left 5 GB in 25 minutes."""
    import shutil
    import shoot
    real = shutil.disk_usage
    monkeypatch.setattr(shutil, "disk_usage", lambda p: real(p)._replace(free=2_000_000_000))
    assert shoot.disk_full(tmp_path / "not-made-yet")
    monkeypatch.setattr(shutil, "disk_usage", lambda p: real(p)._replace(free=50_000_000_000))
    assert not shoot.disk_full(tmp_path)


def test_the_quality_pass_runs_in_the_background_and_frees_the_telescope(tmp_path):
    """2 November 2026: processing goes on in the background while the scope
    does the next job; the pass held it after every run."""
    started, said = [], []
    shoot.restack_later(tmp_path, start=lambda cmd, **kw: started.append((cmd, kw)), say=said.append)
    cmd, kw = started[0]
    assert cmd[1].endswith("restack.py") and cmd[2] == str(tmp_path)
    assert kw["stdin"] is shoot.subprocess.DEVNULL and (tmp_path / "restack.log").exists()
    assert "telescope is free" in said[0]


def test_drift_is_measured_from_the_first_frame_after_a_centring(monkeypatch):
    """2 November 2026: a re-centre past the meridian swung the tube over the
    pole; the frames came back turned half round, a big "shift" from the
    reference with the target centred, and NGC 7331 was re-centred every
    four frames."""
    import numpy as np
    session = shoot.Session("Drift test", 16, 1500, save=False)
    monkeypatch.setattr(session, "publish", lambda: None)
    monkeypatch.setattr(shoot.stacking, "append_log", lambda *a: None)

    def frame(index, shift):
        entry = {"index": index, "accepted": True, "shift": shift, "fwhm": 5.2, "roundness": 0.9, "stars": 300,
                 "flux": 1.0, "background": 8.0, "noise": 40.0}
        return {"entry": entry, "frame": np.zeros((100, 150)), "reference": "ref", "timings": {}}
    session.absorb(frame(1, (0.0, 0.0)))
    session.absorb(frame(2, (3.0, 4.0)))
    assert session.drift == 0.05                     # 5 px of a 100 px frame: real drift
    session.drift, session.origin = 0.0, None        # re-centred, and swung over the pole
    session.absorb(frame(3, (148.0, 99.0)))          # turned half round: far "from the reference"
    session.absorb(frame(4, (148.5, 99.0)))
    assert session.drift == 0.005                    # but only half a pixel since the centring


def test_the_hold_learns_the_dec_slack_and_takes_it_up_on_each_reversal():
    """2 November 2026: +Dec moved the frames 12.3 px a second and -Dec only
    2.0 (gear slack eaten by the reversal); the hold's corrections never
    closed the miss and it gave up mid-transit."""
    import math
    sky = Sky({("RA", 1): (3.0, 1.0), ("RA", -1): (-3.0, -1.0), ("Dec", 1): (-1.0, 3.0), ("Dec", -1): (1.0, -3.0)},
              dec_slack=3.0)
    hold = shoot.Hold(5.0, sky.pulse)
    said = run_hold(sky, hold, frames=300)
    assert hold.state == "hold" and 2.0 < hold.dec_slack < 4.0
    assert any("slack" in s for s in said)
    late = [math.hypot(x, y) for _, x, y in sky.shifts[-100:]]
    assert max(late) < 10


def test_an_order_named_for_one_run_never_reaches_another(tmp_path, monkeypatch):
    """1 November 2026: a "stop" timed for M33 was taken by the M31 run that
    followed it."""
    monkeypatch.setattr(shoot, "ORDERS", tmp_path / "run_order.txt")
    shoot.tell("stop", run="M33")
    assert shoot.order("M31") is None and shoot.ORDERS.exists()      # left for the run it names
    assert shoot.order("M33") == "stop" and not shoot.ORDERS.exists()
    shoot.tell("stop")
    assert shoot.order("M31") == "stop"                                # unnamed: for whatever is running
    shoot.tell("stop", run="M31")
    import time
    assert shoot.order("M31", now=time.time() + shoot.ORDER_STALE_S + 1) is None   # stale: never acted on
    shoot.ORDERS.write_text("stop")                                    # the old plain form still works
    assert shoot.order("M31") == "stop"


def test_minutes_alone_mean_image_for_that_long():
    """4 November 2026: '--minutes 90' with no --frames took the default 60
    frames and would have stopped after half an hour (nightreplay.py found it)."""
    assert shoot.frames_asked(None, 90) == 0          # as many as the minutes allow
    assert shoot.frames_asked(None, None) == 60       # as before, with neither
    assert shoot.frames_asked(19, 5.5) == 19          # a count given is kept
    assert shoot.frames_asked(0, None) == 0
