"""Lucky imaging: the SER file, the ranking and the multi-point stack, on
made-up frames of a textured disc bent by made-up seeing."""
import json

import numpy as np
from scipy import ndimage

import lucky


def surface(size=256, seed=1):
    rng = np.random.default_rng(seed)
    texture = ndimage.gaussian_filter(rng.random((size, size)), 2.0)
    texture = (texture - texture.min()) / np.ptp(texture)
    yy, xx = np.indices((size, size))
    disc = np.hypot(yy - size / 2, xx - size / 2) < size * 0.45
    return (1000 + 2500 * texture) * disc + 40


def seen(truth, rng, bend=2.0, blur=0.6):
    """The truth as the air shows it: bent by a smooth random field, blurred."""
    h, w = truth.shape
    field = [ndimage.zoom(rng.normal(0, bend, (3, 3)), (h / 3, w / 3), order=3)[:h, :w] for _ in range(2)]
    rows, cols = np.indices((h, w), dtype=np.float32)
    bent = ndimage.map_coordinates(truth, [rows + field[0], cols + field[1]], order=1, mode="nearest")
    return ndimage.gaussian_filter(bent, blur) + rng.normal(0, 15, truth.shape)


def mosaic_of(image):
    return np.clip(image, 0, 4095).astype(np.uint16)


def test_a_ser_file_reads_back_what_was_written(tmp_path):
    frames = [np.full((6, 8), v, np.uint16) for v in (1, 2, 4095)]
    writer = lucky.SerWriter(tmp_path / "v.ser", 8, 6, instrument="ALTAIRH183C", depth=16)
    for f in frames:
        writer.add(f)
    writer.close()
    data, colour = lucky.read_ser(tmp_path / "v.ser")
    assert colour == lucky.SER_RGGB and data.shape == (3, 6, 8)
    assert [int(d[0, 0]) for d in data] == [1, 2, 4095]
    assert (tmp_path / "v.ser").stat().st_size == lucky.SER_HEADER + 3 * 6 * 8 * 2


def test_a_video_cut_off_before_it_closed_still_reads_its_whole_frames(tmp_path):
    writer = lucky.SerWriter(tmp_path / "v.ser", 8, 6)
    for v in (10, 20, 30):
        writer.add(np.full((6, 8), v << 4, np.uint16))
    writer.file.write(b"\x07" * 20)       # part of a fourth frame, then the crash: never closed
    writer.file.close()
    data, _ = lucky.read_ser(tmp_path / "v.ser")
    assert data.shape == (3, 6, 8) and [int(d[0, 0]) for d in data] == [10, 20, 30]


def test_8_bit_video_takes_the_top_bits_of_the_12(tmp_path):
    writer = lucky.SerWriter(tmp_path / "v.ser", 2, 1)
    writer.add(np.array([[4095, 160]], np.uint16))
    writer.close()
    data, _ = lucky.read_ser(tmp_path / "v.ser")
    assert data.dtype == np.uint8 and data[0].tolist() == [[255, 10]]


def test_the_phase_correlation_finds_a_shift_to_a_fraction_of_a_pixel():
    truth = surface()
    moved = ndimage.shift(truth, (3.4, -5.7), order=3, mode="nearest")
    dy, dx = lucky.phase_shift(truth, moved)
    assert abs(dy + 3.4) < 0.3 and abs(dx - 5.7) < 0.3


def test_sharper_frames_rank_higher():
    truth = surface()
    sharp, soft = ndimage.gaussian_filter(truth, 0.5), ndimage.gaussian_filter(truth, 2.5)
    assert lucky.sharpness(sharp) > lucky.sharpness(soft)


def test_the_detail_picture_is_the_greens_filled_in_so_the_colour_pattern_does_not_show():
    mosaic = np.zeros((8, 8), np.uint16)
    mosaic[0::2, 0::2] = 4000      # red
    mosaic[1::2, 1::2] = 100       # blue
    mosaic[0::2, 1::2] = mosaic[1::2, 0::2] = 1000    # green
    assert np.allclose(lucky.green(mosaic)[1:-1, 1:-1], 1000)
    rgb = lucky.colour(mosaic)
    assert np.allclose(rgb[2:-2, 2:-2, 0], 4000) and np.allclose(rgb[2:-2, 2:-2, 2], 100)


def test_a_colour_stack_is_drawn_as_a_grey_moon_not_a_green_one(tmp_path):
    from PIL import Image
    image = np.zeros((40, 40, 3), np.float32)
    image[10:30, 10:30] = (116, 147, 93)          # the disc as stacked on 30 October 2026
    balanced = lucky.grey_moon(image)
    assert np.allclose(balanced[20, 20], balanced[20, 20].mean(), rtol=1e-3)
    assert np.allclose(balanced[0, 0], 0)
    drawn = np.asarray(Image.open(lucky.picture(image, tmp_path / "moon.jpg"))).astype(float)
    r, g, b = drawn[20, 20]
    assert abs(r - g) < 6 and abs(b - g) < 6
    flat = np.ones((8, 8), np.float32)
    assert lucky.grey_moon(flat) is not None and lucky.grey_moon(flat).shape == (8, 8)


