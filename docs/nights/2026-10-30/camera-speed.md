# Speed 2 after a night outside, 30 October 2026

At 03:09, after a night outside (the Moon in colour and M34, 23:30 to 03:00),
with the camera still on the scope in the garden:

| Test | Result |
|---|---|
| `camera_test.py --speed-ladder --exposure 16 --frames 8` | speed 2: **8 of 8** arrived |

**The air**, from the forecast for the site at 03:00 (Open-Meteo, the figure
`camera_test.py` uses; there is no thermometer at the scope): **11.4 °C**, dew
point **7.7 °C**, humidity **78 %**. A mild, damp-ish night, not a cold one.
The camera's own sensor temperature is not read by any command yet, so it is
not known.

The ladder stops at the fastest speed that keeps every frame, so speeds 1 and
0 were not tried.

## What it shows

- The camera kept long frames at speed 2 after five hours outside at about
  11 °C and 78 % humidity, as it did indoors on 26 October (21 of 21,
  [the record](../2026-10-26/camera-lead.md)).
- It says nothing about cold: the night was mild. Whether cold brings the
  fault back is still untested.
- Damp is not ruled out either: the dew point was 3.7 °C under the air, and
  the frames still came. One mild damp night does not settle it.
- It is a short test: the lost frames came partway through a night's run
  before.

**Decision, 03:20:** back to readout speed 2 (`readout_speed = 2` in
config.toml) until the fault reappears, on the person's word. If a run loses
frames again, go back to 0 with `camera_test.py --speed-ladder --keep-best`.

At 02:59 one of the laptop's USB controllers dropped for a moment, taking the
camera and the focuser with it ("the camera was unplugged" ended the M34 run);
both came back. The test above ran after it.
