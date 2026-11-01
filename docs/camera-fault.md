# The main camera's lost-frame fault

The whole record in one place, from the first sign to the latest test. The
details are in the dated night files linked from each entry.

**The camera:** Altair Hypercam 183C (Sony IMX183 colour), firmware 1.4.1
(January 2017), on USB 3. The camera is Gary's. Altair support ticket #3470.

**The fault:** at speeds 1 and 2 the sensor gathers light for less than
the time asked, and the frame arrives sooner than an exposure that long
could. Two different measurements show the two halves: the light in the
frame (the light test and the timed light, below) says how long the sensor
gathered; when the frame came down the lead says only when it was sent.
The software, which takes a frame back before its shutter could have
closed for a stray from an earlier exposure, throws the early frame away
and waits in vain, so it is counted lost. Found on 31 October 2026 from the USB
traffic recorded in the fault (below, "What the recording showed"); until
then it looked as if the frame never came down the lead. There is no USB
disconnect or reset in the kernel log, and the link stays at 5000 Mb/s.

**What is in use now:** readout speed 2 (`[camera] readout_speed = 2`) since
31 October 2026, after 2,160 frames of 16 s at speed 2 kept (the count
said no loss, but a lost frame tried again and kept was not counted, so
some may have been: below). It is
left at 2 on purpose while the fault is studied: a lost frame is not
covered over by dropping to a slower speed by itself. Each frame's FITS
header says the speed it was read at (`READSPD`). On 1 November, outside
at 6 °C, it was **speed 0** for the night (`readout_speed = 0`, the probe
off), because speed 2 lost almost every frame; but speed 0 lost frames
too, and the camera jammed until its power was cut, again and again.
Speed 0 kept every frame from 23 to 31 October; it is no longer to be
trusted for a run left to itself.

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

**The same 0.63 was measured before the fault "started".** On 13 October
2026, through INDI, each second asked for added 0.63 s to a frame at speed
2, 0.86 s at speed 1 and 1.25 s at speed 0, and a 10 s frame's star trails
showed the shutter open for 6.43 s (`cache/camera_timing.json`;
`camera.shutter_share()` has asked INDI for longer since). In the fault on
31 October the shares were 0.63 at speed 2, and at speed 0 a 16 s frame
took 21 s, about 1.3 s a second, as on 13 October. In the healthy state
on 31 October, speed 2 took 20.5 s, also about 1.3 s a second, like speed
0. So the likeliest reading: the camera has two states at speeds 1 and 2.
In one the exposure is timed right; in the other (13 October all night,
and the fault since 20 October) it is cut to about 0.63 at speed 2, 0.86
at speed 1, and the frame really is shorter (the trails). INDI took those
short frames as they came; Altair's library route in `altair.py`, used
since October 4 on Windows and later on the laptop, refuses a frame back
before 0.9 of its exposure, so there the same state is a "lost" frame. Not
yet shown: that INDI's lost and late frames of 20 to 22 October are the
same state (INDI has its own waits), and when the laptop's runs moved from
INDI to the library.

The morning's healthy run (720 of 720 at speed 2, recorded) shows the
same thing at its very start: two frames back after 10.3 s, each followed
by the 108 s wait, and then 20.5 s frames once the camera had been closed
and opened again by the third try. The run's count said 720 of 720
because a frame lost and tried again was not counted. From 31 October
every try again is said in the log, and the loss names the frame that came
back too soon and when.

## The light test, 31 October 2026, evening

The fault was still there at 18:37 and 18:51. The cap was off, kitchen roll
taped over the front, a room light; the probe ran twice, at 16 s (too
bright: white) and at 4 s, the light then steady (the first and last 4 s
frames read 464 and 453). Gain 1500, as always. Records:
`cache/camera-probes/20261031-183704/` and `20261031-185138/`, each with
the frame sent too soon kept as a FITS file.

| Frame | Came back after | Mean light | Light a second asked |
|---|---|---|---|
| speed 2: 0.5, 1, 1.5, 2, 4, 8 s | 0.8, 1.1, 1.2, 1.5, 2.8, 5.3 s (the last four refused as too soon) | 58, 116, 173, 235, 464, 938 | 116, the same at every length |
| speed 1: 4 s | 4.0 s (kept) | 611 | 153 |
| speed 0: 4 s | 5.8 s (kept) | 908 | 227 |

