"""camera_setup.py: the checks in order, taking Altair's files out of their
SDK zip, and the test frame, against the made-up camera from test_camera.py."""
import zipfile

import pytest

import altair
import camera
import camera_setup
import host
import snap
from test_camera import World, fake_sdk

LIBRARY = camera_setup.library()[0]
HOME = {"altaircam.dll": "win/x64", "libaltaircam.so": "linux/x64", "libaltaircam.dylib": "mac"}[LIBRARY]


def sdk_zip(path, wrapper=True, library=True):
    """A zip laid out like Altair's: a library for every system, one wrapper."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("altaircamsdk/doc/readme.txt", "docs")
        for folder in ("win/x86", "win/arm64", "linux/armhf", "linux/arm64", "win/x64", "linux/x64", "mac"):
            if library or folder != HOME:
                name = {"win": "altaircam.dll", "linux": "libaltaircam.so", "mac": "libaltaircam.dylib"}[folder.split("/")[0]]
                z.writestr(f"altaircamsdk/{folder}/{name}", f"library for {folder}")
        if wrapper:
            z.writestr("altaircamsdk/python/altaircam.py", "# the wrapper")
    return path


class Args:
    check, sdk, open, exposure, gain = False, None, False, 0.01, 300


@pytest.fixture
def setup(tmp_path, monkeypatch):
    """A machine with the camera plugged in, a driver, and nothing installed."""
    world = World()
    (tmp_path / "home" / "Downloads").mkdir(parents=True)
    monkeypatch.setattr(camera_setup.Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(camera_setup, "ROOT", tmp_path / "project")
    monkeypatch.setattr(altair, "VENDOR", tmp_path / "project" / "vendor" / "altair")
    monkeypatch.setattr(altair, "SETTINGS", {"camera": {"bit_depth": 12}})
    monkeypatch.setattr(altair, "sdk", lambda: fake_sdk(world))
    monkeypatch.setattr(altair, "wait_for", lambda seconds: 2.0)
    monkeypatch.setattr(camera, "BACKEND", "altair")
    monkeypatch.setattr(camera_setup.config, "hardware", lambda: {"camera": {"backend": "altair"}})
    monkeypatch.setattr(host, "camera_device", lambda match: {
        "name": "ALTAIRH183C", "ready": True, "driver": "WINUSB", "detail": "driver WINUSB"})
    monkeypatch.setattr(snap, "publish", lambda *a, **k: None)
    return tmp_path, world


def statuses(result):
    return {step["step"]: step["status"] for step in result["steps"]}


def test_the_right_files_are_taken_from_the_sdk_zip(setup):
    tmp_path, _ = setup
    sdk = sdk_zip(tmp_path / "altaircamsdk_20260531.zip")
    chosen = camera_setup.members(sdk)
    assert chosen["altaircam.py"] == "altaircamsdk/python/altaircam.py"
    assert chosen[LIBRARY] == f"altaircamsdk/{HOME}/{LIBRARY}"      # not the 32-bit or ARM one
    camera_setup.install_sdk(sdk)
    assert (altair.VENDOR / "altaircam.py").read_text() == "# the wrapper"
    if host.WINDOWS:
        assert (altair.VENDOR / LIBRARY).read_text() == f"library for {HOME}"


def test_a_zip_that_is_not_the_sdk_is_refused_and_nothing_is_copied(setup):
    tmp_path, _ = setup
    sdk = sdk_zip(tmp_path / "altaircamsdk_wrong.zip", wrapper=False)
    with pytest.raises(ValueError, match="altaircam.py"):
        camera_setup.install_sdk(sdk)
    assert not altair.VENDOR.exists()


def test_the_newest_sdk_in_downloads_is_the_one_found(setup):
    import os
    tmp_path, _ = setup
    downloads = tmp_path / "home" / "Downloads"
    old = sdk_zip(downloads / "altaircamsdk_2025.zip")
    new = sdk_zip(downloads / "altaircamsdk_2026.zip")
    os.utime(old, (1, 1))
    assert camera_setup.find_sdk() == new
    assert camera_setup.find_sdk(str(old)) == old
    assert camera_setup.find_sdk(str(tmp_path / "nothing.zip")) is None


def test_with_no_camera_plugged_in_it_stops_there(setup, monkeypatch):
    monkeypatch.setattr(host, "camera_device", lambda match: None)
    result = camera_setup.run(Args())
    assert not result["ready"] and statuses(result) == {"python": "ok", "usb": "fail"}
    assert "plugged in" in result["next"]


def test_a_camera_with_no_driver_says_how_to_get_one(setup, monkeypatch):
    monkeypatch.setattr(host, "camera_device", lambda match: {
        "name": "ALTAIRH183C", "ready": False, "driver": "",
        "detail": "Windows has no working driver for it (status Error, problem code 28)"})
    result = camera_setup.run(Args())
    assert statuses(result)["usb"] == "todo" and "AltairCapture" in result["next"]


def test_with_no_sdk_anywhere_it_says_where_to_get_it_and_opens_nothing_unasked(setup, monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    result = camera_setup.run(Args())
    assert not result["ready"] and statuses(result)["files"] == "todo"
    assert "Downloads" in result["next"] and camera_setup.SDK_PAGE in result["next"]
    assert not opened

    class Asked(Args):
        open = True
    camera_setup.run(Asked())
    assert opened == [camera_setup.SDK_PAGE]


def test_checking_only_copies_nothing_and_takes_no_frame(setup):
    tmp_path, world = setup
    sdk_zip(tmp_path / "home" / "Downloads" / "altaircamsdk_2026.zip")

    class Check(Args):
        check = True
    result = camera_setup.run(Check())
    assert statuses(result)["files"] == "todo" and "altaircamsdk_2026.zip" in result["next"]
    assert not altair.VENDOR.exists() and world.triggers == 0


def test_from_a_zip_in_downloads_to_a_test_frame_in_one_go(setup):
    tmp_path, world = setup
    sdk_zip(tmp_path / "home" / "Downloads" / "altaircamsdk_2026.zip")
    world.level = 900
    result = camera_setup.run(Args())
    assert result["ready"], result
    assert statuses(result) == {"python": "ok", "usb": "ok", "files": "fixed", "library": "ok",
                                "camera": "ok", "frame": "ok"}
    frame = next(step["frame"] for step in result["steps"] if step["step"] == "frame")
    assert frame["size"] == [64, 48] and frame["max"] == 901 and frame["bayer"] == "RGGB"

    again = camera_setup.run(Args())             # a second press finds nothing to put right
    assert again["ready"] and statuses(again)["files"] == "ok"


def test_a_camera_that_gives_no_frame_is_not_called_ready(setup):
    tmp_path, world = setup
    sdk_zip(tmp_path / "home" / "Downloads" / "altaircamsdk_2026.zip")
    world.silent = True
    altair.wait_for = lambda seconds: 0.2
    result = camera_setup.run(Args())
    assert not result["ready"] and statuses(result)["frame"] == "fail"
