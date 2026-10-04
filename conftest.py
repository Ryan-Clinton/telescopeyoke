"""Makes the scripts importable from the tests, and keeps the tests away from
any real calibration frames: worker processes inherit this setting."""
import os
import tempfile

os.environ["TY_CALIBRATION"] = tempfile.mkdtemp(prefix="ty-no-calibration-")
