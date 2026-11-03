"""The radio search: a drifting tone is found with its drift, the band's
shape and the noise do not make hits, and of six looks a tone in the ON
looks only is a candidate while one in every look is interference.
Synthetic spectra: nothing touches the network or needs h5py."""
import numpy as np
import pytest

import interface
import seti

WIDTH_HZ = 2.79           # Green Bank's finest channels
FOFF = -WIDTH_HZ / 1e6    # MHz a channel, falling as Breakthrough Listen's files do
TSAMP = 18.25             # seconds a spectrum
FCH1 = 2250.0
N_T, N_F = 16, 4096


def spectra(tones=(), seed=0, n_t=N_T):
    """Noise on a sloping band, with tones (channel at the start, drift Hz/s, height in noise units)."""
    rng = np.random.default_rng(seed)
    band = 100 + 20 * np.linspace(0, 1, N_F)
    out = band + rng.normal(0, 1, (n_t, N_F))
    for channel, drift, height in tones:
        for t in range(n_t):
            # foff is negative: a rising frequency moves to lower channels
            at = channel - drift * t * TSAMP / WIDTH_HZ
            out[t, int(round(at))] += height
    return out


def test_a_drifting_tone_is_found_with_its_drift_and_the_band_and_noise_are_not():
    hits = seti.search(spectra([(2000, 0.5, 8.0)]), FOFF, TSAMP, FCH1)
    assert len(hits) == 1
    h = hits[0]
    assert h["channel"] == 2000 and h["frequency_mhz"] == pytest.approx(FCH1 + 2000 * FOFF)
    assert h["drift_hz_s"] == pytest.approx(0.5, abs=0.02) and h["snr"] > 25     # 8 x sqrt(16)
    assert seti.search(spectra(seed=3), FOFF, TSAMP, FCH1) == []


def test_a_drift_beyond_the_limit_is_not_looked_for():
    # Searched only to 0.2 Hz/s, a tone drifting 0.5 is smeared over channels: never its full 32 times the noise.
    hits = seti.search(spectra([(2000, 0.5, 8.0)]), FOFF, TSAMP, FCH1, max_drift=0.2)
    assert all(abs(h["drift_hz_s"]) <= 0.2 and h["snr"] < 25 for h in hits)


def looks(on_tone, off_tone=None):
    """Six looks five minutes apart: the tone in the ON looks where its drift
    takes it; off_tone (if any) in every look."""
    out = []
    for k in range(6):
        tstart = 57895.0 + k * 330 / 86400
        tones = []
        channel, drift, height = on_tone
        later = channel - drift * k * 330 / WIDTH_HZ
        if k % 2 == 0:
            tones.append((later, drift, height))
        if off_tone:
            tones.append(off_tone)
        out.append({"spectra": spectra(tones, seed=k), "fch1": FCH1, "foff": FOFF, "tsamp": TSAMP,
                    "tstart": tstart, "target": "KIC8462852" if k % 2 == 0 else f"OFF{k}", "fetched_mb": None})
    return out


def test_a_tone_in_every_on_look_and_no_off_look_is_a_candidate_and_one_in_all_is_interference():
    made = looks((3000, 0.3, 8.0), off_tone=(1000, 0.0, 9.0))
    read = lambda source, low, high: made[int(source)]       # noqa: E731
    answer = seti.cadence([str(k) for k in range(6)], 2249.99, 2250.0, say=lambda *_: None, read=read)
    labels = {round(e["frequency_mhz"], 4): e["label"] for e in answer["events"]}
    assert labels[round(FCH1 + 3000 * FOFF, 4)] == "candidate"
    assert labels[round(FCH1 + 1000 * FOFF, 4)] == "interference"
    assert answer["candidates"] == 1 and answer["interference"] == 1
    assert "never a signal" in answer["note"]
    assert [s["on"] for s in answer["scans"]] == [True, False, True, False, True, False]


def test_a_tone_missing_from_an_on_look_is_unconfirmed():
    made = looks((3000, 0.3, 8.0))
    made[4] = dict(made[4], spectra=spectra(seed=99))             # the third ON look without it
    answer = seti.cadence([str(k) for k in range(6)], 2249.99, 2250.0, say=lambda *_: None,
                          read=lambda source, low, high: made[int(source)])
    assert [e["label"] for e in answer["events"]] == ["unconfirmed"]


