# The guide camera's dropped frames

[README](../README.md) · [All docs](README.md) · [Validation](validation.md) · [Autoguiding](autoguiding.md) · [The 6 November record](nights/2026-11-06/guide-camera.md)

**Record, 6 November 2026. Found a working setting, late that evening:
2 x 2 binned (640 x 480) at the camera's USB speed 0 it streams 2 s
frames steadily.** The guide camera, an Altair GPCAM MT9M034M (mono,
1280 x 960, USB 2, ID `16d0:0b2a`), will not send a steady stream of
full-size frames on this laptop: at 2 s it sends one every 3 to 18 s.
Binned and slowed, it sent 149 of 150 in 5 minutes ([below](#what-cured-it)).
The guider opens it that way since 79a2f2d; nothing has guided yet
([Autoguiding](autoguiding.md)).

## What works

| What | When |
|---|---|
| Found on USB and opened, by the oaCapture project's libaltaircamlegacy 1.24.11330 only (no current Altair or ToupTek library opens this early model, on Linux or Windows) | 2 November 2026 |
| Single frames at 1, 10 and 100 ms, the level rising with the exposure | 2 November 2026 |
| Its ST4 port moves the mount all four ways (`./guidecam.py pulse`) | 6 November 2026 |

The 2 November test took one frame at a time, so the fault did not show:
the first frame after the camera is opened arrives before the library's
timeout. It showed when the guider first asked for a run of 2 s frames.

## What fails

`./guidecam.py probe` sets an exposure and counts the frames that arrive.

### On the hubs

The camera on the unpowered Trust hub, on the 183M's internal hub; the
filter wheel unplugged. Frames in 12 s:

| Mode | 0.1 s | 0.5 s | 1 s | 2 s |
|---|---|---|---|---|
| Video, USB speed 4 of 4 | 19, gaps up to 3.1 s | 1 | 1 | 0 |
| Video, USB speed 0 | 6, gaps up to 3.2 s | 2 | 1 | 0 |
| Software trigger, speed 0 | 4, one about every 3.2 s | 2 | 1 | 0 |

`./guidecam.py snap` agreed: single frames at 0.5 and 0.8 s came, others
at 0.6, 0.95 and 1 s timed out.

### On a laptop port, no hubs

Moved to the laptop's own port (`1-1`) at 20:22; frames in 30 s:

| Exposure | Expected | Video | Software trigger |
|---|---|---|---|
| 0.01 s | about 3,000 | 72 | 9 |
| 0.05 s | about 600 | 35 | |
| 0.1 s | about 300 | 14 | 9 |
| 0.5 s | about 60 | 1 | 2 |
| 1 s | about 30 | 2 | 2 |
| 2 s | about 15 | 1 | 2 |

"Expected" is the window divided by the exposure, an upper bound that
leaves out the readout: no USB 2 camera sends 3,000 frames in 30 s. The
fair yardstick is the rate the camera holds at short exposures once it
streams (at 640 x 480, below: 110 frames in 12 s at 0.1 s).

The same as on the hubs, so **the hubs are not the cause.**

### The pattern

- Frames come in twos and threes, then nothing for about **3.2 s**, again
  and again, at every exposure. In trigger mode it is one frame each
  3.2 s, whatever the exposure.
- At 0.5 s and longer the gaps grow to 13 to 18 s.
- A gap that does not depend on the exposure looks like a timeout inside
  the library: it waits about 3 s for a frame that never arrives whole,
  gives up and starts again. Most frames are lost, not late.
- The kernel log has no USB errors or disconnects in that time.
- The library allows exposures of 0.18 ms to 800 s, so 2 s is in range.

## Ruled out

| What | How |
|---|---|
| The hubs, and the filter wheel sharing them | The same on a laptop port with no hubs |
| USB power saving | Autosuspend is off for the camera's port (`power/control` = `on`) |
| The camera's USB speed setting | The same at 0 and 4 of 4 |
| Video against software trigger mode | Both fail the same way |
| An exposure out of range | The library allows up to 800 s |
| A slow USB link | `lsusb -t`: the camera is at 480M, high speed |
| Linux's USB transfer memory (`usbfs_memory_mb`) | Raised from 16 to 200 MB: the same, 30 frames in 12 s at 0.1 s and none at 2 s |
| The library's conversion of each frame | Raw mode: no better (10 frames in 12 s at 0.1 s, none at 2 s) |
| Errors the library saw | Its events, now listed by the probe: only "image", no error and no timeout, in every run. The frames that go missing never reach it. `PullImage` answers E_FAIL while no frame is ready (585 to 2 S_OK in 6 s), so E_FAIL means "not yet" with this library; any other code is named when a frame does not come |

## What others have found

The same symptom is reported for these early GPCAMs, on Windows as well:

- **Webastro, 2018 to 2022** [1]: this model (GPCAM MT9M034M) in PHD2:
  "after 17 s the camera did not complete a 1 s exposure", images
  arriving irregularly. A GPCAM2 290M there: 0.1 s fine in SharpCap, but
  frames lost with gaps of about 20 s at 1.5 s. The MT9M034M worked on its
  owner's old PC and failed on a new laptop, "with or without the hub, on
  a USB2 or USB3 port". New drivers, other ports and other cables did not
  help; one owner was cured by a powered hub, another was not. No fix was
  confirmed.
- **PHD2 forum** [2]: an Altair GPCAM gave "one frame in every 4-8 sec" and
  "seems to work best on 0.5s exposure", with timeouts. Newer Altair
  drivers improved it without fixing it.
- **Support has gone:** Altair's later software was reported incompatible
  with "the very oldest models" [3]; the earliest MT9M034 needs an old
  SharpCap (2.9 or 3.0) [3][4]; some MT9M034M do not work with INDI at
  all [5]. Here, no current Altair or ToupTek library opens it (2 November
  2026).

What fits: this early camera's firmware and its old library do not get on
with newer computers' USB, more than a fault in this one camera. None of
the reports proves which.

## What cured it

6 November, about 21:00 to 21:30, on the laptop's own port, filter wheel
unplugged, `usbfs_memory_mb` at its default 16. One change at a time:

| Setting | 0.1 s, frames in 12 s | 2 s |
|---|---|---|
| 1280 x 960, speed 4 (as before) | 33, gaps up to 3.1 s | 1 in 12 s |
| 1280 x 960, `usbfs_memory_mb` 200 | 30, gaps up to 2.3 s | 0 in 12 s |
| 1280 x 960, raw | 10, gaps up to 2.8 s | 0 in 12 s |
| **640 x 480 (`--size 1`), speed 4** | **110, gaps up to 0.44 s** | 137 in 300 s (91 %), gaps up to 6.0 s |
| **640 x 480, speed 0 (`--size 1 --speed 0`)** | | **149 in 300 s, gaps up to 2.08 s, none over 4 s** |

The last row passes the test below. Every probe opens the camera afresh,
and it streamed the same way each time that evening.

What it means: a full frame is too much for this camera and its library
to send whole on this laptop; a quarter of the data, sent more slowly,
gets through. The library's own table says size 1 is 2 x 2 binning
(ratio 2/1), not a crop, so the guider still sees the whole field, at
about 9.6"/px through the 162 mm guide scope instead of 4.8"/px. Binning
also adds four pixels' light to each.

## Still to do

1. **The guider on the sky.** Since 79a2f2d `star`, `calibrate` and
   `guide` open the camera this way (`GUIDE_SIZE` 1, `GUIDE_SPEED` 0 in
   `guidecam.py`), at 9.55"/px, and calibrations record their binning.
   Built, not yet run.
2. **With the filter wheel plugged in** on the same hub as before, the
   10-minute test in [Autoguiding](autoguiding.md), hardware step 1.

If binning had not cured it, the next step would have been another
computer, older if possible, with an old SharpCap on Windows: the reports
above say the camera worked on older PCs.

### How each is judged

- `./guidecam.py probe` before and after each change, with the same
  exposures and the same window, and on the same port: the frames that
  came, the frames that should have, and the longest gap.
- The pass is not one 2 s frame arriving. It is a steady supply over
  several minutes: `./guidecam.py probe --exposures 2 --window 300` giving
  at least 90 % of the frames expected (about 150 in 5 minutes, less the
  readout), with no gap longer than twice the exposure.
- The library's own events, which the probe now lists: no error, no
  "no frame timeout" and no "no packet timeout" in the run.
- One change at a time, so a cure can be put down to what did it.

### The filter wheel is a separate question

On 6 November the filter wheel and the guide camera also failed together
on the unpowered Trust hub: the wheel never finished its power-up turn.
That is a power question about the wheel on that hub. The dropped frames
happen with no hub and no wheel, so curing one says nothing about the
other; both have to pass before a guided night (the wheel and guide
camera together for 10 minutes, [Autoguiding](autoguiding.md), hardware
step 1).

## For a return

If it goes back, the plain description: "On Linux, with the only library
that still opens this model, frames do not stream: at 2 s exposures one
frame arrives every 3 to 18 s, on the laptop's own port and on hubs alike;
at 0.1 s, bursts of two or three frames then a 3 s gap. Single short
frames and the ST4 port work."

## Sources

1. [Webastro: Souci cam Altair GPCAM](https://www.webastro.net/forums/topic/161088-souci-cam-altair-gpcam/) (in French)
2. [PHD2 forum: Altair gpcam slow frame rate](https://groups.google.com/g/open-phd-guiding/c/YC5hjW3ePKs)
3. [SharpCap forum: MT9M034 not being recognised](https://forums.sharpcap.co.uk/viewtopic.php?t=3114)
4. [Cloudy Nights: GPCAM MT9M034M mono guide camera](https://www.cloudynights.com/forums/topic/788126-gpcam-mt9m034m-mono-guide-camera/)
5. [INDI/Stellarmate forum: Altair cameras not compatible](https://casite-460905.cloudaccess.net/forum/stellarmate/6497-altair-astro-hypercam-183c-protec-not-compatible.html)
