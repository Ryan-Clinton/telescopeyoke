"""Lucky imaging: the SER file, the ranking and the multi-point stack, on
made-up frames of a textured disc bent by made-up seeing."""
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
    writer = lucky.SerWriter(tmp_path / "v.ser", 8, 6, instrument="ALTAIRH183C")
    for f in frames:
        writer.add(f)
    writer.close()
    data, colour = lucky.read_ser(tmp_path / "v.ser")
    assert colour == lucky.SER_RGGB and data.shape == (3, 6, 8)
    assert [int(d[0, 0]) for d in data] == [1, 2, 4095]
    assert (tmp_path / "v.ser").stat().st_size == lucky.SER_HEADER + 3 * 6 * 8 * 2


def test_the_phase_correlation_finds_a_shift_to_a_fraction_of_a_pixel():
    truth = surface()
    moved = ndimage.shift(truth, (3.4, -5.7), order=3, mode="nearest")
    dy, dx = lucky.phase_shift(truth, moved)
    assert abs(dy + 3.4) < 0.3 and abs(dx - 5.7) < 0.3


def test_sharper_frames_rank_higher():
    truth = surface()
    sharp, soft = ndimage.gaussian_filter(truth, 0.5), ndimage.gaussian_filter(truth, 2.5)
    assert lucky.sharpness(sharp) > lucky.sharpness(soft)


def test_the_stack_keeps_the_best_share_of_frames():
    rng = np.random.default_rng(7)
    truth = surface()
    blurs = [0.6 if i % 3 == 0 else 3.0 for i in range(30)]
    frames = np.array([mosaic_of(seen(truth, rng, bend=0.5, blur=b)) for b in blurs])
    _, done = lucky.stack(frames, keep=30, progress=None, box=48, step=24)
    assert done["kept"] == 9 and done["alignment_points"] > 0
    assert done["kept_sharpness_from"] > lucky.sharpness(lucky.grey(frames[1], (1, 1)))


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
    points, done = lucky.stack(frames, keep=100, progress=None, box=48, step=24)
    whole, _ = lucky.stack(frames, keep=100, points=False, progress=None)
    assert done["alignment_points"] > 20
    assert error(points) < 0.95 * error(whole)
    assert lucky.sharpness(points) > lucky.sharpness(whole)


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
                yield np.full((6, 8), n, np.uint16), n * 0.01
        def close(self): pass

    monkeypatch.setattr(camera, "Camera", Cam)
    monkeypatch.setattr(shoot, "RUN_LOCK", tmp_path / "imaging.lock")
    monkeypatch.setattr(snap, "publish", lambda mosaic, **kw: shown.append(kw["detail"]))
    monkeypatch.setattr(lucky, "OUT", tmp_path)
    path = lucky.capture("Moon", 4, 0.02, 100)
    data, _ = lucky.read_ser(path)
    assert data.shape == (4, 6, 8) and shown[0] == "frame 1 of 4"
