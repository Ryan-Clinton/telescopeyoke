#!/usr/bin/env python3
"""A printable degree dial for the focus knob, at true size.

    ./focusdial.py                      for a 40 mm knob, into web/focus-dial.svg
    ./focusdial.py --diameter 38.5      another knob

At f/5 the zone of sharp focus is about 0.067 mm of drawtube, and a Sharpie
line on the tube is ten times wider. A turn of the knob moves the tube many
millimetres, so 1 degree on the knob is about one zone: glue the strip round
the knob's rim (or the disc on its end), fix a pointer to the focuser body,
and read focus to a degree; the line on the tube says which turn. Print at
100% ("actual size", never "fit to page") and check the 50 mm bar with a
ruler before cutting. 2 November 2026.
"""
import argparse
import math
from pathlib import Path

import config

OUT = config.DATA / "web" / "focus-dial.svg"


def ticks(length, height, x0=0.0, y0=0.0):
    """SVG lines and labels for 0-359 degrees along a strip `length` mm long."""
    out = []
    for deg in range(360):
        x = x0 + length * deg / 360
        tall = height if deg % 10 == 0 else height * 0.65 if deg % 5 == 0 else height * 0.4
        out.append(f'<line x1="{x:.3f}" y1="{y0:.3f}" x2="{x:.3f}" y2="{y0 + tall:.3f}" '
                   f'stroke="black" stroke-width="{0.12 if deg % 10 else 0.2}"/>')
        if deg % 30 == 0:
            out.append(f'<text x="{x + 0.4:.3f}" y="{y0 + height + 2.6:.3f}" font-size="2.4" '
                       f'font-family="sans-serif">{deg}</text>')
    return out


def disc(radius, cx, cy):
    """The same dial round a circle, numbers inside, for the knob's end."""
    out = [f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="none" stroke="black" stroke-width="0.2"/>']
    for deg in range(360):
        a = math.radians(deg)
        tall = 3 if deg % 10 == 0 else 2 if deg % 5 == 0 else 1.2
        x1, y1 = cx + radius * math.sin(a), cy - radius * math.cos(a)
        x2, y2 = cx + (radius - tall) * math.sin(a), cy - (radius - tall) * math.cos(a)
        out.append(f'<line x1="{x1:.3f}" y1="{y1:.3f}" x2="{x2:.3f}" y2="{y2:.3f}" stroke="black" '
                   f'stroke-width="{0.12 if deg % 10 else 0.2}"/>')
        if deg % 30 == 0:
            tx, ty = cx + (radius - 5.5) * math.sin(a), cy - (radius - 5.5) * math.cos(a) + 0.9
            out.append(f'<text x="{tx:.3f}" y="{ty:.3f}" font-size="2.4" text-anchor="middle" '
                       f'font-family="sans-serif">{deg}</text>')
    out.append(f'<circle cx="{cx}" cy="{cy}" r="0.6" fill="black"/>')
    return out


def svg(diameter):
    """The page: a strip as long as the knob's rim, a disc as wide as its end,
    and a 50 mm bar to check the printer kept the size."""
    rim = math.pi * diameter
    width, height = max(rim + 20, 120), 40 + diameter + 30
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.1f}mm" height="{height:.1f}mm" '
             f'viewBox="0 0 {width:.1f} {height:.1f}">',
             '<rect width="100%" height="100%" fill="white"/>',
             f'<text x="10" y="7" font-size="3.2" font-family="sans-serif">Focus knob dial, {diameter:g} mm '
             f'knob ({rim:.1f} mm round). Print at 100%, then check the bar is 50 mm.</text>',
             '<line x1="10" y1="11" x2="60" y2="11" stroke="black" stroke-width="0.6"/>',
             '<text x="62" y="12.2" font-size="2.6" font-family="sans-serif">50 mm</text>',
             f'<rect x="10" y="16" width="{rim:.3f}" height="12" fill="none" stroke="black" stroke-width="0.15" '
             'stroke-dasharray="1,1"/>',
             '<text x="10" y="35" font-size="2.6" font-family="sans-serif">Strip: cut on the dashes, wrap round '
             'the rim, 0 meeting 360. Disc: for the end of the knob.</text>']
    parts += ticks(rim, 6, 10, 16)
    parts += disc(diameter / 2, 10 + diameter / 2, 40 + diameter / 2)
    parts.append("</svg>")
    return "\n".join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--diameter", type=float, default=40.0, help="the knob's diameter, mm")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(svg(args.diameter), encoding="utf-8")
    rim = math.pi * args.diameter
    print(f"saved {args.out}: {rim:.1f} mm round, {rim / 360:.2f} mm a degree")


if __name__ == "__main__":
    main()
