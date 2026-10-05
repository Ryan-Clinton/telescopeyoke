"""Site and equipment settings, read from config.toml."""
import copy
import shutil
import sys
import tomllib
from pathlib import Path

import host  # noqa: F401  (every script passes through here: makes output UTF-8)

ROOT = Path(__file__).parent
FILE = ROOT / "config.toml"
EXAMPLE = ROOT / "config.example.toml"

# Used for anything config.toml leaves out. These describe the hardware the
# project was built with, so an older config.toml keeps working.
DEFAULTS = {
    "horizon": {"min_altitude": 20, "blocked": []},
    "scope": {"aperture_mm": 150, "focal_length_mm": 750},
    "camera": {"driver": "indi_altair_ccd", "bit_depth": 12, "pixel_size_um": 2.4,
               "width": 5440, "height": 3648, "setup": "default",
               # How frames are fetched: through the INDI driver, or straight
               # from Altair's own library. INDI does not run on Windows.
               "backend": "altair" if sys.platform == "win32" else "indi"},
    # link: "handset" (a serial lead to the SynScan handset), or with no handset
    # "wifi" (the SynScan Wi-Fi adapter) or "eqdir" (an EQDIR lead).
    "mount": {"serial_match": "FTDI", "link": "handset"},
    "indi": {"port": 7624, "manage_server": False},
}

# Where ASTAP's installer puts the program and the star database on Windows.
SOLVER_FOLDERS = ("C:/Program Files/astap",)


def _merged(given):
    out = copy.deepcopy(DEFAULTS)
    for section, values in given.items():
        if isinstance(values, dict):
            out.setdefault(section, {}).update(values)
        else:
            out[section] = values
    return out


def _read(path):
    with path.open("rb") as f:
        return tomllib.load(f)


def load():
    """Everything, including the observing site. Needs config.toml."""
    if not FILE.exists():
        raise SystemExit("No config.toml. Copy config.example.toml to config.toml "
                         "and put your own location in it.")
    return _merged(_read(FILE))


def hardware():
    """Equipment settings only; works without a config.toml."""
    return _merged(_read(FILE) if FILE.exists() else {})


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
    """Height of the camera's view of the sky, in degrees."""
    import math
    cfg = cfg or hardware()
    sensor_mm = cfg["camera"]["height"] * cfg["camera"]["pixel_size_um"] / 1000
    return math.degrees(sensor_mm / cfg["scope"]["focal_length_mm"])


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
    ("scope", "aperture_mm", "Aperture", "number", "Millimetres.", {"min": 10, "max": 2000}),
    ("scope", "focal_length_mm", "Focal length", "number",
     "Millimetres. The plate solver works out the field of view from this and the sensor.", {"min": 50, "max": 20000}),
    ("camera", "backend", "Camera read through", "choice",
     "indi: the INDI driver (Linux). altair: Altair's own library, the only way on Windows. Blank: the usual one for this system.",
     {"choices": ["indi", "altair"], "optional": True}),
    ("camera", "driver", "INDI driver", "text", "Used when the camera is read through INDI.", {}),
    ("camera", "bit_depth", "Sensor bit depth", "whole", "", {"min": 8, "max": 16}),
    ("camera", "pixel_size_um", "Pixel size", "number", "Micrometres.", {"min": 0.5, "max": 30}),
    ("camera", "width", "Sensor width", "whole", "Pixels.", {"min": 100, "max": 20000}),
    ("camera", "height", "Sensor height", "whole", "Pixels.", {"min": 100, "max": 20000}),
    ("camera", "setup", "Camera arrangement", "text",
     "A name for how the camera sits on the telescope. Change it, and take new flats, whenever the camera is "
     "rotated or taken off.", {}),
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
    ("webcam", "device", "Webcam", "text",
     "On Windows, the camera's name as ffmpeg lists it. Linux finds one by itself.", {"optional": True}),
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
    header = re.compile(r"^\s*(#\s*)?\[(\w+)\]\s*$")
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
        if read_back.get(section, {}).get(key) != value:
            raise ValueError(f"{section}.{key} could not be written safely; the file was left alone.")
    if path.exists():
        path.with_suffix(".toml.bak").write_text(old, encoding="utf-8")
    partial = path.with_suffix(".toml.part")
    partial.write_text(new, encoding="utf-8")
    partial.replace(path)
    return new
