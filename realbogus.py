#!/usr/bin/env python3
"""Real or bogus: how likely a candidate is a new point of light rather than
something the subtraction left behind, learnt from this rig's own nights.

    ./realbogus.py train            learn from every night with a subtraction (minutes; run it in the background)
    ./realbogus.py train --plant 300 --runs 3
    ./realbogus.py score SESSION    the probability for each candidate of a night already vetted
    ./realbogus.py show             what the model learnt and how much it removes

A person's dismissals are too few to learn from yet, so the examples are
made the way the big surveys made theirs. Real ones are fake stars planted
in the night's own stack before the subtraction (difference.py's
planting), with the night's own star shape and noise: whatever a real new
star would look like after this pipeline, they look like. Bogus ones are
every brightening peak above 4 sigma that is not a planted star, and every
fading peak the same, turned over: on a night with no transient they are
what the subtraction alone makes. Candidates a person dismissed with a
label for a fault (noise, hot pixel, edge, bad subtraction, satellite,
cosmic ray, bright-star halo, cloud or tree) are added as bogus.

Each example is described by a few measurements of its patch of the
difference and the reference (FEATURES), and the model is a logistic
regression: one weight a measurement, which can be read and judged. It is
tested night by night: trained on the others, it is asked how many of the
held-out night's false candidates above 5 sigma it would set aside while
keeping 95% of the planted stars found there. That fall in false
candidates is the proof phase 8 asks for (docs/discovery.md).

The probability is advice. vet.py adds it to each candidate's evidence
(`real_bogus`, inferred) and says so in its clues; it never dismisses
anything. Kept in cache/realbogus.json, stamped with the code that made it.
Nothing here moves the mount or uses the camera.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from scipy import optimize
from scipy.spatial import cKDTree

import config
import interface
import records

FEATURES = ("score", "width", "elongation", "sharpness", "dark_lobe", "ring", "on_reference", "offset")
LOW = 4.0            # sigma: peaks this strong are examples; candidates start at difference.THRESHOLD
MATCH = 2.5          # pixels: a peak this near a planted star is that star
KEEP_REAL = 0.95     # the share of planted stars the threshold must keep
PATCH = 8            # pixels round a peak measured
PENALTY = 1.0        # the ridge on the weights, against over-fitting so few nights
FAULTS = ("noise", "hot pixel", "edge", "bad subtraction", "satellite", "cosmic ray", "bright-star halo",
          "cloud or tree")


def path():
    return config.DATA / "cache" / "realbogus.json"


def features(significance, ref, x, y, fwhm):
    """The measurements of one peak at (x, y), in the reference's pixels."""
    h, w = significance.shape
    x0, x1, y0, y1 = max(x - PATCH, 0), min(x + PATCH + 1, w), max(y - PATCH, 0), min(y + PATCH + 1, h)
    s = np.nan_to_num(significance[y0:y1, x0:x1])
    r = np.nan_to_num(ref[y0:y1, x0:x1].astype(float))
    yy, xx = np.mgrid[y0:y1, x0:x1]
    d = np.hypot(xx - x, yy - y)
    peak = float(significance[y, x])
    # only what stands well above the noise, or the noise sets the width
    core = np.where((d <= 4) & (s > 0.25 * peak), s, 0.0)
    total = core.sum() or 1.0
    cx, cy = (core * xx).sum() / total, (core * yy).sum() / total
    cov = np.cov(np.vstack([xx.ravel(), yy.ravel()]), aweights=core.ravel() + 1e-12, bias=True)
    eig = np.sort(np.linalg.eigvalsh(cov))
    width = 2.3548 * float(np.sqrt(max(eig.mean(), 1e-6)))
    around = s[(d >= 5) & (d <= PATCH)]
    near3 = s[d <= 1.5]
    spread = 1.4826 * float(np.median(np.abs(r - np.median(r)))) + 1e-9
    centre = float(np.median(r[d <= 1.5]) - np.median(r))
    return [peak,
            width / max(fwhm, 1.0),
            float(np.sqrt(eig[1] / max(eig[0], 1e-6))),
            float(np.log(max(peak / max(float(near3.mean()), 1e-6), 1e-3))),
            float(s[d <= 6].min()) / peak,
            float(around.mean()) / peak if around.size else 0.0,
            float(np.log1p(max(centre / spread, 0.0))),
            float(np.hypot(cx - x, cy - y))]


