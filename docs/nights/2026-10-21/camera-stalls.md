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
backend = "altair"`) on the 3 m lead again. 1 s frames mostly arrived in
their normal 2.5 s, with a stall every few minutes. 16 s frames never
arrived: the M31-P6 patrol run waited from 04:39:51 with no frame for
more than five minutes. After a restart, the 0.1 s test frame took 28 s,
and a single 16 s frame then failed to arrive within 90 s. The kernel log
shows no USB disconnect.
