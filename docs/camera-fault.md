# The main camera's lost-frame fault

The whole record in one place, from the first sign to the latest test. The
details are in the dated night files linked from each entry.

**The camera:** Altair Hypercam 183C (Sony IMX183 colour), firmware 1.4.1
(January 2017), on USB 3. The camera is Gary's. Altair support ticket #3470.

**The fault:** the camera takes an exposure, but the frame never comes down
the USB lead. There is no USB disconnect or reset in the kernel log, and the
link stays at 5000 Mb/s. When it happens the frame is lost, not just late:
none has come within 108 s of a 16 s exposure.

**What is in use now:** readout speed 0 (`[camera] readout_speed = 0`), the
slowest, which has never lost a frame. It costs about a second more per frame
than speed 2.

## How to read the speed test

`camera_test.py --speed-ladder` tries the readout speeds from the fastest
down. **At each speed it stops at the first lost frame and moves on.** So
"0 of 8" at a speed means the first frame was lost and the other seven were
not tried. A speed that passes has had every frame tried. Since 30 October
the output says this in words, and every run adds a line to
`cache/camera-fault.jsonl` with the result, the `--note`, and where the
camera was on USB (`usb_state`: the port, the link speed, its power
setting, and whether the USB 3 link power states U1 and U2 are in use).

## The record

