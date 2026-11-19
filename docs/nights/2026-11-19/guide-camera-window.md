# 19 November 2026: guide camera full-size frames, and a full-resolution window

Please review the test, the conclusions and the plan below. Say where the
reasoning is wrong, what was missed, and what you would test next.

## The kit

- Guide camera: Altair GPCAM MT9M034M, an early version (mono, 1280 x 960,
  3.75 µm pixels, USB 2, ID `16d0:0b2a`, ST4 port). No current Altair or
  ToupTek library opens it, on Linux or Windows. The only one that does is
  oaCapture's `libaltaircamlegacy` 1.24.11330 (Linux amd64).
- On an Orion Mini 50 mm guide scope, 162 mm focal length: 4.77"/px at
  full size, 9.55"/px binned 2 x 2.
- An Ubuntu laptop. Our own Python code calls the library through ctypes
  (`guidecam.py` in github.com/Ryan-Clinton/telescopeyoke). Pull mode with
  a callback: `StartPullModeWithCallback`, then `PullImage` polled every
  10 ms. This library answers E_FAIL while no frame is ready, so E_FAIL is
  treated as "not yet"; any other code is kept.
- Mount: Sky-Watcher EQ3 Pro, guided through the camera's ST4 port.

## Why full size matters

The guider uses binned 640 x 480 frames, at 9.55"/px, because full size
drops frames (found 6 November 2026). Last night's guiding, binned, gave
RA 2.03" RMS and Dec 9.23" RMS. The mount was just serviced, and the aim
is about 0.7" RMS, which is 0.07 of a binned pixel. To measure guiding
near that, we want full resolution.

## What was already known (6 November)

- Full size streams badly on hubs and on the laptop's own port alike: at
  0.1 s, bursts of 2 or 3 frames then a gap of about 3.2 s; at 2 s, one
  frame every 13 to 18 s.
- Ruled out then: the hubs, USB autosuspend, the USB speed setting (0 and
  4), video vs software trigger mode, exposure range (0.18 ms to 800 s
  allowed), link speed (480M), `usbfs_memory_mb` (16 → 200 MB), the
  library's conversion (raw mode). The library's events show only
  "image": no error, no "no frame timeout", no "no packet timeout". No
  USB errors in the kernel log.
- What cured it: `put_eSize(1)` (640 x 480, which the library says is
  2 x 2 binning, not a crop) at USB speed 0. That gave 149 of 150 2 s
  frames in 5 minutes, and 14,399 of 14,400 overnight.
- Others report the same with early GPCAMs (Webastro, PHD2 forum), on
  Windows too: worked on older PCs, failed on newer laptops. No fix was
  confirmed.

## Today's test (19 November 2026)

- Daylight, cap on (frame levels about 2.2 of 255).
- Camera straight into a laptop USB socket, at 480M, no hub. The 183M
  main camera was on its own USB 3 port; the filter wheel and focuser
  Arduino were on a separate hub chain.
- `./guidecam.py probe`: opens the camera, sets the exposure, empties the
  queue, then counts frames for a fixed window. A new option, `--roi
  WxH`, calls `put_Roi` (centred, even numbers) before the stream starts.
  One run per row.

| Frames | 0.01 s | 0.1 s | 0.25 s | 0.5 s (20 s) | 2 s (20 s) |
|---|---|---|---|---|---|
| Binned 640 x 480, speed 4 | | | | 39, gaps ≤ 0.63 s | 10 of 10 |
| Full 1280 x 960, speed 4 | 24 in 15 s | 16 in 15 s | 2 in 15 s | 5, gaps up to 10 s | 0 |
| Full, software trigger | | | | 3 | 0 |
| Full, raw | | | | 1 | 1 |
| Full, speed 0 | | | | 2 | 0 |
| Full, trigger + raw | | | | 2 | 0 |
| **Window 320 x 240, full resolution** | | | | **39, gaps ≤ 0.61 s** | **10 of 10**; a second run 5 of 5 in 12 s |
| Window 480 x 360, full resolution | | | | | 5, one gap of 10 s |
| Window 640 x 480, full resolution | | | | 17, gaps up to 4.5 s | 1 |

The frames that arrived were checked to be 320 x 240 and 480 x 360.
`get_Size` still reports 1280 x 960 after `put_Roi`.

## Our conclusions (revised after the second set of tests, below)

