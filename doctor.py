#!/usr/bin/env python3
"""Check that everything telescopeyoke needs is installed and connected.

    ./doctor.py                  check everything
    ./doctor.py --offline        skip the network check
    ./doctor.py --skip-handset   do not open the mount's serial port
    ./doctor.py --json           the same as data, for programs
    ./doctor.py --report         the check written out to post as a hardware report
    ./doctor.py --report --probe COM7    also ask whatever is on that port what it is

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
from interface import Refusal

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


def check_config(name_site=True):
    """`name_site` False leaves the site's name out: for a report that is posted in public."""
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
    return OK, f"config.toml, site \"{site['name']}\"" if name_site else "config.toml, with a location set"


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
    except (Exception, Refusal) as error:      # a Refusal is a SystemExit: it would end the whole check
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


def check_other_mount_software():
    """On Windows, say so if ASCOM or a mount driver such as EQMOD is
    installed: nothing is wrong, but only one program can have the mount's
    COM port at a time. None if there is none, or in the demo."""
    if _demo():
        return None
    found = host.ascom_drivers()
    if not found:
        return None
    return OK, (f"{', '.join(found)} installed. telescopeyoke does not use ASCOM and leaves it alone; it talks "
                "to the mount's COM port itself, so close EQMOD or whatever else has that port first")


def check_program(name, purpose):
    if _demo():
        return OK, f"{name} ({purpose}; not needed in the demo)"
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
    return host.has_sound()


def run(offline=False, skip_handset=False, name_site=True):
    """All the checks, as {section: [(status, message), ...]}."""
    import config
    driver = config.hardware()["camera"]["driver"]
    planner = [check_python(), check_libraries(), check_catalogue(), check_config(name_site)]
    if not offline:
        planner.append(check_network())
    mount = [check_serial_access(), check_serial_lead()]
    if not skip_handset:
        mount.append(check_handset())
    mount.append(check_webcam())
    others = check_other_mount_software()
    if others:
        mount.append(others)
    imaging = [check_solver(), check_star_database()]
    if config.DEMO:
        # The pretend camera is the same on every system: no driver, no library.
        imaging += [check_camera()]
    elif config.hardware()["camera"]["backend"] == "altair":
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


def words(results):
    """The checks as the lines a person reads."""
    lines = []
    for section, checks in results.items():
        lines.append(section.capitalize())
        lines += [f"  {MARK[status]} {message}" for status, message in checks]
        lines.append("")
    verdict = ready(results)
    return "\n".join(lines + [f"Ready for {section + ':':9} {'YES' if verdict[section] else 'NO'}"
                              for section in results])


# --- the hardware report --------------------------------------------------------

REPORTS = "https://github.com/Ryan-Clinton/telescopeyoke/issues/new?template=hardware-report.md"
# The mount's model as the handset numbers it, from Sky-Watcher's published
# serial protocol for the SynScan handset.
MODELS = {0: "EQ6", 1: "HEQ5", 2: "EQ5", 3: "EQ3", 4: "EQ8", 5: "AZ-EQ6", 6: "AZ-EQ5"}


def identity(link):
    """(mount model, handset firmware) as the handset gives them, each None
    if it did not say. Two questions from the published protocol; both only
    read, and neither is one the mount acts on."""
    link.write(b"V")
    raw = link.read_until(b"#", 8)
    if len(raw) == 2:
        # An older handset answers in two bytes and then "#". The second byte
        # of version x.35 is itself "#", so the real end is still to come.
        raw += link.read_until(b"#", 1)
    body, firmware = raw[:-1], None
    if len(body) == 6:              # newer: six hexadecimal digits, "042507" for 4.37.07
        try:
            firmware = "{}.{:02d}.{:02d}".format(*(int(body[i:i + 2], 16) for i in (0, 2, 4)))
        except ValueError:
            pass
    elif len(body) == 2:
        firmware = f"{body[0]}.{body[1]:02d}"
    link.write(b"m")
    code = link.read_until(b"#", 2)[:-1]
    model = None
    if len(code) == 1:
        model = MODELS.get(code[0], f"model number {code[0]} (not one this project knows)")
    return model, firmware


def gives_position(link):
    """Whether the handset answers "where are you pointing?" in the shape
    expected. Only whether: the answer itself would say roughly where on
    Earth the mount is, so it is not kept."""
    import re
    link.write(b"e")
    return bool(re.fullmatch(rb"[0-9A-F]{8},[0-9A-F]{8}#", link.read_until(b"#", 18)))


def handset_identity():
    """Ask the handset, or the demo's pretend one, what it is and whether it
    gives its position: (model, firmware, True or False). (None, None, None)
    if there is no handset to ask or it does not answer."""
    try:
        if _demo():
            import simulator
            link = simulator.SimulatedHandset()
            return (*identity(link), gives_position(link))
        port = find_serial_port() if mount_link() == "handset" else None
        if not port:
            return None, None, None
        import serial
        with serial.Serial(port, 9600, timeout=2) as link:
            return (*identity(link), gives_position(link))
    except Exception:       # a report with a gap in it is better than no report
        return None, None, None


BAUDS = (9600, 115200)      # a motor board on an EQDIR lead; one with a USB socket of its own


