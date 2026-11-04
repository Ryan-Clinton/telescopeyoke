"""The machine interface: one envelope, stable error codes, dry runs, the
read-only MCP server, and the agent scenarios in evals/."""
import argparse
import json
from pathlib import Path

import jsonschema
import numpy as np
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
SCENARIOS = {s["name"]: s for s in json.loads((ROOT / "evals" / "scenarios.json").read_text(encoding="utf-8"))}


def schema(name):
    return json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8"))


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
    monkeypatch.setattr(config, "DATA", tmp_path)
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


def test_unexpected_failures_still_come_back_in_an_envelope(capsys):
    result = valid(interface.run("anything", lambda: 1 / 0))
    assert not result["ok"] and result["errors"][0]["code"] == "INTERNAL_ERROR"
    out = capsys.readouterr()
    assert "Traceback" in out.err and "1 / 0" in out.err and not out.out


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
    assert plan["pier_side"] == "west" and plan["warnings"] == ["The tube goes to the west side: it swings over the pole if it is on the east side now."]
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
    sky(monkeypatch, 120.0, 45.0)      # 8 h: past the 7.5 h limit measured clear on 2 November 2026
    error = refusal(lambda: mount.plan_goto("M81", SITE))
    assert error["code"] == SCENARIOS["refuse_beyond_hour_angle"]["expected_error"]


def test_scenario_never_move_when_locked(quiet, monkeypatch):
    sky(monkeypatch, 30.0, 55.0)
    mount.LOCK_FILE.write_text("something caught on the mount", encoding="utf-8")
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
    monkeypatch.setattr(config, "DATA", quiet)
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
    assert data["object_kind"] == "deep_sky" and data["waiting"] == 0
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


def test_every_mcp_tool_publishes_the_shape_of_its_answer(quiet, monkeypatch):
    sky(monkeypatch, 30.0, 55.0)
    arguments = {"get_target": {"name": "M27", "demo": True}, "simulate_goto": {"target": "M27"}}
    for tool in mcp_server.tool_list():
        jsonschema.Draft202012Validator.check_schema(tool["outputSchema"])
        answer = mcp_server.call_tool(tool["name"], arguments.get(tool["name"], {"demo": True}))
        # A refusal (no imaging run yet) must fit the published shape too.
        jsonschema.validate(answer["structuredContent"], tool["outputSchema"])
    assert set(mcp_server.OUTPUT) == set(mcp_server.TOOLS)


def test_the_schema_version_in_code_is_the_one_published():
    assert schema("envelope")["properties"]["schema_version"]["const"] == interface.SCHEMA_VERSION


def frames(count, **late):
    """A log of good frames whose last five differ by `late`."""
    good = {"fwhm": 4.0, "roundness": 0.9, "stars": 100, "accepted": True, "reason": ""}
    return [dict(good, **(late if i >= count - 5 else {}), index=i + 1) for i in range(count)]


def test_scenario_falling_quality_is_given_a_cause():
    assert SCENARIOS["diagnose_soft_focus"]["expected_tools"] == ["get_observing_state"]
    focus = agent._explain(agent._trend(frames(20, fwhm=5.2)))
    assert len(focus) == 1 and "focus" in focus[0] and "30% wider" in focus[0]
    cloud = agent._explain(agent._trend(frames(20, stars=40)))
    assert len(cloud) == 1 and "cloud" in cloud[0]
    wind = agent._explain(agent._trend(frames(20, roundness=0.7)))
    assert len(wind) == 1 and "tracking" in wind[0]
    assert agent._explain(agent._trend(frames(20))) == []
    assert agent._trend(frames(6)) is None   # too few frames to say


def test_the_observing_state_with_nothing_running(quiet, monkeypatch):
    import focus
    monkeypatch.setattr(focus, "FOCUS_FILE", quiet / "focus.json")
    result = valid(interface.run("observing", lambda: agent.observing(demo=True)), "observing")
    assert result["data"]["optics"] == {"focus_state": "unknown"}
    assert result["data"]["imaging"] == {"state": "idle"}


def test_scripts_asked_for_json_print_nothing_else(capsys):
    def chatty():
        print("progress")
        return {"answer": 42}
    with pytest.raises(SystemExit) as stop:
        interface.main("chatty", chatty, as_json=True)
    out, err = capsys.readouterr()
    assert stop.value.code == 0 and json.loads(out)["data"] == {"answer": 42}
    assert "progress" in err and "progress" not in out
    assert interface.main("chatty", chatty) == {"answer": 42}


def test_the_depth_of_a_stack_matches_its_schema():
    import depth
    from test_depth import star_field
    image, wcs, catalogue = star_field()
    answer = valid(interface.run("depth", lambda: depth.measure(image, wcs, catalogue, plant_stars=True,
                                                                  trials=1)), "depth")
    assert answer["ok"] and "all" in answer["data"]["completeness"]


