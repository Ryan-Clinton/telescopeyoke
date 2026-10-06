"""What differs between Linux and Windows, in one place.

Each function has a Linux branch, which is the code the project was built and
tested with, and a Windows branch beside it. Callers do not ask which system
they are on. A rule that holds on both systems does not belong here.

Importing this also makes printed output UTF-8 on Windows when it is piped or
redirected, so "°" survives a pipe and --json output is always UTF-8.
"""
import glob
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

WINDOWS = sys.platform == "win32"
OK, WARN, FAIL = "ok", "warn", "fail"    # the same words doctor.py uses

# Passed to every helper program started in the background, so that on Windows
# it never opens a console window of its own. Nothing is passed on Linux.
QUIET = {"creationflags": subprocess.CREATE_NO_WINDOW} if WINDOWS else {}


def utf8_output():
    """Windows prints Unicode to a console but uses the locale's encoding
    (cp1252 here) for a pipe or a file until Python 3.15."""
    if not WINDOWS:
        return
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


utf8_output()


# --- the handset's serial lead ----------------------------------------------

def serial_ports():
    """Every serial port seen, as (device, description) pairs."""
    if not WINDOWS:
        return [(port, Path(port).name) for port in sorted(glob.glob("/dev/serial/by-id/*"))]
    from serial.tools import list_ports
    return sorted((p.device, p.description or "") for p in list_ports.comports())


def serial_details():
    """Every serial port with what its USB adapter says of itself: for a
    hardware report, where the adapter's make is how a controller is told
    from a handset's lead. Each is {"device", "description", "maker", "usb"}."""
    try:
        from serial.tools import list_ports
        ports = sorted(list_ports.comports(), key=lambda p: p.device)
    except Exception:       # pyserial missing or the system will not list them: the names alone
        return [{"device": device, "description": name, "maker": "", "usb": ""} for device, name in serial_ports()]
    return [{"device": p.device, "description": p.description or "", "maker": p.manufacturer or "",
             "usb": f"{p.vid:04X}:{p.pid:04X}" if p.vid is not None and p.pid is not None else ""}
            for p in ports if WINDOWS or p.vid is not None]      # Linux lists sixteen ttyS that are nothing


# The mount drivers someone with a working Windows setup is likely to have:
# EQMOD, Green Swamp Server and Sky-Watcher's own, as ASCOM registers them.
ASCOM_MOUNT_DRIVERS = {"EQMOD.Telescope": "EQMOD", "ASCOM.GS.Sky.Telescope": "Green Swamp Server",
                       "ASCOM.SkyWatcher.Telescope": "Sky-Watcher's SynScan driver"}


def ascom_drivers(registered=None):
    """Which other mount software is installed (Windows): [] if none, or
    ["ASCOM Platform", "EQMOD", ...]. It reads the registry and changes
    nothing; telescopeyoke does not use ASCOM, and only says what it sees so
    that two programs are not left fighting over one COM port. `registered`
    stands in for the registry in the tests."""
    if registered is None:
        if not WINDOWS:
            return []
        import winreg
        registered = set()
        # ASCOM keeps its list in the 32-bit part of the registry; look in both.
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\ASCOM", 0, winreg.KEY_READ | view):
                    registered.add("")
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\ASCOM\Telescope Drivers", 0,
                                    winreg.KEY_READ | view) as drivers:
                    for i in range(winreg.QueryInfoKey(drivers)[0]):
                        registered.add(winreg.EnumKey(drivers, i))
            except OSError:
                pass
    if not registered:
        return []
    return ["ASCOM Platform"] + [name for key, name in ASCOM_MOUNT_DRIVERS.items()
                                 if any(key.lower() == found.lower() for found in registered)]


def serial_port(match):
    """The port of the lead whose USB adapter's name contains `match`, or None."""
    if not WINDOWS:
        ports = sorted(glob.glob(f"/dev/serial/by-id/*{match}*"))
        return ports[0] if ports else None
    from serial.tools import list_ports
    wanted = match.lower()
    for port in sorted(list_ports.comports(), key=lambda p: p.device):
        if wanted in " ".join(filter(None, (port.description, port.manufacturer, port.hwid))).lower():
            return port.device
    return None


def serial_fallback():
    """The port to try when no lead matched. Windows has none: a guessed COM
    port could be anything."""
    return None if WINDOWS else "/dev/ttyUSB0"


