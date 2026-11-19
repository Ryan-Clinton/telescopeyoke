# 19 November 2026: the 183M's cooler, five starts to get it cold

[All docs](../../README.md) · [Validation](../../validation.md) · [Tonight's tests](test-plan.md)

The 183M Pro TEC took five starts and an hour (16:00-17:03 UT) to begin
cooling: one with no 12 V, two runaways, and two stops on the "12 V lead
out" check with the lead in. Times are UT. The fourth and fifth starts
are in the agent's logs only; the figures below are copied from them.

## What happened

| Start | What ran | What it read | What stopped it |
|---|---|---|---|
| 1, 15:58 | `./calibrate.py dark` (the flat-darks) | the 12 V lead not plugged in: the cooler at 0% for 30 min, the sensor warming 10.8 to 15.6 °C | the run's own 30 min limit on reaching the target; no frames kept |
| 2, 16:29 | the same, started again by the agent before the lead was in | 13.2, 14.7 °C, the cooler at 0%; **the lead went in with the cooler on**, then -7.3 °C against a set point of 13.8 °C | the fail-safe: "the cooler is not obeying its set point" |
| 3, 16:43 | `./keeper.py start --after-fault`, after the 10 min rest | 10.6 °C, set point 11.0; then -8.8 °C against 11 °C within a minute, -8.8 again at the forced off | the same fail-safe: a runaway again, as on 18 November at 20:28 |
| (reset) ~16:50 | the person: 12 V out, the 183M's USB out 30 s and back in, then the 12 V in with the camera closed | | |
| 4, 16:54 | the keeper again | 10.0 °C, set point 9.5, the cooler at 0%: **no runaway** | the "lead out" check (`POWER_GONE_S`, 15 s of 0% with the kept air figure 13 °C over 3 °C above the set point) |
| 5, 17:02 | the keeper again, with `fan = "on"` now set for the 183M | 9.3 °C, set point 8.8, 0% | the same check after 15 s |
| 6, 17:03 | the keeper, with the check waiting 60 s after the cooler goes on | 9.6, 8.8, 7.6, 7.2 °C by 17:05, falling about 1 °C a minute down the ramp | still cooling at the time of writing |

## What it shows

- **The runaway follows the 12 V going in while the cooler is on**, as
  Gary said on 18 November. Start 2 was that: the lead went in during a
  run. The runaway then **survived the 10-minute rest** (start 3), as it
  did on 18 November. **Cutting the camera's USB power cleared it**: start
  4 obeyed its set point. That points to the camera's own controller,
  powered by the USB and not by the 12 V, holding the fault. Two nights,
  one reset: not yet proven.
- **The "lead out" check stopped a camera whose lead was in, twice.** In
  the first 15 s, with the first set point only 0.5 °C below the sensor,
  the cooler drew 0%. Given 60 s, it cooled. So the check judged too
  soon. Unknown: whether the cooler draws nothing at first because of the
  small gap or because it takes time to start.
- **The fan:** the 183M's section of `config.toml` had no `fan` setting,
  so its fan was never set when it opened (the `fan = "on"` was under the
  old `[camera]`, the 183C's). On a ToupTek-made camera, the fan going off
  also turns the cooler off ([AlpacaBridge
  #1993](https://github.com/open-astro/AlpacaBridge/issues/1993)). Start
  5 tripped with the fan set on, so the fan did not cause starts 4 and 5.
  It is set on from now on.

## What changed

- `altair.py`: the "lead out" check (`POWER_GONE_S`) judges only once
  the cooler has been on `POWER_SETTLE_S`, 60 s. A lead truly out is
  still caught within about 75 s, and by the two-minute check
  (`NO_POWER_S`) as before.
- `altair.py`: a fault where the cooler drew nothing needs no 10-minute
  rest before `--after-fault`, on the person's go. After a runaway the
  rest stands.
- `config.toml` (not in the repository): `fan = "on"` under
  `[cameras.183m]`.
- How the agent failed: it restarted start 2 on "oh yeah I didn't plug
  it in", which meant the lead was still out. That is now a rule in its
  memory. It also told the person twice that a powered hub could cut the
  camera's power. That hub was returned on 1 November, and the notes
  that still read as if it were in use are corrected (dc13f02).

## Still owed

- The bench procedure in daylight: what Gary described. 12 V out, the
  camera warmed in software with its cooler off, the 12 V in, then the
  ramp. The SV241 power box, due on 20 November, can switch the 12 V from
  the laptop, so that order no longer needs hands (daylight checks 7
  and 12).
- Whether one bad reading can trip the runaway fail-safe (18 November,
  20:40): unchanged tonight.
