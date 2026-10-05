"""The application: its window, how it closes, and its place in the menu."""
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

import app
import console
import host

ROOT = Path(__file__).parent.parent


def test_the_application_serves_its_own_window_and_stops_the_mount_on_closing(monkeypatch):
    seen, sent, real_run = {}, [], subprocess.run

    def window(url, title, busy, self_test=False):
        # What the window would do: load the page and ask how things are.
        assert url.startswith("http://127.0.0.1:") and "key=" in url
        key = url.split("key=")[1]
        seen["title"], seen["busy"] = title, busy()
        seen["page"] = urllib.request.urlopen(url, timeout=30).read().decode()
        request = urllib.request.Request(url.split("?")[0] + "api/state", headers={"X-Console-Key": key})
        seen["state"] = json.loads(urllib.request.urlopen(request, timeout=60).read())["data"]
        return True

    def run(cmd, **more):
        sent.append(cmd[-2:])
        return real_run(cmd, **more)
    monkeypatch.setattr(console.subprocess, "run", run)
    assert app.run(demo=True, ways=(lambda *a, **k: False, window))        # the first way is not there: next
    assert seen["title"] == "TelescopeYoke (demo)" and seen["busy"] is None
    assert "<title>TelescopeYoke</title>" in seen["page"]
    assert seen["state"]["mode"] == "app" and seen["state"]["demo"]
    assert sent == [["stop", "--json"]]                                    # closing always stops the mount


def test_with_no_way_to_make_a_window_it_says_so(monkeypatch):
    monkeypatch.setattr(console.Jobs, "close", lambda self: {"stopped": True})
    assert app.run(demo=True, ways=(lambda *a, **k: False,)) is False


def test_the_browser_is_asked_for_an_application_window_not_a_tab():
    cmd = app.app_mode_command("chrome", "http://127.0.0.1:1/?key=k", "/tmp/profile")
    assert cmd[0] == "chrome" and "--app=http://127.0.0.1:1/?key=k" in cmd
    assert "--user-data-dir=/tmp/profile" in cmd          # its own profile: a separate program that ends with the window