def test_the_depth_model_matches_its_schema(monkeypatch, tmp_path):
    import depth
    rows = [{"stack": "x", "seconds": t, "fwhm_arcsec": 6.0, "sky": 19.0, "mag_50": 16 + 0.3 * n}
            for n, t in enumerate((60, 120, 300))]
    monkeypatch.setattr(depth, "measurements", lambda folder=None: [dict(r) for r in rows])
    args = type("Args", (), {"predict": True, "fwhm": 4.5, "sky": 19.2, "minutes": 5.0})()
    answer = valid(interface.run("depth-model", lambda: depth.run_model(args, say=lambda *_: None)), "depth-model")
    assert answer["data"]["prediction"]["kind"] == "inferred"


def test_a_difference_matches_its_schema():
    import difference
    import numpy as np
    from test_difference import night
    rng = np.random.default_rng(4)
    xy = rng.uniform(30, (770, 570), (400, 2))
    flux = 10 ** rng.uniform(2.5, 4.5, 400)
    new = night(xy, flux, fwhm=4.5, seed=2, extra=(np.array([[400.0, 300.0]]), np.array([900.0])))
    answer = valid(interface.run("difference", lambda: difference.subtract(new, night(xy, flux, fwhm=4.0, seed=1),
                                                                             zeropoint=22.0, plant_count=40)[0]),
                   "difference")
    assert answer["ok"] and answer["data"]["candidates"]


def test_vetting_matches_its_schema():
    import vet
    from test_vet import candidate
    nothing = {"asteroids": [], "variables": [], "reported": [], "gaia": []}
    answer = valid(interface.run("vet", lambda: {
        "session": "s", "candidates": vet.vet({"candidates": [candidate()]}, nothing, half_scores=[[6.0, 6.2]]),
        "unexplained": 1, "asked": sorted(nothing), "halves_checked": True, "band": None}), "vet")
    assert answer["data"]["candidates"][0]["verdict"].startswith("unexplained")


def test_a_planting_matches_its_schema():
    import numpy as np
    import plant
    from astropy.wcs import WCS
    w = WCS(naxis=2)
    w.wcs.ctype, w.wcs.crval, w.wcs.crpix = ["RA---TAN", "DEC--TAN"], [10.0, 41.0], [300.0, 200.0]
    w.wcs.cd = np.array([[-1.32 / 3600, 0], [0, 1.32 / 3600]])
    ra, dec = w.pixel_to_world_values(np.array([100.0, 300.0]), np.array([100.0, 150.0]))
    fakes = np.column_stack([ra, dec, [15.0, 18.0]])
    result = plant.score(fakes, w, [{"x": 100, "y": 100}])
    found = result.pop("found")
    answer = valid(interface.run("plant", lambda: dict(
        result, new="n", reference="r", frames=3, unsolved=[], zeropoint=23.1,
        fakes=[{"ra": float(a), "dec": float(d), "mag": float(m), "found": f} for (a, d, m), f in zip(fakes, found)])),
        "plant")
    assert answer["data"]["false_candidates"] == 0


def test_a_reference_matches_its_schema(tmp_path, monkeypatch):
    import reference
    from test_reference import measured
    monkeypatch.setattr(config, "DATA", tmp_path)
    measured(tmp_path, "20261013-232632", 17.6)
    args = type("Args", (), {"list": False, "name": "M31", "make": True, "source": None, "force": False})()
    made = valid(interface.run("reference", lambda: reference.run(args, say=lambda *_: None)), "reference")
    assert made["data"]["made"]["version"] == 1
    args.list = True
    valid(interface.run("reference", lambda: reference.run(args, say=lambda *_: None)), "reference")


def test_a_patrol_plan_and_answer_match_their_schema(tmp_path, monkeypatch):
    import argparse
    import patrol
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(mount, "LOCK_FILE", tmp_path / "MOTION_LOCKED")
    args = argparse.Namespace(programme="m31-novae", analyse=None, minutes=None, plan=True, dry_run=False)
    valid(interface.run("patrol", lambda: patrol.run(args, say=lambda *_: None)), "patrol")
    chain = {"depth": lambda: {}, "difference": lambda: {"candidates": []}, "vet": lambda: {"candidates": []}}
    (tmp_path / "s").mkdir()
    valid(interface.run("patrol", lambda: patrol.analyse(tmp_path / "s", say=lambda *_: None, chain=chain)), "patrol")


def test_a_places_history_matches_its_schema():
    valid(interface.run("forced", lambda: {
        "name": "M31", "ra": 11.1, "dec": 41.5, "band": "unfiltered, calibrated approximately to Gaia G",
        "measurements": [{"session": "s", "stack": "f", "exposure_s": 3232.0, "x": 10.0, "y": 20.0,
                          "in_picture": True, "mag": None, "error": None, "limit": 18.0, "kind": "measured"}]}),
          "forced")


