# Windows 11 camera test for Altair ticket #3470

## 31 October 2026: the speed-2 short exposure on Windows

The brief is `docs/agents/windows-camera-test.md`. The camera was on the
powered USB hub (seen as ALTAIRH183C, USB\VID_16D0&PID_0C77, WinUSB).

- **The project's order test** (`python camera_test.py --order`, about
  22:25 GMT, Altair's Windows library 60.31589.20260531): a 16 s frame at
  speed 2 came back **after 10.4 s, short (the fault), all five ways**:
  usual, time first, stream stopped, via speed 0, usual again. This is the
  same as on Linux, so the short exposure does not come from Linux's USB
  stack, INDI or the order in which the project sets speed and exposure.
- Smart App Control had switched itself from evaluation to On and blocked
  scipy's unsigned `_fblas` DLL. Ryan agreed to turn it off, and the test
  then ran. On Windows it cannot be turned back on without a reinstall.
- **AltairCapture** 4.12.31589.20260531 (its altaircam.dll 60.31589.20260531,
  the same library) is installed at
  `C:\Program Files\AltairAstro\AltairCapture\x64\altaircapture.exe`.
  Its frames go in `C:\Users\Facepipe\Pictures\altair-test`.
- **Diagnose file** (step 2, 23:21 GMT): AltairCapture's About > Diagnose
  has no save, only Copy; the copied text is in
  `altaircapture-diagnose-2026-10-31.txt` in this folder. It shows
  AltairCapture 4.12.31589.20260531, altaircam.dll 60.31589.20260531,
  firmware 1.4.1.20170111, FPGA 1.1, the camera behind a Realtek
  SuperSpeed hub (0BDA:0411) on Intel's xHCI (8086:A12F), Frame Speed 2
  of [0, 2], anti-flicker DC. It was taken with the live view open at
  10 ms, gain 1.00, and that live view had stopped at **frame 29, 0.0
  frames a second**, black.
- **Light comparison** (step 3, 23:24 to 23:28 GMT): **not done; no frame
  arrived.** In Video Mode AltairCapture caps the exposure at 5000 ms, so
  it was run in Trigger Mode (software trigger, Single), which allows
  8 s: RAW, 12 bits, gain 100 (its lowest), auto exposure off, Frame
  Speed at Low (0). The 8 s Single frame's progress bar ran to 8.0/8.0
  and then **no frame came back in about 70 s** (Frame: 0); stopped. The
  same again, Single, 8 s, speed 0: **no frame in about 60 s**. Two
  failures, so per the brief it stopped there; speeds 2 and 1 were not
  tried and there are no frames to compare. So, in Altair's own program
  on Windows, an 8 s exposure at speed 0 never arrives at all, the same
  as the 2 s and 16 s frames through the project on 23 October.
- **What it does and does not show.** Altair's own program, with Altair's
  own library, lost every long frame, so the project's code is not the
  cause. But the camera was already stuck before the 8 s tries (the live
  view frozen at frame 29 even at 10 ms, after the order test had run), so
  this is not the clean light comparison of the brief: whether
  AltairCapture also shows speed 2 gathering half of speed 0 is still
  open. It wants the camera unplugged and plugged back in first, then
  AltairCapture straight away, in Trigger Mode, 8 s, speeds 0, 2, 1, 0.

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
