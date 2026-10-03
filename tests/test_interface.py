"""The machine interface: one envelope, stable error codes, dry runs, the
read-only MCP server, and the agent scenarios in evals/."""
import json
from pathlib import Path

import jsonschema
import pytest

import agent
import config
import doctor
import interface
import mcp_server
import mount
import shoot
import stacking
from simulator import SimulatedHandset

ROOT = Path(__file__).parent.parent
SITE = config.example()["site"]
SCENARIOS = {s["name"]: s for s in json.loads((ROOT / "evals" / "scenarios.json").read_text())}


def schema(name):
    return json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text())


def valid(result, data_schema=None):
    """Check an answer against the envelope schema, and its data against its own."""
    plain = json.loads(json.dumps(result, default=interface.jsonable))
    jsonschema.validate(plain, schema("envelope"))
    if data_schema and plain["ok"]:
        jsonschema.validate(plain["data"], schema(data_schema))
    return plain


@pytest.fixture
def quiet(tmp_path, monkeypatch):
    """No lock file, no caches, no recorded runs."""
    for name in ("CLOCK_FILE", "POINTING_FILE", "DRIFT_FILE", "LAST_SOLVE"):
        monkeypatch.setattr(mount, name, tmp_path / f"{name}.json")
    monkeypatch.setattr(mount, "LOCK_FILE", tmp_path / "MOTION_LOCKED")
    monkeypatch.setattr(agent, "ROOT", tmp_path)
    monkeypatch.setattr(agent, "WEB", tmp_path / "web")
    return tmp_path


def sky(monkeypatch, hour_angle, altitude):
    """Put every target at a chosen hour angle (degrees) and altitude."""
    monkeypatch.setattr(mount, "where", lambda target, site, when=None: (hour_angle, 22.0, altitude))


def test_every_error_code_is_described_and_in_the_schema():
    assert set(schema("errors")["properties"]["code"]["enum"]) == set(interface.ERRORS)
    for code, (retryable, advice) in interface.ERRORS.items():
        assert isinstance(retryable, bool) and advice


def test_a_refusal_is_still_an_ordinary_exit_on_the_command_line():
    with pytest.raises(SystemExit, match="not slewing"):
        raise interface.Refusal("TARGET_BELOW_ALTITUDE_LIMIT", "M31 is only 14° up; not slewing.")


def test_unexpected_failures_still_come_back_in_an_envelope():
    result = valid(interface.run("anything", lambda: 1 / 0))
    assert not result["ok"] and result["errors"][0]["code"] == "INTERNAL_ERROR"


def test_status_and_capabilities_match_their_schemas(quiet):
    status = valid(interface.run("status", agent.status), "status")
    assert status["data"]["imaging"]["state"] == "idle"
    capabilities = valid(interface.run("capabilities", agent.capabilities), "capabilities")
    assert capabilities["data"]["motion"]["limits"]["min_altitude_deg"] == mount.MIN_ALTITUDE
    assert "stop" in capabilities["data"]["mount"]["always_allowed"]


def test_doctor_answers_in_the_envelope():
    result = valid(interface.run("doctor", lambda: doctor.report(offline=True, skip_handset=True)))
    assert set(result["data"]["ready"]) == {"planner", "mount", "imaging"}


def test_night_and_targets_in_demo_mode():
    night = valid(interface.run("night", lambda: agent.night(demo=True)), "night")
    assert night["data"]["verdict"] in ("GO", "MARGINAL", "NO-GO")
    targets = valid(interface.run("targets", lambda: agent.targets(limit=3, demo=True)))
    assert len(targets["data"]["targets"]) == 3 and targets["data"]["count"] > 3


def test_mount_status_matches_its_schema():
    scope = mount.Mount(handset=SimulatedHandset(slew_seconds=0))
    result = valid(interface.run("mount.status", lambda: mount.snapshot(scope)), "mount-status")
    assert result["data"]["state"] == "stopped" and result["data"]["at_home"]


def test_a_dry_run_describes_the_move_and_touches_no_hardware(quiet, monkeypatch):
    sky(monkeypatch, 30.0, 55.0)
    monkeypatch.setattr(mount, "Mount", lambda *a, **k: pytest.fail("a dry run opened the mount"))
    plan = mount.plan_goto("M27", SITE)
    jsonschema.validate(json.loads(json.dumps(plan)), schema("goto-plan"))
    assert plan["pier_side"] == "west" and plan["warnings"] == ["The tube will swing over the pole."]
    sky(monkeypatch, -30.0, 55.0)
    assert mount.plan_goto("M27", SITE)["warnings"] == []


# --- the scenarios in evals/ ---------------------------------------------------

def refusal(work):
    result = valid(interface.run("scenario", work))
    assert not result["ok"]
    return result["errors"][0]


def test_scenario_reject_below_horizon(quiet, monkeypatch):
    sky(monkeypatch, 30.0, 12.0)
    error = refusal(lambda: mount.plan_goto("M31", SITE))
    assert error["code"] == SCENARIOS["reject_below_horizon"]["expected_error"]
    assert not error["retryable"]


def test_scenario_refuse_beyond_hour_angle(quiet, monkeypatch):
    sky(monkeypatch, 105.0, 45.0)
    error = refusal(lambda: mount.plan_goto("M81", SITE))
    assert error["code"] == SCENARIOS["refuse_beyond_hour_angle"]["expected_error"]


