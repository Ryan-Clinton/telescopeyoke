#!/usr/bin/env python3
"""Train and judge our own denoiser, on the desktop's GPU (spec, section 5).

    ./denoiser.py train --data DIR --out MODEL.pt [--steps N] [--survey DIR]
        [--masters DIR ...] [--repeats DIR] [--workers N]
    ./denoiser.py prepare --data DIR [--survey DIR] [--masters DIR ...]
    ./denoiser.py judge --data DIR --model MODEL.pt

Pictures only: nothing here touches a raw frame, a stack or a measurement.
PyTorch is needed only by this script, and only on the computer that runs it.
"""
import argparse
import hashlib
import inspect
import json
import re
import struct
import time
from pathlib import Path

import numpy as np
from scipy import ndimage

CROP = 256
HELD_OUT = {"NGC2174": (92.4, 20.5), "IC405": (79.1, 34.3)}   # degrees: never trained on
HELD_OUT_CLEAR = 2.0     # degrees from a field: its 0.66 half-diagonal plus a survey CCD's 0.21, with margin
BATCH = 8
CROP_TRIES = 5000       # draws before a dataset with no usable crop is named and refused


def network():
    import torch
    from torch import nn

    class Block(nn.Module):
        def __init__(self, a, b):
            super().__init__()
            self.skip = nn.Conv2d(a, b, 1)
            self.body = nn.Sequential(nn.Conv2d(a, b, 3, padding=1), nn.GroupNorm(8, b), nn.SiLU(),
                                      nn.Conv2d(b, b, 3, padding=1), nn.GroupNorm(8, b))
            self.end = nn.SiLU()

        def forward(self, x):
            return self.end(self.body(x) + self.skip(x))

    class UNet(nn.Module):
        """Four levels, 32 channels at the top; predicts a correction in units
        of the input's own local noise, so it works at any noise level."""

        def __init__(self, base=32):
            super().__init__()
            sizes = [base, base * 2, base * 4, base * 8]
            self.down = nn.ModuleList([Block(2 if i == 0 else sizes[i - 1], sizes[i]) for i in range(4)])
            self.up = nn.ModuleList([nn.ConvTranspose2d(sizes[i], sizes[i - 1], 2, 2) for i in range(3, 0, -1)])
            self.merge = nn.ModuleList([Block(sizes[i - 1] * 2, sizes[i - 1]) for i in range(3, 0, -1)])
            self.out = nn.Conv2d(base, 1, 1)
            nn.init.zeros_(self.out.weight)
            nn.init.zeros_(self.out.bias)

        def forward(self, x, s):
            h = torch.cat([torch.asinh(x / 3), torch.log(s)], 1)
            kept = []
            for i, block in enumerate(self.down):
                h = block(h)
                if i < 3:
                    kept.append(h)
                    h = nn.functional.avg_pool2d(h, 2)
            for up, merge in zip(self.up, self.merge):
                h = merge(torch.cat([up(h), kept.pop()], 1))
            return x + s * self.out(h)

    return UNet()


class Pairs:
    """Random crops from the kept pairs, read from disk as they are needed."""

    def __init__(self, data, roles, seed=0):
        index = json.loads((Path(data) / "index.json").read_text())
        self.parts = []
        for record in index:
            if record["role"] in roles:
                for part in sorted((Path(data) / record["name"]).glob("split*")):
                    self.parts.append({k: np.load(part / f"{k}.npy", mmap_mode="r") for k in ("x", "y", "s", "valid")})
                    self.parts[-1]["name"] = f"{record['name']}/{part.name}"
        self.rng = np.random.default_rng(seed)
        self.refused = 0

    def crop(self):
        for _ in range(CROP_TRIES):
            p = self.parts[self.rng.integers(len(self.parts))]
            h, w = p["x"].shape
            r, c = self.rng.integers(h - CROP), self.rng.integers(w - CROP)
            if p["valid"][r:r + CROP, c:c + CROP].mean() < 0.98:
                self.refused += 1
                continue
            out = [np.array(p[k][r:r + CROP, c:c + CROP], np.float32) for k in ("x", "y", "s")]
            mask = np.array(p["valid"][r:r + CROP, c:c + CROP], np.float32)
            turn, flip = self.rng.integers(4), self.rng.integers(2)
            out = [np.rot90(a, turn) for a in [*out, mask]]
            return [(a[:, ::-1] if flip else a).copy() for a in out]
        raise RuntimeError(f"no crop {CROP} px square with 98% valid pixels in {CROP_TRIES} draws from: "
                           + ", ".join(p["name"] for p in self.parts))

    def arrays(self, count=BATCH):
        rows = [self.crop() for _ in range(count)]
        return [np.stack([r[k] for r in rows])[:, None] for k in range(4)]

    def batch(self, torch, device, count=BATCH):
        return [torch.from_numpy(a).to(device) for a in self.arrays(count)]


