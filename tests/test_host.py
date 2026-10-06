"""What differs between Linux and Windows (host.py), and the rules that have
to hold on both: UTF-8 output, folder names, paths with spaces."""
import json
import subprocess
import sys
import threading
import time
import types
import urllib.request
from pathlib import Path

import pytest

import config
import doctor
import host
import solve
import stacking

ROOT = Path(__file__).parent.parent


# --- output is UTF-8 even when it is not going to a screen ---------------------------

def test_json_sent_to_a_file_is_utf8(tmp_path):
    out = tmp_path / "result.json"
    with out.open("wb") as f:
        subprocess.run([sys.executable, str(ROOT / "ty"), "capabilities", "--json"],
                       stdout=f, stderr=subprocess.DEVNULL, cwd=ROOT, timeout=120)
    answer = json.loads(out.read_text(encoding="utf-8"))
    assert answer["command"] == "capabilities"


def test_a_degree_sign_survives_a_pipe():
    done = subprocess.run([sys.executable, "-c", "import host; print('20°')"],
                          capture_output=True, cwd=ROOT, timeout=60)
    assert done.stdout.decode("utf-8").strip() == "20°"


# --- previews --------------------------------------------------------------------------

def test_a_preview_replaces_the_old_one(tmp_path):
    new, shown = tmp_path / "latest.part.jpg", tmp_path / "latest.jpg"
    new.write_bytes(b"new")
    shown.write_bytes(b"old")
    assert host.replace_preview(new, shown) is True
    assert shown.read_bytes() == b"new" and not new.exists()


def test_a_preview_being_read_keeps_the_old_one_and_does_not_stop_the_run(tmp_path, monkeypatch):
    new, shown = tmp_path / "latest.part.jpg", tmp_path / "latest.jpg"
    new.write_bytes(b"new")
    shown.write_bytes(b"old")
    monkeypatch.setattr(host, "WINDOWS", True)

    def held_open(source, target):
        raise PermissionError("the web server has it open")
    monkeypatch.setattr(host.os, "replace", held_open)
    assert host.replace_preview(new, shown, patience=0.2) is False
    assert shown.read_bytes() == b"old" and not new.exists()


@pytest.mark.skipif(not host.WINDOWS, reason="only Windows refuses to replace an open file")
def test_a_preview_is_replaced_once_the_reader_lets_go(tmp_path):
    new, shown = tmp_path / "latest.part.jpg", tmp_path / "latest.jpg"
    new.write_bytes(b"new")
    shown.write_bytes(b"old")
    reader = shown.open("rb")
    threading.Timer(0.3, reader.close).start()
    assert host.replace_preview(new, shown) is True
    assert shown.read_bytes() == b"new"


# --- names that become folders ------------------------------------------------------------

def test_ordinary_target_names_make_the_folders_they_always_did():
    for name, folder in (("M27", "M27"), ("NGC 7000", "NGC7000"), ("Vega", "Vega"), ("IC 1396", "IC1396")):
        assert stacking.folder_name(name) == folder


def test_names_windows_would_refuse_are_made_safe():
    assert stacking.folder_name("C/2023 A3") == "C-2023A3"
    assert stacking.folder_name('a<b>c:d"e\\f|g?h*') == "a-b-c-d-e-f-g-h-"
    assert stacking.folder_name("NUL") == "NUL_" and stacking.folder_name("com1") == "com1_"
    assert stacking.folder_name("end.") == "end"
    assert stacking.folder_name(" ") == "unnamed"


# --- the handset's serial port --------------------------------------------------------------

def windows_ports(monkeypatch, *ports):
    """Pretend to be Windows with these (device, description, maker) ports."""
    from serial.tools import list_ports
    monkeypatch.setattr(host, "WINDOWS", True)
    monkeypatch.setattr(list_ports, "comports", lambda: [
        types.SimpleNamespace(device=device, description=description, manufacturer=maker,
                              hwid=f"USB VID:PID={maker}") for device, description, maker in ports])


def test_the_com_port_is_found_by_the_adapters_name(monkeypatch):
    windows_ports(monkeypatch, ("COM3", "Intel(R) Active Management", "Intel"),
                  ("COM7", "Standard Serial over Bluetooth", "Microsoft"),
                  ("COM5", "USB Serial Port (COM5)", "FTDI"))
    assert host.serial_port("FTDI") == "COM5"
    assert host.serial_port("Prolific") is None


