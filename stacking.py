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
from camera import colour, is_mono, luminance

ROOT = Path(__file__).parent
# Where the master dark, bias and flat frames are kept. The tests point this
# at an empty folder, for the worker processes too, through TY_CALIBRATION.
CALIBRATION = Path(os.environ.get("TY_CALIBRATION") or config.camera_folder() / "calibration")   # each camera its own
REGISTER = 1024     # side of the central square used for the first rough line-up
MIN_MATCHES = 6     # stars needed to trust a star-by-star alignment
SPOTS = 40          # brightest stars kept from the quick look at a frame, to place it by
# The processing scale for a mono camera's frames ([imaging] processing_scale):
# 2, each 2x2 block one pixel, as the colour camera's always are (stars here
# are about eight native pixels across); 1, the mono frame's full resolution.
# The raw frames on disk are always the full sensor, whichever it is.
PROCESSING_SCALE = 1 if int(config.hardware().get("imaging", {}).get("processing_scale", 2)) == 1 else 2


# --- names that become folders ---------------------------------------------------

# Windows refuses these characters in a file name, and these names whatever
# follows the dot. A comet's designation has a "/", which is wrong everywhere.
REFUSED = '<>:"/\\|?*'
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)),
            *(f"LPT{n}" for n in range(1, 10))}


def folder_name(name):
    """A target's name as the folder its frames are kept in: spaces removed,
    and made safe on both Linux and Windows so a frames/ folder can be copied
    between them. Names that are already safe (M27, NGC7000) are unchanged."""
    safe = "".join("-" if c in REFUSED or ord(c) < 32 else c for c in name.replace(" ", ""))
    safe = safe.rstrip(".") or "unnamed"
    if safe.split(".")[0].upper() in RESERVED:
        safe += "_"
    return safe


# --- using the whole processor -------------------------------------------------

def cores():
    """Physical processor cores. Image work gains little from the extra
    logical threads, so the worker count follows the real cores."""
    try:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8")
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


def without_rows(master):
    """A dark or bias with its row levels made even, each Bayer site to its
    own overall level. The camera's row stripes are new in every frame, so a
    master averaged from 20 keeps a set of its own (0.16-0.20 against 0.13 in
    the mean of 60 lights, and unrelated to them); taken from every light, it
    put that one set into all of them, where stacking cannot average it away
    (the green bands of 19 October 2026). Pixels' own levels, the hot ones
    included, are kept."""
    if master is None:
        return None
    out = master.copy()
    for dy in (0, 1):
        for dx in (0, 1):
            site = out[dy::2, dx::2]
            level = np.median(site, axis=1)
            site -= (level - np.median(level))[:, None]
    return out


class Calibration:
    """Master dark, bias and flat frames for one exposure and gain, loaded
    once. Any of them may be missing; whatever exists is applied. This is
    the 183C's way (a camera with no thermometer: the dark scaled to the
    night). A camera whose darks are matched, never scaled (the cooled 183M,
    `dark_method`), gets a MatchedCalibration instead, chosen from the
    frame's header (INSTRUME) or, with none given, the camera in use."""
    matched = False
    missing = ()           # nothing is required of the 183C's calibration: science may use it as it is

    def __new__(cls, exposure=None, gain=None, header=None):
        if cls is Calibration and dark_method(camera_from(header)) == "matched":
            return super().__new__(MatchedCalibration)
        return super().__new__(cls)

    def __init__(self, exposure, gain, header=None):
        def load(path):
            return fits.getdata(path).astype(np.float32) if path.exists() else None
        paths = {"dark": master_path("dark", exposure, gain), "bias": master_path("bias", gain=gain),
                 "flat": master_path("flat")}
        self.masters = {kind: p.name for kind, p in paths.items() if p.exists()}
        self.dark = without_rows(load(paths["dark"]))
        self.bias = without_rows(load(paths["bias"]))
        self.flat = load(paths["flat"])
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


# --- matched calibration: the cooled 183M (docs/calibration.md) -------------------
#
# Darks matched on everything that changes them (exposure, gain, offset,
# binning, readout speed, the cooler's set temperature), never scaled: the
# IMX183 has amp glow, which does not scale with the hot pixels. Flats per
# camera, train and filter, each with its flat-dark (a dark at the flat's own
# exposure, from the same library). A bad-pixel map per camera. Every master
# is versioned (NAME-vN.fits) and never overwritten; the newest that matches
# is used, and its file name goes into every stack made with it.

DARK_CARDS = ("EXPTIME", "GAIN", "OFFSET", "XBINNING", "READSPD", "SET-TEMP")


