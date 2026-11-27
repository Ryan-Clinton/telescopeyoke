"""The report's three figures, drawn as plain SVG from the recorded numbers (no plotting library).
Numbers: docs/free-tools-plan.md (denoising, first round) and confirmation-results.md (53 stacks)."""
import json
from pathlib import Path

HERE = Path(__file__).parent
INK, MUTED, ACCENT, GRID, FONT = "#1f2933", "#7b8794", "#2f6fdf", "#e4e7eb", "font-family='Helvetica, Arial, sans-serif'"


def svg(w, h, body):
    return (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {w} {h}' width='{w}' height='{h}' {FONT}>"
            f"<rect width='{w}' height='{h}' fill='white'/>{body}</svg>")


def text(x, y, s, size=13, fill=INK, anchor="start", weight="normal"):
    return f"<text x='{x}' y='{y}' font-size='{size}' fill='{fill}' text-anchor='{anchor}' font-weight='{weight}'>{s}</text>"


def denoise():
    # (method, filament kept %, error against blur) at half the grain, ten held-out pairs
    # each label's offset from its point, so close points' labels do not overlap
    rows = [("Plain blur", 96.4, 1.000, (10, 4)), ("GraXpert 3.0.2", 88.5, 0.971, (-10, 4)), ("DeepSNR 1.3.2", 89.1, 0.974, (10, 14)),
            ("Cosmic Clarity AI3.6", 85.9, 0.985, (10, 16)), ("TelescopeYoke's own model", 84.1, 0.984, (-10, -8)),
            ("Siril NL-Bayes", 76.0, 1.017, (10, 4)), ("Seti Astro AI4", 65.3, 1.027, (10, 4))]
    W, H, L, R, T, B = 720, 430, 70, 200, 50, 60
    x = lambda v: L + (v - 60) / (100 - 60) * (W - L - R)
    y = lambda v: T + (v - 0.96) / (1.04 - 0.96) * (H - T - B)
    out = [text(L, 28, "Noise reduction: faint filament kept against error", 16, weight="bold")]
    for v in (60, 70, 80, 90, 100):
        out += [f"<line x1='{x(v)}' y1='{T}' x2='{x(v)}' y2='{H - B}' stroke='{GRID}'/>", text(x(v), H - B + 18, f"{v}%", 11, MUTED, "middle")]
    for v in (0.96, 0.98, 1.00, 1.02, 1.04):
        out += [f"<line x1='{L}' y1='{y(v)}' x2='{W - R}' y2='{y(v)}' stroke='{GRID}'/>", text(L - 8, y(v) + 4, f"{v:.2f}", 11, MUTED, "end")]
    out += [text((L + W - R) / 2, H - 18, "Planted filament kept (higher is better)", 12, MUTED, "middle"),
            f"<text transform='translate(18,{(T + H - B) / 2}) rotate(-90)' font-size='12' fill='{MUTED}' text-anchor='middle'>Error against an independent stack, blur = 1 (lower is better)</text>"]
    for name, kept, err, (dx, dy) in rows:
        c = ACCENT if name.startswith("GraXpert") else INK
        out += [f"<circle cx='{x(kept)}' cy='{y(err)}' r='6' fill='{c}'/>",
                text(x(kept) + dx, y(err) + dy, name, 12, c, "end" if dx < 0 else "start")]
    out.append(text(L, H - 2, "Ten held-out half-stack pairs, compared at half the original grain.", 11, MUTED))
    return svg(W, H, "".join(out))


def bars(title, rows, maximum, unit, note, highlight):
    W, L, R, T, rowh = 720, 250, 70, 50, 34
    H = T + rowh * len(rows) + 50
    out = [text(20, 28, title, 16, weight="bold")]
    for i, (name, v, label) in enumerate(rows):
        yy = T + i * rowh
        w = (W - L - R) * v / maximum
        c = ACCENT if name in highlight else "#9aa5b1"
        out += [text(L - 10, yy + 20, name, 13, INK, "end"), f"<rect x='{L}' y='{yy + 6}' width='{w:.1f}' height='20' fill='{c}'/>",
                text(L + w + 8, yy + 21, label, 12, INK)]
    out.append(text(20, H - 14, note, 11, MUTED))
    return svg(W, H, "".join(out))


(HERE / "fig-denoise.svg").write_text(denoise())
(HERE / "fig-star-removal.svg").write_text(bars(
    "Star removal on 53 stacks: Dark Star blended against TelescopeYoke's old code",
    [("Faint line kept (rule set first)", 53, "53 of 53"), ("Typical star removed (added after)", 52, "52 of 53"),
     ("Hardest tenth removed (added after)", 46, "46 of 53")], 53, "", "Pass counts. The last two rules were added after the first run showed the first alone was not enough.",
    {"Faint line kept (rule set first)"}))
(HERE / "fig-stretch.svg").write_text(bars(
    "Stretch: faint planted lines over the grain, 53 stacks (median)",
    [("TelescopeYoke's own", 10.1, "10.1"), ("Siril GHS", 5.7, "5.7"), ("Siril autostretch", 5.4, "5.4"),
     ("Seti Astro statistical stretch", 5.4, "5.4")], 11, "", "Higher shows faint nebula more clearly above the grain. Sky levels differ: TelescopeYoke's near black, the others 0.25.",
    {"TelescopeYoke's own"}))
print(json.dumps(sorted(p.name for p in HERE.glob("*.svg"))))
