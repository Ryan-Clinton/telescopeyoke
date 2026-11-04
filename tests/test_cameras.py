"""Camera profiles and light paths (docs/mono-upgrade.md, item 0): a second
camera beside the 183C, never instead of it. With the old single [camera]
table everything is as it was; with [cameras.NAME] and [trains.NAME] the
camera plugged in decides, and each keeps its own files."""
import json

import numpy as np
import pytest
from astropy.io import fits

import altair
import camera
import cameras
import config
import policy
import stacking
from interface import Refusal
from test_camera import World, fake_sdk

TWO = {"cameras": {"183m": {"mono": True, "cooled": True, "readout_speed": 0}},
       "trains": {"183m-cc": {"camera": "183m", "corrector": 0.9, "filterwheel": True, "setup": "183m-cc"}}}
LEGACY = {"scope": {"focal_length_mm": 750},
          "camera": {"backend": "altair", "readout_speed": 0, "power_cycle_on_jam": True, "setup": "default"}}


@pytest.fixture(autouse=True)
def data(tmp_path, monkeypatch):
    """Nothing remembered and no camera asked for, in a data folder of its own."""
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.delenv("TY_CAMERA", raising=False)
    return tmp_path


def merged(given):
    return config._merged(json.loads(json.dumps(given)))


# --- the old config.toml, unchanged -------------------------------------------------

def test_the_old_single_camera_table_loads_as_the_183c_exactly_as_before(data):
    cfg = merged(LEGACY)
    before = dict(config.DEFAULTS["camera"], **LEGACY["camera"])
    assert {k: v for k, v in cfg["camera"].items() if k not in ("name", "chosen_by")} == before
    assert cfg["camera"]["name"] == "183c" and list(cfg["cameras"]) == ["183c"]
    assert cfg["train"] == {"name": "183c", "camera": "183c", "corrector": None, "filterwheel": False,
                            "setup": "default"}
    assert config.focal_length(cfg) == 750 and round(config.field_height(cfg), 2) == 0.67
    assert config.camera_folder(cfg=cfg) == data         # its files stay where they always were
    assert stacking.setup_name() == "default"


def test_the_example_settings_are_the_183c_alone():
    cfg = config.example()
    assert list(cfg["cameras"]) == ["183c"] and config.focal_length(cfg) == 750
    assert cfg["camera"]["chosen_by"] == "default"


def test_a_remembered_camera_means_nothing_with_one_profile(data):
    (data / "cache").mkdir()
    (data / "cache" / "camera-in-use.json").write_text('{"camera": "183m"}')
    assert merged(LEGACY)["camera"]["name"] == "183c"


# --- two cameras ------------------------------------------------------------------------

def test_the_183m_on_its_corrector_has_its_own_focal_length_setup_and_folder(data, monkeypatch):
    monkeypatch.setenv("TY_CAMERA", "183m")
    cfg = merged(dict(LEGACY, **TWO))
    assert cfg["camera"]["name"] == "183m" and cfg["camera"]["chosen_by"] == "--camera"
    assert cfg["camera"]["mono"] is True and cfg["camera"]["backend"] == "altair"   # backend from [camera]
    assert "power_cycle_on_jam" not in cfg["camera"]          # the 183C's own options stay its own
    assert config.focal_length(cfg) == pytest.approx(675)
    assert round(config.field_height(cfg), 2) == 0.74 and round(config.scale(cfg, 2), 2) == 1.47
    assert cfg["camera"]["setup"] == "183m-cc" and cfg["train"]["filterwheel"] is True
    assert config.camera_folder(cfg=cfg) == data / "183m"
    # ...and the 183c beside it is untouched.
    other = config.using_camera("183c", cfg)
    assert config.focal_length(other) == 750 and other["camera"]["power_cycle_on_jam"] is True


def test_with_two_profiles_the_camera_last_plugged_in_is_the_one_used(data):
    assert merged(dict(LEGACY, **TWO))["camera"]["name"] == "183c"
    (data / "cache").mkdir()
    (data / "cache" / "camera-in-use.json").write_text('{"camera": "183m"}')
    cfg = merged(dict(LEGACY, **TWO))
    assert cfg["camera"]["name"] == "183m" and cfg["camera"]["chosen_by"] == "remembered"
    asked = merged(dict(LEGACY, **TWO, imaging={"camera": "183c"}))
    assert asked["camera"]["name"] == "183c" and asked["camera"]["chosen_by"] == "setting"


def test_an_unknown_camera_name_or_an_unclear_train_is_refused(monkeypatch):
    monkeypatch.setenv("TY_CAMERA", "asi294")
    with pytest.raises(SystemExit, match="no camera profile called 'asi294'"):
        merged(dict(LEGACY, **TWO))
    monkeypatch.setenv("TY_CAMERA", "183m")
    trains = {"a": {"camera": "183m"}, "b": {"camera": "183m", "corrector": 0.9}}
    with pytest.raises(SystemExit, match="in 2 trains"):
        merged(dict(LEGACY, cameras=TWO["cameras"], trains=trains))
    chosen = merged(dict(LEGACY, cameras={"183m": {"train": "b"}}, trains=trains))
    assert config.focal_length(chosen) == pytest.approx(675)