def test_no_matching_port_is_refused_and_never_guessed(monkeypatch):
    import mount
    windows_ports(monkeypatch, ("COM3", "Intel(R) Active Management", "Intel"))
    opened = []
    monkeypatch.setattr(mount.serial, "Serial", lambda *a, **k: opened.append(a))
    with pytest.raises(mount.Refusal) as refusal:
        mount.Mount(watch=False)
    assert refusal.value.code_name == "HANDSET_NOT_ANSWERING"
    assert "COM3" in refusal.value.message and not opened


def test_a_port_named_on_the_command_line_is_used_as_given(monkeypatch):
    import mount
    windows_ports(monkeypatch)
    opened = []

    def port(name, *rest, **more):
        opened.append(name)
        raise OSError("stop here: the test only wants to know which port")
    monkeypatch.setattr(mount.serial, "Serial", port)
    with pytest.raises(OSError):
        mount.Mount(port="COM9", watch=False)
    assert opened == ["COM9"]


# --- the plate solver ----------------------------------------------------------------------------

def test_solver_paths_with_spaces_reach_it_as_whole_arguments(tmp_path, monkeypatch):
    import numpy as np
    program = str(tmp_path / "Program Files" / "astap" / "astap_cli.exe")
    database = str(tmp_path / "Program Files" / "astap")
    monkeypatch.setattr(solve, "ASTAP", program)
    monkeypatch.setattr(solve, "DATABASE", database)
    seen = {}

    def fake_run(cmd, **options):
        seen["cmd"], seen["options"] = cmd, options
    monkeypatch.setattr(solve.subprocess, "run", fake_run)
    assert solve.solve(np.zeros((8, 8))) is None
    assert isinstance(seen["cmd"], list) and not seen["options"].get("shell")
    assert seen["cmd"][0] == program
    assert seen["cmd"][seen["cmd"].index("-d") + 1] == database


def test_the_solver_named_in_config_wins():
    named = config.solver({"solver": {"program": "D:/my tools/astap_cli.exe", "database": "D:/star data"}})
    assert named == {"program": "D:/my tools/astap_cli.exe", "database": "D:/star data"}


@pytest.mark.skipif(host.WINDOWS, reason="the Linux defaults")
def test_the_solver_defaults_on_linux_are_unchanged():
    assert config.solver({}) == {"program": "astap_cli", "database": "/opt/astap"}


@pytest.mark.skipif(not host.WINDOWS, reason="the Windows defaults")
def test_the_solver_database_defaults_to_the_programs_folder_on_windows(monkeypatch):
    monkeypatch.setattr(config.shutil, "which", lambda name: None)
    found = config.solver({})
    assert Path(found["program"]) == Path("C:/Program Files/astap/astap_cli.exe")
    assert Path(found["database"]) == Path("C:/Program Files/astap")


# --- the webcam -------------------------------------------------------------------------------------

LISTING = b'''[dshow @ 000001] "Integrated Camera" (video)
[dshow @ 000001]   Alternative name "@device_pnp_..."
[dshow @ 000001] "USB2.0 PC CAMERA" (video)
[dshow @ 000001] "Microphone (Realtek)" (audio)
dummy: Immediate exit requested
'''


def test_webcams_are_read_from_stderr_whatever_the_exit_code(monkeypatch):
    monkeypatch.setattr(host.subprocess, "run", lambda *a, **k: types.SimpleNamespace(
        returncode=1, stdout=b"", stderr=LISTING))
    assert host.webcam_names() == ["Integrated Camera", "USB2.0 PC CAMERA"]


def test_with_no_webcam_configured_on_windows_there_is_simply_no_picture(monkeypatch, tmp_path):
    import watch
    monkeypatch.setattr(host, "WINDOWS", True)
    monkeypatch.setattr(host, "_webcam_name", lambda: "")
    assert host.webcam_input() is None
    assert watch.capture(tmp_path / "scope.jpg") is False


def test_the_configured_webcam_is_given_to_ffmpeg_by_name(monkeypatch):
    monkeypatch.setattr(host, "WINDOWS", True)
    monkeypatch.setattr(host, "_webcam_name", lambda: "USB2.0 PC CAMERA")
    assert host.webcam_input()[-1] == "video=USB2.0 PC CAMERA"


# --- speech ---------------------------------------------------------------------------------------------

LISTENER = r'''
import sys, time
for line in sys.stdin:
    with open(sys.argv[1], "a", encoding="utf-8") as log:
        log.write("start " + line)
    time.sleep(0.3)
    with open(sys.argv[1], "a", encoding="utf-8") as log:
        log.write("end " + line)
    print(".", flush=True)
'''


