#!/usr/bin/env python3
"""How far this rig is from a first night, and the next step: `ty onboard`.

A setup gets interrupted (an evening runs out, Claude Code is closed), and
the next session has to know where it got to without starting again or
taking anything for granted. This reads what the other commands already
know (doctor.py's checks, config.toml, what is kept under cache/ and
frames/) and adds the one kind of fact no command can find out: what the
person has said they saw (the mount's first moves, a first frame). Each step
says how it is known: checked now, measured, kept on disk, the person's
word, or not yet. What was done once (a frame, a picture) is kept apart
from what works now (doctor.py's checks), and counts only for the camera
and light path in use.

    ./onboard.py                     the steps, and the next one
    ./onboard.py --json
    ./onboard.py --confirm moves     the person watched the mount's first moves
                                     (also: telescope, camera, frame, first-light,
                                     motor-focuser or manual-focuser)

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
    "telescope": "the telescope in config.toml ([scope]: aperture, focal length) is theirs",
    "camera": "the camera in config.toml ([camera]: which, its pixel size and sensor) is theirs",
    "frame": "the camera in use has taken a frame they have seen",
    "moves": "they watched the mount's first moves and it turned the right ways and stopped",
    "first-light": "they have their first picture with the camera in use",
    "motor-focuser": "this rig has the project's motor focuser (docs/focuser.md)",
    "manual-focuser": "this rig's focuser is turned by hand",
}
# Each of these pairs is one question: the newer answer replaces the other.
EITHER = {"motor-focuser": "manual-focuser", "manual-focuser": "motor-focuser"}


def telescope(cfg=None):
    cfg = cfg or config.hardware()
    return {"aperture_mm": cfg["scope"].get("aperture_mm"), "focal_length_mm": round(config.focal_length(cfg), 1)}


def camera(cfg=None):
    cfg = cfg or config.hardware()
    cam = cfg["camera"]
    return {"camera": config.camera_name(cfg), "pixel_size_um": cam.get("pixel_size_um"),
            "width": cam.get("width"), "height": cam.get("height"), "backend": cam.get("backend")}


def mount_identity(cfg=None):
    """Which mount the settings reach, as far as they say: how (link) and
    by what (the lead's adapter, the address, the driver's device). The
    person's word for its first moves holds for this mount only."""
    m = (cfg or config.hardware()).get("mount", {})
    return {k: m[k] for k in ("link", "serial_match", "address", "device") if m.get(k) not in (None, "")}


def train(cfg=None):
    """The light path's (train's) name, as frames carry it in TELESCOP."""
    return str(((cfg or config.hardware()).get("train") or {}).get("name") or "") or None


