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

## Our conclusions

1. Full size fails as before, in every mode, at every exposure, at both
   USB speeds, with no hub. So it isn't the hub, the port or the exposure.
2. A 640 x 480 window fails where 640 x 480 binned works. Both have the
   same pixel count and 480 rows. So the amount of data isn't what
   decides it; reading the sensor at full resolution is. Only a small
   window gets through.
3. A 320 x 240 full-resolution window streams every frame. That's about
   25' x 19' of sky at 4.77"/px, room for one guide star.

## The plan

- First, the 5-minute pass on the window: `probe --size 0 --roi 320x240
  --exposures 2 --window 300`. It needs at least 90% of the frames
  expected, no gap over 4 s, and no library error.
- If it passes, change the guider: find the star in a binned frame, then
  guide on a 320 x 240 full-resolution window centred on it. When the
  star nears the window's edge, either move the window or go back to
  binned.

## Questions

1. Is conclusion 2 sound, given one run per row? What else could make a
   640 x 480 window fail when binned 640 x 480 works? For example, does
   the MT9M034 or this library change pixel clock, line timing or USB
   packet size between binned and full-resolution windows?
2. Does `put_Roi` before the stream starts behave differently from after,
   in this library generation? Should the window's offsets be multiples
   of something larger than 2?
3. Is there a setting we've missed that could make full size work in this
   old library? For example: frame-rate or bandwidth options
   (`put_Option` codes), `put_Speed` in other steps, a different pull
   buffer depth, push mode instead of pull mode, or 16-bit / bit-depth
   options.
4. For guiding, is a 320 x 240 window at 4.77"/px a better choice than
   the whole field binned at 9.55"/px? Consider centroid precision on a
   2 s guide star with this sensor, a field that small, a star lost to
   cloud, and dithering.
5. Is there anything in the test method that would make these numbers
   misleading? For example: draining the queue before counting, polling
   every 10 ms, or the first frame after an exposure change being taken
   at the old exposure.
