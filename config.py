"""Site and equipment settings, read from config.toml."""
import copy
import os
import re
import shutil
import sys
import tomllib
from pathlib import Path

import host  # noqa: F401  (every script passes through here: makes output UTF-8)

ROOT = Path(__file__).parent
EXAMPLE = ROOT / "config.example.toml"

# The demo: a simulated mount and camera at the example site, with nothing
# plugged in. It is a property of the whole program, set when it starts
# (app.py --demo, console.py --demo, or TY_DEMO=1), and every command the
# program starts inherits it.
DEMO = os.environ.get("TY_DEMO") == "1"
# Where frames, pictures and remembered measurements are kept. The demo keeps
# its own, so that nothing made up is ever mixed with a real night's files.
# A rig is one telescope: its own settings (rigs/NAME.toml) and its own
# frames, pictures and remembered measurements (rigs/NAME/). Someone with two
# telescopes out runs the program once for each, with TY_RIG, "ty --rig NAME"
# or "app.py --rig NAME" saying which. With no rig named it is as it always
# was: config.toml and the folders beside it.
RIGS = ROOT / "rigs"
RIG = os.environ.get("TY_RIG") or None
if RIG and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,30}", RIG):
    sys.exit(f"A rig's name is letters, digits, - and _ (it names a file): not {RIG!r}")
DATA = Path(os.environ.get("TY_DATA") or (ROOT / "demo" if DEMO else RIGS / RIG if RIG else ROOT))
FILE = RIGS / f"{RIG}.toml" if RIG else ROOT / "config.toml"
if RIG and not DEMO and not FILE.exists():
    # A mistyped name must not quietly become a new, empty telescope.
    sys.exit(f"There is no rig called {RIG}. Make it with:  ./app.py --new-rig {RIG}\n"
             f"Rigs so far: {', '.join(sorted(p.stem for p in RIGS.glob('*.toml'))) or 'none'}")
if DATA != ROOT:
    DATA.mkdir(parents=True, exist_ok=True)     # the scripts make their own folders inside it


def rigs():
    """The names of the rigs that have settings, in order."""
    return sorted(p.stem for p in RIGS.glob("*.toml"))


