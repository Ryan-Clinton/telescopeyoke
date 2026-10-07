"""What a program or a language model needs to know about the telescope, as
plain data. Everything here is read-only and none of it opens the mount's
serial port, so it is always safe to call.

One implementation, several ways in: the `ty` command, the read-only web API
that serve.py offers, and the MCP server in mcp_server.py all call these.
"""
import contextlib
import io
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
WEB = config.DATA / "web"
VERSION = "0.2.1"
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
        "mount_lead": doctor.check_serial_lead(), "plate_solver": doctor.check_solver(),
        "star_database": doctor.check_star_database(), "camera_transport": doctor.check_indi_server(),
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
        "camera": {"available": good("camera_transport", "camera"),
                   "connected": parts["camera"]["status"] == doctor.OK},
        "plate_solver": {"available": good("plate_solver", "star_database"), "name": "ASTAP"},
        "imaging": {"available": good("camera_transport", "camera", "plate_solver", "star_database")},
        "motion": {
            "locked": locked,
            "lock_reason": mount.LOCK_FILE.read_text(encoding="utf-8").strip() if locked else None,
            "approval": "A person must ask for each move. Software, including an agent, must "
                        "not decide to move the mount or remove the lock by itself.",
            "limits": {"min_altitude_deg": mount.MIN_ALTITUDE,
                       "max_hour_angle_hours": mount.MAX_HOUR_ANGLE, "sun_exclusion_deg": 40},
        },
        "components": parts,
    }


def rigs():
    """Every rig in one view: what it is, from its settings, and what its
    newest imaging run is doing, from its own files. It reads; it asks no
    mount or camera anything. The telescope run with no rig named is listed
    first, as "default", when it has settings."""
    listed = [("default", config.ROOT / "config.toml", config.ROOT)] if (config.ROOT / "config.toml").exists() else []
    listed += [(name, config.RIGS / f"{name}.toml", config.RIGS / name) for name in config.rigs()]
    found = []
    for name, file, data in listed:
        entry = {"name": name, "current": name == (config.RIG or "default") and not config.DEMO}
        try:
            settings = config._merged(config._read(file))
            entry.update(mount_link=settings["mount"].get("link", "handset"),
                         serial_match=settings["mount"].get("serial_match"),
                         camera_backend=settings["camera"]["backend"],
                         focal_length_mm=settings["scope"]["focal_length_mm"])
        except Exception as problem:      # one rig's bad file must not hide the others
            entry["problem"] = f"its settings cannot be read: {problem}"
        try:
            run = session(data=data)
            entry["imaging"] = {k: run.get(k) for k in ("name", "state", "captured", "planned", "accepted",
                                                        "acceptance_rate", "median_fwhm", "age")}
        except interface.Refusal:
            entry["imaging"] = None
        found.append(entry)
    return {"rigs": found, "current": "demo" if config.DEMO else config.RIG or "default"}