def kept():
    try:
        return json.loads(RECORD.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def confirm(step):
    """Keep the person's word for one step, with what it was given for: the
    settings, for the telescope and camera; the camera and light path, for a
    frame and a picture. Changing them makes the word stop counting."""
    if step not in CONFIRMABLE:
        raise interface.Refusal("INVALID_REQUEST", f"Confirm one of: {', '.join(CONFIRMABLE)}.")
    entry = {"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if step == "telescope":
        entry["settings"] = telescope()
    elif step == "camera":
        entry["settings"] = camera()
    elif step in ("frame", "first-light"):
        entry["light_path"] = list(config.light_path())
    elif step == "moves":
        entry["mount"] = mount_identity()

    def note(record):
        said = record.setdefault("confirmed", {})
        said[step] = entry
        said.pop(EITHER.get(step), None)
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


def settings_step(what, now, example, said, measured=()):
    """Whether one part of the light path in the settings is this rig's, and
    how that is known: the person's word for these very settings, or every
    value either set by them (changed from the example's) or `measured`
    (the plate solve's scale, a kept frame's size). One value changed does
    not make the rest theirs: a value still the example's and not measured
    leaves the part open until they confirm it."""
    if (said.get(what) or {}).get("settings") == now:
        return True, "the person's word", "confirmed as theirs"
    changed = [k for k in now if now[k] != example[k]]
    proven = [k for k in now if now[k] == example[k] and k in measured]
    same = [k for k in now if now[k] == example[k] and k not in measured]
    if not changed:
        return False, "", "still the example's"
    detail = f"changed from the example: {', '.join(changed)}" + (
        f"; measured: {', '.join(proven)}" if proven else "")
    if same:
        return False, "", f"{detail}; still the example's and not measured: {', '.join(same)}"
    return True, "set by the person" + (", and measured" if proven else ""), detail


def scale_step():
    """What a plate solve measured: the ratio of pixel size to focal length
    (the pixel scale), not either alone, nor the aperture or sensor size."""
    measured = solved_scale()
    if not measured:
        return None
    # The pipeline solves 2x2 frames: either scale is this light path's.
    expected = min((config.scale(block=b) for b in (1, 2)), key=lambda e: abs(measured - e))
    off = abs(measured - expected) / expected
    if off > 0.05:
        return False, "measured", (f"a plate solve measured {measured:.3f}\"/px, the settings make it "
                                   f"{expected:.3f}\"/px ({off:.0%} apart): check the focal length and pixel "
                                   "size in config.toml")
    return True, "measured", f"{measured:.3f}\"/px, as the settings' focal length and pixel size make it"


def sessions():
    """Each folder of frames, newest first, with the camera and focal length
    its first frame's header names. Needs astropy (installed by then: before
    the installer there are no frames)."""
    folder = config.DATA / "frames"
    if not folder.is_dir():
        return
    try:
        from astropy.io import fits
    except ImportError:
        return
    def changed(place):
        try:
            return place.stat().st_mtime
        except OSError:         # a folder tidied away while this looked
            return 0.0
    places = sorted({p.parent for p in folder.rglob("*.fits")}, key=changed, reverse=True)
    for place in places:
        try:
            first = min(place.glob("*.fits"))
            with fits.open(first) as hdus:
                head = hdus[1].header if len(hdus) > 1 else hdus[0].header
        except (OSError, ValueError):
            continue
        focal = head.get("FOCALLEN")
        binning = head.get("XBINNING") or 1
        yield place, [head.get("INSTRUME"), round(focal) if focal else None], {
            "train": head.get("TELESCOP"),
            "size": (head.get("NAXIS1", 0) * binning, head.get("NAXIS2", 0) * binning)}


def steps(check=True):
    said = kept().get("confirmed", {})
    path = list(config.light_path())
    ready = {}
    if check:
        import doctor
        ready = doctor.report(offline=True)["ready"]

    def word(step, bound=False):
        entry = said.get(step) or {}
        if step == "moves":
            # Given for one mount: another lead, address or link is another mount.
            return entry.get("at") if entry.get("mount") == mount_identity() else None
        return entry.get("at") if not bound or entry.get("light_path") == path else None

    # The frames by the light path in use, newest first: its camera and focal
    # length, and its train when the frame names one (frames before
    # TELESCOP was written count by the first two).
    mine = [(place, more) for place, made_with, more in sessions()
            if made_with == path and more["train"] in (None, train())]

    out = []

    def add(name, done, how, detail, next_step, now=False):
        out.append({"step": name, "done": bool(done), "how_known": how if done and how else "not yet",
                    "detail": detail, "next": None if done else next_step, "now": now})

    if check:
        add("installed", ready["planner"], "checked now", "the planner's libraries, catalogue and settings",
            "./install.sh (Windows: install.ps1), then ./doctor.py --offline", now=True)
    add("site", own_site(), "checked now", "the person's own latitude and longitude in config.toml",
        "put their latitude and longitude in config.toml (never guessed)")
    example = config.example()
    scale = scale_step()
    solved = ("focal_length_mm", "pixel_size_um") if scale and scale[0] else ()
    cam = camera()
    sized = ("width", "height") if any(more["size"] == (cam.get("width"), cam.get("height"))
                                       for _, more in mine) else ()
    done, how, detail = settings_step("telescope", telescope(), telescope(example), said, solved)
    add("telescope", done, how, detail, "set [scope] in config.toml to their telescope, or --confirm telescope "
        "once they say the values still the example's are theirs")
    done, how, detail = settings_step("camera", cam, camera(example), said, solved + sized)
    add("camera", done, how, detail, "set [camera] in config.toml to their camera, or --confirm camera "
        "once they say the values still the example's are theirs")
    if scale:
        done, how, detail = scale
        add("pixel scale", done, how, detail, "check [scope] focal_length_mm and [camera] pixel_size_um")
    if check:
        add("mount connected", ready["mount"], "checked now", "the mount's lead and handset, as doctor.py finds them",
            "./doctor.py --need mount, plugging in as it asks", now=True)
        blocked = doctor.goto_blocked()
        add("GoTo allowed", ready["goto"], "checked now",
            "the mount answers and nothing in its setting-up refuses a GoTo" if ready["goto"] else
            f"refused: {blocked}" if blocked else "not until the mount is connected",
            doctor.GOTO_NEXT.get(blocked, "connect the mount first"), now=True)
        add("imaging ready", ready["imaging"], "checked now",
            "the camera, its driver and the plate solver, as doctor.py finds them",
            "./doctor.py --need imaging, plugging in as it asks", now=True)
    frame = light = None
    for place, _ in mine:
        frame = frame or place
        if (place / "final.jpg").exists():
            light = place
            break
    camera_now = f"the {path[0]} at {path[1]} mm"
    add("camera frame", frame or word("frame", True),
        "kept on disk" if frame else "the person's word",
        f"a frame by {camera_now}" if frame or word("frame", True) else f"no frame yet by {camera_now}",
        "./snap.py indoors (a lens cap on is fine), then --confirm frame once they have seen it")
    used = (config.DATA / "cache" / "pointing.json").exists()
    add("first moves", used or word("moves"), "proven by use" if used else "the person's word",
        "GoTos corrected by plate solving (not the same as someone watching)" if used else
        "watched by the person" if word("moves") else "nobody has said they watched the mount move",
        "with the person beside it: ./mount.py nudge (or directions), Ctrl+C during a move, one GoTo and home; "
        "--confirm moves only when they say it turned the right ways and stopped")
    add("first light", light or word("first-light", True), "kept on disk" if light else "the person's word",
        f"a finished picture by {camera_now}" if light or word("first-light", True) else
        f"no finished picture yet by {camera_now}",
        "at night: the nightly-setup skill, then imaging-run on something big and bright (./ty tonight)")
    return out


def kit():
    """What the skills choose their steps by: the camera in use (cooled or
    not, mono or colour), whether the keeper can hold it cold, and whether
    its light path has a filter wheel, from the settings, with whether those
    are still the example's; the focuser from the person's word, since a
    CH340 on USB can be anything (the owner's rig: docs/agents/owner-rig.md)."""
    cfg = config.hardware()
    name = config.camera_name(cfg)
    profile = (cfg.get("cameras") or {}).get(name) or {}
    cooled = bool(profile.get("cooled"))
    said = kept().get("confirmed", {})
    own = config.FILE.exists() and (camera() != camera(config.example()) or "camera" in said)
    return {"camera": name, "source": "settings" if own else "example", "cooled": cooled,
            # keeper.py holds only a cooled camera on Altair's own library with a target set.
            "keeper": cooled and cfg["camera"].get("backend") == "altair" and cfg["camera"].get("tec_target") is not None,
            "mono": bool(profile.get("mono")),
            "filter_wheel": bool((cfg.get("train") or {}).get("filterwheel")),
            "motor_focuser": True if "motor-focuser" in said else False if "manual-focuser" in said else None}


def report(check=True):
    found = steps(check)
    waiting = next((s for s in found if not s["done"]), None)
    return {"steps": found, "done": sum(s["done"] for s in found), "of": len(found), "checked": check,
            "next": waiting and {"step": waiting["step"], "do": waiting["next"]}, "kit": kit()}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--confirm", choices=list(CONFIRMABLE), help="keep the person's word for one step")
    ap.add_argument("--no-check", action="store_true",
                    help="leave out what doctor.py checks now (installed, mount connected, imaging ready): quicker")
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
    focuser = {True: "the motor focuser", False: "a focuser by hand", None: "focuser not known: ask"}[k["motor_focuser"]]
    print(f"\nKit{' (the example settings, not theirs yet)' if k['source'] == 'example' else ''}: the {k['camera']} "
          f"({'cooled' + (', kept cold by keeper.py' if k['keeper'] else ', not by keeper.py') if k['cooled'] else 'not cooled'}, "
          f"{'mono' if k['mono'] else 'colour'}), {'a' if k['filter_wheel'] else 'no'} filter wheel, {focuser}.")
    if data["next"]:
        print(f"\nNext: {data['next']['step']}. {data['next']['do']}")
    elif data["checked"]:
        print("\nEvery step is done.")
    else:
        print("\nNothing outstanding among these; installed, mount connected and imaging ready were not checked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