def new_rig(name):
    """Make a rig's settings file, starting from config.toml if there is one
    (the site is the same garden) and from the example if not. Returns the
    file; an existing rig is left as it is."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,30}", name):
        raise ValueError(f"A rig's name is letters, digits, - and _: not {name!r}")
    RIGS.mkdir(exist_ok=True)
    made = RIGS / f"{name}.toml"
    if not made.exists():
        shutil.copy(ROOT / "config.toml" if (ROOT / "config.toml").exists() else EXAMPLE, made)
    return made

# Used for anything config.toml leaves out. These describe the hardware the
# project was built with, so an older config.toml keeps working.
DEFAULTS = {
    # margin: degrees the measured skyline is raised by before the planner
    # uses it. use_survey: whether the planner uses the measured skyline at all.
    "horizon": {"min_altitude": 20, "blocked": [], "margin": 2, "use_survey": True},
    "scope": {"aperture_mm": 150, "focal_length_mm": 750},
    "camera": {"driver": "indi_altair_ccd", "bit_depth": 12, "pixel_size_um": 2.4,
               "width": 5440, "height": 3648, "setup": "default",
               # How frames are fetched: through the INDI driver, or straight
               # from Altair's own library. INDI does not run on Windows.
               "backend": "altair" if sys.platform == "win32" else "indi"},
    # link: "handset" (a serial lead to the SynScan handset), or with no handset
    # "wifi" (the SynScan Wi-Fi adapter) or "eqdir" (an EQDIR lead).
    # nudge_check: whether the setup routine's motor check (./mount.py nudge) is a step.
    "mount": {"serial_match": "FTDI", "link": "handset", "nudge_check": True},
    "indi": {"port": 7624, "manage_server": False},
    # focus_tones: the focus run's tones in the live stream's sound (stream.Tones).
    "stream": {"focus_tones": True},
    # travel: the furthest, in half-steps either way, a focus run may turn the
    # motor from where it started.
    "focuser": {"travel": 512},
    # filters: the Starlight Xpress wheel's filters, position 1 first (sxwheel.py).
    # None until someone has looked which filter sits in which slot: until
    # then the positions go by number, so no frame is named by a guess.
    "filterwheel": {"filters": ""},
    # camera: the camera profile to use when both are plugged in; blank, the
    # one plugged in ([cameras.NAME], docs/mono-upgrade.md).
    # processing_scale: 2, a mono camera's frames are stacked and searched in
    # 2x2 blocks, as the colour camera's always are; 1, at full resolution.
    "imaging": {"camera": "", "processing_scale": 2},
}

# Where ASTAP's installer puts the program and the star database on Windows.
SOLVER_FOLDERS = ("C:/Program Files/astap",)


def _merged(given):
    out = copy.deepcopy(DEFAULTS)
    for section, values in given.items():
        if section in ("cameras", "trains"):
            continue                       # tables of tables: _profiles() reads them whole
        if isinstance(values, dict):
            out.setdefault(section, {}).update(values)
        else:
            out[section] = values
    return _profiles(out, given)


# --- cameras and light paths (docs/mono-upgrade.md, item 0) ----------------------
#
# A camera profile is one [cameras.NAME] table: how the camera is recognised
# (`model`, part of the name Altair's library reports, the profile's own name
# when left out; or `serial`), whether it is mono or cooled, its sensor and
# its settings. A train is one [trains.NAME] table: one light path, naming its
# camera, the corrector's factor (0.9, or none), whether a filter wheel is in
# it, and the `setup` its flats are filed under. The camera in use is the one
# plugged in, matched to a profile when it opens (altair.py), or the one
# named by --camera (TY_CAMERA) or [imaging] camera. The old single [camera]
# table is the 183c profile, so a config.toml written before stays as it was.
# After resolving, cfg["camera"] is the camera in use's profile and
# cfg["train"] its train, so everything that read [camera] reads the right one.

LEGACY_CAMERA = "183c"
# Settings that are about this computer rather than a camera: a profile that
# does not give its own takes the 183c's ([camera]'s).
SHARED_CAMERA = ("backend", "driver")
REMEMBERED_CAMERA = Path("cache") / "camera-in-use.json"      # under DATA


def remembered_camera():
    """The profile the last camera Altair's library opened matched (altair.py
    keeps it in cache/camera-in-use.json); None when none is remembered."""
    import json
    try:
        return json.loads((DATA / REMEMBERED_CAMERA).read_text(encoding="utf-8")).get("camera")
    except (OSError, ValueError, AttributeError):
        return None


def _profiles(out, given):
    """Adds cfg["cameras"], cfg["trains"], cfg["train"] and makes cfg["camera"]
    the profile of the camera in use."""
    legacy = dict(out["camera"])
    cameras = {LEGACY_CAMERA: legacy}
    for name, table in (given.get("cameras") or {}).items():
        if not isinstance(table, dict):
            continue
        if name == LEGACY_CAMERA:
            base = legacy
        else:
            base = dict(DEFAULTS["camera"], **{k: legacy[k] for k in SHARED_CAMERA if k in legacy})
        cameras[name] = dict(base, **table)
    for name, profile in cameras.items():
        profile["name"] = name
    trains = {}
    for name, table in (given.get("trains") or {}).items():
        if isinstance(table, dict):
            owner = cameras.get(table.get("camera", LEGACY_CAMERA), legacy)
            trains[name] = dict({"camera": LEGACY_CAMERA, "corrector": None, "filterwheel": False,
                                 "setup": owner.get("setup", "default")}, **table, name=name)
    asked = os.environ.get("TY_CAMERA") or str(out.get("imaging", {}).get("camera") or "").strip()
    if asked and asked not in cameras:
        raise SystemExit(f"There is no camera profile called {asked!r}. Profiles: {', '.join(sorted(cameras))}.")
    remembered = remembered_camera() if len(cameras) > 1 else None
    remembered = remembered if remembered in cameras else None
    using = asked or remembered or LEGACY_CAMERA
    out["cameras"], out["trains"] = cameras, trains
    out = using_camera(using, out)
    out["camera"]["chosen_by"] = ("--camera" if os.environ.get("TY_CAMERA") else "setting" if asked
                                  else "remembered" if remembered and using == remembered else "default")
    return out


def using_camera(name, cfg):
    """`cfg` with camera `name`'s profile as cfg["camera"] and its train as
    cfg["train"]: the profile's own `train`, else the one train naming it,
    else the camera straight on the telescope with no corrector or wheel."""
    cameras, trains = cfg["cameras"], cfg["trains"]
    profile = dict(cameras[name])
    its = sorted(t for t in trains if trains[t]["camera"] == name)
    if not profile.get("train") and len(its) > 1:
        raise SystemExit(f"The {name} is in {len(its)} trains ({', '.join(its)}): say which it is on now "
                         f"with train = \"...\" in its camera table.")
    train_name = profile.get("train") or (its[0] if its else None)
    if train_name and train_name not in trains:
        raise SystemExit(f"The {name} profile names the train {train_name!r}, which has no [trains.{train_name}].")
    train = dict(trains[train_name]) if train_name else {
        "name": name, "camera": name, "corrector": None, "filterwheel": False,
        "setup": profile.get("setup", "default")}
    profile["setup"] = train["setup"]        # flats are filed under the train's setup
    return dict(cfg, camera=profile, train=train)


def focal_length(cfg=None):
    """The light path's effective focal length in mm: [scope] focal_length_mm
    (the 150P's 750) times the train's corrector factor (0.9 for the coma
    corrector: 675)."""
    cfg = cfg or hardware()
    factor = (cfg.get("train") or {}).get("corrector") or 1.0
    return cfg["scope"]["focal_length_mm"] * float(factor)


def scale(cfg=None, block=1):
    """Arcseconds per pixel of the camera in use through its train; `block`
    2 for the pipeline's 2x2 frames."""
    cfg = cfg or hardware()
    return 206.265 * block * cfg["camera"]["pixel_size_um"] / focal_length(cfg)


def camera_name(cfg=None):
    """The profile name of the camera in use."""
    return (cfg or hardware())["camera"].get("name", LEGACY_CAMERA)


def match_camera(model, serial=None, cfg=None):
    """The profile a camera the library reports belongs to: its `serial`
    when the profile gives one, else its `model` (the profile's own name when
    left out) as part of the reported name, ignoring case. None when no
    profile, or more than one, matches."""
    cameras = (cfg or hardware())["cameras"]
    found = []
    for name, profile in cameras.items():
        if profile.get("serial"):
            if serial and str(profile["serial"]) == str(serial):
                found.append(name)
        elif str(profile.get("model") or name).lower() in str(model).lower():
            found.append(name)
    return found[0] if len(found) == 1 else None


def camera_folder(name=None, cfg=None):
    """Where what is kept for one camera lives: darks and flats, focus
    positions, readout and lost-frame records, patrol references and their
    zero points. DATA/NAME; the 183c's stay where they always were (the data
    folder's own cache/, calibration/ and reference/) until
    ./cameras.py move-183c has moved them under 183c/."""
    name = name or camera_name(cfg)
    folder = DATA / name
    if name == LEGACY_CAMERA and not folder.is_dir():
        return DATA
    return folder


def _read(path):
    with path.open("rb") as f:
        return tomllib.load(f)


# A spot is one place in the garden the telescope is set up: the site is the
# same, but what is in the way is not. Each has its own settings file,
# spots/NAME.toml (its [horizon]: blocked directions, lowest altitude), laid
# over config.toml's, and its own measured skyline (horizon.py, panorama.py).
# [site] spot in config.toml says where the telescope stands tonight; with
# none named it is as it always was: config.toml's [horizon] and
# cache/horizon.json.
SPOTS = ROOT / "spots"
NAME = r"[a-z0-9][a-z0-9_-]{0,30}"


def _spot():
    if DEMO or not FILE.exists():
        return None
    name = _read(FILE).get("site", {}).get("spot") or None
    if name and not re.fullmatch(NAME, name):
        sys.exit(f"[site] spot in {FILE.name} is lower-case letters, digits, - and _ (it names a file): not {name!r}")
    return name


SPOT = _spot()


def spot_file(name):
    return SPOTS / f"{name}.toml"


def spots():
    """The spots that have settings, in order."""
    return sorted(p.stem for p in SPOTS.glob("*.toml"))


def load():
    """Everything, including the observing site. Needs config.toml; the demo
    uses the example site instead."""
    if DEMO:
        return example()
    if not FILE.exists():
        raise SystemExit("No config.toml. Copy config.example.toml to config.toml "
                         "and put your own location in it.")
    cfg = _merged(_read(FILE))
    if SPOT and spot_file(SPOT).exists():
        for section, values in _read(spot_file(SPOT)).items():
            cfg.setdefault(section, {}).update(values)
    if cfg["horizon"]["use_survey"]:
        # The skyline measured from where this telescope stands (horizon.py,
        # panorama.py). The example site has none: it is not that garden.
        import horizon
        cfg["horizon"]["skyline"] = horizon.measured().get("skyline", [])
    return cfg


def hardware():
    """Equipment settings only; works without a config.toml. The demo's
    equipment is the example's, whatever is plugged in for real."""
    return _merged(_read(FILE) if FILE.exists() and not DEMO else _read(EXAMPLE))


def example():
    """The placeholder site shipped with the project, for the demo mode."""
    return _merged(_read(EXAMPLE))


def solver(cfg=None):
    """The plate solver's program and the folder holding its star database.
    config.toml's [solver] section wins. Otherwise, on Linux, astap_cli and
    /opt/astap; on Windows, astap_cli.exe from PATH or from where ASTAP's
    installer puts it, with the database in the same folder."""
    given = (cfg or hardware()).get("solver", {})
    program, database = given.get("program"), given.get("database")
    if sys.platform != "win32":
        return {"program": program or "astap_cli", "database": database or "/opt/astap"}
    if not program:
        found = shutil.which("astap_cli")
        installed = [Path(folder) / "astap_cli.exe" for folder in SOLVER_FOLDERS]
        program = found or str(next((p for p in installed if p.exists()), installed[0]))
    if not database:
        beside = Path(shutil.which(program) or program).parent
        database = str(beside)
    return {"program": program, "database": database}


def field_height(cfg=None):
    """Height of the camera's view of the sky, in degrees: the camera in
    use's sensor through its train's focal length."""
    import math
    cfg = cfg or hardware()
    sensor_mm = cfg["camera"]["height"] * cfg["camera"]["pixel_size_um"] / 1000
    return math.degrees(sensor_mm / focal_length(cfg))


# --- changing the settings from the application ----------------------------------
#
# Each setting the application can change: (section, key, label, kind, help,
# limits). Kinds: "text", "number", "whole", "choice", "yesno". A setting
# marked optional may be left blank, which leaves it to its default.

SETTINGS = (
    ("site", "name", "Name of the site", "text", "Shown at the top of the window and on the report.", {}),
    ("site", "latitude", "Latitude", "number", "Decimal degrees, north positive. A postcode's centre is accurate enough.",
     {"min": -90, "max": 90}),
    ("site", "longitude", "Longitude", "number", "Decimal degrees; west is negative.", {"min": -180, "max": 180}),
    ("site", "elevation_m", "Height above sea level", "number", "Metres.", {"min": -500, "max": 9000}),
    ("site", "timezone", "Time zone", "text", "Such as Europe/London.", {"timezone": True}),
    ("site", "sqm", "Sky brightness", "number",
     "Mag/arcsec² at the zenith, if you have measured it. Blank looks it up in the light pollution atlas.",
     {"min": 15, "max": 23, "optional": True}),
    ("horizon", "min_altitude", "Lowest height worth pointing at", "number", "Degrees above the horizon.",
     {"min": 0, "max": 80}),
    ("horizon", "use_survey", "Use the measured skyline", "yesno",
     "The skyline from a phone panorama or the telescope's own survey, on the Horizon screen. Off leaves "
     "only the blocked list written in config.toml.", {}),
    ("horizon", "margin", "Margin above the measured skyline", "number",
     "Degrees. One branch is enough to spoil a frame, so targets are kept this far above what was measured.",
     {"min": 0, "max": 20}),
    ("mount", "feet_apart_cm", "Distance between two tripod feet", "number",
     "Centimetres, from one foot to the next. With it, a turn of the whole tripod is also given as how far "
     "each foot moves. Blank leaves that out.", {"min": 20, "max": 400, "optional": True}),
    ("mount", "tripod_cm_per_degree", "Tripod: centimetres per degree", "number",
     "How far a foot moved for each degree the whole tripod turned, measured during polar alignment. "
     "Used in place of the feet's spacing when given.", {"min": 0.1, "max": 20, "optional": True}),
    ("mount", "latitude_degrees_per_mark", "Latitude scale: degrees per mark", "number",
     "What one mark on the mount's latitude scale is worth, measured during polar alignment. With it, "
     "raising or lowering the axis is also said in marks.", {"min": 0.2, "max": 10, "optional": True}),
    ("mount", "nudge_check", "Motor check at setup (the nudge)", "yesno",
     "A step of the setup routine: from home the tube tips 5° and back while you watch, to see that the "
     "motors really turn (on 6 October 2026 they stalled while the handset said they had moved). Off: the "
     "routine goes from asking where it is clear straight to focus. ./mount.py nudge still works when asked for.",
     {}),
    ("scope", "aperture_mm", "Aperture", "number", "Millimetres.", {"min": 10, "max": 2000}),
    ("scope", "focal_length_mm", "Focal length", "number",
     "Millimetres, the telescope's own (750 for the 150P). A light path with a corrector ([trains.NAME] corrector, "
     "0.9 for the coma corrector) multiplies it; the plate solver, the framing and every scale use the result "
     "with the sensor of the camera in use.", {"min": 50, "max": 20000}),
    ("camera", "backend", "Camera read through", "choice",
     "indi: the INDI driver (Linux). altair: Altair's own library, the only way on Windows. Blank: the usual one for this system.",
     {"choices": ["indi", "altair"], "optional": True}),
    ("camera", "driver", "INDI driver", "text", "Used when the camera is read through INDI.", {}),
    ("camera", "bit_depth", "Sensor bit depth", "whole", "", {"min": 8, "max": 16}),
    ("camera", "pixel_size_um", "Pixel size", "number", "Micrometres.", {"min": 0.5, "max": 30}),
    ("camera", "width", "Sensor width", "whole", "Pixels.", {"min": 100, "max": 20000}),
    ("camera", "height", "Sensor height", "whole", "Pixels.", {"min": 100, "max": 20000}),
    ("camera", "offset", "Black level (offset)", "whole",
     "Raised above zero so the faintest signal is not cut off. 46 gives the Altair 183C a level of about 45 "
     "with the cap on; at 0 it reads about 1 and the sky's grain is clipped. Take a new bias after changing it.",
     {"min": 0, "max": 255, "optional": True}),
    ("camera", "readout_speed", "Readout speed", "whole",
     "0 is the slowest. On 23 October 2026 the Altair 183C lost long frames at 1 and 2 and kept them at 0; "
     "camera_test.py --speed-ladder finds the fastest that keeps them. Blank leaves the driver's own.",
     {"min": 0, "max": 3, "optional": True}),
    ("cameras.183m", "tec_target", "183M cooler target", "number",
     "°C, one fixed value for the season so one set of darks serves (0 is the first guess for winter). Set each "
     "time the 183M opens, through Altair's own library; a run keeps no frames until the sensor is within 1 °C of "
     "it, each frame says the sensor temperature (CCD-TEMP), this target (SET-TEMP), the cooler's power and whether "
     "it was within 0.5 °C (TY_ONTGT), and the end of a run warms the sensor 3 °C a minute before the cooler goes "
     "off. A cooler at full power that cannot reach it stops the run and says so. Blank leaves the cooler as it is.",
     {"min": -40, "max": 30, "optional": True}),
    ("imaging", "camera", "Camera in use", "text",
     "The camera profile ([cameras.NAME] in config.toml: 183c, 183m) to use when both cameras are plugged in. "
     "Blank: the one plugged in, matched to its profile when it opens; a camera with no profile is refused.",
     {"optional": True}),
    ("imaging", "processing_scale", "Processing scale, mono camera", "whole",
     "2: a mono camera's frames are stacked and searched in 2x2 blocks (about 1.5\" a pixel at 675 mm), as the "
     "colour camera's always are; stars here are about eight sensor pixels across, so nothing is lost and the "
     "work is a quarter. 1: full resolution, for corner checks or timing centroids, four times the work and "
     "not yet tried on the sky. The raw frames kept are the full sensor either way.", {"min": 1, "max": 2}),
    ("camera", "setup", "Camera arrangement", "text",
     "A name for how the camera sits on the telescope. Change it, and take new flats, whenever the camera is "
     "rotated or taken off.", {}),
    ("focuser", "travel", "Focuser: furthest a run turns", "whole",
     "Half-steps either way from where a focus run starts, overshoot included; a move beyond it is refused. "
     "The Sharpie line on the drawtube marks focus, so it is always close: on 23 October 2026 a sweep with "
     "no limit left the drawtube about an inch out.", {"min": 64, "max": 8192}),
    ("filterwheel", "filters", "Filter wheel: filters in order", "text",
     "The Starlight Xpress wheel's filters by position, 1 first, separated by commas; leave a gap empty. "
     "sxwheel.py move takes these names, and each frame through a train with the wheel says the position the "
     "wheel confirmed (FILTPOS) and its name (FILTER). Blank: positions by number. Set it only after looking: "
     "./sxwheel.py move 1, then see which filter is in the light path, and so on round.", {"optional": True}),
    ("mount", "link", "Mount reached by", "choice",
     "handset: a serial lead to the SynScan handset. wifi: the SynScan Wi-Fi adapter. eqdir: an EQDIR lead. "
     "The last two have no handset.", {"choices": ["handset", "wifi", "eqdir"]}),
    ("mount", "serial_match", "Serial lead's name contains", "text",
     "Part of the USB adapter's name: FTDI for the usual lead, Prolific for a handset's own USB socket.", {}),
    ("mount", "address", "Wi-Fi adapter's address", "text",
     "Blank finds the adapter by asking the network. It is 192.168.4.1 on the network the adapter makes itself.",
     {"optional": True}),
    ("solver", "program", "Plate solver program", "text", "Blank uses astap_cli where it is usually installed.",
     {"optional": True}),
    ("solver", "database", "Star database folder", "text", "Blank uses the usual place for this system.",
     {"optional": True}),
    ("stream", "enabled", "Stream live while imaging", "yesno",
     "To YouTube, Twitch or both, while a run is imaging (stream.py). The stream keys go in "
     "~/.config/telescopeyoke/ (./stream.py key youtube, ./stream.py key twitch), not here.", {}),
    ("stream", "service", "Streaming service", "choice",
     "Where the live stream goes. youtube+twitch sends the same stream to both at once; one without a key "
     "is left out.",
     {"choices": ["youtube", "twitch", "youtube+twitch", "custom"]}),
    ("stream", "focus_tones", "Focus tones on the stream", "yesno",
     "While the telescope focuses, the stream's sound has a click and a tone for each reading, higher the sharper "
     "the stars, as the focus aid's. Off: the stream stays silent. Takes effect when the stream next starts.", {}),
    ("webcam", "enabled", "Use a webcam at all", "yesno",
     "Off: nothing opens a webcam (the telescope pictures during moves, watch.py and the picture on the pages); "
     "the settings below then do nothing.", {}),
    ("webcam", "watch_moves", "Photograph the telescope during every move", "yesno",
     "A picture a second while the mount moves, for the pages. Needs the webcam on.", {}),
    ("webcam", "show_picture", "Show the telescope picture on the pages", "yesno",
     "The status page and the console show the webcam's latest picture of the telescope. Needs the webcam on.", {}),
    ("webcam", "device", "Webcam", "text",
     "On Windows, the camera's name as ffmpeg lists it. Linux finds one by itself.", {"optional": True}),
    ("webcam", "built_in", "Use the laptop's own webcam", "yesno",
     "Off: only a webcam plugged in watches the telescope, and the laptop's camera light stays off.", {}),
    ("plan", "goals", "Captures keep going to their goal", "yesno",
     "A capture keeps going until it has the frames its programme wants accepted, up to a time cap for camera "
     "stalls and a frame cap for rejections, counted apart (goals.py). Off: frames and minutes as given.", {}),
    ("plan", "windows", "Keep protected steps' start times", "yesno",
     "A step given a start time, an occultation or a transit starts on time with its setup before it, and the "
     "steps before it are timed back from that (windows.py). Off: steps run in order, each to its own time.", {}),
    ("plan", "dispatch", "Choose the next step as the night goes", "yesno",
     "At each step's end the next of tonight's agreed steps is chosen by what is owed and what it would add "
     "(dispatch.py); it never adds a step. Off: the steps run in the order listed.", {}),
    ("plan", "follow_up_share", "Share of the night for uncertain candidates", "number",
     "Second looks at candidates that are not yet strong may take at most this share of the night; strong "
     "ones go first outside it.", {"min": 0, "max": 1}),
    ("indi", "port", "INDI server port", "whole", "", {"min": 1, "max": 65535}),
    ("indi", "manage_server", "Start the INDI server automatically", "yesno",
     "That stops any INDI server already running, so leave it off if other equipment shares one.", {}),
)


def checked(section, key, value):
    """A value from the application, as the right type and within its limits;
    None for an optional setting left blank. Raises ValueError saying what is
    wrong, in words for the person who typed it."""
    found = next((s for s in SETTINGS if s[:2] == (section, key)), None)
    if found is None:
        raise ValueError(f"{section}.{key} is not a setting the application can change.")
    _, _, label, kind, _, limits = found
    if value is None or (isinstance(value, str) and not value.strip()):
        if limits.get("optional"):
            return None
        raise ValueError(f"{label} cannot be blank.")
    if kind == "yesno":
        if not isinstance(value, bool):
            raise ValueError(f"{label} must be yes or no.")
        return value
    if kind in ("number", "whole"):
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{label} must be a number.")
        if number != number or not limits["min"] <= number <= limits["max"]:
            raise ValueError(f"{label} must be between {limits['min']:g} and {limits['max']:g}.")
        if kind == "whole":
            if number != int(number):
                raise ValueError(f"{label} must be a whole number.")
            return int(number)
        return int(number) if number == int(number) and "." not in str(value) else number
    text = str(value).strip()
    if len(text) > 200 or any(ord(c) < 32 for c in text):
        raise ValueError(f"{label} is too long or has characters that cannot be used.")
    if kind == "choice" and text not in limits["choices"]:
        raise ValueError(f"{label} must be one of: {', '.join(limits['choices'])}.")
    if limits.get("timezone"):
        from zoneinfo import ZoneInfo
        try:
            ZoneInfo(text)
        except Exception:
            raise ValueError(f"{text} is not a time zone. Use a name such as Europe/London.")
    return text


def section_of(settings, section):
    """One section of a settings file read as it is, a dotted name
    ("cameras.183m") taken a table at a time; {} when it is not there."""
    for part in section.split("."):
        settings = settings.get(part, {}) if isinstance(settings, dict) else {}
    return settings if isinstance(settings, dict) else {}


def _written(value):
    """A value as it is written in the file."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return repr(value)


def changed_text(text, changes):
    """The settings file's text with some values changed, and everything
    else, every comment included, left as it was. `changes` maps (section,
    key) to a value, or to None to leave the setting to its default."""
    import re
    lines = text.splitlines()
    header = re.compile(r"^\s*(#\s*)?\[([\w.-]+)\]\s*$")     # [camera], [cameras.183m]
    for (section, key), value in changes.items():
        heads = [(i, m) for i, m in ((i, header.match(line)) for i, line in enumerate(lines)) if m]
        at = next((i for i, m in heads if m.group(2) == section and not m.group(1)), None)
        if at is None:
            if value is None:
                continue
            at = next((i for i, m in heads if m.group(2) == section), None)
            if at is None:                       # no such section anywhere: add it at the end
                lines += ["", f"[{section}]"]
                at = len(lines) - 1
            else:                                # there, but commented out: bring it into use
                lines[at] = f"[{section}]"
            heads = [(i, m) for i, m in ((i, header.match(line)) for i, line in enumerate(lines)) if m]
        end = next((i for i, _ in heads if i > at), len(lines))
        setting = re.compile(rf"^\s*(#\s?)?{re.escape(key)}\s*=")
        live = next((i for i in range(at + 1, end) if (m := setting.match(lines[i])) and not m.group(1)), None)
        spare = next((i for i in range(at + 1, end) if (m := setting.match(lines[i])) and m.group(1)), None)
        if value is None:
            if live is not None:
                lines[live] = "# " + lines[live].lstrip()
        elif live is not None:
            lines[live] = f"{key} = {_written(value)}"
        elif spare is not None:
            lines[spare] = f"{key} = {_written(value)}"
        else:
            last = max((i for i in range(at + 1, end) if lines[i].strip() and not lines[i].lstrip().startswith("#")),
                       default=at)
            lines.insert(last + 1, f"{key} = {_written(value)}")
    return "\n".join(lines) + "\n"


def save(changes, path=None):
    """Change settings in config.toml, keeping its comments. The file is made
    from the example if there is none; the old one is kept as config.toml.bak.
    Nothing is written unless the result reads back with every value as asked."""
    path = Path(path or FILE)
    old = path.read_text(encoding="utf-8") if path.exists() else EXAMPLE.read_text(encoding="utf-8")
    new = changed_text(old, changes)
    read_back = tomllib.loads(new)
    for (section, key), value in changes.items():
        if section_of(read_back, section).get(key) != value:
            raise ValueError(f"{section}.{key} could not be written safely; the file was left alone.")
    if path.exists():
        path.with_suffix(".toml.bak").write_text(old, encoding="utf-8")
    partial = path.with_suffix(".toml.part")
    partial.write_text(new, encoding="utf-8")
    partial.replace(path)
    return new
