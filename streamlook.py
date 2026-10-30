#!/usr/bin/env python3
"""The live stream's picture, drawn as docs/stream-look.md sets it out.

    ./stream.py preview            each state at full and phone size, with index.html to see them together

`compose(state, stack, single)` draws one picture from a state (what is
running, its figures and its programme) and the two pictures (the stack and
one exposure). Every piece of text goes through `Canvas.text`, which keeps
what was written, where, and on what, so the tests can check the words,
the margins and the contrast without reading pixels.

`stream.py` sends it (drawn on its own thread); `from_status()` turns the
status page's web/status.json into the state.
"""
import functools
import math
import time
import tomllib
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
TARGETS = ROOT / "stream-targets.toml"

WIDTH, HEIGHT = 1920, 1080
MARGIN_X, MARGIN_Y = 96, 54                 # 5 % of the frame: nothing important outside it

COLOURS = {
    "background": (6, 10, 18), "panel": (11, 18, 32), "raised": (17, 26, 42),
    "text": (238, 244, 255), "secondary": (165, 178, 200), "accent": (102, 197, 255),
    "live": (99, 214, 139), "attention": (242, 185, 93), "problem": (238, 107, 115),
    "muted": (52, 66, 90),                  # graphics only, never text
}
FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
FONTS = {"sans": "DejaVuSans.ttf", "bold": "DejaVuSans-Bold.ttf", "mono": "DejaVuSansMono.ttf"}

# What wins when two things want the screen at once, most important first.
PRIORITY = ["problem", "candidate", "transition", "programme", "caption", "figures"]


@functools.lru_cache(maxsize=64)
def font(kind, size):
    """A font, loaded once for each kind and size."""
    try:
        return ImageFont.truetype(str(FONT_DIR / FONTS[kind]), size)
    except OSError:
        return ImageFont.load_default(size=size)


_TARGETS = {"mtime": None, "found": {}}


def targets():
    """stream-targets.toml, read again only when it changes."""
    try:
        mtime = TARGETS.stat().st_mtime
        if mtime != _TARGETS["mtime"]:
            _TARGETS.update(mtime=mtime, found=tomllib.loads(TARGETS.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}
    return _TARGETS["found"]


def luminance(colour):
    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(float(c)) for c in colour[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    """WCAG's contrast ratio between two colours."""
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# --- the display stretch ------------------------------------------------------

def _asinh_for(level, x):
    """The asinh strength that puts value `x` at `level` on the screen
    (nearly linear when `x` is already as bright as `level`)."""
    if x >= level:
        return 1e-3
    lo, hi = 1e-3, 1e4
    for _ in range(50):
        k = math.sqrt(lo * hi)
        if math.asinh(k * x) / math.asinh(k) < level:
            lo = k
        else:
            hi = k
    return k


def sky_of(a):
    """(background, noise) of each channel, from the sky only: the darkest
    60 % of the picture by brightness, so a galaxy filling much of the
    frame (M31) or a bright star does not lift the sky's level."""
    small = a[::4, ::4].reshape(-1, 3)
    light = small.mean(axis=1)
    sky = small[light <= np.percentile(light, 60)]
    background = np.median(sky, axis=0)
    noise = 1.4826 * np.median(np.abs(sky - background), axis=0) + 1e-4
    return background, noise


_STEADY = {}


def steady(role, background, noise, weight=0.2):
    """The display calibration for `role` ("single", "stack"), moved only a
    fifth of the way towards each new picture's: one exposure after another
    then does not pump in brightness or colour on the screen."""
    old = _STEADY.get(role)
    if old is not None and old[0].shape == background.shape:
        background = old[0] + weight * (background - old[0])
        noise = old[1] + weight * (noise - old[1])
    _STEADY[role] = (background, noise)
    return background, noise


def display(picture, sky=0.09, role=None):
    """The picture as shown on the stream: the sky dark and neutral without
    clipping faint structure, faint light lifted gently, bright stars
    rounded off before they clip, a little more colour. Its own sky sets it
    (each picture is normalised independently, smoothed over time for its
    `role`), so one exposure and the stack share a style, not numbers.
    Shows only: nothing measured ever reads it, and it adds no detail."""
    a = np.asarray(picture.convert("RGB"), dtype=np.float32) / 255.0
    background, noise = sky_of(a)
    if role:
        background, noise = steady(role, background, noise)
    # The black point sits well under the sky, so the faintest light stays.
    black = np.clip(background - np.minimum(3.0 * noise, 0.06), 0, None)
    a = np.clip((a - black) / np.maximum(1 - black, 1e-3), 0, 1)
    # A neutral sky: each channel's background brought to the same level.
    level = background - black
    a = a * (level.mean() / np.maximum(level, 1e-4))
    x = float(max(level.mean(), 1e-4))
    k = _asinh_for(sky, x)
    a = np.arcsinh(k * np.clip(a, 0, None)) / math.asinh(k)
    a = 1.12 * a / (1 + 0.12 * a)                       # a soft shoulder for bright stars
    grey = a.mean(axis=2, keepdims=True)
    a = grey + 1.15 * (a - grey)                        # a slight lift in colour
    return Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8))


def shrunk(picture, size):
    """The picture no bigger than `size`, before stretching: the stretch
    then costs a fraction of what it would at full size."""
    p = picture.copy()
    p.thumbnail(size, Image.BILINEAR)
    return p


