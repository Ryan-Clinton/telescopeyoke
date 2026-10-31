# The main camera's lost-frame fault

The whole record in one place, from the first sign to the latest test. The
details are in the dated night files linked from each entry.

**The camera:** Altair Hypercam 183C (Sony IMX183 colour), firmware 1.4.1
(January 2017), on USB 3. The camera is Gary's. Altair support ticket #3470.

**The fault:** at speeds 1 and 2 the camera sends each frame back far too
soon, and the software, which takes a frame back before its shutter could
have closed for a stray from an earlier exposure, throws it away and waits
in vain: the frame is counted lost. Found on 31 October 2026 from the USB
traffic recorded in the fault (below, "What the recording showed"); until
then it looked as if the frame never came down the lead. There is no USB
disconnect or reset in the kernel log, and the link stays at 5000 Mb/s.

**What is in use now:** readout speed 2 (`[camera] readout_speed = 2`) since
31 October 2026, after 2,160 frames of 16 s at speed 2 kept (the count
said no loss, but a lost frame tried again and kept was not counted, so
some may have been: below). It is
left at 2 on purpose while the fault is studied: a lost frame is not
covered over by dropping to a slower speed by itself. Each frame's FITS
header says the speed it was read at (`READSPD`). Speed 0 has never lost a
frame plugged in as below, and costs about a second more per frame.

## Hubs and leads: how to plug the camera in

From 30 October 2026 the camera goes through a powered USB 3.2 hub (Realtek
0bda:0411, its own power supply, a power button for each port). What was
found that afternoon:

| Laptop to hub | Hub to camera | Speed 0, 16 s | Speed 2, 16 s |
|---|---|---|---|
| 3 m lead | new 1 m lead | **failed within 2 minutes, three times** (two laptop ports, two hub ports) | failed |
| new 1 m lead | old 1 m lead | **50 of 50** | **50 of 50** |
| old 1 m lead | new 1 m lead | **50 of 50** | **720 of 720** at speed 2, 18:37 to 22:53 |
| none: the 3 m lead straight into the camera | | every frame, all day | lost at 10:46, kept from 11:02 (the fault) |

- **Use the two 1 m leads behind the hub, either way round. Never the 3 m
  lead from the laptop to the hub.** The 3 m lead works straight into the
  camera, but not into the hub. USB 3 is designed for about 3 m a lead and
  the hub re-sends the signal, so it is that lead's length into the hub's
  input, not the total. More reach between the laptop and the hub needs an
  active (powered) USB 3 extension, not a longer plain lead.
- **What the failure looks like.** About a minute or two in, the camera's
  fan stops and the hub's light goes from steady to flashing. The program
  reports "the camera would not be set up: SDK error 0x8000ffff" at any
  speed; the kernel log shows `device descriptor read/8, error -110` and
  resets, then the camera drops off USB.
- **How to get it back.** Press the camera's port button on the hub twice
  (off, then on): the light goes steady and the fan spins up. The library's
  own replug (a software reset, which `altair.py` now tries once) could not
  bring it back; cutting its power did.
- **The lost-frame fault is separate.** It came and went plugged straight
  in, with no hub. The hub results below say what the hub and leads do, not
  what causes that fault.

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
| 30 Oct 17:46 to 18:07 | Same | 50 × 16 s at **speed 2** | **50 of 50**, no USB error |
| 30 Oct 18:11 to 18:29 | The 1 m leads swapped: the **old 1 m from the laptop to the hub**, the **new 1 m from the hub to the camera** (2-1.1) | 50 × 16 s at speed 0 | **50 of 50**, no USB error: the new 1 m lead feeds the camera fine, so the failures were the **3 m lead to the hub** |
| 30 Oct 18:37 to 22:53 | Same; from about 20:00 the focuser's Nano was on the hub too, and its motor turned several times during the run | 720 × 16 s at **speed 2** | **720 of 720**, no USB error in the kernel log: the longest speed 2 run yet without a loss, 4 h 16 min |
| 30 Oct 22:57 to 31 Oct 03:13 | The control: the **3 m lead straight to the laptop**, no hub, laptop port 2-5 (where speed 2 lost a frame at 10:46) | 720 × 16 s at **speed 2** | **720 of 720**, no USB error: the fault stayed away direct as well, so the hub's 720 of 720 does not show the hub cures it |
| 31 Oct 03:13 to 07:29 | Same, run again at once | 720 × 16 s at **speed 2** | **720 of 720**: 2,160 speed 2 frames in a row across the evening and night, hub and direct, without a loss |
| 31 Oct 08:49 to 13:05 | Same, with every USB transfer on bus 2 recorded by usbmon (`logs/usbmon-bus2-20261031.txt`, kept off git) so a loss could be read packet by packet | 720 × 16 s at **speed 2** | **720 of 720**, no USB line in the kernel log; 109,898 of 112,806 transfers completed, the other 2,908 cancelled (-2, as the driver tidies up), none left waiting: 2,880 speed 2 frames in a row without a loss |

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

