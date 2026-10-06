#!/usr/bin/env python3
"""Set the mount's azimuth by day, from a landmark it has seen before.

    ./landmark.py remember chimney     the telescope is on the landmark now: keep it
    ./landmark.py check chimney        turn back to it and show where it sits now
    ./landmark.py check chimney --watch 20     keep looking, while you turn the bolts
    ./landmark.py list
    ./landmark.py check chimney --dry-run

With the polar axis's height set once, the only thing that changes from one
setting-up to the next is which way the mount faces. A distant fixed thing (a
chimney, a mast, a street lamp) tells you: remember it once, with the
telescope's two axis readings, on a night when the star measurement says the
axis is right. Next time, by day, "check" turns the telescope to the same
readings and shows the view with a cross where the landmark was. Turn the
mount's azimuth bolts until the landmark sits on the cross.

It compares the telescope with itself, so it needs no map and no compass.
It does need the tripod back on its marks, the landmark a few hundred metres
away or more, and the home position set the same way each time: the axis
readings count from wherever the mount was when it was switched on. A miss
left to right is what the azimuth bolts put right. A miss up or down means
the home position was set a little differently.

"check" moves the mount. It is checked against the Sun and the meridian
limit first, and the motion lock is respected.
"""
import argparse
import json
import math
import re
import time

import numpy as np
from PIL import Image, ImageDraw

import config
import interface
import mount

FOLDER = config.DATA / "landmarks"
VIEW = config.DATA / "web" / "landmark.jpg"       # what the telescope sees now, marked up
SQUARE = 512        # side of the central square the two views are compared over
SURE = 12.0         # how far the best match must stand above the rest (in their spread) to be believed


def scale():
    """Degrees of sky per pixel of the half-size pictures used here."""
    cfg = config.hardware()
    return math.degrees(2 * cfg["camera"]["pixel_size_um"] / 1000 / cfg["scope"]["focal_length_mm"])


def name_ok(name):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,39}", name or ""):
        raise interface.Refusal("INVALID_REQUEST", "Give the landmark a short name of letters and digits, "
                                "such as chimney.")
    return name.strip().replace(" ", "-").lower()


def exposed(cam, start=0.002, longest=2.0):
    """A frame neither burnt out nor black, by day or by night: (brightness
    image at half size, exposure in seconds). Raw values follow the light, so
    one or two tries usually find it."""
    from camera import WHITE, luminance
    exposure = start
    for _ in range(8):
        mosaic, _ = cam.frame(exposure)
        level = float(np.percentile(mosaic[::8, ::8], 99)) / WHITE
        if 0.2 <= level <= 0.85 or (level < 0.2 and exposure >= longest) or (level > 0.85 and exposure <= 0.0001):
            break
        exposure = min(max(exposure * 0.5 / max(level, 0.01), 0.0001), longest)
    return luminance(mosaic), exposure, mosaic


