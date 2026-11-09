# Guide scope focus and the first calibration tries, 8 to 9 November 2026

Gaps in the cloud, haze in between. The 183M cold at -5 °C by the keeper
throughout, warmed slowly at the end.

## Polar alignment

The axis had moved a long way since it was last measured: at 22:02, from
the Double Cluster in 15° steps, **7.9° from the pole** (7.8° too low,
2.6° west). The person raised the latitude about 4 marks and swung the
azimuth; at 22:06, **1.7°** (1.7° too low, 0.7° east), left there (the
drift in a 3 s frame is under a star's size). The 25° step failed: the
third position was blocked or clouded.

## Main scope focus

By hand with `./focus.py` (spoken numbers), from doughnuts 220 px across
to HFR about 2.5 to 3 (4.2"); plate solves worked after that.

## Guide scope focus (first time on stars)

`./guidecam.py focus` was written that evening (4c73244 later made it
speak only numbers and "no stars"): the guide star's size, said aloud each
frame, from 2 x 2 binned frames at USB speed 0.

- At the camera's default gain (100 %) the stars were barely above the
  noise: SNR 7 to 18, peak 6 to 13 of 255. A reading of 1.3 px was a
  fading star at SNR 7, not focus. **Gain 400 % gave SNR 20 to 50.**
- Focused at the Double Cluster through haze to **about 3.1 to 3.5 px
  HFD binned** (about 30", at 9.55"/px), readings jumping about ±0.5 px
  frame to frame on a faint star. Locked there. Forum practice is that a
  guide star of a few pixels is good for centroiding (PHD2 users: under
  about 4 px HFD).
- Not finished: judged on a faint star through haze. **Next clear night:
  centre a bright star (Capella, or one in a clear part of the sky) by
  plate solve so it is in the guide scope's view, and focus again at gain
  400.**

## Guider calibration (`./guidecam.py calibrate --gain 400`)

Three tries, none finished:

1. Double Cluster, 2 s: the west leg passed (11 steps, 0.48 px/s, against
   about 0.42 expected at Dec +57.6), then the star was dropped: "two
   stars about as near (1.8 and 2.4 px): not guessing which" (a crowded
   field at 9.55"/px).
2. Same place, 2 s, haze: the west leg passed (7 steps, 0.67 px/s), then
   the star faded under the SNR to follow it.
3. Mirfak, 3 s: no star found at all. The GoTo put the main scope 1.7°
   from Mirfak (plate solved), so Mirfak was likely outside the guide
   scope's 1.70° x 1.27°; then cloud. Stopped.

So the west pulses do move the star, at about the rate expected; the rest
of a calibration waits for clear sky and an uncrowded field.

## Saturn

At 00:51, 25° up in the WSW: the guide camera saw nothing (the washing
line pole is in the way there) and 0.1 s frames on the 183M showed no
bright object (cloud). Called off at about 01:05.
