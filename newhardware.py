#!/usr/bin/env python3
"""New hardware: notice it, ask what it is, and offer the report.

    ./newhardware.py                 the serial devices plugged in, and which are new, then the USB cameras,
                                     wheels and adapters with what TelescopeYoke can do with each; nothing is sent to any
    ./newhardware.py --known PORT    this one is yours and known (a focuser, say): not shown as new again
    ./newhardware.py --probe PORT    ask it what it is (only reads), write the report, and give the form filled in
    ./newhardware.py --watch         keep looking, and say so when something new is plugged in
    ./newhardware.py --probe wifi    ask the SynScan Wi-Fi adapter on the network this computer has joined
    ./newhardware.py --watch --install   watch from boot, as a systemd user service (ty-newhardware)

Noticing reads only what the computer already knows about a USB device (its
name, maker and USB numbers); nothing is sent to it, as it could be a
focuser, a printer or anything else. Asking what it is (`--probe`) is the
person's choice, one port at a time: doctor.py's read-only questions, as a
SynScan handset, then as a Sky-Watcher motor board, then as an LX200-family
mount (ZWO, OnStep, Meade), the first answer ending it.

A SynScan Wi-Fi adapter (or a mount with Wi-Fi built in: AZ-GTi, Star
Adventurer GTi) is not a USB device: it is noticed as a "SynScan_..." network
in the computer's own list of Wi-Fi networks, without asking it anything,
and `--probe wifi`, once the computer has joined that network, asks it the
motor board's version and position (direct.py: they only read).

Nothing is ever sent anywhere by itself. The report is written to
reports/hardware/, with the location and the adapters' serial numbers left
out, and a link to the project's Mount support form, already filled in, is
given for the person to look over and send if they choose
(docs/mounts.md). With --watch, a new device is said on the status page and,
if the person has set up Telegram, on their phone.
"""
import argparse
import json
import re
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

import config
import host
import interface
import records

KNOWN = config.DATA / "cache" / "known-hardware.json"
NEW = config.DATA / "cache" / "new-hardware.json"
REPORTS = config.DATA / "reports" / "hardware"
FORM = "https://github.com/Ryan-Clinton/telescopeyoke/issues/new"
LONGEST = 5000       # characters of the report put into the form's link; the rest is pasted from the file
EVERY_S = 10         # --watch: seconds between looks

# USB numbers worth naming when setting up a rig, with what TelescopeYoke can
# do with each (docs/hardware.md, "What to expect of other equipment"). By
# vendor and product, or vendor alone ("03c3"). A serial adapter says nothing
# about what is behind it: a handset's lead, an EQDIR cable and an Arduino
# all use the same few chips.
SERIAL_ADAPTER = ("serial adapter", "seen: what is behind it is unknown until asked (--probe PORT, only reads)")
USB_KINDS = {
    "0403": SERIAL_ADAPTER,                                   # FTDI
    "067b": SERIAL_ADAPTER,                                   # Prolific (Celestron's leads among others)
    "10c4": SERIAL_ADAPTER,                                   # Silicon Labs CP210x
    "1a86:7523": SERIAL_ADAPTER,                              # CH340 (the owner's focuser; many EQDIR cables)
    "2341": ("Arduino", "seen: TelescopeYoke's focuser firmware runs on one (firmware/focuser), "
                        "anything else does not"),
    "16d0:0c77": ("Altair camera", "proven: the Hypercam 183C and 183M"),
    "16d0:0b2a": ("Altair GPCAM guide camera", "proven as a guide camera on Linux (guidecam.py)"),
    "16d0": ("Altair camera", "unproven on this model: Altair's library on Windows, INDI's driver on Linux"),
    "1278:0920": ("Starlight Xpress filter wheel", "proven (sxwheel.py)"),
    "1278": ("Starlight Xpress device", "not supported, except their USB filter wheel"),
    "03c3": ("ZWO camera, wheel or focuser", "not supported on Windows except through its ASCOM driver "
                                             "(Alpaca, experimental: tried only on ASCOM's simulator); a ZWO "
                                             "camera is unproven through INDI on Linux"),
    "1618": ("QHY camera", "not supported on Windows except through its ASCOM driver (Alpaca, experimental: tried "
                           "only on ASCOM's simulator); unproven through INDI on Linux"),
    "a0a0": ("Player One camera", "not supported on Windows except through its ASCOM driver (Alpaca, experimental: "
                                  "tried only on ASCOM's simulator); unproven through INDI on Linux"),
}