def shift_between(before, now):
    """How far the view has moved between two pictures: (pixels right, pixels
    down, how sure). Found by sliding one over the other; `sure` is how far
    the best fit stands above the rest, and below SURE it is not to be
    believed (a different light, or nothing in common)."""
    def middle(image):
        h, w = image.shape
        cut = image[(h - SQUARE) // 2:(h + SQUARE) // 2, (w - SQUARE) // 2:(w + SQUARE) // 2].astype(np.float64)
        cut = cut - cut.mean()
        return cut * np.outer(np.hanning(SQUARE), np.hanning(SQUARE))
    a, b = np.fft.fft2(middle(before)), np.fft.fft2(middle(now))
    cross = b * np.conj(a)
    match = np.abs(np.fft.ifft2(cross / np.maximum(np.abs(cross), 1e-12)))
    y, x = np.unravel_index(np.argmax(match), match.shape)
    sure = float((match[y, x] - match.mean()) / (match.std() + 1e-12))
    dy = y - SQUARE if y > SQUARE // 2 else y
    dx = x - SQUARE if x > SQUARE // 2 else x
    return float(dx), float(dy), sure


def picture(lum, cross=None, note=""):
    """A view as a picture, with a cross where the landmark belongs."""
    lo, hi = np.percentile(lum[::4, ::4], (1, 99.7))
    grey = (255 * np.clip((lum - lo) / max(hi - lo, 1e-6), 0, 1) ** 0.6).astype(np.uint8)
    image = Image.fromarray(grey).convert("RGB")
    draw = ImageDraw.Draw(image)
    h, w = lum.shape
    x, y = cross if cross else (w / 2, h / 2)
    for dx, dy in ((1, 0), (0, 1)):
        draw.line([(x - 60 * dx - 0 * dy, y - 60 * dy), (x - 12 * dx, y - 12 * dy)], fill=(255, 190, 60), width=2)
        draw.line([(x + 12 * dx, y + 12 * dy), (x + 60 * dx, y + 60 * dy)], fill=(255, 190, 60), width=2)
    if note:
        draw.text((12, 10), note, fill=(255, 190, 60))
    return image


def place(name):
    return FOLDER / f"{name}.json"


def saved(name):
    path = place(name)
    if not path.exists():
        known = ", ".join(note["name"] for note in listed())
        raise interface.Refusal("INVALID_REQUEST", f"No landmark called {name} has been remembered"
                                + (f". Known: {known}." if known else " yet."))
    return json.loads(path.read_text(encoding="utf-8"))


def altaz(ra_axis, dec_axis, latitude):
    """The bearing and height a pair of axis readings aims at. For something
    on the ground this does not change with the time."""
    import polaralign
    if dec_axis <= 90:
        hour_angle, dec = ra_axis - 90, dec_axis
    else:
        hour_angle, dec = ra_axis + 90, 180 - dec_axis
    altitude, azimuth = polaralign.to_altaz(polaralign.vector(hour_angle, dec), latitude)
    return azimuth % 360, altitude


def remember(name, scope, site, cam_class=None):
    """Keep the view the telescope has now, and the axis readings it has it at."""
    from camera import Camera
    name = name_ok(name)
    scope.tracking(False)       # hold still on it: it is not a star
    ra_axis, dec_axis = scope.axes()
    with (cam_class or Camera)() as cam:
        lum, exposure, _ = exposed(cam)
    azimuth, altitude = altaz(ra_axis, dec_axis, site["latitude"])
    polar = scope.drift_model(site).polar
    FOLDER.mkdir(parents=True, exist_ok=True)
    np.save(FOLDER / f"{name}.npy", lum.astype(np.float32))
    picture(lum, note=f"{name}: remembered").save(FOLDER / f"{name}.jpg", quality=90)
    note = {"name": name, "ra_axis_deg": round(ra_axis, 4), "dec_axis_deg": round(dec_axis, 4),
            "bearing_deg": round(azimuth, 2), "height_deg": round(altitude, 2), "exposure_s": exposure,
            "remembered": time.time(),
            # What the star measurement last said about the axis, if it has
            # been made: a landmark is only as true as the alignment it was
            # remembered under.
            "polar_when_remembered": polar}
    place(name).write_text(json.dumps(note, indent=1), encoding="utf-8")
    print(f"Remembered {name}: bearing {azimuth:.1f}°, {altitude:.1f}° up "
          f"(axes: RA {ra_axis:.2f}°, Dec {dec_axis:.2f}°).")
    if not polar:
        print("The polar axis has not been measured against the stars yet, so this only records where "
              "the mount faces now. Remember it again after ./polaralign.py says the axis is right.")
    return note


def plan(name, site):
    """What turning back to a landmark would do, checked against the Sun, the
    meridian limit and the motion lock, without moving anything."""
    note = saved(name_ok(name))
    found = mount.plan_point(note["bearing_deg"], max(2.0, min(89.0, note["height_deg"])), site)
    return dict(found, landmark=note["name"], bearing_deg=note["bearing_deg"], height_deg=note["height_deg"],
                warnings=found.get("warnings", []) + ["The mount is turned to the axis readings it had "
                                                      "when the landmark was remembered, and held there."])


def look(name, scope, cam, note, before):
    """One view of the landmark as things stand, with where it has moved to."""
    lum, _, _ = exposed(cam, start=note["exposure_s"])
    dx, dy, sure = shift_between(before, lum)
    per_pixel, believed = scale(), sure >= SURE
    h, w = lum.shape
    off = math.hypot(dx, dy) * per_pixel
    words = (f"{off:.2f}° from where it was ({abs(dx) * per_pixel:.2f}° {'right' if dx > 0 else 'left'}, "
             f"{abs(dy) * per_pixel:.2f}° {'down' if dy > 0 else 'up'} in the picture)" if believed else
             "the two views could not be matched; compare them by eye")
    VIEW.parent.mkdir(parents=True, exist_ok=True)
    # The cross is where the landmark's remembered place has gone to in this
    # view; with no match it stays in the middle, where the landmark belongs.
    marked = picture(lum, note=f"{name}: {words}")
    marked.save(VIEW.with_suffix(".part.jpg"), quality=88)
    VIEW.with_suffix(".part.jpg").replace(VIEW)
    print(f"  {words}", flush=True)
    return {"right_px": round(dx, 1), "down_px": round(dy, 1), "off_deg": round(off, 3) if believed else None,
            "right_deg": round(dx * per_pixel, 3) if believed else None,
            "down_deg": round(dy * per_pixel, 3) if believed else None, "matched": believed}


def check(name, scope, site, watch=0, cam_class=None, pause=3.0):
    """Turn back to a landmark and say where it sits now. With `watch`, keep
    looking that many times, for turning the azimuth bolts by."""
    from camera import Camera
    name = name_ok(name)
    note = saved(name)
    plan(name, site)                       # refuses here, before anything moves
    before = np.load(FOLDER / f"{name}.npy")
    print(f"Turning to {name}: bearing {note['bearing_deg']:.1f}°, {note['height_deg']:.1f}° up.", flush=True)
    scope.tracking(False)
    scope.dec_creep(0)
    with scope.watching():
        # By the axis readouts, as home is found: Dec first, then RA.
        scope.seek(mount.DEC, note["dec_axis_deg"])
        scope.seek(mount.RA, note["ra_axis_deg"])
    scope.tracking(False)
    seen = []
    with (cam_class or Camera)() as cam:
        for i in range(max(1, watch)):
            seen.append(look(name, scope, cam, note, before))
            if i + 1 < max(1, watch):
                time.sleep(pause)
    last = seen[-1]
    if last["matched"]:
        print(f"Turn the azimuth bolts until the landmark is back on the cross: it is {abs(last['right_deg']):.2f}° "
              f"to the {'right' if last['right_deg'] > 0 else 'left'} of it. "
              + (f"It is also {abs(last['down_deg']):.2f}° {'low' if last['down_deg'] > 0 else 'high'}, which the "
                 "azimuth bolts will not change: the home position was set a little differently."
                 if abs(last["down_deg"]) > 0.1 else ""))
    else:
        print("Compare the remembered picture with this one by eye, and turn the azimuth bolts until the "
              "landmark is in the same place.")
    # Kept so that ./polaris.py knows the mount faces the right way and can
    # look over a small patch only.
    (FOLDER / "last check.json").write_text(json.dumps(dict(last, name=name, checked=time.time())), encoding="utf-8")
    return dict(last, landmark=name, looks=len(seen), picture=str(VIEW))


def listed():
    if not FOLDER.exists():
        return []
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(FOLDER.glob("*.json")) if p.name != "last check.json"]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["remember", "check", "list"])
    ap.add_argument("name", nargs="?", default="landmark")
    ap.add_argument("--watch", type=int, default=0, metavar="N",
                    help="with check: look N times a few seconds apart, for adjusting by")
    ap.add_argument("--dry-run", action="store_true", help="say what it would do; no camera, no mount")
    ap.add_argument("--json", action="store_true", help="answer in JSON at the end")
    args = ap.parse_args()
    kind = f"landmark.{args.command}" + (".dry_run" if args.dry_run else "")
    return interface.main(kind, lambda: run(args), args.json)