def survey_tile(path):
    """One IGAPS frame at our scale and sharpness, scaled so its nebula spans 1,
    or None if it has none. The limit is from six frames looked at by eye on
    22 November 2026: star fields scored 0.5 to 1.3, IC 443 and the Rosette 2 to 3."""
    from astropy.io import fits
    from astropy import units as u
    from astropy.coordinates import SkyCoord
    from astropy.wcs import WCS
    with fits.open(path) as h:
        hdu = next(x for x in h if x.data is not None)
        raw, header = hdu.data.astype(np.float32), hdu.header
    try:
        ra, dec = WCS(header).all_pix2world(raw.shape[1] / 2, raw.shape[0] / 2, 0)
    except Exception:
        return None         # where it is cannot be told, so it cannot be shown clear of the test fields
    here = SkyCoord(float(ra) * u.deg, float(dec) * u.deg)
    if any(here.separation(SkyCoord(a * u.deg, d * u.deg)).deg < HELD_OUT_CLEAR for a, d in HELD_OUT.values()):
        return None
    noise = 1.4826 * np.median(np.abs(raw[::2, ::2] - np.median(raw)))
    coarse = ndimage.median_filter(raw[::8, ::8], 25)
    span = float(np.percentile(coarse, 98) - np.percentile(coarse, 2))
    if span / max(noise, 1e-6) < 1.8:
        return None
    d = ndimage.gaussian_filter(raw, 7.0)[::4, ::4]         # 1.3"/px, stars about our width
    return ((d - np.median(d)) / span).astype(np.float32)


def read_image(path):
    """One plane of a linear master, FITS or uncompressed XISF: (image, filter card)."""
    path = Path(path)
    if path.suffix.lower() != ".xisf":
        from astropy.io import fits
        with fits.open(path, memmap=False) as h:
            hdu = next(x for x in h if x.data is not None)
            if hdu.data.ndim != 2:
                return None, None
            return hdu.data.astype(np.float32), str(hdu.header.get("FILTER", ""))
    with open(path, "rb") as f:
        if f.read(8) != b"XISF0100":
            return None, None
        size = struct.unpack("<I", f.read(4))[0]
        f.read(4)
        head = f.read(size).decode("utf8", "ignore")
        image = re.search(r"<Image\b[^>]*>", head).group(0)
        field = lambda k: (re.search(rf'{k}="([^"]*)"', image) or [0, ""])[1]
        where = field("location").split(":")
        width, height, planes = map(int, field("geometry").split(":"))
        if planes != 1 or field("sampleFormat") != "Float32" or field("compression") or where[0] != "attachment":
            return None, None
        f.seek(int(where[1]))
        data = np.frombuffer(f.read(width * height * 4), "<f4").reshape(height, width).copy()
    card = re.search(r'FITSKeyword name="FILTER" value="([^"]*)"', head)
    return data, card.group(1).strip("' ") if card else ""


def band_of(path, card):
    """Ha, OIII or SII from the filter card, or the file's name when the card says nothing."""
    names = {"h": "Ha", "ha": "Ha", "o": "OIII", "oiii": "OIII", "s": "SII", "sii": "SII"}
    if card.strip().lower() in names:
        return names[card.strip().lower()]
    if card.strip().lower() not in ("", "nofilter"):
        return None
    found = re.findall(r"(?<![a-z])(ha|oiii|sii)(?![a-z])", Path(path).stem.lower())
    return names[found[-1]] if len(set(found)) == 1 else None