| Date and time | Where and how | Test | Result |
|---|---|---|---|
| 6 to 20 Oct | Outside, laptop, USB 3 | Every night's imaging | **Fine.** 16 s frames on 13, 14, 17, 18 and 19 Oct (256 in one run), 32 s on the 19th, 116 of 116 16 s darks indoors on the 19th, 992 4 s frames on 20 Oct to 04:56 |
| 15 and 18 Oct | Outside, cold nights | Imaging | Short hangs that cleared |
| **20 Oct 04:59** | Outside, end of a cold night, cloud coming in | Imaging | **Fault starts:** hangs at 04:59, 05:06, 05:21, 05:28 |
| 21 Oct 23:23 to 00:00 | Garden, camera warm all day, INDI | 1 and 2 s frames, 3 m then 1 m lead | Frames lost or about 35 s late after a minute or two of back-to-back frames, on both leads ([record](nights/2026-10-21/camera-stalls.md)) |
| 22 Oct 04:39 | Altair's own library | 16 s frames | None arrived |
| 22 Oct 05:30 to 05:46 | Indoors, cap on | 2 s frames, four ways of powering the laptop (battery included) | 0 arrived every way; 1 s frames fine. Not the mains |
| 23 Oct 00:16 to 01:20 | Same laptop booted into Windows 11, Altair's SDK | 1, 2 and 16 s | 1 s 6 of 6; 2 s 0 of 6; 16 s 0 of 10. Not Linux, INDI or the project's code |
| 23 Oct 01:36 to 01:51 | Desktop PC, Windows | Same camera in USB 2 and USB 3 mode | USB 2: 2 s 6 of 6, 16 s arrived. USB 3: 2 s 0 of 5, on both leads |
| 23 Oct 02:10 to 03:00 | Desktop PC, USB 3 | Readout speeds | Speed 2 lost 2 s frames; speed 1 kept 2 s, lost 16 s; **speed 0 kept 20 of 20 16 s** |
| 23 Oct 02:35 | Desktop PC | Socket cleaned with isopropyl alcohol | No change: speed 2 still lost 2 s frames |
| 23 Oct 02:40 to 03:05 | Desktop, then laptop | Lead held up and down; speed test on the laptop | Holding the lead changed nothing. Laptop: lost at speeds 2 and 1, kept at 0. **`readout_speed = 0` from here** |
| 23 Oct 17:55 | Laptop | A 2018 Altair library under today's driver | Could not be tried: today's driver needs functions the 2018 library lacks |
| **26 Oct** | Indoors, warm, laptop port 2-4 | New lead, then the old 3 m lead | **Gone:** 21 of 21 at speed 2 (2 s and 16 s) on each lead ([record](nights/2026-10-26/camera-lead.md)) |
| 30 Oct 03:09 | On the scope outside after 5 hours, 11.4 °C, 78 % humidity, port 2-4 | 8 × 16 s, speed 2 | **8 of 8.** `readout_speed = 2` again ([record](nights/2026-10-30/camera-speed.md)) |
| 30 Oct 03:18 | | Camera unplugged and brought in | |
| 30 Oct 10:45:40 | Indoors, warm, plugged into port 2-5 | | |
| 30 Oct 10:46 to 11:02 | Same | 16 s frames at each speed | **Fault back:** speed 2 lost its first frame; speed 1 lost its first frame; speed 0 kept 8 of 8. `readout_speed = 0` again |
| 30 Oct 11:02 to 12:31 | Same, camera not unplugged | 5 each of 60, 120 and 300 s at speed 2 (meant for speed 0; the test ignored `--speeds` until fixed) | **15 of 15** |
| 30 Oct 12:31 to 13:22 | Same | 5 each of 60, 120 and 300 s at speed 0 | **15 of 15** |
| 30 Oct 14:31 | | Unplugged by hand | |
| 30 Oct 14:37 | Plugged into port 2-1 | | |
| 30 Oct 14:40 | Same | 8 × 16 s at speed 2 | **8 of 8** |
| 30 Oct 16:43 | Behind a USB 3.2 hub (Realtek 0bda:0411, says it is self-powered) on port 2-5, the camera on 2-5.1 at 5000 Mb/s. Leads, as the person said: the **3 m lead from the laptop to the hub**, the **new 1 m lead from the hub to the camera** (so until 17:25) | | |
| 30 Oct 17:09 | Same | 50 × 16 s at speed 2 | After about 2 minutes the camera refused its first setting (`put_AutoExpoEnable`) when reopened: SDK error **0x8000FFFF**, never seen before |
| 30 Oct 17:11 and 17:12 | Same | 2 s at speed 2, then 3 × 2 s at speed 0 | **Would not open at either speed**, same error. No USB error in the kernel log |
| 30 Oct 17:13 | Same | 50 × 16 s at speed 2 | Opened normally by itself, then the same error at 17:15. The library's replug (new in `altair.py`) was tried |
| 30 Oct 17:15:04 to 17:15:46 | Same | | **The camera stopped answering USB itself.** The kernel: `device descriptor read/8, error -110` (timed out), a reset, a disconnect, then four tries to find it again, each timing out, and two more from 17:16:02. It was gone from USB until the person cut its power with the hub's port button |
| 30 Oct 17:16:23 | Same, after the hub's port button was pressed twice | | **Back** at 5000 Mb/s: cutting the camera's power brought it back where the library's replug (a software reset) could not |
| 30 Oct 17:18 to 17:20 | Same | 50 × 16 s at **speed 0** | **Failed at once.** About a minute in, the person heard the camera's fan stop and saw the hub's light change from steady to flashing; the kernel then timed out reading the camera (error -110) through seven resets, and it dropped off USB. Speed 0 had never failed plugged straight in. The camera losing power behind this hub fits best: the hub's own supply, if any, is not known |
| 30 Oct 17:22:53 | The same hub moved to laptop port 2-1 (which passed direct at 14:40), the camera on the hub's port 4 (2-1.4) | 50 × 16 s at speed 0 | **The same failure**, two minutes in: at 17:24:57 the kernel reset the camera and timed out reading it (error -110). Stopped there. Other laptop and hub ports, same result: it is the hub, or the camera's power through it |
| 30 Oct 17:28:44 to 17:46 | The leads re-arranged: the **new 1 m lead from the laptop to the hub**, the **old 1 m lead from the hub to the camera**; hub on laptop port 2-1, the camera on the hub's port 1 (2-1.1) | 50 × 16 s at **speed 0** | **50 of 50**, no USB error |

## What is ruled out

- **A lead as the root cause.** Two leads failed on 21 to 23 Oct; a new lead
  and the old 3 m one both passed on 26 Oct. A marginal camera can still
  work with one lead and port and fail with another, so a lead can make the
  difference on the day without being the fault.
