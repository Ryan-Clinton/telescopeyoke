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