def usb_inventory(devices=None, windows=host.WINDOWS):
    """The USB devices plugged in that matter to a telescope, each with what
    it is and what TelescopeYoke can do with it. Reads only."""
    found = []
    for d in host.usb_devices() if devices is None else devices:
        kind = USB_KINDS.get(d["usb"]) or USB_KINDS.get(d["usb"].split(":")[0])
        if kind:
            what, support = kind
            if not windows:
                support = support.split("; ", 1)[-1] if support.startswith("not supported on Windows") else support
            found.append({"usb": d["usb"], "name": d["name"], "kind": what, "support": support})
    return found


def key(d):
    """A device's identity across plugging in and out: its USB numbers and
    name, never its serial number or the port it landed on."""
    return f"{d.get('usb') or '?'}|{d.get('description') or d.get('device')}"


def local_key(d):
    """A device's identity on this computer alone: key(d) and a hash of its
    own serial number or USB socket (host.serial_details), so two identical
    adapters are two devices. Kept in cache/ only; reports use key(d)."""
    return f"{key(d)}#{d['local']}" if d.get("local") else key(d)


def scrub(text):
    """The text with adapters' serial numbers taken out: they identify one
    person's lead, and a report has no use for them."""
    text = re.sub(r"(usb-[^\s/]*?_)[A-Za-z0-9]{6,}(-if\d+)", r"\1…\2", text)
    return re.sub(r"(?i)(serial(?: number)?[:=]\s*)\S+", r"\1…", text)


def in_use():
    """The ports this rig already uses: the mount's lead and the focuser, by
    the adapter names in its own config.toml. A fresh checkout has none, and
    the example's names (an FTDI lead) say nothing about someone else's
    adapters, so then nothing is in use."""
    try:
        site, example = config.load()["site"], config.example()["site"]
        own = config.FILE.exists() and (site["latitude"], site["longitude"]) != (example["latitude"], example["longitude"])
    except (Exception, SystemExit):       # noqa: BLE001 - unreadable settings are no settings
        own = False
    if not own:     # a fresh checkout, or the example the installer copied, not yet filled in
        return set()
    hw = config.hardware()
    used = set()
    try:
        port = host.serial_port(hw["mount"]["serial_match"])
        if port:
            used.add(port)
    except Exception:
        pass
    # The focuser's Nano is found by its USB chip, as focuser.py finds it.
    try:
        import focuser
        port = host.serial_port((hw.get("focuser") or {}).get("serial_match", focuser.MATCH))
        if port:
            used.add(port)
    except Exception:
        pass
    return used | {str(Path(p).resolve()) for p in used}


def load_known():
    try:
        return set(json.loads(KNOWN.read_text(encoding="utf-8")).get("known", []))
    except (OSError, ValueError):
        return set()


def wifi_networks(run=None, windows=host.WINDOWS):
    """SynScan Wi-Fi networks in the computer's own list (Linux: NetworkManager;
    Windows: netsh), as devices: {"device": "wifi", "description", "maker",
    "usb", "joined"}. Joined means this computer is on it, not that the
    adapter has answered anything. None when the list could not be made
    (no Wi-Fi tools, the adapter off, Windows' location setting refusing
    it): then nothing seen proves nothing. Reads the list only; nothing is
    sent to the adapter."""
    import subprocess
    run = run or subprocess.run
    seen = {}
    try:
        if windows:
            # netsh's labels stay "SSID" in every language; the networks in
            # reach, then the one this computer has joined.
            listed = run(["netsh", "wlan", "show", "networks"], capture_output=True, text=True, timeout=10)
            if listed.returncode:
                return None
            heard = listed.stdout
            joined = run(["netsh", "wlan", "show", "interfaces"], capture_output=True, text=True, timeout=10).stdout
            on = {m.strip() for m in re.findall(r"(?m)^\s*SSID\s*:\s*(.+)$", joined or "")}
            for ssid in re.findall(r"(?m)^\s*SSID \d+\s*:\s*(.+)$", heard or "") + sorted(on):
                ssid = ssid.strip()
                if ssid.lower().startswith("synscan"):
                    seen[ssid] = ssid in on
        else:
            done = run(["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"], capture_output=True, text=True, timeout=10)
            if done.returncode:
                return None
            for line in done.stdout.splitlines():
                active, _, ssid = line.partition(":")
                if ssid.lower().startswith("synscan"):
                    seen[ssid] = seen.get(ssid, False) or active == "yes"
    except (OSError, subprocess.SubprocessError):
        return None
    return [{"device": "wifi", "description": f"SynScan Wi-Fi network {re.sub(r'_[A-Za-z0-9]+$', '_…', ssid)}",
             "maker": "Sky-Watcher", "usb": "", "joined": joined} for ssid, joined in seen.items()]