def probe(port):
    """Ask whatever is on one serial port what it is, in the two languages
    this project speaks: the SynScan handset's, then the motor board's (the
    one EQMOD speaks, at each usual speed). Every question only reads, and
    the first answer ends it, so a handset is never sent the motor board's
    words. It is only ever done to a port a person has named. Returns lines
    for the report."""
    import serial
    try:
        with serial.Serial(port, 9600, timeout=2) as link:
            link.write(b"Kx")
            if link.read_until(b"#", 8) == b"x#":
                model, firmware = identity(link)
                return [f"a SynScan handset answered at 9600 baud: mount {model or 'not given'}, "
                        f"firmware {firmware or 'not given'}, position {'given' if gives_position(link) else 'not given'}"]
    except Exception as problem:
        return [f"the port could not be opened: {getattr(problem, 'message', problem)}"]
    import direct
    lines = ["no SynScan handset answered at 9600 baud"]
    for baud in BAUDS:
        try:
            link = direct.Serial(port, baud)
            try:
                seen = direct.describe(link)
            finally:
                link.close()
        except (Exception, Refusal) as problem:
            lines.append(f"no motor board answered at {baud} baud ({getattr(problem, 'message', problem)})")
            continue
        return lines + [f"a motor board answered at {baud} baud in the language EQMOD speaks: model {seen['model']}, "
                        f"firmware {seen['firmware']}, {seen['counts_per_turn']} counts per turn, "
                        f"{'moving' if any(seen['moving']) else 'not moving'}"]
    return lines + ["nothing on this port answered in either language"]


def system():
    """The operating system in words, with nothing that names the computer or its owner."""
    import platform
    if host.WINDOWS:
        return f"Windows {platform.release()} ({platform.version()})"
    try:
        name = platform.freedesktop_os_release()["PRETTY_NAME"]
    except (OSError, KeyError, AttributeError):
        name = platform.system()
    return f"{name} ({platform.system()} {platform.release()}, {platform.machine()})"


def source():
    """Which copy of the code this is: a release's zip, or a git checkout and its commit."""
    import subprocess
    if not (ROOT / ".git").exists():
        return "from a release zip"
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                                text=True, timeout=10, **host.QUIET).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        commit = ""
    return f"a git checkout at {commit}" if commit else "a git checkout"


def config_rig():
    import config
    return config.RIG


def hardware_report(offline=False, skip_handset=False, probe_port=None):
    """The check written out for someone else to read: what the computer is,
    what the mount says it is, and every check. It only looks, as the check
    does, and nothing is moved. The site's name and the home folder are left
    out, since it is for posting in public."""
    import agent
    link = {"handset": "a serial lead to the SynScan handset", "wifi": "the SynScan Wi-Fi adapter (no handset)",
            "eqdir": "an EQDIR lead (no handset)"}.get(mount_link(), mount_link())
    lines = ["### telescopeyoke hardware report", "",
             f"- telescopeyoke {agent.VERSION} ({source()}), Python {'.'.join(str(v) for v in sys.version_info[:3])}",
             f"- System: {system()}",
             f"- Mount reached by: {'the demo (a pretend mount)' if _demo() else link}"]
    if config_rig():
        lines.append("- One of several rigs on this computer")
    if not skip_handset and (_demo() or mount_link() == "handset"):
        model, firmware, position = handset_identity()
        lines += [f"- Mount, as the handset names it: {model or 'not given'}",
                  f"- Handset firmware: {firmware or 'not given'}",
                  f"- Position: {'the handset gives it (left out of this report)' if position else 'not given'}"]
    if not _demo():
        ports = host.serial_details()
        lines.append(f"- Serial ports seen: {len(ports) or 'none'}")
        lines += ["  - " + ", ".join(filter(None, (p["device"].rsplit("/", 1)[-1], p["description"],
                                                  p["maker"] and f"made by {p['maker']}", p["usb"] and f"USB {p['usb']}")))
                  for p in ports]
    if probe_port:
        lines.append(f"- Asked {probe_port} directly what it is (questions that only read):")
        lines += [f"  - {line}" for line in probe(probe_port)]
    lines += ["", "```", words(run(offline, skip_handset, name_site=False)), "```", "",
              "Nothing was moved to make this report, and it leaves out where you are. Add what you",
              f"tried and what happened, then post it: {REPORTS}"]
    return "\n".join(lines).replace(str(Path.home()), "~")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--offline", action="store_true", help="skip the network check")
    ap.add_argument("--skip-handset", action="store_true",
                    help="do not open the mount's serial port")
    ap.add_argument("--json", action="store_true", help="answer in JSON (see schemas/)")
    ap.add_argument("--report", action="store_true",
                    help="write the check out to post as a hardware report; your location is left out")
    ap.add_argument("--probe", metavar="PORT",
                    help="with --report: ask whatever is on this serial port (COM7, /dev/ttyUSB0) what it "
                         "is, as a handset and then as a motor board. Only reads; close EQMOD first")
    args = ap.parse_args()

    if args.json:
        import interface
        result = interface.run("doctor", lambda: report(args.offline, args.skip_handset))
        sys.exit(interface.emit(result) or (0 if result["data"]["ready"]["planner"] else 1))
    if args.probe and not args.report:
        ap.error("--probe goes with --report")
    if args.report:
        print(hardware_report(args.offline, args.skip_handset, args.probe))
        return
    results = run(args.offline, args.skip_handset)
    print("telescopeyoke system check\n")
    print(words(results))
    print("\nNo telescope? Everything can be tried with --demo: ./tonight.py --demo")
    sys.exit(0 if ready(results)["planner"] else 1)


if __name__ == "__main__":
    main()
