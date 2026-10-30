# Speed 2 after a cold night, 30 October 2026

At 03:09, after a night outside (the Moon in colour and M34, 23:30 to 03:00,
clear and cold), with the camera still on the scope:

| Test | Result |
|---|---|
| `camera_test.py --speed-ladder --exposure 16 --frames 8` | speed 2: **8 of 8** arrived |

The ladder stops at the fastest speed that keeps every frame, so speeds 1 and
0 were not tried. With 26 October's 21 of 21 indoors ([the record](../2026-10-26/camera-lead.md)),
the camera has now kept long frames at speed 2 warm and cold, on either lead.
A cold night did not bring the fault back, which weighs against damp as its cause.

Not the same as a night's run at speed 2: the lost frames came mid-run
before. `readout_speed` stays 0 until a whole run at speed 2 keeps its frames.

At 02:59 one of the laptop's USB controllers dropped for a moment, taking the
camera and the focuser with it ("the camera was unplugged" ended the M34 run);
both came back. The test above ran after it.
