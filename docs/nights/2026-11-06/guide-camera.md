# 6 November 2026: the guide camera, indoors

[README](../../../README.md) · [All docs](../../README.md) · [Validation](../../validation.md) · [Autoguiding](../../autoguiding.md)

**Record.** Daytime and evening, no sky. The Orion Mini 50 mm guide scope
arrived and the Altair GPCAM MT9M034M was wired to the mount: USB to the
Trust hub (unpowered) on the 183M's internal hub, and its ST4 lead to the
EQ3 Pro's autoguider port.

## The ST4 lead: works

`./guidecam.py pulse --seconds 5`, the mount tracking, the handset's axes
read before and after each pulse and compared with a still 5 s:

| Pulse | Axis moved beyond the still reading |
|---|---|
| North | Dec +35.7" |
| South | Dec -35.7" |
| East | RA +32.8" |
| West | RA -38.9" |

All four directions move the mount, about 7.1"/s: the handset's 0.5x
sidereal guide rate.

## The guide camera with the filter wheel: fails

With the SX filter wheel and the guide camera both on the Trust hub, the
wheel never finished its power-up turn and the guide camera stopped
sending frames. Each worked alone.

## Frames at guiding exposures: fail

With the wheel unplugged, the camera alone on the Trust hub, cap on.
`./guidecam.py snap` gave single frames at 0.5 and 0.8 s, but failed
("no frame within 6 s") at 0.6, 0.95 and 1 s and on the second of two 2 s
frames. `./guidecam.py probe` counts the frames that arrive in 12 s at
each exposure:

| Mode | 0.1 s | 0.5 s | 1 s | 2 s |
|---|---|---|---|---|
| Video, USB speed 4 of 4 | 19 frames, gaps up to 3.1 s | 1 | 1 | 0 |
| Video, USB speed 0 | 6, gaps up to 3.2 s | 2 | 1 | 0 |
| Software trigger, speed 0 | 4, about one every 3.2 s | 2 | 1 | 0 |

The library allows exposures of 0.18 ms to 800 s, so 2 s is in range.
The 2 November test took single frames of 1 to 100 ms only, so this was
not seen then. Guiding needs a 2 s frame every few seconds, so it cannot
run on this connection as it stands.

Later that evening, on the laptop's own port with no hubs, it was the
same: **the hubs are not the cause.** The full record, what is ruled out,
what others have found and what is left to try:
[the guide camera's dropped frames](../../guide-camera-fault.md).

## Built the same day, not run on the sky

The guider's first three stages (`./guidecam.py star`, `calibrate`,
`guide`; `guider.py`), from [the specification](../../autoguiding.md).
Dry runs only. Nothing has guided.
