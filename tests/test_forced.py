"""A place measured in a stack: a star there gets its magnitude back, an
empty place an upper limit, and a stack's record finds its stack wherever
depth.py was run from."""
import math

import numpy as np
import pytest

import forced
from test_depth import render

ZP = 22.0


def field(star_mag=None, shape=(300, 300), noise=4.0, seed=2, fwhm=4.0):
    rng = np.random.default_rng(seed)
    image = 100 + rng.normal(0, noise, shape)
    if star_mag is not None:
        image += render(shape, np.array([[150.3, 149.6]]), np.array([10 ** (-0.4 * (star_mag - ZP))]), fwhm=fwhm)
    return image.astype(np.float32)


def test_a_star_at_the_place_gets_its_magnitude_back():
    mag, err, limit = forced.measure_at(field(15.5), 150.3, 149.6, 4.0, ZP, np.random.default_rng(1))
    # Measured on the zero point's scale, an aperture as wide as the star,
    # which holds a little less than the whole star: 0.07 mag fainter.
    inside = -2.5 * math.log10(1 - math.exp(-4 * math.log(2)))
    assert mag == pytest.approx(15.5 + inside, abs=0.05) and err < 0.1 and limit > mag


def test_an_empty_place_gives_how_faint_it_must_have_been():
    mag, err, limit = forced.measure_at(field(None), 150.3, 149.6, 4.0, ZP, np.random.default_rng(1))
    assert mag is None and err is None
    # Three times the noise of the weighted measurement, on this grain of sky.
    s = 4.0 / 2.355
    expected = ZP - 2.5 * math.log10(3 * 4.0 * math.sqrt(4 * math.pi * s * s) * (1 - math.exp(-4 * math.log(2))))
    assert limit == pytest.approx(expected, abs=0.35)


def test_a_record_written_elsewhere_still_finds_its_stack(tmp_path):
    folder = tmp_path / "frames" / "M31" / "20261013-232632"
    folder.mkdir(parents=True)
    (folder / "final.fits").write_bytes(b"x")
    record = folder / "depth.json"
    assert forced.located(record, {"stack": "frames/M31/20261013-232632/final.fits"}) == folder / "final.fits"
    assert forced.located(record, {"stack": "/nowhere/discovery.fits"}) is None


def test_the_light_above_the_reference_leaves_out_the_star_underneath(tmp_path, monkeypatch):
    """A new star on top of a steady one: the stack measures both together,
    the stack less the reference measures only the new one."""
    from astropy.io import fits
    import reference
    from test_depth import star_field
    image, wcs, catalogue = star_field(shape=(500, 700), count=220, seed=4)
    ref_path = tmp_path / "ref.fits"
    fits.PrimaryHDU(image).writeto(ref_path)
    monkeypatch.setattr(reference, "for_field", lambda name: (ref_path, name))
    rng = np.random.default_rng(9)
    place = (352.4, 247.8)
    steady = render(image.shape, np.array([place]), np.array([10 ** (-0.4 * (16.5 - ZP))]), fwhm=4.0)
    new_star = render(image.shape, np.array([place]), np.array([10 ** (-0.4 * (16.0 - ZP))]), fwhm=4.0)
    ref_with = (image + steady).astype(np.float32)
    fits.PrimaryHDU(ref_with).writeto(ref_path, overwrite=True)
    tonight = (image + steady + new_star + rng.normal(0, 2, image.shape)).astype(np.float32)
    less = forced.above_reference(tonight, wcs, "M31", lambda lum: wcs)
    inside = -2.5 * math.log10(1 - math.exp(-4 * math.log(2)))
    above, _, _ = forced.measure_at(less, *place, 4.0, ZP, np.random.default_rng(1))
    both, _, _ = forced.measure_at(tonight, *place, 4.0, ZP, np.random.default_rng(1))
    assert above == pytest.approx(16.0 + inside, abs=0.1)
    assert both < above - 0.3          # the steady star adds its light to the plain measurement
