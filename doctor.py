#!/usr/bin/env python3
"""Check that everything telescopeyoke needs is installed and connected.

    ./doctor.py                  check everything
    ./doctor.py --offline        skip the network check
    ./doctor.py --skip-handset   do not open the mount's serial port
    ./doctor.py --json           the same as data, for programs

It only looks; nothing is changed and the mount is never moved. The handset
check sends two status questions, so skip it while another command is using
the mount.
"""
import argparse
import glob
import json
import importlib
import shutil
import socket
import sys
from pathlib import Path

import host

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
    return OK, f"target catalogue ({sum(1 for _ in path.open(encoding='utf-8')) - 1} objects)"


def check_config():
    if _demo():
        return OK, "the example site (demo)"
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


def _demo():
    import config
    return config.DEMO


def mount_link():
    """How config.toml says the mount is reached: "handset", "wifi" or "eqdir"."""
    import config
    return config.hardware()["mount"].get("link", "handset")


def find_serial_port():
    """The mount's lead, or with the Wi-Fi adapter its address; None if not found."""
    import config
    settings = config.hardware()["mount"]
    if mount_link() == "wifi":
        import direct
        return settings.get("address") or next(iter(direct.Udp.find(wait=0.7)), None)
    return host.serial_port(settings["serial_match"])


def check_serial_access():
    if _demo():
        return OK, "serial access (not needed: the mount is simulated)"
    if mount_link() == "wifi":
        return OK, "serial access (not needed: the mount is reached over Wi-Fi)"
    return host.serial_access()


def check_direct():
    """The mount reached without its handset: what answers, and whether it
    has been told the two things a handset would know. Reads only."""
    import direct
    import config
    where = find_serial_port()
    if not where:
        return FAIL, "motor board not checked: no link to the mount"
    try:
        link = direct.Udp(where) if mount_link() == "wifi" else direct.Serial(where, config.hardware()["mount"].get("baud", 9600))
        try:
            seen = direct.describe(link)
        finally:
            link.close()
    except Exception as error:
        return FAIL, f"motor board not answering: {getattr(error, 'message', error)}"
    state = json.loads(direct.STATE_FILE.read_text(encoding="utf-8")) if direct.STATE_FILE.exists() else {}
    board = f"{seen['model']} motor board, firmware {seen['firmware']}"
    if not state.get("home") and seen["position_counts"] != [direct.POWER_ON, direct.POWER_ON]:
        return FAIL, (f"{board}: it has not been told where home is. With the mount at home, "
                      "run ./mount.py sethome")
    if state.get("dec_sign") is None:
        return WARN, (f"{board}: the Dec motor's direction has not been checked, so GoTo is "
                      "refused. With someone watching the mount, run ./mount.py directions")
    return OK, f"{board}, home recorded and Dec direction checked"


def check_serial_lead():
    if _demo():
        return OK, "simulated mount (demo)"
    if mount_link() == "wifi":
        where = find_serial_port()
        if where:
            return OK, f"SynScan Wi-Fi adapter ({where})"
        return FAIL, ("SynScan Wi-Fi adapter not found: join its network (SynScan_WiFi_xxxx), or "
                      "put it on this one and set address under [mount] in config.toml")
    port = find_serial_port()
    if not port:
        if host.WINDOWS:
            import config
            seen = ", ".join(f"{device} {name}" for device, name in host.serial_ports()) or "none"
            return FAIL, (f"handset serial lead not found: no COM port matches "
                          f"\"{config.hardware()['mount']['serial_match']}\" (serial_match "
                          f"under [mount] in config.toml). Ports seen: {seen}")
        return FAIL, "handset serial lead not found (is it plugged in?)"
    return OK, f"handset serial lead ({Path(port).name})"


def check_handset():
    if _demo():
        return OK, "simulated handset, set up (demo)"
    if mount_link() != "handset":
        return check_direct()
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


def check_solver():
    if _demo():
        return OK, "simulated plate solver (demo)"
    import config
    program = config.solver()["program"]
    if shutil.which(program):
        return OK, f"{Path(program).name} (plate solver)"
    if host.WINDOWS:
        return FAIL, (f"{Path(program).name} not found (plate solver). Install ASTAP's "
                      "command-line program, astap_cli.exe (astap.exe alone is not enough), "
                      "or name it under [solver] program in config.toml. "
                      "Looked on PATH and in " + ", ".join(config.SOLVER_FOLDERS))
    return FAIL, f"{program} not found (plate solver)"


def check_star_database():
    if _demo():
        return OK, "star database (not needed in the demo)"
    import config
    folder = config.solver()["database"]
    if glob.glob(str(Path(folder) / "d20_*")):
        return OK, "ASTAP D20 star database"
    return FAIL, f"ASTAP D20 star database not found in {folder}"


def check_indi_server():
    if _demo():
        return OK, "INDI server (not needed: the camera is simulated)"
    import config
    settings = config.hardware()
    if settings["camera"]["backend"] != "indi":
        return OK, "INDI server not used: the camera is read through the Altair SDK"
    port = settings["indi"]["port"]
    try:
        socket.create_connection(("localhost", port), timeout=2).close()
    except OSError:
        if settings["indi"]["manage_server"]:
            return OK, f"INDI server not running; it will be started when needed"
        return FAIL, (f"no INDI server on port {port}: start "
                      f"'indiserver {settings['camera']['driver']}'")
    return OK, f"INDI server on port {port}"


def check_camera_link():
    if _demo():
        return OK, "camera USB link (not needed in the demo)"
    import config
    return host.camera_usb_link(config.hardware()["camera"].get("usb_match", "ALTAIR"))


def check_camera():
    if _demo():
        return OK, "simulated camera (demo)"
    import config
    if config.hardware()["camera"]["backend"] == "altair":
        import altair
        return altair.checks()[-1]
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
    if _demo():
        return WARN, "no webcam in the demo; slews are not photographed"
    return host.has_webcam()


def check_speech():
    return host.has_speech()


def check_tones():
    if shutil.which("ffplay"):
        return OK, "ffplay (focusing tones)"
    return WARN, "ffplay not found; the focusing aid will speak but cannot play tones"


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
    imaging = [check_solver(), check_star_database()]
    if config.hardware()["camera"]["backend"] == "altair":
        import altair
        imaging += altair.checks()
    else:
        imaging += [check_program("indiserver", "INDI"), check_program(driver, "camera driver"),
                    check_indi_server(), check_camera()]
    imaging += [check_camera_link(), check_speech(), check_tones()]
    return {"planner": planner, "mount": mount, "imaging": imaging}


def ready(results):
    """{section: bool}. Mount and imaging also need the planner's basics."""
    passed = {name: all(status != FAIL for status, _ in checks)
              for name, checks in results.items()}
    return {"planner": passed["planner"],
            "mount": passed["planner"] and passed["mount"],
            "imaging": passed["planner"] and passed["imaging"]}


def report(offline=False, skip_handset=False):
    """The check as plain data: what is ready, and each component's state."""
    results = run(offline, skip_handset)
    return {
        "ready": ready(results),
        "components": {section: [{"status": status, "message": message}
                                 for status, message in checks]
                       for section, checks in results.items()},
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--offline", action="store_true", help="skip the network check")
    ap.add_argument("--skip-handset", action="store_true",
                    help="do not open the mount's serial port")
    ap.add_argument("--json", action="store_true", help="answer in JSON (see schemas/)")
    args = ap.parse_args()

    if args.json:
        import interface
        result = interface.run("doctor", lambda: report(args.offline, args.skip_handset))
        sys.exit(interface.emit(result) or (0 if result["data"]["ready"]["planner"] else 1))
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
