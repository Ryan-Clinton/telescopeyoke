# 21 October 2026: the camera stalls on a warm camera and a short lead

For Altair ticket #3470 ([docs/banding.md](../../banding.md)).

The camera had been **indoors all day**. It went out at about 23:00, so it
was warm for the whole of this. INDI driver (`indi_altair_ccd`), on Ubuntu.

## The lead

- Until 23:54: the 3 m USB 3 lead, at 5000 Mbps (USB 3) direct to the laptop.
- From 23:54: a **1 m USB 3 lead**, direct to the laptop, at 5000 Mbps. Altair
  asked for a working USB 3 lead of 1.8 m or less, and this is shorter than that.
  The disconnects at 23:54:07 and 23:56:24 to :43 in
  [kernel-camera-usb.log](kernel-camera-usb.log) are the person swapping and
  then reseating the lead. Apart from those, the kernel log shows no
  disconnect or reset at all.

## What failed

All frames were 1 s and 2 s at gain 1500, the short exposures that worked
even on the cold night of 17 October.

| Time (approx.) | Lead | What happened |
|---|---|---|
| 23:23 | 3 m | 2 s frame: 7.9 s in total (normal) |
| 23:31 | 3 m | motor focus: `timed out waiting for the image` on its first frames |
| 23:35 | 3 m | after a driver restart: a 0.1 s test frame took 42.9 s, then a 2 s frame took 44.1 s. The next 2 s frame took 7.9 s |
| ~23:45 | 3 m | focus walk-in: timed out on its first frame |
| ~23:50 | 3 m | after a restart (0.1 s in 0.92 s, then 2 s in 7.9 s): walk-in hung again in its first readings |
| ~23:53 | 3 m | 2 s frame 44.1 s; a 1 s focus check timed out after 60 s |
| 23:55 | **1 m** | after a restart: 0.1 s test frame in 0.92 s |
| 23:56–00:00 | **1 m** | walk-in ([2356-walk-in.log](2356-walk-in.log)): three 1 s frames came, then after nearly every focuser move a frame did not arrive for 16 to 76 s, while the driver was restarted and the exposure retried |

So it has these signs:

- **It is not the cold.** The camera had been warm indoors all day.
- **It is not the long lead.** The 1 m USB 3 lead behaves the same as the 3 m.
- **It is not a USB dropout.** The link stays at 5000 Mbps, with no
  disconnect in the kernel log.
- **When it fails, it usually loses about 35 to 40 s.** A frame either takes
  its normal time or one of about 43 s, as if one exposure is lost and a
  timeout of about 35 s passes before the retry.
- **Single frames usually work; a run of back-to-back 1 s frames fails within a minute or two.**

The focuser (CH340 on its own USB bus, 3) was on for all of it. The stalls
come mostly after a focuser move, but they also happened in the focus check,
which moves nothing.

## Later: long frames, Altair's own library (22 October, 04:39 to 04:48)

