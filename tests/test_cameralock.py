"""One command at a time has the camera, and a second is told which; a kill
closes the camera the way Ctrl-C does."""
import os
import signal
import subprocess
import sys
import textwrap

import pytest

import altair
import cameralock
import interface


def hold(path, command):
    """Another command holding the lock, as a separate process."""
    process = subprocess.Popen([sys.executable, "-c", textwrap.dedent(f"""
        import pathlib, sys, time
        sys.path.insert(0, {os.getcwd()!r})
        import cameralock
        cameralock.CameraLock(pathlib.Path({str(path)!r}), command={command!r})
        print("held", flush=True)
        time.sleep(60)
    """)], stdout=subprocess.PIPE, text=True)
    assert process.stdout.readline().strip() == "held"
    return process


def test_a_second_command_is_told_who_has_the_camera_and_gets_it_once_that_one_ends(tmp_path):
    """2 November 2026: a dark run thought stopped still held the camera.
    The lock cannot outlive its process, however it ends: killed outright here."""
    path = tmp_path / "camera.lock"
    other = hold(path, "./calibrate.py dark --exposure 16")
    with pytest.raises(interface.Refusal) as refused:
        cameralock.CameraLock(path, command="./horizon.py --trace")
    assert refused.value.code_name == "CAMERA_BUSY"
    assert f"process {other.pid} (./calibrate.py dark --exposure 16)" in str(refused.value)
    other.kill()
    other.wait()
    mine = cameralock.CameraLock(path, command="./horizon.py --trace")
    assert cameralock.holder(path) == (os.getpid(), "./horizon.py --trace")
    mine.release()
    assert cameralock.holder(path) is None


def test_one_command_may_open_the_camera_again_without_refusing_itself(tmp_path):
    path = tmp_path / "camera.lock"
    first = cameralock.CameraLock(path, command="./focus.py")
    second = cameralock.CameraLock(path, command="./focus.py")
    first.release()
    other = subprocess.run([sys.executable, "-c", textwrap.dedent(f"""
        import pathlib, sys
        sys.path.insert(0, {os.getcwd()!r})
        import cameralock
        cameralock.CameraLock(pathlib.Path({str(path)!r}))
    """)], capture_output=True, text=True)
    assert "in use by process" in other.stderr          # still held by the second
    second.release()
    cameralock.CameraLock(path).release()


def test_a_camera_that_will_not_open_lets_the_lock_go(monkeypatch, tmp_path):
    monkeypatch.setattr(cameralock, "PATH", tmp_path / "camera.lock")
    monkeypatch.setattr(altair, "sdk", lambda: object())

    def fails(self, replugged=False):
        raise altair.CameraError("the camera would not be set up")
    monkeypatch.setattr(altair.AltairCamera, "_open", fails)
    with pytest.raises(altair.CameraError):
        altair.AltairCamera()
    cameralock.CameraLock().release()            # not left held


def test_a_kill_ends_the_command_as_ctrl_c_does(monkeypatch):
    monkeypatch.setattr(signal, "getsignal", lambda s: signal.SIG_DFL)
    set_to = {}
    monkeypatch.setattr(signal, "signal", lambda s, handler: set_to.update({s: handler}))
    altair.stop_on_terminate()
    with pytest.raises(KeyboardInterrupt):
        set_to[signal.SIGTERM](signal.SIGTERM, None)
    # A handler the command set itself is left alone.
    set_to.clear()
    monkeypatch.setattr(signal, "getsignal", lambda s: print)
    altair.stop_on_terminate()
    assert set_to == {}