- **The exposures really are shorter.** Against speed 0's 4 s frame, a
  speed 2 frame holds **0.51** of the light and a speed 1 frame **0.67**,
  in the same light seconds apart. The speed 2 frames' light grows in step
  with the time asked, from 0.5 to 8 s, so the whole exposure is scaled,
  not a fixed part lost.
- **Frames that were kept are short too.** The 0.5 and 1 s frames at speed
  2 and the 4 s frame at speed 1 arrived late enough to pass, and hold the
  same reduced light. So in this state frames have been accepted with too
  little exposure, as the star trails of 13 October showed at speed 2.
- **The camera does not know.** It reports the full time asked as its real
  exposure (`get_RealExpoTime`: 16,000,000 µs for a 16 s frame sent after
  10.4 s), and no setting it will read differs from the healthy state but
  the exposure, the frame rate it is working out and its packet count.
- **The light ratios sit a little below the timing ratios** (0.51 and 0.67
  against 0.63 and 0.86, though 0.51 / 0.67 = 0.76 and 0.63 / 0.86 =
  0.73). Speed 0 is the reference here, and whether speed 0 itself
  exposes exactly the time asked is not known: the timed light (next
  tests, 4) or the same test with the camera healthy would settle it.
- Still to see: the same test in the healthy state, where speed 2 should
  hold the same light as speed 0 if the fault is the whole story.

## The timed light, 31 October 2026, evening

The fault still there. The telescope, camera in it on the hub, pointed at
the laptop's screen through kitchen roll; `./camera_test.py --timed-light`
(`cache/camera-probes/timed-20261031-193822/`). The first run, at gain
1500, was too bright (the steady frames white), but its flashes were not:
at speed 2 the flash from 9 to 11 s of a 12 s exposure left the frame at
exactly the dark level (1,043 against 1,044), so the exposure had stopped
before 9 s; at speed 0 the same flash came through whole. Run again at
gain 100, for a 12 s exposure:

| Speed | Gathered light for | Of the time asked | The late flash |
|---|---|---|---|
| 0 | 15.4 s | 128 % | seen whole |
| 1 | 10.4 s | 86 % | seen (but see below) |
| 2 | 8.3 s | 69 % | not seen |

- **Speed 0 is not right either: it exposes about 28 % long.** 13 October's
  timing gave 1.25 s a second asked at speed 0, and the healthy speed 2
  frame of the morning came back after 20.5 s for 16 s, about 1.28. So the
  camera's timing is off at every speed, and in the fault speeds 1 and 2
  go short.
- **Against speed 0, speed 1 gathers 0.67 and speed 2 0.54**, as the light
  test found (0.67 and 0.51): two ways of measuring agree.
- **Two readings are doubtful.** Speed 1's late-flash frame holds nearly
  the light of its steadily lit frame, and speed 2's dark frame five times
  the others'. A light in the room that changed between frames would do
  both; steady room light cancels out of the figures.
