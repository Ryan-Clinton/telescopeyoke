#!/usr/bin/env python3
"""How far this rig is from a first night, and the next step: `ty onboard`.

A setup gets interrupted (an evening runs out, Claude Code is closed), and
the next session has to know where it got to without starting again or
taking anything for granted. This reads what the other commands already
know (doctor.py's checks, config.toml, what is kept under cache/ and
frames/) and adds the one kind of fact no command can find out: what the
person has said they saw (the mount's first moves, a first frame). Each step
says how it is known: checked now, measured, the person's word, or not yet.

    ./onboard.py                     the steps, and the next one
    ./onboard.py --json
    ./onboard.py --confirm moves     the person watched the mount's first moves
                                     (also: equipment, frame, first-light,
                                     motor-focuser: the rig has the project's focuser)

Only the person confirms a step: an agent records one when they say so,
never on its own judgement. Nothing here moves anything or opens a camera.
"""
import argparse
import json
import sys
from datetime import datetime, timezone

import config
import interface
import records

RECORD = config.DATA / "cache" / "onboard.json"
CONFIRMABLE = {
    "equipment": "the telescope and camera in config.toml are theirs",
    "frame": "the camera has taken a frame they have seen",
    "moves": "they watched the mount's first moves and it turned the right ways and stopped",
    "first-light": "they have their first picture",
    "motor-focuser": "this rig has the project's motor focuser (docs/focuser.md)",
}


def equipment(cfg=None):
    """What the settings say the light path is: what the plate solver and
    every pixel scale are worked out from."""
    cfg = cfg or config.hardware()
    cam = cfg["camera"]
    return {"aperture_mm": cfg["scope"].get("aperture_mm"), "focal_length_mm": round(config.focal_length(cfg), 1),
            "camera": config.camera_name(cfg), "pixel_size_um": cam.get("pixel_size_um"),
            "width": cam.get("width"), "height": cam.get("height")}


