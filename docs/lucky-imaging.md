# Lucky imaging of the Moon

The Moon has no stars to line frames up on, and the air bends each part of
it differently from moment to moment. The deep-sky stacker (`shoot.py`)
moves each frame as a whole and takes about one a second, so it averages
the blur in. `lucky.py` does what the planetary stackers (AutoStakkert!,
PlanetarySystemStacker, Siril's multi-point mode) do:

    ./ty lucky capture Moon --frames 300 --exposure 0.02 --gain 100 --roi X Y W H
    ./ty lucky stack frames/lucky/Moon-DATE-TIME.ser --keep 20

`capture` puts the camera in its video mode (`AltairCamera.video`: frames
back to back rather than one triggered exposure each), optionally on a
region of the sensor round the Moon, and writes the raw Bayer frames to one
SER file in `frames/lucky/`. It holds the rig like an imaging run, and shows
a frame on the status page every 3 s so the page and the stream are never
blank (the activity phase `lucky` keeps the stream on air).

`stack` reads the colour mosaic as one grey picture at full resolution, with
each colour scaled to the green's level, because the Moon has next to no
colour and the 2×2 colour picture would halve the detail. Then it:

1. ranks every frame by its fine detail (the spread of the Laplacian on a
   lightly smoothed copy, over the bright surface);
2. keeps the best `--keep` per cent (20 by default);
3. builds a reference: the kept frames (up to 50), each moved as a whole
   onto the best, averaged, which has the surface's true shape;
4. lines each kept frame up with it as a whole, by phase correlation on a
   quarter-size copy;
5. then patch by patch: a grid of 96-pixel alignment points 64 pixels apart,
   only where the surface is bright and has detail, each found by phase
   correlation to a fraction of a pixel. Their shifts are spread smoothly
   into a shift for every pixel, and the frame is warped by it;
6. averages the frames, then sharpens at three scales (like a planetary
   stacker's wavelets).

It writes `NAME.stack.fits` (unsharpened), `NAME.sharp.fits` and `NAME.jpg`
beside the video, and puts the picture on the status page.

## The first result, 24 October 2026

The 97 %-lit Moon, 31° up through thin haze: 300 frames of 20 ms at gain
100, from a 2944-pixel square of the sensor, at 4.2 frames a second
(readout Speed 0, which the camera needs for long frames,
`docs/nights/2026-10-21/camera-stalls.md`). The best 60 were kept and lined
up on 1329 alignment points. The stack shows no stripes, and the ray
systems and small craters are much crisper than the deep-sky stack of the
same night. The Moon drifted toward the box's edge in the 10 minutes,
because the mount tracks at the stars' rate and the Moon moves against them.

Not yet tried: faster readout speeds for short frames (Speed 0 may not be
needed below a second), and the handset's lunar tracking rate.
