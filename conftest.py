"""Makes the scripts importable from the tests, and keeps the tests away from
anything real: every file a script keeps (frames, pictures, remembered
measurements, calibration frames) goes to a folder made for this test run.
Worker processes and commands the tests start inherit the setting."""
import os
import tempfile
from pathlib import Path

import pytest

os.environ["TY_DATA"] = tempfile.mkdtemp(prefix="ty-test-data-")
os.environ["TY_CALIBRATION"] = tempfile.mkdtemp(prefix="ty-no-calibration-")


@pytest.fixture(autouse=True)
def nothing_left_on_air():
    """A focus run or a polar alignment that one test leaves in its stream
    file would put a later test's stream on air (stream.broadcasting)."""
    yield
    cache = Path(os.environ["TY_DATA"]) / "cache"
    for name in ("focus_stream.json", "polar_stream.json"):
        (cache / name).unlink(missing_ok=True)
