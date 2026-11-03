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

Nothing here moves the mount or uses the camera, and nothing is written.
"""
import argparse
import io
import re
import math
from datetime import datetime, timedelta, timezone

import numpy as np
import requests
from urllib.parse import unquote

import interface

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
    return {"spectra": spectra, "fch1": fch1 + first * foff, "foff": foff, "tsamp": float(attrs["tsamp"]),
            "tstart": float(attrs.get("tstart", 0.0)), "target": str(attrs.get("source_name", "")),
            "fetched_mb": round(remote.fetched / 1e6, 1) if remote else None}


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
        spread = 1.4826 * np.median(np.abs(rest - np.median(rest))) or 1.0
        out[t] = rest / spread
    return out


def search(spectra, foff, tsamp, fch1, snr_min=SNR_MIN, max_drift=MAX_DRIFT, block=BLOCK):
    """The hits in one look: each drift line whose sum is snr_min times its
    noise, the best drift for each channel, neighbours merged. A hit's
    frequency is where it was at the start of the look."""
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
    over = np.flatnonzero(best >= snr_min)
    hits, taken = [], np.zeros(n_f, bool)
    for i in over[np.argsort(-best[over])]:
        if taken[i]:
            continue
        reach = abs(best_k[i]) + WINDOW_CHANNELS
        taken[max(0, i - reach):i + reach + 1] = True
        hits.append({"channel": int(i), "frequency_mhz": round(fch1 + i * foff, 6),
                     "drift_hz_s": round(best_k[i] * foff * 1e6 / span, 4) if span else 0.0,
                     "snr": round(float(best[i]), 1)})
    return hits


def look(source, low, high, say=print, read=read_slice):
    """`search` on one look's slice, read from a file here or on the web."""
    s = read(source, low, high)
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


def cadence(sources, low, high, say=print, read=read_slice):
    """The six looks searched, then judged together."""
    if len(sources) != 6:
        raise interface.Refusal("INVALID_REQUEST", "A cadence is six looks: ON, OFF, ON, OFF, ON, OFF.")
    scans, looks = [], []
    for k, source in enumerate(sources):
        answer, hits, s = look(source, low, high, say=lambda *_: None, read=read)
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


def run(args, say=print):
    if args.action == "find":
        if len(args.what) != 1:
            raise interface.Refusal("INVALID_REQUEST", "find takes one target, as Breakthrough Listen names it (KIC8462852).")
        return find(args.what[0], say=say)
    if args.low is None or args.high is None:
        raise interface.Refusal("INVALID_REQUEST", "Give the slice: --from MHZ --to MHZ (a few MHz at most: "
                                "each MHz is about 360,000 channels).")
    if args.action == "search":
        if len(args.what) != 1:
            raise interface.Refusal("INVALID_REQUEST", "search takes one look: a file here or its URL.")
        return look(args.what[0], args.low, args.high, say=say)[0]
    return cadence(args.what, args.low, args.high, say=say)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", choices=("find", "search", "cadence"))
    ap.add_argument("what", nargs="+", help="find: a target; search: one look (file or URL); cadence: six looks")
    ap.add_argument("--from", dest="low", type=float, help="MHz: the bottom of the slice")
    ap.add_argument("--to", dest="high", type=float, help="MHz: the top of the slice")
    ap.add_argument("--json", action="store_true", help="answer in JSON")
    args = ap.parse_args()
    interface.main("seti", lambda: run(args), args.json)


if __name__ == "__main__":
    main()
