#!/usr/bin/env python3
"""A companion for someone else's observatory: watches what it does, says
what went wrong and why, and never touches it.

It reads only what the observatory already writes: the frames its capture
program saves (NINA, SGP, APT, SharpCap, Ekos: any FITS with the usual
headers) and PHD2's guiding (its live event server, listened to, or its
guide log afterwards). It sends nothing to any camera, mount, focuser,
wheel or program: no command it has can move, expose or change anything,
so it can run beside a working setup on its first night.

    ./companion.py report FOLDER [--phd2-log FILE]     the night, the morning after
    ./companion.py watch FOLDER [--phd2 HOST:PORT]      live: a line a frame, a note when something changes
    ./companion.py check FOLDER [--phd2-log FILE]       what it can see: frames, headers, guiding

For each frame: the stars' count, sharpness (FWHM), shape and brightness,
the sky's level, the sensor's temperature against its target, and how
guiding went during it. Each is judged against the best frames of the same
target and filter that night, so no figure from another telescope is
assumed. The report says where the night's time went, target by target and
filter by filter: what was kept, what was spoiled and by what, and the gaps
with no frames. What it measured is said apart from what it infers.
"""
import argparse
import csv
import datetime as dt
import io
import json
import math
import re
import statistics
import sys
import time
from pathlib import Path

import config

FRAME_SUFFIXES = (".fits", ".fit", ".fts", ".xisf")
SOFT = 1.25          # FWHM this many times the best frames': soft
DIM = 0.5            # stars or their brightness down to this share: dimmed
ROUND = 0.75         # roundness below this, the best frames' being round: trailed
BRIGHT_SKY = 1.6     # sky level this many times the best frames': a brighter sky
OFF_TARGET_C = 1.0   # sensor this far from its cooling target: off it
GUIDE_HIGH = 1.6     # guide RMS this many times the night's usual: guiding poor
GAP_MIN_S = 120      # a gap between frames longer than this, beyond the usual: time with no frames


# ---------------------------------------------------------------- frames

def frames(folder):
    """Every frame under `folder`, oldest first by its own start time."""
    import os
    found = [Path(top) / name for top, _, names in os.walk(folder, followlinks=True) for name in names
             if Path(name).suffix.lower() in FRAME_SUFFIXES]
    return sorted(found, key=lambda p: p.stat().st_mtime)


def _when(header):
    text = str(header.get("DATE-OBS") or header.get("DATE") or "").strip().rstrip("Z")
    text = re.sub(r"(\.\d{6})\d+$", r"\1", text)      # seven decimal places (some programs) to the six Python reads
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return dt.datetime.strptime(text, fmt).replace(tzinfo=dt.timezone.utc).timestamp()
        except ValueError:
            continue
    return None


def _number(header, *keys):
    for key in keys:
        value = header.get(key)
        try:
            if value is not None and value != "":
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _folder_name(path):
    """A target's name from its folder when the header has none: the
    nearest folder not named by a date or time."""
    for part in Path(path).parents:
        if part.name and not re.fullmatch(r"[\d_\-T]+", part.name):
            return part.name
    return "unnamed"


XISF_TYPES = {"UInt8": "u1", "UInt16": "<u2", "UInt32": "<u4", "Float32": "<f4", "Float64": "<f8"}


def read_xisf(path):
    """(image, header) from an XISF file (PixInsight's format, which NINA
    can save in): its first image, uncompressed or zlib-compressed, and
    its FITS keywords. None for a colour or multi-channel image; a
    compression it cannot read (lz4, zstd) is an error the caller says."""
    import xml.etree.ElementTree as ET
    import zlib

    import numpy as np
    raw = Path(path).read_bytes()
    if raw[:8] != b"XISF0100":
        raise ValueError("not an XISF file")
    length = int.from_bytes(raw[8:12], "little")
    root = ET.fromstring(raw[16:16 + length].decode("utf-8"))
    image = next((e for e in root.iter() if e.tag.endswith("Image")), None)
    if image is None:
        return None
    size = [int(v) for v in image.get("geometry", "0:0:0").split(":")]
    if len(size) != 3 or size[2] != 1:
        return None
    where = image.get("location", "").split(":")
    if where[0] != "attachment":
        raise ValueError(f"XISF data not attached ({where[0]}): not read")
    start, count = int(where[1]), int(where[2])
    block = raw[start:start + count]
    kind = XISF_TYPES[image.get("sampleFormat", "UInt16")]
    packed = image.get("compression")
    if packed:
        method = packed.split(":")[0]
        if not method.startswith("zlib"):
            raise ValueError(f"XISF compression {method}: only zlib is read here")
        block = zlib.decompress(block)
        if "+sh" in method:              # byte shuffling: the bytes of each value were grouped
            width = np.dtype(kind).itemsize
            block = np.frombuffer(block, "u1").reshape(width, -1).T.tobytes()
    data = np.frombuffer(block, kind).reshape(size[1], size[0])
    header = {}
    for key in (e for e in image.iter() if e.tag.endswith("FITSKeyword")):
        header[key.get("name")] = key.get("value", "").strip().strip("'").strip()
    return data, header