def characterise():
    """What this rig has had measured about itself, and what it has not: one
    line for each thing telescopeyoke would otherwise have to assume. Read
    from the files the measuring commands keep; no mount or camera is asked
    anything. Each line says how to make the measurement."""
    import camera_test
    import focus
    import horizon
    import moved
    import polaralign

    def read(path):
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def line(what, how, found=None, value=None, when=None):
        when = when if when is not None else (found or {}).get("saved") if isinstance(found, dict) else None
        return {"what": what, "measured": value is not None, "value": value,
                "age_days": round((time.time() - when) / 86400, 1) if value is not None and when else None,
                "how": how, "action": ACTION.get(how)}

    # The application's action that makes each measurement, where it has one
    # (console.ACTIONS); the skyline has a screen of its own.
    ACTION = {"./camera_test.py --timing": "camera-timing", "./camera_test.py --trail (stars needed)": "camera-trail",
              "./focus.py, then ./focus.py --report": "focus", "a ./focus.py run that ends on \"Focus good\"": "focus",
              "./mount.py sync on that side, or ./mount.py pointing": "sync", "./mount.py pointing": "pointing-survey",
              "./polaralign.py": "polar", "./polaralign.py --repeat 5": "polar-repeat",
              "./mount.py response": "creep-response", "./mount.py findhome": "find-home"}

    # In the order the work is done on a mount: align it, find its home,
    # see how it points and that it turns, then how it tracks, then the
    # camera, the focus and the place it stands.
    items = []
    polar = read(polaralign.POLAR_FILE) or {}
    items.append(line("How far the polar axis is from the pole", "./polaralign.py",
                      value=f"{polar['total_deg']:g}°" if "total_deg" in polar else None, when=polar.get("measured")))
    items.append(line("How well that measurement repeats", "./polaralign.py --repeat 5",
                      value=f"±{polar['spread_deg']:g}° over {polar['repeats']} measurements" if "spread_deg" in polar else None,
                      when=polar.get("measured")))
    home = read(mount.HOME_FILE)
    items.append(line("Where the home position really is", "./mount.py findhome", home,
                      home and (f"out by {home['ra_home_error_deg']:+.2f}° on the RA axis and "
                                f"{home['dec_home_error_deg']:+.2f}° on the Dec axis"
                                + ("" if home["fits"] else "; the measurement did not fit and is not to be used"))))
    sides = (read(mount.POINTING_FILE) or {}).get("sides", {})
    for side in ("east", "west"):
        here = sides.get(side)
        items.append(line(f"Pointing error on the {side} side", "./mount.py sync on that side, or ./mount.py pointing",
                          here, here and f"{here['error_deg'][0]:+.2f}° in hour angle, {here['error_deg'][1]:+.2f}° in Dec"))
    survey = read(mount.SURVEY_FILE)
    items.append(line("Whether one pointing correction for each side is enough", "./mount.py pointing", survey,
                      survey and ("yes" if survey["one_correction_per_side_is_enough"] else "no: it changes with hour angle")))
    seen = read(moved.MOVED_FILE)
    judged = moved.checked()
    items.append(line("That the telescope turns when the mount says it has",
                      "any ./mount.py goto NAME --solve that needs a correction, or ./horizon.py --trace", seen,
                      seen and f"{seen['how']}; {judged['changed']} moves seen to be real so far, "
                               f"{judged['same']} not, {judged['undecided']} undecided"))
    answer = read(mount.RESPONSE_FILE)
    items.append(line("How the sky's drift answers the Dec motor's creep", "./mount.py response", answer,
                      answer and f"{answer['per_unit']:+.2f} for each arcsecond a second (it should be "
                                 f"{answer['expected_per_unit']:+.0f}); "
                                 + ("in proportion" if answer["straight"] else "not in proportion")))
    timing = read(camera_test.TIMING_FILE) or {}
    frames, trail = timing.get("timing"), timing.get("trail")
    items.append(line("How long a frame takes for the exposure asked", "./camera_test.py --timing", frames,
                      frames and f"{frames['overhead_s']:g} s, plus {frames['seconds_per_second_asked']:g} s for "
                                 "each second asked"))
    items.append(line("How long the shutter is really open", "./camera_test.py --trail (stars needed)", trail,
                      trail and f"{trail['share_of_asked']:.0%} of the time asked"))
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            answered = focus.report()
    except interface.Refusal:
        answered = None
    quick = [row["feedback_s"] for row in (answered or {}).get("levels", []) if row["level"] < 3 and row["feedback_s"]]
    items.append(line("How quickly focusing answers a turn of the knob", "./focus.py, then ./focus.py --report",
                      answered, f"heard within {max(quick):g} s on the quick levels" if quick else None))
    reached = focus.RUNS_FILE.exists() and focus.RUNS_FILE.stat().st_size > 0
    items.append(line("The star size good focus comes to", "a ./focus.py run that ends on \"Focus good\"",
                      value=f"{focus.usual_best():.2f} arcseconds" if reached else None,
                      when=focus.RUNS_FILE.stat().st_mtime if reached else None))
    skyline = horizon.measured()
    items.append(line("The skyline of the place it stands", "./panorama.py, or ./horizon.py --trace", skyline,
                      f"{len(skyline['skyline'])} points, from {skyline.get('source', 'a survey')}" if skyline else None))
    done = sum(item["measured"] for item in items)
    return {"measured": done, "of": len(items), "summary": f"{done} of {len(items)} measured", "items": items}


def session(include_frames=False, limit=50, include_series=False, data=None):
    """The newest imaging run: counts, the latest frame's quality, and why
    frames were dropped. Frame-by-frame detail only on request; so is the
    series of recent measurements, for drawing. `data` is another rig's
    folder, to read its run instead of this one's."""
    base = data or config.DATA
    folders = {p.parent for p in (base / "frames").glob("*/*/frames.json*")}
    if not folders:
        raise interface.Refusal("NO_SESSION", "No imaging run has been recorded yet.")
    newest = max(folders, key=lambda d: max(q.stat().st_mtime for q in d.glob("*.json*")))
    status = stacking.run_status(newest)
    series = status.pop("series", None)
    status["state"] = imaging_state(status)
    status["folder"] = str(newest.relative_to(base))
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
    if include_series and series:
        status["series"] = series
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


def _scale():
    """Arcseconds per pixel of the half-size frames: from the last plate solve
    if there is one, else from the camera and telescope in the settings."""
    if mount.LAST_SOLVE.exists():
        return json.loads(mount.LAST_SOLVE.read_text(encoding="utf-8"))["scale"]
    cfg = config.load() if config.FILE.exists() else config.example()
    pixel = config.hardware()["camera"]["pixel_size_um"]
    return 206.265 * 2 * pixel / cfg["scope"]["focal_length_mm"]