def run(args):
    if args.command == "list":
        found = listed()
        for note in found:
            print(f"{note['name']}: bearing {note['bearing_deg']:.1f}°, {note['height_deg']:.1f}° up, remembered "
                  f"{time.strftime('%d %b %H:%M', time.localtime(note['remembered']))}")
        if not found:
            print("No landmarks remembered yet.")
        return {"landmarks": found}
    if args.command == "remember":
        if args.dry_run:
            print("Would not move the mount: takes a picture where the telescope is and keeps it.")
            return {"would_move": False, "safe": True}
        return remember(args.name, mount.Mount(watch=False), config.load()["site"])
    # The lock comes first: before the settings are read or the mount opened.
    if mount.LOCK_FILE.exists():
        raise interface.Refusal("MOTION_LOCKED",
                                f"Motion is locked: {mount.LOCK_FILE.read_text(encoding='utf-8').strip()}")
    site = config.load()["site"]
    if args.dry_run:
        found = plan(args.name, site)
        print(f"Would turn to {found['landmark']}: bearing {found['bearing_deg']:.1f}°, "
              f"{found['height_deg']:.1f}° up, on the {found['pier_side']} side.")
        return found, found["warnings"]
    scope = mount.Mount()
    try:
        return check(args.name, scope, site, watch=args.watch)
    except BaseException:
        scope.stop()     # never leave a motor running after an error or Ctrl+C
        raise


if __name__ == "__main__":
    main()
