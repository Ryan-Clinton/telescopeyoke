# Long frames at Speed 2 again, on either lead (26 October 2026)

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

**The old 3 m lead, straight after (19:22 to about 19:35).** The same three
tests on the same port (2-4, 5000 Mb/s), cap on: **3 of 3, 10 of 10 and 8
of 8** at Speed 2, again with no USB reset.

So the lead was not the cause: the old lead that lost every Speed 2 frame
on 23 October keeps them all today. The camera's fault comes and goes. It
started at 04:59 on 20 October and has gone, for now, by 26 October, on
the same leads and port. `readout_speed` stays 0 in `config.toml`: a fault
that comes and goes may come back mid-run, and Speed 0 kept its frames
through the fault. What brings it on (the camera's temperature, damp, the
cold nights) is not yet known; `camera_test.py --cooldown` on the next cold
night, at Speed 2, would show whether the cold brings it back.
