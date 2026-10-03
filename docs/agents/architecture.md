# Architecture

One implementation, several ways in:

```
                  ┌── scripts' human output
core functions ───┼── --json (interface.py envelope)
(sky, mount,      ├── ty (one command)
 stacking, ...)   ├── serve.py: status page and read-only /api/v1
                  └── mcp_server.py: read-only MCP tools
```

- `sky.py` computes positions and scores targets with astropy; `feeds.py`
  fetches weather, seeing, light pollution and comets, cached on disk.
- `mount.py` speaks the SynScan handset's serial protocol. It measures the
  handset's clock error, keeps a pointing error from plate solves, and
  applies the limits. `tracking.py` models drift from a rough polar
  alignment. `simulator.py` stands in for the handset in tests and `--demo`.
- `indi.py` is a small INDI client; `camera.py` turns it into "give me a frame".
- `stacking.py` holds calibration, star measurement, registration and
  stacking; `shoot.py` uses it live, `restack.py` afterwards on the saved raws.
- `agent.py` gathers read-only facts for programs; `interface.py` defines the
  envelope, error codes and states.

State on disk: `cache/` (feeds, handset clock, pointing error, drift model,
last plate solve), `frames/NAME/<date-time>/` (raw frames, logs, stacks),
`web/` (the page, pictures, `status.json`), `calibration/` (master frames).
