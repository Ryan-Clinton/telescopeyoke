#!/usr/bin/env python3
"""What tonight's equipment can do, and what it still needs before its
science counts.

    ./instrument.py            the camera in use, its light path and filters, what is calibrated,
                               which programmes are ready, and what to commission first
    ./instrument.py --json

It reads the camera profile and train (config.py), the filter wheel's
filters and their focus offsets (filters.py), the calibration masters kept
for the camera (stacking.MatchedCalibration, the same check science fails
closed on), and the references kept per camera and band (reference.py). It
never opens the camera, the wheel or the mount.

A programme's science is one of:
- ready: matched calibration in its band and a reference in that band from
  this camera, so a visit can be searched against it;
- reference night: calibrated, but no reference from this camera in that
  band; tonight's visit makes it, and finds nothing new (a 183C reference
  never stands in for a 183M one);
- blocked: calibration is missing, and science refuses uncalibrated frames
  (difference images, photometry, depth).

A new camera's first nights are commissioning: masters, filter focus
offsets, references in its patrol band, and each band's depth measured, so
that later nights can compare one filter's science with another's on
measured figures rather than assumed ones.
"""
import argparse

import config
import interface

PATROL_EXPOSURE = 16.0     # the patrols' frame length (programmes/*.toml), the darks they need
PATROL_GAIN = 1500
COOL_RATE = 1.0            # °C a minute: the cooler's ramp (altair.py, never one jump)


def _programmes():
    import tomllib
    import goals
    out = []
    for name, path in goals.files():
        with path.open("rb") as f:
            p = tomllib.load(f)
        g = goals.from_programme(name, p, None)
        out.append({"programme": name, "field": p.get("target") or p.get("mosaic"), "mosaic": p.get("mosaic"),
                    "exposure": float(p.get("exposure", PATROL_EXPOSURE)), "gain": int(p.get("gain", PATROL_GAIN)),
                    "filter": (p.get("goals") or {}).get("filter"), "purpose": g["purpose"]})
    return out


def missing_calibration(cfg, exposure, gain, band):
    """What a frame of this camera, exposure, gain and filter would lack:
    the list MatchedCalibration gives (empty when all is there), or the
    183C's own way (scaled darks, a flat per setup) said as it stands."""
    import stacking
    camera = cfg["camera"].get("name", config.LEGACY_CAMERA)
    if stacking.dark_method(camera) != "matched":
        cal = stacking.Calibration(exposure, gain)
        return [f"{kind} (the 183C's scaled masters)" for kind in ("dark", "flat") if kind not in cal.masters]
    cards = {"INSTRUME": camera, "EXPTIME": exposure, "GAIN": gain,
             "SET-TEMP": cfg["camera"].get("tec_target"), "READSPD": cfg["camera"].get("readout_speed"),
             "OFFSET": cfg["camera"].get("offset"), "TELESCOP": cfg["train"]["name"], "XBINNING": 1}
    if band:
        cards["FILTER"] = band
    return list(stacking.MatchedCalibration(exposure, gain, header=cards).missing)


def references_in(field, band, mosaic=None):
    """How many reference versions this camera keeps for a field in a band
    (a mosaic's panels counted together)."""
    import reference
    import stacking
    names = [f"{mosaic}-P{n}" for n in range(1, 9)] if mosaic else [field]
    count = 0
    for name in names:
        count += len(reference.kept(stacking.folder_name(name), band if band else reference.CURRENT))
    return count


