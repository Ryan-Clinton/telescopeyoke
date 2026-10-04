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
    "mount": {"serial_match": "FTDI"},
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
