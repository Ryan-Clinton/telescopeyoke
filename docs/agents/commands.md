# Commands

`./ty` is the single way in. Every line below accepts `--json`; those marked
*demo* accept `--demo`.

## Read-only (never touch the mount's serial port)

| Command | Returns | Notes |
|---|---|---|
| `ty context` | plain-text briefing | *demo*. Start here. |
| `ty capabilities` | what is available, motion limits, each component's state | |
| `ty status` | mount / camera / imaging / solver states | |
| `ty doctor` | readiness and every check | same as `doctor.py --skip-handset` |
| `ty night` | verdict, clear window, darkness, Moon, best three now | *demo*; fetches weather |
| `ty targets --limit N [--kind K] [--now]` | ranked targets | *demo* |
| `ty target NAME` | where it is now; whether a GoTo is allowed | |
| `ty session [--frames N]` | newest imaging run; frame detail only on request | |

## Asks the handset (opens the serial port; do not run while another command is driving the mount)

| Command | Returns |
|---|---|
| `ty mount status` | `slewing` / `tracking` / `stopped`, position, pier side |

## Planning a move (no hardware needed, nothing moves)

| Command | Returns |
|---|---|
| `ty mount goto NAME --dry-run` | altitude, hour angle, pier side, warnings; or a refusal with a code |
| `ty mount point AZ ALT --dry-run` | the same for a compass bearing |
| `ty mount home\|zenith\|compensate --dry-run` | whether it would move, and what it does |

## Moves the mount (a person must have asked)

`ty mount goto NAME [--solve]`, `point AZ ALT`, `zenith`, `home`, `compensate`.
`ty mount drift` changes the Dec motor's creep. `ty mount stop` halts
everything and is always allowed. `shoot.py` re-centres the target as it
drifts unless given `--no-recentre`.

## Uses the camera, not the mount

`snap.py`, `liveview.py`, `focus.py`, `solve.py`, `skywatch.py`,
`calibrate.py`, `camera_test.py`, `shoot.py --no-recentre`.

## Output rules

- With `--json`, stdout holds exactly one JSON document; anything else is on stderr.
- Exit code 0 means `ok: true`.
- Human-readable output may change freely; the JSON only changes with `schema_version`.