def test_the_candidates_on_file_match_their_schema(tmp_path, monkeypatch):
    import argparse
    import candidates
    monkeypatch.setattr(config, "DATA", tmp_path)
    book = candidates.load("M31")
    candidates.add_night(book, "20261014", [{"ra": 11.1, "dec": 41.5, "score": 5.4, "mag": 18.2,
                                             "verdict": "unexplained: worth a person's eyes"}])
    candidates.follow_up(book, "20261015", lambda ra, dec: (None, None, 18.4), None)
    candidates.add_night(book, "20261015", [{"ra": 11.3, "dec": 41.6, "score": 5.1, "mag": 18.4,
                                             "verdict": "unexplained: worth a person's eyes"}])
    candidates.dismiss(book, book["candidates"][-1]["id"], "hot pixel", "the same pixel each night")
    candidates.save(book)
    args = argparse.Namespace(name="M31", all=True)
    valid(interface.run("candidates", lambda: candidates.run(args, say=lambda *_: None)), "candidates")


def test_a_report_packet_matches_its_schema():
    import report
    from test_report import RECORDS, SEEN, candidate
    valid(interface.run("report", lambda: report.assemble("M31", candidate([SEEN]), None, RECORDS, None)), "report")



def test_a_sweep_matches_the_patrol_schema(tmp_path, monkeypatch):
    import patrol
    monkeypatch.setattr(config, "DATA", tmp_path)
    valid(interface.run("patrol", lambda: patrol.sweep(True, say=lambda *_: None)), "patrol")


def test_an_archive_answer_matches_its_schema(tmp_path, monkeypatch):
    import numpy as np
    import archive
    from test_archive import curve, dip
    t, f, q, quarter = curve()
    f = dip(t, f, 40.0, 0.10, fall=0.5, rise=2.0)
    monkeypatch.setattr(archive, "fetch", lambda kic, get=None, say=None: [])
    monkeypatch.setattr(archive, "catalogue_checks", lambda kic, where, get=None, variables=None: {
        "villanova": None, "vsx": [], "known_binary": None, "asked": ["Villanova Kepler EB catalogue", "VSX"]})
    monkeypatch.setattr(archive, "read", lambda paths: {"t": t, "f": f, "sap": f, "pdc_raw": f * 1000,
                                                        "sap_raw": f * 1000, "q": q, "quarter": quarter})
    one = valid(interface.run("archive", lambda: dict(archive.analyse(8462852), kind="measured")), "archive")["data"]
    assert one["tabby_like"] and one["dips"][0]["verdict"] == "dip" and np.isfinite(one["score"])
    valid(interface.run("archive", lambda: archive.search([8462852], say=lambda *_: None)), "archive")
    monkeypatch.setattr(archive, "tess_fetch", lambda tic, say=None: [])
    tess = valid(interface.run("archive", lambda: dict(archive.analyse_tess(185336364), kind="measured")),
                 "archive")["data"]
    assert tess["mission"] == "TESS" and tess["trend"] == {"sap": None, "pdcsap": None}
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(archive, "target_list", lambda get=None: [8462852])
    valid(interface.run("archive", lambda: archive.screen(1, say=lambda *_: None)), "archive")


def test_a_brokers_answer_matches_its_schema():
    import brokers
    from test_brokers import NOW, REPORTED, get
    valid(interface.run("brokers", lambda: brokers.search(config.example(), 5, 17.5, say=lambda *_: None, get=get,
                                                          reported=REPORTED, now=NOW, tns=lambda ra, dec: [],
                                                          lasair=lambda oid, mag: {"class": "SN", "matched": "NGC 1",
                                                                                   "matched_type": "galaxy",
                                                                                   "separation_arcsec": 3.0,
                                                                                   "distance_mpc": 90.0,
                                                                                   "distance_modulus": 34.8,
                                                                                   "absolute_mag": -18.4,
                                                                                   "link": "https://x"})), "brokers")


def test_a_follow_matches_the_brokers_schema(tmp_path, monkeypatch):
    import brokers
    from test_brokers import follow_get
    monkeypatch.setattr(config, "DATA", tmp_path)
    valid(interface.run("brokers", lambda: brokers.follow(
        "ZTF26acaznbf", 20, say=lambda *_: None, get=follow_get, patrol_run=lambda a: {"programme": {}},
        measure=lambda: [{"session": "s", "in_picture": True, "mag": None, "error": None, "limit": 18.2}])), "brokers")


def test_the_radio_searchs_answers_match_their_schema():
    import seti
    from test_seti import Reply, listing, looks, row
    made = looks((3000, 0.3, 8.0), off_tone=(1000, 0.0, 9.0))
    read = lambda source, low, high: made[int(source)]       # noqa: E731
    valid(interface.run("seti", lambda: seti.cadence([str(k) for k in range(6)], 2249.99, 2250.0,
                                                     say=lambda *_: None, read=read)), "seti")
    valid(interface.run("seti", lambda: seti.look("0", 2249.99, 2250.0, say=lambda *_: None, read=read)[0]), "seti")
    rows = [row("KIC8462852", 57895.42, 0), row("HIP1", 57895.43, 1)]
    valid(interface.run("seti", lambda: seti.find("KIC8462852", get=lambda *a, **k: Reply({"data": rows[:1]}, listing(rows)),
                                                  say=lambda *_: None)), "seti")


