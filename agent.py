"""What a program or a language model needs to know about the telescope, as
plain data. Everything here is read-only and none of it opens the mount's
serial port, so it is always safe to call.

One implementation, several ways in: the `ty` command, the read-only web API
that serve.py offers, and the MCP server in mcp_server.py all call these.
"""
import json
import re
import time
from datetime import datetime, timedelta, timezone
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


def _read_json(path, empty=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty


def _screen_summary(name, kind):
    """One star screen's coverage, from archive.py's own record and its own
    definition of a lead (archive.is_lead): how many screened of how many
    there are, how many failed, and the leads, in the screen's own order."""
    import archive
    record, whole = archive.status(kind)
    c = archive.coverage(record, whole)
    leads = sorted(((k, v) for k, v in record.items() if archive.is_lead(v)), key=lambda kv: archive._rank(kv[1]))
    return {"survey": name, "screened": c["done"], "failed": c["failed"], "unavailable": c["unavailable"],
            "excluded": c["excluded"], "of": whole,
            "covered_percent": round(100 * len(record) / whole, 3) if whole else None,
            "tabby_like": c["tabby_like"], "leads": c["leads"], "known_binaries": c["known_binaries"],
            "top_leads": [dict(v, star=k) for k, v in leads[:5]]}


def research(html=False):
    """The research that needs no sky, in one view (`ty research`): how much
    of each survey has been searched (the Kepler and TESS screens, each SETI
    sweep), the leads they flagged, what investigate.py made of the ones it
    looked into, and the papers not yet read. Each lead is kept apart by
    where it stands: a lead (flagged, not looked into), explained or an
    artefact (looked into), unexplained after the checks, and known to
    science (studied by others: SIMBAD cites it often). Reads files only;
    with `html`, also writes web/research.html for the 8080 page's server."""
    cache = config.DATA / "cache"
    surveys = [_screen_summary("Kepler screen", "kepler"), _screen_summary("TESS screen", "tess")]
    seti = []
    for path in sorted((cache / "seti").glob("*.json")):
        kept = _read_json(path, {}) or {}
        done = kept.get("done", {})
        blocks = len(kept.get("blocks") or [])
        seti.append({"survey": f"SETI sweep {path.stem}", "searched": len(done), "of": blocks,
                     "covered_percent": round(100 * len(done) / blocks, 2) if blocks else None,
                     "searched_mhz": round(sum(d["to_mhz"] - d["from_mhz"] for d in done.values()), 3),
                     "candidates": sum(d.get("candidates", 0) for d in done.values())})
    looked = []
    for path in sorted((cache / "research").glob("*.json")):
        r = _read_json(path)
        if r:
            looked.append({"lead": r["lead"], "star": r["star"], "verdict": r["verdict"],
                           "known_to_science": r.get("known_to_science", False),
                           "can_watch": r.get("follow_up", {}).get("can_watch"),
                           "investigated": r.get("investigated"), "report": f"docs/research/{r['lead']}.md"})
    # investigate.py's own queue: the same leads it would take, and those
    # it will look into again because a check went unanswered.
    import investigate
    kept = investigate.done()
    waiting = sum(1 for lead in investigate.leads() if investigate.lead_id(lead) not in kept)
    rechecks = len(investigate.recheck(kept))
    # literature.py's own rule: once anything is marked read, every paper
    # not marked; before that, only those of its last NIGHT_DAYS days.
    import feeds
    import literature
    marked = _read_json(cache / "literature-read.json", None)
    since = (datetime.now(timezone.utc) - timedelta(days=literature.NIGHT_DAYS)).isoformat()
    unread = 0
    for path in sorted(feeds.CACHE.glob("arxiv_*.json")):
        for p in _read_json(path, []) or []:
            if marked is None:
                unread += p.get("submitted", "") >= since[:19]
            else:
                unread += re.sub(r"v\d+$", "", p.get("id", "")) not in set(marked)
    count = lambda *labels: sum(1 for r in looked if r["verdict"] in labels)     # noqa: E731
    answer = {"surveys": surveys + seti,
              "leads": {"waiting": waiting, "to_recheck": rechecks, "explained": count("explained"),
                        "likely_explained": count("likely explained"), "artefact": count("artefact"),
                        "likely_interference": count("likely interference"),
                        "unexplained_weak": count("unexplained, weak"), "unexplained_strong": count("unexplained, strong"),
                        "known_to_science": sum(1 for r in looked if r["known_to_science"])},
              "investigated": sorted(looked, key=lambda r: r["investigated"] or "", reverse=True),
              "papers_unread": unread,
              "meaning": {"lead": "flagged by a search, not yet looked into",
                          "to_recheck": "looked into, but a catalogue did not answer: asked again next run",
                          "explained": "a catalogue names this star's variability and every catalogue answered",
                          "likely_explained": "a known class fits (a red giant, say) or a catalogue did not "
                                              "answer: likely, not certain",
                          "likely_interference": "a SETI candidate with signs of interference (a satellite band, "
                                                 "no drift): signs, not proof",
                          "artefact": "a check failed: the data, the pipeline or a neighbour's light",
                          "unexplained": "every check made and nothing accounts for it: for a person to read, "
                                         "not a discovery",
                          "known_to_science": "others have studied it (SIMBAD cites it 20 times or more)"}}
    if html:
        answer["page"] = str(write_research_page(answer))
    return answer


def write_research_page(answer):
    """web/research.html: the same numbers as a plain page, each report linked
    on GitHub (the reports are committed under docs/research/)."""
    import html as escape
    rows = "".join(
        f"<tr><td>{escape.escape(s['survey'])}</td><td>{s.get('screened', s.get('searched', 0))}</td>"
        f"<td>{s['of'] if s['of'] is not None else '?'}</td><td>{s['covered_percent'] if s['covered_percent'] is not None else '?'}%</td>"
        f"<td>{s.get('failed', '')}</td><td>{s.get('leads', s.get('candidates', 0))}</td></tr>" for s in answer["surveys"])
    looked = "".join(
        f"<tr><td><a href=\"https://github.com/Ryan-Clinton/telescopeyoke/blob/main/{escape.escape(r['report'])}\">"
        f"{escape.escape(r['star'])}</a></td><td>{escape.escape(r['verdict'])}</td>"
        f"<td>{'yes' if r['known_to_science'] else 'no'}</td><td>{'yes' if r['can_watch'] else 'no'}</td>"
        f"<td>{escape.escape((r['investigated'] or '')[:10])}</td></tr>" for r in answer["investigated"])
    leads = answer["leads"]
    meaning = "".join(f"<li><b>{escape.escape(k.replace('_', ' '))}</b>: {escape.escape(v)}</li>"
                      for k, v in answer["meaning"].items())
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Research</title><style>body{{font-family:system-ui,sans-serif;max-width:60rem;margin:1rem auto;padding:0 1rem;background:#fff;color:#111}}
table{{border-collapse:collapse;width:100%;margin:.5rem 0 1.5rem}}td,th{{border-bottom:1px solid #ccc;padding:.3rem .5rem;text-align:left}}
@media (prefers-color-scheme: dark){{body{{background:#111;color:#eee}}a{{color:#9cf}}td,th{{border-color:#444}}}}</style></head><body>
<h1>Research that needs no sky</h1>
<p>Leads waiting: <b>{leads['waiting']}</b>, {leads['to_recheck']} to ask again. Looked into: {leads['explained']} explained,
{leads['likely_explained']} likely explained, {leads['artefact']} artefacts, {leads['likely_interference']} likely interference,
{leads['unexplained_weak']} unexplained (weak), <b>{leads['unexplained_strong']}</b> unexplained (strong); {leads['known_to_science']} known to science.
Papers not yet read: {answer['papers_unread']}.</p>
<h2>Surveys</h2><table><tr><th>Survey</th><th>Searched</th><th>Of</th><th>Covered</th><th>Failed</th><th>Leads</th></tr>{rows}</table>
<h2>Looked into</h2><table><tr><th>Star</th><th>Verdict</th><th>Known to science</th><th>This telescope can watch</th><th>When</th></tr>{looked}</table>
<h2>What the words mean</h2><ul>{meaning}</ul></body></html>
"""
    path = config.DATA / "web" / "research.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
    return path


def candidates():
    """Every field's open candidates in one view, in the same shape as
    candidates.py's, each with its field; the most nights seen first; and
    the comet hunt's newest tracks heading in towards the Sun. It reads the
    candidate books and the hunt's answers and nothing else."""
    import candidates as book
    found = []
    for file in sorted((config.DATA / "candidates").glob("*.json")):
        try:
            kept = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        found += [dict(k, field=kept.get("name", file.stem)) for k in kept.get("candidates", []) if k.get("open")]
    found.sort(key=lambda k: (-book.nights_seen(k), k["id"]))
    # The comet hunt's newest answer from each camera: what heads in towards the Sun.
    comets = []
    for file in sorted((config.DATA / "sungrazer").glob("hunt-*.json")):
        try:
            hunt = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        comets += [dict(c, camera=hunt.get("camera"), hunted=hunt.get("when")) for c in hunt.get("towards_sun", [])]
    return {"name": "every field", "candidates": found, "comets": comets}


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
              "a ./focus.py run that ends on \"Focus good\"": "focus",
              "./mount.py sync on that side, or ./mount.py pointing": "sync", "./mount.py pointing": "pointing-survey",
              "./polaralign.py": "polar", "./polaralign.py --repeat 5": "polar-repeat",
              "./mount.py findhome": "find-home"}

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
    timing = read(camera_test.TIMING_FILE) or {}
    frames, trail = timing.get("timing"), timing.get("trail")
    items.append(line("How long a frame takes for the exposure asked", "./camera_test.py --timing", frames,
                      frames and f"{frames['overhead_s']:g} s, plus {frames['seconds_per_second_asked']:g} s for "
                                 "each second asked"))
    items.append(line("How long the shutter is really open", "./camera_test.py --trail (stars needed)", trail,
                      trail and f"{trail['share_of_asked']:.0%} of the time asked"))
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
        judged = status["captured"] - status.get("waiting", 0)    # not those kept for the quality pass
        status["acceptance_rate"] = round(status["accepted"] / judged, 3) if judged else 1.0
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


def spots():
    """Where the telescope stands tonight, and every spot known, each with
    whether its skyline has been measured."""
    import horizon
    cache = config.DATA / "cache"
    # A survey set aside or a skyline replaced (horizon-SPOT.not-used-TIME.json,
    # .replaced-TIME.json) is not a spot of its own.
    names = set(config.spots()) | {p.stem[len("horizon-"):] for p in cache.glob("horizon-*.json")
                                   if "." not in p.stem}
    rows = []
    for name in sorted(names):
        kept = cache / f"horizon-{name}.json"
        saved = json.loads(kept.read_text(encoding="utf-8")).get("saved") if kept.exists() else None
        rows.append({"name": name, "current": name == config.SPOT, "skyline_measured": saved is not None,
                     "skyline_saved": saved})
    return {"spot": config.SPOT, "skyline_measured": bool(horizon.measured()), "spots": rows}


def set_spot(name):
    """Say where the telescope stands from now on. A new spot gets its own
    settings, spots/NAME.toml, with nothing yet known to be in the way. The
    first spot named, when none was, takes over what was measured so far
    (config.toml's blocked directions, the skyline and its pictures): it is
    where the telescope has been standing."""
    import re
    import shutil
    if not re.fullmatch(config.NAME, name or ""):
        raise interface.Refusal("INVALID_REQUEST", f"A spot's name is lower-case letters, digits, - and _: not {name!r}.")
    made = config.spot_file(name)
    if not made.exists():
        config.SPOTS.mkdir(exist_ok=True)
        blocked = config.load()["horizon"].get("blocked", []) if config.SPOT is None else []
        rows = "".join(f"    {{ from = {b['from']}, to = {b['to']}, altitude = {b['altitude']} }},\n" for b in blocked)
        made.write_text(
            f"# Where the telescope stands: {name} (./ty spot {name}). Laid over config.toml.\n"
            "[horizon]\n# Directions blocked from here, as in config.toml; the measured skyline\n"
            f"# (./horizon.py --trace --daylight) is kept apart, per spot.\nblocked = [\n{rows}]\n",
            encoding="utf-8")
    if config.SPOT is None:
        old, new = config.DATA / "cache" / "horizon.json", config.DATA / "cache" / f"horizon-{name}.json"
        if old.exists() and not new.exists():
            old.replace(new)
        pictures, home = config.DATA / "horizon", config.DATA / "horizon" / name
        if pictures.exists() and not home.exists():
            home.mkdir()
            for item in list(pictures.iterdir()):
                if item != home and item.name not in config.spots():
                    shutil.move(str(item), home / item.name)
    config.save({("site", "spot"): name})
    config.SPOT = name
    return {"spot": name, "settings": f"spots/{made.name}",
            "skyline_measured": (config.DATA / "cache" / f"horizon-{name}.json").exists()}


PROGRAMMES = Path(__file__).resolve().parent / "programmes"


def discovery_tonight(demo=False):
    """When each discovery programme's field is up in darkness tonight, in
    the order they come best: what the night is for, before any pretty
    picture. The command is the one each programme's own header names."""
    import re
    import tomllib
    import numpy as np
    import sky
    import starwatch
    cfg = _site(demo)
    night = sky.Night(cfg)
    n = len(night.unix)
    plan = []
    for path in sorted(PROGRAMMES.glob("*.toml")):
        text = path.read_text(encoding="utf-8")
        p = tomllib.loads(text)
        field = p.get("target") or p.get("mosaic")
        # A watched star is placed by its watch (Tabby is in no catalogue).
        found = next((s for s in starwatch.STARS.values() if s["name"] == field), None)
        try:
            found = found or mount.find_target(field)
        except (interface.Refusal, Exception):
            continue
        alt, az = night.altaz_fixed([found["ra"]], [found["dec"]])
        seen = night.assess({"id": field, "kind": "star"}, np.full(n, found["ra"]),
                            np.full(n, found["dec"]), alt[0], az[0])
        command = re.search(r"then (\./\S+ \S+)", text)
        plan.append({"programme": path.stem, "field": field,
                     "minutes": p.get("minutes"), "mosaic": "mosaic" in p,
                     "command": command.group(1) if command else None,
                     "window": [seen["start"], seen["end"]] if seen else None,
                     "best_time": seen["best"] if seen else None,
                     "best_altitude_deg": seen["best_alt"] if seen else None,
                     "direction": seen["direction"] if seen else None,
                     "last_run": last_run(programme_fields(path.stem, p)),
                     "watch": watches(p, night.times.jd[0], night.times.jd[-1])})
    plan.sort(key=lambda r: (r["best_time"] is None, r["best_time"] or 0))
    return plan


def watches(p, start_jd, end_jd):
    """A programme's dated events ([[watch]] in its file, each with its
    source): whether tonight falls inside one of its windows, and the next
    window after tonight. Tabby's proposed companion (2026) is the first."""
    from astropy.time import Time
    day = lambda jd: Time(jd, format="jd").datetime.strftime("%Y-%m-%d")
    out = []
    for w in p.get("watch", []):
        spans = sorted(w.get("windows", []))
        inside = next((s for s in spans if s[0] <= end_jd and s[1] >= start_jd), None)
        later = next((s for s in spans if s[0] > end_jd), None)
        out.append({"what": w["what"], "source": w["source"], "tonight": inside is not None,
                    "window": [day(inside[0]), day(inside[1])] if inside else None,
                    "next": [day(later[0]), day(later[1])] if later else None})
    return out


def programme_fields(name, p):
    """The fields a programme images: its target, or its mosaic's panels."""
    if not p.get("mosaic"):
        return [p.get("target")]
    import patrol
    try:
        return patrol.fields(dict(p, name=name), keep=False)
    except Exception:
        return [p["mosaic"]]


def last_run(fields, data=None):
    """When a programme last imaged any of its fields (UTC), from the newest
    session folder holding a picture or frames; None if never. The folder
    names are the local time each session started."""
    from datetime import datetime, timezone
    base = (data or config.DATA) / "frames"
    names = [s.name for f in fields if f for s in (base / stacking.folder_name(f)).glob("*/")
             if re.fullmatch(r"\d{8}-\d{6}", s.name)
             and ((s / "final.fits").is_file() or any(s.glob("light-*.fits")))]
    if not names:
        return None
    return datetime.strptime(max(names), "%Y%m%d-%H%M%S").astimezone(timezone.utc)


def in_the_clear(plan, clear):
    """Each programme's window cut to the forecast's clear spell, and its best
    time inside it (the nearest the clear spell comes to the field's highest),
    so a plan never sends a patrol to a field under cloud. Best first."""
    for p in plan:
        span = None
        if p["window"] and clear:
            start, end = max(p["window"][0], clear[0]), min(p["window"][1], clear[1])
            span = [start, end] if start < end else None
        p["in_clear"] = span
        p["best_in_clear"] = min(max(p["best_time"], span[0]), span[1]) if span else None
    plan.sort(key=lambda r: (r["best_in_clear"] is None, r["best_in_clear"] or 0))
    return plan


FIELD_MIN_ARCMIN = 8     # a galaxy smaller than this is a few pixels of a 60' frame: little to patrol
BIG_SHARE = 0.25         # of the frame's width: "fills a decent proportion of the frame" (said 14 October 2026)
CADENCE_DAYS = 20        # a supernova stays within about a magnitude of its peak some three weeks:
                         # a galaxy unwatched this long may have had one come and go unseen


def _key(name):
    return (name or "").replace(" ", "").upper()


def _days_since(when, now):
    return None if when is None else max(0.0, (now - when.timestamp()) / 86400)


def watched_footprints():
    """Every frame the discovery programmes take, as footprints (footprint.py):
    a mosaic's panels from its plan, a field's from its reference's solve or
    at the catalogue's centre, a star's at its place."""
    import tomllib

    import footprint
    import starwatch
    out = []
    for path in PROGRAMMES.glob("*.toml"):
        p = tomllib.loads(path.read_text(encoding="utf-8"))
        if p.get("mosaic"):
            out += footprint.of_mosaic(p["mosaic"], p.get("grid", "1x1"))
            continue
        star = next((s for s in starwatch.STARS.values() if s["name"] == p.get("target")), None)
        if star and not footprint.of_reference(star["name"]):
            out.append(footprint.nominal(star["ra"], star["dec"]))
        elif p.get("target"):
            out += footprint.of_field(p["target"])
    return out


def kept_references():
    """{field: footprint} for each field with a usable reference kept: a
    numbered version whose picture is on disk (reference.newest), not merely
    a folder. Placed by the reference's own plate solve when kept, else at
    the catalogue's centre."""
    import footprint
    import reference
    root = config.DATA / "reference"
    out = {}
    for d in sorted(root.iterdir()) if root.is_dir() else []:
        path = reference.newest(d.name) if d.is_dir() else None
        if path is not None and path.is_file():
            placed = footprint.of_field(d.name)
            if placed:
                out[d.name] = placed[0]
    return out


EDGE_ON = 0.3     # a disc this thin for its length (minor/major axis) is seen nearly edge-on
FACE_ON = 0.8     # this round, nearly face-on


def describe(t):
    """What the object is, in a few words, from the catalogue alone (OpenNGC's
    class, its galaxy type and its two axes): "barred spiral galaxy (SBb),
    seen nearly edge-on, 9.3' x 2.2', magnitude 9.8". Nothing is written
    that the catalogue does not give."""
    kind, hubble = t.get("kind", ""), (t.get("hubble") or "").strip()
    words = kind
    if "galaxy" in kind and hubble:
        shape = ("elliptical" if hubble.startswith("E") else "lenticular" if hubble.startswith("S0")
                 else "barred spiral" if hubble.startswith("SB") else "spiral" if hubble.startswith("S")
                 else "irregular" if hubble.startswith("I") else "")
        words = f"{shape} galaxy ({hubble})" if shape else f"galaxy ({hubble})"
        size, minor = t.get("size"), t.get("minor")
        if size and minor and shape in ("spiral", "barred spiral", "lenticular"):
            if minor / size <= EDGE_ON:
                words += ", seen nearly edge-on"
            elif minor / size >= FACE_ON:
                words += ", seen nearly face-on"
    if t.get("name"):
        words = f"{t['name']}, {words}"
    if t.get("size"):
        words += f", {t['size']:g}' x {t['minor']:g}'" if t.get("minor") else f", {t['size']:g}' across"
    if t.get("mag") is not None:
        words += f", magnitude {t['mag']:g}"
    return words


def other_fields(rep, limit=4, data=None, now=None):
    """Galaxies up in darkness tonight that no discovery programme's frames
    hold, big enough to patrol: fresh fields for a supernova watch, ranked
    by what a watch there adds tonight, with the reasons.

    The value of a field is the product of: whether it can be searched
    tonight (a reference kept) or only gives its reference (half); how long
    since it was watched, up to CADENCE_DAYS (watched last night adds
    little: a supernova there would have been seen); how much of the galaxy
    the frame holds (a galaxy wider than the frame loses what falls
    outside); and how well placed it is tonight (the planner's score).
    No galaxy distances are kept, so its supernova rate is not ranked.

    Footprints are the camera's rectangle, turned as solved (footprint.py):
    a galaxy whose centre lies in a programme's frame (M110 in M31's mosaic)
    is left out, and one lying in a kept reference's frame (M81 in M81-M82)
    is offered as that field. A bright supernova listed in it now is named:
    the reference then holds it, its fading measured, not its arrival.
    2 November 2026: asked "can we not do fresh patrols on anything else?",
    the outlook had only the programmes."""
    import footprint
    import mosaic
    now = now or time.time()
    data = data or config.DATA
    watched = watched_footprints()
    kept = kept_references()
    frame_width = mosaic.field()[0]
    active = {_key(s["name"]): s for s in rep.get("supernovae", [])}
    out, taken = [], set()
    for t in rep["targets"]:
        size = t.get("size") or 0
        if "galaxy" not in t["kind"] or size < FIELD_MIN_ARCMIN:
            continue
        if any(footprint.contains(fp, t["ra"], t["dec"]) for fp in watched):
            continue
        field = next((name for name, fp in kept.items() if footprint.contains(fp, t["ra"], t["dec"])), t["id"])
        field = t["id"] if field == stacking.folder_name(t["id"]) else field    # its own reference: NGC2403
        if field in taken:
            continue
        taken.add(field)
        reference = stacking.folder_name(field) in kept
        days = _days_since(last_run([field], data), now)
        stale = 1.0 if days is None else min(days, CADENCE_DAYS) / CADENCE_DAYS
        held = min(1.0, frame_width * 60 / size)
        placed = max(0.0, min(1.0, (t.get("score") or 0) / 100))
        value = (1.0 if reference else 0.5) * stale * held * placed
        why = ["reference kept: searched tonight" if reference else "no reference: tonight's stack becomes it",
               "never watched" if days is None else f"last watched {days:.0f} days ago",
               "the whole galaxy in the frame" if held >= 1 else f"the frame holds {held:.0%} of its length",
               f"planner score {t.get('score')}"]
        names = {_key(t["id"]), _key(t.get("alt_id"))} - {""}
        sn = next((active[n] for n in names if n in active), None)
        if sn:
            why.append(f"{sn['id']} in it now: the reference will hold it")
        out.append(dict(_target(t), field=field, what=describe(t), size_arcmin=round(size, 1), reference=reference,
                        supernova=sn["id"] if sn else None, days_since_watched=days and round(days, 1),
                        value=round(value, 3), why=why,
                        command=f"./patrol.py {field!r}" if " " in field else f"./patrol.py {field}"))
    out.sort(key=lambda f: -f["value"])
    return out[:limit]


def history(name, data=None, now=None):
    """(nights imaged, days since the last) for a target, from its session folders."""
    base = (data or config.DATA) / "frames" / stacking.folder_name(name)
    nights = {s.name[:8] for s in base.glob("*/") if re.fullmatch(r"\d{8}-\d{6}", s.name)
              and ((s / "final.fits").is_file() or any(s.glob("light-*.fits")))}
    return len(nights), _days_since(last_run([name], data), now or time.time())


def _sky_apart(a, b):
    """Degrees between two catalogue entries."""
    import math
    ra1, d1, ra2, d2 = map(math.radians, (a["ra"], a["dec"], b["ra"], b["dec"]))
    c = math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(ra1 - ra2)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def _span(group):
    """Arcminutes from the far edge of one object to the far edge of
    another, across the widest pair of a group; one object's own size."""
    return max([o["size"] for o in group] + [_sky_apart(a, b) * 60 + (a["size"] + b["size"]) / 2
                                             for i, a in enumerate(group) for b in group[i + 1:]])


def big_targets(rep, limit=5, data=None, now=None):
    """The night's best targets that fill a decent share of the frame
    (BIG_SHARE of its width or more), in the planner's order, each with the
    share it fills, the mosaic it needs when bigger than the frame, and how
    often it has been imaged already: new ones are said as new, a repeat
    as adding to its stack. Objects that share one frame are taken
    together: the Double Cluster's two 14' halves fill the frame between
    them, as M81 and M82 do. Their sizes are added for the share filled
    (two small ones far apart fill little), and the span from the far edge
    of one to the far edge of the other sets the framing."""
    import mosaic
    width, height = mosaic.field()
    targets = [t for t in rep["targets"] if t.get("size")]
    out, used = [], set()
    for t in targets:
        if t["id"] in used:
            continue
        group, same = [t], set()
        for o in targets:                    # each one added only if the whole group still fits the frame
            if o["id"] in used or o is t:
                continue
            if any(_sky_apart(m, o) * 60 < (m["size"] + o["size"]) / 2 for m in group):
                same.add(o["id"])            # overlapping: the same thing under another entry (C14, h and chi Persei)
            elif _span(group + [o]) <= width * 60:
                group.append(o)
        span = _span(group)
        share = min(span, sum(o["size"] for o in group)) / 60 / width     # what the objects fill, not the gap
        if share < BIG_SHARE:
            continue
        used.update([o["id"] for o in group] + list(same))
        across = t.get("minor") if len(group) == 1 else max(o["size"] for o in group)   # a pair is long and thin
        columns, rows = mosaic.suggest(dict(t, size=span, minor=across), width, height)
        nights, days = history(t["id"], data, now)
        out.append(dict(_target(t), what=describe(t), size_arcmin=round(span, 1), frame_share=round(min(share, 1.0), 2),
                        panels=None if columns * rows == 1 else f"{columns}x{rows}",
                        nights_imaged=nights, days_since_imaged=days and round(days, 1),
                        **{"with": [o["id"] for o in group[1:]]}))
        if len(out) >= limit:
            break
    return out


def night(demo=False):
    """Tonight in brief: the verdict, when it is dark and clear, the Moon,
    and the discovery programmes' fields first, then the best targets."""
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
        "spot": None if demo else config.SPOT,
        "skyline_measured": bool(_site(demo)["horizon"].get("skyline")),
        "discovery": in_the_clear(discovery_tonight(demo),
                                  [w["clear_from"], w["clear_to"]] if w and w["clear_hours"] else None),
        "best_now": [_target(t) for t in rep["targets"] if t["now"]][:3],
        "best_tonight": big_targets(rep, data=None if not demo else config.DATA),
        "other_fields": other_fields(rep, data=None if not demo else config.DATA),
        "supernovae": [dict(_target(s), mag=s["mag"], type=s["type"], last_seen=s["last_seen"], peak_mag=s["peak_mag"])
                       for s in rep.get("supernovae", [])],
        "campaigns": [dict(_target(c), section=c["section"], priority=c["priority"], var_type=c["var_type"],
                           range=c["range"], cadence_days=c["cadence_days"],
                           days_since_measured=c["days_since_measured"], overdue=c["overdue"], note=c["note"],
                           link=c["link"])
                      for c in rep.get("campaigns", [])],
        "papers": rep.get("papers", []),
        "news": rep.get("news", []),
        "sources": rep.get("sources", []),
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


def discovery_fields():
    """The fields the discovery programmes (programmes/*.toml) point at."""
    import tomllib
    fields = set()
    for path in (Path(__file__).parent / "programmes").glob("*.toml"):
        try:
            target = tomllib.loads(path.read_text(encoding="utf-8")).get("target")
        except (OSError, tomllib.TOMLDecodeError):
            continue
        if target:
            fields.add(target)
    return fields


STOPPED_AFTER = 300     # seconds without a frame after which an unfinished run is taken to have died


def discovery(hours=14, now=None, data=None):
    """Tonight's discovery work, for the status page: every session started
    in the last `hours`, with how far it got and the patrol's answer when
    there is one; the mosaic being patrolled, panel by panel; Tabby's star;
    the comet hunt; and the candidates still open. Reads files only."""
    import datetime
    import re
    import mosaic
    base = data or config.DATA
    now = now or time.time()
    watched = discovery_fields()
    sessions = []
    for folder in (base / "frames").glob("*/*"):
        # Only discovery fields: a look at a bright star to focus on is not
        # a search, and "imaged; not searched" for it says nothing (18 October 2026).
        if not (folder.parent.name in watched or re.match(r".+-P\d+$", folder.parent.name)
                or (folder / "patrol.json").exists()):
            continue
        try:
            started = datetime.datetime.strptime(folder.name, "%Y%m%d-%H%M%S").timestamp()
        except ValueError:
            continue
        if not folder.is_dir() or now - started > hours * 3600 or started > now + 60:
            continue
        run = stacking.run_status(folder) if any(folder.glob("frames.json*")) else {}
        row = {"field": folder.parent.name, "session": folder.name, "started": started,
               "frames": run.get("captured", 0), "kept": run.get("accepted", 0), "planned": run.get("planned"),
               "finished": bool(run.get("finished")) or (folder / "frames.json").exists(),
               # A run with no frame for 5 minutes and no end record died (17 October: a camera hang).
               "stopped": not (run.get("finished") or (folder / "frames.json").exists())
               and run.get("age", 0) > STOPPED_AFTER,
               "summary": None, "unexplained": None, "pictures": []}
        patrolled = folder / "patrol.json"
        if patrolled.exists():
            p = json.loads(patrolled.read_text(encoding="utf-8"))
            row["summary"] = p.get("summary") or []
            row["unexplained"] = (p.get("vet") or {}).get("unexplained")
            row["pictures"] = sorted(q.name for q in folder.glob("patrol-*.png"))
        sessions.append(row)
    sessions.sort(key=lambda r: r["started"])
    mosaics = {}
    for row in sessions:
        found = re.match(r"(.+)-P(\d+)$", row["field"])
        if not found:
            continue
        kept = mosaic.load(found.group(1))
        if not kept:
            continue
        m = mosaics.setdefault(found.group(1), {"name": found.group(1), "columns": kept["columns"],
                                                "rows": kept["rows"], "panels": {}})
        m["panels"][int(found.group(2))] = {"state": "done" if row["summary"] is not None else
                                            "stopped" if row["stopped"] else "now",
                                            "unexplained": row["unexplained"], "session": row["session"]}
    for m in mosaics.values():
        m["panels"] = [dict({"panel": n}, **m["panels"].get(n, {"state": "waiting"}))
                       for n in range(1, m["columns"] * m["rows"] + 1)]
    tabby = None
    watched = base / "frames" / "Tabby" / "starwatch.json"
    if watched.exists():
        nights = json.loads(watched.read_text(encoding="utf-8")).get("nights") or []
        if nights:
            tabby = {"nights": len(nights), "last": nights[-1].get("session"),
                     "mag": round(nights[-1]["mag"], 3) if nights[-1].get("mag") is not None else None,
                     "error": nights[-1].get("scatter")}
    comets = None
    for hunt in sorted((base / "sungrazer").glob("hunt-*.json")):
        h = json.loads(hunt.read_text(encoding="utf-8"))
        comets = {"camera": h.get("camera"), "when": h.get("when"), "towards_sun": len(h.get("towards_sun") or [])}
    open_ = 0
    for book in (base / "candidates").glob("*.json"):
        open_ += sum(k.get("open", False) for k in json.loads(book.read_text(encoding="utf-8")).get("candidates", []))
    return {"sessions": sessions, "mosaics": list(mosaics.values()), "tabby": tabby, "comets": comets,
            "open_candidates": open_}


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
        where = f"Spot: {tonight['spot'] or 'not named'}"
        lines += [where + ("; skyline measured." if tonight["skyline_measured"] else
                           "; NO SKYLINE MEASURED HERE: windows go by the lowest altitude alone. "
                           "Measure it first: ./horizon.py --trace --daylight."), ""]
        # The night is for discovery first (docs/discovery.md): plan from these.
        lines += ["Discovery tonight (programmes/, best first):"]
        for p in tonight["discovery"]:
            when = (f"up {p['window'][0]:%H:%M}-{p['window'][1]:%H:%M}, best {p['best_time']:%H:%M} "
                    f"at {p['best_altitude_deg']:.0f} deg {p['direction']}" if p["window"]
                    else "not up in darkness")
            if tonight["clear_window"]:
                when += (f"; in the clear {p['in_clear'][0]:%H:%M}-{p['in_clear'][1]:%H:%M}, "
                         f"go about {p['best_in_clear']:%H:%M}" if p["in_clear"] else "; NOT up while clear")
            length = f"{p['minutes']} min{' a panel' if p['mosaic'] else ''}"
            last = f"last run {p['last_run']:%d %b %H:%M}" if p.get("last_run") else "never run"
            lines += [f"  {p['programme']} ({p['field']}, {length}): {when}; {last}; {p['command']}"]
        lines += [""]
        for s in tonight["supernovae"]:
            lines += [f"Supernova: {s['id']} in {s['name']}, mag {s['mag']:g} ({s['last_seen']}), "
                      f"best {s['best_time']:%H:%M} at {s['best_altitude_deg']:.0f} deg {s['direction']}"]
        if tonight["supernovae"]:
            lines += [""]
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
