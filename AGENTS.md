# telescopeyoke: notes for coding and operating agents

It makes an ordinary Sky-Watcher SynScan telescope smarter by measuring and
correcting the things that normally have to be set up perfectly by hand:
night planning, SynScan mount control, plate solving, focusing and stacking,
on a laptop left beside the telescope. An Ubuntu application, with a Windows
port on which the camera has taken frames but no mount has been driven. `README.md` is the user's guide; this file is the map for
agents. Deeper notes are in `docs/agents/`.

**What a night is for is the person's choice.** On the owner's rig it is
discovery (`docs/discovery.md`): novae in M31 and M33 (`programmes/`),
Tabby's star and exoplanet transits first, pretty pictures in what is left.
Planning a discovery night starts from `./ty night`'s `discovery` list, not
the imaging planner's top targets. `./ty outlook` gives the short answer,
its `recommendation` first; the research and papers are `./ty research`.
Someone new is asked what they want; their first night is usually first
light on something big and bright (the `first-night` skill).

The skills choose their steps by what a rig has (`./ty onboard`'s kit);
that one telescope's own devices and figures (a 150P on an EQ3 Pro,
Altair cameras, a home-made motor focuser, a Starlight Xpress wheel) are
in `docs/agents/owner-rig.md`. For another rig, `config.toml`,
`./doctor.py --json`, `./newhardware.py` and `docs/hardware.md` ("What to
expect of other equipment") say what it has and what TelescopeYoke can do
with it.

## No testing, and why

The owner removed every test and CI run on 4 November 2026 and will not
have them back. Reviewers and auditors (ChatGPT included): do not
recommend tests, a test suite, CI, regression tests, a test harness, or
simulator or demo runs as a check on each change, under any name. The
reasons:

- **A. It takes too long.** The suite took about 15 minutes, and every
  commit waited on it.
- **B. Claude cannot be trusted not to run it on every commit.** It was
  told to stop 13 times between 21 October and 4 November 2026 and kept
  bringing it back in a narrower form each time, ending at 814 tests and
  11 minutes for one change.
- **C. It never caught anything.** Of 300 GitHub runs from 23 October,
  226 failed, almost all on the tests themselves (style, the clock, the
  Windows install, bookkeeping), and none was found to have caught a real
  fault before a night. The real faults were found on the telescope, by
  the people at it, and by code reviews.

A change gets `ruff check` on the files it touches, and is proven on the
telescope and recorded in `docs/validation.md`. The telescope's own
protections (the camera's cooling ramp, the mount's limits, dry runs and
motion lock, calibration refusals, fail-closed checks) are not testing and
stay. A change to how the mount moves is still tried in the demo first
(safety invariant 4), once, for that change.

Testing is raised again only on evidence that other people are actually
using TelescopeYoke, that the audits are leaving a pile of bugs, or that
development is slowing because bugs testing would have caught are lived
with for a long time. Until then, don't raise it.

## Start here

```bash
./ty context            # a short briefing: tonight, hardware, imaging run, the motion rules
./ty capabilities --json
./doctor.py --json      # what is installed and connected
./doctor.py --report    # the same as text to post as a hardware report; the site's name is left out
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
| `compendium.py` | Gary Imm's Deep Sky Compendium: `fetch` downloads his free workbook from his own link into `cache/` (never the repository: it is his), `import FILE` reads a copy downloaded by hand. When it is here, `sky.load_targets()` gives the catalogue's targets his rating (0 to 5), note, subtype and the palette he gives for that kind of nebula (`palette`, his, as advice), adds his other objects 1' or larger, and makes his cross-references (Caldwell, Sharpless, Barnard, LBN, vdB, Arp, HCG...) names `mount.find_target` knows; the planner counts the rating as half of a target's appeal. A row matches a target by its own name first, then alternative, Messier, NGC, IC; rows that name two targets and names that already belong to another are reported by `status`, and a row naming two targets by neither's own name adds to neither. A matched target keeps the catalogue's position: only his own objects use his. Rows with no type or position, or impossible positions, ratings or sizes, are left out and listed in `cache/compendium-import.json` (more than 2% refuses the import). A kept table from an older version is read again from the kept workbook, or left unused. Without it, nothing changes |
| `app.py` | TelescopeYoke, the application: a window of its own over `console.py`'s server, with every screen |
| `console.py`, `console/` | The server and the page behind the application; run by itself, the companion page in a browser (observing only). This computer only; runs the other scripts |
| `mount.py`, `tracking.py`, `polaralign.py`, `polaris.py`, `landmark.py`, `simulator.py` | Mount control, drift model, polar alignment by the stars, the same by day from Polaris alone (experimental: not yet found on the real sky), azimuth by a remembered landmark, simulated handset and motor board |
| `moved.py` | Whether the telescope really turned, judged from two pictures or two plate solves; raises `MOUNT_NOT_MOVING` |
| `horizon.py`, `panorama.py` | The skyline from where the telescope stands: measured by the telescope, or taken from a phone panorama. Kept in `cache/horizon.json`; the planner keeps targets above it |
| `direct.py` | The mount without its handset (Wi-Fi adapter or EQDIR lead): stands in for the handset so `mount.py` is unchanged |
| `companion.py` | A companion for someone else's observatory (`docs/companion.md`): reads the frames their capture program saves (FITS or XISF) and PHD2's guiding (live or its log), measures each frame against that night's best, and says what spoiled frames and where the time went, measured apart from inferred; NINA's own log explains the gaps (`--nina-log`), or gives the night alone; the `night-review` skill runs it for someone's own observatory. Sends nothing to any device |
| `phd2.py` | `shoot.py --guide` through PHD2 (`[guider] backend = "phd2"`): asks it to guide, dither, stop around GoTos, and measures each frame's guiding from PHD2's own guide steps, answering as `guider.Supervisor` does. Built to PHD2's published protocol and tried against `simulator.PretendPhd2`, not yet PHD2 itself |
| `alpaca.py` | The mount through its ASCOM driver over the network (Alpaca, `link = "alpaca"`): stands in for the handset the same way; `find` and `status` only read. Also another maker's camera, filter wheel and focuser (`backend = "alpaca"`), answering as `altair.py`, `sxwheel.py` and `focuser.py` do. Tried on ASCOM's simulator, no real device yet |
| `camera.py`, `indi.py`, `altair.py`, `keeper.py`, `snap.py`, `liveview.py`, `focus.py` | Camera (through INDI, or Altair's own library; `keeper.py` holds the cooled camera open and cold all night for every command) and focusing |
| `host.py` | Everything that differs between Linux and Windows, in one place |
| `policy.py` | What each command may do: `read_only`, `local_write`, `hardware` or `external`, every runnable script classed once; `classify_text` gives the worst class in a shell line, and anything unknown or hidden counts as `hardware`. The base of the safety hooks in `docs/skills-and-agents.md` |
| `jobs.py` | Every long job's record, its queue and the progress report (`docs/job-reporting-spec.md`): `./ty bg NAME [--after JOB[:ended\|:released\|:MILESTONE]] [--needs camera,mount,cpu,gpu] -- COMMAND` starts a command as a job, now or once what it waits for is done, its output never held back; `./ty jobs` says what needs the agent, what runs, waits and is queued, and the computer, camera and mount; `--watch` prints only the events that need the agent; `--ack`, `--busy-until`, `--stop`. In a script, `activity.job(...)` (steps, deadlines, milestones, waits); `jobs.run_as` keeps a job only once it has run a minute |
| `agentlog.py` | `ty agent-report`: the decision record the hooks keep in `cache/agent-log.jsonl` (what ran, who asked, what was refused; redacted), summed up |
| `runwatch.py` | `ty watch-run`: watches an imaging run and prints a line only when frames stop, stop being kept, the share kept halves, the stars dim or come back, or the run ends |
| `.claude/` | Claude Code's side: `settings.json` and `hooks/guard.py`, the safety hooks (fail closed: the motion lock, no inline hardware scripts, no subagent moving anything, no `pkill -f`, no secrets printed, no project command left in the background outside `./ty bg`), `hooks/log.py`, the decision record, `hooks/running.py`, the jobs and their open events with each message, `hooks/keepgoing.py`, which sends the agent back once when it would stop with the person's work undone, `hooks/sky.py`, which adds `./clouds.py --approach` (when clear sky gets here) and `./rain.py` (when rain does) to any message of the person's about the sky, read from the answers the satellite timer keeps when they are recent, `skills/`, fourteen procedures, and `agents/`, six agents that read and advise and never move anything (`docs/skills-and-agents.md`) |
| `records.py` | Every kept JSON file: written whole or not at all, changed under a lock (`records.change`), checked against its schema before it replaces anything, and each scientific result stamped with the code that made it (`schemas/provenance.schema.json`) |
| `alert.py` | Tells the house when cloud or rain arrives: a Hue light changes colour and a Google Home speaker says so. Reads the run's frames and the forecast; moves nothing |
| `focuser.py`, `firmware/focuser/` | The focuser's motor: an Arduino Nano driving a NEMA 17 on a TMC2209 (docs/focuser.md), and the firmware it runs. `focuser.py` turns the motor; `focus.py --motor` uses it to focus on the stars in view |
| `refocus.py` | `shoot.py` focusing again between frames when the stars widen or the focuser's temperature moves, through `focus.py --auto --only-if-better`; never moves the mount; off for photometry, in the demo and without the camera keeper (`docs/focus.md`). Not yet tried on the sky |
| `cameras.py` | The camera profiles (`[cameras.NAME]`; the old `[camera]` is the 183c) and light paths (`[trains.NAME]`), which is in use and why; `move-183c --go` moves the 183C's own files under `183c/` once |
| `usbguard.py` | A USB lead that drops off (the handset's or the filter wheel's, with the hub they share): `mount.py` and `sxwheel.py` call `recover()` before giving up, which re-enables the hub port it hung from (`sudo -n`), so nobody is asked to replug at night; `status`, `recover` |
| `sxwheel.py` | The Starlight Xpress USB filter wheel (HID): `status`, `move` a name or number; names from `[filterwheel] filters` (none until someone has looked); frames through a train with the wheel carry the position it confirmed (`FILTPOS`, `FILTER`) |
| `shoot.py`, `stacking.py`, `restack.py`, `process.py`, `calibrate.py` | Imaging pipeline |
| `freetools.py` | The free image-processing tools TelescopeYoke drives and each person installs themselves: `status` says which are here and where to get the rest; `colour.py --denoise graxpert` uses GraXpert on each filter's linear stack, and a narrowband picture takes its stars off the nebula with Seti Astro Suite Pro's Dark Star (each star decided once for all filters); for pictures only, and each step is skipped, and said, when its tool is missing (`docs/free-tools-plan.md`) |
| `desktopqueue.py` | The desktop's long jobs: a CPU lane and a one-at-a-time GPU lane, restartable, a failed job stopping only what waits on it, with CPU, GPU, disk and memory use logged. No camera, no mount |
| `depth.py` | How faint a stack reaches, measured: zero point against Gaia, 5-sigma limit, planted stars found again (`docs/discovery.md`, phase 0) |
| `remote.py` | `restack.py --on HOST`: sends the frames, calibration and code to another computer by SSH and rsync, stacks there under `~/telescopeyoke-laptop/remote`, and brings the picture back |
| `planet.py` | A planet: thousands of a second per frame, a square round it kept from each, the sharpest stacked. Uses the camera only |
| `moon.py` | `ty moon`: the Moon end to end. GoTo, find the disc in the picture and centre it from that (the first time on each side, two test moves measure the picture's directions), set the exposure from the surface, read only the region round the disc, take the video in bursts with the Moon put back between them, stack (`docs/lucky-imaging.md`). Moves the mount; `--dry-run` moves nothing |
| `collimation.py` | `ty collimation`: whether the mirrors are still lined up, from how far the secondary's shadow sits off the middle of a defocused star's doughnut; a motor focus (`focus.py --auto`) runs it on its first doughnuts; history in `cache/collimation.jsonl` (`docs/collimation.md`). Uses the camera only, or `--file` |
| `lunar.py` | The Moon in a picture: its disc (a circle fitted to the sunlit limb), the region round it, the exposure, the centring sums; tonight's Moon from `sky.moon_state`; the Moon's orientation (IAU model), each pixel's latitude, longitude and light angles, the named seas, and the picture's turn found from the terminator and the seas |
| `mineral.py` | The mineral Moon, run by `ty lucky mineral` and `ty moon --mineral`: colour from 16-bit colour stacks, clipping left out, log ratios on 2×2 blocks, the slope taken off, colour that does not repeat between videos (or goes with one video left out) turned down or marked, turned up by a stated factor; safe, full and balanced pictures, ratio maps, a confidence map, whether the colour follows the Moon or the sensor, the orientation checked against the night's plate solve, a check that Tranquillitatis is bluer than Serenitatis, a rank comparison with Clementine's colour map (`ty lucky reference`), and `--compare-flats` (`docs/lucky-imaging.md`) |
| `lucky.py` | `ty lucky`: the lucky-imaging engine. `capture` takes a video in the camera's video mode as an 8-bit (or 16-bit, the header saying 12) SER file with its frames a second and dropped frames; `stack` chooses frames patch by patch, lines each up as a whole and then on trusted alignment points, and stacks several shares at once, green detail or `--colour`, `--flat` to divide by the flat (`docs/lucky-imaging.md`). Uses the camera only |
| `difference.py` | Proper image subtraction (ZOGY) of a reference stack from a new one: what is brighter now (`docs/discovery.md`, phase 1) |
| `patrol.py`, `programmes/` | A discovery patrol of one field: readiness, point and image (through `mount.py` and `shoot.py`), then depth, subtraction, vetting and a short answer |
| `realbogus.py` | Real or bogus: a logistic model trained on stars planted in this rig's own subtractions and on the peaks the subtraction leaves, tested night by night; its probability goes into each vetted candidate's evidence, as advice (`docs/discovery.md`, phase 8) |
| `reference.py`, `vet.py`, `plant.py` | Each field's kept reference; the evidence for each candidate and its verdict; fake novae through the whole pipeline for the discovery completeness (`docs/discovery.md`, phase 1) |
| `streak.py` | Which satellite made the streak across a frame: finds the line, plate-solves the frame, and places every active satellite (CelesTrak's orbits, SGP4) through the exposure; names one only when it alone fits (`docs/satellites.md`) |
| `brokers.py` | Public alerts: ALeRCE's new supernova-like transients, bright enough and up here tonight, not on the Rochester lists; `--unreported` searches the last month for bright ones on neither list (`docs/discovery.md`, phase 6) |
| `notify.py` | Alerts to the person's phone by their own Telegram bot (`[telegram]` in config.toml): the patrol's unexplained candidates with their pictures and report packet, every finished stack's picture with the same picture attached at full size (Telegram shrinks a photo); claiming them is `docs/agents/claiming.md` |
| `starwatch.py` | A watch on a star that dims without warning, Tabby's star first: a short look through the patrol, measured against the stars round it, and a warning when it is fainter than usual (`docs/discovery.md`, phase 9) |
| `transits.py` | Known exoplanet transits: which can be taken whole from here tonight (NASA's Exoplanet Archive), and from a night's frames its verdict, the fitted depth and timing, the light curve drawn, the calibration and timing checks, BJD_TDB and the exposure headroom (`docs/discovery.md`, phase 9) |
| `onboard.py` | `ty onboard`: how far a rig's first setup has got and the next step, each step with how it is known (checked, measured, kept on disk, or the person's word, kept by `--confirm`), and the rig's kit, which the skills choose their steps by. `docs/agents/owner-rig.md` is the owner's rig's devices and figures |
| `newhardware.py` | Notices a new serial device or SynScan Wi-Fi network without sending it anything; on the person's choice asks it what it is (only reads: SynScan handset, motor board, LX200 family), writes the report with serial numbers left out, and gives the Mount support form filled in, never sent. `--watch --install` runs from boot |
| `lighttest.py` | What a light round the house does to the sky: a run's frames with the light on against those with it off (sky level, stars, their brightness and width), in multiples of the frames' own scatter. Reads only |
| `precision.py` | How precise a night's photometry is and what limits it: the frames measured with every aperture, colour channel, stripe treatment and comparison set, ranked by their scatter, with how it falls with averaging (beta) and what it follows (drift, star width, sky, airmass) |
| `variables.py` | Variable stars in frames already taken: light curves from batches of each night's frames, the stars that scatter more than their brightness allows, checked against VSX (`docs/discovery.md`, phase 9) |
| `mosaic.py` | Panels for an object bigger than the frame, kept in `mosaics/`; `mount.find_target` turns a panel name (`M31-P2`) into its centre |
| `tour.py` | Records the demo being used, for the README: `docs/tour.gif` and `docs/screens/` (Ubuntu) |
| `docs/index.html` | The project's home page, served by GitHub Pages from `docs/` |
| `schemas/`, `evals/` | Output schemas, agent scenarios |

A **rig** is one telescope: `TY_RIG=name`, `ty --rig name` or `app.py --rig
name` makes `config.FILE` `rigs/name.toml` and `config.DATA` `rigs/name/`.
With none named it is `config.toml` and the repository root, as before.
`rigs/` is ignored by git: it holds the user's location.

## Safe without hardware

All of `ty` except `ty run` (an order for the imaging run; `ty run status`
only reads) and the
pass-throughs that drive hardware: `ty mount` with a motion command, `ty
shoot` (it re-centres), `ty focus` (the focuser, and `--field` slews), `ty
moon`, and the camera through `ty lucky capture` and `ty collimation`. Anything with `--demo`; anything with `--dry-run`;
`doctor.py`. `policy.py` is the reference: it classes every command.

## Commands that move the telescope

`mount.py goto | point | zenith | home | compensate | directions`, and `shoot.py` (which
re-centres), `patrol.py` (through those two; not with `--plan`, `--analyse` or `--dry-run`), `focus.py --field` (which goes to a bright star to focus on), `polaralign.py`, `polaris.py find` and `align`, `landmark.py check`, `horizon.py`. `mount.py drift` and `shoot.py --assist` change
a motor's creep rate. `mount.py stop` is always allowed.

## Safety invariants (do not weaken these)

1. **No approval asking.** What the person asks for, and every slew of the
   night's plan, is made at once: dry-run it and, if the dry run passes,
   send it. (A suggestion for a mount nobody has watched move yet: offer to
   say each move first.) Never remove `MOTION_LOCKED`, and never move on
   the example site (`Mount.may_move` refuses every movement, whichever
   command asks, while the lock is there or until config.toml has the
   person's own site; stopping never goes through it). One command moves
   the mount at a time: `may_move` holds it for the first to move it and
   that command's children, and refuses anyone else's move with
   `MOUNT_IN_USE`; never work round that hold either.
2. **The web server and the MCP server are read-only.** No motion, no
   capture, no writes; do not add any without authentication designed first.
   The control console (`console.py`) is the one place with buttons, and it
   keeps to its own rules: it listens on `127.0.0.1` only, needs the key made
   when it starts, runs only the fixed commands in its table, and moves the
   mount only after a person confirms a plan. Do not loosen any of those,
   and do not give it a way to listen on the network.
3. **Limits stay in the code:** minimum altitude 20°, at most 7.5 h from the
   meridian (measured clear of the tripod on 2 November 2026; it was 5.75 h
   before), 40° from the Sun, and refusal when the handset is not set up.
   Without a handset (`direct.py`) the same refusals stand in for it: no
   movement until home has been recorded, and no GoTo until a person has
   watched which way the Dec motor turns. When the person says the tube is
   at home, run `./mount.py sethome` for them: their word is the go;
   `./mount.py truehome` records the home `findhome` measured by itself. Never
   answer the Dec direction for them, nor a `ty onboard --confirm` they have
   not given.
   `doctor.py --probe` sends a port only questions that read, and only a
   port a person named: never try ports in turn to see what is there.
4. **Anything that changes how the mount moves is tried first in the demo
   (`--demo`, against `simulator.py`).**
5. **The user's location never goes in the repository:** `config.toml`, `rigs/`,
   `web/`, `frames/`, `cache/`, `calibration/`, `horizon/` are ignored. Do not publish
   photos of the garden: a panorama for `panorama.py` is one, and so is
   anything named `*.PANO.jpg`.

## Design principles

- **Small and specific.** Automation for ordinary SynScan gear, not a general
  observatory suite.
- **Small enough to understand.** One person can read the lot. Prefer a few
  clear lines to an abstraction; do not generalise for hardware nobody has
  reported trying.
- **Honest status.** Say what is proven on real hardware and what is not.
- **Runs without hardware.** `--demo` covers everything it can.
- **One implementation, several interfaces.** The CLI, `--json`, the web API
  and MCP all call the same functions.

## Conventions

- Short scripts, plain functions, comments that say why. Match the file you
  are in. No new dependencies without a strong reason.
- Machine output: `--json` gives one envelope (`schemas/envelope.schema.json`)
  on stdout; progress goes to stderr; exit code 0 only if `ok`. Error codes
  live in `interface.py` and are stable. Bump `SCHEMA_VERSION` for any
  breaking change.
- Keep `--demo` working with every change.
- On another computer (the desktop), everything goes under one folder,
  `~/telescopeyoke-laptop/`: `remote/` for `restack.py --on`. Nothing else
  is made in its home folder.
- A job that runs more than a minute is started with `./ty bg NAME --
  COMMAND` (the guard refuses a project command left in the background
  any other way), and what must follow it is queued with `--after`, so it
  starts by itself. `./ty jobs --watch` runs as the one Monitor for jobs;
  a progress report is `./ty jobs`; each event that needs the agent is
  acted on and acked (`./ty jobs --ack EVENT "what was done"`). When the
  person asks for work to go on ("keep going until they are all done",
  "fill the next 8 hours"), `./ty jobs --busy-until TIME "their words"`:
  the Stop hook then sends the agent back whenever nothing runs or is
  queued. A question for the person is asked the moment it arises, while
  the work that does not need the answer goes on; never saved for the end
  (24 November 2026). A new long-running script reports through
  `activity.job` from its first commit.
- What goes to the person's phone (`notify.send`) is copied to
  `cache/sent.jsonl`; `.claude/hooks/news.py` puts anything new from it in
  front of the agent at the start of a session and with each message, so
  an alert that reached the phone overnight reaches the agent too.
- Keep every JSON file through `records.write` (never `write_text`): a
  scientific result with `stamp=True` and its schema, a file two processes
  may change (a field's candidate book) through `records.change`. Change a
  kept record's shape and its schema together, or the write is refused.
- The sky: before putting lost stars, bad frames or failed guiding down to
  dew, focus or the kit, look at the satellite, the radar, the forecast and
  the camera's figures (`./clouds.py --approach`, `./rain.py`,
  `./clouds.py --history`). Say what was measured apart from what was
  inferred (the satellite's own movement, a model's wind, the camera's
  stars), and say "unknown" when the evidence does not settle it.
- A cloud or rain arrival is a guide, not a promise: several of our own
  calculations giving the same time is not a reason to trust it, and nor are
  the forecast centres agreeing (they share data). What a method is
  worth is what `./clouds.py --scores` says it has done against what was
  seen: the sky checks, the radar and every imaging frame, each judged by
  one star rule (20 or more clear, under 8 cloud, between unknown). The
  arrival is the change from cloud to clear, not the first clear look; a
  forecast counts as on time only inside its own range, its window is
  judged on its own (a false alarm however soon clear sky came after), and
  one with an hour of its stretch unseen is unjudged, never right or wrong.
  Its horizon lines set the satellite beside each forecast centre's hourly
  cloud (Meteosource among them from 16 November 2026), against the same looks.
  `--scores 1 --keep` at the night's end keeps that night's scores with the
  scoring code's commit, so a later change to the scoring can be told apart
  from a change in the forecasts.
- There are no tests and no CI (removed 4 November 2026 at the user's
  request). Before a commit: `ruff check` on the changed files. Why, and
  what not to suggest: "No testing, and why" above.
- What is proven on real hardware is recorded once, in `docs/validation.md`.
  The README and the other pages follow it and may lag.
- The table of tried hardware is in the README ("Hardware"). The version is in
  `pyproject.toml` and `agent.VERSION`, each release has a section in
  `CHANGELOG.md`, and the download links in the README and the home page
  name the release's zip. `./release.py` checks that all of these agree and
  builds the zip; `./release.py --publish` tags the commit and publishes it.

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
- `docs/agents/owner-rig.md`: the owner's rig's devices and figures, which the skills read only there
- `docs/agents/architecture.md`, `hardware.md`
