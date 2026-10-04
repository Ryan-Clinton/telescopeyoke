# For programs and AI agents

[Back to the README](../../README.md)

Everything a person can read, a program can read too, in one stable shape.
Start with [AGENTS.md](../../AGENTS.md); the details are in the pages beside this one.

```
./ty capabilities                         # what is connected, allowed and locked
./ty status                               # mount, camera, imaging run, system
./ty context                              # a short plain-text briefing for an agent
./mount.py goto M27 --dry-run --json      # what a move would do, without moving
```

- **`--json`** on `mount.py`, `doctor.py` and `tonight.py`, and always from
  `ty`. Every answer is the same envelope: `schema_version`, `ok`, `command`,
  `timestamp`, `data`, `warnings`, `errors`. The shapes are JSON Schemas in
  [`schemas/`](../../schemas/).
- **Error codes that stay put**, such as `MOTION_LOCKED`,
  `TARGET_BELOW_ALTITUDE_LIMIT` and `HANDSET_NOT_SET_UP`, each saying whether
  retrying can help and what to do instead.
- **`--dry-run`** on every command that moves the mount: the same checks, the
  planned move and any warning (such as the tube swinging over the pole), and
  the hardware is never opened.
- **Web API**: `GET /api/v1/status`, `/capabilities`, `/night`, `/targets`,
  `/target/NAME`, `/session/current` and `/context` on the status page's port.
- **MCP**: `./mcp_server.py` over stdio; setup in
  [mcp.md](mcp.md).

The web API and the MCP server are read-only: they can report, plan and
simulate, and cannot move the mount or start the camera. Moving the telescope
from an agent means running `mount.py`, with the same limits as a person and
only when a person has asked for that move.
[`evals/`](../../evals/) holds the situations an agent should handle well; the test
suite checks the interface gives the right answer in each. They have not yet
been run with a model in the loop.

## Also

- `./ty observing` (also `/api/v1/observing` and the MCP tool
  `get_observing_state`): sky, focus, tracking and the imaging run in one
  snapshot, with a note naming the likely cause when quality falls: wider
  stars with a steady count point at focus, fewer stars at cloud or dew,
  less round stars at tracking or wind.
- `--json` on `shoot.py`, `focus.py`, `solve.py`, `restack.py` and
  `horizon.py` too. Progress goes to stderr; stdout carries one envelope at
  the end.
- `shoot.py NAME --dry-run` and `horizon.py --dry-run` say what would happen
  without touching camera or mount.
- Every MCP tool publishes an `outputSchema` built from the files in
  `schemas/`.

## The schemas are a public interface

Field names in `schemas/` do not change casually. New fields may be added
under schema version 1.0. Anything that would break a reader raises the version
to 2.0.
