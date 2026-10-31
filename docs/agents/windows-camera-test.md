# Brief: the camera's timing fault in Altair's own program, on Windows

For a Claude session on the laptop's Windows 11 boot (the project is at
`C:\Users\Facepipe\telescopeyoke`; `git pull` first). Ryan is at the
laptop. Read `docs/camera-fault.md` ("The scan", "What is known") first.

**The question.** On Linux, through Altair's library, the camera has been
in a state since 31 October 17:28 where at readout speed 2 an exposure
gathers light for half as long as at speed 0 (speed 1: two thirds), while
reporting the full time. Does Altair's own program, AltairCapture, show
the same with the same camera? If it does, the fault is the camera's or
Altair's, not this project's; that is the point to put to Altair (ticket
#3470, Ryan's own; the camera is Gary's).

**What is set up.** The camera on the telescope, plugged into the powered
USB hub, the telescope pointing at something evenly lit through kitchen
roll. No mount, no focuser: nothing here moves anything.

## Steps

1. **Is AltairCapture installed?** If not, say so to Ryan and stop at
   step 4; installing software is his to agree to.
2. **Altair's Diagnose file.** AltairCapture has a Diagnose (or "Diagnose
   File") option in its menus; Altair asks support customers for it. Make
   one with the camera plugged in, and say where it was saved.
3. **The light comparison in AltairCapture.**
   - The light: a steady lamp in the room (not the laptop's screen, which
     AltairCapture's own window is on), the kitchen roll over the
     telescope's end. Nothing in the room changes during the test.
   - In AltairCapture: raw (RAW/16-bit) if it offers it, gain as low as it
     goes, auto exposure off, an exposure of **8 s**, and the frame-speed
     (USB speed, "Frame Speed Level") setting at its **slowest** (speed 0).
     Take one frame and save it as FITS or TIFF.
   - The same at the **fastest** setting (speed 2), and at the middle one
     (speed 1). Then speed 0 again, to show the light did not change.
   - Ask Ryan to time each with a phone stopwatch if AltairCapture shows no
     progress: from the start of the exposure to the frame appearing.
   - Compare the frames' mean levels (any program that reads FITS or TIFF;
     the project's Python with astropy or Pillow is fine). Speed 2 at about
     half of speed 0, speed 1 at about two thirds, means AltairCapture shows
     the fault too. About equal means it does not.
   - If the frames are white (saturated), shorten the exposure to 2 s and
     repeat; if barely above black, raise the gain a step.
4. **The project's own test on Windows** (Altair's Windows library, no
   light needed): `python camera_test.py --order` from the project folder
   (about 3 minutes; `[camera] backend = "altair"` must be set in its
   `config.toml`; do not read that file whole, look only at `[camera]`).
   Each way's line says whether a 16 s frame at speed 2 came back short
   (about 10.4 s: the fault) or full.

## Afterwards

Write what was found, with the figures (each frame's mean, the times, the
library version AltairCapture shows, the Diagnose file's path) in
`WINDOWS-RESULTS.md`, commit and push it (title by what it found; no
"round", "audit" or "ChatGPT" in the message). Then tell Ryan in two or
three lines, and that he can boot back into Ubuntu.

## Rules

- Never move the mount or the focuser.
- Never send anything to Altair or anyone else: Ryan does that.
- If a step fails twice, stop and tell Ryan rather than working round it.
