"""Set 76 (QHY Minicam8M, 600 s Ha and OIII): the restack cleaning against no cleaning, by the pass mark fixed on
24 November, as protocol step 1 (docs/research/free-tools-2026-11-23/confirmation-protocol.md).

Deviation, the harness only: this camera has no darks in our library, so each frame is calibrated by the set's own
master bias (median of its 100 bias frames) and its own flat for that filter (median of the 10, bias taken off,
normalised), then destriped and binned exactly as clip.base does. Nothing in the cleaning is changed. Sessions, fixed
before any was measured: for each filter the first and the last night with at least 20 frames of 600 s, up to 40 frames each.
Copies only: the set's files are read, never changed.
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
import clip14rule  # noqa: F401  after clip13, whose clip12 import it overrides: the shipped rule, third neighbour at 40%
import stacking

SET = Path("/mnt/d/telescopyokearchive/training-data/discord/76-NGC6888-raw")
SESSIONS = {"Ha": ("2025-10-10", "2025-11-02"), "OIII": ("2025-10-10", "2025-10-29")}
_bias = None
_flats = {}


def bias():
    global _bias
    if _bias is None:
        _bias = np.median(np.stack([fits.getdata(p).astype(np.float32) for p in sorted((SET / "bias").glob("*.fits"))]), axis=0)
    return _bias


def flat(name):
    if name not in _flats:
        tag = "OIII 7" if name.startswith("OIII") else name
        f = np.median(np.stack([fits.getdata(p).astype(np.float32) - bias() for p in sorted((SET / "FLATS").glob(f"*_{tag}_*.fits"))]), axis=0)
        _flats[name] = f / np.median(f)
    return _flats[name]


def base(path, exposure, gain):
    raw = fits.getdata(path).astype(np.float32)
    name = "OIII" if "_OIII" in Path(path).name else "Ha"
    cal = (raw - bias()) / np.clip(flat(name), .2, None)
    return stacking.colour(stacking.destripe(cal), mono=True, block=stacking.PROCESSING_SCALE)[..., 0].astype(np.float32)


clip.base = base


def load_light(path):
    """Another camera's frames keep the image in the primary HDU, ours in the second."""
    with fits.open(path) as h:
        return h[0].data.astype(np.float32), h[0].header


stacking.load_light = load_light


def prepare(name, night):
    tag = "_OIII" if name == "OIII" else "_Ha_"
    files = sorted(p for p in (SET / "lights").glob(f"{night}_*.fits") if tag in p.name and "_600.00s_" in p.name)[:40]
    d = clip.WORK / "input" / f"set76b-{name}-{night}"
    d.mkdir(parents=True, exist_ok=True)
    for i, p in enumerate(files):
        link = d / f"light-{i:04d}.fits"
        if not link.exists():
            link.symlink_to(p)
    return f"set76b-{name}-{night}"


if __name__ == "__main__":
    only = sys.argv[1:]
    bias(); [flat(n) for n in SESSIONS]   # made once, before the workers fork
    with Pool(3) as pool, open(clip.WORK / "clip76.jsonl", "a") as log:
        for name, nights in SESSIONS.items():
            for night in nights:
                if only and f"{name}-{night}" not in only:
                    continue
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