def examples_from(significance, usable, ref, fwhm, planted=None, skip=()):
    """(X, y, scores) from one subtraction: planted stars found as real (1),
    every other peak above LOW either way as bogus (0)."""
    import difference
    X, labels = [], []
    spots = planted[0] if planted is not None else np.empty((0, 2))
    tree = cKDTree(spots) if len(spots) else None
    avoid = cKDTree(np.array(skip, float)) if len(skip) else None
    for sign in (1, -1):
        sig = sign * significance
        xs, ys = difference.peaks(sig, usable, threshold=LOW)
        for x, y in zip(xs, ys):
            if avoid is not None and np.isfinite(avoid.query([x, y], distance_upper_bound=MATCH)[0]):
                continue    # a candidate a person is still to judge: neither real nor bogus yet
            if sign == 1 and difference.dipole(sig, x, y):
                continue    # the search leaves these out itself
            is_planted = sign == 1 and tree is not None and \
                np.isfinite(tree.query([x, y], distance_upper_bound=MATCH)[0])
            # the reference as it is either way: is there a star under it?
            X.append(features(sig, ref, int(x), int(y), fwhm))
            labels.append(int(is_planted))
    return np.array(X, float).reshape(-1, len(FEATURES)), np.array(labels, int)


def nights():
    """The nights that have been subtracted, with what they were subtracted from."""
    found = []
    for kept in sorted(config.DATA.glob("frames/*/*/candidates.json")):
        record = json.loads(kept.read_text(encoding="utf-8"))
        if record.get("new") and record.get("reference") and Path(record["new"]).exists() \
                and Path(record["reference"]).exists():
            found.append((kept.parent, record))
    return found


def subtraction_of(folder, record, plant_count, seed):
    """Subtract the night again from its reference, planting fakes; the
    working images come back in a dict."""
    from astropy.io import fits
    import depth
    import difference
    new_path, ref_path = Path(record["new"]), Path(record["reference"])
    new, ref = depth.brightness(fits.getdata(new_path)), depth.brightness(fits.getdata(ref_path))
    name = record.get("object") or depth.object_name(new_path)
    kept = depth.record_path(new_path)
    zeropoint = json.loads(kept.read_text(encoding="utf-8"))["zeropoint"] if kept.exists() else None
    keep = {}
    difference.subtract(new, ref, depth.plate(new, name), depth.plate(ref, name), zeropoint, plant_count,
                        seed=seed, workings=keep)
    return keep


def standardise(X, centre=None, scale=None):
    centre = X.mean(axis=0) if centre is None else np.asarray(centre)
    scale = X.std(axis=0) + 1e-9 if scale is None else np.asarray(scale)
    return (X - centre) / scale, centre, scale


def fit(X, y, penalty=PENALTY):
    """Logistic regression with a ridge, the classes weighted equally."""
    Z, centre, scale = standardise(X)
    weight = np.where(y == 1, 0.5 / max(y.mean(), 1e-9), 0.5 / max(1 - y.mean(), 1e-9))

    def loss(w):
        z = Z @ w[1:] + w[0]
        p = 1 / (1 + np.exp(-np.clip(z, -30, 30)))
        nll = -np.sum(weight * (y * np.log(p + 1e-12) + (1 - y) * np.log(1 - p + 1e-12))) / len(y)
        grad = Z.T @ (weight * (p - y)) / len(y)
        return nll + penalty * np.sum(w[1:] ** 2) / len(y), np.concatenate(
            [[np.sum(weight * (p - y)) / len(y)], grad + 2 * penalty * w[1:] / len(y)])
    w = optimize.minimize(loss, np.zeros(Z.shape[1] + 1), jac=True, method="L-BFGS-B").x
    return {"intercept": float(w[0]), "weights": dict(zip(FEATURES, map(float, w[1:]))),
            "centre": centre.tolist(), "scale": scale.tolist()}