def test_a_sungrazer_look_matches_its_schema(tmp_path, monkeypatch):
    import config
    import sungrazer
    from test_sungrazer import sequence
    from PIL import Image
    monkeypatch.setattr(config, "DATA", tmp_path)
    images, _, _ = sequence()
    paths = []
    for i, image in enumerate(images):
        paths.append(tmp_path / f"20261015_{i:02d}06_c3_1024.jpg")
        Image.fromarray(np.clip(image, 0, 255).astype(np.uint8)).save(paths[-1], quality=95)
    answer = valid(interface.run("sungrazer", lambda: sungrazer.look("c3", say=lambda *_: None, paths=paths)),
                   "sungrazer")
    assert answer["data"]["pictures"] == len(images)


def test_a_variables_answer_matches_its_schema(tmp_path, monkeypatch):
    import argparse
    import variables
    from test_variables import BATCHES, made_up_night, session_with_frames
    monkeypatch.setattr(config, "DATA", tmp_path)
    images, wcs, catalogue, _ = made_up_night()
    session_with_frames(tmp_path / "frames" / "M31" / "20261014-021118", BATCHES * 10)
    real = variables.night
    monkeypatch.setattr(variables, "night", lambda s, name, size, say: real(
        s, name, size, say, stack=lambda groups: images, solve=lambda lum: wcs, gaia=lambda ra, dec, r: catalogue,
        brightest=variables.BRIGHTEST))
    args = argparse.Namespace(name="M31", session=None, bin=10, offline=True)
    answer = valid(interface.run("variables", lambda: variables.run(args, say=lambda *_: None)), "variables")
    assert answer["data"]["candidates"] == 1 and (tmp_path / "frames" / "M31" / "variables.json").exists()


def test_a_hunt_matches_the_sungrazer_schema(tmp_path, monkeypatch):
    import datetime
    import sungrazer
    from test_sungrazer import Reply
    monkeypatch.setattr(config, "DATA", tmp_path)
    seen = {"pictures": 40, "folder": "f", "candidates": [
        {"pictures": [1, 2, 3, 4, 5], "track": [[1, 2]], "towards_sun": 0.9, "times": ["t"], "pixels_per_12_min": 3.0,
         "strength": 9.0, "movie": "m.gif"}]}
    now = datetime.datetime(2026, 10, 16, 12, tzinfo=datetime.timezone.utc)
    valid(interface.run("sungrazer", lambda: sungrazer.hunt("ccor1", 24, say=lambda *_: None, now=now,
                                                            get=lambda *a, **k: Reply(""), looker=lambda: seen)),
          "sungrazer")


