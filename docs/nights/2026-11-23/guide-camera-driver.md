# Would a better driver help the guide camera?

[The guide camera's fault](../../guide-camera-fault.md) · [Validation](../../validation.md)

**Tested 24 November 2026, 01:46 to 02:25 UT, indoors. Answer: not for the
mode the guider uses now, which already delivers its frames. A driver could
only help full-width frames, and a 512 x 960 window already gets the full
resolution without one.**

The camera is the Altair GPCAM MT9M034M, on the SV241 hub by a short lead,
with the filter wheel off USB. There were 25 runs of `./guidecam.py probe`:
no pulses, no frames kept, no sky. The main camera was on the laptop's USB 3
bus for the colder dark test.

## Results

Frames arriving in 20 s, each from a fresh open of the camera. The most
possible is about 200 at 0.1 s, 40 at 0.5 s and 10 at 2 s.

| Mode | USB speed | 0.1 s | 0.5 s | 2 s |
|---|---|---|---|---|
| Full 1280 x 960 | 4 | 19 | 3 | 0 |
| Full, speed set first | 0 | 5 | 2 | 1 |
| Full, raw | 0 | 8 | 1 | 0 |
| Full, software trigger | 0 | 6 | 3 | 2 |
| Full, real-time mode | 0 | 10 | 9 | 1 |
| **Binned 640 x 480 (the guider's mode)** | 0, set after the start | **194** | **41** | **10** |
| Binned, speed set first | 0 | 196 | 41 | 10 |
| Binned | 4 | 196 | 41 | 10 |
| Binned, raw | 0 | 196 | 41 | 10 |
| Binned, real-time mode | 0 | 196 | 41 | 10 |
| Window 320 x 240 | 0 | 196 | 41 | 10 |
| Window 480 x 240 | 0 | 194 | 41 | 10 |
| **Window 512 x 960** | 0 | **194** | **41** | **10** |
| Window 512 x 960 | 1 | 193 | 39 | 10 |
| Window 512 x 960 | 2 | 190 | 39 | 10 |
| Window 544 x 960 | 0 | 158 | 33 | 6 |
| Window 576 x 960 | 0 | 157 | 32 | 6 |
| Window 640 x 480 | 0 | 133 | 30 | 9 |
| Window 640 x 960 | 0 | 84 | 19 | 2 |
| Window 800 x 600 | 0 | 34 | 9 | 3 |
| Window 1024 x 768 | 0 | 7 | 3 | 0 |

Every window was at full resolution and set with the speed first.

Longer runs, all at USB speed 0:

| Mode | Exposure | Frames | Longest gap |
|---|---|---|---|
| Binned, speed set after the start (as the guider does) | 2 s for 300 s | 149 | 2.08 s |
| Binned, speed set first | 2 s for 300 s | 149 | 2.18 s |
| Window 512 x 960 | 2 s for 300 s | 149 | 2.15 s |
| Binned, speed set first | 0.5 s for 120 s | 239 | 0.67 s |

No run repeated a frame or had a pull error, and the kernel logged no USB
error or disconnect.

## What it shows

- **The guider's mode has nothing left to gain.** It delivers a frame per
  exposure, so its rate is set by the exposure. Setting the speed first made
  no difference to it, so the guider stays as it is.
- **USB bandwidth is not the limit.** Taking frames as 8-bit, a full frame
  every 2 s is about 0.6 MB/s and fails, while 512 x 960 at about 10 frames a
  second is about 4.8 MB/s and works.
- **The width of the read decides it.** Delivery is complete up to 512 pixels
  and falls off from 544. A 640 x 480 window loses frames where 640 x 480
  binned does not, with the same number of pixels.
- **The lost frames never reach the library's count.** It counted what was
  pulled, to within one frame, and reported no error or timeout. So the loss
  is in the library's handling below that count, in the USB transfers, or in
  the camera.

## What a driver could and could not do

These odds are judgement, not measurement.

| Question | Odds |
|---|---|
| A driver makes the guider's current mode better | Under 5% |
| A driver makes full-width frames stream | About 30% |
| A driver makes guiding noticeably better than a 512 x 960 window would | About 5% |

A driver would help full width only if the fault is in how the old library
sets up the sensor or reads the USB transfers. If it is in the camera's
firmware, a driver could not fix it. These tests cannot tell the two apart.

## What to do instead

1. **Compare binned and windowed on a real star:** `./guidecam.py star
   --compare-window`, on the next clear night. The window is 4.77"/px against
   9.55"/px binned, over 41' x 76' of sky rather than the whole 1.7° x 1.3°.
2. **Only if the window measures better,** build what is still missing: find
   the star binned, then guide on a 512 x 960 window round it.
3. **Only if full width is still wanted,** capture the USB traffic with
   `usbmon` while a full frame fails. That shows whether the camera sends the
   missing data, and so whether a driver has anything to fix. It needs a
   kernel module loaded and has not been done.

## What was not tested

- Stars: nothing here measures guiding accuracy.
- The filter wheel running at the same time, as its lead is still to come.
- Any other computer, or the camera straight into the laptop on this night.
- The 20 s runs are short, so a difference of a few frames between them means
  little. The 5-minute runs are the firmer evidence.