def measure(path):
    """One frame, measured: its header's facts and its stars. Reads only."""
    import numpy as np
    from astropy.io import fits

    import stacking
    from camera import luminance
    if Path(path).suffix.lower() == ".xisf":
        found = read_xisf(path)
        if found is None:
            return {"file": str(path), "skip": "a colour or multi-channel XISF: not a raw frame"}
        data, header = found
    else:
        with fits.open(path, memmap=False) as hdus:
            hdu = next((h for h in hdus if getattr(h, "data", None) is not None and h.data.ndim == 2), None)
            if hdu is None:
                return {"file": str(path), "skip": "no single-plane image (a stack or a colour picture)"}
            data, header = hdu.data, hdu.header
    kind = str(header.get("IMAGETYP") or header.get("FRAME") or "light").strip().lower()
    if "light" not in kind:
        return {"file": str(path), "skip": f"a calibration frame ({kind})"}
    start = _when(header)
    exposure = _number(header, "EXPTIME", "EXPOSURE")
    # The 2x2 sum: a colour mosaic's colour cells, a mono frame's blocks, as the project's own frames.
    rows, cols = data.shape[0] // 2 * 2, data.shape[1] // 2 * 2
    lum = luminance(np.asarray(data[:rows, :cols], dtype=np.float32))
    stars = stacking.find_stars(lum)
    q = stacking.quality(lum, stars)
    pixel = _number(header, "XPIXSZ", "PIXSIZE1", "PIXSIZE")
    focal = _number(header, "FOCALLEN")
    binning = _number(header, "XBINNING") or 1
    scale = 206.265 * pixel * binning * 2 / focal if pixel and focal else None      # arcsec a 2x2 pixel
    sensor, target = _number(header, "CCD-TEMP", "CCD_TEMP", "TEMPERAT"), _number(header, "SET-TEMP", "SET_TEMP")
    return {"file": str(path), "start": start, "exposure": exposure,
            "end": start + exposure if start is not None and exposure else None,
            "object": str(header.get("OBJECT") or "").strip() or _folder_name(path),
            "filter": str(header.get("FILTER") or "").strip() or "none",
            "gain": _number(header, "GAIN"), "sensor_c": sensor, "target_c": target,
            "focuser": _number(header, "FOCPOS", "FOCUSPOS"), "focuser_c": _number(header, "FOCTEMP", "FOCUSTEM"),
            "camera": str(header.get("INSTRUME") or "").strip(),
            "stars": q["stars"], "fwhm_px": q["fwhm"], "roundness": q["roundness"], "flux": q["flux"],
            "background": q["background"], "scale": scale,
            "fwhm_arcsec": q["fwhm"] * scale if q["fwhm"] and scale else None}


# ---------------------------------------------------------------- guiding

class GuideLog:
    """PHD2's guide log (PHD2_GuideLog_*.txt), read: each guide step's time,
    its distance from the lock in pixels, and the steps where the star was
    lost; dithers and the stretches guiding was on. PHD2 writes its times
    in the computer's own local time, which is how they are read."""

    def __init__(self, paths):
        self.steps, self.dithers, self.sessions, self.scale, self.exposure = [], [], [], None, None
        for path in paths:
            self._read(Path(path))
        self.steps.sort()
        # The guide cycle: PHD2's own exposure (its log says it) and a
        # readout; only without it, the night's usual spacing of steps.
        import phd2
        spacing = [b[0] - a[0] for a, b in zip(self.steps, self.steps[1:]) if 0 < b[0] - a[0] < 60]
        self.cycle = (self.exposure + phd2.READOUT_S if self.exposure else
                      statistics.median(spacing) if spacing else 3.0)

    def _read(self, path):
        begun, columns = None, None
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("Calibration Begins at"):
                begun, columns = None, None      # calibration's rows are not guide steps
                continue
            found = re.match(r"Guiding Begins at (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", line)
            if found:
                begun = local(found.group(1), "%Y-%m-%d %H:%M:%S")
                self.sessions.append([begun, None])
                columns = None
                continue
            found = re.match(r"Guiding Ends at (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", line)
            if found and self.sessions:
                self.sessions[-1][1] = local(found.group(1), "%Y-%m-%d %H:%M:%S")
                begun = None
                continue
            found = re.search(r"Pixel scale = ([\d.]+) arc-sec/px", line)
            if found:
                self.scale = float(found.group(1))
            found = re.search(r"Exposure = (\d+) ?ms", line)
            if found:
                self.exposure = int(found.group(1)) / 1000
            if line.startswith("Frame,Time,"):
                columns = next(csv.reader([line]))
                continue
            if "DITHER" in line.upper() and begun is not None and self.steps:
                self.dithers.append(self.steps[-1][0])
                continue
            if begun is None or columns is None or not line[:1].isdigit():
                continue
            row = dict(zip(columns, next(csv.reader(io.StringIO(line)))))
            try:
                when = begun + float(row["Time"])
            except (KeyError, ValueError):
                continue
            dropped = row.get("mount", "").strip('"') == "DROP"   # PHD2's FrameDropped row (guidinglog.cpp)
            try:
                ra, dec = float(row.get("RARawDistance") or 0), float(row.get("DECRawDistance") or 0)
            except ValueError:
                ra = dec = 0.0
            self.steps.append((when, None if dropped else math.hypot(ra, dec)))

    def during(self, start, end):
        return _judge([s for s in self.steps if start <= s[0] <= end], self.scale,
                      any(a <= start and (b is None or b >= end) for a, b in self.sessions), start, end, self.cycle)

    def sparse(self):
        """Stretches PHD2 was guiding with far fewer guide steps than its
        cycle makes: [(start, end, steps)]. Its state said guiding; its own
        steps did not."""
        out = []
        for a, b in self.sessions:
            b = b if b is not None else (self.steps[-1][0] if self.steps else a)
            steps = sum(1 for t, _ in self.steps if a <= t <= b)
            if b - a >= 4 * self.cycle and steps * self.cycle < 0.5 * (b - a):
                out.append((a, b, steps))
        return out

    def events_between(self, start, end):
        lost = sum(1 for t, d in self.steps if start <= t <= end and d is None)
        dithers = sum(1 for t in self.dithers if start <= t <= end)
        on = [s for s in self.sessions if s[0] <= end and (s[1] is None or s[1] >= start)]
        return {"star_lost": lost, "dithers": dithers, "guiding_on": bool(on),
                "guiding_started": [s[0] for s in self.sessions if start < s[0] < end],
                "guiding_ended": [s[1] for s in self.sessions if s[1] and start < s[1] < end]}