def test_every_fields_candidates_and_the_hunts_comets_in_one_view(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    (tmp_path / "candidates").mkdir()
    (tmp_path / "candidates" / "M31.json").write_text(json.dumps({"name": "M31", "candidates": [
        {"id": "M31-1", "ra": 10.6, "dec": 41.2, "first": "20261014", "open": True, "nights": []},
        {"id": "M31-2", "ra": 10.7, "dec": 41.3, "first": "20261006", "open": False, "nights": []}]}))
    (tmp_path / "sungrazer").mkdir()
    (tmp_path / "sungrazer" / "hunt-ccor1.json").write_text(json.dumps({"camera": "ccor1", "when": "2026-10-17 12:00",
        "towards_sun": [{"pictures": [1, 2, 3, 4, 5], "towards_sun": 0.9, "movie": "m.gif"}]}))
    answer = valid(interface.run("candidates", agent.candidates), "candidates")["data"]
    assert [k["id"] for k in answer["candidates"]] == ["M31-1"] and answer["candidates"][0]["field"] == "M31"
    assert answer["comets"] == [{"pictures": [1, 2, 3, 4, 5], "towards_sun": 0.9, "movie": "m.gif",
                                 "camera": "ccor1", "hunted": "2026-10-17 12:00"}]


def test_transits_tonight_and_measured_match_their_schema(tmp_path):
    import numpy as np
    import transits
    from test_transits import NOW, light_curve, planet
    valid(interface.run("transits", lambda: transits.tonight(config.example(), [planet()], now=NOW,
                                                             say=lambda *_: None)), "transits")
    jd, mag = light_curve()
    p = planet()
    night = {"jd": list(jd), "stars": np.array([[p["ra"], p["dec"], 11.0, 0.9]]), "mags": mag[:, None]}
    session = tmp_path / "TEST-1" / "20261016-220000"
    session.mkdir(parents=True)
    valid(interface.run("transits", lambda: transits.measure(session, "TEST-1 b", say=lambda *_: None, rows=[p],
                                                             night=night)), "transits")


def test_a_starwatch_night_matches_its_schema(tmp_path, monkeypatch):
    import starwatch
    from test_starwatch import night
    monkeypatch.setattr(config, "DATA", tmp_path)
    session = tmp_path / "frames" / "Tabby" / "20261018-193000"
    session.mkdir(parents=True)
    valid(interface.run("starwatch", lambda: starwatch.measure("tabby", session, say=lambda *_: None,
                                                               night=night(11.6, session.name))), "starwatch")
    valid(interface.run("starwatch", lambda: starwatch.look("tabby", plan=True, say=lambda *_: None,
                                                            patrol_run=lambda a: {})), "starwatch")


def test_the_rigs_view_matches_its_schema(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "RIGS", tmp_path)
    config.new_rig("heq5")
    answer = valid(interface.run("rigs", agent.rigs), "rigs")
    assert answer["ok"] and "heq5" in [rig["name"] for rig in answer["data"]["rigs"]]


def test_a_release_agrees_with_itself():
    """The version, the changelog and every download link name the same release."""
    import agent
    import release
    assert release.disagreements() == []
    title, text = release.changes()
    assert title and "Proven on" in text
    tag, name, address = release.names()
    assert tag == f"v{agent.VERSION}" and address.endswith(f"/{tag}/{name}")
    assert address in release.notes() and "doctor.py --report" in release.notes()
    assert any("pyproject" in line for line in release.disagreements("9.9.9"))


def test_a_watch_on_a_run_matches_its_schema(tmp_path):
    import argparse
    import runwatch
    folder = tmp_path / "frames" / "M31" / "s"
    folder.mkdir(parents=True)
    (folder / "frames.jsonl").write_text('{"index": 1, "taken": 1.0, "accepted": true, "flux": 1.0, "reason": "ok"}\n')
    valid(interface.run("watch-run", lambda: runwatch.run(argparse.Namespace(session=str(folder), every=60,
                                                                             once=True), say=lambda s: None)),
          "watch-run")


def test_the_agent_report_matches_its_schema(tmp_path, monkeypatch):
    import argparse
    import agentlog
    monkeypatch.setattr(config, "DATA", tmp_path)
    agentlog.write(agentlog.refusal("no-motion", {"tool_name": "Bash", "tool_input": {"command": "./mount.py nudge"},
                                                  "agent_type": "x"}, "no"))
    valid(interface.run("agent-report", lambda: agentlog.run(argparse.Namespace(days=None), say=lambda s: None)),
          "agent-report")


def test_a_test_run_matches_its_schema():
    import test_testrun
    import testrun
    runner, _ = test_testrun.fake([test_testrun.OUTPUT])
    valid(interface.run("test-run", lambda: testrun.run(argparse.Namespace(tests=[], k=None, here=True),
                                                        say=lambda s: None, runner=runner)), "test-run")


def test_a_trained_classifier_matches_its_schema(tmp_path, monkeypatch):
    import realbogus
    import test_realbogus
    monkeypatch.setattr(config, "DATA", tmp_path)
    rng = np.random.default_rng(5)
    folders = [(tmp_path / f"n{i}", {"candidates": [], "new": "n", "reference": "r"}) for i in range(2)]
    for f, _ in folders:
        f.mkdir()
    monkeypatch.setattr(realbogus, "nights", lambda: folders)

    def subtraction_of(folder, record, count, seed):
        s, u, r, p = test_realbogus.night(rng)
        return {"significance": s, "usable": u, "ref": r, "fwhm": 4.8, "planted": p}
    monkeypatch.setattr(realbogus, "subtraction_of", subtraction_of)
    valid(interface.run("realbogus", lambda: realbogus.train(40, 1, say=lambda s: None)), "realbogus")


def test_tonights_discovery_matches_its_schema(tmp_path):
    import test_discovery_view
    test_discovery_view.session(tmp_path, "M31-P6", "20991017-233312")
    valid(interface.run("discovery", lambda: agent.discovery(now=4.1e9, hours=1e6, data=tmp_path)), "discovery")


def _galaxy(id_, ra, dec, size, score, kind="galaxy"):
    return {"id": id_, "alt_id": "", "name": "", "kind": kind, "ra": ra, "dec": dec, "size": size, "minor": None,
            "score": score, "now": True, "best": None, "best_alt": 60.0, "direction": "S",
            "start": None, "end": None, "tags": []}


def _keep_reference(root, name, footprint=None):
    """A usable reference as reference.py keeps one: v1.json naming v1.fits, and its depth record."""
    import stacking
    folder = root / "reference" / stacking.folder_name(name)
    folder.mkdir(parents=True)
    (folder / "v1.fits").write_bytes(b"")
    (folder / "v1.json").write_text(json.dumps({"version": 1, "file": str(folder / "v1.fits")}))
    (folder / "v1-depth.json").write_text(json.dumps({"footprint": footprint} if footprint else {}))


def test_other_fields_offer_fresh_galaxies_beyond_the_programmes(tmp_path, monkeypatch):
    """A night full of galaxies the programmes do not watch offers them as
    fresh patrol fields: one inside a kept reference's solved frame by that
    field's name, a bright supernova flagged, and neither a galaxy in a
    programme's frames (M110 sits in M31's mosaic) nor one too small to patrol."""
    import json as _json
    monkeypatch.setattr(config, "DATA", tmp_path)
    # M81-M82's reference, solved between the pair, its long side north-south: both galaxies in it.
    scale = 0.66 / 3600
    _keep_reference(tmp_path, "M81-M82", {"ra": 148.93, "dec": 69.37, "cd": [[0, -scale], [scale, 0]],
                                          "width_px": 5496, "height_px": 3672})
    rep = {"targets": [_galaxy("M110", 10.092, 41.685, 16.2, 90),          # in M31's mosaic
                       _galaxy("M81", 148.888, 69.065, 21.6, 88),          # in the kept M81-M82 frame
                       _galaxy("M82", 148.968, 69.680, 11.0, 86),          # the same frame again
                       _galaxy("NGC 7331", 339.267, 34.416, 9.3, 64),
                       _galaxy("NGC 7814", 0.812, 16.146, 5.5, 60),        # too small
                       _galaxy("NGC 2403", 114.214, 65.603, 21.9, 58)],
           "supernovae": [{"id": "SN 2026aaiv", "name": "NGC 7331"}]}
    fields = agent.other_fields(rep, data=tmp_path)
    assert [f["field"] for f in fields] == ["M81-M82", "NGC 7331", "NGC 2403"]
    assert [f["reference"] for f in fields] == [True, False, False]
    assert fields[1]["supernova"] == "SN 2026aaiv" and fields[1]["command"] == "./patrol.py 'NGC 7331'"
    assert fields[0]["command"] == "./patrol.py M81-M82" and "reference kept: searched tonight" in fields[0]["why"]
    schema = _json.loads((Path(__file__).resolve().parent.parent / "schemas" / "night.schema.json").read_text())
    jsonschema.validate(fields, schema["properties"]["other_fields"])


def test_a_reference_folder_with_nothing_kept_is_not_a_reference(tmp_path, monkeypatch):
    """An empty or half-made folder under reference/ is not a usable
    reference: the galaxy is offered under its own name, to be made."""
    monkeypatch.setattr(config, "DATA", tmp_path)
    (tmp_path / "reference" / "NGC2403").mkdir(parents=True)          # as reference.py names it, but empty
    fields = agent.other_fields({"targets": [_galaxy("NGC 2403", 114.214, 65.603, 21.9, 58)]}, data=tmp_path)
    assert fields[0]["field"] == "NGC 2403" and fields[0]["reference"] is False


def test_the_frame_is_a_rectangle_turned_as_solved():
    """A place 0.45 degrees east of the centre is inside a frame whose 1.0
    degree side runs east-west, and outside the same frame turned a quarter
    (its 0.67 degree side east-west): a circle could tell neither."""
    import footprint
    flat = footprint.make(100.0, 0.0, 1.0, 0.67, (1, 0), (0, 1), "test")
    turned = footprint.make(100.0, 0.0, 1.0, 0.67, (0, 1), (-1, 0), "test")
    assert footprint.contains(flat, 100.45, 0.0) and not footprint.contains(turned, 100.45, 0.0)
    assert footprint.contains(turned, 100.0, 0.45) and not footprint.contains(flat, 100.0, 0.45)
    scale = 0.66 / 3600
    solved = footprint.from_solve({"ra": 100.0, "dec": 0.0, "cd": [[-scale, 0], [0, scale]],
                                   "width_px": 5496, "height_px": 3672})
    assert abs(solved["width_deg"] - 1.0076) < 1e-3 and footprint.contains(solved, 100.45, 0.0)
    assert not footprint.contains(solved, 100.0, 0.4)


def test_a_programmes_dated_watch_says_when_tonight_is_inside_a_window_and_the_next_one():
    from astropy.time import Time
    p = {"watch": [{"what": "a transit", "source": "https://doi.org/x",
                    "windows": [[2461332.2, 2461337.3], [2461419.8, 2461421.8]]}]}
    night = Time("2026-10-20T18:00:00").jd
    inside = agent.watches(p, night, night + 0.6)[0]
    assert inside["tonight"] and inside["window"] == ["2026-10-18", "2026-10-23"]
    assert inside["next"] == ["2027-01-14", "2027-01-16"]     # BJD 2461419.8 is 14 January 07:12 UTC
    tonight = Time("2026-11-03T18:00:00").jd
    out = agent.watches(p, tonight, tonight + 0.6)[0]
    assert not out["tonight"] and out["window"] is None and out["next"][0] == "2027-01-14"
    import tomllib
    tabby = tomllib.loads((agent.PROGRAMMES / "tabby.toml").read_text(encoding="utf-8"))
    assert tabby["watch"][0]["source"].endswith("stag1273")


def test_each_recommendation_says_what_it_is_from_the_catalogue_alone():
    import sky
    targets = {t["id"]: t for t in sky.load_targets()}
    assert agent.describe(targets["NGC 891"]) == "spiral galaxy (Sb), seen nearly edge-on, 13.03' x 3.03', magnitude 10"
    assert agent.describe(targets["M33"]).startswith("Triangulum Galaxy, spiral galaxy (Sc), ")
    assert "edge-on" not in agent.describe(targets["M33"]) and "face-on" not in agent.describe(targets["M33"])
    assert agent.describe({"kind": "open cluster", "size": 30.0, "mag": 3.7}) == "open cluster, 30' across, magnitude 3.7"


def test_a_field_unwatched_and_searchable_ranks_above_one_watched_last_night(tmp_path, monkeypatch):
    """Value, not the planner's order: a galaxy with a reference kept and
    not watched for a month comes before a better-placed one watched last
    night (a supernova there would have been seen), and one that only
    makes its reference tonight counts half."""
    import time as _time
    monkeypatch.setattr(config, "DATA", tmp_path)
    now = _time.time()
    _keep_reference(tmp_path, "NGC 2403")
    old = tmp_path / "frames" / "NGC2403" / _time.strftime("%Y%m%d-%H%M%S", _time.localtime(now - 30 * 86400))
    recent = tmp_path / "frames" / "NGC891" / _time.strftime("%Y%m%d-%H%M%S", _time.localtime(now - 86400))
    for d in (old, recent):
        d.mkdir(parents=True)
        (d / "light-0001.fits").write_bytes(b"")
    rep = {"targets": [_galaxy("NGC 891", 35.639, 42.349, 13.5, 95),       # watched yesterday
                       _galaxy("NGC 7331", 339.267, 34.416, 9.3, 80),      # never, no reference
                       _galaxy("NGC 2403", 114.214, 65.603, 21.9, 60)]}    # a month ago, reference kept
    fields = agent.other_fields(rep, data=tmp_path, now=now)
    assert [f["field"] for f in fields] == ["NGC 2403", "NGC 7331", "NGC 891"]
    assert fields[0]["days_since_watched"] == 30.0 and fields[1]["days_since_watched"] is None
    assert fields[2]["value"] < 0.1 and "last watched 1 days ago" in fields[2]["why"]


def test_best_tonight_is_the_big_targets_with_what_they_fill_and_their_history(tmp_path, monkeypatch):
    """The Double Cluster or Orion's nebula when they are up: objects that
    fill a quarter of the frame or more (the Double Cluster as one pair), in the planner's order, with the
    mosaic a big one needs; the small (the Ring) left out; one imaged before
    says so."""
    import time as _time
    monkeypatch.setattr(config, "DATA", tmp_path)
    now = _time.time()
    done = tmp_path / "frames" / "M42" / _time.strftime("%Y%m%d-%H%M%S", _time.localtime(now - 2 * 86400))
    done.mkdir(parents=True)
    (done / "final.fits").write_bytes(b"")
    rep = {"targets": [_galaxy("M57", 283.396, 33.029, 1.4, 99, kind="planetary nebula"),
                       _galaxy("M42", 83.822, -5.391, 85.0, 90, kind="nebula"),
                       _galaxy("NGC 869", 34.75, 57.13, 14.4, 85, kind="open cluster"),
                       _galaxy("NGC 884", 35.58, 57.15, 14.4, 84, kind="open cluster"),
                       _galaxy("C014", 35.17, 57.14, 30.0, 83, kind="open cluster")]}     # the pair's own entry
    rep["targets"] += [_galaxy("NGC 7000", 314.7, 44.3, 120.0, 70, kind="nebula"),
                       _galaxy("NGC 6826", 296.2, 50.525, 2.3, 60, kind="planetary nebula"),   # two small ones in
                       _galaxy("NGC 6811", 294.34, 46.38, 4.5, 59, kind="open cluster")]       # different frames
    best = agent.big_targets(rep, data=tmp_path, now=now)
    assert [b["id"] for b in best] == ["M42", "NGC 869", "NGC 7000"]
    assert best[0]["panels"] is not None and best[0]["frame_share"] == 1.0 and best[0]["with"] == []
    assert best[0]["nights_imaged"] == 1 and best[0]["days_since_imaged"] == 2.0
    assert best[1]["with"] == ["NGC 884"] and best[1]["panels"] is None        # the Double Cluster, one frame
    assert best[1]["nights_imaged"] == 0 and best[1]["days_since_imaged"] is None
    assert 0.4 < best[1]["frame_share"] < 0.6          # two 14.4' halves: neither is a quarter alone
    schema = json.loads((Path(__file__).resolve().parent.parent / "schemas" / "night.schema.json").read_text())
    jsonschema.validate(best, schema["properties"]["best_tonight"])


def test_two_small_objects_sharing_a_frame_are_not_a_big_target(tmp_path, monkeypatch):
    """Two 3' galaxies at opposite ends of one frame fill little of it: the
    share is what the objects cover, not the gap between them."""
    monkeypatch.setattr(config, "DATA", tmp_path)
    rep = {"targets": [_galaxy("A", 100.0, 0.0, 3.0, 80), _galaxy("B", 100.8, 0.0, 3.0, 79)]}
    assert agent.big_targets(rep, data=tmp_path) == []


def test_an_observations_outcome_matches_its_schema(tmp_path, monkeypatch):
    import outcome
    monkeypatch.setattr(config, "DATA", tmp_path)
    folder = tmp_path / "frames" / "M31-P3" / "20261104-033025"
    folder.mkdir(parents=True)
    (folder / "session.json").write_text(json.dumps({"frames": 19, "exposure": 16.0}))
    (folder / "frames.jsonl").write_text(json.dumps({"taken": 1.0, "accepted": True, "reason": ""}) + "\n")
    valid(interface.run("outcome", lambda: {"sessions": [outcome.of_session(folder)]}), "outcome")


def test_what_observing_costs_matches_its_schema(tmp_path, monkeypatch):
    import history
    monkeypatch.setattr(config, "DATA", tmp_path)
    folder = tmp_path / "frames" / "M33" / "20261104-011700"
    folder.mkdir(parents=True)
    (folder / "session.json").write_text(json.dumps({"exposure": 16.0}))
    (folder / "frames.jsonl").write_text("".join(json.dumps({"taken": 1000.0 + 21 * i, "accepted": True}) + "\n"
                                                 for i in range(5)))
    valid(interface.run("history", lambda: history.costs(data=tmp_path)), "history")


def test_a_night_replay_matches_its_schema(tmp_path, monkeypatch):
    import nightreplay
    import test_nightreplay as t
    monkeypatch.setattr(config, "DATA", tmp_path)
    t.plan(tmp_path, [{"label": "M33", "minutes": 20, "until": None, "started": t.at(1, 15), "finished": t.at(1, 35),
                       "command": ["./patrol.py", "m33-novae"]}])
    t.session(tmp_path, "M33", t.at(1, 16), 30, depth=17.5)
    night = nightreplay.load(t.EVENING, tmp_path)
    valid(interface.run("nightreplay", lambda: {
        "night": "2026-11-03", "replays": [nightreplay.replay(night, nightreplay.Current, runs=2, costs=t.COSTS)]}),
          "nightreplay")
    valid(interface.run("nightreplay", lambda: nightreplay.check(night, runs=2, costs=t.COSTS)), "nightreplay")
    # Phases 2 to 4, with a protected window, carry the visits' causes and the window's lateness.
    valid(interface.run("nightreplay", lambda: {
        "night": "2026-11-03", "replays": [nightreplay.replay(night, nightreplay.Dispatch, runs=2, protect="01:30",
                                                              costs=t.COSTS)]}), "nightreplay")


def test_goals_match_their_schema():
    import goals
    valid(interface.run("goals", lambda: goals.run(argparse.Namespace(field=None), say=lambda *a: None)), "goals")
    valid(interface.run("goals", lambda: goals.run(argparse.Namespace(field="M101"), say=lambda *a: None)), "goals")


def test_obligations_match_their_schema(tmp_path, monkeypatch):
    import obligations
    import outcome
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(obligations, "FILE", tmp_path / "obligations.json")
    monkeypatch.setattr(outcome, "night_sessions", lambda evening, d=None: [])
    (tmp_path / "candidates").mkdir()
    (tmp_path / "candidates" / "M31-P1.json").write_text(json.dumps({"name": "M31-P1", "candidates": [
        {"id": "M31-P1-x", "first": "20261104-033754", "open": True, "ra": 1.0, "dec": 2.0, "nights": [
            {"night": "20261104-033754", "seen": True, "verdict": "unexplained", "real_bogus": 0.2, "mag": 16.0}]}]}))
    obligations.owe("interrupted", "WASP-12 b", "again", "its window ended with an error", "2026-12-01")
    valid(interface.run("obligations", lambda: obligations.run(argparse.Namespace(), say=lambda *a: None)),
          "obligations")


def test_dispatch_matches_its_schema(tmp_path, monkeypatch):
    import dispatch
    import obligations
    import schedule
    import windows
    monkeypatch.setattr(obligations, "refresh", lambda: {"obligations": [], "allowance": {}})
    monkeypatch.setattr(windows, "costs", lambda: {})
    monkeypatch.setattr(dispatch, "Sky", lambda cfg=None, now=None: None)
    schedule.save({"steps": []})
    schedule.add("M33", 30, ["./shoot.py", "M33"])
    valid(interface.run("dispatch", lambda: dispatch.run(argparse.Namespace(), say=lambda *a: None)), "dispatch")
