#!/usr/bin/env python3
"""A search for radio signals from other civilisations in Breakthrough
Listen's open data, as SETI@home did, one slice of the band at a time.

    ./seti.py find KIC8462852                         the observations of a target, by cadence
    ./seti.py search URL --from 2250 --to 2253        narrowband signals in one scan's slice
    ./seti.py cadence ON1 OFF1 ON2 OFF2 ON3 OFF3 --from 2250 --to 2253 --json

Breakthrough Listen (seti.berkeley.edu/opendata) publishes its telescopes'
recordings: Green Bank, Parkes and others, observed in cadences of three
five-minute looks at a target, each followed by a look at another star
(ON, OFF, ON, OFF, ON, OFF). The finest product of each look
(.gpuspec.0000.h5) splits the band into channels about 3 Hz wide, every
18 seconds; it is about 15 GB, so only the slice asked for is read, over
the web, block by block (HTTP range requests; h5py and hdf5plugin).

A transmitter on a planet drifts in frequency as the planet turns and
orbits. `search` adds each scan's spectra along every drift line up to
MAX_DRIFT Hz a second either way (one channel across the scan between
lines) and keeps each line SNR_MIN times above the noise: a hit. The
noise is measured robustly (the median and its absolute deviation, after
taking out the band's smooth shape) so a few bright signals do not hide
the rest.

`cadence` is the test that matters. Nearly every hit is interference from
our own world: satellites, radar, phones, the telescope's own electronics.
Interference comes in whatever the telescope points at; a signal from the
target comes in only while pointing at it. A hit counts as a candidate
only when it is found in all three ON looks, where its drift says it
should be, and in none of the OFF looks; one also seen OFF is labelled
interference, and one missing from an ON look unconfirmed. A candidate is
then something to check against known interference and the published
searches of the same data, never a signal from anyone: every candidate
Breakthrough Listen has examined so far has turned out to be ours.

`benchmark FILE...` runs the same slices (saved with --keep) through
turboSETI, Breakthrough Listen's own search, and sets the hits side by
side. Nothing here moves the mount or uses the camera; only --keep
writes, and only the slices.
"""
import argparse
import io
import json
import math
import os
import re
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote

import numpy as np
import requests

import config
import interface
import records

API = "https://seti.berkeley.edu/opendata/api/query-files"
FINE = ".gpuspec.0000.h5"       # the finest frequency product of a Green Bank look
SNR_MIN = 10.0                  # turboSETI's default: a hit is ten times the noise
MAX_DRIFT = 4.0                 # Hz a second either way: the Earth's own turning gives up to about 0.4 at 1-10 GHz
BLOCK = 1024                    # channels in each piece of the band's smooth shape taken out
WINDOW_CHANNELS = 3             # channels either way a hit may sit from where its drift puts it
CADENCE_DAYS = 0.06             # OFF looks within this long (about 1.5 hours) of the ON looks are the cadence's
MAX_LISTED = 100                # hits or events listed; the counts are of all of them
TIMEOUT = 120
READ_BUFFER = 1 << 22           # bytes asked for at a time over the web
HEADERS = {"User-Agent": "telescopeyoke/0.1 (personal SETI search of Breakthrough Listen open data)"}
MJD_UNIX = 40587.0              # the MJD of 1970-01-01


def _utc(mjd):
    return (datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(days=mjd - MJD_UNIX)).strftime("%Y-%m-%d %H:%M:%S")


# --- finding the observations ---------------------------------------------------

def _session(url):
    """The observing session a file belongs to: the folder after pipeline/."""
    parts = url.split("/")
    return parts[parts.index("pipeline") + 1] if "pipeline" in parts else parts[-2]


def _scan(row, on):
    return {"target": str(row["target"]).removeprefix("DIAG_"), "on": on, "mjd": row["mjd"], "utc": _utc(row["mjd"]), "url": row["url"],
            "size_gb": round(row["size"] / 1e9, 2), "centre_mhz": round(float(row["center_freq"]), 3),
            "telescope": row.get("telescope")}


def query(get=requests.get, **params):
    reply = get(API, params=params, timeout=TIMEOUT, headers=HEADERS)
    reply.raise_for_status()
    return reply.json().get("data") or []


_LOOK = re.compile(r'href="([^"]*guppi_(\d+)_(\d+)_(.+?)_(\d{4})\.gpuspec\.0000\.h5)"')


def _bare(name):
    """A target's name as compared: DIAG_ (a diagnostic look) taken off, any case."""
    return str(name).removeprefix("DIAG_").upper()


