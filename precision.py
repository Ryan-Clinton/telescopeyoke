#!/usr/bin/env python3
"""How precise a night's photometry is, and what limits it.

    ./precision.py frames/WASP-12/20261020-014726 --planet "WASP-12 b"
    ./precision.py SESSION --planet "WASP-12 b" --again     measure the frames again

The night's own frames, measured every way at once, so the ways can be
compared on the same light: plain round apertures of 1 to 3 times the stars'
width and the star-shaped weighting `variables.py` uses; the brightness of
all four Bayer sites and of red, green and blue on their own (each 2x2
superpixel, so nothing is interpolated); each frame with and without its row
stripes taken out; and the target compared with every steady star, the best
20, 10 and 5 of them, the ones like it in brightness and colour, and the 10
nearest it on the sensor.

For every way it reports the target's scatter before the transit (per 10
frames), the bright stars' own scatter, how the scatter falls as more frames
are averaged (it falls as one over the square root of their number for
random noise, and stops falling at a systematic floor: the ratio to that is
`beta`), the depth a box fits, the baseline's slope, and how the target's
light follows the stars' drift across the sensor, their width, the sky and
the airmass. The best ways first.

Stars are found in each frame where its registration (frames.jsonl: the
shift and rotation onto the first frame) puts them, and centred again there.
The measurements are kept (precision-flux.npz) so a second look is quick;
the answer in precision.json. 20 October 2026: the first transit,
WASP-12 b, had a floor of about 20 mmag for every star brighter than G 13,
where photon noise is under 1 mmag (docs/discovery/transit-wasp12b-2026-10-20).
Nothing here moves the mount or uses the camera.
"""
import argparse
import json
import math
import time
from pathlib import Path

import numpy as np

import config
import interface
import records

RADII = (1.0, 1.5, 2.0, 2.5, 3.0)     # aperture radii, times the stars' width (FWHM)
ANNULUS = (4.0, 6.0)                  # the sky round each star, times the FWHM
CHANNELS = ("all", "red", "green", "blue")
VARIANTS = ("destriped", "as read")
APERTURES = tuple(f"{r:g} FWHM" for r in RADII) + ("weighted",)
BIN = 10                              # frames in each point of a light curve
BINS = (1, 2, 5, 10, 20, 40)          # frames averaged, for the scatter's fall
FAINTEST = 14.0                       # G: comparison stars no fainter than this
EDGE = 80                             # pixels: stars nearer the edge than this are left out
SETS = ("all", "best 20", "best 10", "best 5", "like it", "nearest 10")


def positions(xy, shift, rotation):
    """Where stars at `xy` on the first frame are in a frame that
    registration moved onto it by `rotation` degrees and `shift` (p_first =
    R p + t, stacking.warp)."""
    a = math.radians(rotation)
    r = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    return (np.asarray(xy, float) - np.asarray(shift, float)) @ r


def centred(image, xy, box=5):
    """Each star centred again on its light within `box` pixels; where there
    is too little light, the place given."""
    out = np.array(xy, float)
    h, w = image.shape
    for k, (x, y) in enumerate(out):
        ix, iy = int(round(x)), int(round(y))
        if not (box <= ix < w - box and box <= iy < h - box):
            continue
        cut = image[iy - box:iy + box + 1, ix - box:ix + box + 1]
        light = np.clip(cut - np.median(cut), 0, None)
        total = light.sum()
        if total > 0:
            yy, xx = np.mgrid[-box:box + 1, -box:box + 1]
            out[k] = (ix + (light * xx).sum() / total, iy + (light * yy).sum() / total)
    return out


