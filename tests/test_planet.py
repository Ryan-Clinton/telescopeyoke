import numpy as np
from scipy import ndimage

import planet


def disc(shift=(0.0, 0.0), blur=1.0, size=256):
    y, x = np.mgrid[:size, :size]
    body = ((y - size / 2 - shift[0]) ** 2 + (x - size / 2 - shift[1]) ** 2 < 20 ** 2).astype(np.float32)
    body[size // 2 - 2:size // 2 + 2] *= 0.5           # a band across it, for detail
    return 100 + 2000 * ndimage.gaussian_filter(body, blur)


def test_a_shift_is_measured_to_a_fraction_of_a_pixel():
    dy, dx = planet.shift_to(disc().astype(np.float32), disc((3.3, -5.6)).astype(np.float32))
    assert abs(dy + 3.3) < 0.2 and abs(dx - 5.6) < 0.2


def test_the_sharpest_frames_are_kept_and_lined_up():
    rng = np.random.default_rng(1)
    squares = [disc((rng.uniform(-6, 6), rng.uniform(-6, 6)), blur) for blur in [1.0] * 10 + [5.0] * 30]
    stacked, used = planet.stack(np.array(squares), keep=0.25)
    plain = np.mean([planet.colour(s) for s in squares], axis=0)
    assert used == 10
    assert planet.sharpness(stacked.sum(axis=2)) > 5 * planet.sharpness(plain.sum(axis=2))


def test_a_planet_off_the_edge_of_the_sensor_gives_no_square():
    mosaic = np.zeros((1000, 1000), np.uint16)
    assert planet.crop(mosaic, 50, 500) is None and planet.crop(mosaic, 500, 500).shape == (256, 256)
