"""Network against blur at equal grain: planted filaments and independent error, stars protected."""
import json, sys
from pathlib import Path
sys.path.insert(0, ".")
import numpy as np, torch
from scipy import ndimage as N
import denoiser as D
T = Path.home() / "telescopeyoke-laptop/training"
def lines(shape, seed):
    r = np.random.default_rng(seed); yy, xx = np.mgrid[:shape[0], :shape[1]]; out = np.zeros(shape, np.float32)
    for _ in range(14):
        a = r.uniform(0, np.pi); c = r.uniform(.15, .85) * shape[0]; d = r.uniform(.15, .85) * shape[1]; w = r.uniform(1.2, 2.5)
        dist = (yy - c) * np.cos(a) - (xx - d) * np.sin(a); along = (yy - c) * np.sin(a) + (xx - d) * np.cos(a)
        out = np.maximum(out, np.exp(-dist ** 2 / (2 * w * w)) * (np.abs(along) < 170))
    return out
def search(sky, x, make, target):
    lo, hi = 0.0, 1.0
    for _ in range(14):
        k = (lo + hi) / 2
        lo, hi = (k, hi) if D.grain(make(k), sky) > target else (lo, k)
    return hi
results = []
index = [r for r in json.load(open(T / "pairs/index.json")) if r["role"] == "test"]
for model in sys.argv[1:]:
    net = D.network().cuda(); net.load_state_dict(torch.load(T / f"models/{model}.pt", map_location="cuda")["state"]); net.eval()
    run = lambda a, b: D.infer(net, torch, a, b, "cuda")
    for rec in index:
        p = T / "pairs" / rec["name"] / "split0"; meta = json.load(open(p / "meta.json"))
        x, y, s = (np.load(p / f"{k}.npy").astype(np.float32) for k in "xys"); valid = np.load(p / "valid.npy")
        fine = x - N.median_filter(x, size=9); noise = 1.4826 * np.median(np.abs(fine[valid][::3]))
        star = N.binary_dilation(fine > 5 * noise, iterations=4); soft = np.clip(N.gaussian_filter(star.astype(np.float32), 1.5) * 1.6, 0, 1)
        sky = valid & ~N.binary_dilation(star, iterations=3); floor = meta["input"] / meta["target"]
        out0 = run(x, s); out = soft * x + (1 - soft) * out0
        plant = lines(x.shape, 11) ; use = plant > .25
        for amp in (1, 3):
            xp = x + amp * plant; o0 = run(xp, s); op = soft * xp + (1 - soft) * o0
            for target in (.7, .5, .3):
                a = search(sky, x, lambda k: x + k * (out - x), target); sg = 4 * search(sky, x, lambda k: N.gaussian_filter(x, 4 * k) if k else x, target)
                neto = x + a * (out - x); nett = xp + a * (op - xp); blo = N.gaussian_filter(x, sg); blt = N.gaussian_filter(xp, sg)
                keep = lambda t, o: float(((t - o)[use & sky] * plant[use & sky]).sum() / (amp * (plant[use & sky] ** 2).sum()))
                err = lambda o: float(np.sqrt(max(np.mean((o[sky] - y[sky]) ** 2) - floor, 0)))
                row = dict(model=model, session=rec["name"], filter=rec["filter"], amp=amp, grain=target, net_keep=round(keep(nett, neto), 3), blur_keep=round(keep(blt, blo), 3), net_err=round(err(neto), 4), blur_err=round(err(blo), 4), input_err=round(err(x), 4))
                results.append(row); print(json.dumps(row), flush=True)
json.dump(results, open(T / f"fair-{sys.argv[1]}.json", "w"))
