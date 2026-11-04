"""Choosing the next of tonight's agreed steps (docs/observing-plan-spec.md,
Phase 4): what is owed first, then what sets soonest, then the most
neglected field; never a step the person did not agree to."""
import json
import types
from datetime import date

import dispatch
import goals
import schedule
import windows

NOW = 1_793_800_000.0


def item(index, label, target, minutes=30, up=True, stays=None, owed=None, verdict=None, neglect=1.0):
    return {"index": index, "label": label, "id": label, "target": target, "minutes": minutes, "up": up,
            "stays_s": stays, "owed_days": owed, "owed_verdict": verdict, "neglect_days": neglect}


def labels(ranked):
    return [it["label"] for it in ranked]


def test_what_is_owed_and_near_its_expiry_goes_first():
    ranked = dispatch.rank([item(0, "M33", "M33", neglect=9), item(1, "P4 look", "M31-P4", owed=1)], NOW)
    assert labels(ranked) == ["P4 look", "M33"] and "owed, 1 days" in ranked[0]["why"]


def test_a_target_about_to_set_goes_before_one_that_stays():
    ranked = dispatch.rank([item(0, "M33", "M33", stays=None, neglect=9),
                            item(1, "M31", "M31", stays=30 * 60, neglect=2)], NOW)
    assert labels(ranked) == ["M31", "M33"]


def test_otherwise_the_most_neglected_field_and_then_the_same_target():
    ranked = dispatch.rank([item(0, "A", "M33", neglect=2), item(1, "B", "M31", neglect=8)], NOW)
    assert labels(ranked) == ["B", "A"]
    tie = dispatch.rank([item(0, "A", "M33", neglect=3), item(1, "B", "M31", neglect=3)], NOW, last_target="M31")
    assert labels(tie) == ["B", "A"]


def test_a_target_not_up_waits_its_turn():
    ranked = dispatch.rank([item(0, "SN", "NGC 3310", up=False, owed=0), item(1, "M33", "M33")], NOW)
    assert labels(ranked) == ["M33", "SN"] and "not up now" in ranked[1]["why"]


def test_a_mosaic_counts_its_most_neglected_panel(tmp_path):
    for field, name in (("M31-P1", "20261104-010000"), ("M31-P2", "20261020-010000")):
        folder = tmp_path / "frames" / field / name
        folder.mkdir(parents=True)
        (folder / "outcome.json").write_text(json.dumps({"worth_it": "met"}))
    now = __import__("datetime").datetime(2026, 11, 5, 1).timestamp()
    assert round(dispatch.field_neglect("M31-P1", tmp_path, now)) == 1
    assert dispatch.neglect(["M31-P1", "M31-P2"], tmp_path, now) == dispatch.NEGLECT_CAP_DAYS
    # A session after the moment asked about is not known yet (a replay).
    assert dispatch.field_neglect("M31-P1", tmp_path, now - 86400 * 2) == dispatch.NEGLECT_CAP_DAYS


def test_obligations_on_a_steps_fields_are_found():
    owed = [{"field": "M31-P4", "until": "2026-11-06", "weighed": {"verdict": "now"}},
            {"field": "M31-P4", "until": "2026-11-20", "telescope": False}]
    assert dispatch.owed_on(["M31-P4"], owed, date(2026, 11, 5)) == (1, "now")
    assert dispatch.owed_on(["M33"], owed, date(2026, 11, 5)) == (None, None)


def step(label, command, **extra):
    return {"id": label, "label": label, "minutes": 30, "status": "queued", "command": command, **extra}


class Up:
    """A sky where the named targets are up for the given seconds."""

    def __init__(self, rises=None, **stays):
        self.stays, self.rises = stays, rises or {}

    def window(self, target, now):
        s = self.stays.get(target.replace(" ", ""), "down")
        return (False, None) if s == "down" else (True, s)

    def rises_in(self, target, now):
        return self.rises.get(target.replace(" ", ""))


def test_with_nothing_up_no_step_is_offered_and_it_waits_for_the_first_to_rise(tmp_path, monkeypatch):
    monkeypatch.setattr(dispatch, "LOG", tmp_path / "dispatch.jsonl")
    steps = [step("M33", ["./shoot.py", "M33"]), step("SN", ["./shoot.py", "NGC 3310"])]
    chosen, until, wait, ranked = dispatch.choose(steps, NOW, Up(rises={"NGC3310": 1800}), [], {}, data=tmp_path)
    assert chosen is None and wait == 1800 and all(not it["up"] for it in ranked)
    # Nothing rising again before dawn: no step and no wait; the runner leaves them queued.
    chosen, until, wait, _ = dispatch.choose(steps, NOW, Up(), [], {}, data=tmp_path)
    assert chosen is None and wait is None


def test_it_chooses_only_among_the_agreed_queued_steps(tmp_path, monkeypatch):
    monkeypatch.setattr(dispatch, "LOG", tmp_path / "dispatch.jsonl")
    steps = [step("done one", ["./shoot.py", "M33"], status="done"),
             step("M33", ["./shoot.py", "M33"]), step("SN", ["./shoot.py", "NGC 3310"])]
    chosen, until, wait, ranked = dispatch.choose(steps, NOW, Up(M33=None, NGC3310=20 * 60), [], {}, data=tmp_path)
    assert chosen["label"] == "SN" and {it["label"] for it in ranked} == {"M33", "SN"}
    kept = json.loads((tmp_path / "dispatch.jsonl").read_text())
    assert kept["chose"] == "SN" and len(kept["offered"]) == 2


def test_the_runner_takes_dispatchs_choice(monkeypatch):
    monkeypatch.setattr(goals, "enabled", lambda phase, cfg=None: phase == "dispatch")
    monkeypatch.setattr(windows, "costs", lambda: {})
    monkeypatch.setattr(schedule, "last_field", lambda: None)
    import obligations
    monkeypatch.setattr(obligations, "refresh", lambda: {"obligations": [], "allowance": {}})
    monkeypatch.setattr(dispatch, "Sky", lambda cfg=None, now=None: Up(M33=None, NGC3310=20 * 60))
    schedule.save({"steps": []})
    schedule.add("M33", 30, ["./shoot.py", "M33"])
    schedule.add("SN", 30, ["./shoot.py", "NGC 3310"])
    ran, said = [], []
    schedule.run(say=said.append, start=lambda cmd: ran.append(cmd) or types.SimpleNamespace(returncode=0),
                 sleep=lambda s: None)
    assert [c[1] for c in ran] == ["NGC 3310", "M33"]
    assert any("chosen next: SN" in s and "up 20 more minutes" in s for s in said)