def camera_from(header=None):
    """The camera profile a frame was taken with (INSTRUME), or the camera in use."""
    if header is not None:
        return str(header.get("INSTRUME") or config.LEGACY_CAMERA)   # a frame from before INSTRUME: the 183C's
    return config.camera_name()


def dark_method(camera):
    """"matched" (darks matched, never scaled; masters required for science)
    or "scaled" (the 183C's way). A profile's `dark_method`, else matched for
    a cooled camera."""
    profile = config.hardware().get("cameras", {}).get(camera) or {}
    return profile.get("dark_method") or ("matched" if profile.get("cooled") else "scaled")


def library(camera):
    """Where a camera's masters are kept: its own calibration/ folder."""
    if camera == config.camera_name():
        return CALIBRATION
    return config.camera_folder(camera) / "calibration"


def _slug(value):
    return re.sub(r"[^A-Za-z0-9_.+-]+", "-", f"{value:g}" if isinstance(value, float) else str(value))


def dark_stem(cards):
    """The file-name stem of a matched dark for these cards."""
    def card(key, default="x"):
        value = cards.get(key)
        return default if value is None else _slug(float(value) if key in ("EXPTIME", "SET-TEMP") else value)
    return (f"dark-{card('EXPTIME')}s-g{card('GAIN')}-o{card('OFFSET')}-b{card('XBINNING', '1')}"
            f"-s{card('READSPD')}-t{card('SET-TEMP')}")


def flat_stem(cards):
    return f"flat-{_slug(cards.get('TELESCOP') or 'none')}-{_slug(cards.get('FILTER') or 'none')}"


def versions(folder, stem):
    """Every kept version of a master, oldest first."""
    found = []
    for p in Path(folder).glob(f"{stem}-v*.fits"):
        tail = p.stem[len(stem) + 2:]
        if tail.isdigit():
            found.append((int(tail), p))
    return [p for _, p in sorted(found)]


def keep_master(folder, stem, data, header):
    """Keep a master as the next version; an existing file is never replaced."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    have = versions(folder, stem)
    number = int(have[-1].stem.rsplit("-v", 1)[1]) + 1 if have else 1
    path = folder / f"{stem}-v{number}.fits"
    fits.PrimaryHDU(data, fits.Header(dict(header, TY_VER=number))).writeto(path, overwrite=False)
    return path


def calibration_cards(header):
    """The cards a matched calibration is chosen by, from a frame's header."""
    keys = DARK_CARDS + ("INSTRUME", "TELESCOP", "FILTER")
    return tuple((k, header.get(k)) for k in keys) if header is not None else None


def matches(master_header, cards, keys):
    for key in keys:
        want, have = cards.get(key), master_header.get(key)
        if key in ("EXPTIME", "SET-TEMP") and want is not None and have is not None:
            if abs(float(want) - float(have)) > 1e-6:
                return False
        elif (None if want is None else str(want)) != (None if have is None else str(have)):
            return False
    return True