def master_tile(path):
    """A narrowband master with its stars brought to about our width in pixels
    (4), as (tile with its nebula spanning 1, band, key), or None."""
    import stacking
    data, card = read_image(path)
    band = band_of(path, card or "")
    if data is None or band is None:
        return None
    data = np.nan_to_num(data)[64:-64, 64:-64]
    data = data - np.median(data)
    spread = 1.4826 * np.median(np.abs(data[::4, ::4]))
    stars = stacking.find_stars(data / max(spread, 1e-9) + 10, 200)
    stars = stars[stars[:, 4] > 0.6] if len(stars) else stars
    if len(stars) < 20:
        return None
    width = float(np.median(stars[:, 3]))
    if width > 4:
        data = ndimage.zoom(ndimage.gaussian_filter(data, 0.4 * width / 4), 4 / width, order=1)
    else:
        data = ndimage.gaussian_filter(data, np.sqrt(16 - width ** 2) / 2.355)
    data = data - np.median(data)
    noise = 1.4826 * np.median(np.abs((data - ndimage.gaussian_filter(data, 2))[::2, ::2]))
    coarse = ndimage.median_filter(data[::8, ::8], 25)
    span = float(np.percentile(coarse, 98) - np.percentile(coarse, 2))
    if span / max(noise, 1e-9) < 1.8 or min(data.shape) < 2 * CROP:
        return None
    # The file's own name: different targets can share a folder name ("master") and a filter.
    return (data / span).astype(np.float32), band, "/".join(Path(path).parts[-3:]), round(width, 2)


def try_master(path):
    """(tile or None, why it was not used); one unreadable file does not stop the rest."""
    try:
        made = master_tile(path)
    except Exception as e:
        return None, f"unreadable: {type(e).__name__}"
    return made, None if made else "refused: no narrowband nebula, or too few stars"


def same_master(a, b):
    """One set kept as both FITS and XISF: same filter, same size, the same pixels."""
    if a[1] != b[1] or a[0].shape != b[0].shape:
        return False
    return float(np.corrcoef(a[0][::8, ::8].ravel(), b[0][::8, ::8].ravel())[0, 1]) > 0.999