def look(details=None, known=None, used=None, networks=None):
    """Each serial device, and each SynScan Wi-Fi network in reach, with
    whether it is in use by this rig, known, or new."""
    details = (host.serial_details() if details is None else details) + (
        (wifi_networks() or []) if networks is None else networks)
    known = load_known() if known is None else known
    used = in_use() if used is None else used
    out = []
    for d in details:
        # A device marked known before 20 November 2026 was kept by key(d)
        # alone, which still counts for every adapter of its kind.
        state = "in use" if d["device"] in used else "known" if {local_key(d), key(d)} & known else "new"
        out.append(dict(d, state=state, key=local_key(d)))
    return out


def mark_known(port, details=None):
    found = [d for d in (host.serial_details() if details is None else details) if d["device"] == port]
    if not found:
        raise interface.Refusal("INVALID_REQUEST", f"No serial device on {port} now.")
    known = load_known() | {local_key(found[0])}
    records.write(KNOWN, {"known": sorted(known)})
    return key(found[0])


def form_link(device, report):
    """The Mount support form with what is known already filled in."""
    fields = {"template": "mount-support.yml",
              "title": f"Mount support: {device.get('description') or device.get('device')}",
              "doctor": report[:LONGEST]}
    return FORM + "?" + urllib.parse.urlencode(fields)


def wifi_report(finder=None, describer=None):
    """The SynScan Wi-Fi adapters on the joined network, as report text: each
    asked the motor board's version and position, which only read."""
    import direct
    import doctor
    finder = finder or direct.Udp.find
    describer = describer or (lambda address: direct.describe(direct.Udp(address)))
    lines = [doctor.hardware_report(False, True, None), "", "SynScan Wi-Fi adapters on this network:"]
    found = finder()
    if not found:
        lines.append("  none answered: is the mount switched on with the adapter in, and the adapter on this router (or this computer on its own SynScan_... network)?")
    for address in found:
        try:
            seen = describer(address)
            lines.append(f"  a motor board answered over Wi-Fi in the language EQMOD speaks: model {seen['model']}, "
                         f"firmware {seen['firmware']}, {seen['counts_per_turn']} counts per turn, "
                         f"{'moving' if any(seen['moving']) else 'not moving'}")
        except Exception as problem:
            lines.append(f"  an adapter answered but could not be read: {getattr(problem, 'message', problem)}")
    return "\n".join(lines)


def probe(port, details=None, reporter=None):
    """Ask what is on `port` (read-only), keep the report, and give the form.
    `port` "wifi" asks the SynScan Wi-Fi adapter on the joined network."""
    import doctor
    if port == "wifi":
        reporter = reporter or (lambda p: wifi_report())
        details = details if details is not None else [{"device": "wifi", "description": "SynScan Wi-Fi adapter",
                                                        "maker": "Sky-Watcher", "usb": ""}]
    reporter = reporter or (lambda p: doctor.hardware_report(False, True, p))
    device = next((d for d in (host.serial_details() if details is None else details) if d["device"] == port),
                  {"device": port, "description": port, "maker": "", "usb": ""})
    text = scrub(reporter(port))
    REPORTS.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9]+", "-", device.get("description") or Path(port).name).strip("-")[:40]
    path = REPORTS / f"{datetime.now():%Y%m%d-%H%M%S}-{name}.txt"
    path.write_text(text, encoding="utf-8")
    return {"device": scrub(port), "description": device.get("description"), "usb": device.get("usb"),
            "report": str(path), "form": form_link(device, text)}