- **A particular computer, operating system or program as the root cause.**
  It failed on the laptop and the desktop PC, under Linux (INDI and Altair's
  library) and Windows (Altair's SDK). The host's USB 3 port and controller
  can still affect whether the fault shows: see the ports below.
- **The mains supply.** It failed on battery too.
- **Dirt on the socket.** No change after cleaning it.
- **Cold.** It failed indoors and warm on 30 Oct, eight hours after passing
  outside.
- **Damp, as an active cause.** It came and went within a quarter of an
  hour indoors and warm on 30 Oct. Corrosion left by damp on 20 Oct, making
  a contact marginal, is not ruled out.
- **USB 3 link power states on the laptop.** For the camera, the kernel
  makes no U1 or U2 setting at all (no `usb3_hardware_lpm_u1` or `_u2`
  file), so those states are not in use, and its power control is `on`
  (never suspended). Read by `usb_state`, no root needed.
- **The length of the frame.** 16 s frames were lost at speed 2 at 10:46 and
  kept at 14:40; 60 to 300 s frames passed at speed 2 in between.
- **Needing a power cycle to clear it.** On 30 Oct it was lost at about
  10:47 and gone by 11:02 with the camera plugged in throughout.

## What is known

- **Behind the hub, the leads decide it.** With the 3 m lead from the
  laptop to the hub and the new 1 m lead from the hub to the camera, it
  failed at speed 0 within two minutes, three times, on different ports,
  the fan stopping and the hub's light flashing: the camera lost its power,
  or the hub shut its port. With the new 1 m lead from the laptop to the hub
  and the old 1 m lead to the camera, speed 0 kept 50 of 50. If the hub
  takes its power from the laptop, a 3 m lead carrying the hub and the
  camera both would drop the voltage most; a bad new 1 m lead to the camera
  would also fit. Swapping one lead at a time would tell which.
- **The camera's USB chip itself can stop answering.** On 30 Oct at 17:15,
  behind a hub, the kernel's own requests for the camera's descriptor timed
  out (error -110) through a reset and four tries to find it again. That is
  below every program and library: the camera's USB 3 side had stopped
  responding at all. It is the strongest sign yet that the fault is in the
  camera's USB 3 electronics (or, this once, the hub between).

- **The faster the readout, the more it fails.** Speed 0 has never lost a
  frame, through every fault. Speed 1 has lost 16 s frames and kept 2 s ones.
  Speed 2 has lost frames as short as 2 s.
- **USB 2 mode kept frames that USB 3 mode lost** on the same PC and port
  (23 Oct).
- **It comes and goes,** over days (gone by 26 Oct) and within a quarter of
  an hour (30 Oct). Nothing done to the camera has been followed by a change
  every time.
- **It started at 04:59 on 20 October,** at dawn after a cold night, and was
  not there before. Nothing in the software changed between the good nights
  and the bad.
- **The port may matter.** On 30 Oct it failed on port 2-5 at 10:46 and
  passed on 2-1 at 14:40. Ports 2-5 and 2-1 are on the same root hub
  (bus 2) but are separate sockets and traces. One test each, hours apart,
  so the fault's own coming and going could explain it too: the port
  survey below would tell.

## What is still open

- **What brings it on.** Neither cold nor warmth does on its own. Damp was
  suggested on 26 Oct (the camera drying out after the dawn of 20 Oct); it
  is not ruled out, but it does not explain a change within 15 minutes
  indoors.
- **Where it is.** Everything points at the camera's SuperSpeed path: the
  same camera, computer and program work at USB 2 and fail at USB 3, and a
  slower readout keeps it working. Ranked, as a guide to what to test, not
  as measured odds:
  1. The camera's USB 3 bridge chip or its high-speed signal path on the
     board. It fits the link staying at 5000 Mb/s while frames stop, and a
     state that comes and goes with nothing touched.
  2. The camera's USB 3 socket or its solder joints. Holding the lead up
     and down changed nothing, cleaning changed nothing, and the link never
     dropped to USB 2, which makes a bent or loose contact less likely, but
     a joint that is marginal at 5 Gb/s would not show those signs.
  3. The camera's firmware (1.4.1, 2017) and the library's USB transport.
  4. The camera's own power: its USB 3 chip runs from the lead's 5 V, and a
     tired regulator or capacitor could fail only at the fastest readout.
     A powered hub would test this (other makers of IMX183 cameras suggest
     one for hangs, e.g. QHY's 183C manual).
  5. How the host's USB 3 port and controller treat a marginal device.
- **Whether the first frames after the camera is opened matter.** At 10:46
  the fault showed within minutes of the camera being plugged in; it has not
  been seen to begin partway through a test that was passing.
- **Whether speed 0 can ever fail.** It has not yet, in every test since
  23 Oct.

## Next tests

In order. Each says what it needs.

1. **Stay at speed 0 for imaging.** It costs about a second a frame.
2. **Through a powered USB 3 hub.** The camera is on a USB 3.2 hub now (16:43,
   30 Oct) that says it is self-powered; whether its own supply is plugged
   in is for the person to say.
   `camera_test.py --speed-ladder --speeds 2 --exposure 16 --frames 50
   --note "powered hub, port 2-5"`. If speed 2 holds through the hub, power
   or signal conditioning moves up the list. Needs the person's go: it runs
   the camera for about 20 minutes.
3. **The ports, one at a time.** The same 50 frames of 16 s at speed 2 on
   each of the laptop's USB 3 ports in turn; the fault log records which.
   Needs the person's hands to move the plug.
4. **usbmon during a lost frame.** It shows whether the laptop was waiting
   on transfers the camera never answered (the camera never sent the frame)
   or never asked (the program or firmware stopped). Loading usbmon and
   reading its capture need root, so the person runs these two:
   `sudo modprobe usbmon` and, during a test,
   `sudo cat /sys/kernel/debug/usb/usbmon/2u > usbmon.txt`. Then
   `camera_test.py --usb-report usbmon.txt` says what the capture shows for
   the camera.
5. **AltairCapture's Diagnose, on Windows, camera plugged straight in**, as
   Altair asks of support customers. Needs the Windows boot and AltairCapture
   installed.
6. **Another Hypercam 183C on this laptop, or this one on another
   astronomy computer.** Needs a second camera or computer.

## For Altair (ticket #3470)

The camera is Gary's, and the ticket is his to answer. In short:

| | |
|---|---|
| Computers | laptop and desktop PC |
| Systems | Ubuntu (INDI, Altair's library) and Windows 11 (Altair's SDK 60.31589) |
| Leads | four: 3 m, 1 m, a new one, and the 3 m again |
| USB 2 mode | 2 s and 16 s frames arrive |
| USB 3, speed 0 | every frame has arrived, in every test since 23 Oct |
| USB 3, speed 2 | frames lost at times, as short as 2 s; the link stays at 5000 Mb/s, no disconnect |
| Started | 04:59 on 20 Oct 2026, at dawn after a cold night |
| Comes and goes | gone 26 Oct; back 30 Oct 10:46; gone again by 11:02, nothing touched |
| Firmware | 1.4.1 (January 2017) |

## What others have found

- **Altair's own advice for dropped frames.** Altair's help page on a black
  or halted preview names the Hypercam 183C's large frames, and says to
  lower the camera's USB frame-rate setting until it runs smoothly, use a
  region or binning, and take other devices off the same USB controller
  ([altairastro.help](https://www.altairastro.help/black_preview_screen/)).
  It is written for the live preview, but it is the same remedy as speed 0.
- **A port change fixed it for one owner.** A Hypercam 183C review's
  unexplained dropped frames went when the author changed USB port on the
  laptop ([AstroBackyard](https://astrobackyard.com/altair-hypercam-183c-review/)).
- **Timeouts fixed in a driver for the 183M.** Altair's ASCOM driver
  1.4.142.0 "resolves reported timeout issue with Hypercam 183M TEC Camera"
  ([altairastro.help](https://www.altairastro.help/download/ascom-driver-1-4-142-0/)).
  The 183C is not named.

The same camera model with the same fault, and similar cameras that worked
at USB 2 and not at USB 3, are listed with their sources in
[the 21 October record](nights/2026-10-21/camera-stalls.md#what-others-have-found-23-october).

## For guiding

Guided exposures will be 1 to 5 minutes. On 30 Oct, 5 each of 60, 120 and
300 s frames arrived at speed 0 (and at speed 2), so guiding needs no change
to the main camera.
