"""Spots: more than one place in the garden the telescope is set up, each
with its own blocked directions and its own measured skyline (18 October
2026: away from the boiler's flue, where Polaris cannot be seen)."""
import importlib
import json

import pytest

import agent
import config
import interface
from test_interface import valid


@pytest.fixture
def garden(tmp_path, monkeypatch):
    """A config.toml with the house in the way, a skyline already measured
    from where the telescope has stood, and no spot named yet."""
    settings = tmp_path / "config.toml"
    text = config.EXAMPLE.read_text(encoding="utf-8").replace(
        "blocked = []", "blocked = [ { from = 274, to = 294, altitude = 47 } ]", 1)
    settings.write_text(text, encoding="utf-8")
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "horizon.json").write_text(json.dumps(
        {"saved": 1.0, "source": "trace", "skyline": [{"az": 0, "alt": 30}, {"az": 180, "alt": 25}]}), encoding="utf-8")
    (tmp_path / "horizon" / "looks").mkdir(parents=True)
    (tmp_path / "horizon" / "looks" / "001-az0-alt30.jpg").write_bytes(b"x")
    monkeypatch.setattr(config, "FILE", settings)
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(config, "SPOTS", tmp_path / "spots")
    monkeypatch.setattr(config, "DEMO", False)
    monkeypatch.setattr(config, "SPOT", None)
    return tmp_path


def reload_paths():
    import horizon
    import panorama
    importlib.reload(horizon)
    importlib.reload(panorama)
    return horizon


def test_naming_the_first_spot_keeps_what_was_measured_there(garden):
    answer = agent.set_spot("louie-side")
    assert answer["spot"] == "louie-side" and answer["skyline_measured"]
    assert (garden / "cache" / "horizon-louie-side.json").exists()
    assert not (garden / "cache" / "horizon.json").exists()
    assert (garden / "horizon" / "louie-side" / "looks" / "001-az0-alt30.jpg").exists()
    assert config._read(config.FILE)["site"]["spot"] == "louie-side"
    kept = config._read(config.spot_file("louie-side"))
    assert kept["horizon"]["blocked"] == [{"from": 274, "to": 294, "altitude": 47}]


def test_a_new_spot_starts_with_nothing_in_the_way_and_no_skyline(garden):
    agent.set_spot("louie-side")
    answer = agent.set_spot("ralphie-side")
    assert answer == {"spot": "ralphie-side", "settings": answer["settings"], "skyline_measured": False}
    assert config._read(config.spot_file("ralphie-side"))["horizon"]["blocked"] == []
    config.SPOT = config._spot()
    assert config.SPOT == "ralphie-side"
    horizon = reload_paths()
    try:
        assert horizon.RESULTS.name == "horizon-ralphie-side.json"
        cfg = config.load()
        assert cfg["horizon"]["blocked"] == [] and cfg["horizon"]["skyline"] == []
        listed = valid(interface.run("spot", agent.spots), "spot")["data"]
        assert [(s["name"], s["current"], s["skyline_measured"]) for s in listed["spots"]] == [
            ("louie-side", False, True), ("ralphie-side", True, False)]
    finally:
        config.SPOT = None
        reload_paths()


def test_going_back_to_a_spot_brings_back_its_skyline_and_blocked_directions(garden):
    agent.set_spot("louie-side")
    agent.set_spot("ralphie-side")
    agent.set_spot("louie-side")
    config.SPOT = config._spot()
    reload_paths()
    try:
        cfg = config.load()
        assert cfg["horizon"]["blocked"] == [{"from": 274, "to": 294, "altitude": 47}]
        assert [p["az"] for p in cfg["horizon"]["skyline"]] == [0, 180]
    finally:
        config.SPOT = None
        reload_paths()


@pytest.mark.parametrize("name", ["Louie Side", "../x", ""])
def test_a_spot_name_must_be_a_plain_file_name(garden, name):
    with pytest.raises(interface.Refusal):
        agent.set_spot(name)


def test_the_briefing_says_when_this_spot_has_no_skyline(monkeypatch):
    real = agent.night

    def no_skyline(demo=False):
        out = real(demo)
        return dict(out, spot="ralphie-side", skyline_measured=False)
    monkeypatch.setattr(agent, "night", no_skyline)
    text = agent.context(demo=True)
    assert "Spot: ralphie-side" in text and "NO SKYLINE MEASURED HERE" in text