def say_new(found, send=None):
    """A new device on the status page's file and, if set up, the phone."""
    new = [d for d in found if d["state"] == "new"]
    records.write(NEW, {"seen": time.time(), "new": [{k: d[k] for k in ("device", "description", "usb")}
                                                      for d in new]})
    if new and send is not False:
        import notify
        (send or notify.send)("New hardware plugged in: " + "; ".join(
            f"{d['description'] or d['device']} ({d['usb'] or 'no USB numbers'}) on {d['device']}" for d in new)
            + ". To find out what it is (it only reads): ./newhardware.py --probe PORT. If it is yours and "
            "known: ./newhardware.py --known PORT.")
    return new


def watch(say=print, every=EVERY_S, looker=look, rounds=None, send=None):
    """Look every `every` seconds; say each device the first time it is new."""
    told = set()
    n = 0
    while rounds is None or n < rounds:
        found = looker()
        fresh = [d for d in found if d["state"] == "new" and d["key"] not in told]
        if fresh:
            say_new(found, send)
            for d in fresh:
                say(f"new: {d['description'] or d['device']} ({d['usb']}) on {d['device']}")
            told |= {d["key"] for d in fresh}
        n += 1
        if rounds is None or n < rounds:
            time.sleep(every)


def install(say=print, run=None, home=None):
    """--watch as a systemd user service, from this checkout, from boot."""
    import subprocess
    import sys
    run = run or subprocess.run
    place = Path(home or Path.home()) / ".config" / "systemd" / "user"
    place.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parent
    (place / "ty-newhardware.service").write_text(
        "[Unit]\nDescription=telescopeyoke: notice new hardware plugged in (reads only)\n\n"
        f"[Service]\nWorkingDirectory={root}\nExecStart={sys.executable} {root / 'newhardware.py'} --watch\n"
        "Restart=on-failure\nRestartSec=30\nNice=10\n\n[Install]\nWantedBy=default.target\n", encoding="utf-8")
    run(["systemctl", "--user", "daemon-reload"], check=True)
    run(["systemctl", "--user", "enable", "--now", "ty-newhardware.service"], check=True)
    say("Watching for new hardware from boot (ty-newhardware). Stop it: "
        "systemctl --user disable --now ty-newhardware.service")
    return {"installed": str(place / "ty-newhardware.service")}


def run(args, say=print):
    if args.known:
        k = mark_known(args.known)
        say(f"{args.known} is known from now on ({k})")
        return {"known": k}
    if args.probe:
        answer = probe(args.probe)
        say(f"Report written: {answer['report']}")
        say("To send it to the project, open this, look it over, and press Submit (nothing is sent until you do):")
        say(answer["form"])
        return answer
    if args.watch and args.install:
        return install(say)
    if args.watch:
        watch(say)
        return {}
    networks = wifi_networks()
    found = look(networks=networks or [])
    for d in found:
        joined = " (joined)" if d.get("joined") else ""
        say(f"  {d['state']:7} {d['device']}  {d['description']}{joined}  {d['maker']}  {d['usb']}")
    if not found:
        say("No USB serial devices plugged in.")
    if networks is None:
        say("Wi-Fi networks could not be listed here, so a SynScan Wi-Fi adapter in reach would not show.")
    usb = usb_inventory()
    if usb:
        say("USB devices a telescope might use:")
    for d in usb:
        say(f"  {d['usb']}  {d['kind']} ({d['name'] or 'no name'}): {d['support']}")
    new = [d for d in found if d["state"] == "new"]
    if new:
        say("New: ./newhardware.py --probe PORT asks one what it is (it only reads; PORT \"wifi\" for a SynScan "
            "network, once joined); --known PORT if it is yours.")
    return {"devices": [{k: d[k] for k in ("device", "description", "maker", "usb", "state")} for d in found],
            "usb": usb, "wifi_listed": networks is not None}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--probe", metavar="PORT", help="ask the device on PORT what it is (only reads), and write the report")
    ap.add_argument("--known", metavar="PORT", help="the device on PORT is yours and known: not new again")
    ap.add_argument("--watch", action="store_true", help="keep looking for new devices")
    ap.add_argument("--install", action="store_true", help="with --watch: run it from boot as a systemd user service")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("newhardware", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
