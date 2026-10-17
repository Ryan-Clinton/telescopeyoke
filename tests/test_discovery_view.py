"""agent.discovery(): tonight's discovery work for the status page, from files only."""
import json
import time

import agent
import mosaic


def session(base, field, name, frames=3, patrol=None, pictures=0, finished=False):
    folder = base / "frames" / field / name
    folder.mkdir(parents=True)
    (folder / "session.json").write_text(json.dumps({"name": field, "frames": frames, "exposure": 16}))
    with (folder / "frames.jsonl").open("w") as f:
        for i in range(frames):
            f.write(json.dumps({"index": i, "accepted": True, "reason": "kept", "taken": time.time(), "fwhm": 5.0,
                                "roundness": 0.9, "stars": 200}) + "\n")
    if finished:
        (folder / "frames.json").write_text("[]")
    if patrol is not None:
        (folder / "patrol.json").write_text(json.dumps(patrol))
    for n in range(pictures):
        (folder / f"patrol-{n + 1}.png").write_bytes(b"png")
    return folder


def test_tonight_with_a_mosaic_tabby_the_hunt_and_open_candidates(tmp_path, monkeypatch):
    now = time.mktime(time.strptime("20261017-235000", "%Y%m%d-%H%M%S"))
    monkeypatch.setattr(mosaic, "load", lambda name: {"columns": 4, "rows": 2} if name == "M31" else None)
    session(tmp_path, "M31-P6", "20261017-233312", patrol={"summary": ["Depth G 17.1"], "vet": {"unexplained": 1}},
            pictures=2, finished=True)
    session(tmp_path, "M31-P7", "20261017-234500")
    session(tmp_path, "M31", "20261016-220000")                       # last night: not tonight
    tabby = tmp_path / "frames" / "Tabby"
    tabby.mkdir(parents=True)
    (tabby / "starwatch.json").write_text(json.dumps({"nights": [{"session": "s", "mag": 11.65543, "scatter": 0.019}]}))
    (tmp_path / "sungrazer").mkdir()
    (tmp_path / "sungrazer" / "hunt-ccor1.json").write_text(json.dumps({"camera": "ccor1", "when": "w",
                                                                        "towards_sun": [{}]}))
    (tmp_path / "candidates").mkdir()
    (tmp_path / "candidates" / "M31.json").write_text(json.dumps({"candidates": [{"open": True}, {"open": False}]}))
    d = agent.discovery(now=now, data=tmp_path)
    assert [s["field"] for s in d["sessions"]] == ["M31-P6", "M31-P7"]
    p6, p7 = d["sessions"]
    assert p6["summary"] == ["Depth G 17.1"] and p6["unexplained"] == 1 and p6["pictures"] == ["patrol-1.png",
                                                                                                "patrol-2.png"]
    assert p7["summary"] is None and not p7["finished"]
    states = {p["panel"]: p["state"] for p in d["mosaics"][0]["panels"]}
    assert states[6] == "done" and states[7] == "now" and states[1] == "waiting" and len(states) == 8
    assert d["tabby"] == {"nights": 1, "last": "s", "mag": 11.655, "error": 0.019}
    assert d["comets"]["towards_sun"] == 1 and d["open_candidates"] == 1


def test_a_quiet_night_has_nothing_to_show(tmp_path):
    d = agent.discovery(data=tmp_path)
    assert d == {"sessions": [], "mosaics": [], "tabby": None, "comets": None, "open_candidates": 0}
