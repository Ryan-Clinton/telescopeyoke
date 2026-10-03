"""What a program or a language model needs to know about the telescope, as
plain data. Everything here is read-only and none of it opens the mount's
serial port, so it is always safe to call.

One implementation, several ways in: the `ty` command, the read-only web API
that serve.py offers, and the MCP server in mcp_server.py all call these.
"""
import json
import socket
import time
from pathlib import Path

import config
import doctor
import interface
import mount
import stacking

ROOT = Path(__file__).parent
WEB = ROOT / "web"
VERSION = "0.1.0"
_night_cache = {}


def _age(path):
    return round(time.time() - path.stat().st_mtime) if path.exists() else None


def _site(demo):
    return config.example() if demo or not config.FILE.exists() else config.load()


def components():
    """Each part of the setup as {"status": ok|warn|fail, "message": ...}."""
    checks = {
        "python_libraries": doctor.check_libraries(), "config": doctor.check_config(),
        "catalogue": doctor.check_catalogue(), "serial_access": doctor.check_serial_access(),
        "mount_lead": doctor.check_serial_lead(), "plate_solver": doctor.check_program("astap_cli", "plate solver"),
        "star_database": doctor.check_star_database(), "indi_server": doctor.check_indi_server(),
        "camera": doctor.check_camera(), "webcam": doctor.check_webcam(),
    }
    return {name: {"status": status, "message": message} for name, (status, message) in checks.items()}


def capabilities():
    """What can be done right now, and what is in the way of the rest."""
    parts = components()
    good = lambda *names: all(parts[n]["status"] != doctor.FAIL for n in names)
    planner = good("python_libraries", "catalogue")
    locked = mount.LOCK_FILE.exists()
    return {
        "version": VERSION,
        "planner": {"available": planner, "demo": True},
        "mount": {
            "available": planner and good("serial_access", "mount_lead"),
            "connected": parts["mount_lead"]["status"] == doctor.OK,
            "read_commands": ["status"],
            "motion_commands": ["goto", "point", "zenith", "home", "compensate"],
            "always_allowed": ["stop"],
            "dry_run": True,
        },
        "camera": {"available": good("indi_server", "camera"),
                   "connected": parts["camera"]["status"] == doctor.OK},
        "plate_solver": {"available": good("plate_solver", "star_database"), "name": "ASTAP"},
        "imaging": {"available": good("indi_server", "camera", "plate_solver", "star_database")},
        "motion": {
            "locked": locked,
            "lock_reason": mount.LOCK_FILE.read_text().strip() if locked else None,
            "approval": "A person must ask for each move. Software, including an agent, must "
                        "not decide to move the mount or remove the lock by itself.",
            "limits": {"min_altitude_deg": mount.MIN_ALTITUDE,
                       "max_hour_angle_hours": mount.MAX_HOUR_ANGLE, "sun_exclusion_deg": 40},
        },
        "components": parts,
    }


