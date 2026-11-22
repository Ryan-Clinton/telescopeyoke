#!/usr/bin/env python3
"""Train and judge our own denoiser, on the desktop's GPU (spec, section 5).

    ./denoiser.py train --data DIR --out MODEL.pt [--steps N] [--survey DIR]
    ./denoiser.py judge --data DIR --model MODEL.pt

Pictures only: nothing here touches a raw frame, a stack or a measurement.
PyTorch is needed only by this script, and only on the computer that runs it.
"""
import argparse
import hashlib
import inspect
import json
import time
from pathlib import Path

import numpy as np
from scipy import ndimage

CROP = 256
HELD_OUT = {"NGC2174": (92.4, 20.5), "IC405": (79.1, 34.3)}   # degrees: never trained on
HELD_OUT_CLEAR = 2.0     # degrees from a field: its 0.66 half-diagonal plus a survey CCD's 0.21, with margin
BATCH = 8


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
        self.rng = np.random.default_rng(seed)

    def crop(self):
        while True:
            p = self.parts[self.rng.integers(len(self.parts))]
            h, w = p["x"].shape
            r, c = self.rng.integers(h - CROP), self.rng.integers(w - CROP)
            if p["valid"][r:r + CROP, c:c + CROP].mean() < 0.98:
                continue
            out = [np.array(p[k][r:r + CROP, c:c + CROP], np.float32) for k in ("x", "y", "s")]
            mask = np.array(p["valid"][r:r + CROP, c:c + CROP], np.float32)
            turn, flip = self.rng.integers(4), self.rng.integers(2)
            out = [np.rot90(a, turn) for a in [*out, mask]]
            return [(a[:, ::-1] if flip else a).copy() for a in out]

    def batch(self, torch, device):
        rows = [self.crop() for _ in range(BATCH)]
        return [torch.from_numpy(np.stack([r[k] for r in rows])[:, None]).to(device) for k in range(4)]


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


class Survey:
    """IGAPS Ha nebulae at our scale and sharpness, with our own real noise:
    the difference of a kept pair. The clean picture is the target."""

    def __init__(self, folder, data, seed=1):
        import multiprocessing
        from concurrent.futures import ProcessPoolExecutor
        self.rng = np.random.default_rng(seed)
        paths = sorted(map(str, Path(folder).glob("*.fits.fz")))
        # The cache is named by the frames and the code that made it: a kept
        # one from an older filter was silently reused on 22 November 2026.
        key = hashlib.sha256(json.dumps([[Path(p).name, Path(p).stat().st_size] for p in paths]).encode()
                             + inspect.getsource(survey_tile).encode()).hexdigest()[:16]
        cache = Path(folder).parent / f"survey-tiles-{key}.npy"
        if cache.exists():
            self.tiles = list(np.load(cache))
        else:
            with ProcessPoolExecutor(12, mp_context=multiprocessing.get_context("spawn")) as pool:
                self.tiles = [t for t in pool.map(survey_tile, paths, chunksize=8) if t is not None]
            np.save(cache, np.stack(self.tiles))
        self.noise = Pairs(data, ("train",), seed)

    def crop(self):
        tile = self.tiles[self.rng.integers(len(self.tiles))]
        r, c = self.rng.integers(tile.shape[0] - CROP), self.rng.integers(tile.shape[1] - CROP)
        clean = tile[r:r + CROP, c:c + CROP] * float(self.rng.uniform(1, 12))   # the nebula, in our noise
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

    def batch(self, torch, device, count):
        rows = [self.crop() for _ in range(count)]
        return [torch.from_numpy(np.stack([r[k] for r in rows])[:, None]).to(device) for k in range(4)]


def loss_of(net, x, y, s, mask):
    # In linear units, weighted by the input's own noise, never by the target's.
    return (mask * ((net(x, s) - y) / s) ** 2).sum() / mask.sum().clamp(min=1)


def train(args):
    import torch
    device = "cuda"
    torch.manual_seed(7)
    net = network().to(device)
    pairs, check = Pairs(args.data, ("train",)), Pairs(args.data, ("check",), seed=5)
    survey = Survey(args.survey, args.data) if args.survey else None
    if survey:
        print(f"survey: {len(survey.tiles)} frames with nebula", flush=True)
    fixed = [check.batch(torch, device) for _ in range(12)]
    opt = torch.optim.AdamW(net.parameters(), 2e-4, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, 6e-4, total_steps=args.steps, pct_start=0.1)
    best, began = None, time.time()
    for step in range(1, args.steps + 1):
        x, y, s, mask = pairs.batch(torch, device)
        loss = loss_of(net, x, y, s, mask)
        if survey:
            a, b, c, d = survey.batch(torch, device, 4)
            loss = 0.5 * loss + 0.5 * loss_of(net, a, b, c, d)
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
            print(f"step {step}: checking loss {score:.4f}; {step / (time.time() - began):.1f} steps/s", flush=True)
            if best is None or score < best:
                best = score
                torch.save({"state": net.state_dict(), "step": step, "score": score, "survey": bool(survey)}, args.out)
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
    with torch.no_grad():
        for r in rows:
            for c in cols:
                a = torch.from_numpy(np.array(x[r:r + tile, c:c + tile], np.float32))[None, None].to(device)
                b = torch.from_numpy(np.array(s[r:r + tile, c:c + tile], np.float32))[None, None].to(device)
                total[r:r + tile, c:c + tile] += net(a, b).cpu().numpy()[0, 0] * window
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


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("what", choices=["train", "judge"])
    ap.add_argument("--data", required=True)
    ap.add_argument("--out")
    ap.add_argument("--model")
    ap.add_argument("--steps", type=int, default=12000)
    ap.add_argument("--survey")
    ap.add_argument("--save")
    args = ap.parse_args()
    (train if args.what == "train" else judge)(args)


if __name__ == "__main__":
    main()
