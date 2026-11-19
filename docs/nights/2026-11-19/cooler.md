# 19 November 2026: the 183M's cooler, six starts to get it cold

[All docs](../../README.md) · [Validation](../../validation.md) · [Tonight's tests](test-plan.md)

The 183M Pro TEC took six starts and an hour (16:00-17:03 UT) to begin
cooling: one with no 12 V, two runaways, and two stops on the "12 V lead
out" check with the lead in; the sixth cooled. It held -5.0 °C from about
17:20 and took the flat-darks through the keeper. Times are UT. The fourth and fifth starts
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
  powered by the USB and not by the 12 V, holding the fault. Not yet
  proven: two nights, one reset, and the reset changed two things at once.
  The USB power was cut, and the 12 V went back in with the camera closed
  (at start 3 it had gone in at 16:31 with the cooler on). A daylight
  comparison is needed to tell the two apart.
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
  the cooler has been on `POWER_SETTLE_S`, 60 s.
- `altair.py`: **neither lead-out check could catch start 1.** The first
  needs the kept air temperature 3 °C above the set point, and the ramp
  keeps the set point near the sensor. The second (`NO_POWER_S`) times
  from `held_since`, which each step down of the ramp reset. So the lead
  was out for 30 minutes and only the wait for the target ended it. A
  third check now stops the camera when the cooler has drawn nothing for
  `NO_POWER_S` (2 min) with the sensor above its set point, whatever the
  air: about 3 minutes from the cooler going on, with the 60 s settle.
- `altair.py`: the runaway check stopped only below -7 °C (`TEC_LOWEST`
  less `RAMP_LEAD_C`), whatever the set point, so start 2 reached -7.3 °C
  against +13.8 °C first. That floor stays. A second check stops it when
  the sensor is more than 5 °C below the set point on two readings in a
  row with the cooler at half its power or more. Two readings, so one bad
  reading (18 November, 20:40) does not stop it. Half power or more, so a
  sensor cooled by the air, or the warm-up's rising set point, does not.
- `altair.py`: a kept fault carries its kind (`no_power`, `runaway`,
  `other`), not only its words. A `no_power` fault needs no 10-minute rest
  before `--after-fault`, on the person's go, and its message no longer
  asks for one. Any other fault still rests. A fault kept before the
  kinds is read by its words.
- `altair.py`: the fan's setting is read back as the camera opens, and
  said when it differs.
- All of these act at the next opening of the camera. The keeper that is
  holding it now runs the code it started with, so tonight's cooling is
  unchanged.
- `config.toml` (not in the repository): `fan = "on"` under
  `[cameras.183m]`; `config.example.toml` shows it for a cooled camera.
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
- On the bench: start with the 12 V out (the new check should stop it in
  about 3 minutes), take the lead out mid-ramp, and the USB reset apart
  from the order the 12 V goes in.
- Whether one bad reading can trip the absolute floor (18 November,
  20:40): that check still acts on one reading.
- A whole cycle: a full ramp, the hold all night, the warm-up and a
  restart.