def serial_access():
    """Whether this user may open serial ports at all. It says nothing about
    whether the handset's port can be opened."""
    if WINDOWS:
        return OK, "serial access (does not apply: Windows has no dialout group)"
    import grp
    try:
        members = grp.getgrnam("dialout")
    except KeyError:
        return WARN, "no dialout group on this system"
    user = os.environ.get("USER", "")
    if members.gr_gid in os.getgroups() or members.gr_gid == os.getegid():
        return OK, "serial access (dialout group)"
    if user in members.gr_mem:
        return WARN, ("in the dialout group but not yet active: log out and back in, or "
                      "prefix mount commands with: sudo -u $USER -g dialout")
    return FAIL, "not in the dialout group: sudo usermod -aG dialout $USER"


# --- the camera's USB connection --------------------------------------------

def camera_usb_link(match):
    """How fast the camera's USB connection is. Linux lists every USB device
    with its speed; the camera is found by a name set in config.toml."""
    if WINDOWS:
        return WARN, ("camera USB link: speed and power saving cannot be read on Windows. "
                      "If frames are slow or cut off, open the camera and its USB hub in "
                      "Device Manager and, under Power Management, untick \"Allow the "
                      "computer to turn off this device to save power\"")
    match = match.lower()
    for device in Path("/sys/bus/usb/devices").glob("*"):
        product = device / "product"
        if product.exists() and match in product.read_text().lower():
            speed = int((device / "speed").read_text())
            name = {12: "USB 1 full speed: far too slow for a camera", 480: "USB 2 high speed",
                    5000: "USB 3", 10000: "USB 3.1"}.get(speed, "")
            # "auto" lets Linux power the port down when idle, which some
            # astronomy cameras take badly during long sessions.
            control = device / "power" / "control"
            saving = control.exists() and control.read_text().strip() == "auto"
            note = "; USB power saving is on for it" if saving else ""
            return (FAIL if speed < 480 else OK), f"camera USB link: {speed} Mbps ({name}){note}"
    return WARN, "camera USB link: camera not found on USB"


# --- the webcam that photographs the telescope -------------------------------

BUILT_IN = "HP_HD_Camera"


def _webcam_name():
    import config
    return config.hardware().get("webcam", {}).get("device", "")


def webcam_device():
    """The webcam to use: on Linux an external one if plugged in, else the
    laptop's own; on Windows the one config.toml names, or None."""
    if WINDOWS:
        return _webcam_name() or None
    cameras = sorted(glob.glob("/dev/v4l/by-id/*-video-index0"))
    external = [c for c in cameras if BUILT_IN not in c]
    return (external or cameras or ["/dev/video0"])[0]


def webcam_input():
    """ffmpeg's arguments for reading the webcam, or None if there is none."""
    device = webcam_device()
    if device is None:
        return None
    if WINDOWS:
        return ["-f", "dshow", "-video_size", "1280x720", "-i", f"video={device}"]
    return ["-f", "v4l2", "-input_format", "mjpeg", "-video_size", "1280x720", "-i", device]


def webcam_names():
    """The DirectShow cameras ffmpeg can see (Windows only)."""
    # ffmpeg prints the list on stderr and exits with an error, because
    # "dummy" is not a device: read stderr and ignore the exit code.
    done = subprocess.run(["ffmpeg", "-hide_banner", "-list_devices", "true", "-f", "dshow",
                           "-i", "dummy"], capture_output=True, timeout=20, **QUIET)
    names = []
    for line in done.stderr.decode("utf-8", "replace").splitlines():
        if "(video)" in line and '"' in line:
            names.append(line.split('"')[1])
    return names


def has_webcam():
    """(status, message) for the doctor."""
    if not shutil.which("ffmpeg"):
        return WARN, "ffmpeg not found; the webcam watch will not work"
    if not WINDOWS:
        if not glob.glob("/dev/video*"):
            return WARN, "no webcam; slews will not be photographed"
        return OK, "webcam and ffmpeg"
    wanted = _webcam_name()
    if not wanted:
        return WARN, ("no webcam named in config.toml ([webcam] device); slews will not "
                      "be photographed")
    try:
        names = webcam_names()
    except (OSError, subprocess.SubprocessError) as error:
        return WARN, f"webcam not checked: {error}"
    if wanted in names:
        return OK, f"webcam ({wanted}) and ffmpeg"
    seen = ", ".join(f'"{n}"' for n in names) or "none"
    return WARN, f'webcam "{wanted}" not found; cameras seen: {seen}'


# --- speech for the focusing aid ---------------------------------------------