def test_the_launcher_goes_in_the_menu(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    written = host.install_launcher(ROOT)
    assert len(written) == 2 and all(path.exists() for path in written)
    if host.WINDOWS:
        assert [path.name for path in written] == ["TelescopeYoke.lnk", "TelescopeYoke (demo).lnk"]
        assert written[0].parent == tmp_path / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    else:
        entry, demo = (path.read_text(encoding="utf-8") for path in written)
        assert "Name=TelescopeYoke\n" in entry and "Terminal=false" in entry
        assert f'"{ROOT / "app.py"}"\n' in entry and f'"{ROOT / "app.py"}" --demo' in demo
        assert f"Icon={ROOT / 'console' / 'telescopeyoke.png'}" in entry
    assert (ROOT / "console" / "telescopeyoke.png").exists() and (ROOT / "console" / "telescopeyoke.ico").exists()


# --- settings changed from the application ------------------------------------------

def test_settings_are_changed_in_place_and_the_comments_kept():
    import config
    import tomllib
    old = config.EXAMPLE.read_text(encoding="utf-8")
    new = config.changed_text(old, {("site", "latitude"): 55.1, ("site", "sqm"): 20.4, ("mount", "link"): "wifi",
                                    ("solver", "program"): "C:/Program Files/astap/astap_cli.exe",
                                    ("webcam", "device"): 'USB "PC" CAMERA', ("indi", "manage_server"): True,
                                    ("guider", "port"): 4400})
    read = tomllib.loads(new)
    assert read["site"]["latitude"] == 55.1 and read["site"]["sqm"] == 20.4 and read["mount"]["link"] == "wifi"
    assert read["solver"] == {"program": "C:/Program Files/astap/astap_cli.exe"}       # the section was commented out
    assert read["webcam"]["device"] == 'USB "PC" CAMERA' and read["indi"]["manage_server"] is True
    assert read["guider"] == {"port": 4400}                                            # a section nobody had written
    assert read["site"]["longitude"] == -0.0015 and read["horizon"]["blocked"] == []   # the rest untouched
    kept = [line for line in old.splitlines() if line.startswith("#") and "=" not in line and "[" not in line]
    assert kept and all(line in new for line in kept)                                  # every comment still there
    # Blank again: back to a comment, so the default applies.
    back = tomllib.loads(config.changed_text(new, {("site", "sqm"): None, ("mount", "link"): None}))
    assert "sqm" not in back["site"] and "link" not in back["mount"]


def test_values_are_checked_before_anything_is_written():
    import config
    import pytest
    assert config.checked("site", "latitude", "55.07") == 55.07 and config.checked("camera", "width", "5440") == 5440
    assert config.checked("site", "sqm", "") is None and config.checked("indi", "manage_server", True) is True
    assert config.checked("site", "timezone", "Europe/Dublin") == "Europe/Dublin"
    for section, key, bad in (("site", "latitude", "95"), ("site", "latitude", "north"), ("site", "name", ""),
                              ("camera", "width", "54.5"), ("mount", "link", "bluetooth"), ("site", "timezone", "Mars/Olympus"),
                              ("indi", "manage_server", "yes"), ("site", "name", "a\nb = 1"), ("site", "password", "x")):
        with pytest.raises(ValueError):
            config.checked(section, key, bad)


def test_saving_from_the_application(tmp_path, monkeypatch):
    import threading
    import urllib.error

    import config
    monkeypatch.setattr(config, "FILE", tmp_path / "config.toml")
    server, key = console.serve(port=0, demo=False, mode="app")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def call(path, body=None):
        request = urllib.request.Request(base + path, headers={"X-Console-Key": key},
                                         data=None if body is None else json.dumps(body).encode())
        try:
            return json.loads(urllib.request.urlopen(request, timeout=60).read())
        except urllib.error.HTTPError as refused:
            return json.loads(refused.read())
    try:
        fields = call("/api/settings")["data"]["fields"]
        assert {"site.latitude", "mount.link", "camera.backend"} <= {f"{f['section']}.{f['key']}" for f in fields}
        # One wrong value: nothing at all is written.
        answer = call("/api/settings", {"values": {"site.name": "Garden", "site.latitude": "200"}})
        assert not answer["ok"] and "Latitude must be between" in answer["errors"][0]["message"]
        assert not config.FILE.exists()
        answer = call("/api/settings", {"values": {"site.name": "Garden", "site.latitude": "54.5", "mount.link": "wifi",
                                                   "site.sqm": ""}})
        assert answer["ok"] and config.FILE.exists()
        assert config.load()["site"]["name"] == "Garden" and config.load()["site"]["latitude"] == 54.5
        assert config.hardware()["mount"]["link"] == "wifi"
        shown = {f"{f['section']}.{f['key']}": f["value"] for f in call("/api/settings")["data"]["fields"]}
        assert shown["site.name"] == "Garden" and shown["mount.link"] == "wifi"
        # Saving the same again changes nothing; a second change keeps the last version beside it.
        assert call("/api/settings", {"values": {"site.name": "Garden"}})["data"]["saved"] == 0
        call("/api/settings", {"values": {"site.name": "Hilltop"}})
        assert 'name = "Garden"' in (tmp_path / "config.toml.bak").read_text(encoding="utf-8")
        assert call("/api/settings", {"values": {"site.password": "x"}})["ok"] is False
    finally:
        server.shutdown()
        server.server_close()


def test_the_companion_page_and_the_demo_cannot_change_settings(tmp_path, monkeypatch):
    import threading
    import urllib.error

    import config
    monkeypatch.setattr(config, "FILE", tmp_path / "config.toml")
    for demo, mode, status in ((False, "companion", 403), (True, "app", 409)):
        server, key = console.serve(port=0, demo=demo, mode=mode)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        request = urllib.request.Request(f"http://127.0.0.1:{server.server_address[1]}/api/settings",
                                         headers={"X-Console-Key": key}, data=b'{"values": {"site.name": "X"}}')
        try:
            urllib.request.urlopen(request, timeout=60)
            raise AssertionError("it was allowed")
        except urllib.error.HTTPError as refused:
            assert refused.code == status
        finally:
            server.shutdown()
            server.server_close()
    assert not config.FILE.exists()