class Survey:
    """IGAPS Ha nebulae at our scale and sharpness, with our own real noise:
    the difference of a kept pair. The clean picture is the target."""

    def __init__(self, folder, data, seed=1, masters=()):
        import multiprocessing
        from concurrent.futures import ProcessPoolExecutor
        self.rng = np.random.default_rng(seed)
        self.drawn = {}
        paths = sorted(map(str, Path(folder).glob("*.fits.fz"))) if folder else []
        # The cache is named by the frames and the code that made it: a kept
        # one from an older filter was silently reused on 22 November 2026.
        key = hashlib.sha256(json.dumps([[Path(p).name, Path(p).stat().st_size] for p in paths]).encode()
                             + inspect.getsource(survey_tile).encode()).hexdigest()[:16]
        cache = Path(folder or data).parent / f"survey-tiles-{key}.npy"
        if not paths:
            self.tiles = []
        elif cache.exists():
            self.tiles = list(np.load(cache))
        else:
            with ProcessPoolExecutor(12, mp_context=multiprocessing.get_context("spawn")) as pool:
                self.tiles = [t for t in pool.map(survey_tile, paths, chunksize=8) if t is not None]
            np.save(cache, np.stack(self.tiles))
        self.noise = Pairs(data, ("train",), seed)
        self.masters, self.used, self.census = {}, [], {}
        files = sorted({str(f) for m in masters for f in Path(m).rglob("*")
                        if f.suffix.lower() in (".fit", ".fits", ".xisf")
                        and "Lights" not in f.parts and "Flats" not in f.parts and "MasterDarks" not in f.parts
                        and "ngc660" not in f.name.lower()})
        if files:
            key = hashlib.sha256(json.dumps([[Path(f).name, Path(f).stat().st_size] for f in files]).encode()
                                 + (inspect.getsource(master_tile) + inspect.getsource(same_master)).encode()
                                 ).hexdigest()[:16]
            kept = Path(folder or data).parent / f"master-tiles-{key}.npz"
            if kept.exists():
                with np.load(kept, allow_pickle=False) as z:
                    found = [(z[f"t{i}"], str(z["bands"][i]), str(z["keys"][i]), float(z["widths"][i]))
                             for i in range(len(z["bands"]))]
                    self.census = json.loads(str(z["census"]))
            else:
                with ProcessPoolExecutor(6, mp_context=multiprocessing.get_context("spawn")) as pool:
                    made = list(pool.map(try_master, files))
                decoded = [t for t, _ in made if t is not None]
                found = []
                for t in decoded:
                    if not any(same_master(t, k) for k in found):
                        found.append(t)
                self.census = {"discovered": len(files), "decoded": len(decoded),
                               "duplicates": len(decoded) - len(found), "sampled": len(found),
                               "not_used": {"/".join(Path(p).parts[-3:]): why for p, (_, why) in zip(files, made) if why}}
                np.savez(kept, bands=np.array([t[1] for t in found]), keys=np.array([t[2] for t in found]),
                         widths=np.array([t[3] for t in found]), census=np.array(json.dumps(self.census)),
                         **{f"t{i}": t[0] for i, t in enumerate(found)})
            for tile, band, name, _ in found:
                self.masters.setdefault(band, []).append((tile, name))
            share = (0.5 if self.tiles else 1.0) / len(self.masters) if self.masters else 0
            self.used = [{"master": name, "band": band, "star_width_px": width, "size": list(tile.shape),
                          "chance_per_survey_crop": round(share / len(self.masters[band]), 4)}
                         for tile, band, name, width in found]

    def crop(self):
        if self.masters and (not self.tiles or self.rng.random() < 0.5):   # each band equally, so OIII and SII are not swamped
            bands = sorted(self.masters)
            band = bands[self.rng.integers(len(bands))]
            group = self.masters[band]
            tile, name = group[self.rng.integers(len(group))]
            source = f"master {name}"
        else:
            tile = self.tiles[self.rng.integers(len(self.tiles))]
            source = "survey Ha"
        self.drawn[source] = self.drawn.get(source, 0) + 1
        r, c = self.rng.integers(tile.shape[0] - CROP), self.rng.integers(tile.shape[1] - CROP)
        clean = np.rot90(tile[r:r + CROP, c:c + CROP], self.rng.integers(4)).copy()
        if self.rng.integers(2):
            clean = clean[:, ::-1].copy()
        # A master keeps some noise of its own, which would be in input and target
        # alike: its brightness is capped so that stays under a quarter of what we add.
        own = 1.4826 * float(np.median(np.abs(clean - ndimage.gaussian_filter(clean, 2))))
        top = min(12.0, 0.25 / max(own, 1e-6))
        clean = clean * float(self.rng.uniform(min(1.0, top), top))   # the nebula, in our noise
        x, y, s, _ = self.noise.crop()
        grain = x - y
        grain = grain - ndimage.gaussian_filter(grain, 8)
        # Stars leave shape differences between the halves, not noise.
        clear = s < 1.5
        if clear.mean() < 0.5:
            clear = np.ones_like(clear)
        grain = grain / max(1.4826 * float(np.median(np.abs(grain[clear] - np.median(grain[clear])))), 1e-6)
        grain = np.where(clear, grain, self.rng.standard_normal(grain.shape, dtype=np.float32))    # unit noise, as s says
        grain = np.clip(grain, -6, 6)
        return (clean + grain).astype(np.float32), clean.astype(np.float32), np.ones_like(s), np.ones_like(s)

    def arrays(self, count):
        rows = [self.crop() for _ in range(count)]
        return [np.stack([r[k] for r in rows])[:, None] for k in range(4)]


def feed(torch, pairs, survey, repeats, workers):
    """Batches made ahead by CPU workers, so the GPU does not wait for Python. Forked, so
    the workers share the tiles and the mapped pairs. Each batch says which sources it drew."""
    from torch.utils.data import DataLoader, IterableDataset, get_worker_info

    class Stream(IterableDataset):
        def __iter__(self):
            info = get_worker_info()
            if info:
                torch.set_num_threads(1)
                for k, source in enumerate((pairs, survey, survey.noise if survey else None, repeats)):
                    if source:
                        source.rng = np.random.default_rng([11 + k, info.id])
            while True:
                if survey:
                    survey.drawn = {}
                yield (pairs.arrays(), survey.arrays(4) if survey else [], repeats.arrays(2) if repeats else [],
                       json.dumps(survey.drawn if survey else {}))

    return iter(DataLoader(Stream(), batch_size=None, num_workers=workers, pin_memory=True,
                           persistent_workers=workers > 0, prefetch_factor=4 if workers else None,
                           multiprocessing_context="fork" if workers else None))


