"""The imaging pipeline's working parts: calibration, star measurement, frame
quality, registration and stacking. shoot.py uses them live, frame by frame;
restack.py uses them afterwards on the saved raw frames for the best result.

Frames are handled as float32 RGB at half the sensor's resolution (one pixel
per 2x2 Bayer cell), about 1.3 arcseconds per pixel on the 150P, which suits
ordinary seeing better than the sensor's native 0.66.
"""
import functools
import json
import multiprocessing
import os
import re
import time
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import numpy as np
from astropy.io import fits
from scipy import ndimage
from scipy.spatial import cKDTree

import config
from camera import colour, luminance

ROOT = Path(__file__).parent
CALIBRATION = ROOT / "calibration"
REGISTER = 1024     # side of the central square used for the first rough line-up
MIN_MATCHES = 6     # stars needed to trust a star-by-star alignment


# --- using the whole processor -------------------------------------------------

def cores():
    """Physical processor cores. Image work gains little from the extra
    logical threads, so the worker count follows the real cores."""
    try:
        text = Path("/proc/cpuinfo").read_text()
        found = {(block.split("physical id")[1].split("\n")[0], block.split("core id")[1].split("\n")[0])
                 for block in text.split("\n\n") if "core id" in block}
        if found:
            return len(found)
    except (OSError, IndexError):
        pass
    return max(1, (os.cpu_count() or 2) // 2)


@contextmanager
def worker_pool(workers=None):
    """A pool of worker processes for work that is independent frame to
    frame. Each worker is held to one maths thread: the pool supplies the
    parallelism, and letting every worker start its own threads as well would
    have them fighting over the same cores."""
    limits = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")
    before = {name: os.environ.get(name) for name in limits}
    os.environ.update({name: "1" for name in limits})
    try:
        # "spawn" starts each worker afresh, so the limits above apply to it.
        with ProcessPoolExecutor(max_workers=workers or cores(),
                                 mp_context=multiprocessing.get_context("spawn")) as pool:
            yield pool
    finally:
        for name, value in before.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


class Timings:
    """Seconds spent in each phase of the work, for --profile."""

    def __init__(self):
        self.seconds = {}

    @contextmanager
    def phase(self, name):
        started = time.perf_counter()
        try:
            yield
        finally:
            self.seconds[name] = self.seconds.get(name, 0.0) + time.perf_counter() - started

    def add(self, other):
        for name, value in (other.seconds if isinstance(other, Timings) else other).items():
            self.seconds[name] = self.seconds.get(name, 0.0) + value

    def report(self, wall=None):
        lines = [f"  {name:<22}{value:8.1f} s" for name, value in self.seconds.items()]
        total = sum(self.seconds.values())
        lines.append(f"  {'work done':<22}{total:8.1f} s")
        if wall is not None:
            lines.append(f"  {'time on the clock':<22}{wall:8.1f} s")
        return "\n".join(lines)


# --- calibration ---------------------------------------------------------------

def setup_name():
    """The current camera arrangement's name from config.toml, safe for a
    file name."""
    return re.sub(r"[^A-Za-z0-9_-]+", "-", str(config.hardware()["camera"]["setup"]))


def master_path(kind, exposure=None, gain=None):
    if kind == "dark":
        return CALIBRATION / f"dark-{exposure:g}s-g{gain}.fits"
    if kind == "bias":
        return CALIBRATION / f"bias-g{gain}.fits"
    # A flat belongs to one arrangement of camera and telescope.
    return CALIBRATION / f"flat-{setup_name()}.fits"


class Calibration:
    """Master dark, bias and flat frames for one exposure and gain, loaded
    once. Any of them may be missing; whatever exists is applied."""

    def __init__(self, exposure, gain):
        def load(path):
            return fits.getdata(path).astype(np.float32) if path.exists() else None
        self.dark = load(master_path("dark", exposure, gain))
        self.bias = load(master_path("bias", gain=gain))
        self.flat = load(master_path("flat"))
        self.scale = 1.0   # how strongly the dark was applied to the last frame
        self.hot = None
        if self.dark is not None and self.bias is not None:
            # The part of the dark that grows with temperature, and where its
            # hottest pixels are: they show how warm the sensor is now.
            self.current = self.dark - self.bias
            level = np.percentile(self.current[::4, ::4], 99.9)
            self.hot = np.flatnonzero(self.current > max(level, 1.0))

    def describe(self):
        have = [name for name in ("dark", "bias", "flat") if getattr(self, name) is not None]
        return ", ".join(have) if have else "none (run calibrate.py for cleaner pictures)"

    def apply(self, mosaic):
        """(raw - dark) / flat on the raw Bayer mosaic. The dark carries the
        camera's offset with it; without a dark the bias alone is removed.

        This camera has no temperature sensor to match darks by. With both a
        dark and a bias, the dark's hot pixels are compared with the same
        pixels in the frame, and the dark is scaled to fit: a warmer sensor
        needs more of it, a cooler one less."""
        frame = mosaic.astype(np.float32)
        if self.hot is not None and len(self.hot) >= 50:
            excess = frame.ravel()[self.hot] - np.median(frame[::8, ::8])
            self.scale = float(np.clip(np.median(excess / self.current.ravel()[self.hot]), 0.3, 3.0))
            frame -= self.bias + self.scale * self.current
        elif self.dark is not None:
            frame -= self.dark
        elif self.bias is not None:
            frame -= self.bias
        if self.flat is not None:
            frame /= self.flat
        return frame


def clean(rgb):
    """Replace hot pixels the dark frame did not catch: anything far brighter
    than its neighbours."""
    out = rgb.copy()
    for c in range(3):
        plane = rgb[..., c]
        local = ndimage.median_filter(plane, 3)
        spread = 1.4826 * np.median(np.abs(plane - local)) + 1e-6
        hot = plane - local > 8 * spread
        out[..., c][hot] = local[hot]
    return out


def prepare(mosaic, calibration):
    """A raw frame, calibrated, as half-size RGB with hot pixels removed."""
    return clean(colour(calibration.apply(mosaic)))


# --- raw frames on disk --------------------------------------------------------

def save_light(folder, index, mosaic, header):
    """Keep a raw frame, losslessly compressed (about half the size)."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"light-{index:04d}.fits"
    kept = fits.Header({k: header[k] for k in ("EXPTIME", "GAIN", "DATE-OBS", "BAYERPAT")
                        if k in header})
    fits.HDUList([fits.PrimaryHDU(), fits.CompImageHDU(mosaic, kept, compression_type="RICE_1")]
                 ).writeto(path, overwrite=True)
    return path


def load_light(path):
    with fits.open(path) as hdul:
        return hdul[1].data, hdul[1].header


# --- stars and frame quality ---------------------------------------------------

@functools.lru_cache(maxsize=4)
def _grid(shape):
    """Row and column number of every pixel, built once per frame size."""
    return np.indices(shape, dtype=np.float32)


def find_stars(lum, limit=300):
    """Stars in a brightness image, brightest first, as rows of
    (x, y, flux, fwhm, roundness). FWHM is in pixels; roundness is 1 for a
    round star and falls towards 0 as it trails."""
    work = ndimage.gaussian_filter(lum.astype(np.float32), 1.0)
    work -= ndimage.uniform_filter(work, 64)
    sample = work[::4, ::4]
    noise = 1.4826 * float(np.median(np.abs(sample - np.median(sample)))) + 1e-6
    mask = work > 5 * noise
    labels, count = ndimage.label(mask)
    if not count:
        return np.zeros((0, 5), np.float32)
    index = np.arange(1, count + 1)
    area = ndimage.sum_labels(mask, labels, index)
    value = np.where(mask, work, 0)
    flux = ndimage.sum_labels(value, labels, index)
    yy, xx = _grid(lum.shape)
    x = ndimage.sum_labels(value * xx, labels, index) / flux
    y = ndimage.sum_labels(value * yy, labels, index) / flux
    xx2 = ndimage.sum_labels(value * xx * xx, labels, index) / flux - x * x
    yy2 = ndimage.sum_labels(value * yy * yy, labels, index) / flux - y * y
    xy = ndimage.sum_labels(value * xx * yy, labels, index) / flux - x * y
    # Long and short widths of each star, from its second moments.
    mid = (xx2 + yy2) / 2
    half = np.sqrt(np.maximum(((xx2 - yy2) / 2) ** 2 + xy ** 2, 0))
    major, minor = np.maximum(mid + half, 1e-6), np.maximum(mid - half, 1e-6)
    fwhm = 2.355 * np.sqrt((major + minor) / 2)
    roundness = np.sqrt(minor / major)
    keep = (area >= 4) & (area <= 3000)
    stars = np.column_stack([x, y, flux, fwhm, roundness])[keep]
    return stars[np.argsort(-stars[:, 2])][:limit].astype(np.float32)


def quality(lum, stars):
    """What a frame is like: star sharpness, shape and brightness, how many
    stars, and the sky's level and grain."""
    sample = lum[::4, ::4]
    background = float(np.median(sample))
    noise = 1.4826 * float(np.median(np.abs(sample - background))) + 1e-6
    if len(stars) == 0:
        return {"fwhm": None, "roundness": None, "stars": 0, "flux": 0.0,
                "background": background, "noise": noise}
    return {"fwhm": float(np.median(stars[:, 3])), "roundness": float(np.median(stars[:, 4])),
            "stars": int(len(stars)),
            # Brightness of the 30 brightest stars: thin cloud dims them
            # before it hides them.
            "flux": float(np.median(stars[:30, 2])),
            "background": background, "noise": noise}


def quick_quality(mosaic, calibration):
    """A frame's quality from a quarter-size brightness image: a fraction of
    the work of the full treatment, and enough to tell a good frame from a
    spoiled one before spending that work on it. The numbers are scaled to
    match what the full-size image would give."""
    lum = luminance(calibration.apply(mosaic))
    rows, cols = lum.shape[0] // 2 * 2, lum.shape[1] // 2 * 2
    small = lum[:rows, :cols].reshape(rows // 2, 2, cols // 2, 2).mean(axis=(1, 3))
    small = ndimage.median_filter(small, 3)   # hot pixels are not stars
    stars = find_stars(small)
    q = quality(small, stars)
    if q["fwhm"] is not None:
        q["fwhm"] *= 2
    q["flux"] *= 4
    q["noise"] *= 2
    return q


def judge(q, accepted):
    """(keep?, reason) for a frame, against the frames accepted so far."""
    if q["stars"] < 8:
        return False, "too few stars (cloud?)"
    if q["roundness"] < 0.5:
        return False, "stars trailed (wind or a knock?)"
    if len(accepted) < 3:
        return True, ""
    typical = {k: float(np.median([a[k] for a in accepted]))
               for k in ("fwhm", "roundness", "stars", "flux", "background")}
    if q["stars"] < 0.5 * typical["stars"]:
        drop = 100 * (1 - q["stars"] / typical["stars"])
        return False, f"stars down {drop:.0f}% (cloud)"
    if q["flux"] < 0.6 * typical["flux"]:
        drop = 100 * (1 - q["flux"] / typical["flux"])
        return False, f"star brightness down {drop:.0f}% (cloud)"
    if q["fwhm"] > 1.5 * typical["fwhm"]:
        return False, "stars bloated (seeing or shake)"
    if q["roundness"] < 0.75 * typical["roundness"]:
        return False, "stars trailed (wind or a knock?)"
    if q["background"] > 1.5 * typical["background"]:
        return False, "sky brightened (cloud or a light)"
    return True, ""


def weight(q, best):
    """How much a frame counts in the final stack, against the best frame:
    sharpness x roundness x transparency x cleanness. No frame that passed
    the checks counts for less than a quarter."""
    sharpness = (best["fwhm"] / q["fwhm"]) ** 2
    shape = min(q["roundness"] / best["roundness"], 1.0)
    transparency = min(q["flux"] / best["flux"], 1.0) if best.get("flux") else 1.0
    cleanness = (best["noise"] / q["noise"]) ** 2
    return float(np.clip(sharpness * shape * transparency * cleanness, 0.25, 1.0))


def baseline(frames):
    """The frames to judge the rest of a session against: the better half.
    If much of the session was under cloud, the session's own average would
    be mediocre and let poor frames through."""
    ranked = sorted(frames, key=lambda f: f["fwhm"] / (max(f["roundness"], 0.1) * max(f["flux"], 1e-6)))
    return ranked[:max(3, len(ranked) // 2)]


# --- registration --------------------------------------------------------------

def centre_square(lum):
    """The middle of the frame reduced to its stars only. The sensor's own
    fixed pattern and dust shadows sit still from frame to frame, and would
    otherwise fool the line-up into finding no movement at all."""
    y, x = (lum.shape[0] - REGISTER) // 2, (lum.shape[1] - REGISTER) // 2
    square = ndimage.gaussian_filter(lum[y:y + REGISTER, x:x + REGISTER], 1.5)
    square = square - ndimage.uniform_filter(square, 64)
    noise = 1.4826 * np.median(np.abs(square))
    return np.clip(square - 5 * noise, 0, None)


def offset(reference, square):
    """(rows, cols) to shift a frame by so its stars land on the reference's,
    to a fraction of a pixel."""
    fa, fb = np.fft.fft2(reference), np.fft.fft2(square)
    match = np.fft.ifft2(fa * fb.conj()).real
    py, px = np.unravel_index(np.argmax(match), match.shape)

    def refine(before, peak, after):
        # Vertex of the parabola through the peak and its two neighbours.
        bend = before - 2 * peak + after
        return 0.0 if bend == 0 else float(np.clip(0.5 * (before - after) / bend, -0.5, 0.5))

    n = REGISTER
    dy = py + refine(match[(py - 1) % n, px], match[py, px], match[(py + 1) % n, px])
    dx = px + refine(match[py, (px - 1) % n], match[py, px], match[py, (px + 1) % n])
    return (dy - n if dy > n / 2 else dy), (dx - n if dx > n / 2 else dx)


def fit_rigid(source, target):
    """Rotation matrix R and shift t with target ≈ R·source + t, for matched
    (x, y) points: the best rigid fit, with no change of scale. Scale and
    lens distortion are left alone on purpose; every frame in a session comes
    through the same optics. The residual each frame reports would show it if
    that ever stopped being enough."""
    cs, ct = source.mean(axis=0), target.mean(axis=0)
    u, _, vt = np.linalg.svd((source - cs).T @ (target - ct))
    r = (u @ vt).T
    if np.linalg.det(r) < 0:   # a reflection is never the right answer
        vt[-1] *= -1
        r = (u @ vt).T
    return r, ct - r @ cs


def pair_up(moved, reference_xy, tolerance):
    """Indices (frame star, reference star) of stars that are each other's
    nearest neighbour and within `tolerance` pixels: one partner each, so two
    stars can never be matched to the same reference star."""
    distance, nearest = cKDTree(reference_xy).query(moved)
    _, back = cKDTree(moved).query(reference_xy)
    mine = np.arange(len(moved))
    mutual = (back[nearest] == mine) & (distance < tolerance)
    return mine[mutual], nearest[mutual]


def align(stars, reference_stars, rough):
    """Rotation and shift taking this frame's stars onto the reference's,
    starting from a rough (dy, dx) shift. Returns (R, t, matches, residual),
    the residual being the typical distance left between matched stars in
    pixels. With too few matched stars the rough shift is returned as it
    stands."""
    r, t = np.eye(2), np.array([rough[1], rough[0]], dtype=float)
    if len(stars) < MIN_MATCHES or len(reference_stars) < MIN_MATCHES:
        return r, t, 0, None
    xy = stars[:, :2].astype(float)
    reference_xy = reference_stars[:, :2].astype(float)
    matched, residual = 0, None
    for tolerance in (4.0, 2.0):
        a, b = pair_up(xy @ r.T + t, reference_xy, tolerance)
        if len(a) < MIN_MATCHES:
            break
        r, t = fit_rigid(xy[a], reference_xy[b])
        # Drop pairs the fit leaves far out (a wrong match or a blended
        # star), and fit again without them.
        left = np.hypot(*(xy[a] @ r.T + t - reference_xy[b]).T)
        close = left <= max(2.5 * np.median(left), 0.3)
        if MIN_MATCHES <= close.sum() < len(a):
            a, b = a[close], b[close]
            r, t = fit_rigid(xy[a], reference_xy[b])
            left = np.hypot(*(xy[a] @ r.T + t - reference_xy[b]).T)
        matched, residual = len(a), float(np.median(left))
    return r, t, matched, residual


def warp(rgb, r, t):
    """Move a frame onto the reference: rotate by R and shift by t, with
    smooth (cubic) resampling. Pixels with no data come back as NaN."""
    # For each output pixel, where to read the input: p_in = Rᵀ(p_out - t),
    # written in (row, col) order for scipy.
    swap = np.array([[0.0, 1.0], [1.0, 0.0]])
    matrix = swap @ r.T @ swap
    shift = swap @ (-r.T @ t)
    out = np.empty_like(rgb)
    for c in range(rgb.shape[2]):
        out[..., c] = ndimage.affine_transform(rgb[..., c], matrix, offset=shift, order=3,
                                               mode="constant", cval=np.nan)
    return out


def register(rgb, lum, stars, reference):
    """Line a frame up with the reference frame. `reference` is a dict with
    the reference's "square" and "stars". Returns (registered frame, info)."""
    rough = offset(reference["square"], centre_square(lum))
    r, t, matched, residual = align(stars, reference["stars"], rough)
    rotation = float(np.degrees(np.arctan2(r[1, 0], r[0, 0])))
    return warp(rgb, r, t), {"shift": [float(t[0]), float(t[1])], "rotation": rotation,
                             "matched": matched, "residual": residual}


# --- stacking ------------------------------------------------------------------

class Stack:
    """A running average that leaves out anything that does not belong: a
    satellite or aircraft trail, a cosmic ray, the empty edge of a shifted
    frame. Each pixel keeps its own sum, sum of squares and weight."""

    def __init__(self, shape, clip=4.0, after=8):
        self.total = np.zeros(shape, np.float32)
        self.squares = np.zeros(shape, np.float32)
        self.weights = np.zeros(shape, np.float32)
        self.frames, self.clip, self.after = 0, clip, after
        self.reference = None   # (mean, spread) to clip against instead, if set

    def mean(self):
        return self.total / np.maximum(self.weights, 1e-6)

    def spread(self):
        mean = self.mean()
        return np.sqrt(np.maximum(self.squares / np.maximum(self.weights, 1e-6) - mean ** 2, 0))

    def add(self, frame, weight=1.0):
        use = np.isfinite(frame)
        if self.reference is not None:
            mean, spread = self.reference
        elif self.frames >= self.after:
            mean, spread = self.mean(), self.spread()
        else:
            mean = None
        if mean is not None:
            # Stars flicker from frame to frame, so allow a share of the
            # brightness as well as the measured spread.
            allowed = self.clip * spread + 0.25 * np.abs(mean)
            use &= np.abs(np.nan_to_num(frame) - mean) <= allowed
        value = np.where(use, frame, 0).astype(np.float32)
        self.total += weight * value
        self.squares += weight * value * value
        self.weights += weight * use
        self.frames += 1

    def result(self):
        """The stack so far; pixels nothing contributed to are NaN-free zeros."""
        return np.where(self.weights > 0, self.mean(), 0).astype(np.float32)


# --- work done in the worker processes -----------------------------------------

@functools.lru_cache(maxsize=2)
def _calibration(exposure, gain):
    return Calibration(exposure, gain)


def measure_file(path, exposure, gain):
    """Worker: the quick quality of one saved raw frame, with timings."""
    timings = Timings()
    with timings.phase("load raw frames"):
        mosaic, _ = load_light(Path(path))
    with timings.phase("measure quality"):
        q = quick_quality(mosaic, _calibration(exposure, gain))
    q["file"] = Path(path).name
    return q, timings.seconds


def register_file(path, exposure, gain, reference, store, slot, shape):
    """Worker: prepare one raw frame in full, line it up on the reference and
    write it into its slot of the shared file of registered frames."""
    timings = Timings()
    with timings.phase("load raw frames"):
        mosaic, _ = load_light(Path(path))
    with timings.phase("calibrate and clean"):
        rgb = prepare(mosaic, _calibration(exposure, gain))
        lum = rgb.sum(axis=2)
    with timings.phase("find stars"):
        stars = find_stars(lum)
    with timings.phase("line up"):
        rough = offset(reference["square"], centre_square(lum))
        r, t, matched, residual = align(stars, reference["stars"], rough)
    with timings.phase("resample"):
        registered = warp(rgb, r, t)
    with timings.phase("write registered"):
        frames = np.memmap(store, dtype=np.float16, mode="r+", shape=shape)
        frames[slot] = registered
        frames.flush()
    info = {"shift": [float(t[0]), float(t[1])],
            "rotation": float(np.degrees(np.arctan2(r[1, 0], r[0, 0]))),
            "matched": matched, "residual": residual}
    return info, timings.seconds


def live_frame(mosaic, header, exposure, gain, folder, index, save, recent, reference):
    """Worker: everything that can be done to one live frame without the
    running stack. Keeps the raw file, checks the frame quickly against the
    recently accepted ones (`recent`), and only if it passes prepares it in
    full and lines it up on `reference` (None for the first frame, which
    becomes the reference). Returns a dict with the log entry, the frame
    ready to stack (or None), and what a first frame needs to be a reference."""
    timings = Timings()
    if save:
        with timings.phase("save raw frames"):
            save_light(Path(folder), index, mosaic, header)
    calibration = _calibration(exposure, gain)
    with timings.phase("measure quality"):
        q = quick_quality(mosaic, calibration)
    keep, reason = judge(q, recent)
    out = {"entry": dict(q, index=index, accepted=keep, reason=reason), "frame": None,
           "reference": None, "timings": timings.seconds}
    if not keep:
        return out
    with timings.phase("calibrate and clean"):
        rgb = prepare(mosaic, calibration)
        lum = rgb.sum(axis=2)
    with timings.phase("find stars"):
        stars = find_stars(lum)
    if reference is None:
        out["frame"] = rgb
        out["reference"] = {"square": centre_square(lum), "stars": stars}
        out["entry"].update(shift=[0.0, 0.0], rotation=0.0, matched=len(stars), residual=0.0)
        return out
    with timings.phase("line up"):
        rough = offset(reference["square"], centre_square(lum))
        r, t, matched, residual = align(stars, reference["stars"], rough)
    with timings.phase("resample"):
        out["frame"] = warp(rgb, r, t)
    out["entry"].update(shift=[float(t[0]), float(t[1])],
                        rotation=float(np.degrees(np.arctan2(r[1, 0], r[0, 0]))),
                        matched=matched, residual=residual)
    return out


def save_only(mosaic, header, folder, index):
    """Worker: keep a raw frame the live stack had no time for."""
    save_light(Path(folder), index, mosaic, header)
    return index


def write_stack(path, rgb, header):
    fits.PrimaryHDU(np.moveaxis(rgb, 2, 0).astype(np.float32), fits.Header(header)).writeto(
        path, overwrite=True)


def append_log(session, entry):
    """Add one frame's entry to the session's log. One line per frame, so a
    long run does not rewrite the whole log every frame."""
    with (Path(session) / "frames.jsonl").open("a") as f:
        f.write(json.dumps(entry) + "\n")


def read_log(session):
    """Every frame's entry so far."""
    lines = Path(session) / "frames.jsonl"
    if lines.exists():
        return [json.loads(line) for line in lines.read_text().splitlines() if line.strip()]
    path = Path(session) / "frames.json"   # sessions from before the line-per-frame log
    return json.loads(path.read_text()) if path.exists() else []


def run_status(session, now=None):
    """Where an imaging run has got to, for the web page: frames taken, kept
    and dropped, why the dropped ones were dropped, and the newest frame."""
    import time
    session = Path(session)
    log = read_log(session)
    plan = {}
    if (session / "session.json").exists():
        plan = json.loads((session / "session.json").read_text())
    rejected = [f for f in log if not f["accepted"]]
    reasons = {}
    for f in rejected:
        # "star brightness down 61% (cloud)" and "... 54% (cloud)" are one reason.
        reason = re.sub(r" \d+%", "", f["reason"])
        reasons[reason] = reasons.get(reason, 0) + 1
    status = {
        "name": plan.get("name", session.parent.name),
        "planned": plan.get("frames"), "exposure": plan.get("exposure"),
        "captured": len(log), "accepted": len(log) - len(rejected), "rejected": len(rejected),
        "reasons": dict(sorted(reasons.items(), key=lambda item: -item[1])),
        "finished": (session / "final.fits").exists() or (session / "live.fits").exists(),
        "restacked": (session / "final.fits").exists(),
    }
    if log:
        last = log[-1]
        status["last"] = ("accepted" if last["accepted"] else "rejected: " + last["reason"])
        if last.get("fwhm"):
            status["last"] += f", FWHM {last['fwhm']:.1f}, {last['stars']} stars"
    kept = [f for f in log if f["accepted"]]
    if plan.get("exposure"):
        status["integration"] = round(plan["exposure"] * len(kept))
    if kept:
        # The newest accepted frame against the run's typical frame, so the
        # page can say whether focus, cloud or drift is getting worse.
        newest = kept[-1]
        typical = {k: float(np.median([f[k] for f in kept])) for k in ("fwhm", "roundness", "stars")}
        height = 1824.0   # half-size frame height, for drift as a share of the frame
        drift = 100 * float(np.hypot(*newest.get("shift", [0, 0]))) / height

        def verdict(good, fair):
            return "good" if good else "watch" if fair else "poor"

        status["latest"] = {
            "fwhm": [round(newest["fwhm"], 1),
                     verdict(newest["fwhm"] <= 1.15 * typical["fwhm"],
                             newest["fwhm"] <= 1.4 * typical["fwhm"])],
            "roundness": [round(newest["roundness"], 2),
                          verdict(newest["roundness"] >= 0.8, newest["roundness"] >= 0.65)],
            "stars": [newest["stars"],
                      verdict(newest["stars"] >= 0.8 * typical["stars"],
                              newest["stars"] >= 0.5 * typical["stars"])],
            "drift": [round(drift), verdict(drift < 10, drift < 20)],
            "rotation": [round(newest.get("rotation", 0.0), 3), "good"],
        }
        recent = log[-60:]
        status["series"] = {
            "fwhm": [f.get("fwhm") for f in recent],
            "stars": [f.get("stars") for f in recent],
            "drift": [round(100 * float(np.hypot(*f["shift"])) / height, 1) if f.get("shift") else None
                      for f in recent],
            "accepted": [bool(f["accepted"]) for f in recent],
        }
    newest = max((p.stat().st_mtime for p in session.glob("*.json*")), default=0)
    status["age"] = round((now or time.time()) - newest)
    return status


# --- choosing the exposure -----------------------------------------------------

def choose_exposure(trials, keep_round=0.85, allow_bloat=1.25):
    """The longest exposure whose stars are still nearly as round and tight
    as the shortest one's. `trials` is a list of (seconds, quality) pairs."""
    usable = sorted((s, q) for s, q in trials if q["stars"] >= 8)
    if not usable:
        return None
    _, shortest = usable[0]
    best = usable[0][0]
    for seconds, q in usable:
        if (q["roundness"] >= keep_round * shortest["roundness"]
                and q["fwhm"] <= allow_bloat * shortest["fwhm"]):
            best = seconds
        else:
            break
    return best