class GuideLive:
    """PHD2's event server, listened to: the guide steps as they come. Only
    PHD2's read-only questions are ever asked (its pixel scale)."""

    def __init__(self, address):
        import phd2
        self.link = phd2.Phd2(address)
        try:
            self.scale = float(self.link.call("get_pixel_scale") or 0) or None
        except Exception:      # noqa: BLE001 - a scale it will not give leaves pixels
            self.scale = None
        try:
            self.cycle = float(self.link.call("get_exposure")) / 1000 + phd2.READOUT_S
        except Exception:      # noqa: BLE001 - PHD2's usual 2 s and a readout
            self.cycle = 2.0 + phd2.READOUT_S

    def during(self, start, end):
        rows = self.link.steps(start, end)
        steps = [(e.get("Timestamp", e["_seen"]),
                  None if e["Event"] == "StarLost" else math.hypot(e.get("RADistanceRaw", 0), e.get("DECDistanceRaw", 0)))
                 for e in rows]
        return _judge(steps, self.scale, bool(steps), start, end, self.cycle)

    def events_between(self, start, end):
        rows = self.link.steps(start, end)
        return {"star_lost": sum(1 for e in rows if e["Event"] == "StarLost"), "dithers": 0, "guiding_on": bool(rows),
                "guiding_started": [], "guiding_ended": []}


def _judge(steps, scale, on, start, end, cycle):
    """How guiding went in one frame, by the same rule as the PHD2 guider
    (phd2.unguided): guided only with guide steps all through it, not one
    step in a long exposure."""
    import phd2
    good = [(t, d) for t, d in steps if d is not None]
    errors = [d * (scale or 1.0) for _, d in good]
    lost = phd2.unguided([t for t, _ in good], start, end, cycle)
    guided = on and bool(good) and lost <= 0.5 * cycle
    return {"guided": guided, "steps": len(steps), "star_lost": len(steps) - len(good),
            "unguided_s": round(lost, 1), "coverage": round(max(0.0, 1 - lost / (end - start)), 3) if end > start else None,
            "rms": round(math.sqrt(sum(e * e for e in errors) / len(errors)), 2) if errors else None,
            "max": round(max(errors), 2) if errors else None, "unit": "arcsec" if scale else "px"}


# ---------------------------------------------------------------- NINA's own log

ZONE = None          # the zone the logs' local times are in (--tz); None: this computer's


def local(text, fmt):
    """A local time from a log, as UTC seconds: in ZONE when given (a log
    from another computer's clock), else this computer's own zone."""
    when = dt.datetime.strptime(text, fmt)
    if ZONE:
        from zoneinfo import ZoneInfo
        when = when.replace(tzinfo=ZoneInfo(ZONE))
    return when.timestamp()


# NINA's sequencer logs every step "Starting Category: C, Item: NAME, ..."
# and "Finishing ..." (or "Failed: ..."), and every trigger "Starting
# Trigger: NAME" (NINA.Sequencer, SequenceItem.Run and SequenceTrigger.Run,
# read from NINA's source). What each step is, for the time it took:
KINDS = {"RunAutofocus": "autofocus", "AutofocusAfterExposures": "autofocus",
         "AutofocusAfterFilterChange": "autofocus", "AutofocusAfterHFRIncreaseTrigger": "autofocus",
         "AutofocusAfterTemperatureChangeTrigger": "autofocus", "AutofocusAfterTimeTrigger": "autofocus",
         "Center": "centring (plate solving)", "CenterAndRotate": "centring (plate solving)",
         "SolveAndSync": "centring (plate solving)", "SolveAndRotate": "centring (plate solving)",
         "CenterAfterDriftTrigger": "centring (plate solving)", "SlewScopeToRaDec": "slewing",
         "SlewScopeToAltAz": "slewing", "Dither": "dithering", "DitherAfterExposures": "dithering",
         "MeridianFlipTrigger": "meridian flip", "ProgrammableMeridianFlipTrigger": "meridian flip",
         "StartGuiding": "starting guiding", "StopGuiding": "guiding stopped", "RestoreGuiding": "starting guiding",
         "WaitForTime": "waiting", "WaitForTimeSpan": "waiting", "WaitUntil": "waiting",
         "WaitForAltitude": "waiting", "WaitUntilAboveHorizon": "waiting", "WaitForSunAltitude": "waiting",
         "WaitForMoonAltitude": "waiting", "WaitUntilSafe": "waiting for safe conditions",
         "TriggerOnUnsafe": "unsafe conditions", "CoolCamera": "camera cooling", "WarmCamera": "camera warming",
         "SwitchFilter": "filter change", "ParkScope": "parking", "UnparkScope": "unparking",
         "FindHome": "finding home", "OpenDomeShutter": "dome", "CloseDomeShutter": "dome",
         "SynchronizeDome": "dome", "ReconnectTrigger": "reconnecting", "ReconnectOnDownloadFailure": "reconnecting",
         "ConnectAllEquipment": "connecting", "ConnectEquipment": "connecting"}
LINE = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?)\|([A-Z]+)\|([^|]*)\|([^|]*)\|([^|]*)\|(.*)$")


def night_span(day):
    """Noon to noon from the date given, in the logs' zone, as UTC seconds."""
    start = local(f"{day} 12:00:00", "%Y-%m-%d %H:%M:%S")
    return start, start + 24 * 3600


