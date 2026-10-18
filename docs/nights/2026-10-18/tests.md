# Tests at ralphie-side, 18 October 2026

Run during the M31 patrol (16 s frames, gain 1500), from each frame's own
record in `frames/<panel>/<session>/frames.jsonl`. Times are when each frame
was kept (its end).

## 1. Kitchen light

Light on 22:07:09, off 22:08:53. Panel M31-P3, session 20261018-220720.

| Frame | Kept at | Light | Sky level | Stars | Star brightness | FWHM |
|---|---|---|---|---|---|---|
| 1 | 22:07:42 | on | 125.1 | 300 | 89714 | 6.0 |
| 2 | 22:08:00 | on | 125.2 | 300 | 94441 | 6.0 |
| 3 | 22:08:18 | on | 124.3 | 300 | 95907 | 6.1 |
| 4 | 22:08:35 | on, then off | 122.8 | 300 | 95683 | 6.1 |
| 5 | 22:08:53 | off | 117.5 | 300 | 88882 | 6.0 |
| 6-9 | 22:09:13-22:10:12 | off | 116.3-117.3 | 300 | 84567-95693 | 5.9-6.5 |

The kitchen light raises the sky by about 8 (7%), with no change to the
stars' number, brightness or sharpness. Every frame was kept: the cloud
check does not catch it, and at 7% it costs only about 3.5% more noise in
those frames. From ralphie-side the kitchen light does no real harm.
(17 October, from the other spot, two of Tabby's frames were lost to it.)

## 2. Upstairs bathroom light

Light on 22:11:55, off 22:13:28. Same panel and session.

| Frames | Kept at | Light | Sky level | Stars | FWHM |
|---|---|---|---|---|---|
| 12-14 | 22:11:12-22:11:51 | off | 115.4-116.4 | 300 | 5.8-5.9 |
| 15-18 | 22:12:11-22:13:10 | on | 115.2-116.0 | 300 | 5.8-6.1 |
| 19 | 22:13:30 | off | 113.4 | 300 | 5.8 |

No effect that can be measured: the sky stayed within its frame-to-frame
scatter of about 1 while the light was on.

## 3. Utility room light

Light on 22:20:41, off 22:23:17. Panel M31-P7, session 20261018-221836.

| Frames | Kept at | Light | Sky level | Stars | FWHM |
|---|---|---|---|---|---|
| 2-6 | 22:19:16-22:20:28 | off | 105.5-106.5 | 300 | 5.6-6.3 |
| 7-12 | 22:20:47-22:23:00 | on | 104.8-107.4 | 300 | 5.4-5.8 |
| 13-16 | 22:23:20-22:24:20 | off | 104.7-105.8 | 300 | 5.5-5.7 |

No effect that can be measured: the sky stayed within its usual scatter.
(Frame 8 came 55 s after frame 7, a pause in the camera, not the light.)
