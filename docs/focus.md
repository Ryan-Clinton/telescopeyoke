# Focusing by ear

[Back to the README](../README.md)

`./focus.py` is built for a manual focuser in the dark: turn the knob, listen.
It measures the half-flux radius (HFR) of up to forty stars at once, steadies
the readings over three frames, and ignores changes smaller than the air's
own shimmer. It says "Improving. 4.8", "No change", "Worse. Go back", and,
when the numbers bottom out and rise again, "Minimum passed. Reverse
slightly", then "Best focus. Hold" when you are back on it. `--tones` swaps
the speech for a tone whose pitch rises as focus improves.
