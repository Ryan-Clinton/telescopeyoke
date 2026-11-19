# 19 November 2026: tonight's tests

[All docs](../../README.md) · [Validation](../../validation.md) · [The guide camera window](guide-camera-window.md) · [The focuser's first light](../2026-11-18/focuser.md)

The after-dark tests owed from the last few days, in the order they run
tonight, each started as soon as the sky allows. There is no deadline.
Afterwards the night's imaging follows, with the camera kept cold: there
is no warm-up between the tests and the imaging. Times are UT.

Sky: clear expected from about 16:15, for about ten hours. Nautical
twilight at 17:00 (stars bright enough for Vega); astronomical dark at
18:25.

## What changed since last night

- **Dec balance:** Gary's reading of the 18 November guiding graph was
  that Dec was not happy, most likely from the balance. A stand-in for the
  top dovetail bar (ordered, not here): 1 kg of sand in bags taped to the
  tube, 700 g at the back end, 300 g on the side opposite the guide scope.
- **The focuser's 12 V lead** was pulled tight on 18 November and may
  have held the tube back in Dec. For the guiding tests it is unplugged:
  the drawtube holds by friction with the driver off.
- **The guide camera** can read a 512 x 960 window at full resolution
  (4.77"/px) when the USB speed is set before the stream starts
  ([record](guide-camera-window.md)). Guiding still runs binned (9.55"/px);
  only the comparison in step 5 uses the window.
- **Plate-solve frames** are binned 2 x 2 on the 183M since today.

## The order

| # | When | What | Command | Hands |
|---|---|---|---|---|
| 0 | Dusk | Mount on at home, the time set, the camera keeper started early so the 183M is at -5 °C by 17:00, the focuser's 12 V in | `./mount.py status`, `./mount.py settime`, `./keeper.py start` (background) | Switch-on, 12 V lead |
| 1 | ~17:00 | GoTo Vega with a plate solve. Also the binned solve frames' check: each solve line's frame time against 18 November's 1.5-3.6 s, the solves still succeed, the keeper holds -5 °C | `./mount.py goto Vega --solve` | |
| 2 | Next | Focus: measure first, then the far-focus search on the sky (untried since 6055f3d), then the walk-in. The final HFR is step 8's baseline | `./focus.py --check`; `./focuser.py move 1600`; `./focus.py --find`; `./focus.py --walk-in` | |
| 3 | ~17:15 | ~~The focuser's 12 V lead out~~ Skipped: the owner taped the lead to the mount clear of the tube (19 November, before dark), so it stays in for the guiding tests | | |
| 4 | ~17:15-17:35 | **The balance test, matched to 18 November.** NGC 7662 then sits at the hour angle Capella had for last night's run (-2.7 h, east side; Dec +42.5 against +46), so the mount carries the tube the same way | `./mount.py goto "NGC 7662" --solve`; `./guidecam.py guide --recalibrate --minutes 10 --exposure 2 --gain 400`; `./guidegraph.py` | |
| 5 | Next | **The window comparison:** the same star binned, then at full resolution in the 512 x 960 window; the wander of each in arcseconds. No pulses | `./guidecam.py star --count 30 --compare-window` | |
| 6 | Next | **Dec guided one way**, then the same with **the pile-up cap**; a graph each | `./guidecam.py guide --minutes 10 --exposure 2 --gain 400 --dec-one-way WAY`, then with `--dec-stuck 3`; `./guidegraph.py` after each | |
| 7 | If asked for | A 50 g bag of sand moved, if the graphs say the balance is off; then step 4 again | | Yes |
| 8 | Next | **Does the drawtube hold focus** with the driver off and the 12 V out? | `./focus.py --check`, against step 2 | |
| 8a | After the guide scope tests (asked by the owner, 19 November) | The focuser's 12 V is already in (step 3 skipped) | | |
| 8b | Next | **Focus in every filter:** a walk-in in each of L, R, G, B, Ha, SII, OIII, each filter's focus position in steps, so the offsets between them are known, not assumed parfocal | `./focus.py --walk-in --prove-sets` | |
| 8c | Next | **Moving between filters, practised:** L to each other filter and back, a walk-in each time, kept as measurements of each set's offset; repeated so each offset has a scatter | `./focus.py --walk-in --offset FILTER`, for R, G, B, Ha, SII, OIII, then again | |
| 8d | Next | **The gears' slack (backlash) and the sweep step**, measured on the stars: how many steps the motor turns before the drawtube follows, each way | `./focus.py --measure-backlash`, then `--measure-step` | The guard refuses both today (`small-focus` in `.claude/hooks/guard.py`); it needs the owner's word to allow these two for this step |
| 9 | After | The night's imaging, the camera cold | | |

WAY in step 6 is the way the polar drift pushes Dec (the option's own
help), read from step 4's guiding: which way its Dec pulses mostly went.
On 18 November nearly every Dec pulse went south.

## What each is judged against

| Test | Last time | Better means |
|---|---|---|
| Balance (step 4) | 18 November, Capella: Dec slack 12.1 ± 4.6 s at calibration; RA 2.03" RMS, Dec 9.23" RMS; the guider stopped at 10' of Dec correction | Less Dec slack, Dec RMS well down, RA unchanged, no stop |
| Window (step 5) | Not yet run | The window's wander in arcseconds near or below the binned one's, the star found and kept |
| Dec one way, pile-up cap (step 6) | Not yet run since the service | A smaller Dec sawtooth, not only a smaller RMS |
| Far-focus search (step 2) | 18 November: confused by the star leaving the frame | Ends at the smallest rings, or stops and says the star left |
| Focus held (step 8) | 18 November: held, not measured | HFR within the usual scatter of step 2's |
| Solve frames (step 1) | 18 November: full frames, 1.5-3.6 s | Shorter, solves still succeed, -5 °C held |

## Not tonight unless the owner says

- `./focus.py --measure-backlash` and `--measure-step`: the guard refuses
  them until they are allowed.
- The overnight test of the guide camera's window: the guide camera
  guides all night; it is a daytime test instead.

Results go in this folder, and a result that changes what is proven
is linked from [validation](../../validation.md).