- **What follows for frames already taken:** EXPTIME has not been the time
  the sensor gathered light at any speed. At speed 0 a frame holds about
  1.28 times its EXPTIME; at speed 2 when healthy probably the same, and in
  the fault about 0.69 times. Relative photometry (a star against the
  others in the same frame, as the transits and Tabby's star use) is not
  touched by this, and nor is a frame's depth: `depth.py` measures each
  frame's limiting magnitude from the Gaia stars in it, not from EXPTIME.
  What is: what is worked out from the exposure time itself, such as the
  depth `depth.py --model` predicts for an hour of frames, and the middle
  of each exposure, which assumes the shutter is open from the time the
  frame was asked for for EXPTIME (a 16 s frame's middle could be off by
  a second or two, far less than a transit's timing needs). The figures
  of this table are estimates: two readings were doubtful and the flashes
  were timed by the laptop, not by an independent clock.
- **Two questions now, not one.** Why the exposure is scaled at every
  speed (speed 0 too), and why speed 2 switches between two timings
  (20.5 s and 10.3 s for a 16 s frame). The second may be a state the
  camera comes up in when it is opened, not a failing part.
- **Frames already taken.** Each frame keeps EXPTIME as the time asked,
  with READSPD and, from 31 October, TY_BACK beside it; nothing writes a
  guessed real exposure. Frames at speed 2 from before 23 October (the
  nights of 13 to 20 October, when the camera was very likely in the same
  state: the trail test of 13 October) probably gathered about 0.63 of
  their EXPTIME, frames at speed 0 since 23 October about 1.27 times it.
- **No correction by a fixed factor.** A factor right for one state would
  be badly wrong in the other. `altair.py` applies none. The INDI route's
  `camera.shutter_share()` does (0.643 at speed 2, from the trails of 13
  October); it is not in use while `[camera] backend = "altair"`, and is
  not to be turned on for the same reason.

## The scan, 31 October 2026, night

The fault still there (speed 2's frames sent too soon). The telescope at
the laptop's screen through kitchen roll, gain 100, `./camera_test.py
--scan`: 8 s exposures, a 1 s flash moved through each by 1 s and past its
end, at each speed (`cache/camera-probes/scan-20261031-210553/`).

| Speed | Starts gathering | Stops | Gathered | Of the time asked |
|---|---|---|---|---|
| 0 | 0.5 s after it is asked for | 10.7 s | 10.2 s | 1.27 |
| 1 | 0.4 s | 7.3 s | 6.8 s | 0.86 |
| 2 | 0.4 s | 5.5 s | 5.1 s | 0.63 |

- **The window is shortened, not moved.** Every speed starts about half a
  second after the exposure is asked for; only the end differs. These
  flashes were timed from the request, and the camera is triggered a little
  after it (the exposure time is set and the pipes emptied first), so the
  true start after the trigger is somewhat less than half a second; the
  lengths are not affected. From 1 November the scan times each flash from
  the trigger itself.
- **The shares are 13 October's** (1.25, 0.86, 0.63 from timings and star
  trails), so the camera was in this state that night as well.
- **Against speed 0, speed 1 gathers two thirds and speed 2 exactly half**
  (the dark frames, lit only by the black screen, keep the same ratios:
  70.6, 47.5, 35.2). As if the exposure were timed with speed 0's clock
  while the sensor reads at speed 1's or 2's. In the healthy state of the
  morning, speed 2 took as long as speed 0 (20.5 s for 16 s, about 1.28).
  So the likeliest mechanism: how the camera's firmware or Altair's
  library sets the exposure timer for each readout speed, right in one
  state and wrong in the other.
- **A speed 1 frame can pass as kept and still be short:** they arrived
  7.18 s after the trigger, just past the 7.15 s check, having gathered
  6.8 s.
- This answers the timed light's doubtful readings: the scan's figures
  agree with it (8.3 of 12 s at speed 2 is 0.69; here 0.63, with 1 s
  flashes resolving the end to a few tenths of a second).

## Outside, 1 November 2026, 00:00 to 01:10

The telescope outside at the ralphie-side spot, clear overhead, the camera
on the hub (2-1.1, then 2-5.1 after the hub's lead was moved), its body at
**6.1 °C** by the thermistor at 01:10 (about 20 °C indoors earlier).

- **00:14, speed 2:** the focus walk-in's 1 s frames were lost, and so were
  1.5 and 2 s ones in the probe that followed
  (`cache/camera-probes/20261101-001458/`). On 31 October, indoors, 1 s
  frames at speed 2 had still been kept: outside, cold, the fault reached
  shorter frames.
- **00:17, speed 0:** after that probe was stopped part way, a check at
  speed 0 lost its frame too (`20261101-001657/`): the camera jammed at
  every speed, as AltairCapture's live view had on Windows. Five seconds
  without power at the hub's port button cleared it: at 00:20 speed 0 kept
  2 of 2 frames of 4 s, and `readout_speed = 0` was set for the night.
- **00:21 onward, speed 0:** the first frame or two after the camera is
  opened are often lost and a retry gets through (the walk-ins' logs,
  `logs/walkin-20261101*.log`: 13 retries in seven runs); once, at 00:39,
  three tries in a row failed (the camera "hung") and another power cut
  cleared it. The probe that starts at the first loss was turned off for
  the night (`probe_on_loss = false`): it held the camera ten minutes at a
  time while the person stood outside, and the fault was already recorded.
- **01:08, speed 0, 16 s frames:** the M31 patrol's first two frames were
  each lost after waiting 108 s. **Speed 0 losing 16 s frames had not been
  seen before** (every test since 23 October kept them).

So outside and cold the fault is worse: speed 2 loses even 1 s frames, and
speed 0, the speed that never failed, loses some, and the camera jams in a
way only cutting its power clears.

## What is known

- **The exposures really are shorter in the fault, and speed 0's are
  longer than asked.** Against a clock, a 12 s exposure gathered light for
  about 15.4 s at speed 0, 10.4 s at speed 1 and 8.3 s at speed 2 (the
  timed light, estimates). Speed 0 keeps every frame, but its exposures
  are not the time asked either.
- **Frames arrive whole.** In the fault, a full 39.7 MB frame came down the
  lead for every exposure, lost ones included: the lead and the link carry
  the data. What arrives early is a frame that was also exposed short.
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

- **The faster the readout, the more it fails.** Speed 0 lost no frame
  from 23 to 31 October; outside and cold on 1 November it lost some,
  16 s ones included, and the camera jammed at every speed. Speed 1 has
  lost 16 s frames and kept 2 s ones. Speed 2 has lost frames as short as
  1 s.
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
  1. The camera's exposure timing: the clock or settings its FPGA or the
     sensor uses for each readout speed, or the firmware that sets them
     (1.4.1, 2017). It fits every measurement: the light gathered is
     scaled with the time asked at every speed (speed 0 long, 1 and 2
     short), and at speeds 1 and 2 by more in a state that holds through
     closing and opening the camera and clears by itself.
  2. How that state is entered: something set differently when the camera
     starts (the morning's run came right after the camera was closed and
     opened; the evening's stayed wrong through it).
  3. Less likely now, since whole frames cross the lead in the fault: the
     camera's USB 3 bridge chip, its socket or solder joints, its power,
     and the host's port. They explained "frames that never come", which
     is not what happens. The one sign left for them is the camera that
     stopped answering USB altogether behind the hub on 30 October.
- **Whether the first frames after the camera is opened matter.** At 10:46
  on 30 October the fault showed within minutes of the camera being plugged
  in. On 31 October it showed on the first frame of two runs: the morning's,
  where closing and opening the camera cleared it on the third try, and
  the 17:28 check, where it did not, even after the probe's own close and
  open. It has not been seen to begin partway through a test that was
  passing, though until 31 October a frame lost and kept on a retry would
  not have been seen.
- **What the camera does differently in the two states.** The scan shows
  the exposure is timed as if by speed 0's clock in the fault; what sets it
  right in the other state is not known. Not the order the speed and the
  time are set in, not closing and opening the camera, and not five
  seconds without power (31 October); the morning's healthy state came
  after a night's run, and the fault has cleared by itself before (30
  October, within a quarter of an hour).
- **Whether the cold or the time since power-on brings it on.** Speed 0
  failed for the first time outside at 6 °C on 1 November; indoors and
  warm it has failed at speeds 1 and 2 as well. Whether the failures
  follow the camera's temperature, or the time since it was last powered,
  or neither, is not known (next tests, the warm and cold run).
- **Whether the jams and the short exposures are one fault.** The
  exposure scaled at speeds 1 and 2, and the camera jamming at every speed
  until its power is cut, may be two faults, not one.

## Next tests

In order. Each says what it needs.

The aim now is why the exposure is scaled, not how to stop the timeout
it causes. The check that refuses a frame back before 0.9 of its exposure
stays: taking those frames would hide the fault, not mend it, and the
light test showed that frames it lets through can be short as well.

Three questions now lead, all about the camera's timing rather than its
lead: is the exposure asked for read the same way at every speed and on
both routes (INDI and Altair's library)? Does the camera really expose for
only about 0.63 of the time at speed 2 in the fault? And what changes when
it goes from one state to the other? Until they are answered, no repair or
replacement is to be asked for on the strength of a USB fault: the frames
cross the lead whole. The USB recording cannot answer the third by itself:
the library scrambles its control requests differently each time the
camera is opened (the same request read `5ff6` in one capture and `ece0`
in another), so the camera's own readable settings are compared instead.

0. **AltairCapture on Windows, the same light comparison** (brief:
   `docs/agents/windows-camera-test.md`). Tried 31 October, 22:25 to
   23:28 (`WINDOWS-RESULTS.md`, `altaircapture-diagnose-2026-10-31.txt`):
   the project's `--order` test through Altair's Windows library gave 10.4 s
   for every 16 s frame at speed 2, all five ways, as on Linux. In
   AltairCapture itself (4.12, the same library), Trigger Mode, 8 s at
   speed 0, gain 100: the progress bar reached 8 s and no frame came back,
   twice; its live view had already frozen at frame 29. So Altair's own
   program lost frames as well, but the camera was stuck by then and the
   light comparison was not made. Still to do: the camera unplugged and
   plugged in again, then AltairCapture first, Trigger Mode, 8 s at speeds
   0, 2, 1 and 0. Whether Altair's own program
   shows the half-length exposures at speed 2: if it does, the fault is
   the camera's or Altair's, not this project's. Altair's Diagnose file in
   the same sitting.
0b. **Warm and cold, with the temperature and the time since power-on**
   (`./camera_test.py --cooldown`, cap on). From 1 November each set of
   frames also keeps the camera's body temperature from the thermistor
   (the camera has none of its own) and the minutes since it last appeared
   on USB. Run indoors from warm, then carried outside, the same lead,
   hub and settings throughout: whether failures follow the temperature,
   the time since it was powered, or neither. Needs the person's time.
1. **Done 31 October (above): the scan, at speeds 0, 1 and 2, while the fault is present**
   (`./camera_test.py --scan`, the telescope at the laptop's screen through
   kitchen roll, room lights off, about 40 minutes). Where the sensor's
   window starts and ends after the exposure is asked for, at each speed:
   shortened, moved, or both. Then the same with `--repeat 3 --between
   reopen` and `--between replug`: whether the state survives the camera
   being started again. Needs the fault, and the person's time.
2. **Done 31 October, about 21:25: the order the camera is told things in**
   (`./camera_test.py --order`, about 3 minutes, needs the fault). Every
   way came back short, 10.4 s for 16 s: the speed then the time, the time
   then the speed, the stream stopped and started, by way of speed 0. Then
   the camera's power was cut at the hub's port button for five seconds
   (back on USB at 21:29:40) and the test run again: every way still short.
   Neither the order of our commands nor a power cut clears the state; it
   held from at least 17:28 to 21:30. The same 16 s at
   speed 2 set four ways: the speed then the time (as every frame is
   taken), the time then the speed, the speed set with the stream stopped
   and started (as when the camera is opened), and by way of speed 0. When
   each frame comes back says its state (10.3 s short, 20.5 s full). Our
   own calls are the same in both states, in the same order every time
   (`altair.py` sets the speed before the stream starts and the time before
   each frame), so it is the camera or the library that differs; this asks
   whether any order puts it right.
3. **Done: keep the frame sent too soon, in the fault, and look at it.** With
   light on the camera (cap off, an even glow), the frame that comes back
   after 10.3 s of a 16 s exposure is kept instead of thrown away and set
   beside a good 16 s frame and a 10 s one. About 0.63 of the light: the
   exposure itself ends early, as the trails of 13 October showed, and the
   fault is that state. The right light but sent early: the
   timing of the transfer only. Noise or stripes: the readout is broken.
   Answered on 31 October (the light test, above): the early frames are
   real, shorter exposures. The probe keeps such a frame as
   `early-16s.fits` each time it runs.
4. **Every frame says when it came back** (from 31 October): the FITS
   header's `TY_BACK`, seconds from the trigger to the frame arriving: 20.5
   for a healthy 16 s frame at speed 2, 10.3 in the fault. So an ordinary
   night's frames show when the camera changes state. (What the camera
   reports as its real exposure is only the time asked, so it is read once
   in the probe's settings, not stamped on every frame.)
5. **Every setting, in both states** (from 31 October): the probe reads
   every setting the camera will give (the named readings and every
   readable option) before it starts and after it ends, and lists those
   that changed. One reading taken in the fault and one when healthy is
   the comparison of the two states: `./camera_test.py --probe` run by hand
   while healthy gives the second (it says the fault had already cleared,
   and keeps the settings). Among them are the frame rate the camera works
   out and the exposure range (`HZ` among them is the anti-flicker light
   frequency, 60 Hz, 50 Hz or DC, not a clock, as an earlier version of
   this page had it). The readout mode (integrate while reading or then
   reading), bandwidth and precise frame rate options exist in Altair's
   library but this camera does not answer them; the
   sensor's own clock dividers and timing registers are not readable
   through Altair's library, and its USB requests are scrambled, so those
   stay with Altair.
6. **A timed light** (`./camera_test.py --timed-light`, from 31 October):
   the laptop's own screen is the light, a window over the whole screen
   switched between black and white within a frame (about 1/60 s); `--light
   NAME` uses a Hue light instead, slower to switch (a tenth of a second or
   more). The camera, cap off, faces the screen through kitchen roll in a
   dark room. At each of speeds 0, 1 and 2, four 12 s exposures: dark, the
   light on throughout, a 2 s flash starting 1 s in, and a 2 s flash ending
   1 s before the time asked. The steady frame over the early flash (both
   less the dark) times 2 s is how long the sensor gathered light, against
   a clock rather than against speed 0; the late flash says whether the
   exposure was still running at the end of the time asked. A frame sent
   too soon is measured as well. A light's delay in switching is the same
   on and off, so it moves the flash without changing its length. Needs
   the fault for the faulty state, and the healthy state for the other.
   Each measurement keeps the camera's timing settings beside it (the
   exposure asked and reported, the speed, the frame rate, the trigger
   mode).
   - The laptop's screen is the light (`--light NAME`: a Hue light).
     **No LED or other light driven by a microcontroller will be built or
     bought for this.** It was suggested, for a clock independent of the
     laptop, and turned down on 31 October: the laptop's clock is good to
     well under a millisecond and the screen switches within about 1/60 s,
     so a 2 s flash is timed to about 1 %, which is all these tests need.
     The flashes the scan and the timed light use are the screen's.
   - **Where the window is:** `./camera_test.py --scan` moves a 1 s flash
     through an 8 s exposure and past its end, 1 s at a time, at each
     speed, and reports when the sensor starts and stops gathering after
     the exposure is asked for. A scaled exposure and a moved one shorten
     a frame alike; the scan tells them apart.
   - **Again after each start:** `--repeat 3 --between reopen` (the camera
     closed and opened again between runs) or `--between replug` (dropped
     from USB and found again by Altair's library) shows whether the
     timing is fixed or a state the camera comes up in. Cutting its power
     needs hands: the hub's port button pressed twice, then the same run.
7. **Image at speed 2 and watch.** From 31 October, so a night's imaging
   is itself the test. If frames are lost, it is seen at once (`./ty
   watch-run`) and the person decides whether to go back to speed 0.
8. **Through a powered USB 3 hub.** Done on 30 Oct (above): on the 1 m leads
   speed 2 kept 50 of 50, and then 720 of 720 over 4 h 16 min (18:37 to
   22:53), with the focuser on the hub as well. But the control straight
   to the laptop on the 3 m lead, port 2-5, also kept 720 of 720 (22:57 to
   03:13), and 720 of 720 again (03:13 to 07:29) and a third time with the USB traffic recorded (08:49 to 13:05): the fault was away that night, so the hub is not shown to cure
   it. Those counts did not count a frame lost and kept on a retry, and the
   recorded run lost its first frame that way, twice. If speed 2 holds through the hub for whole nights, power
   or signal conditioning moves up the list of causes.
9. **The ports, one at a time.** The same 50 frames of 16 s at speed 2 on
   each of the laptop's USB 3 ports in turn; the fault log records which.
   Needs the person's hands to move the plug.
10. **Everything at once, the moment a frame is lost** (`camera_probe.py`,
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
11. **AltairCapture's Diagnose, on Windows, camera plugged straight in**, as
   Altair asks of support customers. Needs the Windows boot and AltairCapture
   installed.
12. **Another Hypercam 183C on this laptop, or this one on another
   astronomy computer.** Needs a second camera or computer.

## For Altair (ticket #3470)

The camera is Gary's; the ticket is ours, and paying for a repair would be his call. In short:

| | |
|---|---|
| Computers | laptop and desktop PC |
| Systems | Ubuntu (INDI, Altair's library) and Windows 11 (Altair's SDK 60.31589) |
| Leads | four: 3 m, 1 m, a new one, and the 3 m again |
| USB 2 mode | 2 s and 16 s frames arrive |
| USB 3, speed 0 | every frame arrived from 23 to 31 Oct; outside at 6 °C on 1 Nov it lost frames, 16 s ones included, and jammed until its power was cut |
| USB 3, speed 2 | frames lost at times, as short as 2 s; the link stays at 5000 Mb/s, no disconnect |
| What a lost frame is | in the fault the frame comes back in about half the time: a 16 s frame after 10.3 s instead of 20.5 s, at speeds 1 and 2, not 0 (USB recorded, 31 Oct) |
| The light in it | in the fault, against speed 0 in the same light: speed 2 frames hold 0.51 of it, speed 1 frames 0.67, scaled with the time asked from 0.5 to 8 s; the camera still reports the full exposure (31 Oct, cap off) |
| Against a clock | timed flashes of light from a screen, 12 s asked, in the fault: speed 0 gathered 15.4 s (128 %), speed 1 10.4 s (86 %), speed 2 8.3 s (69 %), and a flash at 9 to 11 s did not reach the speed 2 frame (31 Oct) |
| Where the exposure falls | a 1 s flash moved through 8 s exposures, in the fault: all speeds start gathering 0.4 to 0.5 s after the request; speed 0 stops at 10.7 s, speed 1 at 7.3 s, speed 2 at 5.5 s: 1.27, 0.86 and 0.63 of the time asked, speed 2 exactly half of speed 0 (31 Oct) |
| In one line | in one state, which comes and goes, the exposure at speeds 1 and 2 is timed as if by speed 0's clock: a 1 s flash moved through 8 s exposures shows speed 2 gathering exactly half as long as speed 0, speed 1 two thirds, all starting 0.4 to 0.5 s after the request; the camera reports the time asked throughout. Is this a known behaviour of firmware 1.4.1 or of the library at these speeds? |
| Seen before | an Altair 183C Pro owner on SharpCap's forum, December 2023: exposures ending at 50-70 % of the time asked, recorded at full length (forums.sharpcap.co.uk, topic 7304); was it ever resolved? |
| Altair's own program | AltairCapture 4.12 with altaircam.dll 60.31589 on Windows 11 (31 Oct): two 8 s Trigger Mode frames at Frame Speed 0 never arrived, the live view frozen; Altair's Windows library gave the same short 16 s frames at speed 2 as on Linux. Diagnose output attached (`altaircapture-diagnose-2026-10-31.txt`) |
| Started | 04:59 on 20 Oct 2026, at dawn after a cold night |
| Comes and goes | gone 26 Oct; back 30 Oct 10:46; gone again by 11:02, nothing touched; back 31 Oct 17:28 just after the camera was handled and replugged, and still there after closing and opening it |
| Speed 0 | kept every frame from 23 Oct to 31 Oct; outside on 1 Nov at 6 °C it lost 16 s frames and the first frames after each opening, and jammed until its power was cut |
| Firmware | 1.4.1 (January 2017) |

## A replacement being considered, 1 November 2026

After the night of 1 November (the camera jamming at every speed, speed 0
failing outside, focus fought for hours around it), a replacement is
tempting: a used **ZWO ASI294MC Pro**, about £450 to £520 on eBay. Nothing
is bought yet; the 183C is a friend's, and Altair's answer on #3470 (an
update with the measurements above was written for it on 1 November) may
still change things.

What it would mean here, from its published specification:

- **A bigger field:** a 4144 × 2822 sensor of 4.63 µm pixels, about
  1.5° × 1.0° on the 150P (750 mm), against the 183C's 1.0° × 0.67°, at
  about 1.27" a pixel. M31 fits better, and the patrol would need new
  references for the new field.
- **Cooled:** the sensor held at a set temperature (needs a 12 V supply of
  about 3 A for the cooler, besides USB), so its temperature stops being a
  variable and darks match from night to night.
- **A USB 3 socket to the computer and a two-socket USB 2 hub on the
  camera** for the other kit (the focuser's Nano, a guide camera), one lead
  down from the telescope instead of the powered hub whose USB 2 side
  dropped again and again on 1 November.
- **Software:** ZWO cameras work through INDI (`indi_asi_ccd`), the route
  `camera.py` already uses; `altair.py` would not be needed for it.

Worth checking on a used one: that the 12 V lead comes with it, and the
sensor window for condensation or hot pixels, the usual faults of used
cooled cameras.

## What others have found

- **The same symptom on another Altair 183C, 2023.** On SharpCap's forum
  (["Altair 183C ascom driver"](https://forums.sharpcap.co.uk/viewtopic.php?t=7304),
  29 December 2023), the owner of an Altair 183C Pro, using the native
  driver, wrote that frames of 7.9 s were taken after about 5 s and frames
  of 60 s after about 30 s, each recorded at the full time: "any exposure
  only reaches 50-70%". The SharpCap developer had not seen it before and
  suggested other leads, no hub and a lower USB speed. No cause or fix was
  posted. A different program and a Pro model, but the same fingerprint:
  short exposures recorded at full length.
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
