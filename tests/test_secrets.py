"""The user's own settings never reach the repository.

On 18 October 2026 config.toml.bak, the copy config.save() keeps, was
committed with the Telegram token and the garden's latitude and longitude in
it. These fail before a commit can carry either again."""
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def tracked():
    if not (ROOT / ".git").exists():
        pytest.skip("not a git checkout (the desktop's test copy)")
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    return out.stdout.splitlines()


def test_no_copy_of_the_settings_is_tracked():
    kept = [f for f in tracked() if Path(f).name.startswith("config.toml") or f.endswith(".bak")]
    assert kept == []


@pytest.mark.parametrize("name", ["config.toml", "config.toml.bak", "rigs/garden.toml.bak"])
def test_the_settings_and_their_copies_are_ignored(name):
    tracked()
    assert subprocess.run(["git", "check-ignore", "-q", name], cwd=ROOT).returncode == 0
