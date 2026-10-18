# 18 October 2026: focus logs

The telescope at ralphie-side. Before dark the motor focuser was taken off,
nuts on it tightened, the camera taken off and its sensor cleaned. Every
focus attempt of the evening is here, by start time. Positions are in
half-steps of the motor (4096 to a turn, plus is out), counted from where
that run started.

| File | What it was |
|---|---|
| `1907-hand-aid.log` | `focus.py --numbers`, the spoken hand aid, on Deneb in twilight: HFR 36. Stopped; the motor was on USB all along |
| `1919-motor.log` | `focus --motor`, fixed steps. Out 1344 with HFR flat at 15 (the motor slipping outward), then stars lost coming in. Lines as read mid-run |
| `1940-motor.log` | After a nut was loosened. No stars anywhere in reach; a hot pixel read as HFR 0.67; the closing message wrongly said "back where it started" |
| `1945-search-in.log` | Half turns in, a check after each: stars back at -6144 |
| `1953-motor-runaway.log` | First version with steps sized from HFR. Readings stuck at ~22 (the measuring box, not the star) set a step size from one dip; it went five turns in before being stopped |
| `2005-search-out.log` | Half turns out, a check after each: HFR 22-23 all the way |
| `2015-hand-aid.log` | Hand focusing back to HFR ~6 |
| `2020-motor.log` | From HFR ~6: readings jumping 4-10 from frame to frame made big steps near focus |
| `2027-motor-deneb.log` | Small steps near focus on Deneb: readings 3.5-8 for 32-step moves, ended 5.43 |
| `2031-motor-double-cluster.log` | On the Double Cluster: steadier, best 2.87 |
| `2101-sweep-slipped.log` | The new fitted sweep (`focus.py --sweep`), first time on the sky. Started at HFR 3.25 ±0.03; its first move out (2560 half-steps) slipped the coupler, and every point after read 7.2-7.5: the drawtube was not following the motor |
| `2109-sweep-no-stars.log` | After the coupler was refitted: no stars at any point (HFR over 12 or none); focus had moved |

The code changes made during the evening are the commits of 18 October in
`focus.py` and `tests/test_focus.py`.