def apertures(image, xy, fwhm, radii=RADII, annulus=ANNULUS):
    """Each star's light in round apertures of `radii` times the FWHM, less
    the sky's median in the annulus round it: [stars, radii]."""
    outer = int(math.ceil(annulus[1] * fwhm)) + 1
    yy, xx = np.mgrid[-outer:outer + 1, -outer:outer + 1]
    out = np.full((len(xy), len(radii)), np.nan)
    h, w = image.shape
    for k, (x, y) in enumerate(xy):
        ix, iy = int(round(x)), int(round(y))
        if not (outer <= ix < w - outer and outer <= iy < h - outer):
            continue
        cut = image[iy - outer:iy + outer + 1, ix - outer:ix + outer + 1]
        d = np.hypot(xx - (x - ix), yy - (y - iy))
        ring = cut[(d >= annulus[0] * fwhm) & (d < annulus[1] * fwhm)]
        sky = float(np.median(ring)) if ring.size else 0.0
        for j, r in enumerate(radii):
            inside = d < r * fwhm
            out[k, j] = float(cut[inside].sum() - sky * inside.sum())
    return out


def measure_frame(path, exposure, gain, xy, shift, rotation, fwhm):
    """One frame, every way: [variants, channels, stars, apertures]."""
    import forced
    import stacking
    from camera import colour
    calibration = stacking._calibration(exposure, gain)
    raw = calibration.apply(stacking.load_light(path)[0])
    here = positions(xy, shift, rotation)
    out = np.full((len(VARIANTS), len(CHANNELS), len(xy), len(APERTURES)), np.nan)
    for v, frame in enumerate((stacking.destripe(raw), raw)):
        rgb = stacking.clean(colour(frame))
        lum = rgb.sum(axis=2)
        if v == 0:
            here = centred(lum, here)
        for c, image in enumerate((lum, rgb[..., 0], rgb[..., 1], rgb[..., 2])):
            out[v, c, :, :len(RADII)] = apertures(image, here, fwhm)
            out[v, c, :, -1] = forced.weighted(image - np.median(image), here, fwhm, max(fwhm, 2.0))
    return out


def chosen_stars(session, planet):
    """The target and the comparison stars, from the night's measurements
    (variables-BIN.json): rows (ra, dec, G, colour), their places on the
    first stack, the target's index, and the stars' width."""
    import transits
    import variables
    kept = json.loads((session / f"variables-{BIN}.json").read_text(encoding="utf-8"))
    p = next((r for r in transits.planets() if r["planet"].replace(" ", "").lower()
              == planet.replace(" ", "").lower()), None)
    if p is None:
        raise interface.Refusal("TARGET_UNKNOWN", f"'{planet}' is not among the transiting planets kept.")
    stars = np.array([[np.nan if v is None else v for v in row] for row in kept["stars"]], float)
    xy = np.array(kept["xy"], float)
    near = np.hypot((stars[:, 0] - p["ra"]) * math.cos(math.radians(p["dec"])), stars[:, 1] - p["dec"]) * 3600
    target = int(np.argmin(near))
    if near[target] > 5:
        raise interface.Refusal("NO_SESSION", f"{p['star']} is not among the stars measured in {session.name}.")
    exposure = json.loads((session / "session.json").read_text(encoding="utf-8")).get("exposure")
    alone = np.array(kept["alone"], bool)
    glow = np.array([np.inf if v is None else v for v in kept["glow"]], float)
    comps = alone & (glow <= variables.GLOW) & (stars[:, 2] >= variables.trusted(exposure)) \
        & (stars[:, 2] <= FAINTEST)
    comps[target] = False
    pick = np.r_[target, np.flatnonzero(comps)]
    return p, stars[pick], xy[pick], float(kept["fwhm_px"])