def probability(model, X):
    X = np.atleast_2d(np.asarray(X, float))
    Z, _, _ = standardise(X, model["centre"], model["scale"])
    z = Z @ np.array([model["weights"][f] for f in FEATURES]) + model["intercept"]
    return 1 / (1 + np.exp(-np.clip(z, -30, 30)))


def threshold_for(model, X_real, keep=KEEP_REAL):
    """The probability below which a candidate is likely bogus: the level
    that keeps `keep` of the planted stars."""
    p = np.sort(probability(model, X_real))
    return float(p[int(np.floor((1 - keep) * len(p)))]) if len(p) else 0.5


def judged(model, cut, X, y, at=5.0):
    """At candidates' strength (score >= at): planted kept, bogus set aside."""
    strong = X[:, 0] >= at
    p = probability(model, X[strong]) if strong.any() else np.array([])
    real, bogus = y[strong] == 1, y[strong] == 0
    return {"planted": int(real.sum()), "planted_kept": int((p[real] >= cut).sum()),
            "bogus": int(bogus.sum()), "bogus_set_aside": int((p[bogus] < cut).sum())}


def reference_image(path):
    """A reference stack as one plane of brightness, as vet.py and the
    subtraction see it (a colour stack has three)."""
    from astropy.io import fits
    import depth
    ref = depth.brightness(fits.getdata(path))
    return np.where(ref == 0, np.median(ref[ref != 0]), ref).astype(float)


def human_labels():
    """Features of candidates a person dismissed as faults, from their nights."""
    from astropy.io import fits
    X = []
    for book in config.DATA.glob("candidates/*.json"):
        for k in json.loads(book.read_text(encoding="utf-8")).get("candidates", []):
            if (k.get("dismissed") or {}).get("reason") not in FAULTS:
                continue
            for n in k["nights"]:
                folder = next(config.DATA.glob(f"frames/*/{n['night']}"), None)
                if not n.get("seen") or folder is None or not (folder / "difference.fits").exists():
                    continue
                vetted = json.loads((folder / "vetted.json").read_text(encoding="utf-8"))
                c = next((c for c in vetted["candidates"] if abs(c.get("ra", 1e9) - k["ra"]) < 2e-4
                          and abs(c.get("dec", 1e9) - k["dec"]) < 2e-4), None)
                record = json.loads((folder / "candidates.json").read_text(encoding="utf-8"))
                if c is None:
                    continue
                sig = fits.getdata(folder / "difference.fits").astype(float)
                ref = reference_image(record["reference"])
                X.append(features(sig, ref, c["x"], c["y"], record.get("fwhm_px", 4.8)))
    return np.array(X, float).reshape(-1, len(FEATURES))