def _trend(kept, recent=5):
    """How the newest accepted frames compare with the ones before them."""
    if len(kept) < 2 * recent:
        return None
    middle = lambda frames, key: sorted(f[key] for f in frames)[len(frames) // 2]
    before, after = kept[:-recent], kept[-recent:]
    percent = lambda key: round(100 * (middle(after, key) / max(middle(before, key), 1e-6) - 1))
    return {"fwhm_change_percent": percent("fwhm"), "stars_change_percent": percent("stars"),
            "roundness_change": round(middle(after, "roundness") - middle(before, "roundness"), 2)}


def _explain(trend):
    """Put a name to what is going wrong, from which measurements moved."""
    notes = []
    if not trend:
        return notes
    wider, fewer = trend["fwhm_change_percent"], -trend["stars_change_percent"]
    oval = -trend["roundness_change"]
    if fewer >= 30:
        notes.append(f"Star count is down {fewer}%: likely cloud or dew.")
    if oval >= 0.1:
        notes.append(f"Stars are less round (by {oval:.2f}): likely tracking or wind.")
    if wider >= 15 and fewer < 30 and oval < 0.1:
        notes.append(f"Stars are {wider}% wider while their number and shape hold steady: "
                     "likely focus (or seeing), not cloud or tracking.")
    return notes


def observing(demo=False):
    """One read-only snapshot of everything that bears on the picture: the
    sky, the focus, the tracking and the imaging run, with a plain-words note
    when the measurements point at a cause."""
    import focus
    import tracking
    out = {"sky": {}, "optics": {"focus_state": "unknown"}, "tracking": {},
           "imaging": {"state": "idle"}, "notes": []}
    try:
        weather = _report(demo)["weather"]
        if weather:
            now = min(weather["hours"], key=lambda h: abs(h["time"].timestamp() - time.time()))
            out["sky"] = {"verdict": weather["verdict"], "cloud_percent": now["cloud"],
                          "seeing": now["seeing"], "transparency": now["transparency"],
                          "humidity_percent": now["humidity"],
                          "dew_margin_c": round(now["temp"] - now["dew_point"], 1)}
            if out["sky"]["dew_margin_c"] < 2:
                out["notes"].append("Air is within 2°C of the dew point: optics may fog.")
    except Exception as problem:   # no forecast must not hide the rest
        out["sky"] = {"error": str(problem)}

    if focus.FOCUS_FILE.exists():
        reading = json.loads(focus.FOCUS_FILE.read_text(encoding="utf-8"))
        good = reading["hfr"] <= 1.1 * reading["best_hfr"]
        out["optics"] = {"hfr": reading["hfr"], "best_hfr": reading["best_hfr"],
                         "stars": reading["stars"], "age_s": round(time.time() - reading["saved"]),
                         "focus_state": "good" if good else "soft"}

    if mount.DRIFT_FILE.exists():
        model = tracking.Model(mount.DRIFT_FILE)
        out["tracking"]["dec_creep_arcsec_s"] = model.creep
        if model.observations:
            out["tracking"]["natural_dec_drift_arcsec_s"] = round(model.observations[-1]["rate"], 2)
        out["tracking"]["polar_error"] = model.polar

    try:
        run = session()
    except interface.Refusal:
        return out
    log = stacking.read_log(ROOT / run["folder"])
    kept = [f for f in log if f["accepted"]]
    out["imaging"] = {k: run.get(k) for k in ("state", "name", "captured", "accepted",
                                              "acceptance_rate", "median_fwhm", "reasons")}
    trend = _trend(kept)
    if trend:
        out["imaging"]["trend"] = trend
    # How fast the stars slide across the frame, from the shifts the stacker
    # measured; the median step ignores the jump at a re-centre.
    timed = [f for f in kept if f.get("taken") and f.get("shift")][-20:]
    steps = [((b["shift"][0] - a["shift"][0]) ** 2 + (b["shift"][1] - a["shift"][1]) ** 2) ** 0.5
             / (b["taken"] - a["taken"]) for a, b in zip(timed, timed[1:]) if b["taken"] > a["taken"]]
    if steps:
        drift = sorted(steps)[len(steps) // 2] * _scale()
        out["tracking"]["drift_arcsec_s"] = round(drift, 2)
        out["tracking"]["max_recommended_exposure_s"] = round(tracking.exposure_limit(drift), 1)
    if run["state"] == "capturing":
        out["notes"] += _explain(trend)
        if run["captured"] >= 10 and run["acceptance_rate"] < 0.5:
            why = next(iter(run["reasons"]), "no reason recorded")
            out["notes"].append(f"Only {100 * run['acceptance_rate']:.0f}% of frames kept; "
                                f"mostly: {why}.")
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
    try:
        notes = observing(demo)["notes"]
    except Exception:
        notes = []
    if notes:
        lines += ["Worth knowing:"] + [f"  {note}" for note in notes] + [""]
    limits = caps["motion"]["limits"]
    lines += ["Constraints:",
              f"  Motion is {'LOCKED' if caps['motion']['locked'] else 'not locked'}; a person must "
              "ask for each move.",
              f"  Minimum altitude {limits['min_altitude_deg']} degrees; at most "
              f"{limits['max_hour_angle_hours']} h from the meridian.",
              "  Check any move first with: ty mount goto NAME --dry-run --json"]
    return "\n".join(lines)
