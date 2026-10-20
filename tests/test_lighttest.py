"""lighttest.py: what a light round the house does to the sky, from a run's own frame records."""
import json
import sys
import types
from datetime import datetime

import jsonschema
import pytest

import lighttest

ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent


def session(tmp_path, sky_on, flux_on=90000.0):
    folder = tmp_path / "M31-P3" / "20261018-220720"
    folder.mkdir(parents=True)
    start = datetime(2026, 10, 18, 22, 7, 20).timestamp()
    rows = []
    for i in range(18):
        taken = start + 20 * (i + 1)
        lit = datetime(2026, 10, 18, 22, 9, 0).timestamp() <= taken - 16 and taken <= datetime(
            2026, 10, 18, 22, 11, 0).timestamp()
        rows.append({"index": i + 1, "accepted": True, "taken": taken, "background": (sky_on if lit else 116.0)
                     + 0.5 * ((-1) ** i), "stars": 300, "flux": (flux_on if lit else 90000.0) + 500 * ((-1) ** i),
                     "fwhm": 6.0})
    (folder / "frames.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (folder / "session.json").write_text(json.dumps({"exposure": 16}))
    return folder


def run(folder, on="22:09:00", off="22:11:00"):
    return lighttest.run(types.SimpleNamespace(session=str(folder), on=on, off=off, exposure=None),
                         say=lambda *_: None)


def test_a_light_that_brightens_the_sky_is_measured_against_the_frames_own_scatter(tmp_path):
    answer = run(session(tmp_path, sky_on=125.0))
    assert answer["frames_on"] >= 4 and answer["measures"]["background"]["change_percent"] == pytest.approx(7.8, abs=0.5)
    assert answer["verdict"].startswith("The light raises the sky by 8%") and "stars unchanged" in answer["verdict"]
    data = json.loads(json.dumps(answer))
    jsonschema.validate(data, json.loads((ROOT / "schemas" / "lighttest.schema.json").read_text()))


def test_a_light_that_changes_nothing_says_so_and_frames_across_a_switch_are_left_out(tmp_path):
    answer = run(session(tmp_path, sky_on=116.0), on="22:09:05", off="22:11:05")
    assert answer["verdict"].startswith("The light makes no measurable change")
    assert answer["frames_on"] + answer["frames_off"] < 18          # the frames across a switch


def test_after_midnight_belongs_to_the_same_night(tmp_path):
    day = datetime(2026, 10, 18, 22, 7, 20)
    assert lighttest.moment("00:30", day) > lighttest.moment("23:59", day)
    with pytest.raises(lighttest.interface.Refusal):
        run(session(tmp_path, sky_on=125.0), on="22:11:00", off="22:09:00")
    assert sys.modules["lighttest"] is lighttest
