"""Local astronomy for tonight.py: where things are, how dark it is, and how
well each target suits the night. Nothing here needs the network."""
import csv
import math
import warnings
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from astropy import units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord, get_body
from astropy.time import Time
from astropy.utils import iers

# Stay offline: the bundled Earth-rotation tables are accurate enough.
iers.conf.auto_download = False
iers.conf.auto_max_age = None
warnings.filterwarnings("ignore", module="astropy")
warnings.filterwarnings("ignore", module="erfa")

STEP_MIN = 10
CATALOGUE = Path(__file__).parent / "data" / "targets.csv"

# Extinction near sea level, magnitudes per air mass.
EXTINCTION = 0.25

# Kinds whose visibility depends on contrast with the sky background, and how
# strongly (1 = fully, 0.5 = half the object is stars).
DIFFUSE = {"galaxy": 1.0, "nebula": 1.0, "dark nebula": 1.0,
           "planetary nebula": 1.0, "cluster+nebula": 0.5, "comet": 1.0}
# Surface brightness assumed when the catalogue lacks a magnitude or size.
DEFAULT_SURFACE_BRIGHTNESS = 22.0

# Solar-system targets: how rewarding each is in a small scope (0-1) and the
# lowest altitude worth trying. They are bright enough for twilight.
BODIES = {
    "moon": ("Moon", 1.0), "jupiter": ("Jupiter", 1.0), "saturn": ("Saturn", 1.0),
    "mars": ("Mars", 0.8), "venus": ("Venus", 0.7), "mercury": ("Mercury", 0.5),
    "uranus": ("Uranus", 0.45), "neptune": ("Neptune", 0.35),
}
BODY_MIN_ALT = 10
BODY_SUN_LIMIT = -6

COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def compass(az):
    return COMPASS[int((az + 11.25) % 360 // 22.5)]


def load_targets():
    def number(text):
        return float(text) if text else None

    with CATALOGUE.open() as f:
        return [
            {"id": r["id"], "alt_id": r["alt_id"], "name": r["name"],
             "kind": r["kind"], "const": r["const"],
             "ra": float(r["ra_deg"]), "dec": float(r["dec_deg"]),
             "mag": number(r["mag"]), "size": number(r["size_arcmin"]),
             "minor": number(r["minor_arcmin"]), "messier": bool(r["messier"])}
            for r in csv.DictReader(f)
        ]


def separation(ra1, dec1, ra2, dec2):
    """Angular separation in degrees between two sky positions in degrees."""
    ra1, dec1, ra2, dec2 = (np.radians(x) for x in (ra1, dec1, ra2, dec2))
    cos_sep = (np.sin(dec1) * np.sin(dec2)
               + np.cos(dec1) * np.cos(dec2) * np.cos(ra1 - ra2))
    return np.degrees(np.arccos(np.clip(cos_sep, -1, 1)))


def air_mass(alt):
    zenith = np.radians(90 - np.asarray(alt, dtype=float))
    return (1 - 0.96 * np.sin(zenith) ** 2) ** -0.5


# Sky brightness conversions between V mag/arcsec² and nanoLamberts.
def _to_nl(mag):
    return 34.08 * np.exp(20.7233 - 0.92104 * mag)


def _to_mag(nl):
    return (20.7233 - np.log(nl / 34.08)) / 0.92104


def moonlight(phase_angle, moon_alt, target_alt, sep):
    """Sky brightness added by the Moon at a target, in nanoLamberts.

    Krisciunas & Schaefer (1991), "A model of the brightness of moonlight".
    phase_angle is 0 at full Moon; all angles in degrees.
    """
    if moon_alt <= 0:
        return 0.0
    a = abs(phase_angle)
    illuminance = 10 ** (-0.4 * (3.84 + 0.026 * a + 4e-9 * a ** 4))
    scatter = (10 ** 5.36 * (1.06 + math.cos(math.radians(sep)) ** 2)
               + 10 ** (6.15 - sep / 40))
    return float(scatter * illuminance
                 * 10 ** (-0.4 * EXTINCTION * air_mass(moon_alt))
                 * (1 - 10 ** (-0.4 * EXTINCTION * air_mass(target_alt))))


class Night:
    """One night at one site, sampled every STEP_MIN minutes from local noon
    to the following noon."""

    def __init__(self, cfg, date=None, now=None):
        site = cfg["site"]
        self.tz = ZoneInfo(site["timezone"])
        self.location = EarthLocation(
            lat=site["latitude"] * u.deg, lon=site["longitude"] * u.deg,
            height=site.get("elevation_m", 0) * u.m)
        self.min_alt = cfg["horizon"]["min_altitude"]
        self.blocked = cfg["horizon"].get("blocked", [])
        self.sqm = site.get("sqm", 21.0)

        now = now or datetime.now(timezone.utc)
        if date is None:
            local = now.astimezone(self.tz)
            date = local.date()
            # After midnight the night in progress started yesterday.
            if local.hour < 12 and self._sun_alt_at(now) < BODY_SUN_LIMIT:
                date = date.fromordinal(date.toordinal() - 1)
        self.date = date

        start = datetime.combine(date, time(12), tzinfo=self.tz)
        n = 24 * 60 // STEP_MIN + 1
        self.times = Time(start) + np.arange(n) * STEP_MIN * u.min
        self.unix = self.times.unix
        self.frame = AltAz(obstime=self.times, location=self.location)
        self.future = self.unix >= now.timestamp()

        sun = get_body("sun", self.times, self.location)
        moon = get_body("moon", self.times, self.location)
        self.sun_alt = sun.transform_to(self.frame).alt.deg
        moon_altaz = moon.transform_to(self.frame)
        self.moon_alt, self.moon_az = moon_altaz.alt.deg, moon_altaz.az.deg
        self.moon_ra, self.moon_dec = moon.ra.deg, moon.dec.deg
        elongation = separation(sun.ra.deg, sun.dec.deg, self.moon_ra, self.moon_dec)
        self.moon_phase_angle = 180 - elongation
        self.moon_illum = (1 - np.cos(np.radians(elongation))) / 2
        self.moon_waxing = self.moon_illum[-1] > self.moon_illum[0]

        # The darkest level this night reaches; UK midsummer never gets to
        # astronomical darkness.
        for name, limit in (("astronomical", -18), ("nautical", -12), ("civil", -6)):
            self.dark = self.sun_alt < limit
            self.dark_level = name
            if self.dark.any():
                break
        self.twilight = self.sun_alt < BODY_SUN_LIMIT

    def _sun_alt_at(self, when):
        t = Time(when)
        frame = AltAz(obstime=t, location=self.location)
        return float(get_body("sun", t, self.location).transform_to(frame).alt.deg)

    # --- time helpers -------------------------------------------------------

    def local(self, i):
        return datetime.fromtimestamp(float(self.unix[i]), self.tz)

    def span(self, mask):
        """(first, last) local datetimes where mask is true, or None."""
        idx = np.flatnonzero(mask)
        return (self.local(idx[0]), self.local(idx[-1])) if len(idx) else None

    def crossings(self, alt, level, when=None):
        """(rise, set) local datetimes of the first crossings of an altitude,
        optionally only counting samples where the mask `when` is true."""
        above = alt > level
        when = np.ones(len(alt) - 1, bool) if when is None else when[1:]
        rise = np.flatnonzero(~above[:-1] & above[1:] & when)
        down = np.flatnonzero(above[:-1] & ~above[1:] & when)
        return (self.local(rise[0] + 1) if len(rise) else None,
                self.local(down[0] + 1) if len(down) else None)

    def at(self, unix, values):
        """Sample one of this night's series at arbitrary unix times."""
        return np.interp(unix, self.unix, values)

    # --- positions ----------------------------------------------------------

    def altaz_fixed(self, ra, dec):
        """Altitude and azimuth, shape (targets, times), for fixed positions."""
        coords = SkyCoord(ra=np.asarray(ra)[:, None] * u.deg,
                          dec=np.asarray(dec)[:, None] * u.deg)
        frame = AltAz(obstime=self.times.reshape(1, -1), location=self.location)
        altaz = coords.transform_to(frame)
        return altaz.alt.deg, altaz.az.deg

    def altaz_moving(self, ra, dec):
        """Altitude and azimuth for a position given at every sample time."""
        altaz = SkyCoord(ra=ra * u.deg, dec=dec * u.deg).transform_to(self.frame)
        return altaz.alt.deg, altaz.az.deg

    def body(self, name):
        """(ra, dec, alt, az) arrays for a solar-system body."""
        b = get_body(name, self.times, self.location)
        altaz = b.transform_to(self.frame)
        return b.ra.deg, b.dec.deg, altaz.alt.deg, altaz.az.deg

    def horizon(self, az, floor):
        """Lowest usable altitude at each azimuth."""
        limit = np.full_like(az, float(floor))
        for block in self.blocked:
            lo, hi = block["from"] % 360, block["to"] % 360
            inside = (az >= lo) & (az <= hi) if lo <= hi else (az >= lo) | (az <= hi)
            limit[inside] = np.maximum(limit[inside], block["altitude"])
        return limit

    # --- assessment ---------------------------------------------------------

    def sky_brightness(self, i, alt, ra, dec):
        """Background brightness (mag/arcsec²) at a position at sample i:
        the site's light pollution plus moonlight."""
        sep = float(separation(ra, dec, self.moon_ra[i], self.moon_dec[i]))
        moon = moonlight(self.moon_phase_angle[i], self.moon_alt[i], alt, sep)
        return float(_to_mag(_to_nl(self.sqm) + moon)), sep

    def assess(self, target, ra, dec, alt, az, solar_system=False):
        """Observability of one target tonight, or None if it never clears the
        horizon limits in darkness. ra/dec/alt/az are per-sample arrays."""
        floor = BODY_MIN_ALT if solar_system else self.min_alt
        when = self.twilight if solar_system else self.dark
        usable = when & self.future & (alt >= self.horizon(az, floor))
        if not usable.any():
            return None
        i = int(np.argmax(np.where(usable, alt, -99)))
        start, end = self.span(usable)
        sky, moon_sep = self.sky_brightness(i, alt[i], ra[i], dec[i])
        dimming = EXTINCTION * (float(air_mass(alt[i])) - 1)
        kind = target["kind"]

        if solar_system:
            visibility, contrast = 1.0, None
        elif kind in DIFFUSE:
            surface = surface_brightness(target) + dimming
            contrast = surface - sky  # > 0: fainter than the sky background
            # Catalogue sizes take in faint outskirts, so a mean surface
            # brightness a magnitude below the sky still shows a bright core.
            lost = np.clip((contrast - 1.0) / 5, 0, 0.85)
            visibility = 1 - DIFFUSE[kind] * lost
        else:
            contrast = None
            visibility = float(np.clip(1 - 0.1 * (21.5 - sky), 0.5, 1))

        hours = usable.sum() * STEP_MIN / 60
        mag = target.get("mag")
        height = float(np.clip((alt[i] - 15) / 45, 0, 1))
        duration = float(np.clip(hours / 3, 0.2, 1))
        if solar_system:
            # Planets sit where the ecliptic puts them; don't mark them down
            # much for being low.
            score = 100 * (0.25 * height + 0.60 * target["appeal"] + 0.15 * duration)
        else:
            brightness = 0.4 if mag is None else float(np.clip((11.5 - mag) / 7.5, 0.1, 1))
            # Messier and named objects are the proven showpieces.
            appeal = min(1.0, 0.75 * brightness + 0.25 * target.get("messier", False)
                         + 0.12 * bool(target.get("name")))
            score = 100 * (0.45 * height + 0.40 * appeal + 0.15 * duration) * visibility

        return {
            "id": target["id"], "name": target.get("name", ""), "kind": kind,
            "const": target.get("const", ""), "mag": mag, "size": target.get("size"),
            "ra": round(float(ra[i]), 4), "dec": round(float(dec[i]), 4),
            "best": self.local(i), "best_alt": round(float(alt[i]), 1),
            "best_az": round(float(az[i]), 1), "direction": compass(az[i]),
            "start": start, "end": end, "hours": round(float(hours), 1),
            "moon_sep": None if kind == "moon" else round(moon_sep),
            "sky": round(sky, 2),
            "contrast": None if contrast is None else round(float(contrast), 1),
            "score": round(float(score), 1),
        }


def surface_brightness(target):
    """Mean surface brightness in mag/arcsec² from total magnitude and size."""
    mag, major = target.get("mag"), target.get("size")
    if mag is None or not major:
        return DEFAULT_SURFACE_BRIGHTNESS
    minor = target.get("minor") or major
    return mag + 2.5 * math.log10(math.pi / 4 * major * minor * 3600)
