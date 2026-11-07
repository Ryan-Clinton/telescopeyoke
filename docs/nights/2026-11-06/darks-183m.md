# 183M long darks at -5 °C, 6 to 7 November 2026

Indoors, cap on, light off, the cooler's 12 V plugged in (the first try
ran with it unplugged: the cooler sat at 0 % for 14 minutes while the
sensor rose from 24.8 to 31 °C; stopped with no frames kept, and since
dd17d00 `altair.py` refuses after 2 minutes of that).

`./calibrate.py dark --exposure 120 300 --gain 1500`: 20 frames each at
-5 °C (gain 1500, offset 80, bin 1, speed 3), then the slow warm-up from
-4.5 °C (10 minutes, the cooler off near 22.5 °C). Masters:
`183m/calibration/dark-120s-…-t-5-v1.fits` (23:36) and
`dark-300s-…-t-5-v1.fits` (01:16).

No frame was lit: every frame's median was 79 to 88 ADU, no rise through
the run.

## Dark current at -5 °C

Medians of the centre 1600 x 2500 pixels of each master:

| Master | Median | Spread (std) | 99.9th percentile |
|---|---|---|---|
| 4 s | 78.4 | 1.8 | 84 |
| 16 s | 81.8 | 2.7 | 90 |
| 120 s | 82.6 | 7.1 | 119 |
| 300 s | 81.9 | 15.2 | 176 |

From 16 s to 300 s the typical pixel gained 0.1 ADU and the mean 0.6 ADU
(the mean carries the warm pixels): **at most about 0.002 ADU/s**, too
small to separate from the bias's own drift (120 s to 300 s came out
slightly negative). The warm pixels show in the spread and the tail:
0.14 % of pixels gained over 50 ADU in 300 s; the dark master and the
bad-pixel map take those out.

## Against the sky (M33, 5 November, 16 s, gain 1500)

Sky above the dark level: L 2.2 to 5 ADU/s, R 0.7, G 0.7, B 1.1 ADU/s.
The dark signal is about 0.3 % of the R or G sky, so it adds about 0.15 %
to the noise. For a 3 to 7 nm narrowband filter the sky would be roughly
15 to 30 times fainter than R (not yet measured: no Ha, SII or OIII
frames), so dark would be up to about 10 % of the sky and add up to
about 5 % to the noise.

## The case for -10 °C

For LRGB, none. For narrowband, at most a few per cent of signal to
noise (dark current roughly halves per 5 to 6 °C), and that only if the
narrowband sky turns out as faint as estimated. The warm pixels would
drop too, but the dark master removes them. Measure the sky in the first
Ha frames before deciding; -5 °C stays the target.
