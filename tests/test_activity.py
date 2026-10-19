"""What the telescope is doing now, as the console shows it between frames."""
import activity


def test_a_block_says_what_it_is_doing_and_clears_after():
    with activity.doing("Moving", "to M31"):
        now = activity.now()
        assert [n["words"] for n in now] == ["Moving: to M31"]
    assert activity.now() == []


def test_lines_from_ended_processes_are_dropped():
    activity._write({"999999": {"what": "Moving", "detail": "", "updated": 1e12, "started": 1e12}})
    assert activity.now(alive=lambda pid: False) == []


def test_nested_lines_come_outermost_first_with_their_counts():
    activity._write({"1": {"what": "Panel", "detail": "M31-P5", "step": 3, "of": 8, "updated": 100, "started": 10},
                     "2": {"what": "Moving", "detail": "to M31-P5", "updated": 100, "started": 50}})
    words = [n["words"] for n in activity.now(clock=lambda: 120, alive=lambda pid: True)]
    assert words == ["Panel 3 of 8: M31-P5", "Moving: to M31-P5"]


def test_a_decorated_function_fills_its_words_from_its_arguments():
    seen = []

    @activity.during("Moving", "to {name}")
    def goto(name, fast=False):
        seen.append(activity.now()[0]["words"])
        return name
    assert goto("M31") == "M31" and seen == ["Moving: to M31"] and activity.now() == []


def test_an_error_inside_still_clears_the_line():
    try:
        with activity.doing("Plate solving"):
            raise RuntimeError("no stars")
    except RuntimeError:
        pass
    assert activity.now() == []


def test_a_status_file_that_cannot_be_written_never_stops_what_it_describes(monkeypatch, tmp_path):
    """It is written from inside a GoTo: a write failing must not fail the move."""
    blocked = tmp_path / "file-not-folder"
    blocked.write_text("")
    monkeypatch.setattr(activity, "FILE", blocked / "activity.json")

    @activity.during("Moving", "to {name}")
    def goto(name):
        return "arrived"
    assert goto("M31") == "arrived" and activity.now() == []