def test_every_pixel_balanced_to_the_green_s_level():
    mosaic = np.zeros((8, 8), np.uint16)
    mosaic[0::2, 0::2] = 2000
    mosaic[1::2, 1::2] = 500
    mosaic[0::2, 1::2] = mosaic[1::2, 0::2] = 1000
    assert np.allclose(lucky.balanced(mosaic), 1000)
    rng = np.random.default_rng(2)
    frames = np.array([mosaic_of(seen(surface(), rng, bend=0.3)) for _ in range(6)])
    results, done = lucky.stack(frames, keeps=(50,), report=None, box=48, step=24, pixels="all")
    assert done["kept"] == {"50": 3} and results[50.0].shape == (256, 256)


def test_the_stack_keeps_each_share_of_frames():
    rng = np.random.default_rng(7)
    truth = surface()
    blurs = [0.6 if i % 3 == 0 else 3.0 for i in range(30)]
    frames = np.array([mosaic_of(seen(truth, rng, bend=0.5, blur=b)) for b in blurs])
    results, done = lucky.stack(frames, keeps=(10, 30, 100), report=None, box=48, step=24)
    assert done["kept"] == {"10": 3, "30": 9, "100": 30} and done["alignment_points"] > 0 and done["local"]
    assert set(results) == {10.0, 30.0, 100.0}
    # The sharp third beats all thirty, blurred ones and all.
    assert done["sharpness"]["30"] > done["sharpness"]["100"]


def test_alignment_points_put_back_what_the_air_bent():
    """Moved only as a whole, a bent frame stays bent; the multi-point stack
    straightens each part, so it lies closer to the true surface."""
    rng = np.random.default_rng(3)
    truth = surface()
    frames = np.array([mosaic_of(seen(truth, rng)) for _ in range(16)])
    inner = (slice(50, 206), slice(50, 206))
    # Each result is first moved as a whole onto the truth: where the stack
    # sits in the frame is not what is being judged.
    error = lambda image: np.abs(ndimage.shift(image, lucky.phase_shift(truth, image), order=1)
                                 - truth)[inner].mean()
    points, done = lucky.stack(frames, keeps=(100,), report=None, box=48, step=24)
    whole, _ = lucky.stack(frames, keeps=(100,), points=False, report=None)
    assert done["alignment_points"] > 20
    assert error(points[100.0]) < 0.95 * error(whole[100.0])
    assert lucky.sharpness(points[100.0]) > lucky.sharpness(whole[100.0])


def test_each_part_is_built_from_the_frames_sharpest_there():
    """The air blurs one part of a frame and not another: with local
    selection, each half of the picture takes the frames sharp in that half."""
    rng = np.random.default_rng(5)
    truth = surface()
    frames = []
    for i in range(20):
        image = seen(truth, rng, bend=0.3, blur=0.5)
        half = slice(0, 128) if i % 2 else slice(128, 256)
        image[:, half] = ndimage.gaussian_filter(image, 3.0)[:, half]
        frames.append(mosaic_of(image))
    frames = np.array(frames)
    local, _ = lucky.stack(frames, keeps=(25,), report=None, box=48, step=24)
    whole, _ = lucky.stack(frames, keeps=(25,), local=False, report=None, box=48, step=24)
    assert lucky.sharpness(local[25.0]) > 1.2 * lucky.sharpness(whole[25.0])