def measure_night(session, planet, say=print, again=False, workers=None, first=None):
    """Every kept frame (or the `first` few, for a quick try) measured every
    way, kept in precision-flux.npz."""
    import stacking
    import vet
    kept = session / "precision-flux.npz"
    p, stars, xy, fwhm = chosen_stars(session, planet)
    frames = vet.restack_frames(session)[:first]
    if first:
        kept = session / f"precision-flux-first{first}.npz"
    if kept.exists() and not again:
        saved = np.load(kept)
        # The flux is [variants, channels, frames, stars, apertures].
        if saved["flux"].shape[2] == len(frames) and saved["flux"].shape[3] == len(xy):
            say(f"{session.name}: {len(frames)} frames, as measured before")
            return p, stars, {k: saved[k] for k in saved.files}
    log = {r["index"]: r for r in (json.loads(line) for line in
                                   (session / "frames.jsonl").read_text(encoding="utf-8").splitlines() if line)}
    head = stacking.load_light(frames[0])[1]
    exposure, gain = float(head.get("EXPTIME", 0)), int(float(head.get("GAIN", 0)))
    rows, began = [], time.monotonic()
    say(f"{session.name}: measuring {len(xy)} stars in {len(frames)} frames, {len(VARIANTS) * len(CHANNELS)} ways")
    with stacking.worker_pool(workers) as pool:
        jobs = []
        for path in frames:
            r = log.get(int(path.stem.split("-")[1]), {})
            jobs.append(pool.submit(measure_frame, path, exposure, gain, xy, r.get("shift") or (0.0, 0.0),
                                    r.get("rotation") or 0.0, fwhm))
            rows.append(r)
        flux = []
        for n, job in enumerate(jobs, 1):
            flux.append(job.result())
            if n % 100 == 0 or n == len(jobs):
                left = (time.monotonic() - began) / n * (len(jobs) - n)
                say(f"  {n} of {len(jobs)} frames" + (f"; about {left / 60:.0f} min left" if n < len(jobs) else ""))
    # Each frame's middle, from its own DATE-OBS (the start of the exposure).
    from astropy.time import Time
    jd = np.array([Time(stacking.load_light(f)[1]["DATE-OBS"]).jd + exposure / 2 / 86400 for f in frames])
    out = {"flux": np.moveaxis(np.array(flux), 0, 2),      # [variants, channels, frames, stars, apertures]
           "jd": jd,
           "x": np.array([(r.get("shift") or (0, 0))[0] for r in rows], float),
           "y": np.array([(r.get("shift") or (0, 0))[1] for r in rows], float),
           "fwhm": np.array([r.get("fwhm", np.nan) for r in rows], float),
           "sky": np.array([r.get("background", np.nan) for r in rows], float)}
    np.savez_compressed(kept, **out)
    return p, stars, out


def airmass(jd, ra, dec):
    """The target's airmass at each time, from the site in config.toml; NaN
    without one."""
    try:
        site = config.load()["site"]
    except (SystemExit, KeyError, OSError):
        return np.full(len(jd), np.nan)
    from astropy.coordinates import AltAz, EarthLocation, SkyCoord
    from astropy.time import Time
    import astropy.units as u
    where = EarthLocation(lat=site["latitude"] * u.deg, lon=site["longitude"] * u.deg,
                          height=site.get("elevation_m", 0) * u.m)
    alt = SkyCoord(ra * u.deg, dec * u.deg).transform_to(AltAz(obstime=Time(jd, format="jd"), location=where)).alt
    return 1 / np.sin(np.radians(np.clip(alt.deg, 5, 90)))


def robust(values):
    v = np.asarray(values, float)
    v = v[np.isfinite(v)]
    return 1.4826 * float(np.median(np.abs(v - np.median(v)))) if len(v) > 4 else np.nan


def binned(values, n):
    v = np.asarray(values, float)
    m = len(v) // n
    return np.nanmean(v[:m * n].reshape(m, n), axis=1) if m else np.array([])


def falls(mag, bins=BINS):
    """The scatter (mmag) as more frames are averaged, and beta: the scatter
    of the averages against what random noise alone would leave, the median
    over the averages of 5 frames or more (one size alone is a noisy guide)."""
    mag = np.asarray(mag, float)
    mag = mag[np.isfinite(mag)]
    rms = {}
    for n in bins:
        means = binned(mag, n)
        if len(means) >= 5:
            rms[n] = 1000 * float(np.std(means, ddof=1))
    if 1 not in rms:
        return rms, np.nan
    ratios = [rms[n] / (rms[1] / math.sqrt(n)) for n in rms if n >= 5]
    return rms, float(np.median(ratios)) if ratios else np.nan