def folder(on, get=requests.get):
    """Every finest-resolution look in the session folder an ON look is in,
    from the server's own listing: its target from the file's name (DIAG_
    taken off), its time from the name's MJD and seconds, and the size and
    band of the ON look (the same receiver and set-up all session)."""
    base = on["url"].rsplit("/", 1)[0] + "/"
    reply = get(base, timeout=TIMEOUT, headers=HEADERS)
    reply.raise_for_status()
    out = []
    for name, mjd, seconds, target, _ in _LOOK.findall(reply.text):
        target = unquote(target).removeprefix("DIAG_")
        out.append(dict(on, target=target, mjd=int(mjd) + int(seconds) / 86400, url=base + name))
    return out


def find(target, get=requests.get, say=print):
    """The finest-resolution looks at `target`, by session, each session
    with the OFF looks taken between and after them where the archive lists
    them; `complete` when ON, OFF, ON, OFF, ON, OFF are all there."""
    # The archive matches the name anywhere (KIC8462852 brings KIC8462852_OFF
    # too) and files some looks as DIAG_ NAME: only the name itself is ON.
    rows = [r for r in query(get, target=target) if str(r.get("url", "")).endswith(FINE)
            and _bare(r["target"]) == _bare(target)]
    sessions = {}
    for r in rows:
        sessions.setdefault(_session(r["url"]), []).append(r)
    out = []
    for name, ons in sorted(sessions.items()):
        ons.sort(key=lambda r: r["mjd"])
        first, last = ons[0]["mjd"], ons[-1]["mjd"]
        # The archive is asked by target only, and an OFF look is filed under
        # its own target (KIC8462852_OFF, or another star), so the OFF looks
        # are read from the session's own folder: every look there between
        # and just after the ON looks that is not the target.
        try:
            near = folder(ons[0], get)
        except (requests.RequestException, ValueError):
            near = []
        offs = [r for r in near if _bare(r["target"]) != _bare(target)
                and first - CADENCE_DAYS <= r["mjd"] <= last + CADENCE_DAYS]
        scans = sorted([_scan(r, True) for r in ons] + [_scan(r, False) for r in offs], key=lambda s: s["mjd"])
        pattern = "".join("A" if s["on"] else "B" for s in scans)
        out.append({"session": name, "scans": scans, "complete": "ABABAB" in pattern,
                    "command": ("./seti.py cadence " + " ".join(s["url"] for s in scans[pattern.index("ABABAB"):][:6])
                                + f" --from {scans[0]['centre_mhz'] - 1:.3f} --to {scans[0]['centre_mhz'] + 1:.3f}")
                    if "ABABAB" in pattern else None})
    say(f"{len(rows)} finest-resolution looks at {target} in {len(out)} session(s)")
    for s in out:
        on = sum(sc["on"] for sc in s["scans"])
        say(f"  {s['session']}: {on} ON, {len(s['scans']) - on} OFF, {'a whole cadence' if s['complete'] else 'no whole cadence listed'}"
            f" ({s['scans'][0]['utc']} UTC, {s['scans'][0]['centre_mhz']:.0f} MHz, {s['scans'][0]['size_gb']:g} GB a look)")
    return {"target": target, "looks": len(rows), "sessions": out, "kind": "measured"}


# --- reading a slice ------------------------------------------------------------

class Remote(io.RawIOBase):
    """A file on the web read as if it were here: each read is one HTTP
    range request, so h5py fetches only the blocks a slice needs."""

    def __init__(self, url, get=requests.get, head=requests.head):
        self.url, self.get, self.pos, self.fetched = url, get, 0, 0
        self.size = int(head(url, timeout=TIMEOUT, allow_redirects=True, headers=HEADERS).headers["Content-Length"])

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=io.SEEK_SET):
        self.pos = offset if whence == io.SEEK_SET else self.pos + offset if whence == io.SEEK_CUR else self.size + offset
        return self.pos

    def readinto(self, buffer):
        if self.pos >= self.size:
            return 0
        end = min(self.pos + len(buffer), self.size) - 1
        reply = self.get(self.url, headers=dict(HEADERS, Range=f"bytes={self.pos}-{end}"), timeout=TIMEOUT)
        reply.raise_for_status()
        # Only the bytes asked for will do: a server that ignores the range
        # answers 200 with the file from its start, which read as the slice
        # would be wrong data with no error.
        expected = f"bytes {self.pos}-{end}/"
        if reply.status_code != 206 or not str(reply.headers.get("Content-Range", "")).startswith(expected):
            raise interface.Refusal("INTERNAL_ERROR", f"{self.url} did not answer the range asked for "
                                    f"({reply.status_code}, Content-Range {reply.headers.get('Content-Range')!r}).")
        data = reply.content
        if len(data) != end - self.pos + 1:
            raise interface.Refusal("INTERNAL_ERROR", f"{self.url} sent {len(data)} bytes for a range of "
                                    f"{end - self.pos + 1}.")
        buffer[:len(data)] = data
        self.pos += len(data)
        self.fetched += len(data)
        return len(data)