## What the recording showed, 31 October 2026

At 17:28, after the camera, the focuser's Nano and a thermistor on the
camera's body had been rewired and put back on the telescope, indoors at
about 20 °C on the body, a check of 8 frames of 16 s at speed 2 lost the
first. The probe ran by itself (`cache/camera-probes/20261031-172833/`,
`probe.json` with the USB traffic and the controller's trace):

| In the fault | Result |
|---|---|
| 0.5 s and 1 s frames | kept |
| 1.5, 2, 4, 8 and 16 s frames | lost |
| 2048 × 1536 and 512 × 512 frames of 1.5 s | lost: the frame's size does not matter |
| Video, 20 × 0.05 s | 20 of 20 |
| A 16 s frame waited for 300 s | never kept |
| Speed 1 | lost; speed 0: kept, 21 s after the trigger |
| Port and link | 5000 Mb/s, U0, nothing in the kernel log, before and after |

The USB traffic says what "lost" is. A whole frame (39.7 MB) came down the
lead for every exposure, lost ones included, but early: measured from the
camera's last control request to its first data, a 16 s frame came after
**10.3 s**, where at speed 0 in the fault, and at speed 2 in the healthy
run of the morning, it comes after **20.5 s**: about half. The shorter
exposures came after 0.44, 0.75, 1.07, 1.39 and 2.66 s for 0.5, 1, 1.5, 2
and 4 s, about 0.63 of the exposure each. A frame back before 0.9 of its
exposure is refused by `altair.py` as a stray, so every one from about
1.5 s up was thrown away and the wait ran out. In the fault, then, the
camera's timing at speeds 1 and 2 runs about twice as fast: the exposure
ends early, or the frame is sent before it is taken.

The morning's healthy run (720 of 720 at speed 2, recorded) shows the
same thing at its very start: two frames back after 10.3 s, each followed
by the 108 s wait, and then 20.5 s frames once the camera had been closed
and opened again by the third try. The run's count said 720 of 720
because a frame lost and tried again was not counted. From 31 October
every try again is said in the log, and the loss names the frame that came
back too soon and when.

## What is known

- **Behind the hub, the leads decide it.** With the 3 m lead from the
  laptop to the hub and the new 1 m lead from the hub to the camera, it
  failed at speed 0 within two minutes, three times, on different ports,
  the fan stopping and the hub's light flashing: the camera lost its power,
  or the hub shut its port. With the new 1 m lead from the laptop to the hub
  and the old 1 m lead to the camera, speed 0 kept 50 of 50. The hub has its
  own power supply (the person, 30 Oct), so the camera's power comes from
  it through the lead to the camera, not down the 3 m lead; and the 3 m lead
  ran every direct test that morning, keeping every speed 0 frame. With the two 1 m
  leads swapped (the new one now to the camera) it kept 50 of 50 again, so
  **the 3 m lead to the hub was the cause**: fine straight into the camera
  all morning, but not with the hub at 5 Gb/s. Behind the hub, use the 1 m
  leads.
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
- **Where it is.** Until 31 October everything pointed at the camera's
  SuperSpeed path: the same camera, computer and program work at USB 2 and
  fail at USB 3, and a slower readout keeps it working. The recording made
  in the fault moves it: whole frames came down the lead intact in size,
  only too soon, so the lead and the link carry the data and it is the
  camera's timing at speeds 1 and 2 that goes wrong. Ranked, as a guide to
  what to test, not as measured odds:
  0. The camera's timing at the fast readouts: the clock or setting its
     FPGA or the sensor uses at speeds 1 and 2, or the firmware that sets
     it (1.4.1, 2017). A clock running at twice its rate fits a frame back
     in half the time, speed 0 unaffected, and a state that holds through
     closing and opening the camera and clears by itself.
  1. The camera's USB 3 bridge chip or its high-speed signal path on the
     board. It fits the link staying at 5000 Mb/s, but not frames arriving
     whole and early.
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
  on 30 October the fault showed within minutes of the camera being plugged
  in. On 31 October it showed on the first frame of two runs: the morning's,
  where closing and opening the camera cleared it on the third try, and
  the 17:28 check, where it did not, even after the probe's own close and
  open. It has not been seen to begin partway through a test that was
  passing, though until 31 October a frame lost and kept on a retry would
  not have been seen.
- **Whether the frame sent early is a real, shorter exposure.** Not yet
  looked at: `altair.py` throws it away (next tests, 1).
- **Whether speed 0 can ever fail.** It has not yet, in every test since
  23 Oct.

## Next tests

In order. Each says what it needs.

1. **Keep the frame sent too soon, in the fault, and look at it.** With
   light on the camera (cap off, an even glow), the frame that comes back
   after 10.3 s of a 16 s exposure is kept instead of thrown away and set
   beside a good 16 s frame and an 8 s one. About half the light: the
   exposure itself ends early. The right light but sent early: the
   timing of the transfer only. Noise or stripes: the readout is broken.
   Needs the fault (it may still be there just after it shows) and a small
   change to the probe; about two minutes.
2. **Image at speed 2 and watch.** From 31 October, so a night's imaging
   is itself the test. If frames are lost, it is seen at once (`./ty
   watch-run`) and the person decides whether to go back to speed 0.
3. **Through a powered USB 3 hub.** Done on 30 Oct (above): on the 1 m leads
   speed 2 kept 50 of 50, and then 720 of 720 over 4 h 16 min (18:37 to
   22:53), with the focuser on the hub as well. But the control straight
   to the laptop on the 3 m lead, port 2-5, also kept 720 of 720 (22:57 to
   03:13), and 720 of 720 again (03:13 to 07:29) and a third time with the USB traffic recorded (08:49 to 13:05): the fault was away that night, so the hub is not shown to cure
   it. Those counts did not count a frame lost and kept on a retry, and the
   recorded run lost its first frame that way, twice. If speed 2 holds through the hub for whole nights, power
   or signal conditioning moves up the list of causes.
4. **The ports, one at a time.** The same 50 frames of 16 s at speed 2 on
   each of the laptop's USB 3 ports in turn; the fault log records which.
   Needs the person's hands to move the plug.
5. **Everything at once, the moment a frame is lost** (`camera_probe.py`,
   from 31 October 2026). With `[camera] probe_on_loss = true`, the first
   frame lost by any run (imaging, a speed test) is followed at once by
   about ten minutes of looking at the camera in that state, before it can
   clear, and the person is told on their phone:
   - the USB controller's state of each port (link state U0 to U3, error
     flags), the camera's versions and temperature and the kernel's USB
     messages, before and after;
   - the bus's traffic (usbmon) and the controller's own events (the
     xhci-hcd trace) throughout: whether the laptop was waiting on a frame
     the camera never sent, or never asked for it;
   - whether a frame is still lost; the shortest exposure lost, from
     0.5 s to 8 s (23 October: 1 s arrived, 2 s did not);
   - part of the sensor (2048 x 1536 and 512 x 512) at that exposure: the
     amount of data or the wait;
   - the camera's video mode, frames back to back;
   - one frame waited for five minutes: lost, or only late;
   - the same exposure at speeds 1 and 0, and a last one at the speed lost.

   The readout speed is not changed for what follows: the fault is to be
   seen, not covered over. Results in `cache/camera-probes/STAMP/`
   (`probe.json`, `usbmon.txt`, `xhci-trace.txt`) and a line in the fault
   log. `./camera_test.py --probe` runs it by hand. Root comes from
   passwordless sudo; without it the captures are left out. Two things
   still need hands: pressing the hub's port button twice (does cutting
   the power clear it?) and warming the camera gently with a hairdryer.
   First caught on 31 October at 17:28 (above). The camera reports no
   temperature of its own; from that evening a thermistor on its body
   reads it through the focuser's Nano (`./focuser.py temp`): 20.3 °C just
   after the probe.