class MatchedCalibration(Calibration):
    """A matched calibration for one camera, exposure and set of settings:
    the newest matching dark, flat (less its flat-dark) and bad-pixel map.
    `missing` says what is not there or does not match; science refuses a
    frame with anything missing (require()). The frame is still calibrated
    with what there is, for a quick look or the stream, labelled uncalibrated."""
    matched = True

    def __init__(self, exposure, gain, header=None):
        cards = dict(header or {})
        cards.setdefault("INSTRUME", camera_from(header))
        cards.setdefault("EXPTIME", exposure)
        cards.setdefault("GAIN", gain)
        if header is None:
            cfg = config.hardware()
            cards.setdefault("SET-TEMP", cfg["camera"].get("tec_target"))
            cards.setdefault("READSPD", cfg["camera"].get("readout_speed"))
            cards.setdefault("TELESCOP", cfg["train"]["name"])
        self.camera, self.cards = cards["INSTRUME"], cards
        folder = library(self.camera)
        self.missing, self.masters = [], {}
        self.dark = self._newest(folder, dark_stem(cards), cards, DARK_CARDS, "dark")
        self.flat = None
        raw = self._newest(folder, flat_stem(cards), cards, ("TELESCOP", "FILTER"), "flat")
        if raw is not None:
            flat_cards = dict(cards, EXPTIME=self._flat_exposure)
            flat_dark = self._newest(folder, dark_stem(flat_cards), flat_cards, DARK_CARDS, "flat-dark")
            if flat_dark is not None:
                light = raw - flat_dark
                self.flat = np.clip(light / np.median(light), 0.2, None)
        mask = self._newest(folder, "badpixels", cards, (), "bad-pixel map")
        self.bad = None if mask is None else mask > 0
        self.bias = None
        self.scale = 1.0
        self.hot = None

    def _newest(self, folder, stem, cards, keys, kind):
        found = versions(folder, stem)
        for path in reversed(found):
            with fits.open(path) as hdul:
                head = hdul[0].header
                if matches(head, cards, keys):
                    self.masters[kind] = path.name
                    if kind == "flat":
                        self._flat_exposure = float(head.get("EXPTIME", 0))
                    return hdul[0].data.astype(np.float32)
        what = {"dark": "a dark at " + ", ".join(f"{k} {cards.get(k)}" for k in DARK_CARDS),
                "flat": f"a flat for {cards.get('TELESCOP')} in {cards.get('FILTER') or 'no filter'}",
                "flat-dark": f"a flat-dark at the flat's {cards.get('EXPTIME')} s",
                "bad-pixel map": "a bad-pixel map"}[kind]
        self.missing.append(what + (f" ({len(found)} kept, none matching)" if found else ""))
        return None

    @property
    def calibrated(self):
        return not self.missing

    def describe(self):
        have = ", ".join(f"{k} {v}" for k, v in self.masters.items()) or "none"
        return (f"matched ({have})" if self.calibrated else
                f"UNCALIBRATED, quick look only: missing {'; '.join(self.missing)} (have: {have})")

    def apply(self, mosaic):
        """(raw - dark) / flat, the dark matched and never scaled, and bad
        pixels replaced by the median of their neighbours."""
        frame = mosaic.astype(np.float32)
        if self.dark is not None and self.dark.shape == frame.shape:
            frame -= self.dark
        if self.flat is not None and self.flat.shape == frame.shape:
            frame /= self.flat
        if self.bad is not None and self.bad.shape == frame.shape and self.bad.any():
            ys, xs = np.nonzero(self.bad)
            h, w = frame.shape
            around = [frame[np.clip(ys + dy, 0, h - 1), np.clip(xs + dx, 0, w - 1)]
                      for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx]
            frame[ys, xs] = np.median(np.array(around), axis=0)
        return frame


SCIENCE = ("difference images", "photometry", "transits", "depth")


def require(calibration, purpose):
    """Science fails closed: a frame from a camera whose darks are matched
    (the 183M) with any master missing or not matching is refused
    (CALIBRATION_MISSING), saying which. The 183C's calibration is used as
    it always was."""
    import interface
    if getattr(calibration, "matched", False) and calibration.missing:
        raise interface.Refusal("CALIBRATION_MISSING", f"{purpose} refused: these {calibration.camera} frames "
                                f"have no matching {'; '.join(calibration.missing)}. Make it with ./calibrate.py "
                                "(darks with the cap on, indoors or on a cloudy night).")
    return calibration


def require_frames(paths, purpose):
    """require() for a set of raw frames, judged by the first of each folder."""
    seen = set()
    for path in paths:
        folder = Path(path).parent
        if folder in seen:
            continue
        seen.add(folder)
        head = fits.getheader(path, 1)
        require(Calibration(float(head.get("EXPTIME", 0)), int(float(head.get("GAIN", 0))), head), purpose)


def require_stack(path, purpose):
    """require() for a stack, from what restack wrote into it: a matched
    camera's stack labelled uncalibrated (TY_CALIB false) never enters
    science or a search."""
    import interface
    if not Path(path).is_file():
        return fits.Header()           # nothing to judge here: reading the stack itself will say it is missing
    head = fits.getheader(path)
    camera = str(head.get("INSTRUME") or config.LEGACY_CAMERA)
    if dark_method(camera) == "matched" and head.get("TY_CALIB") is not True:
        why = head.get("TY_MISS") or "its calibration was not recorded"
        raise interface.Refusal("CALIBRATION_MISSING", f"{purpose} refused: {Path(path).name} is an uncalibrated "
                                f"stack from the {camera} ({why}); it is for a quick look only.")
    return head


def stack_cards(calibration, header):
    """What a stack's FITS header says about where it came from and how it
    was calibrated: the camera and band, whether calibrated, and the masters."""
    cards = {k: header[k] for k in ("INSTRUME", "TELESCOP", "FOCALLEN", "FILTER", "FILTPOS") if k in header}
    missing, masters = getattr(calibration, "missing", ()), getattr(calibration, "masters", {})
    cards["TY_CALIB"] = bool(not missing)
    for kind, key in (("dark", "TY_DARK"), ("flat", "TY_FLAT"), ("flat-dark", "TY_FDARK"),
                      ("bad-pixel map", "TY_BPM"), ("bias", "TY_BIAS")):
        if kind in masters:
            cards[key] = masters[kind][:68]
    if missing:
        cards["TY_MISS"] = "; ".join(missing)[:68]
    return cards


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


