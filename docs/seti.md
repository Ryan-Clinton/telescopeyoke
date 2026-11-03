# Radio SETI in Breakthrough Listen's open data

`seti.py` searches Breakthrough Listen's published radio recordings for
narrowband signals, in the spirit of SETI@home: a slice of the band at a
time, with the test that tells our own interference from a signal coming
from the target. It uses no telescope of ours; it runs on cloudy days.

## What the data are

Breakthrough Listen (seti.berkeley.edu/opendata) observes nearby stars with
the Green Bank Telescope, Parkes and others in cadences: three five-minute
looks at the target, each followed by a look at another star (ON, OFF, ON,
OFF, ON, OFF). The finest product of each look, `.gpuspec.0000.h5`, splits
the band into channels about 2.8 Hz wide, one spectrum every 18 seconds,
and is about 15 GB. The files are HDF5, stored in blocks and packed with
bitshuffle, so `seti.py` reads only the blocks of the slice asked for, over
the web with HTTP range requests (it needs `python3-h5py` and
`python3-hdf5plugin`, in `install.sh`).

## The commands

    ./seti.py find KIC8462852
    ./seti.py search URL --from 2250 --to 2253
    ./seti.py cadence ON1 OFF1 ON2 OFF2 ON3 OFF3 --from 2250 --to 2253

- `find` lists the target's finest looks by observing session, with the
  OFF looks of the same session between them where the archive lists them,
  and gives the `cadence` line for a whole cadence.
- `search` sums each look's spectra along every drift line up to 4 Hz a
  second either way (a transmitter on a turning, orbiting planet drifts)
  and keeps lines 10 times above the noise (turboSETI's default). The
  band's smooth shape is taken out first and the noise measured robustly
  (median and median absolute deviation), so the band's edges and a few
  bright signals do not make hits.
- `cadence` follows each hit of the first ON look to where its drift puts
  it in the later looks. Found in every ON look and no OFF look, it is a
  candidate; seen in any OFF look, interference; missing from an ON look,
  unconfirmed.

## What a candidate is

Nearly every hit is ours: satellites, radar, phones, the telescope's own
electronics. Interference comes in wherever the telescope points; a signal
from the target only while pointing at it, which is what the cadence
tests. A candidate is the start of the checking, not the end: it is
compared with known interference and with the published searches of the
same data (Breakthrough Listen's own papers list their candidates for
these targets). Every candidate examined so far has turned out to be ours.

## The sweep

`./seti.py sweep KIC8462852 --blocks N` searches the target's whole
cadence N blocks further than the runs before got, one block at a time:
each block is one chunk of the files (one coarse channel of 1,048,576
channels, 2.93 MHz), so a block is read in the fewest pieces. Tabby's
25 May 2017 cadence is 308 blocks, 1818 to 2721 MHz. Each block's answer
is kept (`cache/seti/TARGET-SESSION.json`), so the band is covered over
many cloudy days, and every candidate found in any block is listed with
it. The cloudy-day skill starts a few blocks each time.

## Checked against turboSETI

`./seti.py search` and `cadence` take `--keep DIR` to save each slice
they read (a small HDF5 file in Breakthrough Listen's own layout), and
`./seti.py benchmark FILE...` runs each saved slice through this search
and through turboSETI, Breakthrough Listen's own, at the same limits
(10 times the noise, drifts to 4 Hz/s), and lists what both find and
what only one does. turboSETI is not an Ubuntu package: it is installed
in its own environment that sees the system's h5py
(`python3 -m venv --system-site-packages ~/.local/share/telescopeyoke/seti-venv`,
then its `pip install turbo_seti`; `TY_TURBOSETI_PYTHON` names another).

On a made-up flat band with two tones (3 November 2026) both found both.
On a sloping band turboSETI found neither: it measures the noise over the
whole slice, band shape and all, where this search takes the band's
shape out first. That is a difference in method to be measured on real
data, not a fault in either.

## Tabby's star

KIC 8462852 was observed by Green Bank in May 2017, among other times;
`./seti.py find KIC8462852` lists them. The whole cadence is on 25 May
2017 (session AGBT17A_999_68, scans 31 to 36: three looks at the star,
each followed by one at KIC8462852_OFF); the archive files the OFF looks
under their own name, so `find` reads them from the session's folder. It is the
same star the telescope watches (`starwatch.py tabby`), so the optical and
radio searches look at one target.
