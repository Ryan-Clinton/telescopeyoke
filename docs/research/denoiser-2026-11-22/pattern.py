"""What is the pattern fixed to the sensor in calibrated frames?"""
import json
import sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, ".")
import numpy as np
from PIL import Image
from scipy import ndimage as N

import stacking

OUT = Path(__file__).parent
SESSIONS = ("NGC2174/20261120-014420", "IC405/20261121-211523", "IC405/20261122-001737", "M33/20261105-001232")


def fine(x):
    return x - N.median_filter(x, size=9)


def one(job):
    path, exposure, gain = job
    mosaic, header = stacking.load_light(Path(path))
    x = stacking.prepare(mosaic, stacking._calibration(exposure, gain, stacking.worker_cards(header)),
                         mono=True)[..., 0].astype(np.float32)
    d = fine(x)
    s = 1.4826 * np.median(np.abs(d[::3, ::3]))
    d[N.binary_dilation(np.abs(d) > 3.5 * s, iterations=3)] = np.nan
    return d / s      # in units of each frame's own noise


def block(x):
    h, w = x.shape[0] // 2, x.shape[1] // 2
    return x[:2 * h, :2 * w].reshape(h, 2, w, 2).mean(axis=(1, 3)).astype(np.float32)


def rho(a, b, shift=(0, 0)):
    b = np.roll(b, shift, axis=(0, 1))
    use = np.isfinite(a) & np.isfinite(b)
    use[:40] = use[-40:] = False
    use[:, :40] = use[:, -40:] = False
    return float(np.corrcoef(a[use][::3], b[use][::3])[0, 1])


def without_lines(x):
    x = x - np.nanmedian(x, axis=1, keepdims=True)
    return x - np.nanmedian(x, axis=0, keepdims=True)


def check(name, pool):
    session = Path("frames") / name
    found = stacking.one_setting(stacking.on_target(sorted(session.glob("light-*.fits")), lambda *_: None),
                                 lambda *_: None)
    found = found[:: max(1, len(found) // 32)][:32]
    _, header = stacking.load_light(found[0])
    exposure, gain = float(header["EXPTIME"]), int(float(header["GAIN"]))
    c = stacking.Calibration(exposure, gain, header)
    maps = pool.map(one, [(str(p), exposure, gain) for p in found])
    a = np.nanmean(np.stack(maps[::2]), axis=0)
    b = np.nanmean(np.stack(maps[1::2]), axis=0)
    both = (a + b) / 2
    limit = 3 * np.nanstd(both)
    clip = lambda x: np.where(np.abs(both) < limit, x, np.nan)
    dark, flat = fine(block(c.dark)), fine(block(c.flat))
    use = np.isfinite(both)
    design = np.column_stack([dark[use], flat[use]])
    design = (design - design.mean(0)) / design.std(0)
    fit, *_ = np.linalg.lstsq(design[::3], both[use][::3] - np.nanmean(both), rcond=None)
    ra, rb = a.copy(), b.copy()
    ra[use] -= design @ fit
    rb[use] -= design @ fit
    worst = np.abs(both[use])
    top = np.nanpercentile(worst, 99)
    result = {"session": name, "filter": str(header.get("FILTER")), "seconds": exposure, "frames": len(found),
              "same_place": round(rho(a, b), 3),
              "shifted_1px": round(rho(a, b, (0, 1)), 3), "shifted_25px": round(rho(a, b, (25, 25)), 3),
              "without_outliers": round(rho(clip(a), clip(b)), 3),
              "without_rows_columns": round(rho(without_lines(a), without_lines(b)), 3),
              "with_dark": round(rho(both, dark), 3), "with_flat": round(rho(both, flat), 3),
              "after_removing_dark_flat": round(rho(ra, rb), 3),
              "share_of_variance_in_top_1pct": round(float((worst[worst > top] ** 2).sum() / (worst ** 2).sum()), 3)}
    crop = both[700:1100, 1100:1700]
    Image.fromarray((np.clip(np.nan_to_num(crop) / (3 * np.nanstd(crop)) * .5 + .5, 0, 1) * 255).astype(np.uint8)).resize(
        (1200, 800), Image.NEAREST).save(OUT / f"pattern-{name.replace('/', '-')}.png")
    return result


if __name__ == "__main__":
    with Pool(8) as pool:
        for name in SESSIONS:
            print(json.dumps(check(name, pool)), flush=True)
