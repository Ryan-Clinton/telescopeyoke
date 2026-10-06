# telescopeyoke: notes for coding and operating agents

A lightweight telescope automation system for Linux, and for Windows where
the tests pass but no hardware has been run yet: night planning, SynScan
mount control, plate solving, focusing and stacking, on a laptop left beside
the telescope. `README.md` is the user's guide; this file is the map for
agents. Deeper notes are in `docs/agents/`.

## Start here

```bash
./ty context            # a short briefing: tonight, hardware, imaging run, the motion rules
./ty capabilities --json
./doctor.py --json      # what is installed and connected
./doctor.py --report    # the same as text to post as a hardware report; the site's name is left out
pytest -q               # about three minutes; needs no hardware
```

Everything runs without a telescope: `./tonight.py --demo`, `./serve.py --demo`,
`./ty mount --demo goto M27`. `./app.py --demo` (or `TY_DEMO=1` before any
command) is the full demo: a pretend mount, camera and sky from
`simulator.py`, with the real focusing, imaging and centring code running on
them and every file kept under `demo/`.

## Layout

| Files | What they are |
|---|---|
| `ty` | One command over everything; `--json` on any subcommand |
| `agent.py`, `interface.py` | Read-only facts for programs; the JSON envelope, error codes, states |
| `mcp_server.py` | Read-only MCP server over `agent.py` |
| `tonight.py`, `sky.py`, `feeds.py`, `page.py`, `serve.py` | Planner, status page, read-only web API |
| `app.py` | TelescopeYoke, the application: a window of its own over `console.py`'s server, with every screen |
| `console.py`, `console/` | The server and the page behind the application; run by itself, the companion page in a browser (observing only). This computer only; runs the other scripts |
| `mount.py`, `tracking.py`, `polaralign.py`, `polaris.py`, `landmark.py`, `simulator.py` | Mount control, drift model, polar alignment by the stars, the same by day from Polaris alone, azimuth by a remembered landmark, simulated handset and motor board |
| `horizon.py`, `panorama.py` | The skyline from where the telescope stands: measured by the telescope, or taken from a phone panorama. Kept in `cache/horizon.json`; the planner keeps targets above it |
| `direct.py` | The mount without its handset (Wi-Fi adapter or EQDIR lead): stands in for the handset so `mount.py` is unchanged |
| `camera.py`, `indi.py`, `altair.py`, `snap.py`, `liveview.py`, `focus.py` | Camera (through INDI, or Altair's own library) and focusing |
| `host.py` | Everything that differs between Linux and Windows, in one place |
| `shoot.py`, `stacking.py`, `restack.py`, `process.py`, `calibrate.py` | Imaging pipeline |
| `tour.py` | Records the demo being used, for the README: `docs/tour.gif` and `docs/screens/` (Ubuntu) |
| `docs/index.html` | The project's home page, served by GitHub Pages from `docs/` |
| `schemas/`, `tests/`, `evals/` | Output schemas, tests, agent scenarios |

A **rig** is one telescope: `TY_RIG=name`, `ty --rig name` or `app.py --rig
name` makes `config.FILE` `rigs/name.toml` and `config.DATA` `rigs/name/`.
With none named it is `config.toml` and the repository root, as before.
`rigs/` is ignored by git: it holds the user's location.

## Safe without hardware

All of `ty` except `ty mount` with a motion command; anything with `--demo`;
anything with `--dry-run`; `pytest`; `doctor.py`.

## Commands that move the telescope

`mount.py goto | point | zenith | home | compensate | directions`, and `shoot.py` (which
re-centres), `focus.py --field` (which goes to a bright star to focus on), `polaralign.py`, `polaris.py find` and `align`, `landmark.py check`, `horizon.py`. `mount.py drift` and `shoot.py --assist` change
a motor's creep rate. `mount.py stop` is always allowed.

## Safety invariants (do not weaken these)

1. **A person asks for each move.** An agent never decides to move the mount,
   and never removes `MOTION_LOCKED`. Check a move with `--dry-run`, report
   what it would do, and let the person run or approve it.
2. **The web server and the MCP server are read-only.** No motion, no
   capture, no writes; do not add any without authentication designed first.
   The control console (`console.py`) is the one place with buttons, and it
   keeps to its own rules: it listens on `127.0.0.1` only, needs the key made
   when it starts, runs only the fixed commands in its table, and moves the
   mount only after a person confirms a plan. Do not loosen any of those,
   and do not give it a way to listen on the network.
3. **Limits stay in the code:** minimum altitude 20°, at most 5.75 h from the
   meridian, 40° from the Sun, and refusal when the handset is not set up.
   Without a handset (`direct.py`) the same refusals stand in for it: no
   movement until home has been recorded, and no GoTo until a person has
   watched which way the Dec motor turns. Never record either for the user.
   `doctor.py --probe` sends a port only questions that read, and only a
   port a person named: never try ports in turn to see what is there.
4. **Anything that changes how the mount moves needs a test against
   `simulator.py`.**
5. **The user's location never goes in the repository:** `config.toml`, `rigs/`,
   `web/`, `frames/`, `cache/`, `calibration/`, `horizon/` are ignored. Do not publish
   photos of the garden: a panorama for `panorama.py` is one, and so is
   anything named `*.PANO.jpg`.

## Design principles

- **Small and specific.** Automation for ordinary SynScan gear, not a general
  observatory suite. No ASCOM, plugin systems or sequencing engines.
- **Small enough to understand.** One person can read the lot. Prefer a few
  clear lines to an abstraction; do not generalise for hardware nobody has
  reported trying.
- **Honest status.** Say what is proven on real hardware and what is not.
- **Runs without hardware.** `--demo` and the tests cover everything they can.
- **One implementation, several interfaces.** The CLI, `--json`, the web API
  and MCP all call the same functions.

## Conventions

- Short scripts, plain functions, comments that say why. Match the file you
  are in. No new dependencies without a strong reason.
- Machine output: `--json` gives one envelope (`schemas/envelope.schema.json`)
  on stdout; progress goes to stderr; exit code 0 only if `ok`. Error codes
  live in `interface.py` and are stable. Bump `SCHEMA_VERSION` for any
  breaking change.
- Keep `--demo` and the tests working with every change.
- The README's "Current status" must stay true about what is proven on real
  hardware.
- The table of tried hardware is in the README ("Hardware") and again on
  the home page (`docs/index.html`); change both together. The version is in
  `pyproject.toml` and `agent.VERSION`, each release has a section in
  `CHANGELOG.md`, and the download links in the README and the home page
  name the release's zip. `./release.py` checks that all of these agree and
  builds the zip; only a person runs `./release.py --publish`.

## More

- `docs/agents/commands.md`: every command, what it returns, whether it moves anything
- `docs/agents/state-model.md`: states, error codes, the envelope
- `docs/agents/safety.md`: why the rules above exist, and the planned approval design
- `docs/agents/mcp.md`: the MCP server and the web API
- `docs/agents/examples.md`: worked examples of answering common requests
- `docs/agents/architecture.md`, `testing.md`, `hardware.md`
