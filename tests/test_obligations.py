"""What the night owes (docs/observing-plan-spec.md, Phase 4): candidates
weighed, not assumed; uncertain ones bounded by the follow-up allowance;
obligations kept between nights with why and until when."""
import json
from datetime import date

import pytest

import config
import obligations

TODAY = date(2026, 11, 5)


def candidate(first="20261104-033754", rb=0.6, local=6.0, mag=16.2, verdict="unexplained: worth a person's eyes",
              nights=1, **extra):
    seen = [{"night": first, "seen": True, "score": 6.0, "mag": mag, "verdict": verdict, "real_bogus": rb,
             "local_score": local}] * nights
    return {"id": f"M31-P1-{first}-001", "first": first, "open": True, "nights": seen, **extra}


def test_a_strong_candidate_goes_now():
    w = obligations.weigh(candidate(), depth_g=17.2, today=TODAY)
    assert w["verdict"] == "now" and w["level"] == 2 and w["rb_uncertainty"] is None


def test_an_uncertain_one_waits_on_the_allowance():
    w = obligations.weigh(candidate(rb=0.1), depth_g=17.2, today=TODAY)
    assert w["verdict"] == "allowance"
    weak_locally = obligations.weigh(candidate(local=2.0), depth_g=17.2, today=TODAY)
    assert weak_locally["verdict"] == "allowance"


def test_one_at_the_limit_of_its_stack_waits_for_a_deeper_night():
    w = obligations.weigh(candidate(mag=17.0), depth_g=17.2, today=TODAY)
    assert w["verdict"] == "wait" and "deeper night" in w["why"]


def test_closed_dismissed_old_or_confirmed_ones_are_not_chased():
    assert obligations.weigh(candidate(dismissed={"reason": "noise"}), 17.2, TODAY)["verdict"] == "close"
    assert obligations.weigh(candidate(first="20261020-010000"), 17.2, TODAY)["verdict"] == "close"
    assert obligations.weigh(candidate(nights=2), 17.2, TODAY)["level"] == 3


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(obligations, "FILE", tmp_path / "obligations.json")
    return tmp_path / "obligations.json"


def test_the_allowance_lets_uncertain_looks_through_until_it_is_spent(store):
    night = 10 * 3600
    uncertain = [{"verdict": "allowance", "why": "uncertain"}]
    cfg = {"plan": {"follow_up_share": 0.25}}
    assert obligations.may_follow_up(uncertain, night, now=1_793_800_000, cfg=cfg)[0]
    obligations.spend(9000, now=1_793_800_000)
    go, why = obligations.may_follow_up(uncertain, night, now=1_793_800_000, cfg=cfg)
    assert not go and "allowance is spent" in why
    # A strong one goes all the same, outside the allowance.
    assert obligations.may_follow_up([{"verdict": "now", "why": ""}], night, now=1_793_800_000, cfg=cfg)[0]
    assert not obligations.may_follow_up([{"verdict": "wait", "why": "at the limit"}], night, cfg=cfg)[0]


def test_a_patrols_second_look_is_weighed_only_with_dispatch_on(store, monkeypatch):
    import patrol
    result = {"session": "/x/M31-P1/20261104-033754",
              "depth": {"completeness": {"all": {"mag_50": 17.2}}},
              "vet": {"candidates": [{"x": 1, "y": 2, "verdict": "unexplained: worth a person's eyes",
                                      "real_bogus": 0.05, "local_score": 6.0, "mag": 16.0}]}}
    assert patrol.follow_up("M31-P1", result) == (True, None)
    on = {"plan": {"dispatch": True, "follow_up_share": 0.25}}
    monkeypatch.setattr(patrol, "night_seconds", lambda: 10 * 3600)
    go, why = patrol.follow_up("M31-P1", result, cfg=on)
    assert go and why.startswith("uncertain")
    patrol.spent((go, why), 9000)
    assert not patrol.follow_up("M31-P1", result, cfg=on)[0]
    # At the stack's limit: it waits for a deeper night, whatever the allowance.
    result["vet"]["candidates"][0]["mag"] = 17.1
    go, why = patrol.follow_up("M31-P1", result, cfg=on)
    assert not go and "deeper night" in why


def test_owed_things_are_kept_between_nights_with_why_and_until(store, tmp_path, monkeypatch):
    import outcome
    data = tmp_path / "data"
    (data / "candidates").mkdir(parents=True)
    (data / "candidates" / "M31-P1.json").write_text(json.dumps({"name": "M31-P1", "candidates": [candidate()]}))
    monkeypatch.setattr(config, "DATA", data)
    monkeypatch.setattr(outcome, "night_sessions", lambda evening, d=None: [])
    first = obligations.refresh(today=TODAY, data=data)
    owed = obligations.open_ones(first)
    assert [o["kind"] for o in owed] == ["second look"] and owed[0]["until"] == "2026-11-11"
    assert owed[0]["weighed"]["verdict"] in ("now", "allowance")
    assert json.loads(store.read_text())["obligations"][0]["state"] == "open"
    # Once the candidate is closed, the obligation is done, not forgotten.
    (data / "candidates" / "M31-P1.json").write_text(json.dumps(
        {"name": "M31-P1", "candidates": [candidate(open=False) | {"open": False}]}))
    later = obligations.refresh(today=TODAY, data=data)
    assert obligations.open_ones(later) == [] and later["obligations"][0]["state"] == "done"


def test_a_short_field_and_an_unrun_search_are_owed(store, tmp_path, monkeypatch):
    import outcome
    data = tmp_path / "data"
    (data / "candidates").mkdir(parents=True)
    monkeypatch.setattr(config, "DATA", data)
    monkeypatch.setattr(outcome, "night_sessions",
                        lambda evening, d=None: ["/x/M31-P3/20261105-033025"] if evening == date(2026, 11, 4) else [])
    monkeypatch.setattr(outcome, "of_session", lambda s: {
        "field": "M31-P3", "programme": "m31-panels", "search": "not started", "search_stopped": None,
        "searchable": "short", "worth_it": "short", "limited_by": ["6 stacked, under the 8 the search needs"]})
    owed = obligations.open_ones(obligations.refresh(today=TODAY, data=data))
    kinds = {o["kind"]: o for o in owed}
    assert set(kinds) == {"search not run", "field short"}
    assert kinds["search not run"]["telescope"] is False and "6 stacked" in kinds["field short"]["why"]
