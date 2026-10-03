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
    page = (tmp_path / "index.html").read_text()
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