# Rows over which a row's own level is compared with its neighbours', in
# rows of one Bayer site (two rows of the sensor each), and the sections
# across the frame each row is levelled in.
STRIPE_ROWS = 101
STRIPE_SECTIONS = 4


def smooth_rows(level, width=STRIPE_ROWS):
    """A running median of the row levels. Past each end the levels are
    carried on by turning them about the end, so a gradient runs straight
    to the edge instead of flattening there."""
    half = width // 2
    start, end = np.median(level[:5]), np.median(level[-5:])
    padded = np.concatenate([2 * start - level[half:0:-1], level, 2 * end - level[-2:-half - 2:-1]])
    return ndimage.median_filter(padded, width, mode="nearest")[half:half + len(level)]


SKY_SHARE = 0.2     # the least share of a row's section that must be sky to measure its stripe there


def extended_light(image, small=31, broad=255):
    """Where an image shows light that is not sky: a galaxy, a nebula, a
    bright star's glow. The sky's tilt (a plane fitted to the whole image)
    is taken off first; what is left, smoothed over `small` pixels, is light
    where it stands above the broad background round it (`broad` pixels) by
    three times its own spread. Row stripes barely show at that smoothing."""
    step = max(1, min(image.shape) // 200)
    yy, xx = np.mgrid[0:image.shape[0]:step, 0:image.shape[1]:step]
    sample = image[::step, ::step].astype(np.float64)
    keep = sample < np.percentile(sample, 80)                      # the sky, not the galaxy
    design = np.column_stack([np.ones(keep.sum()), yy[keep], xx[keep]])
    a, b, c = np.linalg.lstsq(design, sample[keep], rcond=None)[0]
    rows, cols = np.indices(image.shape, dtype=np.float32)
    rest = image - (a + b * rows + c * cols)
    excess = ndimage.uniform_filter(rest, small) - ndimage.uniform_filter(rest, broad, mode="nearest")
    spread = 1.4826 * float(np.median(np.abs(excess - np.median(excess)))) + 1e-6
    return excess > np.median(excess) + 3 * spread


def destripe(frame, sections=STRIPE_SECTIONS):
    """Take out the row stripes this camera reads into each frame: every row
    of each Bayer site is brought to the level of the rows round it.

    A stripe is not one level along its row: on 19 October 2026 a row green
    at the left of the frame was magenta at the right (left and right
    thirds correlated -0.87), the same in every frame, so stacking never
    averaged it away. So each row is measured in `sections` across the frame
    and the correction runs straight between their middles.

    Each row's level is the median of its sky alone. Taken over every pixel,
    as at first, the level followed a galaxy narrower than STRIPE_ROWS, and
    levelling it against the rows round it took real light: on 19 October
    2026 a galaxy 280 rows across lost 12% of its core and a narrower one
    38% (now about 2% and 4%). So the frame is levelled the first way, which
    takes out the stripes but only dents a galaxy, the light is found in
    that (extended_light), and the frame is levelled again from its sky.
    Stars do not move a median; anything broader than STRIPE_ROWS, a
    gradient or a galaxy filling the frame, is left alone."""
    first = level_rows(frame, sections)
    # One map of where the light is, from all four sites together, found in
    # 4x4 blocks of a site (the smoothing is far broader than a block) and
    # spread back to every pixel: a sixteenth of the work.
    h, w = first.shape[0] // 8 * 8, first.shape[1] // 8 * 8
    blocks = first[:h, :w].reshape(h // 8, 8, w // 8, 8).mean(axis=(1, 3))
    light = np.repeat(np.repeat(extended_light(blocks, small=8, broad=64), 4, axis=0), 4, axis=1)
    return level_rows(frame, sections, light)


def level_rows(frame, sections=STRIPE_SECTIONS, light=None):
    """destripe's levelling, from every pixel of each row's section, or with
    `light` (a map at the size of one Bayer site) from the sky alone. A
    section of a row with less than SKY_SHARE sky takes its stripe from the
    row's nearest sections that have enough."""
    out = frame.astype(np.float32, copy=True)
    for dy in (0, 1):
        for dx in (0, 1):
            site = out[dy::2, dx::2]
            rows, cols = site.shape
            if rows < STRIPE_ROWS:
                continue
            edges = np.linspace(0, cols, sections + 1).astype(int)
            middles = (edges[:-1] + edges[1:] - 1) / 2
            mask = None
            if light is not None:
                mask = np.zeros(site.shape, bool)
                mask[:light.shape[0], :light.shape[1]] = light[:rows, :cols]
            stripes = []
            for a, b in zip(edges[:-1], edges[1:]):
                level = np.median(site[:, a:b], axis=1)
                lit = None if mask is None else mask[:, a:b].any(axis=1)
                if lit is None or not lit.any():
                    stripes.append(level - smooth_rows(level))
                    continue
                # Only rows with some light in them need the slower median of their sky alone.
                part = np.where(mask[lit, a:b], np.nan, site[lit, a:b])
                enough = np.ones(rows, bool)
                enough[lit] = np.isfinite(part).mean(axis=1) >= SKY_SHARE
                stripe = np.full(rows, np.nan)
                if enough.sum() > 1:
                    measured = level.copy()
                    ok = enough[lit]
                    measured[np.flatnonzero(lit)[ok]] = np.nanmedian(part[ok], axis=1)
                    # Rows with too little sky take their level from the sky rows round them.
                    level = np.interp(np.arange(rows), np.flatnonzero(enough), measured[enough])
                    stripe = level - smooth_rows(level)
                    stripe[~enough] = np.nan
                stripes.append(stripe)
            stripes = np.array(stripes)
            for r in np.flatnonzero(~np.isfinite(stripes).all(axis=0)):
                have = np.flatnonzero(np.isfinite(stripes[:, r]))
                stripes[:, r] = np.interp(np.arange(sections), have, stripes[have, r]) if len(have) else 0.0
            # How much of each section's stripe reaches each column: straight
            # between the middles, flat beyond the outer ones.
            share = np.array([np.interp(np.arange(cols), middles, np.eye(sections)[i])
                              for i in range(sections)])
            site -= stripes.T @ share
    return out


def prepare(mosaic, calibration, mono=False):
    """A raw frame, calibrated and destriped, as half-size RGB with hot
    pixels removed; grey RGB from a mono camera (camera.is_mono), at
    PROCESSING_SCALE."""
    return clean(colour(destripe(calibration.apply(mosaic)), mono=mono, block=PROCESSING_SCALE if mono else 2))


# --- raw frames on disk --------------------------------------------------------

# The header cards a kept raw frame carries: what it was (which camera:
# the 183C and the 183M may each be used on any night), and what the
# pipeline needs to treat it (no BAYERPAT and TY_MONO: a mono frame).
KEPT = ("EXPTIME", "GAIN", "DATE-OBS", "BAYERPAT", "TY_MONO", "INSTRUME", "TELESCOP", "FOCALLEN", "TY_MODEL",
        "FILTER", "FILTPOS", "CCD-TEMP", "SET-TEMP", "TY_ONTGT", "TY_TECV", "TY_TECP", "READSPD", "OFFSET",
        "XBINNING")


def camera_of(header):
    """(camera, focal length in mm) a frame was taken with, from its INSTRUME
    and FOCALLEN (camera.identify). A frame from before they were written
    was the 183C's, at a focal length nobody wrote down (None)."""
    camera = str(header.get("INSTRUME") or config.LEGACY_CAMERA)
    focal = header.get("FOCALLEN")
    return camera, (round(float(focal)) if focal else None)


def same_camera(paths):
    """Refuses (INVALID_REQUEST) a set of raw frames from more than one camera
    or focal length: a stack or a difference image must never mix them by
    accident. One frame is read from each folder, as a run's frames all come
    from one camera."""
    import interface
    seen = {}
    for path in paths:
        folder = Path(path).parent
        if folder not in seen:
            seen[folder] = camera_of(fits.getheader(path, 1))
    cameras = {c for c, _ in seen.values()}
    focals = {f for _, f in seen.values() if f is not None}
    if len(cameras) > 1 or len(focals) > 1:
        listed = "; ".join(f"{folder.name}: {c}{f' at {f} mm' if f else ''}" for folder, (c, f) in seen.items())
        raise interface.Refusal("INVALID_REQUEST", f"These frames come from more than one camera or light "
                                f"path ({listed}); they cannot go into one picture.")


def save_light(folder, index, mosaic, header):
    """Keep a raw frame, losslessly compressed (about half the size)."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"light-{index:04d}.fits"
    kept = fits.Header({k: header[k] for k in KEPT if k in header})
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
    # Where the brightest stars are, in the pixels of the full treatment's
    # picture: enough to tell how far this frame sits from another.
    q["spots"] = [[2 * float(x), 2 * float(y)] for x, y in stars[:SPOTS, :2]]
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
    # The sky's rise against its own level, measured from its own grain:
    # after the bias it can sit near or below zero (18 October 2026, about
    # -55 after the camera was moved to another port), where "half as much
    # again" of a negative number rejected every frame of a clear night.
    rise = q["background"] - typical["background"]
    if rise > max(0.5 * abs(typical["background"]), 10 * q.get("noise", 0) or 0):
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


def _refine(xy, reference_xy, r, t):
    """Improve a starting rotation and shift by pairing stars, loosely at
    first and then tightly. Returns (R, t, matches, residual)."""
    matched, residual = 0, None
    for tolerance in (12.0, 6.0, 4.0, 2.0):
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


def align(stars, reference_stars, rough, centre=None):
    """Rotation and shift taking this frame's stars onto the reference's,
    starting from a rough (dy, dx) shift. Returns (R, t, matches, residual),
    the residual being the typical distance left between matched stars in
    pixels. With too few matched stars the rough shift is returned as it
    stands.

    On a mount whose polar axis is well out, the field slowly turns: a few
    degrees in an hour. If the plain attempt pairs few stars and `centre`
    (x, y of the frame's middle) is given, a turn of up to 8 degrees either
    way about the centre is tried and the best start is refined."""
    r, t = np.eye(2), np.array([rough[1], rough[0]], dtype=float)
    if len(stars) < MIN_MATCHES or len(reference_stars) < MIN_MATCHES:
        return r, t, 0, None
    xy = stars[:, :2].astype(float)
    reference_xy = reference_stars[:, :2].astype(float)
    found = _refine(xy, reference_xy, r, t)
    if centre is None or found[2] >= min(len(xy), len(reference_xy)) / 3:
        return found if found[2] else (r, t, 0, None)
    centre = np.asarray(centre, dtype=float)
    # For each trial angle, let the brightest stars vote on the shift: every
    # pair of (frame star, reference star) proposes one, and the true shift
    # is the one many pairs agree on. This needs no starting guess.
    bright, bright_reference = xy[:60], reference_xy[:60]
    best, start = 0, None
    for degrees in np.arange(-8.0, 8.5, 0.5):
        a = np.radians(degrees)
        turn = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
        turned = (bright - centre) @ turn.T + centre
        proposals = (bright_reference[:, None, :] - turned[None, :, :]).reshape(-1, 2)
        cells, counts = np.unique(np.round(proposals / 8.0).astype(int), axis=0, return_counts=True)
        top = counts.argmax()
        if counts[top] > best:
            agreed = proposals[np.all(np.abs(proposals - cells[top] * 8.0) <= 8.0, axis=1)]
            best, start = int(counts[top]), (turn, centre - turn @ centre + np.median(agreed, axis=0))
    if start is not None and best >= MIN_MATCHES:
        turned = _refine(xy, reference_xy, *start)
        if turned[2] > found[2]:
            found = turned
    return found if found[2] else (r, t, 0, None)


def apart(spots, reference_spots):
    """How far a frame sits from another, as the (x, y) shift that takes its
    brightest stars onto the other's, or None if too few agree. Every pair of
    stars proposes a shift and the true one is the one many pairs agree on,
    so no starting guess is needed and no shift is too far."""
    a, b = np.asarray(spots, dtype=float), np.asarray(reference_spots, dtype=float)
    if len(a) < MIN_MATCHES or len(b) < MIN_MATCHES:
        return None
    proposals = (b[:, None, :] - a[None, :, :]).reshape(-1, 2)
    cells, counts = np.unique(np.round(proposals / 8.0).astype(int), axis=0, return_counts=True)
    top = counts.argmax()
    if counts[top] < MIN_MATCHES:
        return None
    agreed = proposals[np.all(np.abs(proposals - cells[top] * 8.0) <= 8.0, axis=1)]
    return np.median(agreed, axis=0)


def framing(spots, reference_spots):
    """Where most of a session's frames sat, as an (x, y) shift from the
    reference frame, or None when that is not known or is nowhere else.

    Everything is lined up on the sharpest frame, and the picture used to
    take its framing from that frame too. On 6 October 2026 the sharpest of
    207 frames of M31 was the one that had drifted furthest, 19 arcminutes
    off, and the galaxy's core came out in a corner of a picture the run had
    kept centred for all but a few minutes."""
    shifts = [s for s in (apart(reference_spots, own) for own in spots) if s is not None]
    if len(shifts) < 3:
        return None
    middle = np.median(shifts, axis=0)
    return None if np.hypot(*middle) < 2 else middle


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
    # The rough line-up cannot see a shift of more than half its square, and
    # reports some smaller one in its place; with the frame's middle given,
    # the stars are then asked directly. Without it a drifted frame matched
    # no stars, went into the stack out of place, and the run, told it had
    # drifted 8 arcminutes when it was 19, did not re-centre.
    centre = (lum.shape[1] / 2, lum.shape[0] / 2)
    r, t, matched, residual = align(stars, reference["stars"], rough, centre)
    rotation = float(np.degrees(np.arctan2(r[1, 0], r[0, 0])))
    return warp(rgb, r, t), {"shift": [float(t[0]), float(t[1])], "rotation": rotation,
                             "matched": matched, "residual": residual}


# --- stacking ------------------------------------------------------------------

TRIM_SHARE = 0.9   # an edge row or column reached by fewer of the frames than this is trimmed off
TRIM_MOST = 0.15   # but never more than this share of a side

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

    def covered(self, share=TRIM_SHARE, most=TRIM_MOST):
        """The rows and columns (two slices) to keep so that the picture's
        edges are where nearly every frame reached. Frames framed a little
        differently, or two sessions put together, leave a band along the
        edges that fewer frames covered: noisier, and after the sky is
        levelled a lighter strip. On 14 October 2026 the two M31 sessions
        left one 130 pixels deep along the bottom. Never more than `most` of
        a side is taken off."""
        weights = self.weights.mean(axis=2) if self.weights.ndim == 3 else self.weights
        keep = []
        for along in (np.median(weights, axis=1), np.median(weights, axis=0)):
            enough = np.flatnonzero(along >= share * along.max())
            limit = int(most * len(along))
            start = min(int(enough[0]), limit) if len(enough) else 0
            stop = max(int(enough[-1]) + 1, len(along) - limit) if len(enough) else len(along)
            keep.append(slice(start, stop))
        return tuple(keep)


# --- work done in the worker processes -----------------------------------------

@functools.lru_cache(maxsize=4)
def _calibration(exposure, gain, cards=None):
    """One calibration per exposure and gain, and per camera and its
    settings (calibration_cards of the frame), loaded once a worker. The
    183C's is chosen by exposure and gain alone, as before."""
    return Calibration(exposure, gain, dict(cards) if cards else None)


def worker_cards(header):
    """The hashable cards a worker's calibration is chosen by."""
    return calibration_cards(header) if header is not None else None


def measure_file(path, exposure, gain):
    """Worker: the quick quality of one saved raw frame, with timings."""
    timings = Timings()
    with timings.phase("load raw frames"):
        mosaic, header = load_light(Path(path))
    with timings.phase("measure quality"):
        q = quick_quality(mosaic, _calibration(exposure, gain, worker_cards(header)))
    q["file"] = Path(path).name
    return q, timings.seconds


FLIP_RESIDUAL = 2.0      # pixels: a fit worse than this is tried the other way up

def register_file(path, exposure, gain, reference, store, slot, shape, scale=1.0, try_flip=False):
    """Worker: prepare one raw frame in full, line it up on the reference and
    write it into its slot of the shared file of registered frames."""
    timings = Timings()
    with timings.phase("load raw frames"):
        mosaic, header = load_light(Path(path))
    with timings.phase("calibrate and clean"):
        rgb = prepare(mosaic, _calibration(exposure, gain, worker_cards(header)), mono=is_mono(header))
        lum = rgb.sum(axis=2)
    with timings.phase("find stars"):
        stars = find_stars(lum)
    with timings.phase("line up"):
        rough = offset(reference["square"], centre_square(lum))
        # The picture is framed where most frames sat (see framing()): the
        # reference's stars have been moved there already, and the rough
        # line-up, which knows only the reference as it was taken, follows.
        moved = reference.get("moved", (0.0, 0.0))
        rough = (rough[0] + moved[1], rough[1] + moved[0])
        centre = (lum.shape[1] / 2, lum.shape[0] / 2)
        r, t, matched, residual = align(stars, reference["stars"], rough, centre)
        flipped = False
        if try_flip and (matched < 8 or residual is None or residual > FLIP_RESIDUAL):
            # Taken on the other side of the meridian, the picture is upside
            # down: the tube swung over the pole in between. Turn it and retry.
            # A dense field gives eight or more chance matches to an upside-down
            # frame, so a poor fit is enough to try: on 14 October 2026 all but
            # 8 of 226 frames from the far side of M31 were stacked unturned,
            # 7.7 pixels out, and the galaxy came out twice.
            turned = np.ascontiguousarray(rgb[::-1, ::-1])
            turned_lum = turned.sum(axis=2)
            turned_stars = find_stars(turned_lum)
            again = align(turned_stars, reference["stars"],
                          offset(reference["square"], centre_square(turned_lum)), centre)
            if again[2] >= 8 and (again[2] > matched or (again[3] is not None and (residual is None or again[3] < residual))):
                rgb, flipped = turned, True
                r, t, matched, residual = again
    with timings.phase("resample"):
        # `scale` puts frames of a different exposure length on the same footing.
        registered = warp(rgb, r, t) * scale
    with timings.phase("write registered"):
        frames = np.memmap(store, dtype=np.float16, mode="r+", shape=shape)
        frames[slot] = registered
        frames.flush()
    info = {"shift": [float(t[0]), float(t[1])],
            "rotation": float(np.degrees(np.arctan2(r[1, 0], r[0, 0]))),
            "matched": matched, "residual": residual, "flipped": flipped}
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
    calibration = _calibration(exposure, gain, worker_cards(header))
    with timings.phase("measure quality"):
        q = quick_quality(mosaic, calibration)
    keep, reason = judge(q, recent)
    out = {"entry": dict(q, index=index, accepted=keep, reason=reason), "frame": None,
           "reference": None, "timings": timings.seconds}
    if not keep:
        return out
    with timings.phase("calibrate and clean"):
        rgb = prepare(mosaic, calibration, mono=is_mono(header))
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
    with (Path(session) / "frames.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


CAPTURE_FILES = ("frames.jsonl", "frames.json", "session.json")


def last_capture(session):
    """When the run itself last wrote to `session`: its plan (the start),
    a frame's line in the log, the log written whole at the end; 0 if none.
    Never what processing writes beside them afterwards (restack.json,
    depth.json, patrol.json, forced photometry...): on 4 November 2026 a
    restack and a search of finished sessions read as imaging, and the
    stream went back on air three times after the night was over."""
    times = []
    for name in CAPTURE_FILES:
        try:
            times.append((Path(session) / name).stat().st_mtime)
        except OSError:
            pass
    return max(times, default=0)


def read_log(session):
    """Every frame's entry so far."""
    lines = Path(session) / "frames.jsonl"
    if lines.exists():
        return [json.loads(line) for line in lines.read_text(encoding="utf-8").splitlines() if line.strip()]
    path = Path(session) / "frames.json"   # sessions from before the line-per-frame log
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def run_status(session, now=None):
    """Where an imaging run has got to, for the web page: frames taken, kept
    and dropped, why the dropped ones were dropped, and the newest frame."""
    import time

    import sky
    session = Path(session)
    log = read_log(session)
    plan = {}
    if (session / "session.json").exists():
        plan = json.loads((session / "session.json").read_text(encoding="utf-8"))
    # A frame the live stack had no time for is kept for the quality pass,
    # not dropped: counted apart, never as rejected (24 October 2026, the
    # Moon: the page said 27 of 52 rejected when 5 were).
    waiting = [f for f in log if not f["accepted"] and (f.get("deferred") or "kept for the quality pass" in f["reason"])]
    rejected = [f for f in log if not f["accepted"] and f not in waiting]
    reasons = {}
    for f in rejected:
        # "star brightness down 61% (cloud)" and "... 54% (cloud)" are one reason.
        reason = re.sub(r" \d+%", "", f["reason"])
        reasons[reason] = reasons.get(reason, 0) + 1
    status = {
        "name": plan.get("name", session.parent.name),
        # Older sessions did not say; their name does (sky.object_kind).
        "object_kind": plan.get("object_kind") or sky.object_kind(plan.get("name", session.parent.name)),
        "planned": plan.get("frames"), "exposure": plan.get("exposure"),
        "captured": len(log), "accepted": len(log) - len(rejected) - len(waiting),
        "rejected": len(rejected), "waiting": len(waiting),
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
    status["age"] = round((now or time.time()) - last_capture(session))
    return status


# --- choosing the exposure -----------------------------------------------------

def choose_exposure(trials, keep_round=0.85, allow_bloat=1.25):
    """The longest exposure whose stars are still round, and no more than a
    little wider than at the length before. `trials` is a list of (seconds,
    quality) pairs.

    Each length is judged against the one before it, not against the
    shortest: a 1 or 2 s frame freezes the seeing, and every longer frame
    is wider for that alone. On 13 October 2026 the stars were round to
    16 s, FWHM 2.8 at 2 s and 4.2 at 16, but judged against the 2 s frame
    nothing past 4 s could be chosen. Trailing shows as stars losing their
    roundness, or a sudden jump in width."""
    usable = sorted((s, q) for s, q in trials if q["stars"] >= 8)
    if not usable:
        return None
    best, before = usable[0]
    roundest = before["roundness"]
    for seconds, q in usable[1:]:
        roundest = max(roundest, q["roundness"])
        if q["roundness"] >= keep_round * roundest and q["fwhm"] <= allow_bloat * before["fwhm"]:
            best, before = seconds, q
        else:
            break
    return best
