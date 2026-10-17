#!/usr/bin/env python3
"""Cover an object bigger than the frame with several panels.

    ./mosaic.py M31 3x1          plan three panels along the camera's long side, and keep it
    ./mosaic.py NGC7000          suggest a grid from the object's size; keep it
    ./mosaic.py M31              show the kept plan
    ./mosaic.py M31 3x2 --replace

The panels are laid out along the camera's own sides, turned as the last
plate solve found the camera (or by --angle), so neighbouring panels overlap
by the same strip all the way along. Each panel's centre is worked out once
and kept in mosaics/name.json, so a panel shot on another night lands in the
same place even if the camera has been turned since.

A panel is then a target like any other:

    ./mount.py goto M31-P1 --dry-run
    ./shoot.py M31-P1 --frames 600

and its frames are kept under frames/M31-P1/. Stitching the panels into one
picture is not done here; restack each panel, then join them in Siril or
PixInsight.
"""
import argparse
import json
import math
import re
import sys

import config
import records

OVERLAP = 0.15          # of the frame's width and height, shared with the next panel
PANEL = re.compile(r"^(.+?)-?p(\d+)$")


def folder():
    return config.DATA / "mosaics"


def path(name):
    import stacking
    # Lower case, so "m31-p2" finds the plan kept for M31.
    return folder() / f"{stacking.folder_name(name).lower()}.json"


def field(cfg=None):
    """(width, height) of the camera's view in degrees."""
    cfg = cfg or config.hardware()
    height = config.field_height(cfg)
    return height * cfg["camera"]["width"] / cfg["camera"]["height"], height


def camera_axes(angle=None):
    """Unit vectors on the sky (east, north) along the frame's width and
    height. From --angle (degrees from east towards north) if given, else
    from the last plate solve's CD matrix, else the camera square to RA."""
    if angle is None:
        import mount
        if mount.LAST_SOLVE.exists():
            cd = json.loads(mount.LAST_SOLVE.read_text(encoding="utf-8")).get("cd")
            if cd:
                across = (cd[0][0], cd[1][0])
                up = (cd[0][1], cd[1][1])
                return _unit(across), _unit(up), "the last plate solve"
        angle, source = 0.0, "no plate solve yet, so square to RA and Dec"
    else:
        source = "--angle"
    a = math.radians(angle)
    return (math.cos(a), math.sin(a)), (-math.sin(a), math.cos(a)), source


def _unit(v):
    size = math.hypot(*v)
    return v[0] / size, v[1] / size


def suggest(target, width, height, overlap=OVERLAP):
    """The smallest grid (columns along the frame's width, rows along its
    height) that covers the object's catalogue size and minor axis."""
    major = (target.get("size") or 0) / 60
    minor = (target.get("minor") or target.get("size") or 0) / 60
    step_w, step_h = width * (1 - overlap), height * (1 - overlap)

    def count(span, frame, step):
        return max(1, math.ceil((span - frame) / step - 1e-9) + 1) if span > frame else 1
    # Lay the long axis along whichever side needs fewer panels in all.
    one = (count(major, width, step_w), count(minor, height, step_h))
    other = (count(minor, width, step_w), count(major, height, step_h))
    return min(one, other, key=lambda g: (g[0] * g[1], -g[0]))


def offset(ra, dec, east, north):
    """The sky position `east` and `north` degrees from (ra, dec) on the
    tangent plane there, in degrees."""
    xi, eta = math.radians(east), math.radians(north)
    ra0, dec0 = math.radians(ra), math.radians(dec)
    denominator = math.cos(dec0) - eta * math.sin(dec0)
    new_ra = ra0 + math.atan2(xi, denominator)
    new_dec = math.atan2(math.sin(dec0) + eta * math.cos(dec0), math.hypot(xi, denominator))
    return math.degrees(new_ra) % 360, math.degrees(new_dec)


