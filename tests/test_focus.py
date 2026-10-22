"""The focusing aid: its three levels, what it says and sounds, and the loop
that keeps the camera exposing while a frame is measured. No camera and no
speaker: the frames are made up and the sounds are caught."""
import io
import itertools
import json
import sys
import time
import wave

import numpy as np
import pytest

import focus
import simulator

STARS = 20     # a reading taken over many stars; 0 is one star, or its ring


def each(tracker, values, stars=STARS):
    return [tracker.feed(v, stars) for v in values]


def said(heard):
    return [h["say"] for h in heard if h["say"]]


def fine(tracker):
    """A tracker taken to level 3, as three small readings on many stars do."""
    assert said(each(tracker, (3.9, 3.8, 3.8))) == ["Level three. Fine focus."]
    return tracker


# --- levels ---------------------------------------------------------------------

def test_it_climbs_the_levels_by_itself():
    tracker = focus.FocusTracker(usual=2.0)
    rings = each(tracker, (30, 24, 18), stars=0)                 # far out: one big ring
    assert tracker.level == 1 and not said(rings) and {h["sound"] for h in rings} == {"tone"}
    assert said(each(tracker, (9.0, 8.0, 7.0))) == ["Level two."]            # stars have appeared
    assert tracker.level == 2
    assert said(each(tracker, (6.0, 5.0, 4.4))) == []                        # not near enough yet
    assert said(each(tracker, (3.9, 3.7, 3.6, 3.6))) == ["Level three. Fine focus."]
    assert tracker.level == 3 and not tracker.single


def test_each_level_steadies_its_readings_more_than_the_last():
    assert [focus.SMOOTH[level] for level in (1, 2, 3)] == [1, 2, 3]
    tracker = focus.FocusTracker(usual=2.0)
    tracker.feed(30, 0)
    tracker.feed(10, 0)
    assert tracker.now == 10                    # level 1 takes each frame as it comes
    fine(tracker)
    each(tracker, (3.0, 3.0, 3.0, 9.0))
    assert tracker.now == 3.0                   # level 3 is not moved by one wild frame


def test_a_field_with_one_star_still_reaches_fine_focus():
    tracker = focus.FocusTracker(usual=2.0)
    assert said(each(tracker, (3.9, 3.8, 3.7), stars=0)) == ["Level three. Fine focus."]
    assert tracker.single
    assert {h["sound"] for h in each(tracker, (3.5, 3.4, 3.3), stars=0)} == {"tone"}


def test_fine_focus_is_left_when_the_stars_swell_again():
    tracker = fine(focus.FocusTracker(usual=2.0))
    assert said(each(tracker, (7.0, 7.5, 8.0, 8.0, 8.0))) == ["Level two."]
    assert tracker.level == 2


# --- what is said ------------------------------------------------------------------

def test_a_pass_through_the_minimum_and_back_to_focus_good():
    tracker = fine(focus.FocusTracker(usual=2.0))
    down = each(tracker, [v for v in (3.6, 3.2, 2.8, 2.4, 2.1, 2.0) for _ in range(3)])
    assert not said(down) and "improving" in {h["trend"] for h in down}
    past = each(tracker, [v for v in (2.4, 2.8) for _ in range(3)])
    assert said(past) == ["Minimum passed. Reverse slightly."] and tracker.state == "passed"
    back = each(tracker, [v for v in (2.4, 2.1) for _ in range(3)] + [2.0] * 8)
    assert said(back) == ["Best focus.", "Focus good. Hold."]
    assert tracker.state == "good" and tracker.best == pytest.approx(2.0)


def test_focus_good_is_not_said_before_the_minimum_has_been_passed():
    tracker = fine(focus.FocusTracker(usual=2.0))
    assert said(each(tracker, [3.0] * 20)) == []          # held still, but who knows if it is the best
    assert tracker.state == "seeking"


def test_it_does_not_chase_the_seeing():
    tracker = fine(focus.FocusTracker(usual=2.0))
    jitter = np.random.default_rng(8).normal(3.0, 0.1, 40)
    heard = each(tracker, [float(v) for v in jitter])
    assert said(heard) == [] and {h["trend"] for h in heard} <= {"settling", "steady"}


def test_a_focuser_turned_in_steps_is_not_taken_for_scatter():
    tracker = fine(focus.FocusTracker(usual=2.0))
    each(tracker, [v for v in (3.6, 3.2, 2.8, 2.4) for _ in range(3)])
    assert tracker.scatter() < 0.05


def test_losing_focus_good_is_said_once():
    tracker = fine(focus.FocusTracker(usual=2.0))
    each(tracker, [v for v in (3.0, 2.5, 2.0, 2.5, 3.0, 2.5) for _ in range(3)] + [2.0] * 8)
    assert tracker.good
    assert said(each(tracker, [2.6] * 6)) == ["Worse. Go back."]
    assert tracker.state == "seeking"


def test_nothing_in_view_buzzes_and_is_said_once():
    tracker = focus.FocusTracker(usual=2.0)
    heard = each(tracker, [None] * 6, stars=0)
    assert {h["sound"] for h in heard} == {"buzz"} and said(heard) == ["Star lost."]
    assert tracker.state == "lost"


