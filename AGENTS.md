# telescopeyoke: notes for coding and operating agents

It makes an ordinary Sky-Watcher SynScan telescope smarter by measuring and
correcting the things that normally have to be set up perfectly by hand:
night planning, SynScan mount control, plate solving, focusing and stacking,
on a laptop left beside the telescope. An Ubuntu application, with a Windows
port on which the camera has taken frames but no mount has been driven. `README.md` is the user's guide; this file is the map for
agents. Deeper notes are in `docs/agents/`.

**What the nights are for now: discovery** (`docs/discovery.md`). Novae in
M31 and M33 (`programmes/`), Tabby's star, comets near the Sun and
exoplanet transits come first; pretty pictures fill what is left. Plan any
night, or answer "what's the outlook", from `./ty night`'s `discovery` list
(each programme's field and when it is up in darkness), not from the
imaging planner's top targets.

## Start here

```bash
./ty context            # a short briefing: tonight, hardware, imaging run, the motion rules
./ty capabilities --json
./doctor.py --json      # what is installed and connected
./doctor.py --report    # the same as text to post as a hardware report; the site's name is left out
pytest -q               # about fifteen minutes on a laptop; needs no hardware
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
| `mount.py`, `tracking.py`, `polaralign.py`, `polaris.py`, `landmark.py`, `simulator.py` | Mount control, drift model, polar alignment by the stars, the same by day from Polaris alone (experimental: not yet found on the real sky), azimuth by a remembered landmark, simulated handset and motor board |
| `moved.py` | Whether the telescope really turned, judged from two pictures or two plate solves; raises `MOUNT_NOT_MOVING` |
| `horizon.py`, `panorama.py` | The skyline from where the telescope stands: measured by the telescope, or taken from a phone panorama. Kept in `cache/horizon.json`; the planner keeps targets above it |
| `direct.py` | The mount without its handset (Wi-Fi adapter or EQDIR lead): stands in for the handset so `mount.py` is unchanged |
| `camera.py`, `indi.py`, `altair.py`, `snap.py`, `liveview.py`, `focus.py` | Camera (through INDI, or Altair's own library) and focusing |
| `host.py` | Everything that differs between Linux and Windows, in one place |
| `policy.py` | What each command may do: `read_only`, `local_write`, `hardware` or `external`, every runnable script classed once (a new one fails the tests until it is); `classify_text` gives the worst class in a shell line, and anything unknown or hidden counts as `hardware`. The base of the safety hooks in `docs/skills-and-agents.md` |
| `agentlog.py`, `testrun.py` | `ty agent-report`: the decision record the hooks keep in `cache/agent-log.jsonl` (what ran, who asked, what was refused; redacted), summed up. `ty test-run`: the tests on the desktop, only the failures brought back |
| `runwatch.py` | `ty watch-run`: watches an imaging run and prints a line only when frames stop, stop being kept, the share kept halves, the stars dim or come back, or the run ends |
| `.claude/` | Claude Code's side: `settings.json` and `hooks/guard.py`, the safety hooks (fail closed: the motion lock, no inline hardware scripts, no subagent moving anything, no `pkill -f`, no secrets printed), `hooks/log.py`, the decision record, `skills/`, fourteen procedures, and `agents/`, eight agents that read and advise and never move anything (`docs/skills-and-agents.md`) |
| `records.py` | Every kept JSON file: written whole or not at all, changed under a lock (`records.change`), checked against its schema before it replaces anything, and each scientific result stamped with the code that made it (`schemas/provenance.schema.json`) |
| `alert.py` | Tells the house when cloud or rain arrives: a Hue light changes colour and a Google Home speaker says so. Reads the run's frames and the forecast; moves nothing |
| `focuser.py`, `firmware/focuser/` | The focuser's motor: an Arduino Nano driving a small stepper, and the firmware it runs. `focuser.py` turns the motor; `focus.py --motor` uses it to focus on the stars in view |
| `shoot.py`, `stacking.py`, `restack.py`, `process.py`, `calibrate.py` | Imaging pipeline |
| `depth.py` | How faint a stack reaches, measured: zero point against Gaia, 5-sigma limit, planted stars found again (`docs/discovery.md`, phase 0) |
| `remote.py` | `restack.py --on HOST`: sends the frames, calibration and code to another computer by SSH and rsync, stacks there under `~/telescopeyoke-laptop/remote`, and brings the picture back |
| `planet.py` | A planet: thousands of a second per frame, a square round it kept from each, the sharpest stacked. Uses the camera only |
| `difference.py` | Proper image subtraction (ZOGY) of a reference stack from a new one: what is brighter now (`docs/discovery.md`, phase 1) |
| `patrol.py`, `programmes/` | A discovery patrol of one field: readiness, point and image (through `mount.py` and `shoot.py`), then depth, subtraction, vetting and a short answer |
| `realbogus.py` | Real or bogus: a logistic model trained on stars planted in this rig's own subtractions and on the peaks the subtraction leaves, tested night by night; its probability goes into each vetted candidate's evidence, as advice (`docs/discovery.md`, phase 8) |
| `reference.py`, `vet.py`, `plant.py`, `recover.py` | Each field's kept reference; the evidence for each candidate and its verdict; fake novae through the whole pipeline for the discovery completeness; a known nova rediscovered from ZTF images (`docs/discovery.md`, phase 1) |
| `streak.py` | Which satellite made the streak across a frame: finds the line, plate-solves the frame, and places every active satellite (CelesTrak's orbits, SGP4) through the exposure; names one only when it alone fits (`docs/satellites.md`) |
| `sungrazer.py` | Comets near the Sun in SOHO's LASCO pictures, for cloudy nights: fetches them politely, finds what moves other than as the stars do, and makes a movie of each for a person (`docs/discovery.md`, phase 4) |
| `brokers.py` | Public alerts: ALeRCE's new supernova-like transients, bright enough and up here tonight, not on the Rochester lists; `--unreported` searches the last month for bright ones on neither list (`docs/discovery.md`, phase 6) |
| `notify.py` | Alerts to the person's phone by their own Telegram bot (`[telegram]` in config.toml): the patrol's unexplained candidates with their pictures and report packet, the comet hunt's finds with the movie; claiming them is `docs/agents/claiming.md` |
| `starwatch.py` | A watch on a star that dims without warning, Tabby's star first: a short look through the patrol, measured against the stars round it, and a warning when it is fainter than usual (`docs/discovery.md`, phase 9) |
| `transits.py` | Known exoplanet transits: which can be taken whole from here tonight (NASA's Exoplanet Archive), and from a night's frames its verdict, the fitted depth and timing, the light curve drawn, the calibration and timing checks, BJD_TDB and the exposure headroom (`docs/discovery.md`, phase 9) |
| `precision.py` | How precise a night's photometry is and what limits it: the frames measured with every aperture, colour channel, stripe treatment and comparison set, ranked by their scatter, with how it falls with averaging (beta) and what it follows (drift, star width, sky, airmass) |
| `variables.py` | Variable stars in frames already taken: light curves from batches of each night's frames, the stars that scatter more than their brightness allows, checked against VSX (`docs/discovery.md`, phase 9) |
| `mosaic.py` | Panels for an object bigger than the frame, kept in `mosaics/`; `mount.find_target` turns a panel name (`M31-P2`) into its centre |
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
re-centres), `patrol.py` (through those two; not with `--plan`, `--analyse` or `--dry-run`), `focus.py --field` (which goes to a bright star to focus on), `polaralign.py`, `polaris.py find` and `align`, `landmark.py check`, `horizon.py`. `mount.py drift` and `shoot.py --assist` change
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
- On another computer (the desktop), everything goes under one folder,
  `~/telescopeyoke-laptop/`: `tests/` for `ty test-run`, `remote/` for
  `restack.py --on`, `pycache/` for the test run's compiled files. Nothing
  else is made in its home folder: no one-off copies for a test run.
- What goes to the person's phone (`notify.send`) is copied to
  `cache/sent.jsonl`; `.claude/hooks/news.py` puts anything new from it in
  front of the agent at the start of a session and with each message, so
  an alert that reached the phone overnight reaches the agent too.
- Keep every JSON file through `records.write` (never `write_text`): a
  scientific result with `stamp=True` and its schema, a file two processes
  may change (a field's candidate book) through `records.change`. Change a
  kept record's shape and its schema together, or the write is refused.
- CI runs `ruff check .` (mistakes, not style) and measures branch coverage
  with a floor in `pyproject.toml`; `constraints-tested.txt` is a set of
  versions the tests passed with.
- The README's "Current status" table must stay true about what is proven on
  real hardware, and the account behind it is in `docs/validation.md` ("What
  has and has not been proven, in full"): a change to what is proven goes in
  both. The README's "What makes it different" states how far each thing is
  proven too.
- The table of tried hardware is in the README ("Hardware") and again on
  the home page (`docs/index.html`); change both together. The version is in
  `pyproject.toml` and `agent.VERSION`, each release has a section in
  `CHANGELOG.md`, and the download links in the README and the home page
  name the release's zip. `./release.py` checks that all of these agree and
  builds the zip; only a person runs `./release.py --publish`.

## More

- What has really been proven on hardware is `docs/validation.md`
  ("Current conclusions"). Never take it from the README's prose, a guide
  or the changelog: they follow it and can lag.

- `docs/agents/commands.md`: every command, what it returns, whether it moves anything
- `docs/agents/state-model.md`: states, error codes, the envelope
- `docs/agents/safety.md`: why the rules above exist, and the planned approval design
- `docs/agents/mcp.md`: the MCP server and the web API
- `docs/agents/examples.md`: worked examples of answering common requests
- `docs/agents/setup-routine.md`: the order to run things in while a person is at the telescope
- `docs/agents/architecture.md`, `testing.md`, `hardware.md`
