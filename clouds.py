#!/usr/bin/env python3
"""Live cloud picture from the Meteosat weather satellite.

    ./clouds.py        fetch the newest infrared image, mark the site on it,
                       save it for the web page and print how cloudy it looks
    ./clouds.py --at 2026-11-05T04:30   the picture at that time (UT), saved
                       beside it as clouds-YYYYMMDD-HHMM.jpg: was it cloud?

Source: EUMETSAT's public image service (view.eumetsat.int), 10.5 µm
infrared, a new image every 10 minutes. Infrared works at night: clouds are
cold and show bright, clear ground and sea are warm and show dark.
"""
import io
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw

import config

ROOT = Path(__file__).parent
PICTURE = config.DATA / "web" / "clouds.jpg"
WMS = "https://view.eumetsat.int/geoserver/wms"
WIDTH, HEIGHT = 1110, 510
# Degrees of latitude and longitude shown either side of the site.
SPAN_LAT, SPAN_LON = 1.7, 3.7


def _layer(name, box, transparent=False, when=None):
    extra = {"time": when.strftime("%Y-%m-%dT%H:%M:00Z")} if when else {}
    r = requests.get(WMS, timeout=60, params={**extra,
        "service": "WMS", "version": "1.3.0", "request": "GetMap", "layers": name,
        "styles": "", "crs": "EPSG:4326", "bbox": ",".join(f"{v:.3f}" for v in box),
        "width": WIDTH, "height": HEIGHT, "format": "image/png",
        "transparent": str(transparent).lower()})
    r.raise_for_status()
    try:
        return Image.open(io.BytesIO(r.content))
    except OSError as error:
        # The service sometimes answers with an error page instead of a
        # picture (2 November 2026): said plainly, not as a traceback.
        raise RuntimeError(f"the satellite service sent no picture of {name} just now "
                           f"({r.headers.get('content-type', 'unknown')})") from error


def coastline(box):
    """Yellow coastline overlay for the map; fetched once and kept, since the
    service that draws it fails now and then. None if it has never worked."""
    kept = config.DATA / "cache" / "coastline_{:.2f}_{:.2f}.png".format(*box[:2])
    if not kept.exists():
        try:
            lines = np.array(_layer("backgrounds:ne_10m_coastline", box, True).convert("RGBA"))
        except requests.RequestException:
            return None
        lines[lines[..., 3] > 0] = (255, 220, 0, 255)
        kept.parent.mkdir(exist_ok=True)
        Image.fromarray(lines).save(kept)
    return Image.open(kept)


def update(site, when=None):
    """Fetch, annotate and save the image. Returns (brightness over the site,
    brightness of the darkest tenth of the map), both 0-255; the second is a
    stand-in for clear sky. `when` (UTC) is a past picture, saved under its
    own name so the page's live one is left alone: 5 November 2026, dimmed
    stars were put down to dew without a look at the satellite."""
    lat, lon = site["latitude"], site["longitude"]
    box = (lat - SPAN_LAT, lon - SPAN_LON, lat + SPAN_LAT, lon + SPAN_LON)
    infrared = _layer("mtg_fd:ir105_hrfi", box, when=when).convert("RGB")
    levels = np.asarray(infrared.convert("L"), dtype=float)
    x, y = WIDTH // 2, HEIGHT // 2
    here = float(levels[y - 4:y + 5, x - 4:x + 5].mean())
    clear = float(np.percentile(levels, 10))

    coast = coastline(box)
    if coast:
        infrared.paste(coast, (0, 0), coast)
    draw = ImageDraw.Draw(infrared)
    # A circle for where the telescope is, and no name: the picture is on the
    # page, and the place is nobody else's business (20 October 2026).
    draw.ellipse([x - 7, y - 7, x + 7, y + 7], outline=(255, 40, 40), width=3)
    # Stretch vertically so distances look right at this latitude.
    true_height = round(WIDTH * SPAN_LAT / (SPAN_LON * np.cos(np.radians(lat))))
    out = PICTURE.with_name(f"clouds-{when:%Y%m%d-%H%M}.jpg") if when else PICTURE
    out.parent.mkdir(exist_ok=True)
    infrared.resize((WIDTH, true_height)).save(out, quality=88)
    return here, clear, out


if __name__ == "__main__":
    import argparse
    import datetime as dt
    ap = argparse.ArgumentParser(description="Live (or past) cloud picture from Meteosat.")
    ap.add_argument("--at", metavar="YYYY-MM-DDTHH:MM", help="a past time, UT")
    args = ap.parse_args()
    when = dt.datetime.fromisoformat(args.at).replace(tzinfo=dt.timezone.utc) if args.at else None
    try:
        here, clear, saved = update(config.load()["site"], when)
    except (RuntimeError, requests.RequestException) as problem:
        raise SystemExit(f"No satellite picture: {problem}. Try again in a few minutes.")
    verdict = "cloud" if here - clear > 20 else "probably clear" if here - clear < 10 else "thin or broken cloud"
    print(f"over the site: {here:.0f}, clear areas: {clear:.0f} -> {verdict}")
    print(f"saved {saved}")