def test_a_cadence_is_six_looks_and_a_slice_must_be_inside_the_band():
    with pytest.raises(interface.Refusal):
        seti.cadence(["a", "b"], 1, 2, say=lambda *_: None)
    assert seti.channels(FCH1, FOFF, N_F, FCH1 + 100 * FOFF, FCH1 + 10 * FOFF) == (10, 101)
    with pytest.raises(interface.Refusal):
        seti.channels(FCH1, FOFF, N_F, 3000, 3001)


class Reply:
    def __init__(self, body, text=""):
        self.body, self.text = body, text

    def json(self):
        return self.body

    def raise_for_status(self):
        pass


def row(target, mjd, scan, session="AGBT17A_999_67"):
    return {"target": target, "mjd": mjd, "size": 15561148516, "center_freq": 2269.6, "telescope": "GBT",
            "url": f"https://bldata.berkeley.edu/pipeline/{session}/holding/"
                   f"spliced_blc20_guppi_57895_{int(round((mjd - 57895) * 86400))}_DIAG_{target}_{scan:04d}.gpuspec.0000.h5"}


def listing(rows):
    """A session folder's page, as the server lists it."""
    return "".join(f'<a href="{r["url"].rsplit("/", 1)[1]}">x</a>' for r in rows)


def test_find_groups_the_looks_by_session_and_puts_the_off_looks_between():
    ons = [row("KIC8462852", 57895.420 + k * 0.0076, k) for k in (0, 2, 4)]
    offs = [row("KIC8462852_OFF", 57895.420 + k * 0.0076, k) for k in (1, 3, 5)]
    later = [row("HIP9", 57896.5, 9)]                       # the same folder, a day on: not this cadence
    coarse = dict(ons[0], url=ons[0]["url"].replace("0000.h5", "0002.h5"))

    def get(url, params=None, timeout=None, headers=None):
        if params:                                       # the archive, asked by target: it matches the name anywhere
            return Reply({"data": [dict(r, target="DIAG_" + r["target"]) for r in ons + offs] + [coarse]})
        return Reply(None, listing(ons + offs + later))  # the session's folder
    answer = seti.find("KIC8462852", get=get, say=lambda *_: None)
    assert answer["looks"] == 3
    s = answer["sessions"][0]
    assert [sc["on"] for sc in s["scans"]] == [True, False, True, False, True, False]
    assert [sc["target"] for sc in s["scans"]][:2] == ["KIC8462852", "KIC8462852_OFF"]
    assert s["complete"] and s["command"].startswith("./seti.py cadence ") and "HIP9" not in s["command"]
    assert s["scans"][0]["size_gb"] == 15.56


class Ranged:
    """A server's answer to a range request."""
    def __init__(self, status, body, content_range):
        self.status_code, self.content, self.headers = status, body, {"Content-Range": content_range}

    def raise_for_status(self):
        pass


def test_the_remote_reader_takes_only_the_bytes_it_asked_for():
    import pytest
    blob = bytes(range(256)) * 4
    head = lambda *a, **k: type("H", (), {"headers": {"Content-Length": str(len(blob))}})()   # noqa: E731

    def honest(url, headers=None, timeout=None):
        lo, hi = (int(x) for x in headers["Range"][6:].split("-"))
        return Ranged(206, blob[lo:hi + 1], f"bytes {lo}-{hi}/{len(blob)}")
    r = seti.Remote("https://x/f.h5", get=honest, head=head)
    r.seek(100)
    assert r.read(10) == blob[100:110]

    def ignores_range(url, headers=None, timeout=None):     # 200 and the file from its start
        return Ranged(200, blob, "")
    r = seti.Remote("https://x/f.h5", get=ignores_range, head=head)
    r.seek(100)
    with pytest.raises(interface.Refusal):
        r.read(10)

    def short(url, headers=None, timeout=None):
        lo, hi = (int(x) for x in headers["Range"][6:].split("-"))
        return Ranged(206, blob[lo:hi - 3], f"bytes {lo}-{hi}/{len(blob)}")
    r = seti.Remote("https://x/f.h5", get=short, head=head)
    with pytest.raises(interface.Refusal):
        r.read(10)
