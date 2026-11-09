# 9 November 2026: guide scope focused, first full calibration

Clear spells 20:17–20:55 and 22:05–22:25, then thick cloud.

## Guide scope focus

On Alpheratz (centred by plate solve, 62° up), the guide camera at gain 400
showed every star as a faint disc about 60 px across at full resolution: the
guide scope was far out of focus. `./guidecam.py focus` had been measuring
with the guider's 13 px box, which on such a disc caught noise specks and
said 1.4 (tonight) and 3.1–3.5 (8 November, [record](../2026-11-08/guide-focus.md)):
those numbers were wrong. The aid now sums the brightest star's light within
30 px and says its true half-flux diameter (`focus_size`).

Clockwise on the guide scope's focuser brings it in. From about 18–21 px HFD
the person turned it in to **2.6–3.0 px** (binned, 2 s frames), the star's
peak rising from 14 to about 165: focused. `./guidecam.py star` then read
HFD 2.9 px at SNR 260, wander 0.10 px RMS.

## Calibration on Alpheratz (Dec +28.6, west of the pier)

| Try | West | East | North | Result |
|---|---|---|---|---|
| 1 | 10 steps, 0.75 px/s | 0.76 px/s | 14 steps, 0.72 px/s | refused: RA and Dec 103° apart, not 90 ± 10 |
| 2 | 0.82 px/s | 0.70 px/s | – | star lost (cloud) |
| 3 | – | – | – | star lost at once (cloud: frame level 15 against 5 clear) |

The first full run of every leg. The rates are about the expected 0.68 px/s
for this Dec. The Dec slack was 9–17 s (11.7 ± 3.8). The likeliest cause of
the 103° is drift during the slow north leg; the polar alignment is still
1.7° off. Nothing kept.

The guide camera's full-resolution snap (`./guidecam.py snap`) sent no frame
twice after 22:20, while the binned guiding mode carried on; that is the
known weak mode ([fault](../../guide-camera-fault.md)), not a stall.

## Next clear night

Calibrate again on Alpheratz or another bright star in a sparse field; then
guide.