1. Full size fails as before, in every mode, at every exposure, at both
   USB speeds, with no hub. So it isn't the hub, the port or the exposure.
2. A 640 x 480 window fails where 640 x 480 binned works: the number of
   pixels sent alone does not explain it. The cause is not known. The
   second set of tests points at the window's **width** at full
   resolution, not its height, its pixel count or its position (below);
   why is not known (the sensor's line timing, the camera's firmware or
   the library could each do it).
3. A 320 pixel wide window at full resolution streams every frame, as
   well as the binned mode does over 5 minutes at USB speed 0.

## Second set of tests (19 November 2026, afternoon)

Same set-up (cap on, laptop socket, no hub), USB speed 4 unless said,
20 s per exposure. The probe now counts the wait after the last frame as
a gap, counts frames whose bytes repeat the one before (a stale buffer;
even capped, new frames' noise differs), sets and checks the USB speed's
return code, and takes the window's corner (`--roi-at X,Y`).

| Window (full resolution) | Pixels | 0.5 s | 2 s |
|---|---|---|---|
| 320 x 360 | 115,200 | 39, gaps ≤ 0.61 s | 10 of 10 |
| 480 x 240 | 115,200 | 5, gaps up to 8.5 s | 2 |
| 480 x 360 at y 296 | 172,800 | 6 | 0 |
| 480 x 360 at y 300 | 172,800 | 3 | 2 |
| 480 x 360 at y 304 | 172,800 | 9 | 2 |
| 320 x 240 at the top left corner (0, 0) | 76,800 | 38, gaps ≤ 0.99 s | 10 of 10 |
| 320 x 240 at the bottom right (960, 720) | 76,800 | 39, gaps ≤ 0.60 s | 10 of 10 |

No repeated frames in any run.

- 320 x 360 and 480 x 240 have the same number of pixels: the taller,
  narrower one streams, the wider one does not. Width decides it, not
  pixel count or rows.
- 480 x 360 fails at all three vertical offsets: no sign of an
  alignment rule beyond even numbers.
- 320 x 240 streams at the middle and at both corners: position does
  not matter.

Five minutes, 320 x 240 in the middle, 2 s exposures (150 expected):

| USB speed | Frames | Longest gap | Repeated |
|---|---|---|---|
| 0 | **149** | 2.03 s | 0 |
| 4 | 148 | 4.00 s (one) | 0 |

At speed 0 that matches the binned baseline over the same 5 minutes
(149 of 150, gaps up to 2.08 s, 6 November). The binned mode's real
record is 14,399 of 14,400 over 8 hours; the window has not run that
long.

What the library offers (its exports, checked with `nm`): no frame
number or hardware timestamp (no `PullImageV2` or frame metadata, no
`get_FinalSize`), so lateness can only be judged by arrival times.
Untried: push mode (`StartPushMode`), `put_RealTime` (hand over only the
newest frame), `Flush`, `get_FrameRate`, and `put_Option` codes beyond
raw (0x04) and trigger (0x0b).

## The plan (revised)

1. **An overnight run of the window** at USB speed 0, against the binned
   record: `./guidecam.py probe --size 0 --roi 320x240 --speed 0
   --exposures 2 --window 28800`. The bar is the binned mode's, not 90%.
2. **On the sky, no pulses:** the same star at 2 s, binned and in the
   window, one after the other: centroid scatter in arcseconds, HFD,
   SNR, and how late frames arrive.
3. **Only then a guider that uses the window,** binned kept as the
   fallback:
   - find the star in a binned frame, then open a 320 pixel wide window
     around it (`roi_at` exists in the driver; the guider does not use it);
   - leave the window fixed while the star is safely inside: at 4.77"/px
     a 320 x 240 window is about 25' x 19', far more than guiding moves;
     whether the library can move a window while streaming, or only by
     stopping and starting, is untested;
   - the guider's limits are in binned pixels today (`guider.BIN = 2`:
     minimum RA move, calibration distance, dither size, error fault).
     They would be held in arcseconds and turned into pixels for the
     mode in use. A calibration already records its binning and is
     refused for another, so an old one is never reused.
4. Better sampling will not fix the Dec error by itself: last night's
   9.23" Dec against 2.03" RA is the mount (balance, slack, the focuser
   lead), being tested separately tonight with the tube rebalanced.

The USB speed is still set after the stream starts in the guider's own
path, as in every run of the proven binned mode; the probe sets it the
same way and reads it back ("USB speed 0 of 4").