def train(plant_count=300, runs=2, say=print):
    began = time.monotonic()
    found = nights()
    if len(found) < 2:
        raise interface.Refusal("NO_SESSION", "Training needs at least two nights that have been subtracted "
                                "(./difference.py or the patrol): it is tested on each against the others.")
    per_night = {}
    for folder, record in found:
        vetted = folder / "vetted.json"
        skip = [(c["x"], c["y"]) for c in (json.loads(vetted.read_text(encoding="utf-8"))["candidates"]
                                           if vetted.exists() else []) if c["verdict"].startswith("unexplained")]
        Xs, ys = [], []
        for run in range(runs):
            keep = subtraction_of(folder, record, plant_count, seed=100 + run)
            X, y = examples_from(keep["significance"], keep["usable"], keep["ref"], keep["fwhm"], keep["planted"],
                                 skip)
            Xs.append(X)
            ys.append(y)
        per_night[folder.name] = (np.vstack(Xs), np.concatenate(ys))
        say(f"{folder.parent.name} {folder.name}: {int(per_night[folder.name][1].sum())} planted found, "
            f"{int((per_night[folder.name][1] == 0).sum())} bogus")
    people = human_labels()
    tests = []
    for held in per_night:
        X = np.vstack([v[0] for k, v in per_night.items() if k != held] + [people])
        y = np.concatenate([v[1] for k, v in per_night.items() if k != held] + [np.zeros(len(people), int)])
        model = fit(X, y)
        cut = threshold_for(model, X[y == 1])
        tests.append(dict(night=held, **judged(model, cut, *per_night[held])))
    X = np.vstack([v[0] for v in per_night.values()] + [people])
    y = np.concatenate([v[1] for v in per_night.values()] + [np.zeros(len(people), int)])
    model = fit(X, y)
    model["cut"] = threshold_for(model, X[y == 1])
    bogus = sum(t["bogus"] for t in tests)
    planted = sum(t["planted"] for t in tests)
    answer = {"features": list(FEATURES), "model": model, "trained_on": {
        "nights": sorted(per_night), "planted": int(y.sum()), "bogus": int((y == 0).sum()),
        "dismissed_by_a_person": len(people), "plant_per_run": plant_count, "runs": runs},
        "tested": tests, "kind": "measured",
        "summary": {"bogus_above_5_sigma": bogus,
                    "set_aside": sum(t["bogus_set_aside"] for t in tests),
                    "share_set_aside": round(sum(t["bogus_set_aside"] for t in tests) / bogus, 3) if bogus else None,
                    "planted_above_5_sigma": planted,
                    "planted_kept": sum(t["planted_kept"] for t in tests),
                    "share_kept": round(sum(t["planted_kept"] for t in tests) / planted, 3) if planted else None},
        "seconds": round(time.monotonic() - began)}
    records.write(path(), answer, stamp=True)
    s = answer["summary"]
    say(f"tested night by night: {s['set_aside']} of {s['bogus_above_5_sigma']} false candidates above 5 sigma "
        f"set aside, {s['planted_kept']} of {s['planted_above_5_sigma']} planted stars kept")
    return answer


def load():
    p = path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def score_candidates(candidates, significance, ref, fwhm, kept=None):
    """Each candidate's probability of being real, or None with no model."""
    kept = kept or load()
    if kept is None:
        return [None] * len(candidates)
    return [round(float(probability(kept["model"], features(significance, ref, c["x"], c["y"], fwhm))[0]), 3)
            for c in candidates]


def run(args, say=print):
    if args.action == "train":
        return train(args.plant, args.runs, say)
    kept = load()
    if kept is None:
        raise interface.Refusal("NO_SESSION", "No classifier yet: ./realbogus.py train")
    if args.action == "show":
        for f in FEATURES:
            say(f"  {f:13s} {kept['model']['weights'][f]:+.2f}")
        s = kept["summary"]
        say(f"set aside {s['set_aside']} of {s['bogus_above_5_sigma']} false candidates, kept {s['planted_kept']} "
            f"of {s['planted_above_5_sigma']} planted, below {kept['model']['cut']:.2f}")
        return kept
    from astropy.io import fits
    folder = Path(args.session)
    record = json.loads((folder / "candidates.json").read_text(encoding="utf-8"))
    sig = fits.getdata(folder / "difference.fits").astype(float)
    ref = reference_image(record["reference"])
    scores = score_candidates(record["candidates"], sig, ref, record.get("fwhm_px", 4.8), kept)
    rows = [dict(x=c["x"], y=c["y"], score=c["score"], real_bogus=p, likely_bogus=p < kept["model"]["cut"])
            for c, p in zip(record["candidates"], scores)]
    for r in rows:
        say(f"  ({r['x']}, {r['y']}) {r['score']} sigma: {r['real_bogus']:.2f}"
            + (" likely bogus" if r["likely_bogus"] else ""))
    return {"session": str(folder), "cut": kept["model"]["cut"], "candidates": rows}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", choices=["train", "score", "show"])
    ap.add_argument("session", nargs="?", help="for score: the night's folder")
    ap.add_argument("--plant", type=int, default=300, help="fakes planted a run (train)")
    ap.add_argument("--runs", type=int, default=2, help="runs a night, each with fakes elsewhere (train)")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    if args.action == "score" and not args.session:
        ap.error("score needs a session")
    interface.main("realbogus", lambda: run(args), args.json)


if __name__ == "__main__":
    sys.exit(main())