# One PowerShell is kept open for the whole run and reads a phrase per line:
# starting one per phrase takes about a second each, so phrases would overlap
# or come out of order. It answers each line once the words have been spoken.
SPEAKER = ("Add-Type -AssemblyName System.Speech; "
           "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
           "while (($l = [Console]::In.ReadLine()) -ne $null) "
           "{ $s.Speak($l); [Console]::Out.WriteLine('.') }")
SPEAKER_COMMAND = ["powershell", "-NoProfile", "-NonInteractive", "-Command", SPEAKER]


class Speaker:
    """Speaks phrases one at a time, in order, without holding up the caller.
    A phrase still waiting when a newer one arrives is dropped: the newest
    focus reading is the only one worth hearing. One being spoken is always
    finished."""

    def __init__(self, command=SPEAKER_COMMAND):
        self.command = command
        self.waiting = queue.Queue(maxsize=1)
        self.thread = None

    def say(self, words):
        if self.thread is None or not self.thread.is_alive():
            # Started on first use, and again if the speaking program died.
            # A daemon thread, and a child that ends when its input closes,
            # so nothing here keeps the program alive after focusing ends.
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
        while True:
            try:
                self.waiting.put_nowait(words)
                return
            except queue.Full:
                try:
                    self.waiting.get_nowait()   # drop the stale phrase
                except queue.Empty:
                    pass

    def _run(self):
        try:
            child = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                                     **QUIET)
        except OSError:
            return   # no speech on this machine; focusing carries on silently
        while True:
            words = self.waiting.get()
            try:
                child.stdin.write(" ".join(words.split()) + "\n")
                child.stdin.flush()
                if not child.stdout.readline():   # it has gone away
                    return
            except OSError:
                return


_speaker = Speaker()


def speak(words):
    """Say `words` through the computer's speaker without waiting for it."""
    if WINDOWS:
        _speaker.say(words)
        return
    subprocess.Popen(["spd-say", "-r", "20", words],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def has_speech():
    """(status, message) for the doctor."""
    if WINDOWS:
        if shutil.which("powershell"):
            return OK, "speech (Windows, through PowerShell) for the focusing aid"
        return WARN, "PowerShell not found; the focusing aid will be silent"
    if shutil.which("spd-say"):
        return OK, "speech (spd-say) for the focusing aid"
    return WARN, "spd-say not found; the focusing aid will be silent"


# --- the application in the system's menu -------------------------------------

DESKTOP_ENTRY = """[Desktop Entry]
Type=Application
Name={name}
Comment=Plan the night and run the telescope
Exec="{python}" "{script}"{arguments}
Icon={icon}
Terminal=false
Categories=Science;Astronomy;
StartupWMClass=telescopeyoke
"""

SHORTCUT = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:TY_LINK); "
            "$s.TargetPath = $env:TY_TARGET; $s.Arguments = $env:TY_ARGUMENTS; "
            "$s.WorkingDirectory = $env:TY_FOLDER; $s.IconLocation = $env:TY_ICON; "
            "$s.Description = 'Plan the night and run the telescope'; $s.Save()")


def install_launcher(root, python=None, rig=None):
    """Put TelescopeYoke, and its demo, in the applications menu (Linux) or
    the Start Menu (Windows), so it is started like any other program: no
    terminal, its own icon. With `rig`, the one entry that opens that rig.
    Returns the files written."""
    root, python = Path(root), python or sys.executable
    entries = (("TelescopeYoke", ""), ("TelescopeYoke (demo)", " --demo"))
    if rig:
        entries = ((f"TelescopeYoke ({rig})", f" --rig {rig}"),)
    written = []
    if WINDOWS:
        # pythonw runs a program with no console window behind it.
        windowless = Path(python).with_name("pythonw.exe")
        target = str(windowless if windowless.exists() else python)
        menu = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        menu.mkdir(parents=True, exist_ok=True)
        for name, arguments in entries:
            link = menu / f"{name}.lnk"
            values = {"TY_LINK": str(link), "TY_TARGET": target, "TY_FOLDER": str(root),
                      "TY_ARGUMENTS": f'"{root / "app.py"}"{arguments}',
                      "TY_ICON": str(root / "console" / "telescopeyoke.ico")}
            # The values go in by the environment, never into the command's text.
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", SHORTCUT],
                           env={**os.environ, **values}, check=True, timeout=60, **QUIET)
            written.append(link)
        return written
    menu = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "applications"
    menu.mkdir(parents=True, exist_ok=True)
    for name, arguments in entries:
        entry = menu / ("telescopeyoke.desktop" if not arguments else
                        f"telescopeyoke-{rig}.desktop" if rig else "telescopeyoke-demo.desktop")
        entry.write_text(DESKTOP_ENTRY.format(name=name, python=python, script=root / "app.py",
                                              arguments=arguments, icon=root / "console" / "telescopeyoke.png"),
                         encoding="utf-8")
        entry.chmod(0o755)
        written.append(entry)
    return written


