# 24 November 2026: the 183M's cooler and its 12 V going in

Indoors, cap on, the camera on the SV241 (USB and, from today, its 12 V
from one of the box's outputs, on the mount's AL-1250 supply). Testing
the theory from 18 and 19 November (`docs/nights/2026-11-19/cooler.md`):
the cooler runs away when its 12 V goes in while it is on. Each test with
the set point a few degrees below the room, so a runaway would show as
the sensor falling past it while still far from freezing
(`./camera_test.py --cooler-on-test`: the cooler off at once if the sensor
fell 3 °C below the set point, the camera's USB power cut if it went on
falling). Before the tests, the camera's USB power was cut for 8 s from
the laptop, which resets its controller, and its 12 V went in with the
camera open and the cooler held off (`--watch-cooler`): 23 °C, 0 V.

| Test | What was done | What happened |
|---|---|---|
| 1, 17:03-17:09 | Cooler on at 19 °C with the 12 V in, settled (18.4-19 °C, 0.3 V); 12 V out about a minute (sensor rose to 22.8 °C, 0 V), then in | 0.7 V at once, the sensor down to 16.9 °C (2.1 °C under), then back to 17.5-18 °C at 0.3 V: **no runaway** |
| 2, 17:10-17:13 | Cooler started at 19 °C **with the 12 V out** (0 V, sensor 21-22 °C) for about 30 s, then the 12 V in: the 19 November start 2 | 0.7 V, the sensor down to 17.4 °C (1.6 °C under), then back up to 18.4 °C at 0.3 V: **no runaway** |

## What it shows

- The runaway did not happen either way, set 3 °C below a 22 °C room. The
  cooler overshoots by about 2 °C when its 12 V arrives, then takes
  control again.
- So "the 12 V going in with the cooler on" is not enough by itself.
  What 19 November had that these tests did not: the keeper's ramp
  stepping the set point down while the cooler had no power (the hold on
  an unpowered cooler came after); a colder set point, 13.8 °C, in a
  colder room; the camera's own Mean Well supply plugged straight into it,
  not the SV241's output; the camera's controller not reset beforehand.
  Unknown which matters.
- The keeper's own guards did not run in these tests (the test command
  sets the target and only watches): its check that closes the camera when
  the 12 V drops, so the cooler is not on when it comes back, and its
  check that the cooler's target has not changed by itself. Since today,
  when the fail-safe catches a runaway or a target changed by itself, it
  also closes the camera and cuts its USB power at the SV241 for 8 s, which
  resets the camera's controller (19 November: what cleared it). Not yet
  seen on a real runaway.
- Not tested: a set point near -5 °C. A runaway there could frost the
  sensor indoors, so it would want the cap on in a cold room and the same
  trip.