def session(include_frames=False, limit=50):
    """The newest imaging run: counts, the latest frame's quality, and why
    frames were dropped. Frame-by-frame detail only on request."""
    folders = {p.parent for p in (ROOT / "frames").glob("*/*/frames.json*")}
    if not folders:
        raise interface.Refusal("NO_SESSION", "No imaging run has been recorded yet.")
    newest = max(folders, key=lambda d: max(q.stat().st_mtime for q in d.glob("*.json*")))
    status = stacking.run_status(newest)
    series = status.pop("series", None)
    status["state"] = imaging_state(status)
    status["folder"] = str(newest.relative_to(ROOT))
    if status["captured"]:
        status["acceptance_rate"] = round(status["accepted"] / status["captured"], 3)
    if include_frames:
        log = stacking.read_log(newest)
        status["frames"] = [{k: f.get(k) for k in ("index", "accepted", "reason", "fwhm",
                                                   "roundness", "stars")} for f in log[-limit:]]
    elif series:
        kept = [v for v in series["fwhm"] if v is not None]
        if kept:
            status["median_fwhm"] = round(sorted(kept)[len(kept) // 2], 1)
    return status


def imaging_state(run):
    if run.get("restacked"):
        return "finished"
    if run.get("finished"):
        return "processing"
    return "capturing" if run.get("age", 10 ** 9) <= 180 else "idle"


def status():
    """The state of the mount, camera, imaging run and plate solver, each as
    one of a fixed set of words."""
    parts = components()
    lead = parts["mount_lead"]["status"] == doctor.OK
    try:
        run = session()
    except interface.Refusal:
        run = None
    camera_ok = parts["camera"]["status"] == doctor.OK
    newest_frame = _age(WEB / "latest.jpg")
    busy = (run and run["state"] == "capturing") or (newest_frame is not None and newest_frame < 30)
    solver = (parts["plate_solver"]["status"] == doctor.OK
              and parts["star_database"]["status"] == doctor.OK)
    return {
        "mount": {
            # The handset is only asked when someone runs "mount status":
            # this view must never get in the way of a command driving it.
            "state": "connected" if lead else "offline",
            "live_state_command": "ty mount status --json",
            "last_plate_solve_age_s": _age(mount.LAST_SOLVE),
            "motion_locked": mount.LOCK_FILE.exists(),
        },
        "camera": {"state": "offline" if not camera_ok else "capturing" if busy else "idle",
                   "newest_frame_age_s": newest_frame},
        "imaging": {"state": run["state"] if run else "idle",
                    "target": run["name"] if run else None,
                    "captured": run["captured"] if run else 0,
                    "accepted": run["accepted"] if run else 0},
        "solver": {"state": "ready" if solver else "unavailable"},
    }


def _report(demo=False):
    """Tonight's report, kept for five minutes: it takes a few seconds to make."""
    import tonight
    key = bool(demo)
    made, report = _night_cache.get(key, (0, None))
    if time.time() - made > 300:
        cfg = _site(demo)
        report = tonight.build(cfg, demo=demo or not config.FILE.exists())
        _night_cache[key] = (time.time(), report)
    return report


def _target(t):
    return {"id": t["id"], "name": t["name"], "kind": t["kind"], "score": t["score"],
            "observable_now": t["now"], "best_time": t["best"], "best_altitude_deg": t["best_alt"],
            "direction": t["direction"], "window": [t["start"], t["end"]], "tags": t["tags"]}


def night(demo=False):
    """Tonight in brief: the verdict, when it is dark and clear, the Moon."""
    rep = _report(demo)
    w = rep["weather"]
    return {
        "site": rep["site"], "date": rep["date"],
        "verdict": w["verdict"] if w else None,
        "clear_window": [w["clear_from"], w["clear_to"]] if w and w["clear_hours"] else None,
        "clear_hours": w["clear_hours"] if w else None,
        "mean_cloud_percent": w["mean_cloud"] if w else None,
        "notes": w["notes"] if w else ["no forecast available"],
        "sunset": rep["sunset"], "sunrise": rep["sunrise"],
        "darkness": {"level": rep["dark_level"], "start": rep["dark_start"], "end": rep["dark_end"],
                     "hours": rep["dark_hours"]},
        "moon": rep["moon"],
        "sky_brightness_mag_arcsec2": (rep["light_pollution"] or {}).get("sqm"),
        "best_now": [_target(t) for t in rep["targets"] if t["now"]][:3],
    }


def targets(limit=10, kind=None, now=False, demo=False):
    """The best targets tonight, best first."""
    found = _report(demo)["targets"]
    if kind:
        found = [t for t in found if kind == t["kind"] or kind in t["kind"].replace("+", " ").split()]
    if now:
        found = [t for t in found if t["now"]]
    return {"count": len(found), "targets": [_target(t) for t in found[:limit]]}


def target(name, demo=False):
    """One catalogue object: where it is now and whether the mount may go there."""
    site = _site(demo)["site"]
    found = mount.find_target(name)
    hour_angle, dec, altitude = mount.where(found, site)
    out = {"id": found["id"], "name": found.get("name", ""), "kind": found.get("kind", "star"),
           "altitude_deg": round(float(altitude), 1), "hour_angle_hours": round(float(hour_angle) / 15, 3),
           "dec_deg": round(float(dec), 2)}
    try:
        plan = mount.plan_goto(name, site)
        out["goto"] = {"allowed": True, "pier_side": plan["pier_side"], "warnings": plan["warnings"]}
    except interface.Refusal as refusal:
        out["goto"] = {"allowed": False, "error": refusal.as_error()}
    return out


def context(demo=False):
    """A short plain-text briefing for a model starting a session."""
    caps, now = capabilities(), status()
    lines = [f"telescopeyoke {VERSION}", ""]
    try:
        tonight = night(demo)
        window = ""
        if tonight["clear_window"]:
            window = f" Clear from {tonight['clear_window'][0]:%H:%M}, {tonight['clear_hours']} h."
        lines += ["Night:", f"  {tonight['verdict'] or 'no forecast'}.{window}",
                  f"  Dark {tonight['darkness']['start']:%H:%M}-{tonight['darkness']['end']:%H:%M}; "
                  f"Moon {tonight['moon']['illumination']}% lit.", ""]
        if tonight["best_now"]:
            lines += ["Best now: " + ", ".join(f"{t['id']} ({t['score']:.0f})"
                                               for t in tonight["best_now"]), ""]
    except Exception as problem:   # the briefing should survive a planner failure
        lines += [f"Night: unavailable ({problem})", ""]
    lines += ["Hardware:",
              f"  Mount {now['mount']['state']}; camera {now['camera']['state']}; "
              f"plate solver {now['solver']['state']}.", ""]
    run = now["imaging"]
    if run["target"]:
        lines += ["Imaging:", f"  {run['target']}: {run['state']}, {run['captured']} frames, "
                              f"{run['accepted']} accepted.", ""]
    limits = caps["motion"]["limits"]
    lines += ["Constraints:",
              f"  Motion is {'LOCKED' if caps['motion']['locked'] else 'not locked'}; a person must "
              "ask for each move.",
              f"  Minimum altitude {limits['min_altitude_deg']} degrees; at most "
              f"{limits['max_hour_angle_hours']} h from the meridian.",
              "  Check any move first with: ty mount goto NAME --dry-run --json"]
    return "\n".join(lines)
