"""The night report end to end in demo mode, the INDI client's message
handling, and small lookups."""
from xml.etree.ElementTree import XMLPullParser

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
