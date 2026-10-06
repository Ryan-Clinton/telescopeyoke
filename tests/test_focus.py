"""The focusing aid: its three levels, what it says and sounds, and the loop
that keeps the camera exposing while a frame is measured. No camera and no
speaker: the frames are made up and the sounds are caught."""
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
