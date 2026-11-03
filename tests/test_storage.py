"""Room on the laptop's disk: finished Moon videos moved to the storage disk."""
import os
import sys

import pytest

import storage

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="links need privileges on Windows")


def video(lucky, name, stacked=True, age_s=3600):
    path = lucky / f"{name}.ser"
    path.write_bytes(b"x" * 1000)
    if stacked:
        (lucky / f"{name}.best5.fits").write_bytes(b"f")
    old = path.stat().st_mtime - age_s
    os.utime(path, (old, old))
    return path


def test_only_finished_videos_are_moved_and_each_leaves_a_link(tmp_path):
    data, store = tmp_path / "data", tmp_path / "store"
    lucky = data / "frames" / "lucky"
    lucky.mkdir(parents=True)
    done = video(lucky, "Moon-1")
    unstacked = video(lucky, "Moon-2", stacked=False)          # no picture yet: kept
    writing = video(lucky, "Moon-3", age_s=0)                   # still being written: kept
    said = []
    assert storage.tidy(store, data, say=said.append) == 1000
    assert done.is_symlink() and done.read_bytes() == b"x" * 1000      # still read through its old path
    assert (store / "frames" / "lucky" / "Moon-1.ser").is_file()
    assert not unstacked.is_symlink() and not writing.is_symlink()
    assert said == ["moved Moon-1.ser (0.0 GB)"]
    # Already moved: left alone the second time.
    assert storage.tidy(store, data, say=said.append) == 0


def test_a_dry_run_moves_nothing_and_no_storage_disk_moves_nothing(tmp_path):
    data = tmp_path / "data"
    lucky = data / "frames" / "lucky"
    lucky.mkdir(parents=True)
    done = video(lucky, "Moon-1")
    assert storage.tidy(tmp_path / "store", data, say=lambda s: None, dry_run=True) == 1000
    assert not done.is_symlink() and not (tmp_path / "store").exists()
    said = []
    assert storage.tidy("", data, say=said.append) == 0 and said[0].startswith("no storage disk set")
    assert storage.archive({"storage": {"archive": ""}}) is None
    assert storage.archive({"storage": {"archive": "/mnt/x"}}).name == "x"


def test_a_low_disk_is_said_and_a_roomy_one_is_not(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "free", lambda data=None: 14e9)
    assert storage.words(tmp_path).startswith("only 14 GB free")
    monkeypatch.setattr(storage, "free", lambda data=None: 400e9)
    assert storage.words(tmp_path) is None


def test_the_schedule_makes_room_before_a_step(monkeypatch, tmp_path):
    import types

    import schedule
    monkeypatch.setattr(schedule, "FILE", tmp_path / "schedule.json")
    monkeypatch.setattr(schedule, "RUNNER", tmp_path / "schedule.runner")
    monkeypatch.setattr(schedule, "end", lambda **k: True)
    import notify
    monkeypatch.setattr(notify, "send", lambda *a, **k: None)
    room = {"free": 5e9}
    monkeypatch.setattr(storage, "free", lambda data=None: room["free"])
    tidied = []
    monkeypatch.setattr(storage, "tidy", lambda **k: tidied.append(1) or room.update(free=300e9))
    schedule.add("Moon picture", 5, ["./ty", "moon"])
    order = []
    assert schedule.run(say=lambda s: None, sleep=lambda s: None,
                        start=lambda c: order.append(("step", list(tidied))) or types.SimpleNamespace(returncode=0))
    assert order == [("step", [1])]       # the room was made before the step began


def test_old_sessions_raw_frames_are_moved_and_tonights_kept(tmp_path):
    data, store = tmp_path / "data", tmp_path / "store"
    old, new = data / "frames" / "M31" / "20261018-2200", data / "frames" / "M33" / "20261102-1900"
    for session, age in ((old, 2 * 86400), (new, 60)):
        session.mkdir(parents=True)
        for name in ("light-0001.fits", "light-0002.fits", "final.fits"):
            f = session / name
            f.write_bytes(b"x" * 100)
            os.utime(f, (f.stat().st_mtime - age,) * 2)
    said = []
    assert storage.tidy(store, data, say=said.append) == 200
    assert (old / "light-0001.fits").is_symlink() and (old / "light-0001.fits").read_bytes() == b"x" * 100
    assert not (old / "final.fits").is_symlink()                  # the stacked picture stays here
    assert (store / "frames" / "M31" / "20261018-2200" / "light-0002.fits").is_file()
    assert not (new / "light-0001.fits").is_symlink()              # tonight's session is still being written
    assert said == ["moved M31/20261018-2200: 2 frames (0.0 GB)"]
    assert storage.tidy(store, data, say=said.append) == 0         # already moved: left alone
