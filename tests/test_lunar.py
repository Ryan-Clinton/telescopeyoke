"""Finding the Moon's disc in a picture, its region, its exposure, the
centring sums, and tonight's Moon."""
import numpy as np
import pytest

import config
import lunar


def moon_picture(shape=(300, 400), centre=(150, 200), r=60, lit=1.0, level=3000, sky=40):
    """A disc lit from the right; `lit` 1 is full, 0.5 a half Moon (the
    terminator a straight line through the centre)."""
    yy, xx = np.indices(shape)
    disc = np.hypot(yy - centre[0], xx - centre[1]) < r
    edge = centre[1] + r - 2 * r * lit
    return np.where(disc & (xx >= edge), level, sky).astype(np.float32)


@pytest.mark.parametrize("lit", [1.0, 0.75, 0.5])
def test_the_disc_is_found_from_its_sunlit_limb_whatever_the_phase(lit):
    disc = lunar.find_disc(moon_picture(centre=(140, 210), lit=lit))
    assert disc["cy"] == pytest.approx(140, abs=4) and disc["cx"] == pytest.approx(210, abs=4)
    assert disc["r"] == pytest.approx(60, abs=4)


def test_a_disc_cut_by_the_frame_edge_is_still_found():
    disc = lunar.find_disc(moon_picture(centre=(150, 40)))
    assert disc["cx"] == pytest.approx(40, abs=5) and disc["r"] == pytest.approx(60, abs=5)


def test_no_disc_in_an_empty_sky():
    assert lunar.find_disc(np.full((300, 400), 40, np.float32)) is None


def test_the_region_holds_the_disc_with_a_margin():
    disc = lunar.find_disc(moon_picture(centre=(150, 200)))
    x, y, w, h = lunar.roi(disc, (300, 400))
    assert w == h and w >= 2 * 60 * 1.16 and w % 16 == 0
    assert x <= 200 - 60 and x + w >= 200 + 60 and y <= 150 - 60 and y + h >= 150 + 60


def test_the_exposure_puts_the_surface_up_the_scale_without_clipping():
    disc = lunar.find_disc(moon_picture(level=742))
    exposure, gain = lunar.exposure_for(disc, 0.005, 4095)
    assert exposure == pytest.approx(0.005 * 0.72 * 4095 / 742, rel=0.05) and gain == 100
    clipped = lunar.find_disc(moon_picture(level=4095))
    assert lunar.exposure_for(clipped, 0.02, 4095)[0] < 0.02 * 0.5
    # Past the longest exposure, the gain rises instead.
    dim = lunar.find_disc(moon_picture(level=800))
    exposure, gain = lunar.exposure_for(dim, 0.02, 4095, longest=0.03)
    assert exposure == pytest.approx(0.03) and gain > 100


def test_a_measured_calibration_turns_an_offset_into_the_move_that_removes_it():
    truth = np.array([[2.0, -88.0], [90.0, 3.0]])        # pixels (down, right) per arcminute (east, north)
    moves = [((5.0, 0.0), tuple(truth @ [5.0, 0.0])), ((0.0, 5.0), tuple(truth @ [0.0, 5.0]))]
    matrix = lunar.calibration(moves)
    assert np.allclose(matrix, truth)
    east, north = lunar.correction(matrix, 120.0, -45.0)
    assert np.allclose(truth @ [east, north], [-120.0, 45.0])


def test_tonights_moon():
    """24 October 2026, 01:00 UTC: two days before full, waxing."""
    m = lunar.state(config.example()["site"], "2026-10-24T01:00:00")
    assert 85 <= m["illumination"] <= 99 and m["waxing"]
    assert 11 <= m["age_days"] <= 14
    assert 356000 <= m["distance_km"] <= 407000 and 0.48 <= m["size_deg"] <= 0.57