def logs_only(nina, guide=None):
    """A night from NINA's log alone, with PHD2's guiding for each exposure
    when its log is given: no frame is measured."""
    lines = nina.summary()
    if guide and nina.exposures:
        judged = [guide.during(e["start"], e["start"] + e["seconds"]) for e in nina.exposures]
        inside = [j for j, e in zip(judged, nina.exposures)
                  if any(a <= e["start"] and (b is None or b >= e["start"] + e["seconds"]) for a, b in guide.sessions)]
        guided = sum(1 for j in inside if j["guided"])
        lost = sum(j["star_lost"] for j in inside)
        lines.append(f"Guiding (PHD2's log): {len(inside)} of {len(nina.exposures)} exposures taken while PHD2 was "
                     f"guiding; {guided} of those guided all through, {len(inside) - guided} with gaps in the guide "
                     f"steps; the star lost {lost} time(s) during them")
        for a, b, steps in guide.sparse():
            lines.append(f"PHD2 said it was guiding {_clock(a)}-{_clock(b)} ({b - a:.0f} s) with {steps} guide "
                         f"step(s), where its {guide.cycle:.0f} s cycle makes about {(b - a) / guide.cycle:.0f}: "
                         "the exposures then were not guided all through (measured from its log)")
        rms = [j["rms"] for j in inside if j["rms"] is not None]
        if rms:
            lines.append(f"Guide error during exposures: median RMS {statistics.median(rms):.2f} "
                         f"{inside[0]['unit']}, worst {max(rms):.2f}")
    lines.append("From the logs alone: no frame was measured, so nothing here says whether the pictures were good.")
    return lines


class NinaLog:
    """NINA's log (%LOCALAPPDATA%\\NINA\\Logs), read: each exposure started
    and each file saved, the sequencer's steps with when they began and
    ended (or failed), the safety monitor's changes, devices lost, and
    errors. Its times are the computer's local time (ZONE)."""

    def __init__(self, paths):
        self.exposures, self.saves, self.steps, self.events, self.errors = [], [], [], [], []
        open_steps = {}
        for path in paths:
            for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
                found = LINE.match(line)
                if not found:
                    continue
                stamp, level, source, method, _, text = found.groups()
                when = local(stamp[:26], "%Y-%m-%dT%H:%M:%S.%f" if "." in stamp else "%Y-%m-%dT%H:%M:%S")
                self._take(when, level, source, method, text.strip(), open_steps)
        for (name, kind), began in open_steps.items():
            self.steps.append({"kind": kind, "name": name, "start": began, "end": None, "failed": False})
        self.steps.sort(key=lambda s: s["start"])

    def _take(self, when, level, source, method, text, open_steps):
        found = re.match(r"Starting Exposure - Exposure Time: ([\d.]+)s; Filter: ([^;]*);", text)
        if found:
            self.exposures.append({"start": when, "seconds": float(found.group(1)), "filter": found.group(2).strip()})
            return
        found = re.match(r"Successfully saved file at (.*)", text)
        if found:
            self.saves.append({"time": when, "file": found.group(1)})
            return
        found = re.match(r"(Starting|Finishing|Failed:) (?:Category: [^,]*, )?(Item|Trigger): (\w+)", text)
        if found:
            verb, _, name = found.groups()
            kind = KINDS.get(name)
            if kind is None or name == "TakeExposure":
                return
            key = (name, kind)
            if verb == "Starting":
                if name.endswith("Trigger") or name in ("TriggerOnUnsafe", "RestoreGuiding"):
                    # A trigger logs its start only; what it runs logs the rest.
                    self.steps.append({"kind": kind, "name": name, "start": when, "end": None, "failed": False})
                else:
                    open_steps[key] = when
            else:
                began = open_steps.pop(key, None)
                if began is not None:
                    self.steps.append({"kind": kind, "name": name, "start": began, "end": when,
                                       "failed": verb == "Failed:"})
            return
        found = re.search(r"SafetyMonitorInfo state changed to (\w+)", text)
        if found:
            self.events.append((when, f"the safety monitor said {found.group(1).lower()}"))
            return
        if method == "UsbDeviceWatcher_DeviceRemoved":
            self.events.append((when, "a USB device was removed"))
            return
        if method in ("OpenShutter", "CloseShutter"):
            self.events.append((when, "the dome shutter " + ("opened" if method == "OpenShutter" else "closed")))
            return
        if level == "ERROR":
            self.errors.append((when, f"{source}: {text[:140]}"))

    def only(self, start, end):
        """Keep only what happened between two times (one night)."""
        self.exposures = [e for e in self.exposures if start <= e["start"] < end]
        self.saves = [s for s in self.saves if start <= s["time"] < end]
        self.steps = [s for s in self.steps if start <= s["start"] < end]
        self.events = [e for e in self.events if start <= e[0] < end]
        self.errors = [e for e in self.errors if start <= e[0] < end]

    def between(self, start, end):
        """What NINA logged between two times, in words, with the seconds
        each kind of step took inside the window."""
        said = []
        took = {}
        for step in self.steps:
            a, b = step["start"], step["end"] if step["end"] is not None else step["start"]
            if b < start or a > end:
                continue
            seconds = max(0.0, min(b, end) - max(a, start))
            name = step["kind"] + (" (failed)" if step["failed"] else "")
            took[name] = took.get(name, 0.0) + seconds
        for name, seconds in sorted(took.items(), key=lambda kv: -kv[1]):
            said.append(f"NINA: {name}" + (f" {seconds / 60:.1f} min" if seconds >= 30 else ""))
        started = [e for e in self.exposures if start <= e["start"] <= end]
        saved = [s for s in self.saves if start <= s["time"] <= end]
        if len(started) > len(saved):
            said.append(f"NINA: {len(started) - len(saved)} exposure(s) started and not saved")
        for when, what in self.events:
            if start <= when <= end:
                said.append(f"NINA: {what} at {_clock(when)}")
        errors = [text for when, text in self.errors if start <= when <= end]
        if errors:
            said.append(f"NINA: {len(errors)} error(s), the first: {errors[0]}")
        return said

    def summary(self):
        """The night by NINA's log alone: exposures started and saved by
        filter and length, the time each kind of step took, events, errors."""
        lines = []
        groups = {}
        for e in self.exposures:
            groups.setdefault((e["filter"] or "no filter", e["seconds"]), []).append(e)
        for (band, seconds), started in sorted(groups.items(), key=lambda kv: kv[1][0]["start"]):
            lines.append(f"{band}, {seconds:g} s: {len(started)} exposures started, "
                         f"{len(started) * seconds / 60:.0f} min of exposure, {_clock(started[0]['start'])}-"
                         f"{_clock(started[-1]['start'])}")
        lines.append(f"Files saved: {len(self.saves)} of {len(self.exposures)} exposures started")
        took = {}
        for step in self.steps:
            if step["end"] is not None:
                name = step["kind"] + (" (failed)" if step["failed"] else "")
                took[name] = took.get(name, 0.0) + step["end"] - step["start"]
        if took:
            lines.append("Time in the sequencer's steps: " + ", ".join(
                f"{name} {seconds / 60:.0f} min" for name, seconds in sorted(took.items(), key=lambda kv: -kv[1])))
        kinds = {}
        for _, what in self.events:
            key = re.sub(r" at .*", "", what)
            kinds[key] = kinds.get(key, 0) + 1
        if kinds:
            lines.append("Events: " + ", ".join(f"{what} ({n})" for what, n in sorted(kinds.items())))
        if self.errors:
            lines.append(f"Errors: {len(self.errors)}, the first {_clock(self.errors[0][0])}: {self.errors[0][1]}")
        return lines