def loss_of(net, x, y, s, mask):
    # In linear units, weighted by the input's own noise, never by the target's.
    return (mask * ((net(x, s) - y) / s) ** 2).sum() / mask.sum().clamp(min=1)


def train(args):
    import torch
    device = "cuda"
    torch.manual_seed(7)
    net = network().to(device)
    pairs, check = Pairs(args.data, ("train",)), Pairs(args.data, ("check",), seed=5)
    survey = Survey(args.survey, args.data, masters=args.masters or ()) if args.survey or args.masters else None
    repeats = Pairs(args.repeats, ("train",), seed=9) if args.repeats else None
    if survey:
        print(f"survey: {len(survey.tiles)} frames with nebula; masters "
              f"{ {k: len(v) for k, v in survey.masters.items()} }", flush=True)
    if repeats:
        print(f"repeated survey exposures: {len(repeats.parts)} real pairs", flush=True)
    if survey:
        print(f"masters: {json.dumps({k: v for k, v in survey.census.items() if k != 'not_used'})}", flush=True)
    fixed = [check.batch(torch, device) for _ in range(12)]
    opt = torch.optim.AdamW(net.parameters(), 2e-4, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, 6e-4, total_steps=args.steps, pct_start=0.1)
    best, began, waited = None, time.time(), 0.0
    drawn = {}
    batches = feed(torch, pairs, survey, repeats, args.workers)
    to_gpu = lambda group: [torch.as_tensor(a).to(device, non_blocking=True) for a in group]
    for step in range(1, args.steps + 1):
        before = time.time()
        own, outside, again, sources = next(batches)
        waited += time.time() - before
        for k, n in json.loads(sources).items():
            drawn[k] = drawn.get(k, 0) + n
        loss = loss_of(net, *to_gpu(own))
        extras = []
        if survey:
            extras.append(loss_of(net, *to_gpu(outside)))
        if repeats:
            extras.append(loss_of(net, *to_gpu(again)))
        if extras:
            loss = 0.5 * loss + 0.5 * sum(extras) / len(extras)
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(net.parameters(), 2.0)
        opt.step()
        sched.step()
        if step % 500 == 0 or step == args.steps:
            net.eval()
            with torch.no_grad():
                score = float(np.mean([loss_of(net, *b).item() for b in fixed]))
            net.train()
            print(f"step {step}: checking loss {score:.4f}; {step / (time.time() - began):.1f} steps/s, "
                  f"{100 * waited / (time.time() - began):.0f}% of the time waiting for data", flush=True)
            if best is None or score < best:
                best = score
                torch.save({"state": net.state_dict(), "step": step, "score": score, "survey": bool(survey),
                            "masters": list(args.masters or ()), "repeats": args.repeats}, args.out)
                # What this model learned from, how each master was resampled, and the crops each gave.
                Path(args.out).with_suffix(".sources.json").write_text(json.dumps({
                    "own_pairs": len(pairs.parts), "survey": args.survey, "survey_frames": len(survey.tiles) if survey else 0,
                    "masters": survey.used if survey else [], "master_files": survey.census if survey else {},
                    "crops_drawn": drawn,
                    "real_pairs": args.repeats, "real_pair_count": len(repeats.parts) if repeats else 0,
                    "loss_shares": {"own": 0.5 if survey or repeats else 1.0,
                                    "each_extra": 0.5 / ((1 if survey else 0) + (1 if repeats else 0))
                                    if survey or repeats else 0}, "step": step}, indent=1))
    print(f"kept {args.out}: checking loss {best:.4f}", flush=True)


