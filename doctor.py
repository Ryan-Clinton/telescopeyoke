#!/usr/bin/env python3
"""Check that everything telescopeyoke needs is installed and connected.

    ./doctor.py                  check everything
    ./doctor.py --offline        skip the network check
    ./doctor.py --skip-handset   do not open the mount's serial port

It only looks; nothing is changed and the mount is never moved. The handset
check sends two status questions, so skip it while another command is using
the mount.
"""
import argparse
import glob
import grp
import importlib
import os
import shutil
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).parent
OK, WARN, FAIL = "ok", "warn", "fail"
MARK = {OK: "✓", WARN: "!", FAIL: "✗"}
LIBRARIES = {"astropy": "astropy", "numpy": "numpy", "scipy": "scipy", "PIL": "pillow",
             "requests": "requests", "serial": "pyserial"}


def check_python():
    version = ".".join(str(v) for v in sys.version_info[:3])
    if sys.version_info < (3, 11):
        return FAIL, f"Python {version}; 3.11 or newer is needed"
    return OK, f"Python {version}"


def check_libraries():
    missing = []
    for module, package in LIBRARIES.items():
        try:
            importlib.import_module(module)
        except ImportError:
            missing.append(package)
    if missing:
        return FAIL, "Python libraries missing: " + ", ".join(missing)
    return OK, "Python libraries (" + ", ".join(LIBRARIES.values()) + ")"


def check_catalogue():
    path = ROOT / "data" / "targets.csv"
    if not path.exists():
        return FAIL, "target catalogue data/targets.csv is missing"
    return OK, f"target catalogue ({sum(1 for _ in path.open()) - 1} objects)"


def check_config():
    import config
    if not config.FILE.exists():
        return WARN, "no config.toml: copy config.example.toml and set your location"
    try:
        site = config.load()["site"]
    except Exception as error:   # a typo in the file should be reported, not crash
        return FAIL, f"config.toml cannot be read: {error}"
    example = config.example()["site"]
    if (site["latitude"], site["longitude"]) == (example["latitude"], example["longitude"]):
        return WARN, "config.toml still has the example location"
    return OK, f"config.toml, site \"{site['name']}\""


def check_network():
    try:
        socket.create_connection(("api.open-meteo.com", 443), timeout=5).close()
    except OSError:
        return WARN, "weather service unreachable; the report will lack a forecast"
    return OK, "weather service reachable"


def find_serial_port():
    import config
    match = config.hardware()["mount"]["serial_match"]
    ports = sorted(glob.glob(f"/dev/serial/by-id/*{match}*"))
    return ports[0] if ports else None


def check_serial_access():
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


def check_serial_lead():
    port = find_serial_port()
    if not port:
        return FAIL, "handset serial lead not found (is it plugged in?)"
    return OK, f"handset serial lead ({Path(port).name})"


def check_handset():
    port = find_serial_port()
    if not port:
        return FAIL, "handset not checked: no serial lead"
    try:
        import serial
        with serial.Serial(port, 9600, timeout=2) as s:
            s.write(b"Kx")
            if s.read_until(b"#", 8) != b"x#":
                return FAIL, "handset not answering: is it on and past its start-up screens?"
            s.write(b"h")
            clock = s.read_until(b"#", 16)
    except Exception as error:
        return FAIL, f"handset not reachable: {error}"
    if len(clock) == 9 and clock[5] == 22:
        return FAIL, ("handset not set up since power-on: press ENTER through its "
                      "start-up screens, entering today's date")
    return OK, "SynScan handset answering and set up"


def check_program(name, purpose):
    if shutil.which(name):
        return OK, f"{name} ({purpose})"
    return FAIL, f"{name} not found ({purpose})"


def check_star_database():
    if glob.glob("/opt/astap/d20_*"):
        return OK, "ASTAP D20 star database"
    return FAIL, "ASTAP D20 star database not found in /opt/astap"


def check_indi_server():
    import config
    settings = config.hardware()
    port = settings["indi"]["port"]
    try:
        socket.create_connection(("localhost", port), timeout=2).close()
    except OSError:
        if settings["indi"]["manage_server"]:
            return OK, f"INDI server not running; it will be started when needed"
        return FAIL, (f"no INDI server on port {port}: start "
                      f"'indiserver {settings['camera']['driver']}'")
    return OK, f"INDI server on port {port}"


def check_camera():
    import config
    port = config.hardware()["indi"]["port"]
    try:
        from indi import Indi
        client = Indi(port=port)
        devices = client.devices()
        client.close()
    except OSError:
        return FAIL, "camera not checked: no INDI server"
    cameras = [d for d in devices if any(name == "CCD_EXPOSURE" or name == "CONNECTION"
                                         for dev, name in client.props if dev == d)]
    if not cameras:
        return FAIL, "no camera on the INDI server (is it plugged in?)"
    return OK, f"camera: {cameras[0]}"


def check_webcam():
    if not shutil.which("ffmpeg"):
        return WARN, "ffmpeg not found; the webcam watch will not work"
    if not glob.glob("/dev/video*"):
        return WARN, "no webcam; slews will not be photographed"
    return OK, "webcam and ffmpeg"


def check_speech():
    if shutil.which("spd-say"):
        return OK, "speech (spd-say) for the focusing aid"
    return WARN, "spd-say not found; the focusing aid will be silent"


def run(offline=False, skip_handset=False):
    """All the checks, as {section: [(status, message), ...]}."""
    import config
    driver = config.hardware()["camera"]["driver"]
    planner = [check_python(), check_libraries(), check_catalogue(), check_config()]
    if not offline:
        planner.append(check_network())
    mount = [check_serial_access(), check_serial_lead()]
    if not skip_handset:
        mount.append(check_handset())
    mount.append(check_webcam())
    imaging = [check_program("astap_cli", "plate solver"), check_star_database(),
               check_program("indiserver", "INDI"), check_program(driver, "camera driver"),
               check_indi_server(), check_camera(), check_speech()]
    return {"planner": planner, "mount": mount, "imaging": imaging}


def ready(results):
    """{section: bool}. Mount and imaging also need the planner's basics."""
    passed = {name: all(status != FAIL for status, _ in checks)
              for name, checks in results.items()}
    return {"planner": passed["planner"],
            "mount": passed["planner"] and passed["mount"],
            "imaging": passed["planner"] and passed["imaging"]}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--offline", action="store_true", help="skip the network check")
    ap.add_argument("--skip-handset", action="store_true",
                    help="do not open the mount's serial port")
    args = ap.parse_args()

    results = run(args.offline, args.skip_handset)
    print("telescopeyoke system check\n")
    for section, checks in results.items():
        print(section.capitalize())
        for status, message in checks:
            print(f"  {MARK[status]} {message}")
        print()
    verdict = ready(results)
    for section in results:
        print(f"Ready for {section + ':':9} {'YES' if verdict[section] else 'NO'}")
    print("\nNo telescope? Everything can be tried with --demo: ./tonight.py --demo")
    sys.exit(0 if verdict["planner"] else 1)


if __name__ == "__main__":
    main()
