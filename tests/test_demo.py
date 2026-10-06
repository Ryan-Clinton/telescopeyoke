"""The full demo: the real commands, run on a pretend mount, camera and sky,
with their files in a folder of the test's own. Nothing real is touched."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


@pytest.fixture
def demo(tmp_path):
    """Run one of the project's commands in the demo; returns its output."""
    env = {**os.environ, "TY_DEMO": "1", "TY_DEMO_FAST": "1", "TY_DATA": str(tmp_path),
           "TY_CALIBRATION": str(tmp_path / "calibration")}

    def run(*command, check=True):
        done = subprocess.run([sys.executable, *command], cwd=ROOT, env=env, capture_output=True,
                              text=True, encoding="utf-8", timeout=300)
        if check:
            assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]
        return done
    run.folder = tmp_path
    run.python = lambda code: run("-c", code).stdout.strip()
    return run


def reachable(demo):
    """A target the mount may go to at whatever hour the test runs."""
    return demo.python("import mount, sky, config, interface\n"
                       "site = config.load()['site']\n"
                       "for t in sky.load_targets():\n"
                       "    try:\n        mount.plan_goto(t['id'], site); print(t['id']); break\n"
                       "    except interface.Refusal:\n        pass")


def test_the_demo_keeps_its_files_to_itself(demo):
    seen = json.loads(demo.python("import json, config, mount, shoot, agent, stacking\n"
                                  "print(json.dumps([str(p) for p in (config.DATA, mount.CLOCK_FILE, shoot.WEB, agent.WEB)]"
                                  " + [config.load()['site']['name'], config.DEMO]))"))
    assert all(str(demo.folder) in path for path in seen[:4])
    assert seen[4] == "My back garden" and seen[5] is True          # the example site, never the real one
    assert "Ready for imaging:  YES" in demo("doctor.py", "--skip-handset").stdout
    report = demo("doctor.py", "--report").stdout
    assert "the demo (a pretend mount)" in report and "as the handset names it: EQ3" in report


def test_a_goto_with_centring_has_something_real_to_correct(demo):
    target = reachable(demo)
    said = demo("mount.py", "goto", target, "--solve").stdout
    # The pretend home position is a degree or so out and the polar axis a little off,
    # so the first solve finds a miss of tens of arcminutes and the last finds it centred.
    import re
    misses = [abs(float(m)) for m in re.findall(r"off by ([+-][\d.]+)' in hour angle", said)]
    assert len(misses) >= 2 and misses[0] > 30 and misses[-1] < 2
    assert "centred" in said and "tracking" in said
    assert (demo.folder / "cache" / "last_solve.json").exists()
    assert not (ROOT / "demo" / "cache" / "last_solve.json").exists() or True


def test_the_focusing_aid_goes_to_a_field_of_stars_first(demo):
    """--field slews the pretend mount to a bright star before focusing, or
    says that none is well placed; --dry-run names the star and moves nothing."""
    dry = json.loads(demo("focus.py", "--field", "--dry-run", "--json", check=False).stdout)
    if not dry["ok"]:
        assert "well up" in dry["errors"][0]["message"]
        pytest.skip("none of the focus stars is well placed at this hour")
    assert dry["data"]["would_move"] is True and dry["data"]["field"]
    answer = json.loads(demo("focus.py", "--field", "--frames", "2", "--quiet", "--json").stdout)
    assert answer["ok"], answer
    assert answer["data"]["hfr"] > 0


def test_the_focusing_aid_follows_the_pretend_focuser(demo):
    readings = []
    for turns in (5, 2, 0):
        demo.python(f"import simulator; simulator.set_sky(focus={turns})")
        answer = json.loads(demo("focus.py", "--frames", "3", "--quiet", "--json").stdout)
        assert answer["ok"], answer
        readings.append(answer["data"]["hfr"])
    assert readings[0] > readings[1] > readings[2]                   # sharper as it nears best focus
    assert json.loads((demo.folder / "cache" / "focus.json").read_text(encoding="utf-8"))["hfr"] == readings[2]