def infer(net, torch, x, s, device, tile=512, overlap=64):
    """The whole picture in overlapping tiles, then its large-scale light put
    back from the input, so the model can change only fine detail."""
    h, w = x.shape
    total, weight = np.zeros((h, w), np.float32), np.zeros((h, w), np.float32)
    ramp = np.minimum(np.arange(1, tile + 1), np.arange(tile, 0, -1)).clip(max=overlap) / overlap
    window = np.outer(ramp, ramp).astype(np.float32)
    rows = sorted({*range(0, max(h - tile, 1), tile - overlap), max(h - tile, 0)})
    cols = sorted({*range(0, max(w - tile, 1), tile - overlap), max(w - tile, 0)})
    places = [(r, c) for r in rows for c in cols]
    with torch.no_grad():
        for i in range(0, len(places), 4):      # four 512 px tiles fit the 1080's memory
            group = places[i:i + 4]
            take = lambda image: torch.from_numpy(np.stack([np.array(image[r:r + tile, c:c + tile], np.float32)
                                                            for r, c in group])[:, None]).to(device, non_blocking=True)
            done = net(take(x), take(s)).cpu().numpy()[:, 0]
            for (r, c), out in zip(group, done):
                total[r:r + tile, c:c + tile] += out * window
                weight[r:r + tile, c:c + tile] += window
    out = total / np.maximum(weight, 1e-6)
    return out + ndimage.gaussian_filter(np.asarray(x) - out, 32)


def protected(x, out):
    """Stars from the input and only the nebula and sky from the model: the
    first models widened stars 7% and changed their light by 4 to 22%."""
    fine = x - ndimage.median_filter(x, size=9)
    noise = 1.4826 * np.median(np.abs(fine[::3, ::3]))
    star = ndimage.binary_dilation(fine > 5 * noise, iterations=4).astype(np.float32)
    soft = np.clip(ndimage.gaussian_filter(star, 1.5) * 1.6, 0, 1)
    return soft * x + (1 - soft) * out


def starlet(plane, strength=(3.0, 2.0, 1.0)):
    """The plain baseline: wavelet shrinkage scale by scale, the same method as
    colour.quietened, with its strength set from outside to match the grain."""
    smooth, details = plane, []
    for level in range(len(strength)):
        kernel = np.zeros(4 * 2 ** level + 1, np.float32)
        kernel[:: 2 ** level] = np.array([1, 4, 6, 4, 1], np.float32) / 16
        wider = ndimage.convolve1d(ndimage.convolve1d(smooth, kernel, axis=0, mode="mirror"), kernel, axis=1, mode="mirror")
        details.append(smooth - wider)
        smooth = wider
    out = smooth
    for detail, k in zip(details, strength):
        limit = k * 1.4826 * float(np.median(np.abs(detail[::3, ::3])))
        out = out + detail * np.clip((np.abs(detail) - limit) / max(limit, 1e-6), 0, 1)
    return out


def grain(a, sky):
    d = a - ndimage.gaussian_filter(a, 3)
    return 1.4826 * float(np.median(np.abs(d[sky] - np.median(d[sky]))))


def matched(x, sky, target, make):
    lo, hi = 0.0, 6.0
    for _ in range(16):
        k = (lo + hi) / 2
        if grain(make(k), sky) > target:
            lo = k
        else:
            hi = k
    return make(hi), hi


def star_change(x, out):
    """Star flux and width in fixed apertures at the input's positions. Finding
    the stars again in the output counted more pixels once its sky was quieter,
    and reported up to 22% more light in stars it had not changed."""
    import stacking
    reach = 15
    yy, xx = np.mgrid[-reach:reach + 1, -reach:reach + 1]
    radius = np.hypot(yy, xx)
    core, ring = radius <= 6, (radius > 9) & (radius <= 14)

    def measure(a, x0, y0):
        c, r = int(round(x0)), int(round(y0))
        if not (reach <= r < a.shape[0] - reach and reach <= c < a.shape[1] - reach):
            return None
        cut = a[r - reach:r + reach + 1, c - reach:c + reach + 1]
        level = np.median(cut[ring])
        light = np.maximum(cut - level, 0) * core
        total = light.sum()
        if total <= 0:
            return None
        mx, my = (light * xx).sum() / total, (light * yy).sum() / total
        spread = (light * ((xx - mx) ** 2 + (yy - my) ** 2)).sum() / total / 2
        return float((cut - level)[core].sum()), 2.355 * float(np.sqrt(max(spread, 1e-6)))

    flux, width = [], []
    for x0, y0 in stacking.find_stars(x + 10.0, 300)[:, :2]:
        before, after = measure(x, x0, y0), measure(out, x0, y0)
        if before and after and before[0] > 20:
            flux.append(after[0] / before[0])
            width.append(after[1] / before[1])
    if len(flux) < 10:
        return None
    return {"stars": len(flux), "flux_change": float(np.median(flux) - 1), "width_change": float(np.median(width) - 1)}