def test_a_camera_is_matched_by_the_name_the_library_gives_or_its_serial(data):
    cfg = merged(dict(LEGACY, **TWO))
    assert config.match_camera("ALTAIRH183C(USB2.0)", cfg=cfg) == "183c"
    assert config.match_camera("Altair ALTAIRH183M PRO TEC", cfg=cfg) == "183m"
    assert config.match_camera("GPCAM MT9M034M", cfg=cfg) is None
    by_serial = merged(dict(LEGACY, cameras={"guide": {"serial": "SN-G"}}))
    assert config.match_camera("anything", "SN-G", cfg=by_serial) == "guide"


# --- the camera that opens decides --------------------------------------------------------

def open_with(world, monkeypatch, settings):
    lib = fake_sdk(world)
    monkeypatch.setattr(altair, "sdk", lambda: lib)
    monkeypatch.setattr(altair, "wait_for", lambda seconds: 0.3)
    monkeypatch.setattr(altair, "SETTINGS", settings)
    return altair.AltairCamera()


def test_the_183c_with_the_old_settings_opens_and_its_frames_say_which_it_is(monkeypatch):
    world = World()
    with open_with(world, monkeypatch, merged(LEGACY)) as cam:
        data, header = cam.frame(0.01)
    assert header["INSTRUME"] == "183c" and header["TELESCOP"] == "183c" and header["FOCALLEN"] == 750
    assert header["TY_MODEL"] == "Altair ALTAIRH183C" and header["BAYERPAT"] == "RGGB"
    assert not (config.DATA / "cache" / "camera-in-use.json").exists()     # nothing new kept for one camera


def test_a_camera_with_no_profile_is_refused_with_what_was_found(monkeypatch):
    world = World()
    world.cameras = [("Altair ALTAIRH183M PRO TEC", "SN-M")]
    with pytest.raises(Refusal, match="ALTAIRH183M PRO TEC .*serial SN-M.* not a camera with a profile"):
        open_with(world, monkeypatch, merged(LEGACY))


def test_a_swapped_camera_is_remembered_and_the_command_is_asked_again(monkeypatch):
    world = World()
    world.cameras, world.mono, world.tec = [("Altair ALTAIRH183M PRO TEC", "SN-M")], True, True
    with pytest.raises(Refusal, match="The 183m is plugged in, not the 183c .* run the command again"):
        open_with(world, monkeypatch, merged(dict(LEGACY, **TWO)))
    assert config.remembered_camera() == "183m"
    with open_with(world, monkeypatch, merged(dict(LEGACY, **TWO))) as cam:
        _, header = cam.frame(0.01)
    assert header["INSTRUME"] == "183m" and header["TELESCOP"] == "183m-cc" and header["FOCALLEN"] == 675.0
    assert "BAYERPAT" not in header


def test_the_camera_asked_for_is_found_among_two_or_refused(monkeypatch):
    world = World()
    world.cameras = [("Altair ALTAIRH183C", "SN-C"), ("Altair ALTAIRH183M PRO TEC", "SN-M")]
    with pytest.raises(Refusal, match="--camera NAME"):
        open_with(world, monkeypatch, merged(dict(LEGACY, **TWO)))
    monkeypatch.setenv("TY_CAMERA", "183m")
    with open_with(world, monkeypatch, merged(dict(LEGACY, **TWO))) as cam:
        assert cam.name == "Altair ALTAIRH183M PRO TEC" and cam.profile_name == "183m"
    world.cameras = [("Altair ALTAIRH183C", "SN-C")]
    with pytest.raises(Refusal, match="The 183m was asked for \\(by --camera\\), but .* the 183c"):
        open_with(world, monkeypatch, merged(dict(LEGACY, **TWO)))


# --- frames and stacks ----------------------------------------------------------------------

def kept(folder, cards):
    header = fits.Header(dict({"EXPTIME": 1.0, "GAIN": 300, "BAYERPAT": "RGGB"}, **cards))
    return stacking.save_light(folder, 1, np.zeros((8, 8), np.uint16), header)


def test_kept_frames_say_their_camera_and_a_stack_never_mixes_two(tmp_path):
    old = kept(tmp_path / "old", {})                                   # before the cards were written
    c = kept(tmp_path / "c", {"INSTRUME": "183c", "TELESCOP": "183c", "FOCALLEN": 750.0})
    m = kept(tmp_path / "m", {"INSTRUME": "183m", "TELESCOP": "183m-cc", "FOCALLEN": 675.0})
    cc = kept(tmp_path / "cc", {"INSTRUME": "183c", "TELESCOP": "183c-cc", "FOCALLEN": 675.0})
    assert fits.getheader(m, 1)["TELESCOP"] == "183m-cc"
    stacking.same_camera([old, c])                                    # the 183C's, old and new
    for mixed in ([c, m], [old, m], [c, cc]):
        with pytest.raises(Refusal, match="more than one camera or light path"):
            stacking.same_camera(mixed)


