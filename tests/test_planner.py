"""The night report end to end in demo mode, the INDI client's message
handling, and small lookups."""
from pathlib import Path
from xml.etree.ElementTree import XMLPullParser

import pytest

import config
import feeds
import indi
import tonight


def test_demo_report_builds_without_network_or_setup():
    report = tonight.build(config.example(), demo=True)
    assert report["weather"]["verdict"] in ("GO", "MARGINAL", "NO-GO")
    assert report["light_pollution"]["sqm"] == 20.55
    scores = [t["score"] for t in report["targets"]]
    assert scores == sorted(scores, reverse=True)
    text = tonight.render_text(report, 10)
    assert "Weather:" in text and "Top 10" in text


def test_report_renders_as_a_web_page(tmp_path):
    report = tonight.build(config.example(), demo=True)
    tonight.write_html(report, 10, tmp_path / "index.html")
    page = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "<table>" in page and "My back garden" in page


def test_bortle_class_from_sky_brightness():
    assert [feeds.bortle(s) for s in (22.0, 21.0, 20.0, 19.0, 18.0)] == [1, 4, 5, 6, 8]


def test_field_of_view_comes_from_the_sensor_and_focal_length():
    cfg = config.example()
    assert round(config.field_height(cfg), 2) == 0.67
    cfg["scope"]["focal_length_mm"] = 1500
    assert round(config.field_height(cfg), 2) == 0.33


def client():
    """An INDI client with no server behind it, to feed messages to by hand."""
    c = indi.Indi.__new__(indi.Indi)
    c.parser = XMLPullParser(["start", "end"])
    c.parser.feed("<stream>")
    c.depth, c.props, c.blobs, c.messages = 0, {}, [], []
    return c


def feed(c, xml):
    c.parser.feed(xml)
    for event, el in c.parser.read_events():
        c.depth += 1 if event == "start" else -1
        if event == "end" and c.depth == 1:
            c._handle(el)


def test_indi_properties_are_tracked_for_awkward_device_names():
    c = client()
    device = "Altair ALTAIRH183C(USB2.0)"   # the dot breaks the stock INDI tools
    feed(c, f'<defSwitchVector device="{device}" name="CONNECTION" state="Idle">'
            '<defSwitch name="CONNECT">Off</defSwitch>'
            '<defSwitch name="DISCONNECT">On</defSwitch></defSwitchVector>')
    assert c.get(device, "CONNECTION", "CONNECT") == "Off"
    feed(c, f'<setSwitchVector device="{device}" name="CONNECTION" state="Ok">'
            '<oneSwitch name="CONNECT">On</oneSwitch></setSwitchVector>')
    assert c.get(device, "CONNECTION", "CONNECT") == "On"
    assert c.props[(device, "CONNECTION")]["state"] == "Ok"
    assert c.devices() == [device]


def test_indi_images_and_messages_are_collected():
    c = client()
    feed(c, '<setBLOBVector device="cam" name="CCD1"><oneBLOB name="CCD1" format=".fits">'
            'aGVsbG8=</oneBLOB></setBLOBVector>')
    assert c.blobs == [("cam", ".fits", b"hello")]
    feed(c, '<message device="cam" message="[INFO] ready"/>')
    assert c.messages == ["[INFO] ready"]
    feed(c, '<defNumberVector device="cam" name="CCD_EXPOSURE" state="Idle">'
            '<defNumber name="CCD_EXPOSURE_VALUE">1</defNumber></defNumberVector>')
    feed(c, '<delProperty device="cam" name="CCD_EXPOSURE"/>')
    assert c.get("cam", "CCD_EXPOSURE") is None


def test_doctor_runs_with_nothing_attached():
    import doctor
    results = doctor.run(offline=True, skip_handset=True)
    assert set(results) == {"planner", "mount", "imaging"}
    for checks in results.values():
        assert all(status in (doctor.OK, doctor.WARN, doctor.FAIL) and message
                   for status, message in checks)
    assert doctor.check_python()[0] == doctor.OK
    assert doctor.check_catalogue()[0] == doctor.OK


class Wire:
    """A handset that gives fixed answers, read the way a serial port is read:
    up to the first "#", or so many bytes, whichever comes first."""

    def __init__(self, answers):
        self.answers, self.waiting, self.asked = answers, b"", []

    def write(self, question):
        self.asked.append(question)
        self.waiting += self.answers.get(question, b"")

    def read_until(self, end, size):
        cut = self.waiting.find(end)
        taken = min(size, cut + 1 if cut >= 0 else len(self.waiting))
        out, self.waiting = self.waiting[:taken], self.waiting[taken:]
        return out