def readiness(cfg=None):
    """The equipment in use and what it is ready for, as a dict."""
    import filters
    cfg = cfg or config.hardware()
    camera = cfg["camera"]
    train = cfg["train"]
    block = int((cfg.get("imaging") or {}).get("processing_scale", 2)) if camera.get("mono") else 2
    focal = config.focal_length(cfg)
    scale = config.scale(cfg, block)
    width_deg = camera["width"] * camera["pixel_size_um"] / focal * 0.0572958
    height_deg = camera["height"] * camera["pixel_size_um"] / focal * 0.0572958
    wheel = filters.wheel_in_train(cfg)
    names = [f.strip() for f in str(filters.settings(cfg).get("filters", "")).split(",") if f.strip()] if wheel else []
    patrol_band = filters.DEFAULT if wheel else None
    try:
        store = filters.load(filters.path(cfg))
    except Exception:            # no focus record yet
        store = None
    bands = []
    for name in names:
        bands.append({"filter": name,
                      "calibration_missing": missing_calibration(cfg, PATROL_EXPOSURE, PATROL_GAIN, name),
                      "focus_offset": focus_state(name, store)})
    programmes = []
    for p in _programmes():
        band = p["filter"] or patrol_band
        missing = missing_calibration(cfg, p["exposure"], p["gain"], band)
        refs = references_in(p["field"], band, p["mosaic"]) if p["purpose"] == "nova-patrol" else None
        p["references"] = refs
        if missing:
            state = "blocked"
            why = "calibration missing: " + "; ".join(missing)
        elif p["purpose"] == "nova-patrol" and not refs:
            state = "reference night"
            why = (f"no {camera['name']} reference in {band or 'its band'}: tonight's visit makes one and "
                   "can find nothing new")
        else:
            state = "ready"
            why = "calibrated" + (f", {refs} reference(s) in {band}" if refs else "")
        programmes.append(dict(p, band=band, state=state, why=why))
    commissioning = steps_owed(cfg, camera, bands, programmes, patrol_band)
    return {
        "camera": {"name": camera.get("name"), "mono": bool(camera.get("mono")), "cooled": bool(camera.get("cooled")),
                   "tec_target": camera.get("tec_target"), "chosen_by": camera.get("chosen_by")},
        "train": {"name": train["name"], "corrector": train.get("corrector"), "focal_length_mm": round(focal, 1),
                  "arcsec_per_px": round(scale, 3), "processing_block": block,
                  "field_deg": [round(width_deg, 3), round(height_deg, 3)], "filterwheel": wheel},
        "filters": bands,
        "photometry_band": photometry_band(camera, names),
        "programmes": programmes,
        "commissioning": commissioning,
        "warnings": profile_warnings(cfg),
        "cooling_minutes_per_degree": round(1 / COOL_RATE, 1) if camera.get("cooled") else None,
    }


def focus_state(name, store):
    """A filter's focus against L's: in L's parfocal set, proven (three
    nights), provisional (one night, attended runs only), or not proven
    (the run refocuses after changing to it)."""
    import filters
    if store is None:
        return "not proven: no focus record yet"
    try:
        if filters.key_of(name, store) == filters.key_of(filters.DEFAULT, store):
            proved = any(name in s.split(",") for s in (store.get("proof") or {}).get("confirmed", []))
            return "focuses with L, proved" if proved else "with L by the parfocal setting, not yet proved on the sky"
        value, why = filters.offset_of(name, store)
        if value is None:
            return f"not proven: {why}"
        return "provisional: one night, attended runs only" if filters.provisional(name, store) else "proven"
    except Exception as problem:     # a broken record is said, not hidden
        return f"not read: {problem.__class__.__name__}"


def profile_warnings(cfg):
    """A camera profile that leaves out what science relies on: a second
    camera that says neither mono nor cooled is handled as the 183C (its
    darks scaled, not matched), whatever the camera itself is."""
    camera = cfg["camera"]
    out = []
    if camera.get("name") != config.LEGACY_CAMERA:
        unsaid = [k for k in ("mono", "cooled") if k not in (cfg.get("cameras") or {}).get(camera["name"], {})
                  or camera.get(k) is None]
        if not camera.get("cooled"):
            out.append(f"[cameras.{camera['name']}] does not say cooled = true: its darks are scaled as the 183C's, "
                       "not matched, so science does not fail closed without matched darks")
        if not camera.get("mono"):
            out.append(f"[cameras.{camera['name']}] does not say mono = true: it is treated as a colour camera")
        if unsaid and camera.get("cooled") and camera.get("tec_target") is None:
            out.append(f"[cameras.{camera['name']}] has no tec_target: the cooler has no target")
    return out


