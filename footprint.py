"""Where a field's pictures fall on the sky: the camera's rectangle, not a circle.

A footprint is the frame's centre, its width and height in degrees, and the
directions on the sky (east, north) of its width and height. It comes, best
first, from:

  - a plate solve kept with the field's reference (depth.py keeps the
    solve of every stack it measures; ./reference.py NAME --locate adds
    one to a reference made before it did),
  - a kept mosaic plan, for each of its panels (mosaics/NAME.json), or
    the plan mosaic.py would make for the programme's grid,
  - the catalogue's centre with the camera's frame turned as at the last
    plate solve (mosaic.camera_axes), said as "nominal".

`contains` says whether a place lies inside the frame. Used by ty night to
tell which galaxies a programme's pictures already hold (M110 lies in M31's
mosaic) and which reference field a galaxy belongs to (M81 in M81-M82).
"""
import json
import math


def tangent(ra0, dec0, ra, dec):
    """(east, north) in degrees of (ra, dec) on the tangent plane at (ra0, dec0)."""
    a0, d0, a, d = map(math.radians, (ra0, dec0, ra, dec))
    cos_c = math.sin(d0) * math.sin(d) + math.cos(d0) * math.cos(d) * math.cos(a - a0)
    if cos_c <= 0:
        return None                          # the far side of the sky
    xi = math.cos(d) * math.sin(a - a0) / cos_c
    eta = (math.cos(d0) * math.sin(d) - math.sin(d0) * math.cos(d) * math.cos(a - a0)) / cos_c
    return math.degrees(xi), math.degrees(eta)


def make(ra, dec, width, height, across, up, source):
    return {"ra": ra, "dec": dec, "width_deg": width, "height_deg": height,
            "across": list(across), "up": list(up), "source": source}


def contains(fp, ra, dec, margin=0.0):
    """Whether (ra, dec) lies inside the frame, or within `margin` degrees of it."""
    at = tangent(fp["ra"], fp["dec"], ra, dec)
    if at is None:
        return False
    x, y = at
    a = x * fp["across"][0] + y * fp["across"][1]
    b = x * fp["up"][0] + y * fp["up"][1]
    return abs(a) <= fp["width_deg"] / 2 + margin and abs(b) <= fp["height_deg"] / 2 + margin


def from_solve(solve, source="plate solve"):
    """A footprint from a kept solve: {ra, dec, cd, width_px, height_px}."""
    cd = solve["cd"]
    across, up = (cd[0][0], cd[1][0]), (cd[0][1], cd[1][1])
    step_x, step_y = math.hypot(*across), math.hypot(*up)
    return make(solve["ra"], solve["dec"], step_x * solve["width_px"], step_y * solve["height_px"],
                (across[0] / step_x, across[1] / step_x), (up[0] / step_y, up[1] / step_y), source)


def nominal(ra, dec, cfg=None):
    """The camera's frame centred on (ra, dec), turned as at the last plate solve."""
    import mosaic
    width, height = mosaic.field(cfg)
    across, up, _ = mosaic.camera_axes()
    return make(ra, dec, width, height, across, up, "nominal")


def of_plan(plan):
    """One footprint per panel of a kept mosaic plan."""
    width, height = plan["field_deg"]
    a = math.radians(plan.get("angle_deg", 0.0))
    across, up = (math.cos(a), math.sin(a)), (-math.sin(a), math.cos(a))
    return [make(p["ra"], p["dec"], width, height, across, up, f"mosaic plan {p['id']}")
            for p in plan["panels"]]


def of_reference(name):
    """The newest kept reference's footprint from its plate solve, or None
    if the field has no reference or its solve was never kept."""
    import depth
    import reference
    path = reference.newest(name)
    if path is None or not path.is_file():
        return None
    record = depth.record_path(path)
    if not record.is_file():
        return None
    solve = json.loads(record.read_text(encoding="utf-8")).get("footprint")
    return from_solve(solve, f"plate solve of {name}'s reference") if solve else None


def of_field(name, cfg=None):
    """[the footprint] of one frame's field (an object, or a mosaic panel
    such as M31-P3): its reference's solve, else nominal at the catalogue's
    centre. [] if nothing places it."""
    import mount
    kept = of_reference(name)
    if kept:
        return [kept]
    try:
        found = mount.find_target(name)
    except Exception:
        return []
    return [nominal(found["ra"], found["dec"], cfg)]


def of_mosaic(name, grid, cfg=None):
    """Every panel's footprint of a mosaic: the kept plan's, else the plan
    mosaic.py would make for this grid ("4x2")."""
    import mosaic
    import mount
    plan = mosaic.load(name)
    if not plan:
        try:
            target = mount.find_target(name)
        except Exception:
            return []
        columns, rows = (int(v) for v in grid.lower().split("x"))
        plan = mosaic.plan(target, columns, rows, cfg=cfg)
    return of_plan(plan)
