"""DeepSNR 1.3.2 and Seti Astro Suite's AI4 denoise on the same prepared half-stacks, for score.py."""
import os, subprocess, sys, tempfile
from pathlib import Path
import numpy as np
from astropy.io import fits

F = Path.home() / "telescopeyoke-laptop/freetools"; LIBS = (F / "deepsnr_cuda_path").read_text().strip()
TOOLS = {"deepsnr": lambda a, b: ([str(F / "dl/deepsnr/gpu/deepsnr"), "--input", a, "--output", b, "--linear"], dict(os.environ, LD_LIBRARY_PATH=LIBS)),
         "sasai4": lambda a, b: ([str(F / "sas/bin/cosmicclarity"), "denoise", "-i", a, "-o", b, "--gpu", "--denoise-luma", "1.0", "--denoise-color", "1.0"],
                                 dict(os.environ, QT_QPA_PLATFORM="offscreen"))}
names = sorted(p.stem for p in (F / "in").glob("*_a[013].fits"))
for tool in sys.argv[1:] or TOOLS:
    (F / "out" / tool).mkdir(exist_ok=True)
    for n in names:
        t = F / "out" / tool / f"{n}.npy"
        if t.exists(): continue
        with tempfile.TemporaryDirectory(dir=F / "out" / tool) as d:
            cmd, env = TOOLS[tool](str(F / "in" / f"{n}.fits"), f"{d}/out.fits")
            r = subprocess.run(cmd, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
            if not Path(f"{d}/out.fits").exists(): sys.exit(f"{tool} {n}: " + (r.stdout + r.stderr)[-800:])
            if tool == "deepsnr" and "CUDA execution provider" not in r.stdout + r.stderr: sys.exit("DeepSNR is not on the GPU")
            x = np.squeeze(fits.getdata(f"{d}/out.fits")).astype(np.float32)
        if x.shape != fits.getdata(F / "in" / f"{n}.fits").shape: sys.exit(f"{n}: shape {x.shape}")
        np.save(t, x); print(tool, n, flush=True)
