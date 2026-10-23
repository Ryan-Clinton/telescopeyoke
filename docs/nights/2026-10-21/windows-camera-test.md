# Windows 11 camera test for Altair ticket #3470

23 October 2026, 00:16 to 01:20 BST (UTC+1). This is the test Altair asked for
("test on Windows; WinUSB is the most robust"), done the same way as on Ubuntu
on 22 October (`docs/nights/2026-10-21/camera-stalls.md`) so that the two
results compare.

## Setup

- **Laptop:** HP ZBook 15 G4 (i7-7700HQ) running Windows 11 Pro 10.0.26300,
  newly installed on the hard disk.
- **Port:** the laptop's USB 3 (blue) port, on Intel's USB 3.0 controller
  (8086:A12F) with Windows' own xHCI driver.
- **Camera:** ALTAIRH183C, serial AA170607163620183C3F044F2CA0F74.
  Firmware 1.4.1.20170111, hardware 1.0, FPGA 1.1, made 20170607.
- **Camera driver:** Windows bound **WinUSB** to the camera by itself
  (USB\VID_16D0&PID_0C77, service WINUSB). AltairCapture was not installed.
- **Library:** Altair's 64-bit SDK 60.31589.20260531 (`vendor\altair\`),
  reached through `camera_test.py`. The library reported the camera as
  "not held back by a USB 2 port".
- **Conditions:** cap on, indoors, gain 1500, laptop on mains.

## Results

| Set | Frames arrived | Frame time | Stripes |
|---|---|---|---|
| 1 s, 6 frames | **6 of 6** | 0.9 s each | 1.07 to 1.19 ADU, 1.11 ADU overall (4.3); dark +1.476 ADU, 70.6 ppm hot pixels |
| 2 s, 6 frames | **0 of 6** | none arrived; each given up after 73 s | none |
| 16 s, 10 frames | **0 of 10** | none arrived; each given up after 325 s | none |

The camera's temperature and USB speed came back unread (`?`) in the cooldown
summary lines. The readings `camera_test.py` took from the room were air
12.5 °C and dew point 11.5 °C.

## What it means

This is the same pattern as on Ubuntu: 1 s exposures arrive and 2 s or longer
never do. This time it was Windows, WinUSB, a different USB stack and no INDI.
Long frames fail here too, so **the fault is in the camera itself, not in the
laptop's Linux USB stack or driver.** The cut-off is still between 1 s and 2 s
of exposure.

## Not yet done

- **AltairCapture cross-check** (step 5 of the Windows plan): 16 s frames with
  the cap on, using Altair's own program. This would rule out the project's
  code entirely. It needs the person to sign in to altairastro.help to
  download AltairCapture.
- The camera's firmware is from January 2017 (1.4.1). It is worth asking Altair
  whether a firmware update exists for the 183C.