def fit(picture, size, fill=COLOURS["background"]):
    """The whole picture inside `size`, letterboxed: never cropped to fill."""
    box = Image.new("RGB", size, fill)
    p = picture.copy()
    p.thumbnail(size)
    box.paste(p, ((size[0] - p.width) // 2, (size[1] - p.height) // 2))
    return box


# --- the canvas -----------------------------------------------------------------

class Canvas:
    def __init__(self, width=WIDTH, height=HEIGHT):
        self.image = Image.new("RGB", (width, height), COLOURS["background"])
        self.draw = ImageDraw.Draw(self.image)
        self.written = []                       # (words, box, colour, background)
        self.crawl = None                       # a slow line for stream.py to run along the bottom

    def text(self, xy, words, kind, size, colour="text", on="background", anchor="la"):
        f = font(kind, size)
        fill = COLOURS[colour] if isinstance(colour, str) else colour
        under = COLOURS[on] if isinstance(on, str) else on
        self.draw.text(xy, words, font=f, fill=fill, anchor=anchor)
        box = self.draw.textbbox(xy, words, font=f, anchor=anchor)
        self.written.append({"words": words, "box": box, "colour": fill, "on": under, "size": size})
        return box

    def wrap(self, xy, words, kind, size, width, colour="text", on="background", gap=1.3):
        """Words wrapped to `width`; the y below the last line."""
        f = font(kind, size)
        x, y = xy
        line = ""
        for word in words.split():
            trial = f"{line} {word}".strip()
            if self.draw.textlength(trial, font=f) <= width or not line:
                line = trial
            else:
                self.text((x, y), line, kind, size, colour, on)
                y += int(size * gap)
                line = word
        if line:
            self.text((x, y), line, kind, size, colour, on)
            y += int(size * gap)
        return y

    def box(self, rect, colour, outline=None, width=1, radius=10):
        fill = COLOURS[colour] if isinstance(colour, str) else colour
        line = COLOURS[outline] if isinstance(outline, str) else outline
        self.draw.rounded_rectangle(rect, radius=radius, fill=fill, outline=line, width=width)


# --- pieces ---------------------------------------------------------------------

def utc(t, seconds=False):
    return time.strftime("%H:%M:%S" if seconds else "%H:%M", time.gmtime(t)) + " UTC"


def live_state(s):
    """(words, colour) for how fresh the last exposure is."""
    age, exposure = s.get("last_age"), s.get("exposure") or 0
    if age is None:
        return None, None
    if age < max(30, 2 * exposure):
        return "● LIVE", "live"
    if age <= 120:
        return "● WAITING FOR NEXT EXPOSURE", "secondary"
    return f"PAUSED · no new exposure for {int(age // 60)} min", "attention"


def header(c, s):
    name = c.text((MARGIN_X, MARGIN_Y), "TELESCOPEYOKE", "bold", 24, "accent")
    c.text((name[2] + 14, MARGIN_Y + 3), "live observatory", "sans", 21, "secondary")
    words, colour = live_state(s)
    if words:
        c.text((WIDTH - MARGIN_X, MARGIN_Y), words, "bold", 22, colour, anchor="ra")
    if s.get("stage"):
        c.text((WIDTH // 2, MARGIN_Y + 2), s["stage"], "sans", 20, "secondary", anchor="ma")


def footer(c, s):
    y = HEIGHT - MARGIN_Y - 24
    if s.get("last_age") is not None:
        c.text((MARGIN_X, y), f"LAST EXPOSURE {int(s['last_age'])} s ago", "mono", 21, "secondary")
    c.text((WIDTH // 2, y), utc(s["now"], seconds=True), "mono", 21, "secondary", anchor="ma")
    if s.get("next"):
        c.text((WIDTH - MARGIN_X, y), f"COMING UP · {s['next']}", "mono", 21, "secondary", anchor="ra")


def plate(c, rect, strength=0.65, colour=COLOURS["background"]):
    """A see-through dark plate over the picture: quiet, not another widget."""
    rect = tuple(int(v) for v in rect)
    under = c.image.crop(rect)
    c.image.paste(Image.blend(under, Image.new("RGB", under.size, colour), strength), rect[:2])
    return colour


STACK_BOX = (MARGIN_X, MARGIN_Y + 50, 1274, 870)        # x, y, width, height
PANEL_BOX = (MARGIN_X + 1274 + 24, MARGIN_Y + 50, WIDTH - 2 * MARGIN_X - 1274 - 24, 870)


def sky_area(c, s, stack, single):
    x, y, w, h = STACK_BOX
    if (s.get("lucky") or s.get("live")) and single is not None:
        # A lucky-imaging video or the live view: its newest frame is the
        # picture, not an earlier run's stack beside it.
        stack, single = single, None
    # The Moon is its own light: the sky stretch, which sets the black point
    # from the picture's background, turned it black (30 October 2026).
    look = (lambda p, role: p) if s.get("kind") == "moon" else (lambda p, role: display(p, role=role))
    if stack is None:
        c.box((x, y, x + w, y + h), "panel")
        c.text((x + w // 2, y + h // 2), "The picture builds up after the first few exposures",
               "sans", 25, "secondary", on="panel", anchor="mm")
        return
    shown = fit(look(shrunk(stack, (w, h)), "stack"), (w, h))
    age = s.get("last_age") or 0
    if age > 120:
        # Paused: a little dimmer and greyer, so it reads as waiting, not broken.
        grey = shown.convert("L").convert("RGB")
        shown = Image.blend(Image.blend(shown, grey, 0.4), Image.new("RGB", shown.size, (0, 0, 0)), 0.25)
    c.image.paste(shown, (x, y))
    # The picture's own edges inside the letterbox: what sits on it goes on it, not on the bars.
    scale = min(w / stack.width, h / stack.height)
    pw, ph = round(stack.width * scale), round(stack.height * scale)
    x, y, w, h = x + (w - pw) // 2, y + (h - ph) // 2, pw, ph
    line = (s.get("story") or {}).get("line")
    if line:
        # LOOK CLOSELY, or the presenter, for a few seconds across the top of the picture.
        under = plate(c, (x, y, x + w, y + 92), 0.72)
        c.wrap((x + 24, y + 14), line, "sans", 24, w - 48, "text", on=under, gap=1.25)

    if s.get("combined"):
        under = plate(c, (x + 16, y + h - 48, x + min(470, w // 2), y + h - 16), 0.55)
        words = c.text((x + 28, y + h - 42), f"{s['combined']} exposures combined", "mono", 19, "secondary",
                       on=under)
        if s.get("new_exposures"):
            c.text((words[2] + 14, y + h - 42), f"+{s['new_exposures']}", "mono", 19, "live", on=under)
    if single is not None:
        iw, ih = 300, 200
        ix, iy = x + w - iw - 20, y + h - ih - 20
        c.image.paste(fit(look(shrunk(single, (iw, ih)), "single"), (iw, ih)), (ix, iy))
        c.box((ix, iy, ix + iw, iy + ih), None, outline="secondary", width=2, radius=4)
        under = plate(c, (ix, iy - 32, ix + iw, iy - 4), 0.7)
        exposure = s.get("exposure")
        c.text((ix + 10, iy - 29), "ONE EXPOSURE" + (f" · {exposure:g} s" if exposure else ""),
               "mono", 19, "text", on=under)
    explainer = (s.get("story") or {}).get("explainer")
    if explainer:
        # Over everything on the picture: for a few seconds it is the picture.
        explain(c, explainer, s, (x, y, w, h), stack, single)


def dots(c, rect, seed, extra=False):
    """A little schematic star field in `rect` (the same `seed` gives the
    same stars); `extra` adds one new star, marked, in the middle."""
    import random
    rng = random.Random(seed)
    x0, y0, x1, y1 = rect
    c.box(rect, (0, 0, 0), outline="muted", width=2, radius=6)
    for _ in range(26):
        px, py, r = rng.uniform(x0 + 10, x1 - 10), rng.uniform(y0 + 10, y1 - 10), rng.choice((1.5, 2, 2.5, 3.5))
        c.draw.ellipse((px - r, py - r, px + r, py + r), fill=COLOURS["text"])
    if extra:
        mx, my = (x0 + x1) / 2 + 18, (y0 + y1) / 2 - 12
        c.draw.ellipse((mx - 4, my - 4, mx + 4, my + 4), fill=COLOURS["attention"])
        c.draw.ellipse((mx - 14, my - 14, mx + 14, my + 14), outline=COLOURS["attention"], width=2)


def explain(c, kind, s, area, stack, single):
    """A larger explainer for a few seconds, over a dimmed picture: what
    stacking does (with tonight's own exposure and stack), what a transit or
    a nova is, and how a search finds what changed (as a diagram, never a
    real candidate)."""
    x, y, w, h = area
    c.image.paste(Image.blend(c.image.crop((x, y, x + w, y + h)), Image.new("RGB", (w, h), (0, 0, 0)), 0.6),
                  (x, y))
    bx0, by0, bx1, by1 = x + w * 0.06, y + h * 0.16, x + w * 0.94, y + h * 0.84
    c.box((bx0, by0, bx1, by1), "panel", radius=16)
    on = COLOURS["panel"]
    left, top, inner = bx0 + 40, by0 + 34, bx1 - bx0 - 80
    titles = {"stacking": "WHAT IS STACKING?", "transit": "WHAT IS A TRANSIT?", "nova": "WHAT IS A NOVA?",
              "subtraction": "HOW DOES THE SEARCH WORK?", "comet": "THE COMET HUNT"}
    c.text((left, top), titles[kind], "bold", 36, "accent", on=on)
    top += 66
    row_h = (by1 - 110) - top
    if kind == "stacking" and stack is not None and single is not None:
        n = s.get("combined") or 0
        for i, (picture, label, role) in enumerate(((single, "1 EXPOSURE", "single"),
                                                    (stack, f"{n} EXPOSURES" if n else "THE STACK", "stack"))):
            box = (int(inner / 2 - 20), int(row_h - 40))
            px = int(left + i * (inner / 2 + 20))
            c.image.paste(fit(display(shrunk(picture, box), role=role), box), (px, int(top)))
            c.text((px, top + box[1] + 8), label, "mono", 22, "text", on=on)
        words = "Each exposure is noisy. Added together, the noise averages away and fainter stars appear."
    elif kind == "transit":
        cx, cy, r = left + inner * 0.22, top + row_h / 2, min(row_h / 2 - 10, 120)
        c.draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 214, 140))
        c.draw.ellipse((cx + r * 0.1 - r * 0.22, cy - r * 0.22, cx + r * 0.1 + r * 0.22, cy + r * 0.22),
                       fill=(10, 12, 18))
        c.draw.line([(cx - r * 1.3, cy), (cx + r * 1.3, cy)], fill=COLOURS["muted"], width=2)
        gx0, gx1, gy = left + inner * 0.5, left + inner, top + row_h * 0.35
        dip = row_h * 0.3
        c.draw.line([(gx0, gy), (gx0 + (gx1 - gx0) * 0.3, gy), (gx0 + (gx1 - gx0) * 0.38, gy + dip),
                     (gx0 + (gx1 - gx0) * 0.62, gy + dip), (gx0 + (gx1 - gx0) * 0.7, gy), (gx1, gy)],
                    fill=COLOURS["accent"], width=5)
        c.text((gx0, gy + dip + 30), "THE STAR'S BRIGHTNESS", "mono", 22, "secondary", on=on)
        words = "As the planet crosses its star, a little of the light is blocked: the brightness dips, then recovers."
    elif kind == "nova":
        steps = [("A WHITE DWARF", "pulls gas from a companion star"), ("THE GAS BUILDS UP", "on its surface"),
                 ("IT IGNITES", "thousands of times brighter, for days")]
        col = inner / 3
        for i, (head, sub) in enumerate(steps):
            px = left + i * col
            c.wrap((px, top + row_h * 0.3), head, "bold", 28, col - 50, "text", on=on)
            c.wrap((px, top + row_h * 0.3 + 44), sub, "sans", 24, col - 50, "secondary", on=on)
            if i < 2:
                c.text((px + col - 40, top + row_h * 0.3), "→", "bold", 36, "accent", on=on)
        words = "A nova does not destroy its star: it is an explosion on the surface of a white dwarf."
    elif kind == "comet":
        import streamstory
        hunt = (s.get("story") or {}).get("comet") or {}
        shots = movie_frames(hunt.get("movie"))
        size = min((inner - 80) / 3, row_h - 120)
        for i, (shot, label) in enumerate(zip(shots, ("FIRST", "MIDDLE", "LAST"))):
            px = left + i * (size + 40)
            c.image.paste(shot.resize((int(size), int(size)), Image.NEAREST), (int(px), int(top)))
            c.text((px, top + size + 8), label, "mono", 22, "text", on=on)
        words = streamstory.comet_words(hunt) if hunt else "A known comet, found by the comet hunt."
    else:                                                               # subtraction, as a diagram
        size = min((inner - 160) / 3, row_h - 50)
        for i, (label, extra) in enumerate((("OLD SKY", False), ("TONIGHT", True), ("WHAT CHANGED?", None))):
            px = left + i * (size + 80)
            rect = (px, top, px + size, top + size)
            if extra is None:
                c.box(rect, (0, 0, 0), outline="muted", width=2, radius=6)
                mx, my = px + size / 2 + 18, top + size / 2 - 12
                c.draw.ellipse((mx - 4, my - 4, mx + 4, my + 4), fill=COLOURS["attention"])
                c.draw.ellipse((mx - 14, my - 14, mx + 14, my + 14), outline=COLOURS["attention"], width=2)
            else:
                dots(c, rect, 7, extra)
            c.text((px, top + size + 8), label, "mono", 22, "text", on=on)
            if i < 2:
                c.text((px + size + 26, top + size / 2 - 22), "−" if i == 0 else "=", "bold", 40, "accent", on=on)
        words = "A diagram: tonight's picture minus an earlier one leaves only what has changed, then it is checked."
    c.wrap((left, by1 - 96), words, "sans", 25, inner, "text", on=on)


@functools.lru_cache(maxsize=4)
def _frames(path, mtime):
    from PIL import ImageSequence
    with Image.open(path) as gif:
        frames = [f.convert("RGB").copy() for f in ImageSequence.Iterator(gif)]
    inside = frames[2:-3] or frames                  # the movie runs two pictures before the track, three after
    return [inside[0], inside[len(inside) // 2], inside[-1]]


def movie_frames(path):
    """The first, middle and last pictures of a comet hunt's movie; none
    when it has gone."""
    try:
        return _frames(str(path), Path(path).stat().st_mtime) if path else []
    except (OSError, ValueError):
        return []


def about(c, s, x, y, width):
    """The object: its name, common name, plain words and one line of facts."""
    entry = targets().get("targets", {}).get(s["target"], {})
    c.text((x, y), s["target"], "bold", 60, "text", on="panel")
    y += 76
    if entry.get("common"):
        c.text((x, y), entry["common"].upper(), "bold", 26, "secondary", on="panel")
        y += 40
    if entry.get("words"):
        y = c.wrap((x, y + 6), entry["words"], "sans", 25, width, "text", on="panel") + 4
    facts = " · ".join(str(f) for f in (entry.get("distance"),
                                         f"magnitude {entry['magnitude']}" if entry.get("magnitude") else None) if f)
    if facts:
        y = c.wrap((x, y), facts, "mono", 18, width, "secondary", on="panel") + 6
    elif not entry and s.get("kind_of_object"):
        c.text((x, y), s["kind_of_object"], "sans", 22, "secondary", on="panel")
        y += 30
    return y + 18


FIGURE_ROW = 88


def deep_sky_figures(s):
    rows = []
    if s.get("kept") is not None and s.get("captured"):
        rows.append((f"{s['kept']} / {s['captured']}", "FRAMES KEPT"))
    if s.get("integration_s"):
        minutes = s["integration_s"] / 60
        rows.append((f"{minutes:.0f} MIN" if minutes < 120 else f"{minutes / 60:.1f} H", "LIGHT COLLECTED"))
    if s.get("fwhm_arcsec"):
        rows.append((f"{s['fwhm_arcsec']:.1f}″", "STAR SIZE"))
    return rows


def moon_figures(s):
    """The Moon's own figures, then the run's. Never a star size: there are
    no stars to measure (24 October 2026)."""
    m = s.get("moon") or {}
    rows = []
    if m.get("illumination") is not None:
        rows.append((f"{m['illumination']}%", "ILLUMINATED"))
    if m.get("age_days") is not None and m["illumination"] < 97:
        rows.append((f"{m['age_days']:.1f} DAYS", "LUNAR AGE"))
    elif m.get("size_deg"):
        rows.append((f"{m['size_deg']:.2f}°", "APPARENT SIZE"))
    if m.get("altitude") is not None:
        rows.append((f"{m['altitude']}°", "ALTITUDE"))
    if s.get("kept") is not None and s.get("captured"):
        rows.append((f"{s['kept']} / {s['captured']}", "FRAMES KEPT"))
        rows.append((f"{round(100 * s['kept'] / s['captured'])}%", "KEEP RATE"))
    return rows


def figures_for(s):
    """The figures for what is being observed: each kind of object its own,
    so a number that means nothing for it is never shown."""
    return moon_figures(s) if s.get("kind") == "moon" else deep_sky_figures(s)


def figures(c, s, x, y, bottom):
    rows = figures_for(s)
    for number, label in rows[:max(0, min(3, int((bottom - y) // FIGURE_ROW)))]:
        c.text((x, y), number, "bold", 46, "text", on="panel")
        c.text((x, y + 54), label, "sans", 18, "secondary", on="panel")
        y += FIGURE_ROW
    return y


def panel_map(c, p, x, y):
    """The patrol's panels, as the mosaic lays them out: done filled, the
    current one outlined, the rest open."""
    cell, gap = 54, 10
    for panel in p["panels"]:
        px, py = x + panel["col"] * (cell + gap), y + panel["row"] * (cell * 0.7 + gap)
        rect = (px, py, px + cell, py + cell * 0.7)
        if panel["state"] == "done":
            c.box(rect, "muted", radius=4)
        elif panel["state"] == "current":
            c.box(rect, "raised", outline="accent", width=3, radius=4)
        else:
            c.box(rect, None, outline="muted", width=2, radius=4)
    rows = 1 + max(panel["row"] for panel in p["panels"])
    return y + rows * (cell * 0.7 + gap)


def light_curve(c, t, x, y, w, h, now):
    """The expected transit as a muted box, the measurements as dots, and now."""
    start, end = t["ingress"] - 75 * 60, t["egress"] + 75 * 60
    lo, hi = 1 - 1.8 * t["depth"], 1 + 0.6 * t["depth"]

    def at(when, flux):
        return x + (when - start) / (end - start) * w, y + (hi - flux) / (hi - lo) * h
    c.box((x, y, x + w, y + h), "raised", radius=6)
    expected = [(start, 1), (t["ingress"], 1), (t["ingress"] + 20 * 60, 1 - t["depth"]),
                (t["egress"] - 20 * 60, 1 - t["depth"]), (t["egress"], 1), (end, 1)]
    c.draw.line([at(*p) for p in expected], fill=COLOURS["muted"], width=4)
    for when, flux in t.get("points", []):
        px, py = at(when, flux)
        c.draw.ellipse((px - 3, py - 3, px + 3, py + 3), fill=COLOURS["accent"])
    if start <= now <= end:
        nx = at(now, 1)[0]
        c.draw.line([(nx, y), (nx, y + h)], fill=COLOURS["text"], width=1)
        c.text((nx, y - 24), "NOW", "mono", 18, "text", on="panel", anchor="ma")
    for name, when in (("in", t["ingress"]), ("mid", t["mid"]), ("out", t["egress"])):
        c.text((at(when, 1)[0], y + h + 6), name, "mono", 18, "secondary", on="panel", anchor="ma")
    c.text((x, y + h + 34), "▬ EXPECTED", "mono", 18, "secondary", on="panel")
    c.text((x + 160, y + h + 34), "● LIVE MEASUREMENTS", "mono", 18, "accent", on="panel")
    return y + h + 66


def programme(c, s, x, y, width):
    kind = s["kind"]
    if s.get("candidate"):
        return candidate(c, s["candidate"], x, y, width)
    if kind == "patrol":
        p = s["patrol"]
        y = c.wrap((x, y), "NOVA PATROL", "bold", 28, width, "accent", on="panel")
        y = c.wrap((x, y + 4), f"Every star in this part of {p['field']} is being compared with an earlier night.",
                   "sans", 24, width, "text", on="panel") + 10
        bottom = panel_map(c, p, x, y)
        done = sum(panel["state"] == "done" for panel in p["panels"])
        c.text((x + 272, y + 2), f"{done} / {len(p['panels'])}", "bold", 30, "text", on="panel")
        c.text((x + 272, y + 40), "SEARCHED", "sans", 18, "secondary", on="panel")
        y = bottom + 14
        if p.get("awaiting"):
            words = f"{p['awaiting']} candidate{'s' if p['awaiting'] != 1 else ''} awaiting private review"
        elif p.get("possible"):
            words = (f"{p['possible']} possible change{'s' if p['possible'] != 1 else ''}, being checked "
                     "automatically")
        else:
            words = "No confirmed new star yet"
        return c.wrap((x, y), words, "sans", 20, width, "secondary", on="panel") + 14
    if kind == "transit":
        t = s["transit"]
        c.text((x, y), t["planet"], "bold", 28, "accent", on="panel")
        c.text((x, y + 36), "HOT JUPITER TRANSIT" if t.get("hot_jupiter") else "PLANET TRANSIT",
               "bold", 20, "secondary", on="panel")
        y = c.wrap((x, y + 70), f"The planet passes in front of its star and dims it by about "
                   f"{100 * t['depth']:.1f} %.", "sans", 24, width, "text", on="panel") + 10
        c.text((x, y), f"{utc(t['ingress'])[:5]} → {utc(t['egress'])}, mid {utc(t['mid'])[:5]}",
               "mono", 18, "secondary", on="panel")
        y += 34
        state = {"baseline": ("MEASURING BASELINE", "secondary"), "live": ("LIVE PHOTOMETRY", "live"),
                 "measuring": ("MEASURING THE TRANSIT", "secondary"),
                 "paused": ("PHOTOMETRY PAUSED: LOW SIGNAL", "attention")}[t["state"]]
        c.text((x, y), state[0], "bold", 20, state[1], on="panel")
        y += 34
        if t["state"] in ("baseline", "measuring"):
            return c.wrap((x, y), t.get("baseline_words", ""), "sans", 20, width, "secondary", on="panel")
        return light_curve(c, t, x, y + 28, width, 170, s["now"])
    if kind == "moon":
        y = c.wrap((x, y), "EXPLORING THE MOON", "bold", 28, width, "accent", on="panel")
        y = c.wrap((x, y + 6), moon_words(s.get("lucky")), "sans", 24, width, "text", on="panel") + 10
        if s.get("lucky_stage"):
            title, figures = s["lucky_stage"]
            y = c.wrap((x, y), title, "bold", 20, width, "live", on="panel")
            y = c.wrap((x, y + 2), figures, "mono", 18, width, "secondary", on="panel") + 10
        tonight = moon_tonight(s.get("moon") or {})
        if tonight:
            y = c.wrap((x, y), tonight, "mono", 18, width, "secondary", on="panel") + 10
        return y
    if kind == "picture":
        c.text((x, y), "BUILDING A PICTURE", "bold", 28, "accent", on="panel")
        return c.wrap((x, y + 40), "Every exposure is added to the stack; the noise falls as they add up.",
                      "sans", 24, width, "text", on="panel") + 10
    return y


def moon_words(lucky):
    """How the Moon is being imaged, in plain words: a lucky-imaging video
    (lucky.py) or a run of short exposures stacked as they come."""
    if lucky:
        return ("Short exposures freeze moments of steadier air. Afterwards each part of the Moon is "
                "built from the frames that were sharpest there.")
    return "Hundreds of short exposures are combined to make the surface cleaner and more detailed."


def moon_tonight(m):
    """"TONIGHT'S MOON · Waxing · 34% illuminated · 6.1 days after new Moon",
    or None when the Moon's state is not known."""
    if m.get("illumination") is None:
        return None
    return (f"TONIGHT'S MOON · {'Waxing' if m.get('waxing') else 'Waning'} · {m['illumination']}% illuminated · "
            f"{m['age_days']:.1f} days after new Moon")


def candidate(c, k, x, y, width):
    """A possible change: its stage and, at the end, the vetting's result. Never a position."""
    title, words = {
        "detected": ("POSSIBLE CHANGE DETECTED",
                     "The software found a point of light that wasn't clear in the reference image. "
                     "Taking another look now."),
        "second": ("SECOND LOOK UNDER WAY", "The telescope is taking more exposures of the same panel "
                   "to see whether it appears again."),
        "result": ("RESULT", k.get("result", "")),
    }[k["stage"]]
    y = c.wrap((x, y), title, "bold", 28, width, "attention", on="panel")
    y = c.wrap((x, y + 6), words, "sans", 24, width, "text", on="panel") + 12
    steps = [("candidate", "detected"), ("second look", "second"), ("catalogue checks", "result"),
             ("result", "result")]
    order = ["detected", "second", "result"]
    for name, stage in steps:
        done = order.index(stage) < order.index(k["stage"]) or (k["stage"] == "result")
        mark, colour = ("✓", "live") if done else (("●", "accent") if stage == k["stage"] else ("○", "secondary"))
        c.text((x, y), f"{mark}  {name}", "sans", 21, colour, on="panel")
        y += 32
    return y + 10


def chapter_card(c, card, x, y, width):
    """One of the presenter's chapters (SCIENCE, HOW IT WORKS, TONIGHT,
    COMING UP) in place of the programme, for half a minute."""
    title, lines = card
    y = c.wrap((x, y), title, "bold", 28, width, "accent", on="panel") + 8
    for line in lines:
        y = c.wrap((x, y), line, "sans", 25, width, "text", on="panel") + 10
    return y


def side_panel(c, s):
    x, y, w, h = PANEL_BOX
    c.box((x, y, x + w, y + h), "panel", radius=14)
    inner = x + 28
    width = w - 56
    top = about(c, s, inner, y + 26, width)
    story = s.get("story") or {}
    if story.get("card") and story.get("chapter") != "NOW":
        top = chapter_card(c, story["card"], inner, top, width)
    else:
        top = programme(c, s, inner, top, width)
    # The programme comes first; the figures take what room is left (PRIORITY).
    figures(c, s, inner, max(top + 10, y + h - 3 * FIGURE_ROW - 10), y + h - 10)


def ribbon(c, steps, y):
    """Tonight's steps on one line: done dimmed, the current one in the accent, the rest open."""
    x = MARGIN_X
    c.text((x, y), "TONIGHT", "bold", 20, "secondary")
    x += 120
    for i, (label, status) in enumerate(steps):
        mark, colour = {"done": ("✓", "secondary"), "running": ("●", "accent")}.get(status, ("○", "secondary"))
        box = c.text((x, y), f"{label} {mark}", "sans", 20, colour)
        x = box[2] + 14
        if i < len(steps) - 1:
            box = c.text((x, y), "─", "sans", 20, "secondary")
            x = box[2] + 14


def between(c, s, stack):
    """The card between targets: the last stack, dark and soft, behind what comes next."""
    if stack is not None:
        back = display(shrunk(stack, (WIDTH, HEIGHT)))
        back = back.resize((int(back.width * 1.06), int(back.height * 1.06)))
        back = fit(back, (WIDTH, HEIGHT)).filter(ImageFilter.GaussianBlur(6))
        back = Image.blend(back, Image.new("RGB", back.size, (0, 0, 0)), 0.55)
        c.image.paste(back, (0, 0))
    b = s["between"]
    shade = (0, 0, 0)          # the darkened picture: the text is checked against black, its darkest
    x, y = MARGIN_X + 60, 250
    c.text((x, y), "NEXT TARGET", "bold", 24, "secondary", on=shade)
    c.text((x, y + 40), s["target"], "bold", 80, "text", on=shade)
    c.text((x, y + 140), b["programme"], "sans", 28, "text", on=shade)
    c.text((x, y + 182), f"imaging begins in about {round(b['begins_in_s'] / 60)} min", "sans", 24,
           "secondary", on=shade)
    y += 250
    for label, status in b["steps"]:
        mark, colour = {"done": ("✓", "live"), "now": ("●", "accent")}.get(status, ("○", "secondary"))
        c.text((x, y), f"{mark}  {label}", "sans", 26, colour, on=shade)
        y += 42
    if s.get("tonight"):
        ribbon(c, s["tonight"], HEIGHT - MARGIN_Y - 70)


def eyepiece(single, now, fresh=True, caption=""):
    """The stream as looking through the eyepiece (30 October 2026: "what
    the scope is seeing", no cards): the newest camera frame filling the
    screen, a bright object such as the Moon as it is and a starfield
    through the sky stretch, with one quiet line along the bottom."""
    c = Canvas()
    c.image.paste(Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0)), (0, 0))
    if single is not None:
        bright = float((np.asarray(single.convert("L")) > 128).mean()) > 0.02
        picture = shrunk(single, (WIDTH, HEIGHT))
        c.image.paste(fit(picture if bright else display(picture, role="single"), (WIDTH, HEIGHT)), (0, 0))
    line = "TELESCOPEYOKE · live from the telescope" + (f" · {caption}" if caption else "") + f" · {utc(now, seconds=True)}"
    under = plate(c, (MARGIN_X - 12, HEIGHT - MARGIN_Y - 40, MARGIN_X + 14 * len(line) + 12, HEIGHT - MARGIN_Y), 0.55)
    c.text((MARGIN_X, HEIGHT - MARGIN_Y - 34), line, "mono", 22, "text", on=under)
    if fresh:
        c.text((WIDTH - MARGIN_X, MARGIN_Y), "● LIVE", "bold", 22, "live", anchor="ra")
    return c


def open_card(c, s, stack):
    """The night opens: tonight's plan, before anything else on air."""
    if stack is not None:
        back = fit(display(shrunk(stack, (WIDTH, HEIGHT))), (WIDTH, HEIGHT)).filter(ImageFilter.GaussianBlur(8))
        c.image.paste(Image.blend(back, Image.new("RGB", back.size, (0, 0, 0)), 0.7), (0, 0))
    shade = (0, 0, 0)
    x, y = MARGIN_X + 60, 170
    c.text((x, y), "THE NIGHT OPENS", "bold", 24, "secondary", on=shade)
    c.text((x, y + 40), "TONIGHT AT THE OBSERVATORY", "bold", 60, "text", on=shade)
    y += 150
    for label, words in s["open"]["lines"]:
        if y > HEIGHT - MARGIN_Y - 140:
            break
        c.text((x, y), label, "bold", 22, "accent", on=shade)
        y = c.wrap((x + 300, y - 4), words, "sans", 30, WIDTH - 2 * MARGIN_X - 420, "text", on=shade, gap=1.25) + 18
    c.text((x, HEIGHT - MARGIN_Y - 60), "TELESCOPEYOKE", "bold", 26, "accent", on=shade)


CRAWL_BOX = (MARGIN_X, HEIGHT - MARGIN_Y - 34, WIDTH - MARGIN_X, HEIGHT - MARGIN_Y + 4)   # over the footer
CRAWL_SPEED = 70           # pixels a second: slow enough to read


def crawl_strip(text):
    """The crawl's line drawn once, wide enough to run in from the right
    and out at the left, as an array for stream.py to slide along."""
    x0, y0, x1, y1 = CRAWL_BOX
    width = x1 - x0
    f = font("mono", 21)
    length = int(ImageDraw.Draw(Image.new("RGB", (1, 1))).textlength(text, font=f))
    strip = Image.new("RGB", (length + 2 * width, y1 - y0), COLOURS["background"])
    ImageDraw.Draw(strip).text((width, 8), text, font=f, fill=COLOURS["secondary"])
    return np.asarray(strip)


def crawled(picture, strip, seconds):
    """The picture as an array with the crawl `seconds` along, or None once
    it has run out at the left."""
    x0, y0, x1, y1 = CRAWL_BOX
    offset = int(seconds * CRAWL_SPEED)
    if offset + (x1 - x0) > strip.shape[1]:
        return None
    out = picture.copy()
    out[y0:y1, x0:x1] = strip[:, offset:offset + (x1 - x0)]
    return out


# --- focusing and polar alignment -------------------------------------------------

LEFT = (MARGIN_X, MARGIN_Y + 50, 1274, 870)        # the area the stack has while imaging


def checklist(c, x, y, steps, size=22, gap=34, on="panel"):
    """Steps as ✓ done, ● now, ○ to come; the y below them."""
    for label, status in steps:
        mark, colour = {"done": ("✓", "live"), "now": ("●", "accent"),
                        "failed": ("✕", "attention")}.get(status, ("○", "secondary"))
        c.text((x, y), f"{mark}  {label}", "sans", size, colour, on=on)
        y += gap
    return y


def number_rows(c, x, y, rows, row=78):
    """Big figures with their labels under them, as the imaging panel's."""
    for number, label in rows:
        c.text((x, y), number, "bold", 42, "text", on="panel")
        c.text((x, y + 50), label, "sans", 18, "secondary", on="panel")
        y += row
    return y


def story_card(c, s, x, y, width, bottom):
    """The presenter's card for this segment (streamstory.plan), in what room is left."""
    card = (s.get("story") or {}).get("card")
    if not card or y > bottom - 90:
        return y
    title, lines = card
    rows = [row for line in lines for row in wrapped(c, line, "sans", 21, width)]
    if y + 34 + 27 * len(rows) > bottom:
        return y                    # a card that does not fit whole is not shown at all
    y = c.wrap((x, y), title, "bold", 22, width, "accent", on="panel") + 4
    for row in rows:
        c.text((x, y), row, "sans", 21, "text", on="panel")
        y += 27
    return y


def wrapped(c, words, kind, size, width):
    """`words` as the lines Canvas.wrap would draw them."""
    f, out, line = font(kind, size), [], ""
    for word in words.split():
        trial = f"{line} {word}".strip()
        if c.draw.textlength(trial, font=f) <= width or not line:
            line = trial
        else:
            out.append(line)
            line = word
    return out + ([line] if line else [])


def result_card(c, card, area):
    """A finished run's card, held for a few seconds over the left area:
    what happened, in plain words."""
    title, line, colour = card
    x, y, w, h = area
    plate(c, (x, y, x + w, y + h), 0.55)
    bx0, by0, bx1, by1 = x + w * 0.08, y + h * 0.3, x + w * 0.92, y + h * 0.7
    c.box((bx0, by0, bx1, by1), "panel", radius=16)
    c.box((bx0, by0, bx0 + 12, by1), "live" if colour == "live" else "problem", radius=6)
    c.text((bx0 + 48, by0 + 40), title, "bold", 52, colour, on="panel")
    c.wrap((bx0 + 48, by0 + 120), line or "", "sans", 30, bx1 - bx0 - 96, "text", on="panel")


def focus_chart(c, f, x, y, w, h):
    """Star size against the focuser's position: each reading a dot, the best
    so far ringed, the usual best as a line, the fitted focus where there is one."""
    points = [(a, v) for a, v in f["readings"]]
    label = "STAR SIZE (HFR)"
    if not points and f.get("rings"):
        points, label = f["rings"], "DOUGHNUT SIZE (px)"
    c.box((x, y, x + w, y + h), "raised", radius=8)
    c.text((x, y - 34), label, "mono", 19, "secondary", on="background")
    c.text((x + w, y + h + 40), "FOCUSER POSITION, half-steps from the start (minus is in)", "mono", 18,
           "secondary", on="background", anchor="ra")
    if not points:
        c.text((x + w / 2, y + h / 2), "The first reading is being taken", "sans", 24, "secondary",
               on="raised", anchor="mm")
        return
    xs = [a for a, _ in points]
    ys = [v for _, v in points] + ([f["usual_hfr"]] if f.get("usual_hfr") and label.startswith("STAR") else [])
    lo_x, hi_x = min(xs), max(xs)
    if hi_x - lo_x < 1:
        lo_x, hi_x = lo_x - 64, hi_x + 64
    pad = 0.08 * (hi_x - lo_x)
    lo_x, hi_x = lo_x - pad, hi_x + pad
    lo_y, hi_y = 0.0, max(ys) * 1.15

    def at(a, v):
        return x + 24 + (a - lo_x) / (hi_x - lo_x) * (w - 48), y + h - 20 - (v - lo_y) / (hi_y - lo_y) * (h - 40)
    for k in range(1, 4):
        value = hi_y * k / 4
        gy = at(lo_x, value)[1]
        c.draw.line([(x + 8, gy), (x + w - 8, gy)], fill=COLOURS["muted"], width=1)
        c.text((x - 12, gy), f"{value:.1f}", "mono", 18, "secondary", on="background", anchor="rm")
    if f.get("usual_hfr") and label.startswith("STAR"):
        uy = at(lo_x, f["usual_hfr"])[1]
        for gx in range(int(x + 8), int(x + w - 8), 24):
            c.draw.line([(gx, uy), (gx + 12, uy)], fill=COLOURS["live"], width=2)
        c.text((x + w - 16, uy - 6), f"USUAL BEST {f['usual_hfr']:.2f}", "mono", 18, "live", on="raised",
               anchor="rb")
    fit = f.get("fit") or {}
    if fit.get("ok") and fit.get("focus") is not None and lo_x <= fit["focus"] <= hi_x:
        fx = at(fit["focus"], 0)[0]
        c.draw.line([(fx, y + 10), (fx, y + h - 10)], fill=COLOURS["accent"], width=2)
        c.text((fx + 8, y + 14), "FITTED FOCUS", "mono", 18, "accent", on="raised")
    for a, v in points:
        px, py = at(a, v)
        c.draw.ellipse((px - 6, py - 6, px + 6, py + 6), fill=COLOURS["text"])
    for a in sorted({min(xs), max(xs)}):
        c.text((at(a, 0)[0], y + h + 8), f"{a:d}", "mono", 18, "secondary", on="background", anchor="ma")
    if label.startswith("STAR") and f.get("best_hfr") is not None:
        bx, by = at(f["best_at"], f["best_hfr"])
        c.draw.ellipse((bx - 16, by - 16, bx + 16, by + 16), outline=COLOURS["live"], width=3)
        c.text((bx, by + 22), f"BEST SO FAR {f['best_hfr']:.2f}", "mono", 18, "live", on="raised", anchor="ma")
    nx, ny = at(*points[-1])
    c.draw.ellipse((nx - 9, ny - 9, nx + 9, ny + 9), outline=COLOURS["accent"], width=3)


def star_pair(c, f, x, y, size):
    """One star magnified, as it was at the start and as it is now."""
    stars = f.get("stars") or {}
    for i, (key, label) in enumerate((("start", "START"), ("now", "NOW"))):
        px = x + i * (size + 32)
        c.box((px, y, px + size, y + size), (0, 0, 0), outline="muted", width=2, radius=6)
        picture = stars.get(key)
        if picture is not None:
            shown = picture.convert("RGB").resize((size - 8, size - 8), Image.NEAREST)
            c.image.paste(shown, (int(px + 4), int(y + 4)))
        else:
            c.text((px + size / 2, y + size / 2), "no star yet", "sans", 19, "secondary", on=(0, 0, 0),
                   anchor="mm")
        c.text((px, y + size + 10), label, "mono", 19, "text", on="background")


FOCUS_KINDS = {"check": ("FOCUS CHECK", "Three pictures: how sharp the stars are, against the usual best. "
                                        "Nothing turns."),
               "focus": ("FOCUSING", "The motor sweeps the focuser through focus, a curve is fitted to the "
                                     "star sizes, and it goes to the curve's lowest point."),
               "sweep": ("FOCUS CURVE", "The motor sweeps the focuser through focus to measure the curve, "
                                        "then goes back to where it started."),
               "walk": ("FOCUS WALK-IN", "From a little outside focus, the motor brings the focuser in a few "
                                         "steps at a time, measuring after each, to the sharpest."),
               "find": ("FINDING THE STARS", "Far out of focus no star measures: the motor turns half a turn "
                                             "at a time, in and then out, until they do.")}


def focus_layout(c, s):
    f = s["focus"]
    x, y, w, h = LEFT
    focus_chart(c, f, x + 80, y + 50, w - 100, 470)
    star_pair(c, f, x + 10, y + 610, 200)
    if f.get("rings") and not f["readings"]:
        last = f["rings"][-1][1]
        c.text((x + 500, y + 610), f"DOUGHNUTS {last:.0f} px across", "bold", 22, "secondary")
        c.wrap((x + 500, y + 650), "Far from focus a star is a ring: the dark middle is the shadow of the "
               "telescope's small second mirror.", "sans", 22, w - 520, "text")
    else:
        c.text((x + 500, y + 610), "ONE STAR, MAGNIFIED", "bold", 22, "secondary")
        c.wrap((x + 500, y + 650), "The brightest star in view, at the start and in the newest picture. "
               "Each dot on the curve is the stars' size measured at that focuser position: the smaller, the "
               "sharper.", "sans", 22, w - 520, "text")
    # The panel: what this is, the numbers, the target and the steps.
    px, py, pw, ph = PANEL_BOX
    c.box((px, py, px + pw, py + ph), "panel", radius=14)
    inner, width = px + 28, pw - 56
    title, words = FOCUS_KINDS.get(f["kind"], ("FOCUSING", ""))
    top = c.wrap((inner, py + 26), title, "bold", 28, width, "accent", on="panel")
    top = c.wrap((inner, top + 4), words, "sans", 20, width, "text", on="panel") + 12
    rows = []
    for key, label in (("start_hfr", "AT THE START"), ("hfr", "NOW"), ("best_hfr", "BEST SO FAR")):
        if f.get(key) is not None:
            rows.append((f"{f[key]:.2f}", label + " · HFR"))
    top = number_rows(c, inner, top, rows)
    if f.get("usual_hfr"):
        target = f"usual best {f['usual_hfr']:.2f}"
        if f.get("tonight_best_hfr") is not None:
            target += f" · tonight's best so far {f['tonight_best_hfr']:.2f}"
        top = c.wrap((inner, top), target, "mono", 18, width, "live", on="panel") + 8
    if f.get("positions") and not f.get("card"):
        unit = "picture" if f["kind"] == "check" else ("step" if f["kind"] == "find" else "position")
        c.text((inner, top), f"{unit} {f['position']} of {f['positions']}", "bold", 22, "text", on="panel")
        top += 36
    top = checklist(c, inner, top + 4, f["steps"]) + 10
    story_card(c, s, inner, top, width, py + ph - 20)
    if f.get("card"):
        result_card(c, f["card"], LEFT)


NICE = (0.5, 1, 2, 3, 5, 10, 15, 20, 30)


def bullseye(c, p, cx, cy, r):
    """The true pole at the centre and the polar axis at its measured
    azimuth and altitude errors, as polaralign.py gives them: up is too
    high, east is to the right as seen facing north. The drift limit is a
    square, since it holds for each axis on its own. While a measurement is
    under way the last one is shown dimmed."""
    az, alt, limit = p.get("azimuth_deg"), p.get("altitude_deg"), p.get("limit_deg") or 1.0
    reach = next((n for n in NICE if n >= 1.4 * max(abs(az or 0), abs(alt or 0), limit)), NICE[-1])
    c.draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=COLOURS["raised"])
    for k in (1, 2):
        rr = r * k / 2
        c.draw.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), outline=COLOURS["muted"], width=2)
        c.text((cx + rr * 0.71 + 6, cy - rr * 0.71 - 6), f"{reach * k / 2:g}°", "mono", 18, "secondary",
               on="background", anchor="lb")
    side = r * limit / reach
    c.draw.rectangle((cx - side, cy - side, cx + side, cy + side), outline=COLOURS["live"], width=3)
    c.text((cx, cy + side + 6), "DRIFT LIMIT", "mono", 18, "live", on="raised", anchor="ma")
    c.draw.line([(cx - 14, cy), (cx + 14, cy)], fill=COLOURS["text"], width=3)
    c.draw.line([(cx, cy - 14), (cx, cy + 14)], fill=COLOURS["text"], width=3)
    for words, xy, anchor in (("TOO HIGH", (cx, cy - r - 8), "mb"), ("TOO LOW", (cx, cy + r + 8), "ma"),
                              ("EAST", (cx + r + 10, cy), "lm"), ("WEST", (cx - r - 10, cy), "rm")):
        c.text(xy, words, "mono", 18, "secondary", on="background", anchor=anchor)
    if az is not None and alt is not None:
        ax = cx + max(-r, min(r, r * az / reach))
        ay = cy - max(-r, min(r, r * alt / reach))
        colour = COLOURS["accent"] if p["stage"] != "measuring" else COLOURS["muted"]
        c.draw.line([(cx, cy), (ax, ay)], fill=colour, width=2)
        c.draw.ellipse((ax - 13, ay - 13, ax + 13, ay + 13), fill=colour)
    c.text((cx - r, cy + r + 44), "+ TRUE POLE   ● POLAR AXIS" + ("  (last measured)" if p["stage"] == "measuring"
                                                                 else ""), "mono", 18, "text")


def round_bars(c, rounds, x, y, w, most=8):
    """Each round's distance from the pole tonight, as a bar: the history of the alignment."""
    c.text((x, y), "ROUND BY ROUND", "bold", 22, "secondary")
    y += 40
    shown = rounds[-most:]
    if not shown:
        c.text((x, y), "The first measurement is under way", "sans", 22, "secondary")
        return y + 36
    top = max(r["total_deg"] for r in shown) or 1
    first = len(rounds) - len(shown)
    for i, r in enumerate(shown):
        c.text((x, y), f"{first + i + 1}", "mono", 20, "secondary")
        bar = max(6, (w - 150) * r["total_deg"] / top)
        last = i == len(shown) - 1
        c.box((x + 40, y + 2, x + 40 + bar, y + 26), "accent" if last else "muted", radius=4)
        c.text((x + 52 + bar, y), f"{r['total_deg']:.1f}°", "mono", 20, "text" if last else "secondary")
        y += 38
    return y


def polar_layout(c, s):
    p = s["polar"]
    x, y, w, h = LEFT
    bullseye(c, p, x + 330, y + 360, 260)
    right = x + 700
    top = round_bars(c, p.get("rounds") or [], right, y + 20, w - 700)
    top += 16
    if p["stage"] == "measuring":
        c.text((right, top), "THREE PICTURES, TURNING THE POLAR AXIS BETWEEN", "bold", 20, "secondary")
        checklist(c, right, top + 40, p["pictures_steps"], size=24, gap=40, on="background")
    elif p.get("advice") and p["stage"] == "adjust":
        c.text((right, top), "WHAT TO DO", "bold", 22, "attention")
        top += 38
        for line in p["advice"]:
            top = c.wrap((right, top), line, "sans", 22, w - 700, "text") + 8
    px, py, pw, ph = PANEL_BOX
    c.box((px, py, px + pw, py + ph), "panel", radius=14)
    inner, width = px + 28, pw - 56
    top = c.wrap((inner, py + 26), "POLAR ALIGNMENT", "bold", 28, width, "accent", on="panel")
    top = c.wrap((inner, top + 4), p["doing"], "sans", 21, width, "text", on="panel") + 12
    rows = []
    if p.get("total_deg") is not None:
        rows.append((f"{p['total_deg']:.1f}°", "FROM THE POLE"))
        rows.append((f"{abs(p['azimuth_deg']):.1f}°", f"AZIMUTH · {'EAST' if p['azimuth_deg'] > 0 else 'WEST'} OF NORTH"))
        rows.append((f"{abs(p['altitude_deg']):.1f}°", f"ALTITUDE · TOO {'HIGH' if p['altitude_deg'] > 0 else 'LOW'}"))
    top = number_rows(c, inner, top, rows)
    if p.get("previous_total_deg") is not None:
        top = c.wrap((inner, top), f"the round before: {p['previous_total_deg']:.1f}°", "mono", 18, width,
                     "secondary", on="panel") + 4
    if p.get("drift_px"):
        d = p["drift_px"]
        top = c.wrap((inner, top), f"drift in a {p['exposure_s']:g} s frame: {d['azimuth']:g} px azimuth, "
                     f"{d['altitude']:g} px altitude", "mono", 18, width, "secondary", on="panel") + 4
    if p.get("limit_deg"):
        top = c.wrap((inner, top), f"target: under the drift limit, {p['limit_deg']:.2f}° on each axis "
                     f"({p['limit_px']:g} px, a star's own size, in a {p['exposure_s']:g} s frame)", "mono", 18,
                     width, "live", on="panel") + 10
    story_card(c, s, inner, top, width, py + ph - 20)
    if p.get("card"):
        result_card(c, p["card"], LEFT)


def compose(state, stack=None, single=None):
    """The stream's picture for `state`, as a Canvas (its image and what was written)."""
    c = Canvas()
    if state["kind"] in ("focus", "polar"):
        header(c, state)
        c.text((WIDTH - MARGIN_X, MARGIN_Y), "● LIVE", "bold", 22, "live", anchor="ra")
        (focus_layout if state["kind"] == "focus" else polar_layout)(c, state)
        footer(c, state)
        return c
    if state["kind"] == "between":
        between(c, state, stack)
        footer(c, state)
        return c
    if state["kind"] == "open":
        open_card(c, state, stack)
        footer(c, state)
        return c
    header(c, state)
    sky_area(c, state, stack, single)
    side_panel(c, state)
    footer(c, state)
    c.crawl = (state.get("story") or {}).get("crawl")
    return c


# --- examples for the preview -----------------------------------------------------

def examples(now=None):
    """Example states for the preview: the figures are made up for the
    look only and are never sent anywhere."""
    now = now or 1792462896.0           # 20 October 2026, 02:21:36 UTC
    m31 = [{"id": f"P{i + 1}", "col": i % 4, "row": i // 4,
            "state": "done" if i < 5 else ("current" if i == 5 else "open")} for i in range(8)]
    ingress, egress = now - 40 * 60, now + 140 * 60
    rng = np.random.default_rng(1)

    def flux(t):
        inside = ingress + 20 * 60 < t < egress - 20 * 60
        return (1 - 0.014 if inside else 1) + rng.normal(0, 0.0022)
    points = [(t, flux(t)) for t in np.arange(ingress - 75 * 60, now, 300)]
    patrol = {"kind": "patrol", "target": "M31", "now": now, "exposure": 16, "last_age": 3,
              "combined": 225, "kept": 203, "captured": 211, "integration_s": 3248, "fwhm_arcsec": 5.8,
              "new_exposures": 1, "next": "M31 P7", "stage": "3 h 18 min observed · 5 fields done",
              "patrol": {"field": "Andromeda", "panels": m31, "possible": 0}}
    science = dict(patrol, story={"chapter": "SCIENCE", "card": ("SCIENCE", [
        "A nova is a white dwarf star pulling gas from a companion until the gas ignites: for a few days it "
        "shines thousands of times brighter."]), "line": None, "explainer": None, "crawl": None})
    coming = dict(patrol, story={"chapter": "COMING UP", "card": ("COMING UP IN ~12 MIN", [
        "WASP-12 b transit", "A star with a giant planet so close that it circles in just over a day."]),
        "line": "LOOK CLOSELY · Almost every sharp star in this picture is in our own galaxy, in front of Andromeda.",
        "explainer": None, "crawl": "TONIGHT   ·   M31 nova patrol   ·   5 of 8 M31 fields searched   ·   "
                                    "next: WASP-12 b transit"})
    return {
        "patrol": patrol,
        "science": science,
        "coming-up": coming,
        **{f"explain-{k}": dict(patrol, story={"chapter": "NOW", "card": None, "line": None, "explainer": k,
                                               "crawl": None})
           for k in ("stacking", "subtraction", "nova", "transit")},
        "explain-comet": dict(patrol, story={"chapter": "NOW", "card": None, "line": None, "explainer": "comet",
                                             "crawl": None, "comet": {"pictures": 74, "seen": 27, "group": "Kreutz",
                                                                      "hours": 7.0, "day": "19 October",
                                                                      "movie": None}}),
        "transit": {"kind": "transit", "target": "WASP-12", "now": now, "exposure": 4, "last_age": 2,
                    "combined": 980, "kept": 975, "captured": 980, "integration_s": 3900, "fwhm_arcsec": 4.9,
                    "next": "M31 P6 second look at 06:25 UTC",
                    "transit": {"planet": "WASP-12 b", "hot_jupiter": True, "depth": 0.014, "state": "live",
                                "ingress": ingress, "mid": (ingress + egress) / 2, "egress": egress,
                                "points": points}},
        "between": {"kind": "between", "target": "WASP-12", "now": now, "next": "WASP-12 b transit",
                    "between": {"programme": "Hot Jupiter transit", "begins_in_s": 240,
                                "steps": [("moving telescope", "done"), ("confirming field", "now"),
                                          ("checking focus", "open"), ("imaging", "open")]},
                    "tonight": [("M31 core", "done"), ("M31 panels", "done"), ("WASP-12 b", "running"),
                                ("M31 P6 second look", "open")]},
        "candidate": {**patrol, "patrol": {**patrol["patrol"], "possible": 1},
                      "candidate": {"stage": "second"}},
        "open": {"kind": "open", "target": "", "now": now, "open": {"lines": [
            ("THE SKY", "forecast GO, 20% cloud on average"), ("CLEAR SPELL", "21:00 to 03:00 UTC, about 6 h"),
            ("DARK", "astronomical darkness from 18:50 to 04:40 UTC"),
            ("THE MOON", "34% lit, waxing, sets 23:10 UTC"),
            ("TONIGHT WILL TRY", "M31 nova patrol, M31 mosaic fields, WASP-12 b transit, Tabby's star")]}},
        **focus_examples(now),
        **polar_examples(now),
    }


def example_star(spread, ring=False, size=64):
    """A made-up star for the preview: a soft spot, or a doughnut far out of focus."""
    yy, xx = np.indices((size, size)) - size / 2
    r = np.hypot(yy, xx)
    light = np.exp(-((r - spread) ** 2) / 18) * (r > spread * 0.45) if ring else np.exp(-(r ** 2) / (2 * spread ** 2))
    return Image.fromarray((255 * light / light.max()).astype(np.uint8))


def focus_examples(now):
    """Focus states for the preview, the figures made up for the look only
    (5.07 to 2.19 and the usual 2.28 are of the size real runs give)."""
    sweep = [(0, 5.07), (1024, 8.9), (768, 7.6), (512, 6.4), (256, 5.3), (0, 4.9), (-256, 3.7), (-512, 2.31)]
    base = {"kind": "focus", "stage": "sweep", "start_hfr": 5.07, "hfr": 2.31, "best_hfr": 2.31, "best_at": -512,
            "usual_hfr": 2.28, "tonight_best_hfr": 2.31, "at": -512, "position": 8, "positions": 9, "fit": None,
            "outcome": None,
            "readings": sweep, "rings": [], "card": None, "running": True, "showing": True,
            "steps": steps_of(["measure", "sweep", "fit", "verify"], "sweep"),
            "stars": {"start": example_star(9), "now": example_star(2.2)}}
    story = {"chapter": "HOW IT WORKS", "card": ("HOW FOCUSING WORKS", [
        "Star size against focuser position makes a V-shaped curve. A curve fitted through every point finds "
        "its bottom more surely than any one reading."])}
    walk = dict(base, kind="walk", stage="finest steps", position=None, positions=None, start_hfr=3.4,
                readings=[(0, 3.4), (-64, 3.0), (-128, 2.7), (-160, 2.5), (-176, 2.36), (-192, 2.29)],
                hfr=2.29, best_hfr=2.29, best_at=-192, steps=steps_of(["doughnuts", "coming in", "finest steps",
                                                                         "done"], "finest steps"))
    fitted = dict(base, stage="verify", fit={"ok": True, "focus": -560, "hfr": 2.2, "r2": 0.97},
                  readings=sweep + [(-768, 3.0), (-560, 2.19)], best_hfr=2.19, best_at=-560, hfr=2.19,
                  tonight_best_hfr=2.19,
                  steps=steps_of(["measure", "sweep", "fit", "verify"], "verify", True))
    return {
        "focus": {"kind": "focus", "target": "", "now": now, "focus": base, "story": story},
        "focus-walk": {"kind": "focus", "target": "", "now": now, "focus": walk, "story": story},
        "focus-complete": {"kind": "focus", "target": "", "now": now, "story": story,
                           "focus": dict(fitted, card=focus_card({"outcome": "complete", "start_hfr": 5.07,
                                                                  "end_hfr": 2.19}))},
        "focus-check-passed": {"kind": "focus", "target": "", "now": now, "story": story,
                               "focus": dict(base, kind="check", stage="measure", readings=[(0, 2.26), (0, 2.31),
                                                                                           (0, 2.24)],
                                             start_hfr=2.26, hfr=2.24, best_hfr=2.24, best_at=0, position=3,
                                             positions=3, steps=[("measure", "done")],
                                             card=focus_card({"outcome": "passed", "end_hfr": 2.26,
                                                              "usual_hfr": 2.28}))},
        "focus-rejected": {"kind": "focus", "target": "", "now": now, "story": story,
                           "focus": dict(base, stage="fit", steps=steps_of(["measure", "sweep", "fit", "verify"],
                                                                            "fit", True, True),
                                         card=focus_card({"outcome": "rejected", "words": (
                                             "No focus curve could be fitted to the sweep, so the focuser went "
                                             "back to where it started.")}))},
    }


def polar_examples(now):
    """Polar alignment states for the preview, from the real rounds early on
    22 October 2026 (9.6°, 2.5°, 4.2°, 1.8°, 1.2° from the pole, the night's
    notes); the sky-scaled azimuths and the timings are made up for the
    look only."""
    totals = [9.6, 2.5, 4.2, 1.8, 1.2]
    rounds = [{"total_deg": t, "measured": now - 600 * (len(totals) - i)} for i, t in enumerate(totals)]
    base = {"stage": "adjust", "rounds": rounds[:4], "azimuth_deg": -2.1,
            "altitude_deg": -1.3, "total_deg": 1.8, "previous_total_deg": 4.2, "limit_deg": 1.25, "limit_px": 2.0,
            "exposure_s": 16.0, "drift_px": {"azimuth": 3.4, "altitude": 2.1},
            "advice": ["Turn the whole tripod 2.1° clockwise, seen from above: about 4.8 cm at each foot, all "
                       "three the same way round.",
                       "Raise the polar axis 1.3° (about three quarters of a mark on the latitude scale)."],
            "card": None, "doing": "Waiting for the mount to be adjusted, then it measures again",
            "pictures_steps": [("picture 1", "done"), ("picture 2", "done"), ("picture 3", "done")]}
    story = {"chapter": "HOW IT WORKS", "card": ("HOW POLAR ALIGNMENT WORKS", [
        "Three pictures with only the polar axis turned between them land on a circle. The circle's centre is "
        "where the axis really points."])}
    measuring = dict(base, stage="measuring", rounds=rounds[:3], total_deg=4.2, previous_total_deg=2.5,
                     azimuth_deg=7.1, altitude_deg=-0.9, drift_px=None, advice=None,
                     doing="Recheck: picture 2 of 3",
                     pictures_steps=[("picture 1", "done"), ("picture 2", "now"), ("picture 3", "open")])
    done = dict(base, stage="complete", rounds=rounds, total_deg=1.2, previous_total_deg=1.8, azimuth_deg=-0.4,
                altitude_deg=-1.2, drift_px={"azimuth": 0.6, "altitude": 1.9}, advice=None,
                doing="Complete: the axis is close enough")
    done["card"] = polar_card(done)
    failed = dict(measuring, stage="failed", doing="The measurement failed",
                  words="A picture could not be plate-solved: cloud, or something in the way. Nothing was measured.")
    failed["card"] = polar_card(failed)
    return {name: {"kind": "polar", "target": "", "now": now, "polar": p, "story": story}
            for name, p in (("polar-measuring", measuring), ("polar-adjust", base), ("polar-complete", done),
                            ("polar-failed", failed))}


def example_pictures(seed=0):
    """A star field to stand in when there is no stack yet."""
    rng = np.random.default_rng(seed)
    h, w = 1000, 1500
    sky = rng.normal(40, 6, (h, w, 3))
    for _ in range(900):
        y, x = rng.integers(0, h), rng.integers(0, w)
        sky[max(0, y - 1):y + 2, max(0, x - 1):x + 2] += rng.uniform(40, 215)
    stack = Image.fromarray(np.clip(sky, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8))
    single = Image.fromarray(np.clip(sky + rng.normal(30, 25, sky.shape), 0, 255).astype(np.uint8))
    return stack, single


PHONE = (360, 203)        # a 1080p stream in a phone's player


def real_pictures(web, name):
    """(stack, single) from the night's own pictures in web/ for `name`,
    else None: the look is judged on real sky, not only made-up stars."""
    for stem in (f"{name}-final", name, f"{name}-P6-final", f"{name}-P1-final"):
        try:
            with Image.open(web / f"{stem}.jpg") as im:
                stack = im.convert("RGB")
            break
        except OSError:
            continue
    else:
        return None
    try:
        with Image.open(web / "latest.jpg") as im:
            single = im.convert("RGB")
    except OSError:
        single = None
    return stack, single


def preview(out, web=None, say=print):
    """Each example state at full size and at a phone's size, on real
    pictures from `web` where there are some, and index.html showing them
    all together so a change to the look can be seen at a glance."""
    made_up = example_pictures()
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, state in examples().items():
        stack, single = (real_pictures(web, state["target"]) if web is not None else None) or made_up
        started = time.perf_counter()
        canvas = compose(state, stack, single)
        picture = canvas.image
        if canvas.crawl:                                    # the crawl part-way along, as stream.py runs it
            moved = crawled(np.asarray(picture), crawl_strip(canvas.crawl), 14)
            picture = Image.fromarray(moved) if moved is not None else picture
        took = 1000 * (time.perf_counter() - started)
        picture.save(out / f"{name}.png")
        picture.resize(PHONE, Image.LANCZOS).save(out / f"{name}-phone.png")
        rows.append(f'<section><h2>{name} <small>{took:.0f} ms</small></h2>'
                    f'<a href="{name}.png"><img class="full" src="{name}.png"></a>'
                    f'<img class="phone" src="{name}-phone.png"></section>')
        say(f"{out / (name + '.png')}  ({took:.0f} ms)")
    (out / "index.html").write_text(
        "<!doctype html><meta charset=utf-8><title>Stream preview</title><style>"
        "body{background:#060A12;color:#EEF4FF;font-family:sans-serif;margin:24px}"
        "section{display:flex;gap:24px;align-items:flex-start;margin-bottom:32px;flex-wrap:wrap}"
        "h2{width:100%;margin:0}small{color:#A5B2C8;font-weight:normal}"
        ".full{width:960px;max-width:100%}.phone{width:360px;outline:1px solid #333}</style>"
        "<h1>The stream's look, each state, at full and phone size</h1>" + "".join(rows), encoding="utf-8")
    say(f"{out / 'index.html'}: all of them together")


# --- the state, from what is running ----------------------------------------------

def unix(jd):
    return (jd - 2440587.5) * 86400


def transit_for(name):
    """The planet `transits.py` kept for this star tonight, with its archive
    figures, or None."""
    import json

    import config
    import transits
    try:
        kept = json.loads((config.DATA / "cache" / "transients.json").read_text(encoding="utf-8"))
        planet = kept.get(name, {}).get("planet")
        if not planet:
            return None
        return next((r for r in transits.planets() if r["planet"] == planet), None)
    except Exception:
        return None


def measured(session, p):
    """The light curve `transits.py measure` last wrote for this session, as
    (unix time, relative flux) points, or []."""
    import json
    try:
        answer = json.loads((session / f"transit-{p['planet'].replace(' ', '')}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    points = [(unix(t), m) for t, m in zip(answer.get("jd", []), answer.get("mag", [])) if m is not None]
    return points


def transit_state(p, session, now):
    """The transit panel: the predicted times, and the measurements only
    once there are 30 minutes of them and they are steady enough (scatter
    under half the depth) to be worth showing."""
    import transits
    jd_now = now / 86400 + 2440587.5
    middles = transits.transits_between(p, jd_now - 1, jd_now + 1)
    middle = unix(min(middles, key=lambda m: abs(m - jd_now)))
    half = p["hours"] * 1800
    depth = p["depth"] / 100
    t = {"planet": p["planet"], "hot_jupiter": True, "depth": depth,
         "ingress": middle - half, "mid": middle, "egress": middle + half}
    points = measured(session, p) if session else []
    outside = [m for when, m in points if not (t["ingress"] <= when <= t["egress"])]
    span = (points[-1][0] - points[0][0]) / 60 if len(points) > 1 else 0
    if len(outside) >= 3:
        base = float(np.median(outside))
        flux = [(when, 10 ** (-0.4 * (m - base))) for when, m in points]
        out_flux = [f for when, f in flux if not (t["ingress"] <= when <= t["egress"])]
        scatter = float(np.std(out_flux, ddof=1))
    else:
        flux, scatter = [], None
    if span >= 30 and scatter is not None and scatter < depth / 2:
        t["state"], t["points"] = "live", flux
    else:
        t["state"] = "baseline" if now < t["ingress"] else "measuring"
        if now < t["ingress"]:
            t["baseline_words"] = (f"{span:.0f} min of the star's steady light so far · " if span else "") \
                + f"transit begins in {(t['ingress'] - now) / 60:.0f} min"
        else:
            t["baseline_words"] = "The light curve appears here once the measurements are steady enough to trust."
    return t


RESULT_S = 300             # a second look's result is shown strongly this long, then as one small line
_SEEN = {}


def follow_ups(sessions):
    """Each field looked at again tonight after an unexplained candidate:
    (field, the second look's session, still unexplained), oldest first."""
    out = []
    for field in dict.fromkeys(s["field"] for s in sessions):
        done = [s for s in sessions if s["field"] == field and s.get("finished")]
        if len(done) >= 2 and done[-2].get("unexplained"):
            out.append((field, done[-1]["session"], bool(done[-1].get("unexplained"))))
    return sorted(out, key=lambda r: r[1])


def patrol_state(name, discovery, now=None):
    """The patrol panel for a mosaic panel run (M31-P5): the panels as the
    night's discovery summary lays them out, the possible changes, and a
    candidate's follow-up while it is news."""
    now = now or time.time()
    field, _, number = name.partition("-P")
    mosaic = next((m for m in (discovery or {}).get("mosaics", []) if m["name"] == field), None)
    if mosaic is None or not number.isdigit():
        return None, None
    panels = []
    for panel in mosaic["panels"]:
        n = panel["panel"]
        state = "current" if n == int(number) else ("done" if panel.get("state") == "done" else "open")
        panels.append({"id": f"P{n}", "col": (n - 1) % mosaic["columns"], "row": (n - 1) // mosaic["columns"],
                       "state": state})
    sessions = [s for s in (discovery or {}).get("sessions", []) if s["field"].startswith(field)]
    possible = sum(1 for s in sessions if s.get("unexplained"))
    candidate = None
    # A second look: this panel was searched once earlier tonight, with something unexplained.
    earlier = [s for s in sessions if s["field"] == name and s.get("finished")]
    if len(earlier) == 1 and earlier[0].get("unexplained"):
        candidate = {"stage": "second"}
    results = follow_ups(sessions)
    if results and candidate is None:
        where, session, still = results[-1]
        first = _SEEN.setdefault((where, session), now)
        if now - first < RESULT_S:
            candidate = {"stage": "result", "result": "Still unexplained: kept for private checking." if still
                         else "Not confirmed: it did not appear again."}
    awaiting = sum(1 for _, _, still in results if still)
    entry = targets().get("targets", {}).get(field, {})
    label = entry.get("common", field).split()[0]
    return {"field": label, "panels": panels, "possible": possible, "awaiting": awaiting}, candidate


def stage(steps, now):
    """One line on how the night is going, from tonight's schedule."""
    started = [s["start"] for s in steps if s.get("start")]
    done = sum(1 for s in steps if s.get("status") == "done")
    if not started:
        return None
    running = [s for s in steps if s.get("status") == "running"]
    if running and running[-1] is steps[-1]:
        return "Last target before dawn"
    hours, minutes = divmod(int((now - min(started)) / 60), 60)
    return f"{hours} h {minutes:02d} min observed · {done} step{'s' if done != 1 else ''} done"


def depth_of(discovery):
    """The newest searched session's depth tonight: the magnitude at which
    half of the planted stars were found, or None."""
    import json

    import config
    for row in reversed((discovery or {}).get("sessions") or []):
        try:
            found = json.loads((config.DATA / "frames" / row["field"] / row["session"] / "depth.json")
                               .read_text(encoding="utf-8"))
            return found["completeness"]["all"]["mag_50"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return None


def told(s, st, now):
    """The presenter's additions for this picture (streamstory.py)."""
    import streamstory
    live = dict(st, depth_mag=depth_of(st.get("discovery")) if s.get("kind") == "patrol" else None)
    return streamstory.plan(s, live, now)


HOLD_S = 30               # the star size shown changes at most this often
_HELD = {"value": None, "at": 0.0}


def held_star_size(fwhm, scale, now):
    """The star size in arcseconds: the median of the last 10 kept frames,
    changed at most every HOLD_S so seeing's flicker does not look like a
    fault."""
    if not fwhm or not scale:
        return None
    if _HELD["value"] is None or now - _HELD["at"] >= HOLD_S:
        _HELD.update(value=float(np.median(fwhm[-10:])) * scale, at=now)
    return _HELD["value"]


def moon_now(now):
    """sky.moon_state at the observatory's own site (the example site in the
    demo and the tests), or {} if it cannot be worked out."""
    import config
    import sky
    from datetime import datetime, timezone
    try:
        site = config.example()["site"] if config.DEMO else config.load()["site"]
        return sky.moon_state(site, datetime.fromtimestamp(now, timezone.utc))
    except Exception:
        return {}


LUCKY_STAGES = {"centring": "FINDING THE MOON", "capturing": "CAPTURING FRAMES",
                "ranking": "FINDING THE SHARPEST MOMENTS", "stacking": "CORRECTING THE ATMOSPHERE",
                "done": "RESULT READY"}


def lucky_stage(now, fresh=120):
    """(title, figures) for where the lucky imaging has got, from
    web/lucky.json (lucky.progress), or None when it says nothing recent."""
    import json
    import config
    try:
        p = json.loads((config.DATA / "web" / "lucky.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if now - p.get("at", 0) > fresh or p.get("stage") not in LUCKY_STAGES:
        return None
    stage = p["stage"]
    if stage == "capturing":
        words = (f"{p.get('done', 0):,} / {p.get('frames', 0):,} · {p.get('fps', 0):g} a second · "
                 f"{1000 * p.get('exposure', 0):.0f} ms exposures")
    elif stage in ("ranking", "stacking"):
        words = f"{p.get('done', 0):,} / {p.get('frames', 0):,}" + (
            f" · {p['points']} alignment regions" if p.get("points") else "")
    elif stage == "done":
        words = f"best {p.get('kept', 0):,} of {p.get('frames', 0):,} frames"
    else:
        words = "centring the disc from its own picture"
    return LUCKY_STAGES[stage], words


def live_now():
    """True while the live view (liveview.py) is showing what the telescope sees."""
    try:
        import activity
        return activity.phase() == "live"
    except Exception:
        return False


def lucky_now():
    """True while a lucky-imaging video is taken or stacked (lucky.py)."""
    try:
        import activity
        return activity.phase() == "lucky"
    except Exception:
        return False


def from_status(st, now=None, session=None):
    """The picture's state from web/status.json, as stream.py reads it."""
    now = now or time.time()
    name = st.get("name") or ""
    series = st.get("series") or {}
    fwhm = [f for f, ok in zip(series.get("fwhm") or [], series.get("accepted") or []) if f and ok]
    try:
        import focus
        scale = focus.arcsec_per_pixel()
    except Exception:
        scale = None
    steps = (st.get("schedule") or {}).get("steps") or []
    upcoming = next((s for s in steps if s.get("status") == "queued"), None)
    s = {"kind": "picture", "target": name.partition("-P")[0] if "-P" in name else name, "now": now,
         "exposure": st.get("exposure"), "last_age": st.get("age"), "combined": st.get("accepted"),
         "kept": st.get("accepted"), "captured": (st.get("captured") or 0) - (st.get("waiting") or 0), "integration_s": st.get("integration"),
         "fwhm_arcsec": held_star_size(fwhm, scale, now),
         "next": (f"{upcoming['label'].split(',')[0]}" + (f" at {utc(upcoming['start'])}" if upcoming.get("start") else ""))
         if upcoming else None,
         "stage": stage(steps, now)}
    if lucky_now() or live_now():
        # A lucky-imaging video or the live view keeps no run status: its own newest picture
        # says how fresh it is, and the last run's figures and schedule are
        # not tonight's (30 October 2026: "PAUSED · no new exposure for 8683 min").
        import config
        try:
            s["last_age"] = now - (config.DATA / "web" / "latest.jpg").stat().st_mtime
        except OSError:
            s["last_age"] = None
        s["exposure"], s["stage"], s["next"] = None, None, None
        s["combined"] = s["kept"] = None
        s["live"] = live_now()
    import sky
    if (st.get("object_kind") or sky.object_kind(name)) == "moon":
        s["kind"], s["moon"], s["fwhm_arcsec"] = "moon", moon_now(now), None
        s["lucky"] = lucky_now()
        s["lucky_stage"] = lucky_stage(now) if s["lucky"] else None
        s["story"] = told(s, st, now)
        return s
    p = transit_for(name)
    if p:
        s["kind"], s["transit"] = "transit", transit_state(p, session, now)
        s["story"] = told(s, st, now)
        return s
    patrol, candidate = patrol_state(name, st.get("discovery"), now)
    if patrol:
        s["kind"], s["patrol"] = "patrol", patrol
        if candidate:
            s["candidate"] = candidate
    s["story"] = told(s, st, now)
    return s


# --- the state of a focus run or a polar alignment, from their own files ----------

LIVE_S = 600              # a run that has written nothing for this long has stopped, whatever it said
CARD_S = 10               # a finished run's card is held this long
ADJUST_S = 15 * 60        # after a polar measurement, the bolts are being turned for up to this long


def _kept(path):
    import json
    try:
        found = json.loads(Path(path).read_text(encoding="utf-8"))
        return found if isinstance(found, dict) else None
    except (OSError, ValueError):
        return None


def _picture(path, since):
    """A small picture written since `since`, or None."""
    try:
        if Path(path).stat().st_mtime < since - 1:
            return None
        with Image.open(path) as im:
            return im.convert("L").copy()
    except OSError:
        return None


def _alive(pid):
    import activity
    return pid is not None and activity._alive(pid)


def steps_of(steps, stage, ended=False, failed=False):
    """[(step, "done" | "now" | "open" | "failed")] for a run at `stage`."""
    at = steps.index(stage) if stage in steps else -1
    out = []
    for i, name in enumerate(steps):
        if ended and not failed:
            status = "done"
        elif i < at:
            status = "done"
        elif i == at:
            status = "failed" if failed else "now"
        else:
            status = "open"
        out.append((name, status))
    return out


NIGHT_S = 12 * 3600       # a focus run further back than this was another night


def tonight_best(this_run, now, runs_file):
    """The sharpest HFR tonight: this run's best and every run or check
    kept in focus.py's RUNS_FILE in the last NIGHT_S. None if none."""
    import json
    found = [this_run] if this_run is not None else []
    try:
        for line in Path(runs_file).read_text(encoding="utf-8").splitlines():
            try:
                run = json.loads(line)
            except ValueError:
                continue
            value = run.get("best_hfr", run.get("checked_hfr"))
            if value is not None and 0 <= now - float(run.get("saved", 0)) <= NIGHT_S:
                found.append(float(value))
    except OSError:
        pass
    return round(min(found), 2) if found else None


def focus_card(f):
    """(title, line, colour) for how a focus run ended, said plainly."""
    start, end, usual = f.get("start_hfr"), f.get("end_hfr"), f.get("usual_hfr")
    outcome = f.get("outcome")
    if outcome == "complete" and start and end:
        smaller = round(100 * (1 - end / start))
        return ("FOCUS COMPLETE", f"{start:.2f} → {end:.2f} HFR" + (f", {smaller}% smaller stars" if smaller > 0
                                                                   else ": as sharp as it was"), "live")
    if outcome in ("left_alone", "passed") and end:
        return ("FOCUS CHECK PASSED", f"HFR {end:.2f}" + (f", as good as the usual best of {usual:.2f}" if usual
                                                          else "") + ": left as it is.", "live")
    if outcome == "soft" and end:
        return ("FOCUS IS SOFT", f"HFR {end:.2f}" + (f" against the usual best of {usual:.2f}" if usual else "")
                + ": worth focusing.", "attention")
    titles = {"rejected": ("FOCUS CURVE REJECTED", "attention"), "returned": ("FOCUS RETURNED TO START", "attention"),
              "failed": ("FOCUS RUN STOPPED", "attention"), "swept": ("FOCUS CURVE MEASURED", "live"),
              "found": ("STARS FOUND", "live"), "not_found": ("NO STARS FOUND", "attention"),
              "complete": ("FOCUS COMPLETE", "live")}
    title, colour = titles.get(outcome, ("FOCUS RUN ENDED", "attention"))
    return title, f.get("words") or "", colour


def focus_stream_state(now=None, path=None):
    """What a focus run is doing, from focus.py's STREAM_FILE: its kind,
    stage and steps, the start, current, best and usual HFR, where the
    focuser is, the fit, every reading, the star at the start and now, and
    once it has ended the card saying how. None when there is no such file.
    "showing" says whether the stream should show it now."""
    import focus
    path = Path(path or focus.STREAM_FILE)
    f = _kept(path)
    if not f:
        return None
    now = now or time.time()
    ended = f.get("ended")
    running = ended is None and _alive(f.get("pid")) and now - f.get("updated", 0) < LIVE_S
    card = focus_card(f) if ended is not None and 0 <= now - ended < CARD_S else None
    steps = f.get("steps") or []
    out = {k: f.get(k) for k in ("kind", "stage", "start_hfr", "hfr", "best_hfr", "best_at", "usual_hfr", "at",
                                 "position", "positions", "fit", "outcome", "words", "end_hfr", "started", "ended")}
    out.update(running=running, card=card, showing=bool(running or card),
               steps=steps_of(steps, f.get("stage"), ended is not None,
                              f.get("outcome") in ("failed", "rejected", "returned", "not_found")),
               readings=[(r["at"], r["hfr"]) for r in f.get("readings") or [] if r.get("hfr") is not None],
               rings=[(r["at"], r["ring"]) for r in f.get("readings") or [] if r.get("ring")],
               count=len(f.get("readings") or []),
               last_hfr=(f.get("readings") or [{}])[-1].get("hfr"),
               tonight_best_hfr=tonight_best(f.get("best_hfr"), now, path.with_name("focus_runs.jsonl")),
               stars={"start": _picture(path.with_name("focus_star_start.png"), f.get("started", 0)),
                      "now": _picture(path.with_name("focus_star_now.png"), f.get("started", 0))})
    return out


def polar_card(p):
    if p["stage"] == "complete":
        totals = [r["total_deg"] for r in p.get("rounds") or []]
        line = (f"{totals[0]:.1f}° → {totals[-1]:.1f}° from the pole" if len(totals) > 1
                else f"{p['total_deg']:.1f}° from the pole") + ": under the drift limit on both axes."
        return "POLAR ALIGNMENT COMPLETE", line, "live"
    return "POLAR MEASUREMENT FAILED", p.get("words") or "Nothing was measured.", "attention"


def polar_stream_state(now=None, path=None):
    """Where a polar alignment has got, from polaralign.py's STREAM_FILE:
    the stage (measuring, adjust, complete, failed), the picture being taken
    of three, the error now and the round before, tonight's rounds, the
    drift each axis causes, the drift limit and the advice; and a card once
    it is complete or has failed. None when there is no such file."""
    import polaralign
    p = _kept(Path(path or polaralign.STREAM_FILE))
    if not p:
        return None
    now = now or time.time()
    stage, updated, ended = p.get("stage"), p.get("updated", 0), p.get("ended")
    running = stage == "measuring" and _alive(p.get("pid")) and now - updated < LIVE_S
    adjusting = stage == "adjust" and 0 <= now - updated < ADJUST_S
    card = polar_card(p) if stage in ("complete", "failed") and ended and 0 <= now - ended < CARD_S else None
    rounds = p.get("rounds") or []
    if rounds and now - rounds[-1].get("measured", 0) > polaralign.NIGHT_S:
        rounds = []
    picture, taken = p.get("picture") or 1, p.get("taken") or 0
    out = dict(p, rounds=rounds, running=running, adjusting=adjusting, card=card,
               showing=bool(running or adjusting or card),
               pictures_steps=[(f"picture {n}", "done" if n <= taken else ("now" if n == picture else "open"))
                               for n in (1, 2, 3)])
    recheck = "Recheck" if p.get("recheck") else "Measuring"
    out["doing"] = {"measuring": f"{recheck}: picture {picture} of 3",
                    "adjust": "Waiting for the mount to be adjusted, then it measures again",
                    "complete": "Complete: the axis is close enough",
                    "failed": "The measurement failed",
                    "measured": "Measured"}.get(stage, "")
    return out