def test_the_indi_route_s_frames_say_their_camera_too():
    header = camera.identify(fits.Header({"INSTRUME": "Altair 183C (INDI)"}), config.example(), model="x")
    assert header["INSTRUME"] == "183c" and header["FOCALLEN"] == 750


# --- each camera's own files, and the one move -------------------------------------------------

def test_the_183c_s_files_move_under_183c_once_and_only_when_told(data):
    (data / "calibration").mkdir()
    (data / "calibration" / "dark-2s-g300.fits").write_text("dark")
    (data / "reference" / "M31").mkdir(parents=True)
    record = {"file": str(data / "reference" / "M31" / "v1.fits"), "stack": str(data / "frames" / "M31" / "x.fits")}
    (data / "reference" / "M31" / "v1.json").write_text(json.dumps(record))
    (data / "cache").mkdir()
    (data / "cache" / "focus.json").write_text("{}")
    (data / "cache" / "schedule.json").write_text("{}")             # not the camera's: stays

    said = []
    assert cameras.move_183c(data, go=False, say=said.append) == ["calibration", "reference", "cache/focus.json"]
    assert (data / "calibration").exists() and config.camera_folder("183c") == data      # nothing moved

    cameras.move_183c(data, go=True, say=said.append)
    moved = data / "183c"
    assert (moved / "calibration" / "dark-2s-g300.fits").read_text() == "dark"
    assert (moved / "cache" / "focus.json").exists() and (data / "cache" / "schedule.json").exists()
    assert not (data / "calibration").exists() and not (data / cameras.STAGING).exists()
    again = json.loads((moved / "reference" / "M31" / "v1.json").read_text())
    assert again["file"] == str(moved / "reference" / "M31" / "v1.fits") and again["stack"] == record["stack"]
    assert config.camera_folder("183c") == moved
    with pytest.raises(SystemExit, match="Already done"):
        cameras.move_183c(data, go=True, say=said.append)


# --- every user of the focal length reads the train (item 4) ------------------------------------

@pytest.mark.parametrize("camera_in_use, focal", [(None, 750.0), ("183m", 675.0)])
def test_every_scale_and_field_comes_from_the_camera_in_use_and_its_train(camera_in_use, focal, monkeypatch):
    import math

    import agent
    import console
    import focus
    import landmark
    import mount
    import moved
    import polaris
    if camera_in_use:
        monkeypatch.setenv("TY_CAMERA", camera_in_use)
    cfg = merged(dict(LEGACY, **TWO))
    monkeypatch.setattr(config, "hardware", lambda: cfg)
    monkeypatch.setattr(config, "load", lambda: cfg)
    monkeypatch.setattr(config, "FILE", config.EXAMPLE)              # agent._scale reads load()
    monkeypatch.setattr(mount, "LAST_SOLVE", config.DATA / "no-solve.json")
    half = 206.265 * 2 * 2.4 / focal                               # arcseconds a 2x2 pixel
    assert config.focal_length() == pytest.approx(focal)
    assert focus.arcsec_per_pixel() == pytest.approx(half)
    assert agent._scale() == pytest.approx(half)
    for module in (landmark, polaris, moved):
        assert module.scale() == pytest.approx(math.degrees(2 * 2.4e-3 / focal)), module.__name__
    framing = console.Reader.framing(None, "M31")
    assert framing["scale_arcsec_px"] == round(half / 2, 2)
    assert framing["field_deg"][1] == pytest.approx(math.degrees(3648 * 2.4e-3 / focal), abs=0.001)
    assert config.field_height() == pytest.approx(math.degrees(3648 * 2.4e-3 / focal))


# --- settings and safety ---------------------------------------------------------------------

def test_a_profile_s_own_setting_is_written_into_its_table(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(config.EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    config.save({("imaging", "camera"): "183m", ("cameras.183m", "readout_speed"): 0}, path)
    written = config._read(path)
    assert written["imaging"]["camera"] == "183m" and written["cameras"]["183m"]["readout_speed"] == 0
    assert config.checked("imaging", "camera", "") is None


def test_naming_a_rig_or_camera_never_hides_what_a_ty_command_does():
    assert policy.classify_text("./ty --camera 183m mount goto M27") == "hardware"
    assert policy.classify_text("./ty --rig heq5 --camera 183m shoot M31") == "hardware"
    assert policy.classify_text("./ty --camera 183m status") == "read_only"
    assert policy.classify_text("./cameras.py move-183c") == "read_only"
    assert policy.classify_text("./cameras.py move-183c --go") == "local_write"