def test_the_handset_says_what_it_is_and_what_it_drives():
    import doctor
    # Firmware 3.35 in two bytes: the second byte is itself the "#" that ends an answer.
    old = Wire({b"V": bytes([3, 35]) + b"#", b"m": bytes([3]) + b"#"})
    assert doctor.identity(old) == ("EQ3", "3.35") and old.waiting == b""
    new = Wire({b"V": b"042507#", b"m": bytes([1]) + b"#"})
    assert doctor.identity(new) == ("HEQ5", "4.37.07")
    assert doctor.identity(Wire({b"V": bytes([4, 12]) + b"#", b"m": bytes([2]) + b"#"})) == ("EQ5", "4.12")
    assert doctor.identity(Wire({b"V": b"042507#", b"m": bytes([144]) + b"#"}))[0].startswith("model number 144")
    # Only questions that read, and a handset that says nothing leaves gaps, not a crash.
    silent = Wire({})
    assert doctor.identity(silent) == (None, None) and silent.asked == [b"V", b"m"]
    from simulator import SimulatedHandset
    assert doctor.identity(SimulatedHandset())[0] == "EQ3"


def test_a_hardware_report_leaves_out_who_and_where(monkeypatch, tmp_path):
    import config
    import doctor
    settings = tmp_path / "config.toml"
    settings.write_text(config.EXAMPLE.read_text(encoding="utf-8")
                        .replace("My back garden", "Number 9 Secret Street").replace("51.4779", "12.3456"), encoding="utf-8")
    monkeypatch.setattr(config, "FILE", settings)
    monkeypatch.setattr(config, "DEMO", False)
    assert "Number 9 Secret Street" in doctor.check_config()[1]
    monkeypatch.setattr(doctor, "check_solver", lambda: (doctor.FAIL, f"not found in {Path.home() / 'astap'}"))
    # No test opens the real handset's lead, plugged in or not.
    monkeypatch.setattr(doctor, "check_handset", lambda: (doctor.OK, "a handset made up for the test"))
    asked = []
    monkeypatch.setattr(doctor, "handset_identity", lambda: asked.append(1) or ("EQ5", "4.39.05"))
    text = doctor.hardware_report(offline=True, skip_handset=True)
    assert "hardware report" in text and "Ready for planner" in text and "Serial ports seen" in text
    assert "Secret Street" not in text and "12.3456" not in text and str(Path.home()) not in text
    assert "with a location set" in text and "~" in text
    assert not asked and "Handset firmware" not in text         # told to leave the handset alone
    if doctor.mount_link() == "handset":
        text = doctor.hardware_report(offline=True)
        assert "as the handset names it: EQ5" in text and "Handset firmware: 4.39.05" in text


def test_doctor_verdict_needs_the_planner_basics_for_everything():
    import doctor
    good, bad = [(doctor.OK, "fine")], [(doctor.FAIL, "broken")]
    warned = [(doctor.WARN, "not ideal")]
    assert doctor.ready({"planner": good, "mount": warned, "imaging": bad}) == {
        "planner": True, "mount": True, "imaging": False}
    assert doctor.ready({"planner": bad, "mount": good, "imaging": good}) == {
        "planner": False, "mount": False, "imaging": False}


def test_a_recorded_run_becomes_an_animation(tmp_path):
    import json
    from PIL import Image
    import replay
    Image.new("RGB", (160, 107), (40, 40, 60)).save(tmp_path / "frame-01.jpg")
    (tmp_path / "steps.json").write_text(json.dumps([
        {"text": "M27 Dumbbell Nebula: altitude 53°", "frame": 0, "time": 0},
        {"text": "  off by +11.4' in hour angle", "frame": 1, "time": 40},
        {"text": "  centred", "frame": 1, "time": 80}]), encoding="utf-8")
    frames = replay.build(tmp_path, command="./mount.py goto M27 --solve")
    assert len(frames) == 3 and frames[0].size == frames[2].size


def test_the_status_page_has_its_console_sections(tmp_path):
    import page
    report = tonight.build(config.example(), demo=True)
    text = page.render(report, 10, tmp_path)
    for expected in ("Tonight", "Clear window", "Moon", "Dew risk", 'id="run"', 'id="system"',
                     "The night", "All 10 ranked targets", "Weather hour by hour"):
        assert expected in text
    assert ("Best now" in text) or ("Best tonight" in text)
    assert "$" not in text.split("<script>")[0]   # every placeholder was filled in


def test_weather_cells_are_coloured_by_how_bad_they_are():
    import page
    assert page.level(8, 25, 60) == "good" and page.level(45, 25, 60) == "fair"
    assert page.level(90, 25, 60) == "bad"
    assert page.level(5.0, 4, 2, higher_is_better=True) == "good"
    assert page.level(1.0, 4, 2, higher_is_better=True) == "bad"
    assert [page.condition(c) for c in (2, 4, 7)] == ["Good", "Average", "Poor"]


def test_targets_carry_the_reasons_for_their_rank():
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 10, 3, 22, 0, tzinfo=timezone.utc)
    target = {"kind": "galaxy", "best_alt": 72, "sky": 20.5, "moon_sep": 95, "hours": 5.0,
              "start": now - timedelta(hours=1), "end": now + timedelta(hours=4)}
    assert tonight.target_tags(target, {"sqm": 20.55}, now) == ["HIGH", "DARK SKY", "GOOD WINDOW"]
    washed = dict(target, best_alt=25, sky=19.2, hours=1.0, start=now + timedelta(hours=2))
    assert tonight.target_tags(washed, {"sqm": 20.55}, now) == ["LOW", "MOONLIGHT", "MOON FAR", "FROM 00:00"]


