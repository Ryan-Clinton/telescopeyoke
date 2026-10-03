"""Site and equipment settings, read from config.toml."""
import copy
import tomllib
from pathlib import Path

ROOT = Path(__file__).parent
FILE = ROOT / "config.toml"
EXAMPLE = ROOT / "config.example.toml"

# Used for anything config.toml leaves out. These describe the hardware the
# project was built with, so an older config.toml keeps working.
DEFAULTS = {
    "horizon": {"min_altitude": 20, "blocked": []},
    "scope": {"aperture_mm": 150, "focal_length_mm": 750},
    "camera": {"driver": "indi_altair_ccd", "bit_depth": 12, "pixel_size_um": 2.4,
               "width": 5440, "height": 3648},
    "mount": {"serial_match": "FTDI"},
    "indi": {"port": 7624, "manage_server": False},
}


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


def field_height(cfg=None):
    """Height of the camera's view of the sky, in degrees."""
    import math
    cfg = cfg or hardware()
    sensor_mm = cfg["camera"]["height"] * cfg["camera"]["pixel_size_um"] / 1000
    return math.degrees(sensor_mm / cfg["scope"]["focal_length_mm"])