From 00:05 the camera was read through Altair's own library (`[camera]
backend = "altair"`), on the 1 m lead until the rain and on the 3 m lead again from 03:25. 1 s frames mostly arrived in
their normal 2.5 s, with a stall every few minutes. 16 s frames never
arrived: the M31-P6 patrol run waited from 04:39:51 with no frame for
more than five minutes. After a restart, the 0.1 s test frame took 28 s,
and a single 16 s frame then failed to arrive within 90 s. The kernel log
shows no USB disconnect.

## Altair's mains suggestions, tested (22 October, 05:30 to 05:46)

Cap on, indoors, the camera warm, Altair's own library, gain 1500, the camera
on the laptop's USB 3 port at 5000 Mbps. Each lost frame was given up after
75 s (three tries).

| Power to the laptop | 2 s frames arrived |
|---|---|
| Charger in the kitchen socket through the usual extension lead | 0 of 3 |
| The same socket, charger plugged straight in | 0 of 2 |
| Charger unplugged, laptop on battery | 0 of 2 |
| Charger in an upstairs socket (another circuit) through an extension lead | 0 of 2 |

1 s frames arrived in their normal 2.5 s between the sets. So it is not the
socket, the circuit, the extension lead or a ground loop through the charger. The cut-off
is between 1 s and 2 s of exposure.

## On Windows too (23 October, 00:16 to 01:20)

The same laptop, booted into Windows 11, with the camera on WinUSB (Windows
bound it by itself) and Altair's SDK 60.31589. There was no INDI and no Linux,
the port was the same blue USB 3 one, and the cap was on indoors:

| Exposure | Frames arrived |
|---|---|
| 1 s | 6 of 6, 0.9 s each |
| 2 s | 0 of 6 |
| 16 s | 0 of 10 |

The same cut-off between 1 s and 2 s, on a different operating system, USB
stack and driver, so **the fault is in the camera**, not the laptop's Linux
USB or the project's code. The full record is in
[windows-camera-test.md](windows-camera-test.md). The camera's firmware is
1.4.1 from January 2017: worth asking Altair whether a newer one exists.

## USB 2 against USB 3 on the desktop PC (23 October, 01:36 to 01:51)

The camera was moved to the desktop PC (AMD USB 3.1 controller, Windows,
WinUSB, Altair's SDK 60.31589) on the same 3 m lead, cap on, gain 1500. At
first the lead was not fully home, so the camera came up in its USB 2 mode
(PID 0C78); after it was reseated, it came up at USB 3 (PID 0C77) on the same
port.

| Mode | 1 s frames | 2 s frames | 16 s frames |
|---|---|---|---|
| USB 2 | 6 of 6 (8.7 s each) | **6 of 6** (15.0 s each, stripes 1.02 to 1.09 ADU) | arrived (1 tried, 104 s) |
| USB 3, 3 m lead | | **0 of 2** (each given up after 73 s) | |
| USB 3, 1 m lead | | **0 of 3** (each given up after 73 s) | |

Same camera, PC and port. Long exposures arrive in the camera's USB 2 mode and
never in its USB 3 mode, on either lead, here as on the laptop under Ubuntu
and Windows.

## When it started: 04:59 on 20 October

This is not how the camera always was. The kernel log shows it linked at USB
3 (SuperSpeed) on every night from 6 October, and at USB 3 it kept long
frames for hours: 16 s frames on 13, 14, 17, 18 and 19 October (256 in one M31
run on the 13th), 32 s frames of M33 on the 19th, 116 of 116 16 s darks
indoors on the 19th, and 992 4 s frames of WASP-12 b from 01:47 to 04:56 on
20 October. Nothing in `camera.py`, `indi.py` or `altair.py` changed between
that night and the 21st (the last change, the frame wait, was on 19 October
at 00:05, before both), the laptop ran the same kernel, 7.0.0-38, and the
updates installed on 21 October touched no USB, INDI or firmware package.
The camera's firmware still reads 1.4.1.

The change came at the end of the 19 to 20 October night, outdoors, after a
night in the cold, as cloud came in at 04:51: the camera hung on the
re-centre at 04:59, then again at 05:06 (after 10 frames), 05:21 (after 78)
and 05:28 (after 5). It came indoors at 08:17. Since then, every frame of 2 s
or more has been lost at USB 3: on the laptop under INDI and Altair's library
(21 to 22 October), under Windows on the laptop, and on the desktop PC on
both leads. Shorter hangs had come before, on the cold nights of 15 and 18
October, and cleared.

So something in the camera itself changed that morning and has not changed
back, and it is on the USB 3 side: the same camera works in USB 2 mode. The
likeliest places are the USB 3 socket's five extra SuperSpeed contacts
(bent, loose or corroded; damp at dawn could do it) or the camera's own USB 3
chip. Why the exposure matters, when the frame sent down the lead is the
same size at 1 s and 2 s, is not proven. One explanation fits: a USB 3 link
left idle drops into a low-power state and has to wake up to send the frame,
and a marginal SuperSpeed connection may fail that wake while it copes with
a link kept busy.

Until it is mended, the camera can be run in its USB 2 mode (through a USB 2
hub or extension), at about 9 s of download a frame.