def plan(target, columns, rows, overlap=OVERLAP, angle=None, cfg=None):
    """The panels' centres, numbered across then down from the top left of the frame."""
    width, height = field(cfg)
    across, up, source = camera_axes(angle)
    step_w, step_h = width * (1 - overlap), height * (1 - overlap)
    panels = []
    for row in range(rows):
        for column in range(columns):
            a = (column - (columns - 1) / 2) * step_w
            b = ((rows - 1) / 2 - row) * step_h
            ra, dec = offset(target["ra"], target["dec"],
                             a * across[0] + b * up[0], a * across[1] + b * up[1])
            panels.append({"id": f"{target['id'].replace(' ', '')}-P{len(panels) + 1}",
                           "ra": round(ra, 5), "dec": round(dec, 5), "column": column + 1, "row": row + 1})
    return {"target": target["id"], "name": target.get("name", ""), "columns": columns, "rows": rows,
            "overlap": overlap, "field_deg": [round(width, 3), round(height, 3)],
            "covers_deg": [round(width + (columns - 1) * step_w, 2), round(height + (rows - 1) * step_h, 2)],
            "angle_deg": round(math.degrees(math.atan2(across[1], across[0])), 1),
            "angle_from": source, "panels": panels}


def load(name):
    p = path(name)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def find_panel(name):
    """The catalogue entry for a panel name such as 'M31-P2' or 'NGC 7000 P3',
    or None if the name is not one of a kept mosaic's panels."""
    match = PANEL.match(name.replace(" ", "").lower())
    if not match:
        return None
    kept = load(match.group(1))
    if not kept:
        return None
    number = int(match.group(2))
    if not 1 <= number <= len(kept["panels"]):
        return None
    panel = kept["panels"][number - 1]
    return {"id": panel["id"], "alt_id": "", "name": f"{kept['name'] or kept['target']} panel {number}",
            "kind": "panel", "const": "", "ra": panel["ra"], "dec": panel["dec"],
            "mag": None, "size": None, "minor": None, "messier": False}


def describe(kept):
    width, height = kept["field_deg"]
    lines = [f"{kept['target']} {kept['name']}: {kept['columns']} x {kept['rows']} panels of "
             f"{width:.2f}° x {height:.2f}°, {kept['overlap']:.0%} overlap, covering "
             f"{kept['covers_deg'][0]:.2f}° x {kept['covers_deg'][1]:.2f}°",
             f"Camera turned {kept['angle_deg']:+.0f}° from east towards north ({kept['angle_from']}).",
             ""]
    for p in kept["panels"]:
        lines.append(f"  {p['id']:<12} RA {p['ra'] / 15:6.3f} h  Dec {p['dec']:+7.3f}°   "
                     f"column {p['column']}, row {p['row']}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("target", help="catalogue object, e.g. M31 or NGC7000")
    ap.add_argument("grid", nargs="?", help="columns x rows, e.g. 3x1 (default: from the object's size)")
    ap.add_argument("--overlap", type=float, default=OVERLAP, help="share of each frame overlapping the next")
    ap.add_argument("--angle", type=float,
                    help="the camera's turn on the sky in degrees, east towards north (default: last plate solve)")
    ap.add_argument("--replace", action="store_true", help="replace a kept plan with a different grid")
    ap.add_argument("--demo", action="store_true", help="the example camera and telescope; keeps nothing")
    args = ap.parse_args()

    import mount
    target = mount.find_target(args.target)
    kept = load(target["id"])
    cfg = config.example() if args.demo else None
    if args.grid:
        found = re.fullmatch(r"(\d+)\s*[xX×]\s*(\d+)", args.grid)
        if not found or not all(1 <= int(n) <= 6 for n in found.groups()):
            ap.error("the grid is columns x rows, each 1 to 6, e.g. 3x1")
        columns, rows = int(found.group(1)), int(found.group(2))
    elif kept and not args.demo:
        print(describe(kept))
        return 0
    else:
        columns, rows = suggest(target, *field(cfg), args.overlap)
    fresh = plan(target, columns, rows, args.overlap, args.angle, cfg)
    if args.demo:
        print(describe(fresh))
        return 0
    if kept and not args.replace and (kept["columns"], kept["rows"]) != (columns, rows):
        print(describe(kept))
        print(f"\nA {kept['columns']} x {kept['rows']} plan is already kept; --replace to change it "
              "(frames already taken stay where they were).", file=sys.stderr)
        return 1
    if kept and not args.replace:
        print(describe(kept))
        return 0
    folder().mkdir(parents=True, exist_ok=True)
    records.write(path(target["id"]), fresh)
    print(describe(fresh))
    print(f"\nKept in {path(target['id'])}. Aim at a panel with ./mount.py goto {fresh['panels'][0]['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
