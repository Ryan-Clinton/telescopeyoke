"""Run a free tool's own denoising code on every prepared image, on the GPU, at full strength."""
import glob, importlib.util, sys, time, types
from pathlib import Path
F = Path.home() / "telescopeyoke-laptop/freetools"
sys.path.insert(0, str(F / "deps"))
sys.path.insert(0, str(F / "ort"))
import numpy as np
from astropy.io import fits
tool, names = sys.argv[1], sys.argv[2:]
paths = [str(F / "in" / f"{n}.fits") for n in names] or sorted(glob.glob(str(F / "in/*.fits")))
out = F / "out" / tool; out.mkdir(parents=True, exist_ok=True)

def load(name, file):
    spec = importlib.util.spec_from_file_location(name, file); m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m); return m

if tool == "graxpert":
    for mod in ("graxpert", "graxpert.application", "graxpert.ui"):
        sys.modules[mod] = types.ModuleType(mod)
    h = types.ModuleType("graxpert.ai_model_handling")
    h.get_execution_providers_ordered = lambda gpu=True: ["CUDAExecutionProvider", "CPUExecutionProvider"]
    a = types.ModuleType("graxpert.application.app_events"); a.AppEvents = type("Events", (), {"__getattr__": lambda self, name: name})()
    b = types.ModuleType("graxpert.application.eventbus")
    b.eventbus = types.SimpleNamespace(add_listener=lambda *_: None, remove_listener=lambda *_: None, emit=lambda *_: None)
    u = types.ModuleType("graxpert.ui.ui_events"); u.UiEvents = type("Events", (), {"__getattr__": lambda self, name: name})()
    sys.modules.update({h.__name__: h, a.__name__: a, b.__name__: b, u.__name__: u})
    g = load("gx", F / "dl/graxpert/denoising_302.py")
    model = str(Path.home() / ".local/share/GraXpert/denoise-ai-models/3.0.2/model.onnx")
    def run(p):
        g.cached_denoised_image = None
        x = fits.getdata(p).astype(np.float32)[..., None]
        return g.denoise(x, model, 1.0, batch_size=8, ai_gpu_acceleration=True)[..., 0]
else:
    for mod in ("tkinter", "tkinter.simpledialog", "tkinter.messagebox", "tkinter.ttk"):
        sys.modules[mod] = types.ModuleType(mod)
    sys.modules["tkinter"].simpledialog = sys.modules["tkinter.simpledialog"]
    sys.modules["tkinter"].messagebox = sys.modules["tkinter.messagebox"]
    sys.modules["tkinter"].ttk = sys.modules["tkinter.ttk"]
    c = load("cc", F / "dl/cc/SetiAstroCosmicClarity_denoise.py")
    models = c.load_models(str(F / "dl/cc"), use_gpu=True)
    def run(p):
        return np.squeeze(c.denoise_image(p, 1.0, models, "luminance")[0]).astype(np.float32)

for p in paths:
    target = out / (Path(p).stem + ".npy")
    if target.exists():
        continue
    t = time.time(); y = run(p); np.save(target, y.astype(np.float32))
    print(Path(p).stem, y.shape, round(time.time() - t, 1), "s", flush=True)