def faint_glow(x, s, run):
    """A planted soft glow at twice the noise: how much of it comes out."""
    yy, xx = np.mgrid[:x.shape[0], :x.shape[1]]
    glow = 2.0 * np.exp(-((yy - x.shape[0] / 2) ** 2 + (xx - x.shape[1] / 2) ** 2) / (2 * 60.0 ** 2))
    use = glow > 0.6
    change = run(x + glow.astype(np.float32), s) - run(x, s)
    return float((change[use] * glow[use]).sum() / (glow[use] ** 2).sum())


def judge(args):
    import torch
    device = "cuda"
    kept = torch.load(args.model, map_location=device)
    net = network().to(device)
    net.load_state_dict(kept["state"])
    net.eval()
    run = lambda a, b: protected(a, infer(net, torch, a, b, device))
    index = json.loads((Path(args.data) / "index.json").read_text())
    results = []
    for record in index:
        if record["role"] != "test":
            continue
        part = Path(args.data) / record["name"] / "split0"
        x, y, s = (np.load(part / f"{k}.npy").astype(np.float32) for k in "xys")
        valid = np.load(part / "valid.npy")
        fine = x - ndimage.median_filter(x, size=9)
        noise = 1.4826 * np.median(np.abs(fine[valid][::3]))
        star = ndimage.binary_dilation(fine > 5 * noise, iterations=5)
        sky = valid & ~star
        out = run(x, s)
        level = grain(out, sky)
        plain, strength = matched(x, sky, level, lambda k: starlet(x, (k, k * 2 / 3, k / 3)))
        smooth, width = matched(x, sky, level, lambda k: ndimage.gaussian_filter(x, k) if k else x)
        error = lambda a: float(np.sqrt(np.mean((a[sky] - y[sky]) ** 2)))
        base = error(plain)
        changed = star_change(x, out)
        glow = faint_glow(x, s, run)
        glow_base = faint_glow(x, s, lambda a, _: starlet(a, (strength, strength * 2 / 3, strength / 3)))
        row = {"session": record["name"], "filter": record["filter"], "grain_in": round(grain(x, sky), 3),
               "grain_out": round(level, 3), "error_input": round(error(x), 4), "error_blur": round(error(smooth), 4),
               "error_wavelet": round(base, 4), "error_network": round(error(out), 4),
               "gain_over_wavelet": round(1 - error(out) / base, 4), "stars": changed,
               "glow_kept": round(glow, 3), "glow_kept_wavelet": round(glow_base, 3)}
        results.append(row)
        print(json.dumps(row), flush=True)
        if args.save:
            folder = Path(args.save)
            folder.mkdir(parents=True, exist_ok=True)
            np.save(folder / f"{record['name']}-out.npy", out)
    Path(args.model).with_suffix(".judged.json").write_text(json.dumps(results, indent=1))


def prepare(args):
    """Fill the tile caches on the CPU, so a training job starts with its data ready."""
    survey = Survey(args.survey, args.data, masters=args.masters or ())
    print(json.dumps({"survey_frames": len(survey.tiles), "master_files": survey.census}, indent=1), flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("what", choices=["train", "judge", "prepare"])
    ap.add_argument("--data", required=True)
    ap.add_argument("--out")
    ap.add_argument("--model")
    ap.add_argument("--steps", type=int, default=12000)
    ap.add_argument("--survey")
    ap.add_argument("--masters", nargs="*", help="folders of narrowband masters")
    ap.add_argument("--repeats", help="pairs from trainset.py repeats")
    ap.add_argument("--save")
    ap.add_argument("--workers", type=int, default=0, help="CPU processes making batches ahead of the GPU")
    args = ap.parse_args()
    {"train": train, "judge": judge, "prepare": prepare}[args.what](args)


if __name__ == "__main__":
    main()
