import sys, numpy as np
from astropy.io import fits
from scipy import ndimage
d = fits.getdata(sys.argv[1]).astype(float)
lum = d.mean(0) if d.ndim == 3 else d
hp = lum - ndimage.median_filter(lum, 9)
b = 128
H, W = hp.shape
grid = np.zeros((H // b, W // b))
for i in range(H // b):
    for j in range(W // b):
        a = hp[i*b:(i+1)*b, j*b:(j+1)*b]
        grid[i, j] = 1.4826 * np.median(np.abs(a - np.median(a)))
med = np.median(grid)
print(sys.argv[1], lum.shape, "median noise", round(med, 2))
for row in grid:
    print(" ".join(f"{v/med:4.1f}" for v in row))
