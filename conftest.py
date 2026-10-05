"""Makes the scripts importable from the tests, and keeps the tests away from
anything real: every file a script keeps (frames, pictures, remembered
measurements, calibration frames) goes to a folder made for this test run.
Worker processes and commands the tests start inherit the setting."""
import os
import tempfile

os.environ["TY_DATA"] = tempfile.mkdtemp(prefix="ty-test-data-")
os.environ["TY_CALIBRATION"] = tempfile.mkdtemp(prefix="ty-no-calibration-")