def test_too_few_stars_is_a_double_click_and_then_the_search_starts_again():
    tracker = focus.FocusTracker(usual=2.0)
    each(tracker, (9.0, 8.0, 7.0))
    assert tracker.level == 2
    heard = each(tracker, (7.0, 7.0, 7.0), stars=0)
    assert [h["sound"] for h in heard] == ["double"] * 3
    assert said(heard) == ["Stars lost. Level one."] and tracker.level == 1


# --- the tone -----------------------------------------------------------------------

def test_pitch_rises_in_equal_musical_steps():
    pitches = [focus.pitch(n / focus.STEPS) for n in range(focus.STEPS + 1)]
    assert pitches[0] == pytest.approx(250) and pitches[-1] == pytest.approx(1600)
    ratios = np.divide(pitches[1:], pitches[:-1])
    assert ratios == pytest.approx(ratios[0]) and ratios[0] == pytest.approx(2 ** (1 / 12), rel=0.01)
    assert focus.pitch(-1) == pitches[0] and focus.pitch(7) == pitches[-1]


def test_the_tone_rises_as_focus_improves_and_starts_afresh_on_each_level():
    tracker = focus.FocusTracker(usual=2.0)
    coarse = [h["meter"] for h in each(tracker, (30, 24, 18, 12), stars=0)]
    assert coarse == sorted(coarse) and coarse[0] < 0.3
    stars = [h["meter"] for h in each(tracker, (9.0, 8.0, 7.0, 6.0, 5.0, 4.5))]
    assert tracker.level == 2 and stars[3] < coarse[-1]          # level two began low again
    assert stars[3:] == sorted(stars[3:])
    tracker = fine(focus.FocusTracker(usual=2.0))
    sharp = [h["meter"] for h in each(tracker, [v for v in (3.6, 3.0, 2.4, 2.0) for _ in range(3)])]
    assert sharp == sorted(sharp) and sharp[0] < 0.5 < sharp[-1] < 1
    # The same size is the same pitch whenever it comes on a level.
    again = each(tracker, [3.0] * 3)[-1]["meter"]
    assert again == pytest.approx(sharp[5])


def test_every_tone_is_as_loud_as_every_other():
    low, high = focus.waveform("tone", 250), focus.waveform("tone", 1600)
    assert len(low) == len(high)
    assert np.abs(low).max() == pytest.approx(np.abs(high).max(), abs=0.02)
    body = slice(int(0.07 * focus.RATE), int(0.18 * focus.RATE))      # the note, after the click
    assert np.sqrt((low[body] ** 2).mean()) == pytest.approx(np.sqrt((high[body] ** 2).mean()), rel=0.05)


def test_a_sound_is_written_once_as_a_wav_file_and_played(tmp_path, monkeypatch):
    played = []
    monkeypatch.setattr(focus, "SOUNDS", tmp_path / "sounds")
    monkeypatch.setattr(focus.host, "play", lambda path: played.append(path) or True)
    for kind, fraction in (("tone", 0.5), ("tone", 0.5), ("double", None), ("buzz", None)):
        assert focus.sound(kind, fraction)
    assert [p.name for p in played] == ["tone-632.wav", "tone-632.wav", "double.wav", "buzz.wav"]
    with wave.open(str(played[0])) as tone:
        assert tone.getframerate() == focus.RATE and tone.getnchannels() == 1
        assert 0.15 < tone.getnframes() / focus.RATE < 0.3
    assert not list((tmp_path / "sounds").glob("*.part"))


# --- sizes that mean the same on any telescope ---------------------------------------

def test_the_levels_are_set_in_arcseconds_and_learned_from_runs_that_ended_well(tmp_path, monkeypatch):
    monkeypatch.setattr(focus, "RUNS_FILE", tmp_path / "focus_runs.jsonl")
    assert focus.usual_best() == focus.USUAL_BEST
    # 2.4 micron pixels at 750 mm: 0.66" a sensor pixel, 1.32" a pixel here.
    assert focus.arcsec_per_pixel() == pytest.approx(1.32, abs=0.005)
    focus.RUNS_FILE.write_text("".join(json.dumps({"best_arcsec": v}) + "\n" for v in (3.0, 3.4, 3.2))
                               + "not json\n", encoding="utf-8")
    assert focus.usual_best() == pytest.approx(3.2)


# --- the loop --------------------------------------------------------------------------

