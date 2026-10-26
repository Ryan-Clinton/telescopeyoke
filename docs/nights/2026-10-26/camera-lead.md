# A new USB 3 lead: long frames at Speed 2 again (26 October 2026)

A brand new USB 3 lead came with a USB hub. It went straight from the
laptop to the camera (no hub), cap on, indoors, camera warm. The kernel
log gave SuperSpeed (5000 Mb/s) on port 2-4.

| Test | Speed 2 |
|---|---|
| `camera_test.py --speed-ladder` (3 of 16 s) | **3 of 3** arrived |
| `camera_test.py --speed-ladder --exposure 2 --frames 10` | **10 of 10** arrived |
| `camera_test.py --speed-ladder --exposure 16 --frames 8` | **8 of 8** arrived |

21 of 21 at the fastest readout speed, with no USB reset or disconnect in
the kernel log. Since 20 October, Speed 2 at USB 3 had kept none: on the 3 m
lead and on the 1 m lead, on this laptop and on the desktop PC
([the record](../2026-10-21/camera-stalls.md#usb-2-against-usb-3-on-the-desktop-pc-23-october-0136-to-0151)).

What it does not yet say: whether both old leads went bad, or whether the
camera's fault comes and goes. The same ladder on the old 3 m lead, at
once, on the same port, tells the two apart. `readout_speed` stays 0 in
`config.toml` until that is known and a whole run has kept its frames at
Speed 2.