6. **AltairCapture's Diagnose, on Windows, camera plugged straight in**, as
   Altair asks of support customers. Needs the Windows boot and AltairCapture
   installed.
7. **Another Hypercam 183C on this laptop, or this one on another
   astronomy computer.** Needs a second camera or computer.

## For Altair (ticket #3470)

The camera is Gary's; the ticket is ours, and paying for a repair would be his call. In short:

| | |
|---|---|
| Computers | laptop and desktop PC |
| Systems | Ubuntu (INDI, Altair's library) and Windows 11 (Altair's SDK 60.31589) |
| Leads | four: 3 m, 1 m, a new one, and the 3 m again |
| USB 2 mode | 2 s and 16 s frames arrive |
| USB 3, speed 0 | every frame has arrived, in every test since 23 Oct |
| USB 3, speed 2 | frames lost at times, as short as 2 s; the link stays at 5000 Mb/s, no disconnect |
| What a lost frame is | in the fault the frame comes back in about half the time: a 16 s frame after 10.3 s instead of 20.5 s, at speeds 1 and 2, not 0 (USB recorded, 31 Oct) |
| Started | 04:59 on 20 Oct 2026, at dawn after a cold night |
| Comes and goes | gone 26 Oct; back 30 Oct 10:46; gone again by 11:02, nothing touched; back 31 Oct 17:28 just after the camera was handled and replugged, and still there after closing and opening it |
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