# ---------------------------------------------------------------- judging

MIN_COMPARED = 3      # fewer frames with stars than this in a setup: nothing to judge them against


def setup(row):
    """What frames must share to be judged against each other: the night
    (from noon to noon, local), target, filter, camera, gain, exposure and
    pixel scale. A folder holding several nights or setups is split, never
    given one baseline."""
    night = dt.datetime.fromtimestamp(row["start"] - 12 * 3600).date().isoformat() if row.get("start") else "?"
    return (night, row.get("object", "?"), row.get("filter", "?"), row.get("camera") or "", row.get("gain"),
            row.get("exposure"), round(row["scale"], 2) if row.get("scale") else None)


def references(rows):
    """For each setup, its best frames' figures: the brighter half of those
    with stars, then the sharper half of those, so a spoiled stretch cannot
    set the bar. A setup with fewer than MIN_COMPARED frames with stars has
    none: its frames are unassessable, never taken as good."""
    out = {}
    for key in {setup(r) for r in rows}:
        mine = [r for r in rows if setup(r) == key and r.get("fwhm_px") and r.get("stars")]
        if len(mine) < MIN_COMPARED:
            continue
        # The brighter half first (thin cloud shrinks stars as it dims them,
        # so the sharpest alone could be the cloudiest), then the sharper half of those.
        bright = sorted(mine, key=lambda r: -(r["flux"] or 0))[:max(1, (len(mine) + 1) // 2)]
        best = sorted(bright, key=lambda r: r["fwhm_px"])[:max(1, (len(bright) + 1) // 2)]
        guides = [r["guide"]["rms"] for r in mine if (r.get("guide") or {}).get("rms") is not None]
        out[key] = {"fwhm_px": statistics.median(r["fwhm_px"] for r in best),
                    "stars": statistics.median(r["stars"] for r in best),
                    "flux": statistics.median(r["flux"] for r in best),
                    "roundness": statistics.median(r["roundness"] for r in best),
                    "background": statistics.median(r["background"] for r in best),
                    "guide_rms": statistics.median(guides) if guides else None,
                    "focuser_c": statistics.median([r["focuser_c"] for r in best if r.get("focuser_c") is not None])
                    if any(r.get("focuser_c") is not None for r in best) else None}
    return out


UNASSESSABLE = "unassessable"


def judge(row, ref):
    """What spoiled a frame, if anything: [(cause, measured, inferred)],
    empty for a good frame. `measured` is what the figures show; `inferred`
    the likeliest reason, which they do not prove. With nothing to judge it
    against (no reference for its setup) it is UNASSESSABLE, never good."""
    if not ref:
        return [(UNASSESSABLE, "fewer than three frames with stars in its setup (night, target, filter, camera, "
                               "gain, exposure, scale): nothing to judge it against", "")]
    found = []
    guide = row.get("guide") or {}
    if not row.get("stars") or row["stars"] < DIM * ref["stars"] or (row.get("flux") or 0) < DIM * ref["flux"]:
        bright = row["background"] > BRIGHT_SKY * ref["background"]
        found.append(("dimmed", f"{row.get('stars', 0)} stars against {ref['stars']:.0f}, their light "
                                f"{100 * (row.get('flux') or 0) / ref['flux']:.0f}% of the best frames'",
                      "cloud or haze" + (" (the sky brighter too)" if bright else "")))
    elif row["background"] > BRIGHT_SKY * ref["background"]:
        found.append(("bright sky", f"sky level {row['background'] / ref['background']:.1f} times the best frames'",
                      "the Moon, twilight or a light nearby"))
    if row.get("roundness") is not None and row["roundness"] < ROUND <= ref["roundness"]:
        poor = guide.get("rms") is not None and ref.get("guide_rms") and guide["rms"] > GUIDE_HIGH * ref["guide_rms"]
        found.append(("trailed", f"stars' roundness {row['roundness']:.2f} against {ref['roundness']:.2f}",
                      "guiding (its RMS was high)" if poor or guide.get("star_lost") else
                      "wind, flexure, or the mount (guiding looked normal)" if guide.get("guided") else
                      "the mount's tracking or the wind (no guiding to compare)"))
    if row.get("fwhm_px") and row["fwhm_px"] > SOFT * ref["fwhm_px"] and not any(c == "dimmed" for c, _, _ in found):
        poor = guide.get("rms") is not None and ref.get("guide_rms") and guide["rms"] > GUIDE_HIGH * ref["guide_rms"]
        colder = (ref.get("focuser_c") is not None and row.get("focuser_c") is not None
                  and ref["focuser_c"] - row["focuser_c"] >= 1.0)
        found.append(("soft", f"FWHM {row['fwhm_px'] / ref['fwhm_px']:.2f} times the best frames'",
                      "guiding (its RMS was high)" if poor else
                      f"focus ({ref['focuser_c'] - row['focuser_c']:.1f} °C colder at the focuser than the best "
                      "frames)" if colder else "focus or seeing (guiding looked normal)" if guide.get("guided") else
                      "focus or seeing"))
    if row.get("sensor_c") is not None and row.get("target_c") is not None and \
            abs(row["sensor_c"] - row["target_c"]) > OFF_TARGET_C:
        found.append(("off cooling target", f"sensor {row['sensor_c']:.1f} °C, target {row['target_c']:.1f} °C",
                      "still cooling, or the cooler at its limit"))
    if guide.get("star_lost"):
        found.append(("guide star lost", f"PHD2 lost its star {guide['star_lost']} time(s) during it", ""))
    if guide and guide.get("unguided_s", 0) > 0 and not guide.get("guided"):
        found.append(("guiding gap", f"{guide['unguided_s']:.0f} s of it with no guide step", ""))
    return found


def gaps(rows, guide=None, nina=None):
    """Stretches with no frame, longer than the night's usual time between
    frames by GAP_MIN_S: [(from, to, minutes, what was happening)]."""
    timed = sorted((r for r in rows if r.get("start") and r.get("end")), key=lambda r: r["start"])
    # Within one night only (noon to noon): the day between two nights is
    # not time lost, and a folder of several nights is several nights.
    pairs = [(a, b) for a, b in zip(timed, timed[1:]) if setup(a)[0] == setup(b)[0]]
    between = [b["start"] - a["end"] for a, b in pairs]
    usual = statistics.median([g for g in between if g >= 0]) if between else 0
    out = []
    for a, b in pairs:
        gap = b["start"] - a["end"]
        if gap - usual < GAP_MIN_S:
            continue
        why = []
        if (a["object"], a["filter"]) != (b["object"], b["filter"]):
            why.append(f"changed from {a['object']} {a['filter']} to {b['object']} {b['filter']} (measured)")
        elif setup(a) != setup(b):
            why.append("the camera's settings changed (measured)")
        if guide:
            seen = guide.events_between(a["end"], b["start"])
            if seen["star_lost"]:
                why.append(f"PHD2 lost its star {seen['star_lost']} time(s) (measured)")
            if seen["guiding_ended"]:
                why.append("PHD2 stopped guiding (measured)")
            if seen["guiding_started"]:
                why.append("PHD2 started guiding again (measured)")
            if seen["dithers"]:
                why.append(f"{seen['dithers']} dither(s), the settling after them (measured)")
            if not seen["guiding_on"]:
                why.append("no guiding at all then (measured)")
        if nina:
            why += [f"{w} (logged)" for w in nina.between(a["end"], b["start"])]
        out.append((a["end"], b["start"], (gap - usual) / 60, why or [
            "not known: nothing it reads says" + ("" if nina else " (the capture program's own log, --nina-log, would)")]))
    return out


# ---------------------------------------------------------------- the report

def _clock(t):
    if not t:
        return "?"
    if ZONE:
        from zoneinfo import ZoneInfo
        return dt.datetime.fromtimestamp(t, ZoneInfo(ZONE)).strftime("%H:%M")
    return dt.datetime.fromtimestamp(t).strftime("%H:%M")


def read_one(path):
    """measure(), with what cannot be read said rather than raised."""
    try:
        return measure(path)
    except Exception as problem:          # noqa: BLE001 - one bad file is said, not the end of the night
        return {"file": str(path), "skip": f"not readable: {problem}", "unreadable": True}


def gather(folder, guide=None, say=None, paths=None):
    """(frames measured, files left out with why): every file found is one
    or the other."""
    rows, left = [], []
    for path in paths if paths is not None else frames(folder):
        row = read_one(path)
        if "skip" in row:
            left.append(row)
            continue
        if guide and row.get("start") and row.get("end"):
            row["guide"] = guide.during(row["start"], row["end"])
        rows.append(row)
        if say:
            say(f"  measured {Path(row['file']).name}")
    return rows, left


def report(rows, guide=None, left=(), nina=None):
    """The night in words and data: per setup, the gaps, and every file
    left out with why."""
    refs = references(rows)
    parts, lost = {}, {}
    for row in rows:
        key = setup(row)
        part = parts.setdefault(key, {"frames": 0, "kept": 0, "seconds": 0.0, "kept_seconds": 0.0, "causes": {},
                                      "unassessable": 0, "unassessable_seconds": 0.0,
                                      "fwhm": [], "guide_rms": [], "first": None, "last": None})
        causes = judge(row, refs.get(key))
        row["causes"] = [{"cause": c, "measured": m, "inferred": i} for c, m, i in causes]
        seconds = row.get("exposure") or 0
        part["frames"] += 1
        part["seconds"] += seconds
        if row.get("start"):
            part["first"] = min(part["first"] or row["start"], row["start"])
            part["last"] = max(part["last"] or 0, row.get("end") or row["start"])
        if not causes:
            part["kept"] += 1
            part["kept_seconds"] += seconds
            if row.get("fwhm_arcsec") or row.get("fwhm_px"):
                part["fwhm"].append(row.get("fwhm_arcsec") or row["fwhm_px"])
                part.setdefault("units", set()).add("arcsec" if row.get("fwhm_arcsec") else "px")
        elif causes[0][0] == UNASSESSABLE:
            part["unassessable"] += 1
            part["unassessable_seconds"] += seconds
        else:
            main = causes[0]
            part["causes"].setdefault(main[0], {"frames": 0, "seconds": 0.0, "inferred": main[2]})
            part["causes"][main[0]]["frames"] += 1
            part["causes"][main[0]]["seconds"] += seconds
            lost[main[0]] = lost.get(main[0], 0.0) + seconds
        if (row.get("guide") or {}).get("rms") is not None:
            part["guide_rms"].append(row["guide"]["rms"])
    holes = gaps(rows, guide, nina)
    for _, _, minutes, why in holes:
        known = not why[0].startswith("not known")
        name = "no frames (explained)" if known else "no frames (unexplained)"
        lost[name] = lost.get(name, 0.0) + minutes * 60
    for part in parts.values():
        part["units"] = sorted(part.get("units") or ())      # for --json
    reasons = {}
    for row in left:
        reason = row["skip"].split(":")[0] if row.get("unreadable") else row["skip"]
        reasons[reason] = reasons.get(reason, 0) + 1
    return {"frames": len(rows), "files": len(rows) + len(left), "left_out": reasons, "parts": parts, "gaps": holes,
            "sparse": guide.sparse() if isinstance(guide, GuideLog) else [],
            "lost": lost, "rows": rows}


def words(night):
    lines = [f"{night['files']} files: {night['frames']} light frames measured"
             + "".join(f"; {n} left out, {why}" for why, n in sorted(night["left_out"].items())) + "."]
    several = len({k[0] for k in night["parts"]}) > 1
    for key, p in sorted(night["parts"].items(), key=lambda kv: kv[1]["first"] or 0):
        when, target, band, camera, gain, exposure, _ = key
        kit = ", ".join(x for x in (camera, f"gain {gain:g}" if gain is not None else "",
                                    f"{exposure:g} s" if exposure else "") if x)
        kept = (f"{p['seconds'] / 60:.0f} min measured; {p['kept_seconds'] / 60:.0f} min acceptable by its own best "
                f"frames ({p['kept']} of {p['frames']} frames)")
        if p["unassessable"]:
            kept += f"; {p['unassessable_seconds'] / 60:.0f} min ({p['unassessable']} frames) unassessable"
        # The unit is the setup's own: arcseconds only when every frame of it
        # gave its pixel scale, pixels when none did, and no figure when they
        # are mixed (one median of the two would mean nothing).
        units = set(p.get("units") or ())
        sharp = (f", FWHM {statistics.median(p['fwhm']):.2f}{'″' if units == {'arcsec'} else ' px'}"
                 if p["fwhm"] and len(units) == 1 else
                 ", FWHM not given: some frames with a pixel scale and some without" if p["fwhm"] else "")
        guided = f", guide RMS {statistics.median(p['guide_rms']):.2f}" if p["guide_rms"] else ""
        lines.append(f"{(when + ' ') if several else ''}{target} {band}{f' ({kit})' if kit else ''} "
                     f"{_clock(p['first'])}-{_clock(p['last'])}: {kept}{sharp}{guided}")
        for cause, c in sorted(p["causes"].items(), key=lambda kv: -kv[1]["seconds"]):
            lines.append(f"    {c['seconds'] / 60:.0f} min ({c['frames']} frames) {cause}"
                         + (f": likely {c['inferred']}" if c["inferred"] else ""))
    for start, end, minutes, why in night["gaps"]:
        lines.append(f"No frames {_clock(start)}-{_clock(end)} ({minutes:.0f} min beyond the usual gap): " + "; ".join(why))
    for a, b, steps in night.get("sparse", []):
        lines.append(f"PHD2 said it was guiding {_clock(a)}-{_clock(b)} ({b - a:.0f} s) with only {steps} guide step(s) "
                     "(measured from its log)")
    if night["lost"]:
        worst = sorted(night["lost"].items(), key=lambda kv: -kv[1])
        lines.append("Where the time went: " + ", ".join(f"{cause} {seconds / 60:.0f} min" for cause, seconds in worst))
    lines.append("Measured: star counts, sharpness, shape, sky level, temperatures, guide steps. 'Acceptable' is "
                 "judged against the same setup's best frames that night, not a standard; 'likely' is inferred, not "
                 "proven. Frames the capture program never saved, and what it did in a gap (focusing, a meridian "
                 "flip, a download), are not seen here.")
    return "\n".join(lines)


def record(rows, name):
    folder = config.DATA / "cache" / "companion"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.jsonl"
    with path.open("a", encoding="utf-8") as out:
        for row in rows:
            out.write(json.dumps(row, default=str) + "\n")
    return path


# ---------------------------------------------------------------- live

def watch(folder, guide=None, say=print, poll=5.0, sleep=time.sleep, once=False):
    """A line for each new frame, and a note only when what spoils the
    frames changes (or frames stop coming). Ctrl+C ends it."""
    seen, sizes, rows, state, last_new = set(), {}, [], None, time.time()
    name = dt.date.today().isoformat()
    for path in frames(folder):
        seen.add(path)                       # what was there before: the night so far is not re-said
    say(f"watching {folder}: {len(seen)} frames already there; nothing is sent to any device")
    while True:
        for path in frames(folder):
            if path in seen:
                continue
            size = path.stat().st_size
            if sizes.get(path) != size:      # still being written: measured once it stops growing
                sizes[path] = size
                continue
            seen.add(path)
            row = read_one(path)
            if "skip" in row:
                say(f"  {path.name} left out: {row['skip']}")
                continue
            if guide and row.get("start") and row.get("end"):
                row["guide"] = guide.during(row["start"], row["end"])
            rows.append(row)
            record([row], name)
            last_new = time.time()
            causes = judge(row, references(rows).get(setup(row)))
            sharp = f"FWHM {row['fwhm_arcsec']:.2f}″" if row.get("fwhm_arcsec") else \
                f"FWHM {row['fwhm_px']:.2f} px" if row.get("fwhm_px") else "no stars"
            guided = f", guide RMS {row['guide']['rms']}" if (row.get("guide") or {}).get("rms") is not None else ""
            say(f"{_clock(row.get('start'))} {row.get('object')} {row.get('filter')} {row.get('exposure') or 0:g} s: "
                f"{row.get('stars', 0)} stars, {sharp}{guided}" + (f"  [{', '.join(c for c, _, _ in causes)}]"
                                                                    if causes else ""))
            now = tuple(sorted(c for c, _, _ in causes))
            if now != state:
                if now == (UNASSESSABLE,):
                    # Too few frames of this setup yet to judge by: said once,
                    # and never followed by "good again" from it.
                    say("  NOTE: not judged yet: fewer than three frames of this setup with stars to compare with")
                elif causes:
                    say("  NOTE: " + "; ".join(f"{c}: {m}" + (f" (likely {i})" if i else "") for c, m, i in causes))
                elif state and state != (UNASSESSABLE,):
                    say("  NOTE: frames good again")
                elif state == (UNASSESSABLE,):
                    say("  NOTE: judged from here on: good so far")
                state = now
        expected = max(300.0, 3 * statistics.median([r["exposure"] for r in rows if r.get("exposure")] or [100]))
        if rows and time.time() - last_new > expected and state != ("stopped",):
            say(f"  NOTE: no new frame for {(time.time() - last_new) / 60:.0f} min")
            state = ("stopped",)
        if once:
            return rows
        sleep(poll)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["report", "watch", "check"])
    ap.add_argument("folder", nargs="?", help="where the capture program saves the night's frames (report: "
                                              "optional with --nina-log, for a night from the logs alone)")
    ap.add_argument("--phd2-log", nargs="+", metavar="FILE", help="PHD2's guide log(s) for the night")
    ap.add_argument("--nina-log", nargs="+", metavar="FILE", help="NINA's log(s) for the night")
    ap.add_argument("--night", metavar="YYYY-MM-DD", help="only the night that begins on this date (noon to noon)")
    ap.add_argument("--tz", metavar="ZONE", help="the zone the logs' local times are in, such as Europe/Rome "
                                                 "(default: this computer's)")
    ap.add_argument("--phd2", metavar="HOST:PORT", help="for watch: listen to PHD2's event server")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    global ZONE
    ZONE = args.tz
    if args.folder and not Path(args.folder).is_dir():
        sys.exit(f"No folder {args.folder}")
    if not args.folder and not (args.command == "report" and args.nina_log):
        sys.exit("A frames folder is needed (report can do without one given --nina-log)")
    guide = GuideLog(args.phd2_log) if args.phd2_log else None
    nina = NinaLog(args.nina_log) if args.nina_log else None
    if args.night and nina:
        nina.only(*night_span(args.night))
    if args.command == "watch":
        if args.phd2:
            guide = GuideLive(args.phd2)
        try:
            watch(args.folder, guide)
        except KeyboardInterrupt:
            pass
        return
    if args.command == "check":
        found = frames(args.folder)
        rows, left = gather(args.folder, paths=found[:20])
        print(f"{len(found)} files under {args.folder}; of the first {min(20, len(found))}: {len(rows)} light frames "
              f"it can measure, {len(left)} left out")
        for item in left[:5]:
            print(f"  {Path(item['file']).name}: {item['skip']}")
        if any("compression" in item["skip"] for item in left):
            print("  For NINA: Options > Imaging > Image file type FITS, or XISF with no compression or zlib.")
        row = rows[0] if rows else None
        if row:
            print("the first, as read:", {k: row.get(k) for k in ("object", "filter", "exposure", "gain", "sensor_c",
                                                                  "target_c", "focuser", "focuser_c", "scale", "stars")})
            missing = [k for k in ("start", "exposure", "scale") if row.get(k) is None]
            if missing:
                print("not in its header (the report does without):", ", ".join(missing))
        if guide:
            print(f"PHD2 log: {len(guide.steps)} guide steps, {len(guide.sessions)} guiding stretches, "
                  f"pixel scale {guide.scale or 'not given'}")
        return
    if not args.folder:
        lines = logs_only(nina, guide)
        print(json.dumps(lines, indent=1) if args.json else "\n".join(lines))
        return
    rows, left = gather(args.folder, guide, say=lambda line: print(line, file=sys.stderr))
    if args.night:
        span = night_span(args.night)
        rows = [r for r in rows if r.get("start") and span[0] <= r["start"] < span[1]]
    night = report(rows, guide, left, nina)
    if args.json:
        print(json.dumps({k: v for k, v in night.items() if k != "parts"}
                         | {"parts": {" | ".join(str(x) for x in key): p for key, p in night["parts"].items()}},
                         default=str, indent=1))
    else:
        print(words(night) + ("\n" + "\n".join(nina.summary()) if nina else ""))


if __name__ == "__main__":
    main()
