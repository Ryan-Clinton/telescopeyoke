# 10 November 2026: first calibration kept, first guiding

## Calibration on Vega (Dec +38, west of the pier), gain 400 %, 2 s

| Run | West | East | North | Axes apart | Dec slack |
|---|---|---|---|---|---|
| 17:59 | 0.82 px/s | 0.65 px/s | 0.69 px/s | 85.0° | 11.7 ± 4.1 s |
| 18:15 | 0.80 px/s | 0.67 px/s | 0.72 px/s | 84.9° | 11.3 ± 3.8 s |

Camera angle -67°. Both "usable for guiding", short of the first night's
pass: RA guide rate 9.8–10.0"/s against the expected 7.1, and the Dec
slack may be longer than the reversals measured. The kept calibration's
3-step check failed twice (east brought the star back only to 1.2–1.4 px,
over 1.0), so `guide` recalibrated; east is slower than west, which fits.
A calibration in NGC 7789 (Dec +58, east) lost its star (SNR 6) in the
crowded field while both scopes still saw stars.

## Guiding, 18:18–18:28 on Vega

`./guidecam.py guide --gain 400 --exposure 2 --minutes 10`: 150 frames,
the star never lost. RA -1.8" mean, 2.0" SD; Dec +2.0" mean, 0.7" SD;
total RMS 3.45". The offsets are about 0.2 guide px (9.55"/px), against
a centroid wander of 0.13 px RMS with no pulses at all, so the guide
camera barely sees errors this small. Unguided drift was about 0.04 px/s
(about 20"/min).

The 3.45" total includes the mean offsets; the scatter about them alone
is about 2.1" (2.0" RA and 0.7" Dec SD combined). The offsets are the
first thing to understand (drift left uncorrected, a calibration bias, or
centroid noise at 9.55"/px) before any tuning of aggression or minimum
moves.

## First guided main-camera run: Eastern Veil (NGC 6992), Ha, 120 s

`shoot.py NGC6992 --blocks Ha:40,OIII:50 --guide --exposure 120
--focus-as-is`, from 18:52 (session `NGC6992/20261110-185205`), the 183M
at -5 °C, 0.73"/px. The guider recalibrated (about 5 minutes) because the
kept calibration's check failed again. The first five frames were all kept:
FWHM 4.2–5.1 px (3.1–3.7"), roundness 0.84–0.87, 258–300 stars. Guide RMS
0.97" at the start, 2.4–2.9" by 19:00–19:10. Plate solves through Ha
failed (too few stars in a short frame), so the run's re-centring left
the aim as it was.

So 120 s guided frames on this mount keep round stars. Not yet compared
with unguided 120 s frames, and no longer subs tried.

Changed after this: the kept calibration's check now allows for east
being slower than west by what the calibration measured, so a reuse need
not recalibrate (to be seen at the next run's start); a stop sent while a
run is starting is taken before its first exposure.