def light_curve(target, comps):
    """The target's magnitude against the sum of the comparison stars."""
    total = np.nansum(comps, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        return -2.5 * np.log10(target / total)


def ranked(flux):
    """The comparison stars in order of their own steadiness over the whole
    night, each against the sum of the others. Not over the target's
    baseline alone: stars picked for being steady there would flatter the
    target's scatter there, where it is judged."""
    scores = []
    total = np.nansum(flux, axis=1)
    for j in range(flux.shape[1]):
        with np.errstate(divide="ignore", invalid="ignore"):
            m = -2.5 * np.log10(flux[:, j] / (total - flux[:, j]))
        scores.append(robust(binned(m, BIN)))
    return np.argsort(np.nan_to_num(scores, nan=np.inf))


def comparison_sets(flux, stars, xy=None):
    """The comparison sets: indices into the comparison stars."""
    order = ranked(flux)
    target = stars[0]
    comps = stars[1:]
    sets = {"all": np.arange(flux.shape[1]), "best 20": order[:20], "best 10": order[:10], "best 5": order[:5]}
    if np.isfinite(target[3]):
        like = np.flatnonzero((np.abs(comps[:, 2] - target[2]) < 1.0) & (np.abs(comps[:, 3] - target[3]) < 0.3))
        if len(like) >= 3:
            sets["like it"] = like
    if xy is not None:
        sets["nearest 10"] = np.argsort(np.hypot(*(xy[1:] - xy[0]).T))[:10]
    return sets


def correlation(a, b):
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 10 or np.std(a[ok]) == 0 or np.std(b[ok]) == 0:
        return None
    return round(float(np.corrcoef(a[ok], b[ok])[0, 1]), 2)


def accepted_only(session, data, frames):
    """The measurements of the frames the run kept (frames.jsonl
    "accepted"): a frame thrown out for cloud is not the star's light.
    20 October 2026: the 19 cloudy frames at the end made the depths nonsense."""
    log = {r["index"]: r for r in (json.loads(line) for line in
                                   (session / "frames.jsonl").read_text(encoding="utf-8").splitlines() if line)}
    keep = np.array([log.get(int(f.stem.split("-")[1]), {}).get("accepted", False) for f in frames])
    out = dict(data)
    out["flux"] = data["flux"][:, :, keep]
    for k in ("jd", "x", "y", "fwhm", "sky"):
        out[k] = data[k][keep]
    return out


def judge(p, stars, xy, data):
    """Every way's figures, the best first."""
    import transits
    flux, jd = data["flux"], data["jd"]
    middle = transits.transits_between(p, np.nanmin(jd) - 0.5, np.nanmax(jd) + 0.5)
    middle = min(middle, key=lambda m: abs(m - np.nanmean(jd))) if middle else None
    half = p["hours"] / 48
    before = jd < (middle - half) if middle else np.ones(len(jd), bool)
    if before.sum() < 3 * BIN:
        raise interface.Refusal("NO_SESSION", "Too little of the night was before the transit to measure its baseline.")
    mass = airmass(jd, p["ra"], p["dec"])
    rows = []
    for v, variant in enumerate(VARIANTS):
        for c, channel in enumerate(CHANNELS):
            for a, aperture in enumerate(APERTURES):
                f = flux[v, c, :, :, a]
                target, comps = f[:, 0], f[:, 1:]
                bright = [robust(binned(-2.5 * np.log10(comps[:, j] / (np.nansum(comps, axis=1) - comps[:, j]))
                                        [before], BIN))
                          for j in np.flatnonzero(stars[1:, 2] < 13.0)]
                bright_rms = 1000 * float(np.nanmedian(bright)) if bright else np.nan
                for name, pick in comparison_sets(comps, stars, xy).items():
                    mag = light_curve(target, comps[:, pick])
                    mag = mag - np.nanmedian(mag[before])
                    scatter, beta = falls(mag[before])
                    # The scatter in the transit too, about its own level: a way picked
                    # for a quiet baseline alone could be quiet there by chance.
                    during = binned(np.where(before, np.nan, mag), BIN)
                    inside = 1000 * robust(during[np.isfinite(during)]) if np.isfinite(during).sum() > 4 else np.nan
                    t = binned(jd, BIN)
                    m = binned(mag, BIN)
                    fit = transits.fit(t, m, middle, p["hours"]) if middle else None
                    ok = before & np.isfinite(mag)
                    slope = 1000 / 24 * float(np.polyfit(jd[ok], mag[ok], 1)[0]) if ok.sum() > 10 else np.nan   # mmag an hour
                    rows.append({
                        "stripes": variant, "channel": channel, "aperture": aperture, "comparison": name,
                        "comparison_stars": int(len(pick)),
                        "baseline_rms_mmag": round(scatter.get(BIN, np.nan), 2),
                        "transit_rms_mmag": round(inside, 2),
                        "bright_star_rms_mmag": round(bright_rms, 2),
                        "rms_by_frames": {str(k): round(val, 2) for k, val in scatter.items()},
                        "beta": round(beta, 2) if np.isfinite(beta) else None,
                        "depth": fit and fit["depth"], "depth_error": fit and fit["depth_error"],
                        "baseline_slope_mmag_per_h": round(slope, 2) if np.isfinite(slope) else None,
                        "follows": {k: correlation(mag[before], data[s][before] if s != "airmass" else mass[before])
                                    for k, s in (("x", "x"), ("y", "y"), ("width", "fwhm"), ("sky", "sky"),
                                                 ("airmass", "airmass"))}})
    # The worse of the two scatters, so a way is not chosen for one quiet stretch.
    rows.sort(key=lambda r: np.nan_to_num(np.nanmax([r["baseline_rms_mmag"], r["transit_rms_mmag"]]), nan=1e9))
    return {"planet": p["planet"], "predicted_middle": middle, "frames": int(len(jd)),
            "frames_before": int(before.sum()), "ways": rows}


def run(args, say=print):
    session = Path(args.session)
    if not session.is_dir():
        raise interface.Refusal("NO_SESSION", f"No session folder {session}.")
    p, stars, data = measure_night(session, args.planet, say, again=args.again, first=args.first)
    import vet
    data = accepted_only(session, data, vet.restack_frames(session)[:args.first])
    _, _, xy, _ = chosen_stars(session, args.planet)
    answer = judge(p, stars, xy, data)
    answer["session"] = session.name
    records.write(session / "precision.json", answer, stamp=True, default=float)
    ways = answer["ways"]
    usual = next((w for w in ways if (w["stripes"], w["channel"], w["aperture"], w["comparison"])
                  == ("destriped", "all", "weighted", "all")), None)
    say(f"{p['planet']}, {answer['frames']} frames ({answer['frames_before']} before the transit); "
        f"scatter per {BIN} frames before it / during it, best ways first (the worse of the two):")
    for w in ways[:12] + ([usual] if usual and usual not in ways[:12] else []):
        say(f"  {w['baseline_rms_mmag']:6.1f} / {w['transit_rms_mmag']:5.1f} mmag  (stars G<13: "
            f"{w['bright_star_rms_mmag']:5.1f})  beta "
            f"{w['beta']}  {w['stripes']}, {w['channel']}, {w['aperture']}, {w['comparison']} "
            f"({w['comparison_stars']})  depth {w['depth']} ± {w['depth_error']}%  follows {w['follows']}"
            + ("   <- as measured until now" if w is usual else ""))
    say(f"All {len(ways)} ways: {session / 'precision.json'}")
    return answer


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("session", help="the night's session folder")
    ap.add_argument("--planet", required=True, help="the planet, as the archive names it (\"WASP-12 b\")")
    ap.add_argument("--again", action="store_true", help="measure the frames again, not from precision-flux.npz")
    ap.add_argument("--first", type=int, metavar="N", help="only the first N frames: a quick try")
    args = ap.parse_args()
    interface.main("precision", lambda: run(args), False)


if __name__ == "__main__":
    main()