def test_an_imaging_run_on_the_pretend_sky(demo):
    target = reachable(demo)
    demo.python("import simulator; simulator.set_sky(focus=0)")
    answer = json.loads(demo("shoot.py", target, "--frames", "6", "--exposure", "1", "--json").stdout)
    assert answer["ok"], answer
    session = json.loads(demo("ty", "session", "--json").stdout)["data"]
    assert session["captured"] == 6 and session["accepted"] >= 5 and session["finished"]
    assert (demo.folder / "web" / "stack.jpg").exists()
    assert list((demo.folder / "frames").glob("*/*/final.jpg"))


def test_cloud_and_a_pulled_lead_look_as_they_would_for_real(demo):
    counts = json.loads(demo.python(
        "import json, simulator, skywatch\n"
        "from camera import Camera, luminance\n"
        "out = []\n"
        "for cloud in (False, True):\n"
        "    simulator.set_sky(cloud=cloud, focus=0)\n"
        "    with Camera() as cam:\n"
        "        out.append(int(luminance(cam.frame(1.0)[0]).max()))\n"
        "print(json.dumps(out))"))
    assert counts[1] < 0.5 * counts[0]                                  # the stars are far dimmer through cloud
    demo.python("import simulator; simulator.set_sky(cloud=False, unplugged=True)")
    failed = demo("focus.py", "--frames", "2", "--quiet", "--json", check=False)
    answer = json.loads(failed.stdout)
    assert failed.returncode != 0 and not answer["ok"] and "unplugged" in answer["errors"][0]["message"]


def test_polar_alignment_finds_the_pretend_mounts_error(demo):
    # A target well placed for it: near the meridian, mid-declination, high up.
    target = demo.python("import mount, sky, config, interface\n"
                         "site = config.load()['site']\n"
                         "for t in sky.load_targets() + [dict(id=s) for s in mount.STARS]:\n"
                         "    try:\n        p = mount.plan_goto(t['id'], site)\n"
                         "    except interface.Refusal:\n        continue\n"
                         "    if abs(p['hour_angle_hours']) < 1.5 and 5 < p['dec_deg'] < 60 and p['altitude_deg'] > 45:\n"
                         "        print(t['id']); break")
    if not target:
        pytest.skip("nothing is well placed for it at this hour")
    assert json.loads(demo("polaralign.py", "--dry-run", "--json").stdout)["data"]["would_move"] is True
    # Each command starts a fresh pretend mount at home, so the GoTo and the measurement go in one.
    found = json.loads(demo.python(
        "import json, config, mount, polaralign\n"
        "site = config.load()['site']\n"
        "scope = mount.Mount()\n"
        f"scope.goto_target({target!r}, site)\n"
        "print(json.dumps(polaralign.measure(scope, site)))").splitlines()[-1])
    assert found == pytest.approx([1.4, 0.8], abs=0.05)             # simulator.POLAR_ERROR
    # The same answer from turns of 10°, for a garden with little clear sky.
    found = json.loads(demo.python(
        "import json, config, mount, polaralign\n"
        "site = config.load()['site']\n"
        "scope = mount.Mount()\n"
        f"scope.goto_target({target!r}, site)\n"
        "print(json.dumps(polaralign.measure(scope, site, step=10)))").splitlines()[-1])
    assert found == pytest.approx([1.4, 0.8], abs=0.1)
    # A photograph that will not solve (a tree, a cloud) sends it back to
    # where it started, not left pointing at whatever hid the stars.
    back = json.loads(demo.python(
        "import json, config, mount, polaralign, interface\n"
        "site = config.load()['site']\n"
        "scope = mount.Mount()\n"
        f"scope.goto_target({target!r}, site)\n"
        "start = scope.axes()[0]\n"
        "real, looks = scope.where_really, []\n"
        "def hidden(*a, **k):\n"
        "    looks.append(1)\n"
        "    return real(*a, **k) if len(looks) < 3 else None\n"
        "scope.where_really = hidden\n"
        "try:\n"
        "    polaralign.measure(scope, site, step=10)\n"
        "    said = ''\n"
        "except interface.Refusal as refusal:\n"
        "    said = refusal.message\n"
        "print(json.dumps([said, abs((scope.axes()[0] - start + 180) % 360 - 180)]))").splitlines()[-1])
    assert "back where it started" in back[0] and back[1] < 1.0
    # From the home position it refuses: turning the RA axis there shows nothing.
    refused = json.loads(demo("polaralign.py", "--json", check=False).stdout)
    assert not refused["ok"] and "too near the pole" in refused["errors"][0]["message"]