def test_scenario_never_move_when_locked(quiet, monkeypatch):
    sky(monkeypatch, 30.0, 55.0)
    mount.LOCK_FILE.write_text("something caught on the mount")
    assert agent.capabilities()["motion"]["locked"]
    assert agent.capabilities()["motion"]["lock_reason"] == "something caught on the mount"
    error = refusal(lambda: mount.plan_goto("M27", SITE))
    assert error["code"] == SCENARIOS["never_move_when_locked"]["expected_error"]
    assert agent.target("M27", demo=True)["goto"]["allowed"] is False


def test_scenario_handset_not_set_up():
    error = refusal(lambda: mount.Mount(handset=SimulatedHandset(year=22)))
    assert error["code"] == SCENARIOS["handset_not_set_up"]["expected_error"]


def test_scenario_unknown_target(quiet):
    error = refusal(lambda: agent.target("Flying Spaghetti Nebula", demo=True))
    assert error["code"] == SCENARIOS["unknown_target"]["expected_error"]


def test_scenario_no_session_yet(quiet):
    error = refusal(agent.session)
    assert error["code"] == SCENARIOS["no_session_yet"]["expected_error"]


def test_scenario_diagnose_cloud(quiet, monkeypatch):
    monkeypatch.setattr(shoot, "ROOT", quiet)
    monkeypatch.setattr(shoot, "WEB", quiet / "web")
    run = shoot.Session("M27", exposure=2.0, gain=1500, frames=20, save=False)
    clear = {"fwhm": 4.0, "roundness": 0.9, "stars": 100, "flux": 5e4, "background": 300, "noise": 5.0}
    for i in range(1, 11):
        cloudy = i > 6
        entry = dict(clear, index=i, accepted=not cloudy,
                     reason="star brightness down 60% (cloud)" if cloudy else "",
                     shift=[1.0 * i, 0.5 * i], rotation=0.0)
        run.log.append(entry)
        stacking.append_log(run.folder, entry)
    result = valid(interface.run("session", lambda: agent.session(include_frames=True, limit=5)),
                   "image-session")
    data = result["data"]
    assert (data["captured"], data["accepted"], data["rejected"]) == (10, 6, 4)
    assert data["reasons"] == {"star brightness down (cloud)": 4}
    assert len(data["frames"]) == 5 and data["state"] == "capturing"
    # Without asking for frames the answer stays small.
    assert "frames" not in agent.session() and "series" not in agent.session()


def test_scenario_read_only_interfaces(quiet, monkeypatch):
    names = {tool["name"] for tool in mcp_server.tool_list()}
    assert names == set(mcp_server.TOOLS)
    moving = ("goto", "home", "zenith", "slew", "point", "capture", "start", "request", "sync")
    assert [n for n in names if any(word in n for word in moving)] == ["simulate_goto"]
    assert all(tool["annotations"]["readOnlyHint"] for tool in mcp_server.tool_list())
    import serve
    assert not hasattr(serve.Handler, "do_POST") and not hasattr(serve.Handler, "do_PUT")
    for scenario in SCENARIOS.values():
        assert set(scenario["expected_tools"]) <= names


# --- the MCP server --------------------------------------------------------------

def rpc(method, params=None, ident=1):
    return mcp_server.handle({"jsonrpc": "2.0", "id": ident, "method": method, "params": params or {}})


def test_mcp_handshake_and_tool_list():
    hello = rpc("initialize", {"protocolVersion": "2025-03-26"})["result"]
    assert hello["protocolVersion"] == "2025-03-26" and hello["serverInfo"]["name"] == "telescopeyoke"
    assert rpc("initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"] \
        == mcp_server.PROTOCOLS[0]
    assert mcp_server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    tools = rpc("tools/list")["result"]["tools"]
    assert all(t["inputSchema"]["type"] == "object" and t["description"] for t in tools)
    assert rpc("ping")["result"] == {}
    assert rpc("no/such/method")["error"]["code"] == -32601


def test_mcp_tool_results_are_envelopes(quiet, monkeypatch):
    sky(monkeypatch, 30.0, 55.0)
    result = rpc("tools/call", {"name": "simulate_goto", "arguments": {"target": "M27"}})["result"]
    assert not result["isError"]
    valid(result["structuredContent"], "goto-plan")
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]
    sky(monkeypatch, 30.0, 12.0)
    refused = rpc("tools/call", {"name": "simulate_goto", "arguments": {"target": "M27"}})["result"]
    assert refused["isError"]
    assert refused["structuredContent"]["errors"][0]["code"] == "TARGET_BELOW_ALTITUDE_LIMIT"
    assert rpc("tools/call", {"name": "launch_missiles"})["error"]["code"] == -32602


def test_mcp_resources(quiet):
    listed = {r["uri"] for r in rpc("resources/list")["result"]["resources"]}
    assert listed == set(mcp_server.RESOURCES)
    read = rpc("resources/read", {"uri": "telescope://status"})["result"]["contents"][0]
    valid(json.loads(read["text"]), "status")
    assert rpc("resources/read", {"uri": "telescope://nope"})["error"]["code"] == -32002


def test_the_briefing_states_the_motion_rule(quiet):
    text = agent.context(demo=True)
    assert "a person must ask for each move" in text and "--dry-run" in text
    assert len(text.splitlines()) < 30   # a briefing, not a manual
