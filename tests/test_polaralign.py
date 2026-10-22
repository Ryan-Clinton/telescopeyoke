import json
import re
import time

import pytest

import polaralign


def test_two_sides_that_agree_give_the_axis_between_them():
    agree, gap, az, alt = polaralign.cross_check((2.4, 2.8), (2.0, 2.6), 55)
    assert agree and gap < 0.4 and (az, alt) == (2.2, 2.7)


def test_two_sides_that_disagree_are_caught():
    # 13 October 2026, before the Dec axis's movement was allowed for.
    agree, gap, _, _ = polaralign.cross_check((-1.2, -0.5), (4.8, 0.2), 55)
    assert not agree and gap > 3


class FakeMount:
    dec_axis = 40.0

    def axes(self):
        return 0.0, self.dec_axis

    def save_clock(self, site):
        pass

    def drift_model(self, site):
        return type("Model", (), {"set_polar": lambda self, az, alt: None})()


def measure_twice(monkeypatch, tmp_path, first, second):
    import argparse
    import config
    monkeypatch.setattr(polaralign, "SIDES_FILE", tmp_path / "sides.json")
    monkeypatch.setattr(polaralign, "POLAR_FILE", tmp_path / "polar.json")
    monkeypatch.setattr(polaralign.mount, "CLOCK_FILE", tmp_path / "clock.json")
    monkeypatch.setattr(polaralign.config, "load", config.example)
    scope = FakeMount()
    monkeypatch.setattr(polaralign.mount, "Mount", lambda: scope)
    args = argparse.Namespace(dry_run=False, cross_check=True, step=25.0, repeat=1, turned=None)
    answers = []
    for dec_axis, found in ((40.0, first), (140.0, second)):
        scope.dec_axis = dec_axis
        monkeypatch.setattr(polaralign, "measure", lambda *a, found=found: found)
        answers.append(polaralign.run(args))
    return answers


def test_a_cross_check_that_disagrees_gives_no_advice(monkeypatch, tmp_path):
    first, second = measure_twice(monkeypatch, tmp_path, (-1.2, -0.5), (4.8, 0.2))
    assert "cross_check" not in first
    assert second["advice"] is None and not second["cross_check"]["agree"]


def test_a_cross_check_that_agrees_advises_on_the_middle(monkeypatch, tmp_path):
    _, second = measure_twice(monkeypatch, tmp_path, (2.4, 2.8), (2.0, 2.6))
    assert second["cross_check"]["agree"] and second["altitude_deg"] == 2.7


def test_an_error_too_small_to_show_in_a_frame_is_left_alone():
    """19 October 2026: half a degree on the hard-to-turn altitude bolts was
    asked for, though it could not show in a 16 s frame."""
    assert polaralign.shows(0.6, 16) == (1.0, False)
    assert polaralign.shows(3.0, 16) == (4.8, True)
    assert polaralign.shows(0.6, 120)[1]            # in a two-minute frame it would


# --- what a polar alignment tells the live stream (polar_stream.json) -----------

def rounds_of(monkeypatch, tmp_path, answers, exposure=16.0):
    """polaralign.run() once for each (azimuth, altitude) answer, as a
    person re-measuring after each adjustment; the stream file after each."""
    import argparse
    import config
    monkeypatch.setattr(polaralign, "STREAM_FILE", tmp_path / "polar_stream.json")
    monkeypatch.setattr(polaralign, "SIDES_FILE", tmp_path / "sides.json")
    monkeypatch.setattr(polaralign, "POLAR_FILE", tmp_path / "polar.json")
    monkeypatch.setattr(polaralign, "BOLTS_FILE", tmp_path / "bolts.json")
    monkeypatch.setattr(polaralign.mount, "CLOCK_FILE", tmp_path / "clock.json")
    monkeypatch.setattr(polaralign.mount, "LOCK_FILE", tmp_path / "MOTION_LOCKED")
    monkeypatch.setattr(polaralign.config, "load", lambda: dict(config.example(), mount={"tripod_cm_per_degree": 2.3}))
    monkeypatch.setattr(polaralign.mount, "Mount", FakeMount)
    args = argparse.Namespace(dry_run=False, cross_check=False, step=25.0, repeat=1, turned=None, exposure=exposure)
    out = []
    for found in answers:
        monkeypatch.setattr(polaralign, "_measure", lambda *a, found=found: found)
        polaralign.run(args)
        out.append(json.loads((tmp_path / "polar_stream.json").read_text(encoding="utf-8")))
    return out


