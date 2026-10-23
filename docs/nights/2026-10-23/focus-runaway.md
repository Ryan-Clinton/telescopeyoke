# 23 October 2026: a night's observing lost to the focuser, by Claude

The person set the telescope up at ralphie-side, set focus **just a touch
out** from the Sharpie line, ready for small steps in, the method proved on
20 October 2026 (two coils, 30 ms a half-step), and went out in the cold.
The sky was clear. Claude lost the night.

## What Claude did

- 20:16, on M29: `./focus.py --check` measured HFR 13.36 against 2.28.
  Claude called that "well out", over the person's word that it was
  slightly out (a few tens of microns makes HFR 13).
- 20:17: `./focus.py --motor`, the full sweep, with the step (256) and
  overshoot (1536) still only guesses. It winds the drawtube out 1536 to
  2560 half-steps before each sweep. Stars vanished at nearly every
  position, and Claude said it looked like cloud. The sky was clear: it
  was the focuser ([log](2017-motor-m29.log)).
- 20:23: Claude stopped it part way, sent the mount to Vega and started
  `--motor` again, then stopped that part way too
  ([log](2023-motor-vega.log)).
- The person found the drawtube about **an inch** from where they had set
  it, the wrong way, and packed up. Nothing was imaged: Tabby's star and
  the M31 and M33 patrols were missed.

## Why

The lesson was already learnt, in the 20 October daytime session and on
21 October ([record](../2026-10-21/focuser.md)): small step out, tiny steps
in, and a sweep's big moves wind the drawtube off. It reached neither the
focus skill nor the setup routine, which still said `--motor`, and
nothing in the code stopped a move an inch from focus.

## What now stops it

- **A safety hook** (`.claude/hooks/guard.py`, `small-focus`, 986d5be):
  Claude's shell refuses `focus.py --motor`, `--sweep`, `--find`,
  `--measure-step` and `--measure-backlash`, shortened or wrapped, and any
  `focuser.py move` over 64 half-steps.
- **The focus skill, setup routine and first-night guide** (cbe9f13 to
  0cbd91b): "set just a touch out" means `./focus.py --walk-in`, nothing
  else; stars lost during a run mean the focuser, not cloud.
- **focus.py** (merged with this record): every move within `[focuser]
  travel` (512 half-steps) of the start, a sweep refused while its sizes
  are guesses, a run that loses its stars goes back to its start, and a
  stopped sweep returns to its start; a stopped walk-in stays where it is.
