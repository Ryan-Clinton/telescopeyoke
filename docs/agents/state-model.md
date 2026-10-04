# States, errors and the envelope

## The envelope

Every `--json` answer, web API response and MCP tool result has this shape
(`schemas/envelope.schema.json`):

```json
{"schema_version": "1.0", "ok": true, "command": "status",
 "timestamp": "2026-10-03T22:14:31Z", "data": {}, "warnings": [], "errors": []}
```

`ok` is false exactly when `errors` is not empty. Each error has `code`,
`message`, `retryable` and `advice`.

## States

| Thing | States | Where |
|---|---|---|
| Mount, passive | `offline`, `connected` | `ty status` (does not ask the handset) |
| Mount, live | `slewing`, `tracking`, `stopped` | `ty mount status` |
| Camera | `offline`, `idle`, `capturing` | `ty status` |
| Imaging run | `idle`, `capturing`, `processing`, `finished` | `ty status`, `ty session` |
| Plate solver | `ready`, `unavailable` | `ty status` |
| Component check | `ok`, `warn`, `fail` | `ty capabilities`, `ty doctor` |
| Night | `GO`, `MARGINAL`, `NO-GO` | `ty night` |

The passive mount state is deliberately coarse. Whether it is tracking can
only be learned by asking the handset, and the read-only views never do that,
so they cannot disturb a command that is driving the mount.

## Error codes

Defined in `interface.py`; `schemas/errors.schema.json` lists them.

| Code | Retry? | Meaning |
|---|---|---|
| `MOTION_LOCKED` | no | A `MOTION_LOCKED` file blocks movement. Only a person removes it. |
| `HANDSET_NOT_ANSWERING` | yes | Handset off, on its start-up screens, or lead out. |
| `HANDSET_NOT_SET_UP` | no | Handset still shows its default date; it would move the mount wrongly. |
| `TARGET_UNKNOWN` | no | Not in the catalogue. |
| `TARGET_BELOW_ALTITUDE_LIMIT` | no | Under 20° up. |
| `TARGET_BEYOND_HOUR_ANGLE_LIMIT` | no | More than 5.75 h from the meridian. |
| `TARGET_NEAR_SUN` | no | Within 40° of the Sun while it is up. |
| `ALTITUDE_OUT_OF_RANGE` | no | `point` needs 2° to 89°. |
| `SLEW_TIMED_OUT` | yes | The mount was stopped. |
| `GOTO_REFUSED` | yes | The handset would not accept the GoTo. |
| `PLATE_SOLVE_FAILED` | yes | Cloud, focus, or too few stars. Take a frame and look. |
| `NO_SESSION` | no | No imaging run recorded yet. |
| `NO_SKY` | yes | The horizon survey saw no open sky high up: cap, cloud or exposure. |
| `INVALID_REQUEST`, `INTERNAL_ERROR` | no | Bad arguments; unexpected failure. |

## Sizes

Answers are small by default. `ty session` gives counts and the newest
frame's quality; add `--frames N` for the last N frames. `ty targets` gives
ten; raise `--limit` only when needed.