# --- opening a file for the person to edit ---------------------------------

def open_file(path):
    """Open a file in whatever the system uses for it (a text editor, for
    config.toml), without waiting for it to be closed."""
    if WINDOWS:
        os.startfile(str(path))      # noqa: S606  (the user's own settings file)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# --- asking a running script to end ------------------------------------------

# A script the console started must be able to be asked to end as Ctrl+C
# would, so that it closes the camera properly. On Windows a console event
# can only be sent to a process started in its own group, and what arrives
# is Ctrl+Break, which Python would otherwise treat as "die at once".
# It must share this program's console to receive one, so it is not given
# CREATE_NO_WINDOW as the other helper programs are.
OWN_GROUP = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {}

if WINDOWS:
    import signal
    try:
        signal.signal(signal.SIGBREAK, signal.default_int_handler)
    except ValueError:
        pass   # not the main thread: nothing was started this way


def ask_to_end(child):
    """Ask a child started with **OWN_GROUP to stop as Ctrl+C would."""
    import signal
    child.send_signal(signal.CTRL_BREAK_EVENT if WINDOWS else signal.SIGINT)


# --- previews on the web page -------------------------------------------------

def replace_preview(partial, final, patience=1.0):
    """Move a finished preview over the one the web page shows, so the page
    never loads a half-written file. On Windows the move fails while the web
    server has the old file open: try for about a second, then delete the new
    one, keep the old and return False.

    Only for files under web/ that the next frame replaces anyway. Anything
    that would be lost (session records, the drift model, calibration frames)
    must not come through here."""
    if not WINDOWS:
        os.replace(partial, final)
        return True
    give_up = time.monotonic() + patience
    while True:
        try:
            os.replace(partial, final)
            return True
        except PermissionError:
            if time.monotonic() >= give_up:
                break
            time.sleep(0.05)
    try:
        os.remove(partial)
    except OSError:
        pass
    return False


# --- the computer's own state, for the status page ----------------------------

def processor_load():
    """Share of the processor in use, as a percentage, or None if unknown."""
    if WINDOWS:
        return None
    return 100 * os.getloadavg()[0] / (os.cpu_count() or 1)


def temperature():
    """Processor temperature in °C, or None if unknown."""
    zone = Path("/sys/class/thermal/thermal_zone0/temp")
    if WINDOWS or not zone.exists():
        return None
    return int(zone.read_text()) / 1000


# --- whether the camera is plugged in, and has a driver -----------------------

DEVICE_QUERY = (
    "$found = Get-PnpDevice -PresentOnly | Where-Object { $_.FriendlyName -like '*MATCH*' } | "
    "ForEach-Object { [pscustomobject]@{ name = $_.FriendlyName; status = [string]$_.Status; "
    "problem = [int]$_.ConfigManagerErrorCode; driver = [string](Get-PnpDeviceProperty "
    "-InstanceId $_.InstanceId -KeyName DEVPKEY_Device_Service -ErrorAction SilentlyContinue).Data } }; "
    "ConvertTo-Json @($found) -Compress")


def camera_device(match):
    """What the system knows of a plugged-in camera whose name contains
    `match`, before any camera library is involved: {"name", "ready",
    "driver", "detail"}, or None if nothing of that name is plugged in."""
    if WINDOWS:
        if not match.replace(" ", "").replace("-", "").isalnum():
            return None      # the name goes into a command: letters and digits only
        import json
        done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                               DEVICE_QUERY.replace("MATCH", match)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=60, **QUIET)
        try:
            found = json.loads(done.stdout or "[]")
        except ValueError:
            found = []
        if not found:
            return None
        device = found[0]
        ready = device["status"] == "OK" and bool(device["driver"])
        detail = (f"driver {device['driver']}" if ready else
                  f"Windows has no working driver for it (status {device['status']}, "
                  f"problem code {device['problem']})")
        return {"name": device["name"], "ready": ready, "driver": device["driver"], "detail": detail}
    match = match.lower()
    for device in Path("/sys/bus/usb/devices").glob("*"):
        product = device / "product"
        if product.exists() and match in product.read_text().lower():
            return {"name": product.read_text().strip(), "ready": True, "driver": "",
                    "detail": camera_usb_link(match)[1]}
    return None
