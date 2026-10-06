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
| `doctor.py --report --skip-handset` | the check as text to post as a hardware report: the system, every check, the site's name left out | no `--json`; without `--skip-handset` it also asks the handset its firmware version and the mount's model, so it then belongs in the next table |
| `ty night` | verdict, clear window, darkness, Moon, best three now | *demo*; fetches weather |
| `ty targets --limit N [--kind K] [--now]` | ranked targets | *demo* |
| `ty target NAME` | where it is now; whether a GoTo is allowed | |
| `ty session [--frames N]` | newest imaging run; frame detail only on request | |
| `ty rigs` | every rig (a telescope with its own settings and files): how its mount is reached, and its newest imaging run | `schemas/rigs.schema.json`. Reads files only. `ty --rig NAME <command>` runs any command for one rig |

## Asks the handset (opens the serial port; do not run while another command is driving the mount)

| Command | Returns |
|---|---|
| `ty mount status` | `slewing` / `tracking` / `stopped`, position, pier side |
| `doctor.py --report --probe PORT` | the hardware report, plus what answers on that one port: a handset, a motor board, or nothing. Questions that only read; no `--json`. Only for a port a person has named |

## Planning a move (no hardware needed, nothing moves)

| Command | Returns |
|---|---|
| `ty mount goto NAME --dry-run` | altitude, hour angle, pier side, warnings; or a refusal with a code |
| `ty mount point AZ ALT --dry-run` | the same for a compass bearing |
| `ty mount home\|zenith\|compensate --dry-run` | whether it would move, and what it does |

## Moves the mount (a person must have asked)

`ty mount goto NAME [--solve]`, `point AZ ALT`, `zenith`, `home`, `compensate`.
Without a handset only: `ty mount directions` tips the tube 5° and back and
asks a person which way it went; `ty mount sethome` records the home position
and moves nothing.
`landmark.py check NAME` turns the mount to the axis readings a landmark was
remembered at and photographs it (`--watch N` keeps looking); `landmark.py
remember NAME` and `list` move nothing. `polaris.py find` looks in rings around the home position, by day, until
Polaris is in view: the RA axis turns up to 88° either side of home on every ring. It waits at a place while the
sky there is not blue, gives up if cloud stays, and brings the star to the middle once found. `polaris.py align` then tips
the tube a tenth of a degree, turns the RA axis to three readings and back, and gives the polar axis's error
roughly. Both take `--dry-run` and `--json`. `polaralign.py` slews about 25° twice and back to measure the polar axis's
error; it checks all three positions against the limits first, and takes
`--dry-run` and `--json`. `ty mount drift` changes the Dec motor's creep. `ty mount stop` halts
everything and is always allowed. `shoot.py` re-centres the target as it
drifts unless given `--no-recentre`.

## Uses the camera, not the mount

`snap.py`, `liveview.py`, `focus.py`, `solve.py`, `skywatch.py`,
`calibrate.py`, `camera_test.py`, `shoot.py --no-recentre`.

`camera_setup.py` gets the camera ready and is safe to run at any time: it
checks the camera is plugged in and has a driver, copies Altair's library
files out of their SDK zip into `vendor/altair/` if they are missing, and
takes one short test frame. `--check` copies nothing and takes no frame.
`--json` gives each step as `{step, status, message}` with `ready` and, when
not ready, `next`: the one thing the person has to do.

## Output rules

- With `--json`, stdout holds exactly one JSON document; anything else is on stderr.
- Exit code 0 means `ok: true`.
- Human-readable output may change freely; the JSON only changes with `schema_version`.