def test_the_demo_page_has_a_made_up_run_to_show():
    import demo
    status = demo.status()
    assert status["captured"] == status["accepted"] + status["rejected"]
    assert len(status["series"]["fwhm"]) == len(status["series"]["accepted"]) == 60


def test_a_horizon_sweep_becomes_the_planners_blocked_list():
    import horizon
    looks = []
    for az in (0, 90, 180, 270):
        for alt in (25, 40, 55, 70):
            house = az in (180, 270) and alt <= 40      # stars only above 40° to the south and west
            wall = az == 0                              # nothing at all to the north
            looks.append({"az": az, "alt": alt, "open": None if (az == 90 and alt == 25) else
                          not (house or wall)})
    assert horizon.blocked(looks) == [
        {"from": 315.0, "to": 45.0, "altitude": 90},
        {"from": 135.0, "to": 315.0, "altitude": 48}]
    assert "#" in horizon.chart(looks) and "." in horizon.chart(looks)
    assert len(horizon.looks(30)) == 48


def made_up_skyline(az):
    """A house to the south 40° high, a tree at 300° reaching 58°, a fence
    below the lowest look everywhere else."""
    return 40 if 140 <= az <= 220 else 58 if az == 300 else 10


def watcher(skyline=made_up_skyline, unreachable=lambda az, alt: False):
    seen = []

    def look(az, alt):
        seen.append((az, alt))
        return None if unreachable(az, alt) else alt > skyline(az)
    look.seen = seen
    return look


def test_tracing_follows_the_top_of_what_is_in_the_way():
    import horizon
    look = watcher()
    found, warnings = horizon.trace(look, list(range(0, 360, 20)), low=20)
    assert not warnings
    for f in found:
        real = made_up_skyline(f["az"])
        if real < 20:
            assert f["state"] == "open" and f["clear"] == 20
        else:
            assert f["state"] == "edge" and f["shut"] <= real < f["clear"] <= real + horizon.FINE
    # Corners get a look in between: the house's ends and both sides of the tree.
    assert {130, 230, 290, 310} <= {f["az"] for f in found}
    # Far fewer looks than a grid as fine would take (18 bearings x 18 heights).
    assert len(look.seen) < 80
    walls = horizon.skyline_blocked(found)
    assert {"from": 135.0, "to": 225.0} == {k: walls[0][k] for k in ("from", "to")}
    assert 40 < walls[0]["altitude"] <= 43
    assert "blocked up to" in horizon.profile(found, 20)


def test_tracing_checks_itself():
    import horizon
    import interface
    # No sky anywhere: it stops before surveying anything.
    with pytest.raises(interface.Refusal) as refusal:
        horizon.trace(watcher(lambda az: 90), [0, 90, 180, 270], low=20)
    assert refusal.value.code_name == "NO_SKY"

    # Something that passes for sky with nothing but wall above it is doubted.
    def patchy(az, alt, seen=[]):
        return alt > 30 and not (az == 90 and 44 <= alt <= 60)
    found, warnings = horizon.trace(patchy, [0, 90, 180, 270], low=20)
    assert [f.get("doubt") for f in found] == [None, True, None, None]
    assert "Bearing 90" in warnings[0]

    # The mount slips part-way round: the first bearing no longer looks the same.
    calls = []

    def slipping(az, alt):
        calls.append(az)
        return alt > (30 if len(calls) < 12 else 50)
    found, warnings = horizon.trace(slipping, [0, 90, 180, 270], low=20)
    assert any("different answer" in w for w in warnings)


def test_tracing_leaves_out_what_the_mount_may_not_reach():
    import horizon
    # Nothing below 50° may be looked at towards the north; all of the west is out.
    limits = lambda az, alt: (az == 0 and alt < 50) or az == 270
    found, _ = horizon.trace(watcher(unreachable=limits), [0, 90, 180, 270], low=20)
    states = {f["az"]: f["state"] for f in found}
    assert states == {0: "open", 90: "open", 135: "open", 180: "edge", 270: "unreachable"}
    assert found[0]["clear"] >= 50
    house = next(f for f in found if f["az"] == 180)
    assert [w["altitude"] for w in horizon.skyline_blocked(found)] == [house["clear"]]


def test_daylight_tells_sky_from_wall():
    import horizon
    import numpy as np
    sky = np.full((640, 960), 1300, np.uint16)
    wall = np.full((640, 960), 250, np.uint16)
    rooftop = sky.copy()
    rooftop[320:] = 250          # the edge of a roof across the middle of the frame
    dusty = sky.copy()
    dusty[100:110, 200:210] = 300   # a dust speck is not a wall
    assert horizon.is_sky(sky, 1300)[0] and horizon.is_sky(dusty, 1300)[0]
    assert horizon.is_sky(sky * 0.6, 1300)[0]      # sky is dimmer low down
    assert not horizon.is_sky(wall, 1300)[0] and not horizon.is_sky(rooftop, 1300)[0]