def test_each_round_is_kept_with_the_one_before_until_it_is_under_the_drift_limit(monkeypatch, tmp_path):
    # 22 October 2026: 9.6° (16.5° west of north), then 2.5°, 4.2°, 1.8°, 1.2° from the pole.
    seen = rounds_of(monkeypatch, tmp_path, [(-16.5, 1.5), (4.2, -0.5), (7.1, -0.9), (-2.1, -1.3), (-0.4, -1.2)])
    assert [s["stage"] for s in seen] == ["adjust", "adjust", "adjust", "adjust", "complete"]
    assert [len(s["rounds"]) for s in seen] == [1, 2, 3, 4, 5]
    assert seen[1]["previous_total_deg"] == seen[0]["total_deg"] and seen[0]["previous_total_deg"] is None
    assert seen[-1]["limit_deg"] == pytest.approx(1.25) and seen[-1]["exposure_s"] == 16
    assert seen[-1]["drift_px"]["azimuth"] == polaralign.shows(-0.4, 16)[0]
    assert not any(seen[-1]["worth_turning"].values()) and seen[0]["worth_turning"]["azimuth"]
    assert seen[1]["recheck"] and not seen[0]["recheck"]


def test_the_stream_s_advice_turns_clockwise_or_anticlockwise_and_never_says_left_or_right(monkeypatch, tmp_path):
    seen = rounds_of(monkeypatch, tmp_path, [(-16.5, 1.5), (1.6, -1.6), (0.3, 0.2)])
    whole, bolts, fine = (" ".join(s["advice"]) for s in seen)
    assert "whole tripod 16.5° clockwise, seen from above" in whole and "37.9 cm at each foot" in whole, whole
    assert "Lower the polar axis 1.5°" in whole
    assert "1.6° anticlockwise, seen from above" in bolts and "Raise the polar axis 1.6°" in bolts
    assert fine.count("leave it") == 2
    for words in (whole, bolts, fine):
        assert not re.search(r"\b(left|right)\b", words, re.I), words


@pytest.fixture
def bolts(tmp_path, monkeypatch):
    monkeypatch.setattr(polaralign, "BOLTS_FILE", tmp_path / "polar_bolts.json")


def test_learned_bolts_are_named_by_the_side_they_are_on(bolts):
    polaralign.learn({"azimuth_deg": 1.0, "altitude_deg": 0.0}, {"azimuth_deg": 0.5, "altitude_deg": 0.0}, (0.5, 0))
    guidance = polaralign.guidance(1.6, 0.0)
    for axis, error in (("azimuth", 1.6), ("altitude", 0.0)):
        guidance[axis].update(zip(("drift_px", "worth_turning"), polaralign.shows(error)))
    words = " ".join(polaralign.stream_advice(guidance))
    assert "west-side bolt in (clockwise)" in words and "east-side bolt eased out first" in words


def test_a_measurement_says_which_picture_it_is_on_and_a_recheck_is_named_so(monkeypatch, tmp_path):
    import activity
    monkeypatch.setattr(polaralign, "STREAM_FILE", tmp_path / "polar_stream.json")
    seen = []

    def measuring(*a):
        seen.append((polaralign.told()["stage"], activity.phase()))
        return (1.0, 1.0)
    monkeypatch.setattr(polaralign, "_measure", measuring)
    polaralign.measure(None, {"latitude": 55})
    assert seen[-1] == ("measuring", "polar_measure") and polaralign.told()["stage"] == "measured"
    polaralign.tell(rounds=[{"total_deg": 3.0, "measured": time.time()}])
    polaralign.measure(None, {"latitude": 55})
    assert seen[-1] == ("measuring", "polar_recheck") and polaralign.told()["recheck"]
    # A round from another night starts the history again.
    polaralign.tell(rounds=[{"total_deg": 3.0, "measured": time.time() - polaralign.NIGHT_S - 60}])
    assert polaralign.rounds_tonight() == []


def test_a_failed_measurement_says_plainly_what_happened(monkeypatch, tmp_path):
    monkeypatch.setattr(polaralign, "STREAM_FILE", tmp_path / "polar_stream.json")
    for code, words in (("PLATE_SOLVE_FAILED", "could not be plate-solved"), ("MOUNT_NOT_MOVING", "did not move"),
                        ("INVALID_REQUEST", "stopped before the third picture")):
        def failing(*a, code=code):
            raise polaralign.interface.Refusal(code, "the code's own words")
        monkeypatch.setattr(polaralign, "_measure", failing)
        with pytest.raises(polaralign.interface.Refusal):
            polaralign.measure(None, {"latitude": 55})
        kept = polaralign.told()
        assert kept["stage"] == "failed" and words in kept["words"] and "Nothing was measured" in kept["words"]


def test_a_stream_file_that_cannot_be_written_never_stops_a_measurement(monkeypatch, tmp_path):
    (tmp_path / "blocked").write_text("a file where a folder should be")
    monkeypatch.setattr(polaralign, "STREAM_FILE", tmp_path / "blocked" / "polar_stream.json")
    monkeypatch.setattr(polaralign, "_measure", lambda *a: (0.5, 0.5))
    assert polaralign.measure(None, {"latitude": 55}) == (0.5, 0.5)
