#!/usr/bin/env python3
"""Watch for stars: photograph the sky through the telescope every minute and
stop as soon as stars show, or at a set time.

    ./skywatch.py --until 22:00
    ./skywatch.py --until 02:00 --guide-check --flash "Living room"

With --guide-check a clearing counts only when the guide camera finds its
star too (9 November 2026: thin cloud gave the main camera 10-28 stars
while the guide camera saw none). With --flash ROOM, a clearing pulses
that Hue room's lights only (alert.py flash).

Each frame goes to the web page. Exits with a message saying whether the sky
cleared, so whatever started it knows when to carry on.
"""
import argparse
import sys
import time
from datetime import datetime, timedelta

import numpy as np
from scipy import ndimage

import activity
from camera import Camera, luminance
from snap import publish, save

ENOUGH_STARS = 8  # in two frames running; a plate solve needs about this many
# Said with every clearing, for whoever (or whatever agent) started the watch
# (4 November 2026: a gap came and the polar check waited for "go").
GO_NOW = ("Gaps in the cloud can be small. In live observation (anything past setting "
          "the handset) start the next step now: do not wait for the person to say go.")


def star_places(lum):
    """Where the star-like spots standing clear of the sky background are:
    an array of (row, column), one line per star."""
    lum = ndimage.median_filter(lum, 3)  # drop hot pixels
    flat = lum - ndimage.uniform_filter(lum, 64)  # drop the sky gradient
    noise = 1.4826 * float(np.median(np.abs(flat - np.median(flat))))
    spots, count = ndimage.label(flat > 6 * max(noise, 1.0))
    if not count:
        return np.zeros((0, 2))
    sizes = ndimage.sum(np.ones_like(spots), spots, range(1, count + 1))
    # Stars cover a few pixels; anything huge is cloud edge or glare.
    stars = np.flatnonzero((sizes >= 3) & (sizes < 5000)) + 1
    return np.array(ndimage.center_of_mass(flat, spots, stars)).reshape(-1, 2)


def count_stars(lum):
    """Number of star-like spots standing clear of the sky background."""
    return len(star_places(lum))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--until", default="22:00", help="give up at this time (HH:MM)")
    ap.add_argument("--every", type=float, default=60, help="seconds between frames")
    ap.add_argument("--exposure", type=float, default=2.0)
    ap.add_argument("--guide-check", action="store_true",
                    help="count a clearing only when the guide camera finds a star too")
    ap.add_argument("--flash", metavar="ROOM", help="on a clearing, pulse this Hue room's lights")
    args = ap.parse_args()
    # Exit 1 when the deadline passes with no stars, so `skywatch && alert`
    # summons nobody for cloud (9 November 2026: it flashed at once).
    clear = watch(args.until, args.every, args.exposure, args.guide_check)
    if clear and args.flash:
        import alert
        alert.flash(args.flash)
    sys.exit(0 if clear else 1)


@activity.during("Watching for stars", "a {exposure:g} s frame every {every:g} s until {until}")
def guide_sees_star(seconds=2.0, gain=400):
    """Whether the guide camera finds a guide star now (guider.find_star),
    and why not."""
    import guider
    from guidecam import GUIDE_SIZE, GUIDE_SPEED, GuideCamera
    with GuideCamera(role="skywatch", size=GUIDE_SIZE, speed=GUIDE_SPEED) as cam:
        for _ in range(2):
            star, why = guider.find_star(cam.frame(seconds, gain))
            if star is not None:
                return True, f"SNR {star.snr:.0f}"
    return False, why


def watch(until, every, exposure, guide_check=False):
    """Frames until stars show or `until` comes, with "Watching for stars"
    on the status page meanwhile."""
    hour, minute = (int(x) for x in until.split(":"))
    end = datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
    if end <= datetime.now():
        end += timedelta(days=1)   # 02:00 asked at 20:55 is tonight's, not this morning's
    streak = 0
    looked = None    # when the cloud data was last printed
    stars = None
    with Camera() as cam:
        while datetime.now() < end:
            started = time.monotonic()
            mosaic, header = cam.frame(exposure)
            stars = count_stars(luminance(mosaic))
            publish(mosaic, kind="sky check", detail=f"{exposure:g} s")
            print(f"{datetime.now():%H:%M:%S}  {stars} stars, sky level "
                  f"{np.median(mosaic):.0f}", flush=True)
            streak = streak + 1 if stars >= ENOUGH_STARS else 0
            if stars < ENOUGH_STARS and (looked is None or time.monotonic() - looked > 1800):
                cloud_data(stars)
                looked = time.monotonic()
            if streak >= 2 and guide_check:
                seen, why = guide_sees_star()
                print(f"{datetime.now():%H:%M:%S}  guide camera: "
                      + ("star found, " + why if seen else f"no star ({why}): thin cloud, or the guide "
                         "camera's focus or exposure; watching on"), flush=True)
                if not seen:
                    cloud_data(stars, guide="no star")
                    streak = 0
            if streak >= 2:
                print(f"STARS VISIBLE: frame saved as {save(mosaic, header)}", flush=True)
                print(GO_NOW, flush=True)
                return True
            time.sleep(max(0, every - (time.monotonic() - started)))
    print("No clear sky before the deadline.", flush=True)
    cloud_data(stars)
    return False


def cloud_data(stars=None, guide=None):
    """The satellite and the airports, printed when the camera sees no stars
    (at the first such frame, every half hour after, and at the deadline):
    10 November 2026, the cloud data is the first thing to look at."""
    try:
        import clouds
        context = {"skywatch_stars": stars, **({"guide": guide} if guide else {})}
        print(f"{datetime.now():%H:%M:%S}  {clouds.evidence_words(clouds.evidence(context=context))}", flush=True)
    except Exception as problem:     # noqa: BLE001 - the watch goes on without it
        print(f"{datetime.now():%H:%M:%S}  no cloud data: {problem}", flush=True)


if __name__ == "__main__":
    main()