def test_speech_is_one_phrase_at_a_time_in_order_and_stale_ones_are_dropped(tmp_path):
    log = tmp_path / "spoken.txt"
    speaker = host.Speaker([sys.executable, "-c", LISTENER, str(log)])
    began = time.monotonic()
    for words in ("Improving. 5.2", "Improving. 4.7", "Improving. 4.1", "Worse. Go back"):
        speaker.say(words)
        time.sleep(0.05)
    assert time.monotonic() - began < 1.5      # say() never waits for the words
    give_up = time.monotonic() + 20
    while time.monotonic() < give_up:
        if log.exists() and "end Worse. Go back" in log.read_text(encoding="utf-8"):
            break
        time.sleep(0.05)
    lines = log.read_text(encoding="utf-8").splitlines()
    # Each phrase finishes before the next begins: none is cut short or overlaps.
    assert all(lines[i].startswith("start ") and lines[i + 1] == "end " + lines[i][6:]
               for i in range(0, len(lines), 2))
    spoken = [line[6:] for line in lines[::2]]
    assert spoken[0] == "Improving. 5.2" and spoken[-1] == "Worse. Go back"
    assert len(spoken) < 4                     # something stale in the middle was dropped


def test_no_speech_program_leaves_focusing_silent_not_broken():
    speaker = host.Speaker(["no-such-program-for-speech"])
    speaker.say("Improving")
    speaker.thread.join(timeout=10)
    assert not speaker.thread.is_alive()


def test_speech_starts_again_if_the_speaking_program_died(tmp_path):
    log = tmp_path / "spoken.txt"
    once = "import sys; open(sys.argv[1], 'a').write(sys.stdin.readline())"   # says one phrase and exits
    speaker = host.Speaker([sys.executable, "-c", once, str(log)])
    for words in ("first", "second"):
        speaker.say(words)
        speaker.thread.join(timeout=20)      # its program has gone, so the worker ends
        assert not speaker.thread.is_alive()
    assert log.read_text(encoding="utf-8").split() == ["first", "second"]


# --- the doctor and the status page ----------------------------------------------------------------------

@pytest.mark.skipif(not host.WINDOWS, reason="what the doctor says on Windows")
def test_the_doctor_gives_no_linux_instructions_on_windows():
    results = doctor.run(offline=True, skip_handset=True)
    said = " ".join(message for checks in results.values() for _, message in checks)
    for linux_only in ("usermod", "/dev/", "dialout group:", "sudo", "/opt/", "indiserver"):
        assert linux_only not in said, said


def test_the_status_page_serves_and_answers(tmp_path, monkeypatch):
    """serve.py never exits, so it is run here for one page and one question."""
    import functools
    from http.server import ThreadingHTTPServer

    import serve
    (tmp_path / "index.html").write_text("<p>20° up</p>", encoding="utf-8")
    serve.Handler.demo = True
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(serve.Handler, directory=str(tmp_path)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        assert "20°" in urllib.request.urlopen(base + "/index.html", timeout=30).read().decode("utf-8")
        answer = json.loads(urllib.request.urlopen(base + "/api/v1/capabilities", timeout=120).read())
        assert answer["command"] == "capabilities" and answer["ok"]
    finally:
        server.shutdown()
        server.server_close()


def test_the_computers_own_figures_are_numbers_or_nothing():
    for value in (host.processor_load(), host.temperature()):
        assert value is None or value >= 0
    assert host.QUIET == ({"creationflags": subprocess.CREATE_NO_WINDOW} if host.WINDOWS else {})


def test_a_soft_frame_gets_a_second_try_averaged_in_blocks(monkeypatch):
    """Discs that ASTAP will not take for stars are points again once the
    frame is averaged in blocks; the answer is given back in the pixels of
    the frame as it was."""
    import numpy as np
    monkeypatch.setattr(config, "DEMO", False)
    seen = []

    def astap(image, *rest):
        seen.append(image.shape)
        if len(seen) == 1:
            return None
        return {"ra": 10.0, "dec": 20.0, "rotation": 0.0, "scale": 8.0, "seconds": 0.1,
                "cd": [[0.004, 0.0], [0.0, 0.004]]}

    monkeypatch.setattr(solve, "astap", astap)
    found = solve.solve(np.ones((1600, 2000)), 10.0, 20.0)
    assert seen == [(1600, 2000), (400, 500)]
    assert found["scale"] == 2.0 and found["cd"][0][0] == 0.001 and found["coarse"] == 4
    # With no hint the whole sky would be searched twice: it is not tried.
    seen.clear()
    monkeypatch.setattr(solve, "astap", lambda *a: seen.append(1))
    assert solve.solve(np.ones((1600, 2000))) is None and seen == [1]
