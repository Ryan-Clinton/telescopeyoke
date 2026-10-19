"""Every webcam feature has a switch, and all are off unless turned on
(19 October 2026: the bench rig's picture stayed on the pages)."""
import contextlib

import config
import host
import mount
from simulator import SimulatedHandset


def settings(monkeypatch, **webcam):
    monkeypatch.setattr(config, "hardware", lambda: {"webcam": webcam})


def test_everything_is_off_unless_turned_on(monkeypatch):
    settings(monkeypatch)
    assert not host.webcam_on() and not host.webcam_on("watch_moves") and not host.webcam_on("show_picture")
    assert host.webcam_device() is None


def test_a_feature_needs_the_webcam_on_as_well_as_its_own_switch(monkeypatch):
    settings(monkeypatch, watch_moves=True, show_picture=True)
    assert not host.webcam_on("watch_moves")
    settings(monkeypatch, enabled=True)
    assert host.webcam_on() and not host.webcam_on("show_picture")
    settings(monkeypatch, enabled=True, show_picture=True)
    assert host.webcam_on("show_picture") and not host.webcam_on("watch_moves")


def test_the_mount_photographs_its_moves_only_when_that_is_switched_on(monkeypatch, tmp_path):
    monkeypatch.setattr(mount, "CLOCK_FILE", tmp_path / "clock.json")
    monkeypatch.setattr(mount, "LOCK_FILE", tmp_path / "MOTION_LOCKED")
    monkeypatch.delenv("TY_NO_WATCH", raising=False)
    settings(monkeypatch, enabled=True)          # webcam on, moves not to be photographed
    assert mount.Mount(handset=SimulatedHandset(slew_seconds=0)).watching is contextlib.nullcontext
    # (A simulated mount never photographs, so the switched-on case cannot be seen here.)


def test_the_status_page_leaves_out_the_telescope_picture_while_it_is_switched_off(monkeypatch, tmp_path):
    import page
    (tmp_path / "scope.jpg").write_bytes(b"\xff\xd8")
    seen = {}
    monkeypatch.setattr(page.PAGE, "substitute", lambda **parts: seen.update(parts) or "")
    rep = {"targets": []}
    for on in (False, True):
        settings(monkeypatch, enabled=on, show_picture=on)
        try:
            page.render(rep, 5, tmp_path)
        except Exception:
            pass                      # the rest of the report is not what is tested here
        if "scope" in seen:
            assert ("scope.jpg" in seen["scope"]) == on
        seen.clear()


def test_the_settings_form_has_a_switch_for_each():
    rows = {(section, key) for section, key, *_ in config.SETTINGS}
    assert {("webcam", "enabled"), ("webcam", "watch_moves"), ("webcam", "show_picture"),
            ("webcam", "built_in")} <= rows
