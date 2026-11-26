"""DIAGNOSTIC: in Abell 1656's light-0008 (a frame the shipped rule takes 17% from), the pixels the rule
replaces inside the 30 brightest stars, each with its 5 by 5 neighbourhood, the local median, the
7x7 background and the threshold, to see why a star core passes for a lone hit."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, ".")
import numpy as np
from scipy import ndimage as N

import clipmean
import clip
import clip14rule
import stacking

name = clipmean.prepare("Abell1656", clipmean.NIGHTS["Abell1656"])
clipmean.flat_for(clipmean.NIGHTS["Abell1656"])
p = clip.WORK / "input" / name / "light-0008.fits"
_, header = stacking.load_light(p)
x = clip.base(p, float(header["EXPTIME"]), int(float(header["GAIN"])))
out = clip14rule.pair_aware(x)
changed = out != x
local = N.median_filter(x, 3); s = 1.4826 * np.median(np.abs(x - local)) + 1e-6
back = N.median_filter(x, 7); third = N.rank_filter(x, rank=-3, footprint=clip.RING) - back
stars = stacking.find_stars(x, limit=300)
np.set_printoptions(linewidth=160, precision=0, suppress=True)
shown = 0
for sx, sy, flux, fw, rd in stars[:60]:
    r, c = int(round(sy)), int(round(sx))
    box = changed[r - 3:r + 4, c - 3:c + 4]
    if not box.any():
        continue
    ys, xs = np.nonzero(box)
    print(f"star at {c},{r} flux {flux:.0f} fwhm {fw:.2f} round {rd:.2f}: {len(ys)} pixel(s) replaced; spread {s:.1f}")
    for dy, dx in zip(ys, xs):
        a, b = r - 3 + dy, c - 3 + dx
        print(f"  pixel {b},{a}: value-back {x[a,b]-back[a,b]:.0f} value-local {x[a,b]-local[a,b]:.0f} third-back {third[a,b]:.0f} "
              f"limit {max(0.4*(x[a,b]-back[a,b]), 3*s):.0f}")
    print((x[r - 2:r + 3, c - 2:c + 3] - back[r, c]))
    shown += 1
    if shown >= 6:
        break
print("stars with a replaced pixel within 3 px, of the brightest 60:",
      sum(changed[int(round(y)) - 3:int(round(y)) + 4, int(round(x0)) - 3:int(round(x0)) + 4].any() for x0, y in stars[:60, :2]))
