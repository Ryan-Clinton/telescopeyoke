"""Protected windows (docs/observing-plan-spec.md, Phase 3): a protected
start keeps its setup before it, flexible steps are timed back from it, a
deadline step may go early, and the runner tells a flexible step the
cutoff the way it tells a step its end time."""
import types

import pytest

import goals
import schedule
import windows

COSTS = {"move_s": {"median": 240.0, "p10": 80.0, "p90": 654.0, "n": 80}}
NOW = 1_000_000.0


def clock(text, now):
    """Step times in these tests are seconds after NOW, written as text."""
    return NOW + float(text)


def step(label, minutes=30, **extra):
    return {"id": label, "label": label, "minutes": minutes, "status": "queued", "command": ["true"], **extra}


def test_each_step_has_its_class():
    assert windows.protection(step("a", protect="hard", not_before="10")) == "hard"
    assert windows.protection(step("a", deadline="10")) == "deadline"
    assert windows.protection(step("a", not_before="10")) == "person"
    assert windows.protection(step("a")) == "flexible"


def test_the_setup_is_the_90th_percentile_before_a_hard_window_and_the_median_elsewhere():
    assert windows.setup_seconds(COSTS, hard=True) == 654.0 + windows.FOCUS_CHECK_S
    assert windows.setup_seconds(COSTS, hard=False) == 240.0 + windows.FOCUS_CHECK_S
    assert windows.setup_seconds({}, hard=True) == windows.SETUP_FALLBACK_S + windows.FOCUS_CHECK_S


def test_a_window_covers_its_events_uncertainty():
    hard = step("transit", protect="hard", not_before="7200", uncertainty=10)
    assert windows.frames_from(hard, NOW, clock) == NOW + 7200 - 600
    assert windows.launch_at(hard, NOW, COSTS, clock) == NOW + 7200 - 600 - 774


def test_a_flexible_step_is_timed_back_from_the_protected_start():
    steps = [step("panels", 45), step("transit", protect="hard", not_before="3600")]
    chosen, until, wait = windows.choose(steps, NOW, COSTS, clock)
    assert chosen["label"] == "panels" and until == NOW + 3600 - 774 and wait is None


def test_the_protected_step_goes_when_its_setup_is_due_whatever_is_first_in_the_list():
    steps = [step("panels", 45), step("transit", protect="hard", not_before="700")]
    chosen, until, wait = windows.choose(steps, NOW, COSTS, clock)
    assert chosen["label"] == "transit" and until is None


def test_with_too_little_time_before_the_window_nothing_flexible_starts():
    steps = [step("panels", 45), step("transit", protect="hard", not_before="1000")]
    chosen, until, wait = windows.choose(steps, NOW, COSTS, clock)
    assert chosen is None and wait == pytest.approx(1000 - 774)


def test_a_deadline_step_before_a_hard_window_is_timed_back_from_it():
    # c must be done by 5000, b's frames start at 4000: c ends before b's setup (4000 - 774),
    # so it starts by 3226 - 1200 - 360 at the latest, and nothing flexible may run past that.
    steps = [step("c", 20, deadline="5000"), step("b", 20, protect="hard", not_before="4000")]
    assert windows.cutoff(steps, NOW, COSTS, clock) == pytest.approx(NOW + 4000 - 774 - 1200 - 360)
    # A hard window is never moved for another: the earliest launch stands.
    hard_two = [step("a", 20, protect="hard", not_before="3600"), step("b", 20, protect="hard", not_before="9000")]
    assert windows.cutoff(hard_two, NOW, COSTS, clock) == NOW + 3600 - 774


def test_a_deadline_step_may_go_early_and_ends_by_its_deadline():
    steps = [step("comet", 20, deadline="5000")]
    chosen, until, wait = windows.choose(steps, NOW, COSTS, clock)
    assert chosen["label"] == "comet" and until == NOW + 5000


def test_the_runner_tells_a_flexible_step_the_cutoff(monkeypatch):
    monkeypatch.setattr(goals, "enabled", lambda phase, cfg=None: phase == "windows")
    monkeypatch.setattr(windows, "costs", lambda: COSTS)
    monkeypatch.setattr(schedule, "last_field", lambda: None)
    schedule.save({"steps": []})
    in_an_hour = __import__("time").strftime("%H:%M", __import__("time").localtime(__import__("time").time() + 3700))
    schedule.add("panels", 45, ["./patrol.py", "m31-panels"])
    schedule.add("transit", 30, ["./shoot.py", "WASP-12", "--minutes", "30"], not_before_=in_an_hour,
                 protect="hard")
    ran = []

    def start(cmd):
        ran.append(cmd)
        return types.SimpleNamespace(returncode=0)
    said, held = [], []

    def sleep(seconds):
        # The hour passes: the transit's start comes round (a full date and
        # time: by day a bare HH:MM just gone is tomorrow's).
        held.append(seconds)
        assert len(held) < 5, "the runner kept holding"
        plan = schedule.load()
        plan["steps"][1]["not_before"] = __import__("time").strftime("%Y-%m-%d %H:%M", __import__("time").localtime())
        schedule.save(plan)
    schedule.run(say=said.append, start=start, sleep=sleep)
    assert held and held[0] <= 60
    patrol_cmd = next(c for c in ran if any("patrol.py" in x for x in c))
    budget = float(patrol_cmd[patrol_cmd.index("--budget") + 1])
    # The patrol ends before the transit's setup: less than the hour, at least 30 minutes.
    assert 30 < budget <= (3700 - 774) / 60
    assert any("before the next protected start" in s for s in said)
    assert [s["status"] for s in schedule.load()["steps"]] == ["done", "done"]


def test_a_failed_hard_window_is_owed(monkeypatch, tmp_path):
    import obligations
    monkeypatch.setattr(obligations, "FILE", tmp_path / "obligations.json")
    schedule.owe_interrupted(step("WASP-12 b", protect="hard", not_before="10"), 1)
    owed = obligations.open_ones(path=tmp_path / "obligations.json")
    assert owed[0]["kind"] == "interrupted" and owed[0]["field"] == "WASP-12 b"
    schedule.owe_interrupted(step("panels"), 1)      # a flexible step owes nothing
    assert len(obligations.open_ones(path=tmp_path / "obligations.json")) == 1
