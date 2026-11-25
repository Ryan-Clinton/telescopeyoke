"""DIAGNOSTIC, NOT A VERDICT: clip533 with each layer a plain mean of its frames (no rejection), to see whether the stack's rejection takes the stars' light."""
"""Raw 2600MC Pro frames at 1000 mm (a Bortle 2 archive): the restack cleaning against no cleaning, by the pass mark
fixed on 24 November, as protocol step 1 on a colour camera (deviation 4, the harness only).

Each frame: its night's flat (median of its 20 flats, each Bayer site normalised on its own) divided out, no dark or
bias (none in the archive; the sensor has little glow), split into its colour pixels as camera.colour does, and the
green channel tested, as restack cleans each channel. Sessions, fixed before any was measured: for each target the
first night with at least 20 lights, up to 40 frames. Copies only.
"""
import json
import sys
from multiprocessing import Pool
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, ".")
import numpy as np
from astropy.io import fits

import clip
import clip13
import clip14rule  # noqa: F401  after clip13: the shipped rule, third neighbour at 40%
import stacking

ROOT = Path("/mnt/d/telescopyokearchive/training-data/raw-533mc/lights")
NIGHTS = {"Abell1656": "Abell1656_3/RGB/NIGHT_1", "LBN552": "LBN552/RGB", "M81": "M81_3/RGB/NIGHT_1",
          "NGC7293": "NGC7293_2/RGB"}
_flats = {}


def flat_for(night):
    if night not in _flats:
        f = np.median(np.stack([fits.getdata(p).astype(np.float32) for p in sorted((ROOT / night / "FLAT").glob("*.fits"))]), axis=0)
        for dy in (0, 1):
            for dx in (0, 1):
                f[dy::2, dx::2] /= np.median(f[dy::2, dx::2])
        _flats[night] = f
    return _flats[night]


def night_of(path):
    real = Path(path).resolve()
    return str(real.parent.parent.relative_to(ROOT))


def base(path, exposure, gain):
    raw = fits.getdata(Path(path).resolve()).astype(np.float32)
    cal = raw / np.clip(flat_for(night_of(path)), .2, None)
    return stacking.colour(stacking.destripe(cal), mono=False)[..., 1].astype(np.float32)


def load_light(path):
    with fits.open(Path(path).resolve()) as h:
        return h[0].data.astype(np.float32), h[0].header


clip.base = base
stacking.load_light = load_light


def prepare(name, night):
    files = sorted((ROOT / night / "LIGHT").glob("*.fits"))[:40]
    d = clip.WORK / "input" / f"raw533-{name}"
    d.mkdir(parents=True, exist_ok=True)
    for i, p in enumerate(files):
        link = d / f"light-{i:04d}.fits"
        if not link.exists():
            link.symlink_to(p)
    return f"raw533-{name}"


def plain_mean(cube):
    """Diagnostic: every frame averaged, no reference and no rejection."""
    return np.nan_to_num(np.nanmean(np.stack([c.astype(np.float32) for c in cube]), axis=0))   # zero where no frame reached, as Stack.result() writes


if __name__ == "__main__":
    clip13.restacked = plain_mean
    NIGHTS = {"Abell1656": NIGHTS["Abell1656"]}
    for night in NIGHTS.values():
        flat_for(night)
    with Pool(3) as pool, open(clip.WORK / "clipmean.jsonl", "a") as log:
        for name, night in NIGHTS.items():
            session = prepare(name, night)
            try:
                row = clip13.check(session, pool)
            except Exception as e:
                import traceback
                row = {"session": session, "error": repr(e)[:400], "where": traceback.format_exc()[-1500:]}
                print(row["where"], flush=True)
            log.write(json.dumps(row) + "\n"); log.flush()
            c = row.get("honest", {})
            print(session, "cosmic visible", c.get("robust", {}).get("cosmic"), "against",
                  c.get("current", {}).get("cosmic"), row.get("error", ""), flush=True)