def test_a_weak_or_odd_alignment_point_is_not_trusted():
    truth = surface().astype(np.float32)
    moved = ndimage.shift(truth, (1.0, -2.0), order=1, mode="nearest")
    points = lucky.alignment_points(truth, 48, 24)
    field = lucky.shift_field(truth, moved, points, 48)
    assert abs(np.median(field[0]) + 1.0) < 0.3 and abs(np.median(field[1]) - 2.0) < 0.3
    # Pure noise in one patch: its match is weak or disagrees, and the
    # field there follows the points around it.
    rows, cols, used = points
    i, j = (int(v[len(v) // 2]) for v in np.nonzero(used))
    y, x = rows[i], cols[j]
    noisy = moved.copy()
    noisy[y - 24:y + 24, x - 24:x + 24] = np.random.default_rng(1).normal(2000, 400, (48, 48))
    field = lucky.shift_field(truth, noisy, points, 48)
    assert abs(field[1][y, x] - 2.0) < 1.0 and abs(field[0][y, x] + 1.0) < 1.0


def test_a_video_is_written_and_shown_on_the_page_as_it_is_taken(tmp_path, monkeypatch):
    """24 October 2026: the page and stream went blank for the whole video."""
    import camera
    import shoot
    import snap
    shown = []

    class Cam:
        name = "fake"
        def __init__(self, gain): pass
        def video(self, seconds, count, roi=None):
            for n in range(count):
                yield np.full((6, 8), 16 * n, np.uint16), n * 0.01, n + 1 + (n >= 2)    # one frame dropped
        def close(self): pass

    monkeypatch.setattr(camera, "Camera", Cam)
    monkeypatch.setattr(shoot, "RUN_LOCK", tmp_path / "imaging.lock")
    monkeypatch.setattr(snap, "publish", lambda mosaic, **kw: shown.append(kw["detail"]))
    monkeypatch.setattr(lucky, "OUT", tmp_path)
    path = lucky.capture("Moon", 4, 0.02, 100)
    data, _ = lucky.read_ser(path)
    assert data.shape == (4, 6, 8) and data.dtype == np.uint8 and int(data[3, 0, 0]) == 3
    assert shown[0] == "frame 1 of 4"
    notes = json.loads(path.with_suffix(".json").read_text())
    assert notes["frames"] == 4 and notes["dropped"] == 1 and notes["exposure"] == 0.02


def test_the_mineral_moon_turns_the_faint_colour_up_and_keeps_the_detail():
    rng = np.random.default_rng(5)
    truth = surface()
    grey = np.stack([truth] * 3, -1)
    tinted = grey.copy()
    tinted[96:160, 40:90, 2] *= 1.02     # a sea a little bluer on the left
    tinted[96:160, 166:216, 0] *= 1.02   # one a little redder on the right
    noisy = lambda a: a + rng.normal(0, 0.002, a.shape).astype(np.float32)    # noqa: E731
    moved = ndimage.shift(tinted, (3, -2, 0), order=1, mode="nearest")
    image, gain = lucky.mineral([noisy(tinted), noisy(moved)], [truth, ndimage.shift(truth, (3, -2), order=1)],
                                blur=2.0)
    assert gain > 5
    left, right = image[96:160, 40:90], image[96:160, 166:216]
    assert left[..., 2].mean() > left[..., 0].mean() * 1.1
    assert right[..., 0].mean() > right[..., 2].mean() * 1.1
    assert lucky.sharpness(image.mean(axis=-1)) > 0.5 * lucky.sharpness(truth)


def test_red_and_blue_are_moved_onto_green():
    truth = surface()
    rgb = np.stack([ndimage.shift(truth, (0, 2), order=1), truth, ndimage.shift(truth, (-1.5, 0), order=1)], -1)
    lined = lucky.channels_lined_up(rgb)
    inner = (slice(20, -20), slice(20, -20))
    assert np.abs(lined[..., 0][inner] - truth[inner]).mean() < 0.3 * np.abs(rgb[..., 0][inner] - truth[inner]).mean()


def test_a_clipped_stack_gives_no_colour_where_it_clipped():
    truth = surface()
    grey = np.stack([truth] * 3, -1).astype(np.float32)
    grey[..., 1] *= 1.27                    # the camera's green takes in more light, so it tops out first
    clipped = np.minimum(grey * 2, 4000)    # every colour stops at the camera's top
    image, _ = lucky.mineral([grey, clipped], [truth, truth], blur=2.0, ceiling=4000)
    bright = truth > np.percentile(truth[truth > 100], 80)
    r, g, b = (image[..., k][bright].mean() for k in range(3))
    assert g > 0.97 * r                     # not magenta where the second stack clipped


def test_a_colour_slope_across_the_disc_is_taken_off_and_the_patches_kept():
    yy, xx = np.indices((64, 64))
    tint = np.zeros((64, 64, 3), np.float32)
    tint[..., 0] = 0.02 * xx / 64            # redder towards one side, as on 30 October 2026
    tint[20:30, 20:30, 2] += 0.01            # a bluer sea
    flat = lucky.flattened(tint, np.ones((64, 64), bool))
    assert np.ptp(flat[..., 0]) < 1e-4
    assert flat[25, 25, 2] - flat[50, 50, 2] > 0.009


def test_only_blue_against_orange_is_kept_not_green_against_magenta():
    tint = np.zeros((4, 4, 3), np.float32)
    tint[0, 0] = (0.01, -0.02, 0.01)         # magenta: the camera
    tint[1, 1] = (0.01, 0.0, -0.01)          # orange: the Moon
    kept = lucky.blue_to_orange(tint)
    assert np.allclose(kept[0, 0], 0) and np.allclose(kept[1, 1], (0.01, 0, -0.01))


def test_a_stack_fades_out_towards_where_it_clipped_rather_than_stopping():
    good = np.ones((80, 80), bool)
    good[:, 50:] = False
    weight = lucky.feathered(good, width=8)
    assert weight[40, 10] > 0.99 and weight[40, 49] < 0.05
    steps = np.diff(weight[40, 20:50])
    assert np.abs(steps).max() < 0.3 and lucky.feathered(np.ones((5, 5), bool)).min() == 1
