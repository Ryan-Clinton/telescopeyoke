"""Made-up data so the planner and web page can be tried with no telescope,
no network and no config.toml:

    ./tonight.py --demo
    ./serve.py --demo

It stands in for feeds.py: a clear evening that clouds over after 1 a.m.,
average seeing, and a suburban sky. Positions of the Sun, Moon, planets and
targets are still computed for tonight, at the example site.
"""
import shutil
from pathlib import Path

ROOT = Path(__file__).parent
SAMPLE_FRAME = ROOT / "docs" / "m27-result.jpg"

SEEING = {}        # same lookups as feeds, filled below
TRANSPARENCY = {}
NATURAL_SKY = 22.0


def _cloud(hour):
    """Percent cloud by local hour: clear from dusk, clouding over after 1."""
    if 19 <= hour or hour < 1:
        return 8
    return 35 if hour < 2 else 85 if hour < 8 else 40


def weather(lat, lon):
    """Hourly forecast in the shape feeds.weather() returns, covering
    yesterday to three days ahead."""
    import time
    start = int(time.time() // 3600 * 3600) - 24 * 3600
    times = [start + i * 3600 for i in range(96)]
    hours = [time.localtime(t).tm_hour for t in times]
    cloud = [_cloud(h) for h in hours]
    return {
        "time": times,
        "cloud_cover": cloud,
        "cloud_cover_low": [c // 4 for c in cloud],
        "cloud_cover_mid": [c // 2 for c in cloud],
        "cloud_cover_high": cloud,
        "precipitation": [0.0] * 96,
        "precipitation_probability": [0 if c < 50 else 10 for c in cloud],
        "temperature_2m": [9.0 if 19 <= h or h < 7 else 14.0 for h in hours],
        "dew_point_2m": [5.5] * 96,
        "relative_humidity_2m": [80] * 96,
        "wind_speed_10m": [8.0] * 96,
        "wind_gusts_10m": [16.0] * 96,
    }


def seeing(lat, lon):
    import time
    start = int(time.time() // 10800 * 10800) - 24 * 3600
    return [{"time": start + i * 10800, "seeing": 4, "transparency": 3} for i in range(32)]


def light_pollution(lat, lon):
    return {"ratio": 2.8, "sqm": 20.55, "zone": "4b", "bortle": 4, "source": "demo"}


def comets(lat, lon, elevation_m, start, stop):
    return []


def bortle(sqm):
    import feeds
    return feeds.bortle(sqm)


def install_sample_frame(web):
    """Put a real picture taken with this software where the page expects the
    latest camera frame, unless the camera has already put one there."""
    web.mkdir(exist_ok=True)
    if SAMPLE_FRAME.exists() and not (web / "latest.jpg").exists():
        shutil.copy(SAMPLE_FRAME, web / "latest.jpg")


def _fill_lookups():
    import feeds
    SEEING.update(feeds.SEEING)
    TRANSPARENCY.update(feeds.TRANSPARENCY)


_fill_lookups()
