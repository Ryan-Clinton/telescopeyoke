# The guide camera's dropped frames

[README](../README.md) · [All docs](README.md) · [Validation](validation.md) · [Autoguiding](autoguiding.md) · [The 6 November record](nights/2026-11-06/guide-camera.md)

**Record, 6 November 2026. Open: the cause is not known.** The guide
camera, an Altair GPCAM MT9M034M (mono, 1280 x 960, USB 2, ID `16d0:0b2a`),
will not send a steady stream of frames on this laptop. Guiding needs a
2 s frame every few seconds; it sends one every 3 to 18 s. Until that is
fixed nothing can guide ([Autoguiding](autoguiding.md)).

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

## Not yet tried

In order of how likely each is to help:

1. **Linux's limit on USB transfer memory.** The kernel lets a program
   claim at most `usbfs_memory_mb` of buffer memory for USB transfers; on
   this laptop it is the default, **16 MB**. This is a known cause of
   dropped frames for astronomy cameras on Linux: ZWO, QHY and ToupTek tell
   Linux users to raise it (to 200, or 0 for no limit), and INDI's
   installers do. If the library queues more buffers than that, frames
   break off and it times out, which would give exactly the steady 3 s
   gaps. Raised for a test with
   `echo 200 | sudo tee /sys/module/usbcore/parameters/usbfs_memory_mb`
   (no reboot, and back to 16 at the next reboot), then the same probe.
2. **Smaller frames:** the library's 2 x 2 binning or a 640 x 480 size, a
   quarter of the data per frame.
3. **The library's other settings:** raw mode, the other bit depth, its
   frame-rate limit.
4. **Another computer**, older if possible, with an old SharpCap on
   Windows: the reports above say the camera worked on older PCs.

If none of these gives a steady 2 s stream, the camera cannot guide on
this laptop, and there is no maintained software to fix it.

### How each is judged

- `./guidecam.py probe` before and after each change, with the same
  exposures and the same window, and on the same port: the frames that
  came, the frames that should have, and the longest gap.
- The pass is not one 2 s frame arriving. It is a steady supply over
  several minutes: `./guidecam.py probe --exposures 2 --window 300` giving
  at least 90 % of the frames expected (about 150 in 5 minutes, less the
  readout), with no gap longer than twice the exposure.
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
