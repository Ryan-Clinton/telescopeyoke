#!/usr/bin/env python3
"""The live stream's picture, drawn as docs/stream-look.md sets it out.

    ./stream.py preview            each state as a 1920 x 1080 picture, in cache/stream-preview/

`compose(state, stack, single)` draws one picture from a state (what is
running, its figures and its programme) and the two pictures (the stack and
one exposure). Every piece of text goes through `Canvas.text`, which keeps
what was written, where, and on what, so the tests can check the words,
the margins and the contrast without reading pixels.

Built first as a preview, from example states, so the look can be judged
before it is wired into the stream: `stream.py` still sends its old picture.
"""
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


def font(kind, size):
    try:
        return ImageFont.truetype(str(FONT_DIR / FONTS[kind]), size)
    except OSError:
        return ImageFont.load_default(size=size)


def targets():
    try:
        return tomllib.loads(TARGETS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


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


def display(picture, sky=0.09):
    """The picture as shown on the stream: the sky dark and neutral without
    clipping faint structure, faint light lifted gently, bright stars
    rounded off before they clip, a little more colour. Its own background
    and noise set it (each picture is normalised independently), so one
    exposure and the stack share a style, not numbers. Shows only: nothing
    measured ever reads it, and it adds no detail."""
    a = np.asarray(picture.convert("RGB"), dtype=np.float32) / 255.0
    small = a[::4, ::4].reshape(-1, 3)
    background = np.median(small, axis=0)
    noise = 1.4826 * np.median(np.abs(small - background), axis=0) + 1e-4
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
        c.text((WIDTH - MARGIN_X, y), f"NEXT · {s['next']}", "mono", 21, "secondary", anchor="ra")


STACK_BOX = (MARGIN_X, MARGIN_Y + 50, 1274, 870)        # x, y, width, height
PANEL_BOX = (MARGIN_X + 1274 + 24, MARGIN_Y + 50, WIDTH - 2 * MARGIN_X - 1274 - 24, 870)


def sky_area(c, s, stack, single):
    x, y, w, h = STACK_BOX
    if stack is None:
        c.box((x, y, x + w, y + h), "panel")
        c.text((x + w // 2, y + h // 2), "The picture builds up after the first few exposures",
               "sans", 25, "secondary", on="panel", anchor="mm")
        return
    shown = fit(display(shrunk(stack, (w, h))), (w, h))
    age = s.get("last_age") or 0
    if age > 120:
        # Paused: a little dimmer and greyer, so it reads as waiting, not broken.
        grey = shown.convert("L").convert("RGB")
        shown = Image.blend(Image.blend(shown, grey, 0.4), Image.new("RGB", shown.size, (0, 0, 0)), 0.25)
    c.image.paste(shown, (x, y))
    plate = COLOURS["background"]
    if s.get("combined"):
        c.box((x + 16, y + h - 54, x + 540, y + h - 14), plate, radius=8)
        words = c.text((x + 30, y + h - 46), f"{s['combined']} exposures combined", "mono", 21, "secondary",
                       on=plate)
        if s.get("new_exposures"):
            c.text((words[2] + 18, y + h - 46), f"+{s['new_exposures']} exposure"
                   + ("s" if s["new_exposures"] > 1 else ""), "mono", 21, "live", on=plate)
    if single is not None:
        iw, ih = 300, 200
        ix, iy = x + w - iw - 20, y + h - ih - 20
        c.image.paste(fit(display(shrunk(single, (iw, ih))), (iw, ih)), (ix, iy))
        c.box((ix, iy, ix + iw, iy + ih), None, outline="secondary", width=2, radius=4)
        c.box((ix, iy - 34, ix + iw, iy - 4), plate, radius=6)
        exposure = s.get("exposure")
        c.text((ix + 10, iy - 30), "ONE EXPOSURE" + (f" · {exposure:g} s" if exposure else ""),
               "mono", 19, "text", on=plate)


def about(c, s, x, y, width):
    """The object: its name, common name, plain words and one line of facts."""
    entry = targets().get("targets", {}).get(s["target"], {})
    c.text((x, y), s["target"], "bold", 50, "text", on="panel")
    y += 64
    if entry.get("common"):
        c.text((x, y), entry["common"].upper(), "bold", 24, "secondary", on="panel")
        y += 38
    if entry.get("words"):
        y = c.wrap((x, y + 6), entry["words"], "sans", 22, width, "text", on="panel") + 4
    facts = " · ".join(str(f) for f in (entry.get("distance"),
                                         f"magnitude {entry['magnitude']}" if entry.get("magnitude") else None) if f)
    if facts:
        y = c.wrap((x, y), facts, "mono", 18, width, "secondary", on="panel") + 6
    elif not entry and s.get("kind_of_object"):
        c.text((x, y), s["kind_of_object"], "sans", 22, "secondary", on="panel")
        y += 30
    return y + 18


def figures(c, s, x, y, bottom):
    rows = []
    if s.get("kept") is not None and s.get("captured"):
        rows.append((f"{s['kept']} / {s['captured']}", "FRAMES KEPT"))
    if s.get("integration_s"):
        minutes = s["integration_s"] / 60
        rows.append((f"{minutes:.0f} MIN" if minutes < 120 else f"{minutes / 60:.1f} H", "LIGHT COLLECTED"))
    if s.get("fwhm_arcsec"):
        rows.append((f"{s['fwhm_arcsec']:.1f}″", "STAR SIZE"))
    for number, label in rows[:max(0, min(3, int((bottom - y) // 78)))]:
        c.text((x, y), number, "bold", 36, "text", on="panel")
        c.text((x, y + 44), label, "sans", 18, "secondary", on="panel")
        y += 78
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
        y = c.wrap((x, y), f"NOVA PATROL · {p['field'].upper()}", "bold", 24, width, "accent", on="panel")
        y = c.wrap((x, y + 4), "Every star in this picture is being compared with an earlier night.",
                   "sans", 22, width, "text", on="panel") + 10
        bottom = panel_map(c, p, x, y)
        done = sum(panel["state"] == "done" for panel in p["panels"])
        c.text((x + 272, y + 2), f"{done} / {len(p['panels'])}", "bold", 30, "text", on="panel")
        c.text((x + 272, y + 40), "SEARCHED", "sans", 18, "secondary", on="panel")
        y = bottom + 14
        words = (f"{p['possible']} possible change{'s' if p['possible'] != 1 else ''}, being checked "
                 "automatically" if p.get("possible") else "No confirmed new star yet")
        return c.wrap((x, y), words, "sans", 20, width, "secondary", on="panel") + 14
    if kind == "transit":
        t = s["transit"]
        c.text((x, y), t["planet"], "bold", 26, "accent", on="panel")
        c.text((x, y + 36), "HOT JUPITER TRANSIT" if t.get("hot_jupiter") else "PLANET TRANSIT",
               "bold", 20, "secondary", on="panel")
        y = c.wrap((x, y + 70), f"The planet passes in front of its star and dims it by about "
                   f"{100 * t['depth']:.1f} %.", "sans", 22, width, "text", on="panel") + 10
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
    if kind == "picture":
        c.text((x, y), "BUILDING A PICTURE", "bold", 26, "accent", on="panel")
        return c.wrap((x, y + 40), "Every exposure is added to the stack; the noise falls as they add up.",
                      "sans", 22, width, "text", on="panel") + 10
    return y


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
    c.text((x, y), title, "bold", 26, "attention", on="panel")
    y = c.wrap((x, y + 42), words, "sans", 22, width, "text", on="panel") + 12
    steps = [("candidate", "detected"), ("second look", "second"), ("catalogue checks", "result"),
             ("result", "result")]
    order = ["detected", "second", "result"]
    for name, stage in steps:
        done = order.index(stage) < order.index(k["stage"]) or (k["stage"] == "result")
        mark, colour = ("✓", "live") if done else (("●", "accent") if stage == k["stage"] else ("○", "secondary"))
        c.text((x, y), f"{mark}  {name}", "sans", 21, colour, on="panel")
        y += 32
    return y + 10


def side_panel(c, s):
    x, y, w, h = PANEL_BOX
    c.box((x, y, x + w, y + h), "panel", radius=14)
    inner = x + 28
    width = w - 56
    top = about(c, s, inner, y + 26, width)
    top = programme(c, s, inner, top, width)
    # The programme comes first; the figures take what room is left (PRIORITY).
    figures(c, s, inner, max(top + 10, y + h - 3 * 78 - 10), y + h - 10)


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


def end_card(c, s, stack):
    e = s["end"]
    if stack is not None:
        c.image.paste(fit(display(shrunk(stack, (900, 640))), (900, 640)), (WIDTH - MARGIN_X - 900, 220))
    x, y = MARGIN_X + 40, 220
    c.text((x, y), "TONIGHT COMPLETE", "bold", 48, "text")
    y += 90
    for line in e["lines"]:
        c.text((x, y), line, "sans", 28, "text")
        y += 48
    c.text((x, HEIGHT - MARGIN_Y - 60), "TELESCOPEYOKE", "bold", 26, "accent")


def compose(state, stack=None, single=None):
    """The stream's picture for `state`, as a Canvas (its image and what was written)."""
    c = Canvas()
    if state["kind"] == "between":
        between(c, state, stack)
        footer(c, state)
        return c
    if state["kind"] == "end":
        end_card(c, state, stack)
        return c
    header(c, state)
    sky_area(c, state, stack, single)
    side_panel(c, state)
    footer(c, state)
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
    return {
        "patrol": patrol,
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
        "end": {"kind": "end", "target": "M31", "now": now,
                "end": {"lines": ["6 targets observed", "1 h 47 min of light collected", "742 frames kept",
                                  "8 M31 panels searched · 0 confirmed new stars"]}},
    }


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


def preview(out, web=None, say=print):
    """Each example state as a picture in `out`, using the real stack and
    newest exposure from `web` when there are some."""
    stack, single = example_pictures()
    if web is not None:
        try:
            stack = Image.open(web / "stack.jpg").convert("RGB")
            single = Image.open(web / "latest.jpg").convert("RGB")
        except OSError:
            pass
    out.mkdir(parents=True, exist_ok=True)
    for name, state in examples().items():
        started = time.perf_counter()
        compose(state, stack, single).image.save(out / f"{name}.png")
        say(f"{out / (name + '.png')}  ({1000 * (time.perf_counter() - started):.0f} ms)")


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


def patrol_state(name, discovery):
    """The patrol panel for a mosaic panel run (M31-P5): the panels as the
    night's discovery summary lays them out, and the possible changes."""
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
    # A second look: this panel was searched earlier tonight with something unexplained.
    earlier = [s for s in sessions if s["field"] == name and s.get("finished")]
    candidate = None
    if earlier and earlier[-1].get("unexplained") and not earlier[-1].get("second_look_of"):
        candidate = {"stage": "second"}
    entry = targets().get("targets", {}).get(field, {})
    label = entry.get("common", field).split()[0]
    return {"field": label, "panels": panels, "possible": possible}, candidate


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
         "kept": st.get("accepted"), "captured": st.get("captured"), "integration_s": st.get("integration"),
         "fwhm_arcsec": float(np.median(fwhm[-20:])) * scale if fwhm and scale else None,
         "next": (f"{upcoming['label']}" + (f" at {utc(upcoming['start'])}" if upcoming.get("start") else ""))
         if upcoming else None,
         "stage": stage(steps, now)}
    p = transit_for(name)
    if p:
        s["kind"], s["transit"] = "transit", transit_state(p, session, now)
        return s
    patrol, candidate = patrol_state(name, st.get("discovery"))
    if patrol:
        s["kind"], s["patrol"] = "patrol", patrol
        if candidate:
            s["candidate"] = candidate
    return s
