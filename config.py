"""Site and equipment settings, read from config.toml."""
import tomllib
from pathlib import Path

ROOT = Path(__file__).parent
FILE = ROOT / "config.toml"


def load():
    if not FILE.exists():
        raise SystemExit("No config.toml. Copy config.example.toml to config.toml "
                         "and put your own location in it.")
    with FILE.open("rb") as f:
        return tomllib.load(f)