def photometry_band(camera, names):
    """What variable-star brightnesses from this camera may be called: the
    183C's green is close to V, untransformed; a mono camera's are in its
    own filter's band and are not V without a measured transformation. A
    light path with filters is measured in them, whatever the profile says."""
    if not camera.get("mono") and not names:
        return {"band": "green channel, close to V (untransformed)", "v_campaigns": True}
    if "V" in names:
        return {"band": "V filter (untransformed until standards are measured)", "v_campaigns": True}
    if "G" in names:
        return {"band": "G (Optolong), tricolour green: AAVSO's TG, not V", "v_campaigns": False}
    return {"band": "no green or V filter: not for V campaigns", "v_campaigns": False}


def steps_owed(cfg, camera, bands, programmes, patrol_band):
    """What a camera still needs before its science counts, most needed
    first, each with the command that does it."""
    out = []
    dark_missing = any("dark" in m for p in programmes for m in missing_calibration(cfg, p["exposure"], p["gain"], None))
    if dark_missing:
        exposures = sorted({p["exposure"] for p in programmes})
        out.append({"step": "darks", "why": "science refuses frames without matched darks",
                    "needs_sky": False,
                    "command": "; ".join(f"./calibrate.py dark --exposure {e:g} --gain {PATROL_GAIN}" for e in exposures)
                    + " (cap on; a cloudy night or indoors does)"})
    no_flat = [b["filter"] for b in bands if any("flat" in m for m in b["calibration_missing"])]
    if not bands and missing_calibration(cfg, PATROL_EXPOSURE, PATROL_GAIN, None):
        no_flat = ["(no wheel)"]
    if no_flat:
        out.append({"step": "flats", "why": f"no flat for {', '.join(no_flat)}",
                    "needs_sky": False,
                    "command": "./calibrate.py flat" + (", in each filter" if bands else "")
                               + " (twilight or an evenly lit wall), then its flat-dark"})
    unproven = [b["filter"] for b in bands if b["focus_offset"].startswith("not proven")
                or "not yet proved" in b["focus_offset"]]
    if unproven:
        out.append({"step": "filter focus offsets", "why": f"not proven for {', '.join(unproven)}",
                    "needs_sky": True, "command": "./focus.py --walk-in --prove-sets"})
    refs = [p for p in programmes if p.get("references") == 0]
    if refs:
        out.append({"step": f"references in {patrol_band or 'the patrol band'}",
                    "why": "no reference from this camera: " + ", ".join(p["programme"] for p in refs),
                    "needs_sky": True,
                    "command": "the patrols as usual: a first visit becomes the reference "
                               "(./reference.py FIELD --make if it does not)"})
    if bands:
        out.append({"step": "depth in each band", "why": "no filter's sensitivity is measured on this camera, so "
                                                         "one filter's science can't yet be weighed against another's",
                    "needs_sky": True,
                    "command": "./depth.py SESSION --plant on the first stack in each filter"})
    return out


def words(r):
    c, t = r["camera"], r["train"]
    lines = [f"Camera {c['name']} ({'mono' if c['mono'] else 'colour'}{', cooled to ' + str(c['tec_target']) + ' C' if c['cooled'] and c['tec_target'] is not None else ''}), "
             f"chosen by {c['chosen_by']}; train {t['name']}: {t['focal_length_mm']:g} mm, "
             f"{t['arcsec_per_px']:g}\"/px in {t['processing_block']}x{t['processing_block']} blocks, "
             f"field {t['field_deg'][0]:g} x {t['field_deg'][1]:g} deg"
             + ("; filter wheel" if t["filterwheel"] else "")]
    for w in r["warnings"]:
        lines.append(f"  ! {w}")
    for b in r["filters"]:
        cal = "calibrated" if not b["calibration_missing"] else "missing " + "; ".join(b["calibration_missing"])
        lines.append(f"  {b['filter']}: {cal}; focus: {b['focus_offset']}")
    lines.append(f"Variable stars: {r['photometry_band']['band']}")
    for p in r["programmes"]:
        lines.append(f"  {p['programme']} in {p['band'] or 'colour'}: {p['state']} ({p['why']})")
    if r["commissioning"]:
        lines.append("Commissioning still owed, first first:")
        for s in r["commissioning"]:
            lines.append(f"  {s['step']}{'' if s['needs_sky'] else ' (no sky needed)'}: {s['why']}: {s['command']}")
    return lines


def run(args, say=print):
    r = readiness()
    for line in words(r):
        say(line)
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("instrument", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