def kept():
    try:
        return json.loads(RECORD.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def confirm(step):
    """Keep the person's word for one step, with the settings it was given
    for (a confirmed telescope stops counting once the settings change)."""
    if step not in CONFIRMABLE:
        raise interface.Refusal("INVALID_REQUEST", f"Confirm one of: {', '.join(CONFIRMABLE)}.")
    entry = {"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if step == "equipment":
        entry["equipment"] = equipment()

    def note(record):
        record.setdefault("confirmed", {})[step] = entry
    records.change(RECORD, note, empty={}, schema="onboard-record")
    return {"confirmed": step, "meaning": CONFIRMABLE[step]}


def own_site():
    try:
        site, example = config.load()["site"], config.example()["site"]
        return (site["latitude"], site["longitude"]) != (example["latitude"], example["longitude"])
    except (Exception, SystemExit):     # noqa: BLE001 - missing or unreadable settings: no site
        return False


def solved_scale():
    """The pixel scale the last plate solve measured through this light path
    (arcseconds a pixel), or None. Read from the file mount.py keeps, the
    same test as mount.last_solve, without importing the mount."""
    try:
        record = json.loads((config.DATA / "cache" / "last_solve.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if [record.get("camera"), record.get("focal_mm")] != list(config.light_path()):
        return None
    return record.get("scale")


def equipment_step(said):
    """Whether the light path in the settings is this rig's, and how that
    is known: measured by a plate solve, the person's word, set by them, or
    still the example's."""
    now, example = equipment(), equipment(config.example())
    measured = solved_scale()
    if measured:
        # The pipeline solves 2x2 frames: either scale is this light path's.
        expected = min((config.scale(block=b) for b in (1, 2)), key=lambda e: abs(measured - e))
        off = abs(measured - expected) / expected
        if off > 0.05:
            return False, "measured", (f"a plate solve measured {measured:.3f}\"/px, the settings make it "
                                       f"{expected:.3f}\"/px ({off:.0%} apart): check the focal length and "
                                       "pixel size in config.toml")
        return True, "measured", f"{measured:.3f}\"/px, as the settings make it"
    confirmed = (said.get("equipment") or {}).get("equipment")
    if confirmed == now:
        return True, "the person's word", "confirmed as theirs"
    if now != example:
        return True, "set by the person", f"{now['focal_length_mm']:g} mm, {now['camera']}"
    return False, "the example's", ("the settings still have the example's telescope and camera "
                                    f"({example['focal_length_mm']:g} mm, {example['camera']}): set theirs, or "
                                    "confirm it is theirs (--confirm equipment)")


def steps(check=True):
    said = kept().get("confirmed", {})
    data = config.DATA
    ready = {}
    if check:
        import doctor
        ready = doctor.report(offline=True)["ready"]

    def word(step):
        return said.get(step, {}).get("at")

    out = []

    def add(name, done, how, detail, next_step):
        out.append({"step": name, "done": bool(done), "how_known": how if done or how else "not yet",
                    "detail": detail, "next": None if done else next_step})

    if check:
        add("installed", ready["planner"], "checked now" if ready["planner"] else "",
            "the planner's libraries, catalogue and settings",
            "./install.sh (Windows: install.ps1), then ./doctor.py --offline")
    add("site", own_site(), "checked now", "the person's own latitude and longitude in config.toml",
        "put their latitude and longitude in config.toml (never guessed)")
    done, how, detail = equipment_step(said)
    add("equipment", done, how, detail, "set [scope] and [camera] in config.toml to their telescope and camera")
    if check:
        add("mount connected", ready["mount"], "checked now" if ready["mount"] else "",
            "the mount's lead and handset, as doctor.py finds them",
            "./doctor.py --need mount, plugging in as it asks")
    frame = next((data / "frames").rglob("*.fits"), None) if (data / "frames").is_dir() else None
    add("camera frame", frame or word("frame"), "kept on disk" if frame else "the person's word" if word("frame") else "",
        "a frame taken with this rig's camera" if frame or word("frame") else "no frame yet",
        "./snap.py indoors (a lens cap on is fine), then --confirm frame once they have seen it")
    used = (data / "cache" / "pointing.json").exists()
    add("first moves", used or word("moves"), "proven by use" if used else "the person's word" if word("moves") else "",
        "GoTos corrected by plate solving" if used else
        "watched by the person" if word("moves") else "nobody has said they watched the mount move",
        "with the person beside it: ./mount.py nudge (or directions), Ctrl+C during a move, one GoTo and home; "
        "--confirm moves only when they say it turned the right ways and stopped")
    light = next((data / "frames").glob("*/*/final.jpg"), None) if (data / "frames").is_dir() else None
    add("first light", light or word("first-light"), "kept on disk" if light else "the person's word" if word("first-light") else "",
        "a finished picture" if light or word("first-light") else "no finished picture yet",
        "at night: the nightly-setup skill, then imaging-run on something big and bright (./ty tonight)")
    return out


def kit():
    """What the skills choose their steps by: the camera in use (cooled or
    not, mono or colour) and whether its light path has a filter wheel, from
    the settings; the motor focuser from the person's word, since a CH340 on
    USB can be anything (the owner's rig: docs/agents/owner-rig.md)."""
    cfg = config.hardware()
    name = config.camera_name(cfg)
    profile = (cfg.get("cameras") or {}).get(name) or {}
    return {"camera": name, "cooled": bool(profile.get("cooled")), "mono": bool(profile.get("mono")),
            "filter_wheel": bool((cfg.get("train") or {}).get("filterwheel")),
            "motor_focuser": True if "motor-focuser" in kept().get("confirmed", {}) else None}


def report(check=True):
    found = steps(check)
    waiting = next((s for s in found if not s["done"]), None)
    return {"steps": found, "done": sum(s["done"] for s in found), "of": len(found),
            "next": waiting and {"step": waiting["step"], "do": waiting["next"]}, "kit": kit()}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--confirm", choices=list(CONFIRMABLE), help="keep the person's word for one step")
    ap.add_argument("--no-check", action="store_true",
                    help="leave out the steps doctor.py checks (installed, mount connected): quicker")
    ap.add_argument("--json", action="store_true", help="answer in JSON on stdout (see schemas/)")
    args = ap.parse_args()
    if args.confirm:
        done = interface.main("onboard", lambda: confirm(args.confirm), args.json)
        print(f"Kept: {done['meaning']}.")
        return 0
    if args.json:
        interface.main("onboard", lambda: report(not args.no_check), True)
    data = report(not args.no_check)
    for s in data["steps"]:
        print(f"  {'✓' if s['done'] else '·'} {s['step']}: {s['detail']}" + (f" ({s['how_known']})" if s["done"] else ""))
    k = data["kit"]
    print(f"\nKit: the {k['camera']} ({'cooled' if k['cooled'] else 'not cooled'}, {'mono' if k['mono'] else 'colour'}), "
          f"{'a' if k['filter_wheel'] else 'no'} filter wheel, motor focuser "
          f"{'yes (the person said)' if k['motor_focuser'] else 'not known: ask'}.")
    if data["next"]:
        print(f"\nNext: {data['next']['step']}. {data['next']['do']}")
    else:
        print("\nEvery step is done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
