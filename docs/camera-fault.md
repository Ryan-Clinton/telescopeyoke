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
the output says this in words.

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

## What is ruled out

- **The lead.** Two leads failed on 21 to 23 Oct; a new lead and the old 3 m
  one both passed on 26 Oct.
- **The laptop, Linux, INDI or this project's code.** It failed under
  Windows with Altair's own SDK, and on the desktop PC.
- **The mains supply.** It failed on battery too.
- **Dirt on the socket.** No change after cleaning it.
- **Cold.** It failed indoors and warm on 30 Oct, eight hours after passing
  outside.
- **The length of the frame.** 16 s frames were lost at speed 2 at 10:46 and
  kept at 14:40; 60 to 300 s frames passed at speed 2 in between.
- **Needing a power cycle to clear it.** On 30 Oct it was lost at about
  10:47 and gone by 11:02 with the camera plugged in throughout.

## What is known

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

## What is still open

- **What brings it on.** Neither cold nor warmth does on its own. Damp was
  suggested on 26 Oct (the camera drying out after the dawn of 20 Oct); it
  is not ruled out, but it does not explain a change within 15 minutes
  indoors.
- **Where it is.** The likeliest places are the camera's USB 3 socket (five
  extra contacts that can be marginal) or its USB 3 chip: both fit "worse
  when pushed harder" and "fine at USB 2".
- **Whether the first frames after the camera is opened matter.** At 10:46
  the fault showed within minutes of the camera being plugged in; it has not
  been seen to begin partway through a test that was passing.
- **Whether speed 0 can ever fail.** It has not yet, in every test since
  23 Oct.

## What others have found

The same camera model with the same fault, and similar cameras that worked
at USB 2 and not at USB 3, are listed with their sources in
[the 21 October record](nights/2026-10-21/camera-stalls.md#what-others-have-found-23-october).

## For guiding

Guided exposures will be 1 to 5 minutes. On 30 Oct, 5 each of 60, 120 and
300 s frames arrived at speed 0 (and at speed 2), so guiding needs no change
to the main camera.
