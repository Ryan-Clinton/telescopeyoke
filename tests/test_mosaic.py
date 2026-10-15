"""Mosaic panels: their centres, the grid suggested from an object's size, and
a panel name standing in for a target. Nothing here moves anything."""
import json
import math

import pytest

import config
import mosaic
import mount
import sky

CFG = config.example()
M31 = mount.find_target("M31")


@pytest.fixture(autouse=True)
def kept_here(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(mount, "LAST_SOLVE", tmp_path / "cache" / "last_solve.json")


def test_one_panel_is_the_object_itself():
    p = mosaic.plan(M31, 1, 1, angle=0, cfg=CFG)["panels"]
    assert len(p) == 1
    assert p[0]["ra"] == pytest.approx(M31["ra"], abs=1e-4)
    assert p[0]["dec"] == pytest.approx(M31["dec"], abs=1e-4)


def test_neighbours_are_a_frame_less_the_overlap_apart():
    plan = mosaic.plan(M31, 3, 2, overlap=0.2, angle=30, cfg=CFG)
    width, height = mosaic.field(CFG)
    p = {(q["column"], q["row"]): q for q in plan["panels"]}
    across = sky.separation(p[1, 1]["ra"], p[1, 1]["dec"], p[2, 1]["ra"], p[2, 1]["dec"])
    down = sky.separation(p[1, 1]["ra"], p[1, 1]["dec"], p[1, 2]["ra"], p[1, 2]["dec"])
    assert across == pytest.approx(width * 0.8, rel=1e-3)
    assert down == pytest.approx(height * 0.8, rel=1e-3)
    assert [q["id"] for q in plan["panels"]] == [f"M31-P{n}" for n in range(1, 7)]


def test_the_camera_angle_comes_from_the_last_plate_solve():
    a = math.radians(37)
    cd = [[math.cos(a) * 3.7e-4, -math.sin(a) * 3.7e-4], [math.sin(a) * 3.7e-4, math.cos(a) * 3.7e-4]]
    mount.LAST_SOLVE.parent.mkdir(parents=True)
    mount.LAST_SOLVE.write_text(json.dumps({"cd": cd}))
    plan = mosaic.plan(M31, 3, 1, cfg=CFG)
    assert plan["angle_deg"] == pytest.approx(37, abs=0.1)
    first, last = plan["panels"][0], plan["panels"][-1]
    assert last["dec"] > M31["dec"] > first["dec"]       # turned 37° towards north
    assert last["ra"] > M31["ra"] > first["ra"]


def test_a_grid_is_suggested_from_the_size():
    width, height = mosaic.field(CFG)
    assert mosaic.suggest({"size": 20, "minor": 10}, width, height) == (1, 1)
    columns, rows = mosaic.suggest(M31, width, height)
    covers = sorted([width + (columns - 1) * width * 0.85, height + (rows - 1) * height * 0.85])
    assert covers[0] >= M31["minor"] / 60 and covers[1] >= M31["size"] / 60


def test_a_kept_panel_is_a_target(monkeypatch):
    plan = mosaic.plan(M31, 3, 1, angle=0, cfg=CFG)
    mosaic.folder().mkdir()
    mosaic.path("M31").write_text(json.dumps(plan))
    for name in ("M31-P3", "m31-p3", "M31 P3", "M31p3"):
        found = mount.find_target(name)
        assert found["id"] == "M31-P3"
        assert (found["ra"], found["dec"]) == (plan["panels"][2]["ra"], plan["panels"][2]["dec"])
    assert mount.find_target("M31")["id"] == "M31"
    with pytest.raises(mount.Refusal):
        mount.find_target("M31-P4")
    with pytest.raises(mount.Refusal):
        mount.find_target("M33-P1")                       # no plan kept for M33


def test_a_kept_plan_is_not_replaced_by_accident(monkeypatch, capsys):
    def run(*argv):
        monkeypatch.setattr("sys.argv", ["mosaic.py", *argv])
        return mosaic.main()
    monkeypatch.setattr(config, "hardware", lambda: CFG)
    assert run("M31", "3x1", "--angle", "0") == 0
    assert run("M31", "2x2") == 1
    assert json.loads(mosaic.path("M31").read_text())["columns"] == 3
    assert run("M31", "2x2", "--replace") == 0
    assert json.loads(mosaic.path("M31").read_text())["columns"] == 2
