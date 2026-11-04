"""Panel 8 diagnosis: is each candidate a point above its own surroundings,
or a noise peak on a raised patch of the significance map?"""
import json, sys
import numpy as np
from astropy.io import fits
from scipy import ndimage
diff, cands = sys.argv[1], sys.argv[2]
sig = np.nan_to_num(fits.getdata(diff).astype(float))
c = json.load(open(cands))["candidates"]
# The significance map's broad level: median over 96 px squares (stars, candidates negligible).
small = ndimage.median_filter(sig[::4, ::4], 24, mode="nearest")
level = ndimage.zoom(small, (sig.shape[0] / small.shape[0], sig.shape[1] / small.shape[1]), order=1)[:sig.shape[0], :sig.shape[1]]
spread_small = ndimage.median_filter(np.abs(sig[::4, ::4] - small), 24, mode="nearest") * 1.4826
spread = ndimage.zoom(spread_small, (sig.shape[0] / small.shape[0], sig.shape[1] / small.shape[1]), order=1)[:sig.shape[0], :sig.shape[1]]
valid = sig != 0
print(f"whole map: broad level median {np.median(level[valid]):+.2f}, 99th pct {np.percentile(level[valid], 99):+.2f}; "
      f"spread median {np.median(spread[valid]):.2f}, 99th pct {np.percentile(spread[valid], 99):.2f}")
above_level = []
for k in c:
    x, y = k["x"], k["y"]
    lv, sp = level[y, x], spread[y, x]
    # The candidate's width: pixels above half its peak, connected to it.
    patch = sig[max(y-10,0):y+11, max(x-10,0):x+11]
    lab, _ = ndimage.label(patch > k["score"] / 2)
    area = int((lab == lab[min(y,10), min(x,10)]).sum())
    local = (k["score"] - lv) / sp
    above_level.append(local)
    print(f"  x {x:4d} y {y:4d}  score {k['score']:5.1f}  broad level {lv:+.2f}  local spread {sp:.2f}  "
          f"score against its own surroundings {local:4.1f}  half-peak area {area} px")
print(f"candidates still above 5 against their own surroundings: {sum(a >= 5 for a in above_level)} of {len(c)}")