class Scope:
    """A made-up camera whose focuser is turned by a list: one blur a frame."""
    blurs, log = [], []
    bins = True          # False: a camera that will not bin

    def __init__(self, port=None, gain=300):
        self.binning, self.taken = 1, 0
        self.xy, self.flux = simulator.star_field("focus")

    def use(self, profile):
        from camera import PROFILES
        Scope.log.append(("use", profile))
        self.binning = PROFILES[profile] if Scope.bins else 1
        return self.binning

    def frame(self, seconds):
        Scope.log.append(("exposing", self.taken + 1))
        time.sleep(0.05)
        blur = Scope.blurs[min(self.taken, len(Scope.blurs) - 1)]
        self.taken += 1
        lum = simulator.render(self.xy, self.flux * 2, blur, seed=self.taken)
        mosaic = np.repeat(np.repeat(lum / 4, 2, axis=0), 2, axis=1)
        if self.binning > 1:
            b = self.binning
            mosaic = mosaic.reshape(mosaic.shape[0] // b, b, mosaic.shape[1] // b, b).mean(axis=(1, 3))
        return np.clip(mosaic, 0, 4095).astype(np.uint16), {"EXPTIME": seconds}

    def close(self):
        Scope.log.append(("closed", self.binning))


@pytest.fixture
def aid(tmp_path, monkeypatch):
    """focus.main() on the made-up camera; returns a function that runs it."""
    for name in ("FOCUS_FILE", "LIVE_FILE", "FRAMES_FILE", "RUNS_FILE"):
        monkeypatch.setattr(focus, name, tmp_path / getattr(focus, name).name)
    monkeypatch.setattr(focus, "SOUNDS", tmp_path / "sounds")
    monkeypatch.setattr(focus, "PREVIEW", tmp_path / "web" / "latest.jpg")
    monkeypatch.setattr(focus, "Camera", Scope)
    Scope.log, Scope.bins = [], True
    monkeypatch.setattr(focus.host, "has_sound", lambda: (focus.host.OK, "sounds"))
    monkeypatch.setattr(focus.host, "play", lambda path: Scope.log.append(("sound", path.stem)) or True)
    monkeypatch.setattr(focus.host, "speak", lambda words: Scope.log.append(("said", words)))

    def run(blurs, *options):
        Scope.blurs = blurs
        monkeypatch.setattr(sys, "argv", ["focus", "--frames", str(len(blurs)), *options])
        return focus.main()
    run.folder = tmp_path
    return run


THROUGH = [5.5] * 3 + [4.0] * 3 + [2.9] * 4 + [2.5] * 3 + [2.1] * 3 + [1.7] * 3 + [1.5] * 3 \
    + [1.9] * 3 + [2.3] * 3 + [1.9] * 3 + [1.5] * 9


def test_a_whole_focusing_run_by_ear(aid):
    reading = aid(THROUGH)
    words = [what for kind, what in Scope.log if kind == "said" and what != "Exposure increasing."]
    assert words == ["Level two.", "Level three. Fine focus.", "Minimum passed. Reverse slightly.",
                     "Best focus.", "Focus good. Hold."]
    # A click and a tone for every frame, and the pitch higher at the end than the start.
    tones = [int(what.split("-")[1]) for kind, what in Scope.log if kind == "sound"]
    assert len(tones) == len(THROUGH) and tones[-1] > 2 * tones[0]
    # Quick binned frames to begin with, the full sensor for fine focus, and
    # the camera left as the other scripts expect it.
    uses = [what for kind, what in Scope.log if kind == "use"]
    assert uses[0] == "focus_fast" and "focus_fine" in uses and uses[-1] == "imaging"
    assert Scope.log[-1] == ("closed", 1)
    assert reading["state"] == "good" and reading["level"] == 3
    assert reading["hfr"] == pytest.approx(1.177 * 1.5, rel=0.12)
    assert reading["hfr_arcsec"] == pytest.approx(reading["hfr"] * focus.arcsec_per_pixel(), abs=0.02)
    # What it reached is remembered, for the next run to set its levels by.
    run = json.loads(focus.RUNS_FILE.read_text(encoding="utf-8"))
    assert run["best_arcsec"] == pytest.approx(reading["best_hfr"] * focus.arcsec_per_pixel(), abs=0.02)
    assert focus.usual_best() == run["best_arcsec"]


def test_a_binned_reading_is_given_in_full_size_pixels(aid):
    binned = aid([4.0] * 2)                  # two frames: still on level 1, binned 2x2
    live = json.loads(focus.LIVE_FILE.read_text(encoding="utf-8"))
    assert live["binning"] == 2 and live["level"] == 1 and live["kind"] == "stars"
    Scope.bins = False
    whole = aid([4.0] * 2)
    assert json.loads(focus.LIVE_FILE.read_text(encoding="utf-8"))["binning"] == 1
    assert binned["hfr"] == pytest.approx(whole["hfr"], rel=0.08) == pytest.approx(1.177 * 4.0, rel=0.1)


def test_the_next_exposure_starts_before_this_frame_is_heard(aid):
    aid([4.0] * 4)
    order = [entry for entry in Scope.log if entry[0] in ("exposing", "sound")]
    assert [kind for kind, _ in order] == ["exposing", "exposing", "sound", "exposing", "sound",
                                           "exposing", "sound", "sound"]


def test_every_frame_is_timed(aid):
    reading = aid([4.0] * 4)
    frames = [json.loads(line) for line in focus.FRAMES_FILE.read_text(encoding="utf-8").splitlines()]
    assert [f["frame"] for f in frames] == [1, 2, 3, 4]
    for f in frames:
        timing = f["timing"]
        assert timing["capture_s"] >= 0.05                                   # the made-up camera's wait
        assert timing["feedback_s"] == pytest.approx(timing["capture_s"] + timing["process_s"], abs=0.002)
    assert frames[0]["timing"]["cycle_s"] is None and frames[1]["timing"]["cycle_s"] > 0
    assert set(reading["timing"]) == {"capture_s", "process_s", "feedback_s", "cycle_s"}
    assert reading["feedback_s"] == frames[-1]["timing"]["feedback_s"]


def test_quiet_means_no_sound_at_all(aid):
    aid([4.0] * 3, "--quiet")
    assert not [entry for entry in Scope.log if entry[0] in ("sound", "said")]


def test_a_camera_failure_ends_the_run_with_its_reason(aid, monkeypatch, capsys):
    from indi import IndiError

    def broken(self, seconds):
        raise IndiError("the camera was unplugged")
    monkeypatch.setattr(Scope, "frame", broken)
    with pytest.raises(SystemExit):
        aid([4.0] * 3, "--json")
    answer = json.loads(capsys.readouterr().out)
    assert not answer["ok"] and "unplugged" in answer["errors"][0]["message"]
    assert Scope.log[-1][0] == "closed"


class Drawtube:
    """A motor focuser on a pretend telescope: stars of HFR `sharp` at
    `best`, growing by one for every `slope` half-steps away, none past
    `reach`; gears with `slack` half-steps of play (after a reversal the
    drawtube stays put until that much has been turned); each frame's HFR
    scattered by `noise` (a standard deviation, in pixels), as seeing does."""

    def __init__(self, best, slack=0, slope=200, sharp=2.0, reach=6000, noise=0.0, seed=1):
        self.at, self.tube, self.best, self.slack, self.moves, self.going = 0, 0, best, slack, [], 0
        self.slope, self.sharp, self.reach, self.noise = slope, sharp, reach, noise
        self.rng = np.random.default_rng(seed)
        self.read_going = []        # which way the motor last turned, at each read

    def move(self, steps):
        assert steps and abs(steps) <= 4096 * 10
        self.at += steps
        self.moves.append(steps)
        way = 1 if steps > 0 else -1
        if way != self.going and self.going:
            self.play = self.slack          # the slack is taken up over however many moves it takes
        lost = min(getattr(self, "play", 0), abs(steps))
        self.play = getattr(self, "play", 0) - lost
        self.going = way
        self.tube += way * (abs(steps) - lost)

    def size(self):
        off = abs(self.tube - self.best)
        return None if off > self.reach else self.sharp + off / self.slope

    def read(self, frames):
        self.read_going.append(self.going)
        size = self.size()
        return [None if size is None else max(0.5, size + self.rng.normal(0, self.noise)) for _ in range(frames)]


def quiet(*args):
    pass


@pytest.mark.parametrize("best", [-700, -300, 0, 250, 700])
@pytest.mark.parametrize("slack", [0, 600])
def test_the_sweep_finds_focus_from_either_side_whatever_the_slack(best, slack):
    tube = Drawtube(best, slack, noise=0.2)
    result = focus.motor_focus(tube, tube.read, usual=2.0, say=quiet)
    assert result["found"], result["fit"]
    assert abs(tube.tube - tube.best) <= focus.STEP / 4
    assert tube.moves[-1] < 0                         # the last move is inward: the slack is taken up one way


def test_every_point_of_a_sweep_is_reached_moving_in():
    """The gears' slack never enters a measurement: each sweep point comes
    after an inward move."""
    tube = Drawtube(best=300, slack=600, noise=0.2)
    result = focus.motor_focus(tube, tube.read, usual=2.0, say=quiet)
    sweeps = [going for going, r in zip(tube.read_going, result["readings"]) if r["doing"] == "sweep"]
    assert sweeps and all(going == -1 for going in sweeps)


def test_seeing_that_scatters_each_frame_by_a_pixel_still_gives_focus():
    """18 October 2026: near focus single frames read 4.9, 10.6, 5.5 over 96
    half-steps. Three frames a point and a curve through all nine still
    find it."""
    for seed in range(8):
        tube = Drawtube(best=150, slack=300, noise=0.5, seed=seed)
        result = focus.motor_focus(tube, tube.read, usual=2.0, say=quiet)
        assert result["found"] and abs(tube.tube - tube.best) <= focus.STEP / 4, (seed, result["fit"])
    # A pixel of scatter a frame: focus within a step, or the start kept.
    for seed in range(8):
        tube = Drawtube(best=150, slack=300, noise=1.0, seed=seed)
        result = focus.motor_focus(tube, tube.read, usual=2.0, say=quiet)
        assert abs(tube.tube - tube.best) <= focus.STEP if result["found"] else tube.at == 0


def test_a_worse_night_is_focused_to_its_own_best_not_to_the_usual():
    """The usual best says only whether to focus: on a night of worse seeing
    the curve's own lowest point is focus."""
    tube = Drawtube(best=-200, sharp=3.2, noise=0.2)
    result = focus.motor_focus(tube, tube.read, usual=2.0, say=quiet)
    assert result["found"] and abs(tube.tube - tube.best) <= focus.STEP / 4


def test_a_sweep_that_misses_focus_moves_towards_it():
    tube = Drawtube(best=2200, noise=0.2)
    result = focus.motor_focus(tube, tube.read, usual=2.0, say=quiet)
    assert result["found"] and result["sweeps"] > 1 and abs(tube.tube - tube.best) <= focus.STEP / 4


def test_a_flat_sweep_widens_its_step():
    tube = Drawtube(best=0, slope=2000, noise=0.05)
    result = focus.motor_focus(tube, tube.read, usual=2.0, say=quiet)
    assert result["step"] > focus.STEP


def test_with_no_focus_in_reach_the_focuser_goes_back_where_it_started():
    tube = Drawtube(best=50000)
    result = focus.motor_focus(tube, tube.read, usual=2.0, say=quiet)
    assert not result["found"] and tube.at == 0 and tube.moves[-1] < 0


def test_a_fitted_focus_that_checks_worse_than_the_start_is_not_kept():
    """Seeing that goes bad just as the check is taken: the run goes back
    to where it started rather than leave focus worse."""
    tube = Drawtube(best=100, noise=0.1)
    reads = []

    def read(frames):
        reads.append(frames)
        values = tube.read(frames)
        return [v * 3 for v in values] if frames == focus.CHECK_FRAMES else values
    result = focus.motor_focus(tube, read, usual=2.0, say=quiet)
    assert not result["found"] and tube.at == 0


def test_a_run_never_goes_further_than_its_travel_from_the_start():
    tube = Drawtube(best=40000, reach=60000, slope=10000)
    focus.motor_focus(tube, tube.read, usual=2.0, say=quiet)
    position, furthest = 0, 0
    for move in tube.moves:
        position += move
        furthest = max(furthest, abs(position))
    assert furthest <= focus.MOTOR_TRAVEL


def test_a_hot_pixel_or_the_measuring_box_is_not_a_star():
    assert focus.sample(lambda frames: [0.6, None, 25.0], 3, usual=2.0)["hfr"] is None
    found = focus.sample(lambda frames: [3.0, 3.4, 2.8], 3, usual=2.0)
    assert found["hfr"] == 3.0 and found["frames"] == 3 and found["scatter"] == 0.2


def test_the_fit_refuses_a_curve_with_one_side_only():
    points = [{"at": 400 - 100 * k, "hfr": 10 - k * 0.9, "scatter": 0.1} for k in range(9)]
    fitted = focus.fit_curve(points, 100)
    assert not fitted["ok"] and fitted["reason"] == "edge" and fitted["toward"] == -1


def test_the_fit_finds_the_bottom_of_a_v():
    points = [{"at": 400 - 100 * k, "hfr": 2 + abs(400 - 100 * k - 37) / 60, "scatter": 0.1} for k in range(9)]
    fitted = focus.fit_curve(points, 100)
    assert fitted["ok"] and abs(fitted["focus"] - 37) < 20 and fitted["r2"] > 0.95


def test_the_step_is_measured_as_a_quarter_of_the_way_to_two_and_a_half_times():
    tube = Drawtube(best=0, slope=60)
    step = focus.measure_step(tube, tube.read, usual=2.0, say=quiet, backlash=500)
    # 2.5 times HFR 2 is 3 more pixels: 180 half-steps, reached at the 192 mark
    assert step == 48 and tube.at == 0 and tube.moves[-1] < 0


@pytest.mark.parametrize("slack", [300, 800])
def test_the_backlash_is_measured_and_half_as_much_again_kept(slack):
    tube = Drawtube(best=0, slack=slack, slope=200, reach=60000, noise=0.1)
    found = focus.measure_backlash(tube, tube.read, usual=2.0, step=200, say=quiet)
    assert 1.5 * slack - 100 <= found <= 1.5 * slack + 100


def test_a_motor_dry_run_turns_nothing_and_takes_no_frames(monkeypatch, capsys):
    import focuser

    def never(*args, **kwargs):
        raise AssertionError("a dry run opened the focuser or the camera")
    monkeypatch.setattr(focuser, "find_port", lambda port=None: "/dev/ttyUSB1")
    monkeypatch.setattr(focuser.Focuser, "open", classmethod(never))
    monkeypatch.setattr(focus, "Camera", never)
    monkeypatch.setattr(sys, "argv", ["focus.py", "--motor", "--dry-run", "--json"])
    with pytest.raises(SystemExit) as end:
        focus.main()
    answer = json.loads(capsys.readouterr().out)
    assert end.value.code == 0
    assert answer["ok"] and answer["data"]["would_move"] and answer["data"]["port"] == "/dev/ttyUSB1"


class StarCamera:
    """A camera whose frames measure whatever focus.measure_stars is faked to say."""

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def frame(self, seconds):
        return np.zeros((4, 4)), {}


def motor_run(monkeypatch, capsys, hfr, *flags):
    import focuser
    tube = Drawtube(best=0)
    monkeypatch.setattr(focuser.Focuser, "open", classmethod(lambda cls, *a, **k: type(
        "M", (), {"move": lambda self, n: tube.move(n), "close": lambda self: None})()))
    monkeypatch.setattr(focus, "Camera", StarCamera)
    monkeypatch.setattr(focus, "SETTLE_S", 0)
    monkeypatch.setattr(focus, "measure_stars", lambda lum: (hfr, None))
    monkeypatch.setattr(focus, "usual_best", lambda: 2.4 * focus.arcsec_per_pixel())
    monkeypatch.setattr(sys, "argv", ["focus.py", *flags, "--json"])
    with pytest.raises(SystemExit):
        focus.main()
    return json.loads(capsys.readouterr().out)["data"], tube


def test_motor_focus_measures_first_and_leaves_good_focus_alone(monkeypatch, capsys):
    # 17 October 2026: focus untouched since the night before read HFR 1.86,
    # better than usual, and the run still drove it far out and back.
    answer, tube = motor_run(monkeypatch, capsys, 1.86, "--motor")
    assert answer["left_alone"] and answer["moved"] == 0 and tube.moves == []


def test_motor_focus_anyway_turns_even_when_focus_is_good(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(focus, "motor_focus", lambda motor, read, usual, **k: (
        motor.move(32), {"hfr": 1.9, "moved": 32, "found": True, "readings": [], "fit": None,
                         "start_hfr": 1.86})[1])
    monkeypatch.setattr(focus, "RUNS_FILE", tmp_path / "runs.jsonl")
    answer, tube = motor_run(monkeypatch, capsys, 1.86, "--motor", "--anyway")
    assert tube.moves == [32] and not answer.get("left_alone")


def test_the_check_measures_and_turns_nothing(monkeypatch, capsys):
    import focuser
    monkeypatch.setattr(focuser.Focuser, "open", classmethod(lambda cls, *a, **k: pytest.fail("it turned")))
    monkeypatch.setattr(focus, "Camera", StarCamera)
    monkeypatch.setattr(focus, "usual_best", lambda: 2.4 * focus.arcsec_per_pixel())
    for hfr, good in ((1.86, True), (3.52, False)):
        monkeypatch.setattr(focus, "measure_stars", lambda lum, h=hfr: (h, None))
        monkeypatch.setattr(sys, "argv", ["focus.py", "--check", "--json"])
        with pytest.raises(SystemExit):
            focus.main()
        data = json.loads(capsys.readouterr().out)["data"]
        assert data["hfr"] == hfr and data["good"] is good


def test_focus_counts_as_done_from_a_motor_run_or_a_good_check(tmp_path, monkeypatch):
    # 17 October 2026: the patrol said "last focused 48.6 h ago" an hour after a
    # motor run, as it read only the hand aid's record.
    monkeypatch.setattr(focus, "FOCUS_FILE", tmp_path / "focus.json")
    monkeypatch.setattr(focus, "RUNS_FILE", tmp_path / "runs.jsonl")
    assert focus.last_focused() is None
    (tmp_path / "focus.json").write_text(json.dumps({"saved": 100.0}))
    (tmp_path / "runs.jsonl").write_text(json.dumps({"saved": 500.0, "best_hfr": 2.1, "best_arcsec": 2.8}) + "\n")
    assert focus.last_focused() == 500.0
    focus.seen_good(1.9, 1.32)
    assert focus.last_focused() > 500.0
    assert focus.usual_best() == 2.8      # a check does not move what good focus is


def test_measured_step_and_backlash_are_kept_and_used(monkeypatch, tmp_path):
    monkeypatch.setattr(focus, "FOCUSER_FILE", tmp_path / "focuser.json")
    assert focus.focuser_settings()["step"] == focus.STEP and not focus.focuser_settings()["step_measured"]
    focus.keep_focuser(step=120)
    focus.keep_focuser(backlash=900)
    kept = focus.focuser_settings()
    assert kept["step"] == 120 and kept["backlash"] == 900 and kept["step_measured"] and kept["backlash_measured"]


def test_each_motor_reading_is_numbered_says_its_step_and_goes_out_at_once(monkeypatch):
    """A progress report reads the log mid-run: every reading has to be in it
    the moment it is measured (18 October 2026: three minutes of a run showed
    nothing, held back until the end), numbered, with the step it took."""
    flushed = []

    class Out(io.StringIO):
        def flush(self):
            flushed.append(self.getvalue())
    out = Out()
    monkeypatch.setattr(sys, "stdout", out)
    tube = Drawtube(best=100)
    focus.motor_focus(tube, tube.read, usual=2.0)
    lines = [line.split(" ", 1)[1] for line in out.getvalue().splitlines()]     # past the time
    assert lines and len(flushed) >= len(lines)
    readings = [line for line in lines if line.strip().startswith("#")]
    assert readings[0].split()[0] == "#1" and readings[1].split()[0] == "#2"
    assert any(f"step {-focus.STEP:+5d}" in line for line in readings)
    assert any("fitted focus" in line for line in lines)        # the sweep drawn as text


STAMPED = r"^\d\d:\d\d:\d\d "


class Log(io.StringIO):
    """stdout as a log file being tailed: what had been flushed, line by line."""

    def __init__(self):
        super().__init__()
        self.shown = ""

    def flush(self):
        self.shown = self.getvalue()


def opened_motor(tube, closed=None):
    """focuser.Focuser.open() faked: a motor on `tube`, its port named."""
    link = type("Link", (), {"port": "/dev/ttyUSB7"})()
    return classmethod(lambda cls, *a, **k: type("M", (), {
        "link": link, "move": lambda self, n: tube.move(n),
        "close": lambda self: closed is not None and closed.append(True)})())


def test_a_motor_run_stamps_every_line_and_says_each_stage_before_it_waits(monkeypatch):
    """21 October 2026: a run's log stayed empty for four minutes while the
    camera hung. Each stage is said, with the time, before it is waited on."""
    import re
    import focuser
    log = Log()
    shown_at_frame = []

    class Camera(StarCamera):
        def frame(self, seconds):
            shown_at_frame.append(log.shown)
            return super().frame(seconds)
    monkeypatch.setattr(sys, "stdout", log)
    monkeypatch.setattr(focuser.Focuser, "open", opened_motor(Drawtube(best=0)))
    monkeypatch.setattr(focus, "Camera", Camera)
    monkeypatch.setattr(focus, "measure_stars", lambda lum: (1.86, None))
    monkeypatch.setattr(focus, "usual_best", lambda: 2.4 * focus.arcsec_per_pixel())
    monkeypatch.setattr(sys, "argv", ["focus.py", "--motor"])
    focus.main()
    lines = log.getvalue().splitlines()
    assert lines and all(re.match(STAMPED, line) for line in lines)
    assert log.shown == log.getvalue()                       # nothing held back at the end
    assert "focuser open on /dev/ttyUSB7" in shown_at_frame[0] and "camera open" in shown_at_frame[0]
    assert f"measuring the start: {focus.SWEEP_FRAMES} frames of 1 s" in shown_at_frame[1]
    assert "Left as it is" in lines[-1]


def hung_camera(after):
    """A camera that gives `after` frames and then times out, as on 21 October 2026."""
    import indi

    class Camera(StarCamera):
        given = 0

        def frame(self, seconds):
            if Camera.given >= after:
                raise indi.IndiError("timed out waiting for the image")
            Camera.given += 1
            return super().frame(seconds)
    return Camera


def test_a_hung_camera_ends_a_motor_run_in_one_plain_line_saying_where_the_focuser_is(monkeypatch, capsys):
    import focuser
    tube, closed = Drawtube(best=0), []
    monkeypatch.setattr(focuser.Focuser, "open", opened_motor(tube, closed))
    monkeypatch.setattr(focus, "Camera", hung_camera(after=4))     # the stale frame and the start's three
    monkeypatch.setattr(focus, "SETTLE_S", 0)
    monkeypatch.setattr(focus, "measure_stars", lambda lum: (1.86, None))
    monkeypatch.setattr(focus, "usual_best", lambda: 2.4 * focus.arcsec_per_pixel())
    monkeypatch.setattr(focus, "motor_focus", lambda motor, read, usual, **k: (motor.move(320), read(3)))
    monkeypatch.setattr(sys, "argv", ["focus.py", "--motor", "--anyway"])
    with pytest.raises(SystemExit) as end:       # not an IndiError: no traceback
        focus.main()
    import re
    line = str(end.value.code)
    assert re.match(STAMPED, line) and "\n" not in line
    assert "the camera sent no picture for 0 s: it has hung; ./camera_setup.py restarts it" in line
    assert "The focuser is where it was: +320 half-steps from the start." in line
    assert closed == [True] and tube.at == 320
    # The same with --json: the envelope says so, and stderr carries no traceback.
    capsys.readouterr()
    monkeypatch.setattr(focus, "Camera", hung_camera(after=0))
    monkeypatch.setattr(sys, "argv", ["focus.py", "--motor", "--json"])
    with pytest.raises(SystemExit) as end:
        focus.main()
    out = capsys.readouterr()
    answer = json.loads(out.out)
    assert end.value.code == 1 and answer["errors"][0]["code"] == "CAMERA_NOT_CONNECTED"
    assert "has hung" in answer["errors"][0]["message"] and "has not moved" in answer["errors"][0]["message"]
    assert "Traceback" not in out.err


def test_a_hung_camera_ends_a_check_in_one_plain_line(monkeypatch):
    import focuser
    monkeypatch.setattr(focuser.Focuser, "open", classmethod(lambda cls, *a, **k: pytest.fail("it turned")))
    monkeypatch.setattr(focus, "Camera", hung_camera(after=2))
    monkeypatch.setattr(focus, "measure_stars", lambda lum: (1.86, None))
    monkeypatch.setattr(focus, "usual_best", lambda: 2.4 * focus.arcsec_per_pixel())
    log = Log()
    monkeypatch.setattr(sys, "stdout", log)
    monkeypatch.setattr(sys, "argv", ["focus.py", "--check"])
    with pytest.raises(SystemExit) as end:
        focus.main()
    import re
    assert "it has hung; ./camera_setup.py restarts it." in str(end.value.code)
    assert "focuser" not in str(end.value.code)             # a check has no focuser to speak of
    lines = log.shown.splitlines()
    assert all(re.match(STAMPED, line) for line in lines)
    assert "camera open" in lines[1] and "focus check 1/3: HFR 1.86" in lines[2]


def test_a_late_frame_is_said_to_be_late_while_it_is_waited_for(monkeypatch):
    log = Log()
    monkeypatch.setattr(sys, "stdout", log)
    monkeypatch.setattr(focus, "SLOW_FRAME_S", 0.05)

    class Slow:
        def frame(self, seconds):
            time.sleep(0.4)
            return "picture"
    assert focus.Watched(Slow(), 0.05).frame() == "picture"
    assert "no picture from the camera after 0 s (a frame is 0.05 s): still waiting" in log.shown


def test_a_focus_reading_puts_its_frame_and_line_on_the_status_page(monkeypatch, tmp_path):
    monkeypatch.setattr(focus, "PREVIEW", tmp_path / "web" / "latest.jpg")
    lum = np.random.default_rng(0).normal(100, 5, (400, 600)).astype(np.float32)
    focus.show(lum, "  coming in   -480  HFR 6.10   best 6.10   aim 2.28")
    from PIL import Image
    with Image.open(tmp_path / "web" / "latest.jpg") as picture:
        assert picture.width == 900
    note = json.loads((tmp_path / "web" / "latest.json").read_text())
    assert note["kind"] == "focus" and "coming in -480 HFR 6.10 best 6.10 aim 2.28" in note["detail"]


def test_a_long_reading_fits_across_the_page_picture():
    from PIL import Image
    line = "20:31:35 motor focus: #12 coming in step -32 at -480 HFR 4.10 best 3.90 aim 2.28"
    image = focus.annotate(Image.new("RGB", (900, 600)), line)
    assert image.getpixel((5, 30)) == (0, 0, 0)            # the band is drawn
    assert image.crop((892, 0, 900, 60)).getbbox() is None     # nothing runs off the right edge


@pytest.mark.parametrize("best, way", [(-6000, -1), (5000, 1)])
def test_far_out_of_focus_the_stars_are_found_by_half_turns(best, way):
    tube = Drawtube(best=best, slope=200, reach=2000)
    found = focus.find_stars(tube, tube.read, usual=2.0, say=quiet)
    assert found is not None and found * way > 0 and tube.size() is not None


def test_with_no_stars_anywhere_the_search_goes_back_to_the_start():
    tube = Drawtube(best=60000)
    assert focus.find_stars(tube, tube.read, usual=2.0, say=quiet) is None and tube.at == 0


def test_far_out_the_search_turns_back_as_soon_as_the_doughnuts_grow():
    """19 October 2026: a search went a turn and a half in while focus lay
    out. The doughnuts' size, which no HFR measures, says which way."""
    tube = Drawtube(best=5000, slope=200, reach=2000)
    rings = lambda frames: 10 + abs(tube.tube - tube.best) / 100      # grows away from focus
    said = []
    found = focus.find_stars(tube, tube.read, usual=2.0, say=said.append, ring=rings)
    assert found is not None and found > 0 and tube.size() is not None
    assert sum(1 for line in said if line.lstrip().startswith("in")) == 1    # one half turn in, then back
    assert any("the other way" in line for line in said)


@pytest.mark.parametrize("start, slope", [(300, 40), (600, 80), (1500, 200)])
def test_walking_in_from_outside_ends_just_past_the_sharpest(start, slope):
    """19 October 2026: set a little out by hand (HFR 9), brought in 32
    half-steps at a time, it reached HFR 1.58 and stopped two moves past it."""
    tube = Drawtube(best=-start, slope=slope, sharp=1.6, reach=2 * start, noise=0.02)
    result = focus.walk_in(tube, tube.read, usual=2.0, say=quiet)
    assert all(step < 0 for step in tube.moves)                     # inward only
    assert result["best_hfr"] == pytest.approx(1.6, abs=0.5)
    assert abs(result["best_at"] + start) <= 64
    assert result["ended_at"] < result["best_at"] and result["ended_at"] >= -start - 2 * 64


def test_walking_in_stops_on_a_reading_that_stays_empty_and_never_jumps():
    """19 October 2026: an empty reading taken as "far out" jumped 256
    half-steps and went past focus."""
    class Gone(Drawtube):
        def read(self, frames):
            return [None] * frames if self.at <= -96 else super().read(frames)
    tube = Gone(best=-300, slope=40, reach=600)
    result = focus.walk_in(tube, tube.read, usual=2.0, say=quiet)
    assert max(abs(step) for step in tube.moves) <= 64 and result["ended_hfr"] is None


def test_walking_in_with_no_stars_at_the_start_moves_nothing():
    tube = Drawtube(best=-60000, reach=600)
    with pytest.raises(focus.interface.Refusal):
        focus.walk_in(tube, tube.read, usual=2.0, say=quiet)
    assert tube.moves == []


def test_walking_in_takes_finer_steps_near_focus_and_reads_past_a_cloud():
    """21 October 2026: 32-step moves found HFR 2.23 and the run stopped two
    moves later, and one passing cloud read 6.3 between 2.92 and 2.55."""
    class Cloud(Drawtube):
        clouded = False
        def read(self, frames):
            if not self.clouded and (self.size() or 99) < 3:
                self.clouded = True
                return [9.0] * frames
            return super().read(frames)
    tube = Cloud(best=-300, slope=40, sharp=1.6, reach=600, noise=0.02)
    said = []
    result = focus.walk_in(tube, tube.read, usual=2.0, say=said.append)
    assert any("a cloud?" in line for line in said)
    assert 16 in [-step for step in tube.moves]
    assert abs(result["best_at"] + 300) <= 32
    assert result["ended_at"] >= result["best_at"] - 3 * 16


def test_walking_in_from_doughnuts_comes_in_until_the_stars_measure():
    """21 October 2026: set "a touch out" by hand, the stars were doughnuts
    no HFR measures, and the walk-in refused to start."""
    tube = Drawtube(best=-1200, slope=40, sharp=1.6, reach=400, noise=0.02)
    rings = lambda frames: 10 + abs(tube.tube - tube.best) / 20
    result = focus.walk_in(tube, tube.read, usual=2.0, say=quiet, ring=rings)
    assert all(step < 0 for step in tube.moves)
    assert abs(result["best_at"] + 1200) <= 32


def test_walking_in_refuses_when_the_doughnuts_grow_inward():
    tube = Drawtube(best=1200, slope=40, reach=400)
    rings = lambda frames: 10 + abs(tube.tube - tube.best) / 20
    with pytest.raises(focus.interface.Refusal):
        focus.walk_in(tube, tube.read, usual=2.0, say=quiet, ring=rings)
    assert len(tube.moves) == 2


def test_walking_in_keeps_small_steps_past_the_best():
    """21 October 2026: a bad reading past the best (3.73 after 2.85) went
    back to 32-step moves and the run ended 80 half-steps inside focus."""
    tube = Drawtube(best=-300, slope=40, sharp=2.0, reach=600, noise=0.02)
    focus.walk_in(tube, tube.read, usual=2.0, say=quiet)
    past = [step for step, at in zip(tube.moves, itertools.accumulate(tube.moves)) if at < -300]
    assert past and all(-step <= 16 for step in past)