def _h5():
    try:
        import h5py
        import hdf5plugin  # noqa: F401  (the bitshuffle filter Breakthrough Listen's files are packed with)
    except ImportError:
        raise interface.Refusal("INVALID_REQUEST", "Reading Breakthrough Listen's files needs h5py and hdf5plugin: "
                                "sudo apt install python3-h5py python3-hdf5plugin (or pip install \".[seti]\").")
    return h5py


def channels(fch1, foff, nchans, low, high):
    """The channel range [first, last) covering low to high MHz."""
    a, b = sorted(((low - fch1) / foff, (high - fch1) / foff))
    first, last = max(0, int(math.floor(a))), min(nchans, int(math.ceil(b)) + 1)
    if first >= last:
        raise interface.Refusal("INVALID_REQUEST", f"{low:g} to {high:g} MHz is outside this file's band "
                                f"({min(fch1, fch1 + foff * nchans):.3f} to {max(fch1, fch1 + foff * nchans):.3f} MHz).")
    return first, last


def blank_dc(spectra, first, per):
    """Blank the receiver's spike at the middle of each coarse channel (the
    "DC bin": one channel of every `per`, made by the instrument, not the
    sky), with the mean of the channels either side. `first` is the slice's
    first channel in the whole file. Both this search and turboSETI found it
    at 2268.1641 and 1473.6328 MHz in Tabby's looks, each a coarse channel's
    middle (3 November 2026)."""
    n_f = spectra.shape[1]
    if per >= n_f + first or per < 4:
        centre = per // 2 - first
        spikes = [centre] if 0 < centre < n_f - 1 else []
    else:
        spikes = [c - first for c in range(per // 2, first + n_f, per) if first < c < first + n_f - 1]
    for c in spikes:
        spectra[:, c] = (spectra[:, c - 1] + spectra[:, c + 1]) / 2
    return spikes


def read_slice(source, low, high):
    """One look's spectra between low and high MHz: (time, channel) and its header."""
    h5py = _h5()
    remote = None
    if str(source).startswith(("http://", "https://")):
        remote = Remote(source)
        handle = io.BufferedReader(remote, buffer_size=READ_BUFFER)
    else:
        handle = source
    with h5py.File(handle, "r") as f:
        data = f["data"]
        attrs = {k: (v.decode() if isinstance(v, bytes) else v) for k, v in data.attrs.items()}
        fch1, foff, nchans = float(attrs["fch1"]), float(attrs["foff"]), int(attrs.get("nchans", data.shape[-1]))
        first, last = channels(fch1, foff, nchans, low, high)
        spectra = np.asarray(data[:, 0, first:last], dtype=np.float64)
        # A slice saved here keeps where it sat in its file and its coarse
        # channels' width, so its spikes are blanked in the same places.
        per = int(attrs.get("coarse_channel", (data.chunks or data.shape)[-1]))
        whole_first = int(attrs.get("first_channel", 0)) + first
    blank_dc(spectra, whole_first, per)
    return {"spectra": spectra, "fch1": fch1 + first * foff, "foff": foff, "tsamp": float(attrs["tsamp"]),
            "first_channel": whole_first, "coarse_channel": per,
            "tstart": float(attrs.get("tstart", 0.0)), "target": str(attrs.get("source_name", "")),
            "fetched_mb": round(remote.fetched / 1e6, 1) if remote else None}


def save(s, path):
    """A slice as a filterbank HDF5 file of the layout Breakthrough Listen's
    own files and its tools (blimpy, turboSETI) read: one `data` set of
    (time, 1, channel) float32 with the header as its attributes."""
    h5py = _h5()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n_t, n_f = s["spectra"].shape
    with h5py.File(path, "w") as f:
        f.attrs["CLASS"], f.attrs["VERSION"] = "FILTERBANK", "1.0"
        data = f.create_dataset("data", data=s["spectra"].astype(np.float32).reshape(n_t, 1, n_f))
        header = {"fch1": s["fch1"], "foff": s["foff"], "nchans": n_f, "tsamp": s["tsamp"], "tstart": s["tstart"],
                  "nbits": 32, "nifs": 1, "data_type": 1, "telescope_id": 6, "machine_id": 10,
                  "source_name": s["target"] or "unknown", "src_raj": 0.0, "src_dej": 0.0,
                  "az_start": 0.0, "za_start": 0.0, "ibeam": 0, "nbeams": 1,
                  "first_channel": s.get("first_channel", 0), "coarse_channel": s.get("coarse_channel", n_f)}
        for key, value in header.items():
            data.attrs[key] = value
    return path


# --- the search -----------------------------------------------------------------

def flatten(spectra, block=BLOCK):
    """Each spectrum over its own noise, with the band's smooth shape taken
    out: the median of each BLOCK channels, joined up, and the median
    absolute deviation of what is left. A narrow signal stands out of it."""
    n_t, n_f = spectra.shape
    out = np.empty_like(spectra)
    starts = np.arange(0, n_f, block)
    centres = np.minimum(starts + block / 2, n_f - 1)
    every = np.arange(n_f)
    for t in range(n_t):
        level = np.array([np.median(spectra[t, s:s + block]) for s in starts])
        if len(level) > 1:
            # Carried on to both ends along the slope of the blocks nearest them:
            # held flat there, a sloping band would leave a ramp that adds up to hits.
            xs = np.concatenate([[0.0], centres, [n_f - 1.0]])
            first = level[0] - (level[1] - level[0]) * centres[0] / (centres[1] - centres[0])
            last = level[-1] + (level[-1] - level[-2]) * (n_f - 1 - centres[-1]) / (centres[-1] - centres[-2])
            shape = np.interp(every, xs, np.concatenate([[first], level, [last]]))
        else:
            shape = np.full(n_f, level[0])
        rest = spectra[t] - shape
        # The noise too is measured block by block: near a coarse channel's
        # edges the band rolls off and the noise with it, and one figure for
        # the whole spectrum made hits of the quieter edges (3 November 2026,
        # Tabby's 2017 data: four of five hits only this search found).
        spread = np.array([1.4826 * np.median(np.abs(rest[a:a + block] - np.median(rest[a:a + block])))
                           for a in starts])
        spread[spread <= 0] = np.median(spread[spread > 0]) if (spread > 0).any() else 1.0
        if len(spread) > 1:
            noise = np.interp(every, centres, spread)
        else:
            noise = np.full(n_f, spread[0])
        out[t] = rest / noise
    return out


def search(spectra, foff, tsamp, fch1, snr_min=SNR_MIN, max_drift=MAX_DRIFT, block=BLOCK):
    """The hits in one look: each drift line whose sum is snr_min times its
    noise, the best drift for each channel, and only the strongest within
    the widest drift searched of it (as turboSETI keeps its top hits): one
    strong burst lights every drift line near it, and is one hit, not
    dozens. A hit's frequency is where it was at the start of the look."""
    n_t, n_f = spectra.shape
    flat = flatten(spectra, block)
    width_hz = abs(foff) * 1e6
    span = max(n_t - 1, 1) * tsamp
    most = int(max_drift * span / width_hz) if n_t > 1 else 0
    best, best_k = np.full(n_f, -np.inf), np.zeros(n_f, int)
    steps = np.arange(n_t) / max(n_t - 1, 1)
    for k in range(-most, most + 1):
        total = np.zeros(n_f)
        for t in range(n_t):
            total += np.roll(flat[t], -int(round(k * steps[t])))
        snr = total / math.sqrt(n_t)
        if k > 0:
            snr[n_f - k:] = -np.inf          # wrapped round the end of the slice
        elif k < 0:
            snr[:-k] = -np.inf
        better = snr > best
        best[better], best_k[better] = snr[better], k
    # The slice's ends: a drift line starting there runs off the slice, so
    # what lies within the widest drift of either end is not searched.
    edge = most + WINDOW_CHANNELS
    best[:edge] = best[n_f - edge:] = -np.inf
    over = np.flatnonzero(best >= snr_min)
    # One hit for each run of bright channels no further apart than the
    # widest drift: a burst of interference lights a wide run of them and is
    # one hit, not one for every drift line (turboSETI keeps one top hit in
    # each such window too).
    reach = most + WINDOW_CHANNELS
    hits, run = [], []
    for i in list(over) + [None]:
        if run and (i is None or i - run[-1] > reach):
            top = max(run, key=lambda c: best[c])
            hits.append({"channel": int(top), "frequency_mhz": round(fch1 + top * foff, 6),
                         "drift_hz_s": round(best_k[top] * foff * 1e6 / span, 4) if span else 0.0,
                         "snr": round(float(best[top]), 1), "width_channels": int(run[-1] - run[0] + 1)})
            run = []
        if i is not None:
            run.append(i)
    return hits


def look(source, low, high, say=print, read=read_slice, keep=None):
    """`search` on one look's slice, read from a file here or on the web;
    with `keep` (a folder) the slice is also saved there, for a second look
    or the benchmark, without reading it over the web again."""
    s = read(source, low, high)
    if keep:
        save(s, Path(keep) / (Path(str(source)).name.replace(".h5", "") + f"_{low:g}-{high:g}.h5"))
    hits = search(s["spectra"], s["foff"], s["tsamp"], s["fch1"])
    n_t, n_f = s["spectra"].shape
    answer = {"source": str(source), "target": s["target"], "from_mhz": low, "to_mhz": high, "channels": n_f,
              "channel_hz": round(abs(s["foff"]) * 1e6, 3), "spectra": n_t, "seconds": round(n_t * s["tsamp"], 1),
              "tstart": s["tstart"], "max_drift_hz_s": MAX_DRIFT, "snr_min": SNR_MIN, "fetched_mb": s["fetched_mb"],
              "hit_count": len(hits), "hits": sorted(hits, key=lambda h: -h["snr"])[:MAX_LISTED], "kind": "measured"}
    say(f"{s['target'] or source}: {n_f} channels of {answer['channel_hz']:g} Hz, {n_t} spectra over "
        f"{answer['seconds']:g} s; {len(hits)} hit(s) at {SNR_MIN:g} times the noise or more, drifts up to "
        f"±{MAX_DRIFT:g} Hz/s" + (f" ({s['fetched_mb']:g} MB read)" if s["fetched_mb"] else ""))
    for h in answer["hits"][:10]:
        say(f"  {h['frequency_mhz']:.6f} MHz  drift {h['drift_hz_s']:+.4f} Hz/s  SNR {h['snr']:g}")
    return answer, hits, s


def _near(hits, frequency, window_mhz, drift=None, drift_tolerance=None):
    for h in hits:
        if abs(h["frequency_mhz"] - frequency) <= window_mhz and (
                drift is None or abs(h["drift_hz_s"] - drift) <= drift_tolerance):
            return h
    return None


def judge(looks):
    """The ON, OFF, ON, OFF, ON, OFF test on six looks' hits. `looks` are
    (hits, tstart MJD, channel width Hz, seconds) in cadence order; each
    hit of the first ON look is followed to where its drift puts it in each
    later look. Found in every ON and no OFF: a candidate."""
    first_hits, t0, width_hz, seconds = looks[0]
    events = []
    for h in first_hits:
        drift = h["drift_hz_s"]
        tolerance = max(0.5 * abs(drift), 2 * width_hz / max(seconds, 1e-9))
        in_on, in_off = [True], []
        for j, (hits, tstart, _, secs) in enumerate(looks[1:], start=1):
            later = (tstart - t0) * 86400
            expected = h["frequency_mhz"] + drift * later / 1e6
            window = (WINDOW_CHANNELS * width_hz + abs(drift) * secs) / 1e6
            if j % 2:   # an OFF look: anything near where it should be, or where it started, is ours
                in_off.append(bool(_near(hits, expected, window) or _near(hits, h["frequency_mhz"], window)))
            else:
                in_on.append(bool(_near(hits, expected, window, drift, tolerance)))
        label = "interference" if any(in_off) else "candidate" if all(in_on) else "unconfirmed"
        events.append(dict(h, label=label, in_on=in_on, in_off=in_off))
    return events


def cadence(sources, low, high, say=print, read=read_slice, keep=None):
    """The six looks searched, then judged together."""
    if len(sources) != 6:
        raise interface.Refusal("INVALID_REQUEST", "A cadence is six looks: ON, OFF, ON, OFF, ON, OFF.")
    scans, looks = [], []
    for k, source in enumerate(sources):
        answer, hits, s = look(source, low, high, say=lambda *_: None, read=read, keep=keep)
        scans.append({"source": str(source), "target": s["target"], "on": k % 2 == 0, "hit_count": len(hits),
                      "fetched_mb": s["fetched_mb"]})
        looks.append((hits, s["tstart"], abs(s["foff"]) * 1e6, answer["seconds"]))
    events = judge(looks)
    count = {label: sum(e["label"] == label for e in events) for label in ("candidate", "interference", "unconfirmed")}
    note = ("A candidate is found in every ON look where its drift puts it and in no OFF look. It is then checked "
            "against known interference and the published searches of these data: a candidate is never a signal "
            "from anyone until all of that is done, and so far every one has been ours.")
    say(f"{low:g} to {high:g} MHz, {len(events)} hit(s) in the first ON look: {count['candidate']} candidate(s), "
        f"{count['interference']} seen in an OFF look too (interference), {count['unconfirmed']} not in every ON look")
    for e in [e for e in events if e["label"] == "candidate"][:10]:
        say(f"  candidate {e['frequency_mhz']:.6f} MHz  drift {e['drift_hz_s']:+.4f} Hz/s  SNR {e['snr']:g}")
    say(note)
    order = {"candidate": 0, "unconfirmed": 1, "interference": 2}
    return {"from_mhz": low, "to_mhz": high, "scans": scans, "candidates": count["candidate"],
            "interference": count["interference"], "unconfirmed": count["unconfirmed"],
            "events": sorted(events, key=lambda e: (order[e["label"]], -e["snr"]))[:MAX_LISTED],
            "note": note, "kind": "measured"}


# --- the sweep: a cadence searched block by block, carried on from run to run -----

def blocks(source):
    """The file's blocks as (from, to) MHz, lowest first: each is one chunk
    of its HDF5 data (for Green Bank's finest product, one coarse channel of
    1,048,576 channels, 2.93 MHz), so a slice that keeps inside one is read
    in the fewest pieces. A channel is left off each side of a block."""
    h5py = _h5()
    handle = io.BufferedReader(Remote(source), buffer_size=1 << 16) if str(source).startswith("http") else source
    with h5py.File(handle, "r") as f:
        data = f["data"]
        fch1, foff = float(data.attrs["fch1"]), float(data.attrs["foff"])
        nchans, per = data.shape[-1], (data.chunks or data.shape)[-1]
    out = []
    for start in range(0, nchans, per):
        a, b = fch1 + (start + 1) * foff, fch1 + (min(start + per, nchans) - 2) * foff
        out.append((round(min(a, b), 6), round(max(a, b), 6)))
    return sorted(out)


def sweep_store(target, session):
    return config.DATA / "cache" / "seti" / f"{target}-{session}.json"


def sweep(target, count=1, say=print, get=requests.get, run_cadence=None, block_list=None):
    """Search the target's first whole cadence `count` blocks further than
    the runs before got, keeping each block's answer, so the whole band is
    covered over many runs (cloudy days): what is done, and every candidate
    found so far."""
    found = find(target, get=get, say=lambda *_: None)
    session = next((s for s in found["sessions"] if s["complete"]), None)
    if not session:
        raise interface.Refusal("INVALID_REQUEST", f"No whole ON-OFF cadence of {target} is listed.")
    pattern = "".join("A" if sc["on"] else "B" for sc in session["scans"])
    urls = [sc["url"] for sc in session["scans"][pattern.index("ABABAB"):][:6]]
    path = sweep_store(target, session["session"])
    kept = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"blocks": None, "done": {}}
    if not kept["blocks"]:
        kept["blocks"] = [list(b) for b in (block_list or blocks(urls[0]))]
    run_cadence = run_cadence or (lambda low, high: cadence(urls, low, high, say=lambda *_: None))
    todo = [k for k in range(len(kept["blocks"])) if str(k) not in kept["done"]][:count]
    for k in todo:
        low, high = kept["blocks"][k]
        answer = run_cadence(low, high)
        kept["done"][str(k)] = {"from_mhz": low, "to_mhz": high, "candidates": answer["candidates"],
                                "interference": answer["interference"], "unconfirmed": answer["unconfirmed"],
                                "events": [e for e in answer["events"] if e["label"] == "candidate"],
                                "searched": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        path.parent.mkdir(parents=True, exist_ok=True)
        records.write(path, kept)
        say(f"  block {k + 1} of {len(kept['blocks'])}, {low:.3f} to {high:.3f} MHz: {answer['candidates']} "
            f"candidate(s), {answer['interference']} interference, {answer['unconfirmed']} unconfirmed")
    done = kept["done"]
    candidates = [dict(e, block=int(k)) for k, d in done.items() for e in d["events"]]
    covered = sum(d["to_mhz"] - d["from_mhz"] for d in done.values())
    say(f"{target}, session {session['session']}: {len(done)} of {len(kept['blocks'])} blocks searched "
        f"({covered:.1f} MHz), {len(candidates)} candidate(s) so far")
    return {"target": target, "session": session["session"], "blocks": len(kept["blocks"]), "searched": len(done),
            "searched_mhz": round(covered, 3), "this_run": [kept["done"][str(k)] | {"block": k} for k in todo],
            "candidates_so_far": candidates[:MAX_LISTED], "kind": "measured"}


# --- completeness: signals planted in real noise ---------------------------------

INJECT_SNRS = (10, 12, 15, 20, 30, 50)   # the strengths planted, in times the noise of the summed line
INJECT_COUNT = 40                        # signals planted at each strength


def plant(spectra, tones, tsamp, width_hz):
    """`spectra` with drifting tones added: (channel at the start, drift Hz/s,
    height in raw units a spectrum), each on its nearest channel in time."""
    out = spectra.copy()
    for channel, drift, height in tones:
        for t in range(out.shape[0]):
            # foff is negative: a rising frequency moves to lower channels
            at = int(round(channel - drift * t * tsamp / width_hz))
            if 0 <= at < out.shape[1]:
                out[t, at] += height
    return out


def inject(path, snrs=INJECT_SNRS, count=INJECT_COUNT, seed=0, say=print, read=read_slice):
    """How complete the search is, and how clean, in a real look's own noise:
    `count` drifting signals of each strength in `snrs` planted at random
    places and drifts (away from the slice's ends and its own hits), the
    look searched again, and each planted signal counted found when a hit
    lies within its drift's reach with its drift within two steps. Hits
    that are neither planted nor in the look before are false."""
    s = read(path, -1e12, 1e12)
    spectra, foff, tsamp, fch1 = s["spectra"], s["foff"], s["tsamp"], s["fch1"]
    n_t, n_f = spectra.shape
    width_hz, span = abs(foff) * 1e6, max(n_t - 1, 1) * tsamp
    most = int(MAX_DRIFT * span / width_hz)
    reach, step = most + WINDOW_CHANNELS, width_hz / span
    before = search(spectra, foff, tsamp, fch1)
    sigma = float(np.median(np.abs(np.diff(spectra, axis=1)))) / (0.6745 * math.sqrt(2))   # a spectrum's noise
    rng = np.random.default_rng(seed)
    rows = []
    for snr in snrs:
        busy = [h["channel"] for h in before]
        tones = []
        for _ in range(200 * count):              # random places, each clear of the others
            if len(tones) == count:
                break
            c = int(rng.integers(2 * reach, n_f - 2 * reach))
            if all(abs(c - b) > 2 * reach for b in busy):
                drift = float(rng.uniform(-0.9, 0.9) * MAX_DRIFT)
                tones.append((c, drift, snr * sigma / math.sqrt(n_t)))
                busy.append(c)
        hits = search(plant(spectra, tones, tsamp, width_hz), foff, tsamp, fch1)
        found, errors, used = 0, [], set()
        for c, drift, _ in tones:
            h = next((h for h in hits if abs(h["channel"] - c) <= reach and id(h) not in used
                      and abs(h["drift_hz_s"] - drift) <= 2 * step + 0.05 * abs(drift)), None)
            if h:
                found += 1
                used.add(id(h))
                errors.append(abs(h["drift_hz_s"] - drift))
        old = [h for h in hits if any(abs(h["channel"] - b["channel"]) <= reach for b in before)]
        false = len(hits) - len(used) - len(old)
        planted = len(tones)
        rows.append({"snr": snr, "planted": planted, "found": found, "completeness": round(found / max(planted, 1), 3),
                     "drift_error_hz_s": round(float(np.median(errors)), 4) if errors else None,
                     "false_hits": max(false, 0)})
        say(f"  SNR {snr:>3}: {found} of {planted} found ({100 * found / max(planted, 1):.0f}%), "
            f"drift off by {rows[-1]['drift_error_hz_s']} Hz/s at the median, {rows[-1]['false_hits']} false")
    say(f"{Path(str(path)).name}: {len(before)} hit(s) of its own; signals planted in its noise, {count} at each strength")
    return {"file": str(path), "own_hits": len(before), "injected": rows, "max_drift_hz_s": MAX_DRIFT,
            "snr_min": SNR_MIN, "kind": "measured"}


# --- the benchmark: the same slices through turboSETI ----------------------------
# turboSETI (github.com/UCBerkeleySETI/turbo_seti) is Breakthrough Listen's
# own narrowband search. It is not an Ubuntu package, so it lives in its own
# environment that sees the system's h5py (install.sh, the seti extra);
# TURBOSETI_PYTHON is that environment's python.
TURBOSETI_PYTHON = Path(os.environ.get("TY_TURBOSETI_PYTHON",
                                       Path.home() / ".local/share/telescopeyoke/seti-venv/bin/python"))
_TURBO = """
import sys
from turbo_seti.find_doppler.find_doppler import FindDoppler
FindDoppler(sys.argv[1], max_drift=float(sys.argv[2]), snr=float(sys.argv[3]), out_dir=sys.argv[4],
            n_coarse_chan=1, log_level_int=40).search()
"""


def read_dat(text):
    """turboSETI's hits from its .dat table: frequency (MHz), drift (Hz/s), SNR."""
    out = []
    for line in text.splitlines():
        cols = line.split()
        if not cols or line.lstrip().startswith("#") or not cols[0].isdigit():
            continue
        out.append({"drift_hz_s": float(cols[1]), "snr": float(cols[2]), "frequency_mhz": float(cols[3])})
    return out


def turboseti(path, run_it=subprocess.run):
    """turboSETI's hits on a slice file, at the same limits as ours."""
    if not TURBOSETI_PYTHON.exists():
        raise interface.Refusal("INVALID_REQUEST", f"turboSETI is not installed: python3 -m venv "
                                f"--system-site-packages {TURBOSETI_PYTHON.parent.parent} && "
                                f"{TURBOSETI_PYTHON.parent}/pip install turbo_seti")
    with tempfile.TemporaryDirectory() as out:
        done = run_it([str(TURBOSETI_PYTHON), "-c", _TURBO, str(path), str(MAX_DRIFT), str(SNR_MIN), out],
                      capture_output=True, text=True, timeout=3600)
        if done.returncode:
            raise interface.Refusal("INTERNAL_ERROR", f"turboSETI failed on {path}: {done.stderr.strip()[-400:]}")
        dat = next(Path(out).glob("*.dat"), None)
        return read_dat(dat.read_text()) if dat else []


def compare(ours, theirs, width_hz, seconds):
    """Hits matched between the two searches: the same place within a few
    channels and the drift's smear, and the drift within one step."""
    step = width_hz / max(seconds, 1e-9)
    matched, theirs_left = [], list(theirs)
    for h in ours:
        window = (WINDOW_CHANNELS * width_hz + abs(h["drift_hz_s"]) * seconds) / 1e6
        twin = next((t for t in theirs_left if abs(t["frequency_mhz"] - h["frequency_mhz"]) <= window
                     and abs(t["drift_hz_s"] - h["drift_hz_s"]) <= 2 * step), None)
        if twin:
            theirs_left.remove(twin)
            matched.append({"ours": h, "turboseti": twin})
    only_ours = [h for h in ours if not any(m["ours"] is h for m in matched)]
    return {"both": len(matched), "only_ours": only_ours, "only_turboseti": theirs_left, "matched": matched}


def benchmark(paths, say=print, turbo=turboseti):
    """Each saved slice searched by this program and by turboSETI, and the
    hits set side by side: what both find, and what only one does."""
    out = []
    for path in paths:
        s = read_slice(path, -1e12, 1e12)
        n_t, n_f = s["spectra"].shape
        seconds = n_t * s["tsamp"]
        ours = search(s["spectra"], s["foff"], s["tsamp"], s["fch1"])
        theirs = turbo(path)
        # turboSETI reads the file as saved, spike and all; a hit of its on a
        # coarse channel's middle, which this search blanks, is set aside.
        n_t, n_f = s["spectra"].shape
        middles = [s["fch1"] + c * s["foff"] for c in range(n_f)
                   if (s.get("first_channel", 0) + c) % s.get("coarse_channel", n_f + 1) == s.get("coarse_channel", 0) // 2]
        spike = [t for t in theirs if any(abs(t["frequency_mhz"] - m) <= 2 * abs(s["foff"]) for m in middles)]
        theirs = [t for t in theirs if t not in spike]
        c = compare(ours, theirs, abs(s["foff"]) * 1e6, seconds)
        out.append({"file": str(path), "target": s["target"], "ours": len(ours), "turboseti": len(theirs),
                    "turboseti_on_dc_spike": len(spike),
                    "both": c["both"], "only_ours": c["only_ours"][:MAX_LISTED],
                    "only_turboseti": c["only_turboseti"][:MAX_LISTED]})
        say(f"{Path(path).name}: ours {len(ours)}, turboSETI {len(theirs)}, both {c['both']}, "
            f"only ours {len(c['only_ours'])}, only turboSETI {len(c['only_turboseti'])}")
    return {"benchmark": out, "max_drift_hz_s": MAX_DRIFT, "snr_min": SNR_MIN, "kind": "measured"}


def run(args, say=print):
    if args.action == "find":
        if len(args.what) != 1:
            raise interface.Refusal("INVALID_REQUEST", "find takes one target, as Breakthrough Listen names it (KIC8462852).")
        return find(args.what[0], say=say)
    if args.action == "sweep":
        if len(args.what) != 1:
            raise interface.Refusal("INVALID_REQUEST", "sweep takes one target (KIC8462852).")
        return sweep(args.what[0], args.blocks, say=say)
    if args.action == "inject":
        return [inject(p, say=say) for p in args.what][-1] if len(args.what) == 1 else \
            {"files": [inject(p, say=say) for p in args.what], "kind": "measured"}
    if args.action == "benchmark":
        return benchmark(args.what, say=say)
    if args.low is None or args.high is None:
        raise interface.Refusal("INVALID_REQUEST", "Give the slice: --from MHZ --to MHZ (a few MHz at most: "
                                "each MHz is about 360,000 channels).")
    if args.action == "search":
        if len(args.what) != 1:
            raise interface.Refusal("INVALID_REQUEST", "search takes one look: a file here or its URL.")
        return look(args.what[0], args.low, args.high, say=say, keep=args.keep)[0]
    return cadence(args.what, args.low, args.high, say=say, keep=args.keep)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", choices=("find", "search", "cadence", "sweep", "benchmark", "inject"))
    ap.add_argument("what", nargs="+", help="find: a target; search: one look (file or URL); cadence: six looks")
    ap.add_argument("--from", dest="low", type=float, help="MHz: the bottom of the slice")
    ap.add_argument("--to", dest="high", type=float, help="MHz: the top of the slice")
    ap.add_argument("--blocks", type=int, default=1, help="sweep: blocks of 2.9 MHz to search this run (default 1)")
    ap.add_argument("--keep", help="search, cadence: save each slice read in this folder (for benchmark)")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("seti", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
