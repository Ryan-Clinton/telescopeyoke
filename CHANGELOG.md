# Changes

What each release changed, in short, with a link to where it is explained.
This is history: how to use a feature is in the guides, and what has been
proven is `docs/validation.md` ("Current conclusions").

## Not yet released

- **The companion** (`companion.py`, [Companion](docs/companion.md)): for an
  observatory that already runs a night with its own software. It reads
  the frames the capture program saves (FITS or XISF) and PHD2's guiding,
  live or from its log, and says what spoiled frames (cloud, a brighter
  sky, soft or trailed stars, the sensor off target, the guide star lost)
  and where the night's time went, measured apart from inferred. It
  sends nothing to any device. Frames with nothing to judge them
  against are unassessable, never kept; a frame is guided only with
  guide steps all through it (the same rule as the PHD2 guider); only
  frames of one setup (night, target, filter, camera, gain, exposure,
  scale) are compared; every file is accounted for.
  Gaps are counted within a night, never the day between two; FWHM is in
  arcseconds only for a setup whose frames all give a pixel scale; live,
  a setup with too few frames yet says it is not judged, never "good".
  NINA's own log (`--nina-log`) explains the gaps between frames (autofocus,
  centring, flips, dithers, waits, unsaved exposures, the safety monitor,
  lost USB devices, errors), and a night can be read from NINA's and PHD2's
  logs alone; `--night` and `--tz` for logs of several nights or another
  zone. PHD2's log is read as PHD2 writes it (only DROP rows are a lost
  star; calibration rows are not guiding), and a stretch where PHD2 said
  it was guiding with too few steps is named.
- **A mount through ASCOM Alpaca** (`alpaca.py`, `[mount] link = "alpaca"`):
  any mount with an ASCOM driver, on this computer or a Windows one on
  the network, through the same motion lock, limits and dry runs.
  `./alpaca.py find` lists the servers. Tried on ASCOM's own simulator,
  not yet a real mount ([Mounts](docs/mounts.md)). The telescope is the
  one named in the settings, never the first to answer; home and park
  are waited for by the driver's own word; a driver without MoveAxis
  does GoTo and tracking only; a driver whose site is not this one's is
  refused a GoTo until `./mount.py settime`; the doctor only reads.
- **A filter wheel and a focuser through ASCOM Alpaca** (`backend =
  "alpaca"` under `[filterwheel]` or `[focuser]`): they answer as the
  Starlight Xpress wheel and the project's focuser do, so filter
  changes, confirmed positions in each frame and the walk-in use them
  unchanged. Tried on ASCOM's simulator only.
- An imaging run's gain and exposure default to the rig's own (`[imaging]
  gain` and `exposure`, in the Settings form), the owner's 1500 and 2 s
  unless set: another camera's gain is in its own units.
- **Guiding by PHD2** (`phd2.py`, `[guider] backend = "phd2"`): `shoot.py
  --guide` asks PHD2 to guide (its own calibration and star), dithers by
  it, stops it around each GoTo and guides again after, and gives each
  frame the same GUIDED, GUIDERMS and GUIDEMAX from PHD2's guide steps. A
  guided run never carries on unguided. Built to PHD2's published
  protocol and tried against a pretend PHD2 (`simulator.PretendPhd2`),
  not yet PHD2 itself.
- What a frame says is what the equipment did: an Alpaca camera's GAIN is
  read back from the driver (a gain outside its range, or not one of its
  named gains, is refused, never moved into it); only a mono sensor or a
  Bayer mosaic is read, its pattern from the driver; a cooled camera's
  frames wait for its sensor to reach the driver's target (TY_ONTGT as
  the Altair's); an Alpaca wheel's own filter names reach FILTER. PHD2's
  guiding is judged against the cycle PHD2 is set to, so a stalled stream
  of guide steps marks the frame unguided and cannot pass the settle
  check; its profile can be required (`phd2_profile`), and each frame
  names what guided it (GUIDER).
- **A camera through ASCOM Alpaca** (`[camera] backend = "alpaca"`):
  frames with the same header the Altair camera gives (exposure, gain,
  start time, Bayer pattern or mono, temperature, binning), binned for
  plate solves on a mono sensor, read as ASCOM's ImageBytes where the
  server offers it. The doctor and `camera_setup.py` check it without
  connecting. Cooling stays with the driver's own program. Tried on
  ASCOM's simulator only.
- `shoot.py --dry-run` fails when a later GoTo or filter change in the
  plan would be refused; the imaging skill's command shapes follow what
  `shoot.py` allows together.
- **`ty onboard` says only what it knows**: the telescope and the camera
  are separate steps, showing which settings were changed from the
  example and which were not; a plate solve's match is the pixel scale
  alone; a frame or picture counts only for the camera and light path
  in use; imaging ready is checked now beside the mount; `--no-check`
  no longer says every step is done; a hand focuser can be recorded
  (`--confirm manual-focuser`); the kit says whether `keeper.py` can hold
  the camera cold, and whether the camera is still the example's.
- `newhardware.py` takes the settings as the person's by latitude and
  longitude, not latitude alone.
- The setup routine's account of the owner's camera lead and hub moved
  to [owner's rig](docs/agents/owner-rig.md).
- **A binned plate solve keeps the old scale**: the scale and the camera's
  angle it keeps are per pixel of the unbinned frame again, as the drift
  assist, `ty onboard` and `mosaic.py` read them (a 2x2 binned solve had
  them twice as large).
- A bad spot name in `config.toml` is a failed check in `doctor.py`, not
  a crash.
- A lost Wi-Fi link during a direct-drive move says whether the stop got
  through; if not, to look at the mount and switch its power off.
- The motor focuser's far search turns round at `[focuser] travel`
  rather than being stopped there; a killed `focuser.py` waits for the
  Nano's answer to the move it had sent.
- The sky briefing starts one fresh look at a time, and the saved
  satellite and radar answers are written whole.
- **Connected is not ready for a GoTo**: `doctor.py` gives `goto` beside
  `mount`, and `ty onboard` shows a "GoTo allowed" step while a direct
  link waits for the Dec direction to be watched.
- The README, mounts page and guide-camera notes now say what validation
  records: Wi-Fi control has made a GoTo and home (no tube on), and
  guiding has held 120 s subs.
- The first-night skill asks what the person wants first and aims for
  the smallest success their equipment allows.
- GoTo readiness is read from the mount's kept state, not a message:
  `./doctor.py --need goto`, `ty capabilities`'s `goto_blocked`, and a
  "GoTo allowed" step `ty onboard` always shows.
- Without a handset, home and the Dec direction belong to the motor board
  they were found on: another board answering has them found again.
- `doctor.py` counts as the camera only what `camera.py` would open (a
  filter wheel's driver is not a camera), and says when there are two.
- Setup, the agents' hardware notes and the autoguiding page now say
  what validation records.
- **A camera alone is its own check**: `./doctor.py --need camera` needs
  no plate solver or star database, for a first frame indoors.
- Another maker's INDI camera: `camera.py` sets binning, the raw format
  and the gain only where its driver offers them, by the names it uses
  (ZWO's raw format, `CCD_GAIN`); `camera_setup.py` names the maker's own
  driver rather than AltairCapture for a camera that is not an Altair.
- The imaging skill builds the run from what was asked and what the rig
  has (filters, guiding, exposure, gain, a goal) and says the plan first.
- `ty context` no longer tells every rig its nights are for discovery:
  that is the owner's; another person is asked.
- The guide scope's focal length is a setting (`[guider] focal_mm`).
- End of night: by hand the mount is parked only when asked;
  `schedule.py end` parks by itself. Weather is advice, not protection
  (`docs/agents/safety.md`).

## 0.4.0: setup that remembers, skills that follow the rig

- **`ty onboard`**: how far a rig's first setup has got and the next
  step, each step with how it is known: checked now, measured, kept on
  disk, or the person's word (`--confirm moves` once they have watched
  the first moves). A setup broken off one evening carries on the next.
- **The telescope and camera in the settings**: shown as measured by a
  plate solve, the person's, or still the example's; a plate solve that
  disagrees with the settings' pixel scale is said.
- **Skills by kit**: focusing, setting up, imaging and the night's end
  choose their steps by what the rig has (a cooled camera, a filter
  wheel, a motor focuser) instead of assuming the owner's; the owner's
  devices and figures are one page of their own
  ([owner's rig](docs/agents/owner-rig.md)).

## 0.3.2: every mount script stops when killed

- **Stopping**: any script that drives the mount (GoTo, polar alignment,
  the skyline survey, imaging's re-centring) now stops it when killed
  from outside on Linux, as Ctrl+C does; stop also ends the Dec drift
  correction; and an invalid spot name no longer keeps stop from
  reaching the mount.
- **Before the installer, on Windows**: `doctor.py` and `newhardware.py`
  find the COM ports without pyserial.
- **What is plugged in**: no lead is called the mount's while the
  settings still have the example location; `newhardware.py` says when
  it could not list Wi-Fi networks (`wifi_listed`), rather than showing
  none.

## 0.3.1: stopping and refusing, made sure

Fixes to 0.3.0 for a rig other than the owner's.

- **The mount**: every movement, whichever script asks, is refused while
  the motion lock is there, as well as on the example site; a move killed
  from outside (Claude Code's interrupt, a closed terminal) stops the
  motors on Linux; `mount.py stop` works with a missing, example or
  broken settings file.
- **Moves on a new rig**: going first through the moves with the person
  watching is a suggestion the setup makes, not a rule
  ([first night](docs/first-night.md)).
- **What is plugged in**: USB devices on Windows as well as Linux, one
  line each; SynScan Wi-Fi networks on Windows (netsh); a fresh checkout
  no longer calls an FTDI lead its mount's because the example's settings
  name one. `doctor.py --need` answers `ok: false` when not ready, and
  runs before the installer.
- **Setup on Windows**: the setup skill runs the scripts through Python.

## 0.3.0: an experimental hardware preview, set up with Claude Code

Six weeks of nights on one telescope since 0.2.1, and the first release
meant for other people's: clone it or unpack the zip, open Claude Code in
the folder, and ask it to set up your telescope. Proven on a Sky-Watcher
EQ3 Pro with a SynScan handset and Altair cameras; anything else is
unproven or unsupported, and the setup says which before anything moves
([hardware](docs/hardware.md)).

- **Claude Code setup**: safety hooks that fail closed, skills from first
  night to end of night, read-only agents; a new rig asks before every
  move until its first moves have been watched; the mount refuses to move
  on the example site.
- **New hardware**: the cooled mono Altair 183M (kept cold all night), a
  Starlight Xpress filter wheel, a home-built motor focuser, a guide
  camera and autoguiding.
- **Discovery**: nova patrols of M31 and M33 with image subtraction and
  vetting, Tabby's star, exoplanet transits, variable stars, satellite
  streaks named.
- **The night**: cloud and rain arrival from satellite and radar, the
  Moon and planets by lucky imaging, mosaics, a live stream.

What changed, day by day:

- **8 November 2026**: the radio SETI search (`seti.py`) has moved to its
  own project: it uses no telescope. Taken out with it: its schema and
  guide, its sweep in `ty research`, its candidates in `investigate.py`
  (and the "likely interference" verdict), its arXiv topic, its steps in
  the cloudy-day and discovery-night skills, h5py and hdf5plugin from the
  install, and its README and docs entries.

- **8 November 2026**: the comet hunt (`sungrazer.py`) has moved to its
  own project: it needs no telescope, mount or camera. Taken out with it:
  its schema, timer, the comets in `ty candidates` and `ty discovery`, the
  stream's comet card, the report-comet skill, the comet-checker agent and
  the comet parts of the docs. Bright comets for the telescope (COBS and
  JPL Horizons, in `tonight.py`) stay.

- **6 November 2026**: Gary Imm's Deep Sky Compendium, fetched onto this
  computer by `./compendium.py fetch` or the Settings screen's button,
  gives the targets his 0-to-5 rating and note, adds about 1,800 of his
  other objects, and weighs his rating into the planner's ranking; it
  never goes in the repository ([commands](docs/agents/commands.md)).
- **6 November 2026**: the Compendium's rows match the catalogue the same
  way every time (own name first, clashes reported), impossible rows are
  left out, his Caldwell, Sharpless, Barnard and other names find their
  targets, his palettes (SHO, HOO, Ha+RGB, LRGB) are given as advice with
  each nebula, and `--kind` takes his subtypes.
- **6 November 2026**: a Compendium table kept by the first version is read
  again from the workbook instead of breaking the planner; every object row
  is counted, those left out kept with their reasons in
  `cache/compendium-import.json`.

- **3 November 2026**: VSX is asked of every VizieR mirror in turn, a
  dead one left after 10 seconds, and an empty page is no longer read as
  "not in VSX" ([archive](docs/archive.md)).
- **3 November 2026**: a skill may pre-approve commands that write this
  computer's own records, never the rig or a message, and a `*` is tried
  with every word that raises a class (the discovery-night skill's
  `./brokers.py *` let in `--follow`); on Windows the camera lock is one
  fixed byte, so a second command is refused properly, and a Kepler
  download replaces an older copy ([skills](docs/skills-and-agents.md)).
- **3 November 2026**: a lead asked again within a day of its last try
  keeps its count of tries, and `ty research --pull` never copies over a
  newer record here ([archive](docs/archive.md)).
- **3 November 2026**: a fresh session sees the research. `./ty context`
  opens with the mission (discovery first; strange stars and SETI wanted)
  and gives the research queue, the most intriguing leads and any
  watchable lead up tonight; `./ty night` has a `research` section
  (`observe_tonight` with a dry-run GoTo each), and the discovery-night
  skill weighs it before the programmes. Two fresh-session scenarios,
  clear and cloudy, in `evals/scenarios.json`
  ([docs/discovery.md](docs/discovery.md#what-the-project-is-for)).

- **3 November 2026**: `investigate.py` judges short TESS dips and
  possible repeats as leads in their own right (the red-giant rule only
  for dips of a day or more); queues leads by tier and contrast against
  the star's own scatter rather than detection score, with a lighter check
  for routine ones; retries a failed source a day later, asking only it;
  names a SETI lead by its session too, with a `signal` linking sessions;
  and `--summary` writes the most intriguing leads to
  [docs/research/README.md](docs/research/README.md).

- **3 November 2026**: a lead's verdict says how sure it is: "explained"
  needs a catalogue naming the star's variability with every catalogue
  answering, else "likely explained" (KIC 6448574's red giant is now
  this); a SETI candidate with a satellite band or no drift is "likely
  interference" with the signs stated, never a proven artefact. A lead
  whose checks went unanswered is looked into again before new ones (up
  to three tries). One definition of a lead (`archive.is_lead`: possible
  repeats and short TESS dips count, known binaries do not) serves the
  screens, `investigate.py` and `ty research`, which now reads TESS's
  real target files. SETI hits that are not candidates never reach the
  queue ([docs/archive.md](docs/archive.md#looking-into-a-lead)).

- **3 November 2026**: the setup routine's motor check (`./mount.py nudge`)
  is optional: `[mount] nudge_check`, "Motor check at setup" on the Settings
  screen; `./mount.py settime --dry-run` says whether it comes next.
- **A lead looked into without being told which** (`investigate.py`,
  `ty research`): the searches' top lead nobody has looked into goes
  through the same checks each time (SIMBAD, VSX, Villanova's Kepler
  EBs, Gaia DR3, TESS and ZTF, both fluxes, crowding, neighbours),
  ending in a verdict with its reasons and whether this telescope can
  watch it, reported in `docs/research/`; `ty research` shows each
  survey's coverage and every lead by where it stands, and `--html`
  writes `web/research.html`.

- **Research that needs no sky, run by itself** (`seti.py sweep`,
  `seti.py benchmark`, `literature.py --unread`, the cloudy-day and
  discovery-night skills): the radio search of Tabby's star's Green Bank
  cadence carried on block by block, checked against turboSETI on the
  same slices; papers listed until read, with their abstracts; remote
  reads take only the bytes asked for ([SETI](docs/seti.md)).
- **Papers and dated watches** (`literature.py`, `ty night`): arXiv's
  newest on Tabby's star, M31/M33 novae, dipping stars, technosignatures
  and transit timing, listed as `papers`; a programme's `[[watch]]`
  windows from a paper, starting with the transit windows of the
  companion proposed for Tabby's star in 2026
  ([discovery](docs/discovery.md), step 8).
- **Radio SETI in Breakthrough Listen's open data** (`seti.py`): a
  target's looks by cadence, a de-Doppler search of one look's slice read
  over the web, and the ON-OFF test that labels each hit candidate,
  interference or unconfirmed ([seti](docs/seti.md)).
- **Searching Kepler's archive for stars like Tabby's** (`archive.py`):
  a star's dips in its Kepler light curve from MAST, each checked for
  edges, gaps, spacecraft events, periodicity and variability; it finds
  Tabby's D792, D1519 and the 2013 complex, and ranks many stars by how
  Tabby-like they are. Each dip is measured in SAP too, the long-term
  fading is measured with the quarters joined at their edges, `screen`
  works through every star Kepler watched, a benchmark on real binaries
  and quiet stars checks it, and `tess` runs the same on TESS sectors
  (it finds the 2019 transit of Tabby's star) ([archive](docs/archive.md)).
- **What a stack reaches, and who wants what measured** (`ty night`,
  `transits.py`, `build_catalogue.py`): the catalogue holds galaxies to
  magnitude 12 (1,660 objects, from 641), built from a pinned OpenNGC
  release, and each recommendation says what it is from the catalogue
  alone; AAVSO Target Tool stars this camera can measure (`campaigns`,
  with a Target Tool key); ExoClock's priority and each transit's timing
  error, the wanted ones first; comets to magnitude 12 with their motion;
  and how old each outside feed's data is (`sources`). The outlook runs
  `brokers.py` in the background, and each transient it keeps says what
  Lasair's Sherlock matches it to and its absolute magnitude
  ([discovery](docs/discovery.md), step 8).
- **Fresh fields placed by the real frame and ranked by what they add**
  (`ty night`, `footprint.py`): a galaxy is in a programme's field when
  its centre lies in the camera's rectangle (solved, from a mosaic's
  plan, or nominal), not within a fixed circle; a reference counts only
  when a version is kept; fields are ranked by reference, days since
  watched, share in the frame and placing, with their reasons.
  `depth.py` keeps its plate solve, and `reference.py NAME --locate`
  adds one to an older reference. `best_tonight` takes the big targets,
  with objects in one frame together (the Double Cluster) and how often
  each was imaged ([discovery](docs/discovery.md), step 7).
- **Schedule times by the observing night** (`schedule.py`): in darkness
  a clock time gone since sunset is tonight's and goes at once, any
  other is the next one; in daylight the next one; or a full date. It
  replaces a six-hour guess.
- **19 October to 2 November 2026: new commands and changes** (what was
  proven is in `docs/validation.md`):
  - `usbpower.py`: cuts the camera's power at a hub that switches each port
    (the hub itself has since been returned).
  - `youtube.py`: the YouTube broadcast, on air 1 November.
  - `storage.py`: tidies before each step; `schedule.py show` warns when
    space is short.
  - `guidecam.py`: opens the guide camera through libaltaircamlegacy 1.24.
  - `cameralock.py`: one owner of the camera, and a second command is
    refused with `CAMERA_BUSY` naming it; SIGTERM now closes the camera.
  - `focusdial.py`: a printable dial for the focus knob.
  - `vet.py`: only clusters of 3 or more candidates within 120″ are set
    aside as residue; a lone candidate is always alerted.
  - `schedule.py`: `next`, `skip`, `move` and `fill`, and gap filling.
  - `horizon.py`: a survey carries on after being cut short; records the
    side of the pole; repeat check off the meridian; a lone opening is put
    at the lower neighbouring top; `--use-aside` keeps a set-aside survey
    on a person's word.
  - `mount.py point --clearance-test`; the hour-angle limit is 7.5 h, up
    from 5.75 h.

- **Which satellite made a streak** (`streak.py`, `ty streak`): finds a
  straight streak in a frame, plate-solves the frame and places every active
  satellite from CelesTrak's orbits (SGP4) through the exposure; one that
  alone runs along the streak in sunlight while the shutter was open is
  named, and otherwise it says that nothing in the list fits. A new
  dependency, `sgp4` (`docs/satellites.md`).
- **A picture of a single star names it**: `restack.py`'s finished picture
  of Tabby's star, an exoplanet's host, a bright star or a followed
  transient marks the star with two ticks and its name, placed by plate
  solving the stack (`process.mark`). Galaxies, nebulae, clusters, planets
  and mosaic panels are left unlabelled.
- **Real or bogus** (`realbogus.py`, phase 8): a logistic model of what a
  new star looks like after this pipeline against what the subtraction
  leaves, trained on stars planted in five M31 nights and on every other
  peak, tested night by night: 175 of 452 false candidates above 5 sigma
  set aside, 1644 of 1684 planted stars kept, most of it from the shape
  rather than the score. `vet.py` adds its probability to each candidate's
  evidence as advice; the candidate book keeps it each night.
  `difference.subtract` can hand back its working images for training.
- **The decision record says how a skill went**: per skill, the turns
  that ended on a question to the person, the messages that stopped or
  corrected it (only that it did; the words are not kept) and the times
  the person interrupted Claude, from two more hooks (UserPromptSubmit,
  Stop). An interruption is no longer read as the person's words for a
  move.

- **The rest of the skills and agents** (`docs/skills-and-agents.md`):
  skills `claim`, `report-comet` (both only when typed), `discovery-night`,
  `end-of-night`, `morning-summary`, `new-command`, `release` (stops
  before publishing), `first-night`, `troubleshoot`, `cloudy-day`; agents
  `candidate-vetter`, `catalogue-researcher` and `comet-checker` (the web
  readers have no shell and read no files), `night-analyst`,
  `code-reviewer`, `motion-reviewer`, `docs-keeper` (writes only the
  docs) and `debugger`, each with a turn limit, and those with a shell
  held to looking by a fail-closed hook. The decision record
  (`agentlog.py`, `.claude/hooks/log.py`, `./ty agent-report`): each
  command, skill and agent, each refusal, and each hardware command's
  authorisation as data, redacted. `./ty test-run` runs the tests on the
  desktop and brings back only the failures.

- **Claude Code's safety hooks and the nightly skills.**
  `.claude/settings.json` runs `.claude/hooks/guard.py` before every shell
  command, edit and read, failing closed: nothing removes, empties or
  replaces `MOTION_LOCKED` or takes its checks out of the code; no inline
  Python touches the mount, focuser, camera or serial port; no subagent
  runs anything `policy.py` calls hardware or external; no `pkill -f`; no
  printing `config.toml`'s Telegram token. Tested against a long list of
  ways round each (`tests/test_hooks.py`). `./ty watch-run`
  (`runwatch.py`) watches a run and says something only when it changes.
  The skills `nightly-setup`, `focus`, `polar-align` and `imaging-run` are
  in `.claude/skills/`, tested to name only real commands and options and
  to pre-approve nothing that moves (`tests/test_skills.py`), with
  scenarios in `evals/skills.json`. `policy.py` now reads `sudo -u USER`,
  `nice`, `timeout`, `env` and `python -m` in front of a command.

- **What each command may do** (`policy.py`): every runnable script is
  classed `read_only`, `local_write`, `hardware` or `external`, with the
  words that change it: `--help` makes any command read-only, and
  `--dry-run` and `--plan` only where that script declares them (a test
  checks they are its real options); of the rest the worst present
  decides, in any order. A test fails while a script has no class, and
  another keeps `docs/agents/commands.md` filed by it (its first section is
  now "No hardware", since much there writes files). `./policy.py COMMAND`
  answers for one command line, taking the worst of several and counting
  anything unknown or hidden in `bash -c` or `$(...)` as `hardware`. It is
  the base for the Claude Code hooks specified in
  `docs/skills-and-agents.md`, which also gains the safety layers, the
  decision record, least-privilege agents and the tests where nothing
  should happen.

- **Records kept safely, and saying what made them** (`records.py`): every
  JSON file is written to a `.part` file and renamed over the old one, so a
  crash never leaves half a record; a field's candidate book is changed
  under a lock, so the background search and a person dismissing a
  candidate cannot lose each other's change; each scientific result is
  checked against its schema before it replaces the old one (one that does
  not match is kept as `NAME.rejected.json` and the old one stays), and
  carries `provenance`: the version, the git commit and whether it had
  uncommitted changes, the libraries, and a fingerprint of the settings
  with the site and the Telegram bot left out. Each night in a candidate's
  history says the same in short (`0.2.1+6bb014d`). `jsonschema` is now
  needed to run, not only to test.
- **Checks**: CI runs `ruff check .` and measures branch coverage with a
  floor; a job installs exactly `constraints-tested.txt`, and another
  reports known vulnerabilities in the libraries (`pip-audit`). An
  unexpected failure in a `--json` command still answers in its envelope,
  and now prints its traceback on stderr. A test that only passed on Linux
  (a path compared as text) passes on Windows.

- **Alerts and claiming**: when a vetted candidate is unexplained, the
  patrol makes its report packet and sends it, with the night, the
  reference and the difference side by side, to the person's phone by
  their own Telegram bot (`notify.py`, `[telegram]` in config.toml); then,
  in a run the person started, it takes 10 more minutes of the same field
  and searches them, so the second alert says whether it was seen again.
  The comet hunt sends its tracks heading for the Sun with the movie and
  the Sungrazer form's fields. `docs/agents/claiming.md` is how an agent
  fills the Transient Name Server's or the Sungrazer Project's form in the
  browser and stops for the person to press send. `report.py` finds a
  mosaic panel's candidates in the panel's own book.
- **Dips**: `./variables.py` also lists any star that dips, three points
  or more in a row clearly fainter than usual, however quiet it is
  otherwise. `./starwatch.py tabby` watches Tabby's star (KIC 8462852): a
  10-minute look through the patrol, measured against the stars round it,
  each night kept, and a warning when it is 3% or more fainter than usual.
- **Exoplanet transits**: `./transits.py` lists the known transits that can
  be taken whole in the dark here tonight, deepest first, from NASA's
  Exoplanet Archive, and keeps each star by name for `mount.py goto`;
  `./transits.py measure SESSION --planet NAME` makes the star's light
  curve from the night's frames and fits the depth and how early or late
  the transit came.
- **Variable stars**: `./variables.py M31` stacks each night's kept frames
  in batches (10 by default), measures every Gaia star between G 10.5 and
  16 with no close neighbour in each batch, puts each batch on Gaia's
  scale by the median of all of them, and lists the stars that scatter
  more than stars as bright as them, with a picture of each light curve;
  VSX says which are known. One VSX does not have is a candidate for a
  person, not a discovery.
- **Following a public transient**: `./brokers.py --follow OID` keeps the
  object's place under its name (so `mount.py goto OID` and `shoot.py`
  know it), runs the patrol on it with all its checks, and measures it in
  the new stack beside ZTF's last magnitude; `--plan` moves nothing.
  `./brokers.py --unreported` searches the last 30 days for bright
  transients on neither Rochester list, up here or not; every search now
  leaves out what ZTF's real-or-bogus score calls bogus. Its first run
  found AT 2026aexm in NGC 3441 (r 16.7), which the Transient Name Server
  already has.
- **Comets: raw pictures and GOES-19**: `./sungrazer.py fetch --raw` takes
  LASCO's raw FITS pictures (the archive, or the last fortnight's) instead
  of the JPEGs, for fainter comets; `--camera ccor1` takes GOES-19's CCOR-1
  coronagraph from NOAA's open archive, where most new comets have been
  found since 2025. The noise is now measured in each part of the picture
  on its own. `look --plant N` counts fake comets found by strength.
  `./sungrazer.py hunt --camera ccor1` fetches the last day, keeps only
  what heads in towards the Sun and deletes old pictures; `--install`
  runs it every 6 hours as a systemd user timer.
- **Comets in SOHO's pictures, for cloudy nights**: `./sungrazer.py fetch`
  takes LASCO C3 (or C2) pictures from the public archive, each once and a
  second apart; `./sungrazer.py look` finds what moves other than as the
  stars drift and makes a movie of each for a person to watch. Motion is
  measured per 12 minutes from the pictures' own times, so a gap in the
  pictures does not break a track. `--until` looks at a day in the past.
  Tried on the bright C/2024 G3 (ATLAS) on 13 and 14 January 2025: its
  head and tail are the strongest candidates. Not yet good enough for the
  faint ones: SOHO-5175 on 25 January 2025 was not found. Nothing is
  reported for you.
- **Public alerts**: `./brokers.py` asks the ALeRCE broker for new
  supernova-like transients and keeps those bright enough for this rig and
  up in the dark here tonight, naming any the Rochester lists have; the
  Transient Name Server needs a key, so its search link is given instead.
- **Every session searched**: when `shoot.py` or `restack.py` finishes a
  stack of a field with a reference, `patrol.py --analyse` starts on it in
  the background at low priority (its lines in the session's
  `patrol.log`). `./patrol.py --sweep` searches what that missed in the
  last three days, `--sweep --all-history` every session kept.
  A stack whose half-found depth is brighter than G 16 is not searched
  (the 46 s session of 4 October reached G 15.7 and its stars came up as
  197 candidates), and one session's fault no longer stops the sweep. The
  first sweep also found vet.py reading Gaia's answer without its new
  colour column, fixed with a test of a whole vetting.
  A session of fewer than 8 frames is not searched either: too few to
  check each half of the night or to throw out a cosmic ray (the 4-frame
  session at 02:05 on 14 October gave two such candidates).
- **Dismissal labels**: `./candidates.py M31 --dismiss ID --reason "hot
  pixel"` closes a candidate on a person's word and keeps the label, for
  the classifier to learn from later; `--reopen ID` undoes it.
  `./ty candidates` lists every field's open candidates.
- **A real nova rediscovered**: `./recover.py AT2024koe 10.32290 40.96525
  --before 2024-05-21 --after 2024-06-27` takes ZTF's public images from
  before and during a known transient and runs the same subtraction: it
  found AT2024koe 0.27″ from its published place at 10.8 sigma, the
  strongest candidate. On the way, the mask round bright stars now goes
  with the stars' width instead of a fixed 20 pixels, which had hidden it.
- **Realistic fakes**: `plant.py` gives each fake its frame's own local
  star shape, its own photon noise and the frame's clearness, and sets its
  brightness from the new night's zero point (the reference's had made
  them 0.2 mag too bright). Half found at G 17.8 (not 17.9), 90% at 16.9.
  `--colour blue|neutral|red` plants coloured novae through the night's
  colour term, which `depth.py` now measures from Gaia BP-RP (-0.34 mag a
  magnitude of BP-RP on M31: red stars give this camera less light per G
  magnitude).
- **Vetting judged more carefully**: a Gaia star beside a candidate is a
  clue, not an explanation; one half of the night only is the programme's
  rule (`both_halves`), not vet.py's; a candidate is closed after three
  misses only if each was deep enough even had it faded 0.2 mag a day; a
  stack that could hold an open candidate is refused as a reference
  (`--force` overrides); `forced.py --difference` measures the light above
  the reference.
- **Discovery in the application**: a Discovery screen under Observe
  chooses a programme and minutes and plans the patrol, which a person
  confirms like any move; it shows the last patrol's answer and the
  candidates still open.
- `depth.py` run without `--plant` keeps an earlier run's planted-star
  results instead of dropping them.
- **Dithering**: `./shoot.py NAME --dither N` re-centres every N frames on a
  point a little off the target (up to 1.5′, a new direction each time), so
  the camera's own pattern averages away; `mount.py`'s GoTo takes an offset
  for it. Programmes can ask for it (`dither = 15`). Proven against the
  simulator only.
- **The whole of M31, panel by panel**: `./patrol.py m31-panels` plans
  mosaic.py's 4 x 2 panels if none are kept, orders them by novae reported
  in each x the share it should catch x days since it was watched, over
  the minutes it costs, takes as many as the night allows, and makes each
  panel's first night its own reference (M31's is used where they overlap
  until then).
- **A report packet in under five minutes**: `./report.py CANDIDATE` gathers
  the position and its error, the UTC time, the magnitude and the night's
  limit, the last non-detection, the reference, the checks and a finding
  chart with north up, as the TNS form asks, with what is still wanting
  before it is sent. It never sends anything. 95 s for the 14 October
  candidate.
- **A discovery patrol in one command**: `./patrol.py m31-novae` checks it is
  ready (the motion lock, a kept reference, how old the focus is, how deep
  the night should reach), points with `mount.py goto` and images with
  `shoot.py`, then measures the depth, subtracts the field's reference,
  vets every candidate and answers in a few lines, with cut-outs of
  anything unexplained. `--plan` and `--dry-run` move nothing; a
  `MOTION_LOCKED` file stops it before anything moves. Programmes are files
  in `programmes/`. `./reference.py M31 --make` keeps a field's deepest
  measured stack as a numbered reference, `./forced.py M31 RA DEC` gives a
  place's brightness or upper limit in every stack, and
  `./candidates.py M31` follows each candidate from night to night: every
  patrol measures the open ones again, seen or not.
- **What is new between two nights**: `./difference.py NEW --reference REF`
  lays one stack on another by their plate solves and subtracts them
  properly (ZOGY, in squares, allowing for photon noise and lining-up
  error), listing what is brighter now with how many fading peaks are as
  strong. `./vet.py SESSION` checks each candidate against both halves of
  the night, SkyBoT's asteroids, VSX, the Rochester lists of novae and
  supernovae, Gaia and the reference, and gives it a verdict.
  `./plant.py NEW --reference REF` plants fake novae in every raw frame and
  takes them through the whole pipeline, for the discovery completeness.
  Phase 1 of `docs/discovery.md`; measured on M31, 13 and 14 October 2026.
- **Polaris at the edge of the picture is centred again**: with the RA axis
  at the end of its reach the mount can probe one way only, and even a
  quarter step carried an edge star out of the picture, so centring gave up
  and `polaris.py find` reported Polaris 0.9° off. The probes now go down to
  a twentieth of a step. Found by the tests failing only at 22:10 UTC;
  checked at every hour of the day.
- **A run that fell behind no longer crashes or stops under cloud**: a frame
  the live stack had no time for is logged without figures, and the cloud
  report read them anyway (`KeyError: 'flux'`; the Windows tests, which
  run with one worker, failed on it). Such frames now say nothing about
  cloud either way, so twenty of them on a clear night no longer count as
  twenty rejections.
- `./depth.py --model --free` fits the star-width and sky terms too, once
  there are 20 independent stacks; a sweep counts as one night.
- **A stack for finding faint stars**: `./restack.py M31 --discovery` writes
  `discovery.fits` beside the picture, every frame that passes the checks
  weighted for a faint star's signal-to-noise and the poorest left out where
  they would lower it; the picture is untouched. Measured on M31: no deeper
  than the picture's stack (17.59 against 17.61), and two nights no deeper
  than one, which points at a noise floor (no darks or flats) rather than
  poor frames.
- **Depth from the conditions**: `./depth.py --model` fits how deep a stack
  reaches from star width, sky and time to every measurement kept (0.3 mag
  scatter); `--predict --fwhm 4.5 --sky 19.1 --minutes 5` says how deep a
  patrol would go before it is taken. Planted stars now start at G 13, the
  brightest in rounds of their own, and a stack other than final.fits keeps
  its own record (`discovery-depth.json`).
- **How faint a stack reaches, measured**: `./depth.py M31` plate-solves a
  stack, sets its zero point against Gaia DR3, gives the 5-sigma limit on
  open sky and on each brightness of galaxy glow, and with `--plant` plants
  copies of the stack's own stars to count how many are found again;
  `--sweep` does the same for 60 to 600 s of a session's frames. The first
  piece of the discovery plan (`docs/discovery.md`, phase 0). Measured on
  the M31 and M33 stacks of 6 to 16 October 2026: half the planted stars
  found at G 17.6 in 54 minutes of M31, 17.0 in 5 minutes.
- **Focusing with the motor**: `./focus.py --motor` brings the stars to
  focus with the motor focuser and nobody touching the telescope: out past
  focus, in by small steps through the sharpest point, then out beyond the
  gears' slack and in once to the best (`docs/focuser.md`). Proven on the
  150P on 15 October 2026: HFR 2.47. `--motor --dry-run` turns nothing
  and takes no pictures: it says whether the focuser is plugged in.
- **A paused run says why**: `shoot.py --through-cloud` says, when cloud
  pauses it, how bright the stars and the sky are against the kept frames,
  and so whether it looks like cloud lit by the town, thick cloud, or haze
  or dew (which the frames cannot tell apart: look up). While paused it
  says so again every 15 minutes, with the frames kept so far.
- **Polar alignment in centimetres and scale marks**: `tripod_cm_per_degree`
  and `latitude_degrees_per_mark` under `[mount]` (or the Settings screen),
  measured while aligning, make it say how far each foot moves for a tripod
  turn and how many marks on the latitude scale to raise or lower the axis.
  Measured on 15 October 2026: 2.3 cm a degree and about 1.9° a mark.
- `./camera_setup.py` restarts an INDI server that has lost the camera, as
  one left running while the camera was unplugged and plugged back in does;
  `--check` still only looks.
- **Mosaics** (`docs/imaging.md`): `./mosaic.py M31 3x1` lays overlapping
  panels along the camera's sides, turned as the last plate solve found it,
  and keeps their centres; `M31-P1` is then a target for `mount.py goto`,
  `shoot.py` and `restack.py`. With no grid it suggests one from the
  object's size. The catalogue's North America Nebula is 120' x 100', where
  it had 30' across. Not yet tried on the real mount.
- **Polar alignment says what to do with your hands**
  (`docs/calibration.md`). Centre the azimuth bolts first. More than 2° out
  to one side: turn the whole tripod, drawn from above as a clock face, with
  the centimetres each foot moves when the feet's spacing is in the settings.
  Otherwise which bolt to turn in and about how far, each drawn as a clock
  face, once the mount's bolts have been learned: `./polaralign.py --turned`,
  or two boxes on the screen, say what was turned, and the effect of a turn
  is worked out from the next measurement. Nothing is assumed about which
  bolt does what. The screen asks which bolt was turned in and how far, by
  name, never for a plus or a minus. Not yet used on the real mount.
- **From box to first galaxy** (`docs/first-night.md`): a first night for
  someone who knows none of the words, with the explanations folded away and
  each step marked as proven on a real mount or not yet. Its companion,
  `docs/how-it-all-works.md`, explains afterwards what each step was.
- `./mount.py findhome` gives each place's own miss from the fit, and leaves
  out one place, never more, that sits far from what the rest agree on.
- Fixed: a handset lead that comes out, or was never in, is a refusal that
  says what to do (`MOUNT_NOT_CONNECTED`), where it was a traceback.
- **`./mount.py findhome` and `truehome`** (`docs/calibration.md`): after a
  polar alignment, one run of plate solves either side of the meridian
  gives where the home position really is, apart from a tube out of square
  and what is left of the polar error; the mount is then driven there for
  the joints to be marked, and a second run after a restart shows what is
  left. Nothing remembered from earlier is used, and nothing moves except on
  a measurement from the same session that fitted. Simulated mount only.
- `docs/calibration.md`: setting a mount up in order, from a rough level to
  a marked home, and why `settime` is not automatic.
- `./mount.py settime` gives the handset this computer's date and time and
  the site's position, so they need not be typed on its keypad: press ENTER
  through its start-up screens and run it. Moves nothing. Run once on the
  real handset, where it worked.
- `./mount.py nudge`: from home, tips the tube 5° on the Dec axis and brings
  it back, with the same dry run, lock and limits as any move. The smallest
  move there is, for a person beside the mount to see that it really turns.
- **The mount's word is checked.** After the night the motors stopped while
  the handset reported every move as made: a GoTo with centring whose
  correction changes nothing, a polar measurement or pointing survey whose
  plate solves come back the same, and a skyline survey whose pictures do
  not change now stop the mount and refuse with `MOUNT_NOT_MOVING`
  (`moved.py`). By day it only records what it sees: its first real frames
  showed the optics' own marks passing for an unchanged view.
- **Measurements in place of assumptions**, each one command, none yet run
  on the real mount: `./polaralign.py --repeat 5` (does the polar
  measurement repeat?), `./camera_test.py --timing` and `--trail` (how long
  is the shutter really open?), `./mount.py response` (does the drift answer
  the Dec motor in proportion?), `./mount.py pointing` (is one pointing
  correction for each side enough?), `./focus.py --report` (how quickly was
  a turn of the knob heard?).
- **`./ty characterise`**, and the application's **Rig knowledge** screen:
  what this rig has had measured about itself, and for each thing it has not,
  the command, or on the screen a "Measure this" button. A measurement that
  moves the mount is shown as a plan first.
- The check that the telescope turned keeps every judgement with its
  figures (`cache/moved_log.jsonl`: how far the mount was turned, how far
  the view was seen to move) and the two pictures behind every "same view"
  (`cache/moved/`), so its first thresholds can be set from real frames.
- `./polaris.py find` looks within 1.6° instead of 3° when `polaralign.py`
  put the axis close to the pole in the last fortnight.
- The README now opens with what makes telescopeyoke different (a home
  position set by eye, a manual focuser, a garden skyline, setting up before
  dark, a rough polar alignment, short exposures rebuilt from the raw
  frames), each marked with how far it is proven. "Current status" is a
  table; the night-by-night account has moved, whole, to
  `docs/validation.md`. "Three parts" has become "The scripts underneath".
- **Focusing by ear, reworked for quick frames** (`docs/focus.md`). A click
  and a tone for every frame measured, the tone higher as focus improves,
  with the camera already exposing the next frame. Three levels it moves
  between by itself: quick binned frames judged one at a time, then many
  stars on binned frames, then the full sensor with the readings steadied.
  Words only at the turning points: "Level two", "Level three. Fine focus",
  "Minimum passed. Reverse slightly", "Best focus", "Focus good. Hold".
  Sizes are also given in arcseconds, the levels are set in them, and each
  run that ends on "Focus good" teaches the next what good focus comes to.
  Every frame's capture, measuring and feedback times are printed and kept.
  Proven on made-up star fields only: no real camera has run it.
- Changed: `focus.py` no longer speaks every reading, and `--tones` has gone,
  the click and tone being what it does unless `--quiet`. The Focus screen's
  sound choice is "Clicks and tones" or "Silent".
- The camera layer takes a purpose, `cam.use("focus_fast")`,
  `cam.use("focus_fine")` or `cam.use("imaging")`, and sets the binning
  itself on either route. A camera that will not bin carries on unbinned.
- The focusing sounds no longer need `ffplay`: Linux plays them with
  `pw-play`, `paplay`, `aplay` or `ffplay`, Windows by itself.
- **First night of polar alignment by plate solving on the real mount**
  (6 October 2026): from about 6° to 0.2° from the pole in five rounds.
  `./polaralign.py --step DEG` turns less between photographs, for a garden
  where the third would be of a house or a tree, and a round waits 5 s after
  each turn, not 30.
- **`focus.py` measures only the bright stars.** Far out of focus it had been
  reading the sky's grain. `--numbers` speaks each reading in place of the
  click and tone.
- **The pointing error is kept for each side of the meridian**, not as one
  figure reversed across the pole, which sent every first GoTo across the
  meridian 6° wide on the real mount.
- **`focus.py --field`** goes first to a bright star with many round it
  (it moves the telescope), and the meter no longer takes specks of grain
  for stars when the focuser is far out.
- **The final picture is framed where most frames sat**, not where the
  sharpest one happened to be, and the live run matches stars on a frame that
  has drifted past the rough line-up, so it knows how far it has drifted and
  re-centres when it should.
- **An object that fills the frame keeps its glow**: only a level is taken
  off its sky, and the colours are balanced on the stars alone.
- **The live picture is finished like the final one** from the fifth frame,
  and a run that cloud stops leaves the live view running.
- **`polaralign.py` keeps clear of what is known to be in the way** and goes
  back to where it started when a photograph will not solve.
- **A run says so when frames arrive faster than their exposure.** The 183C
  here exposes for about 0.63 of what it is asked; see the README.
- **`horizon.py --trace --torch`**: by night, with a torch fixed along the
  tube, what it lights is in the way and a dark frame with no stars is
  cloud. Tried on the real mount; the first survey was spoiled by cloud
  arriving, which it now notices.
- **`solve.py` tries again on a frame averaged in blocks** when stars too
  soft to be taken for stars leave the first try with nothing.
- **The skyline from a phone panorama** (`./panorama.py`, and the Horizon
  screen): the line between sky and everything else is found in the picture
  and can be redrawn, two marks tie it to the compass, and panoramas from
  other heights add doubt where near things sit differently. No motors, a
  few minutes. Found well in two real panoramas and badly in a third; not
  yet tied to the compass for real.
- **The planner uses a measured skyline directly**, from `cache/horizon.json`,
  raised by `margin` under `[horizon]` (2° unless changed). There is nothing
  to copy into `config.toml` any more; `use_survey = false` leaves it out.
- **`horizon.py --trace` looks less and says more.** It starts 30° apart and
  adds bearings only where the skyline bends; it starts from the skyline
  already measured and looks further only where that is wrong; by day each
  small square of a frame is judged by brightness, smoothness and colour
  against the day's own sky; a frame showing the top itself, by day or among
  stars, ends the search there; by day it waits only until two frames agree
  and reports how long that took; and every look's picture is kept, marked
  with what was not taken for sky. `--show` and `--forget` are new. On a
  made-up garden it takes about 60 looks from nothing and about 22 from a
  known skyline. None of this has been run on the real mount.
- The camera on a USB 3 lead, timed indoors: a full frame at a 1 s exposure
  in 1.54 s, against 9.3 s on USB 2. Figures in `docs/validation.md`. No
  night has been run on it yet.
- Fixed: `./camera_test.py --throughput` could leave the camera on native
  transfer, after which no frame could be read by anything. It now stops the
  exposure before changing back, and the camera is put back on FITS
  whenever it is opened.

## 0.2.1: two telescopes, and asking a controller what it is

For someone who already has a working setup, perhaps with two telescopes and
EQMOD: it fits beside what they have, and can find out safely whether it can
talk to their mount.

- **Rigs**: more than one telescope on one computer, each with its own
  settings (`rigs/NAME.toml`) and its own frames, pictures and measurements.
  `./app.py --new-rig NAME`, `./app.py --rig NAME`, `./ty --rig NAME ...`,
  and `./ty rigs` or the application's Rigs screen to see them all.
- **`./doctor.py --report --probe PORT`** asks whatever is on a serial port
  you name what it is, as a SynScan handset and then as a motor board, with
  questions that only read. For controllers such as an EQStar, where nobody
  yet knows whether telescopeyoke can talk to them.
- The hardware report lists each serial port's adapter, maker and USB
  numbers, and whether the handset gives a position (never the position).
- On Windows the doctor says when ASCOM or EQMOD is installed, and that only
  one program can have the mount's port. Neither is used or changed.
- Azimuth by day from a remembered landmark (`landmark.py`).
- Fixed: the doctor stopped dead, instead of reporting it, when a mount
  reached without its handset did not answer.

**Proven on, and not**

Nothing has changed in what has run on real equipment since 0.2.0. Rigs have
been run only as tests, never with two real telescopes. `--probe` has never
met a real controller: finding out whether an EQStar or another EQMOD-style
controller answers is what it is for. The ASCOM and EQMOD notice has not run
on a computer that has them. `landmark.py` has not been run on the real
mount. The README's "Current status" has the rest.

## 0.2.0: the application and the demo

Everything since the first night, and the first release someone else can try
in one step with no telescope.

**Try it with nothing plugged in**

- **TelescopeYoke (demo)** is the whole thing on a pretend telescope: a
  pretend mount, camera and sky, with the real centring, focusing and
  stacking code running on them. Nothing real is connected or moved, and its
  files are kept in a folder of their own.
- One step to start it, from the release's zip. Ubuntu: `./install.sh
  --demo`. Windows: double-click `try-demo.cmd` (Python 3.11 or newer must
  be installed first).
- `./tour.py` records the demo being used; the animation in the README is
  what it wrote.

**New**

- **The application** (`app.py`): one window with everything in it, started
  from the applications menu on Ubuntu or the Start Menu on Windows. Every
  move is checked with a dry run and shown as a plan; nothing turns until you
  confirm it. `console.py` is the same observing screens as a page in a
  browser.
- **A Windows port.** It runs natively on Windows 10 and 11, with the camera
  read through Altair's own library instead of INDI.
- **A hardware report in one command**: `./doctor.py --report`, or "Write a
  hardware report" on the application's Doctor screen. It says what the
  computer is, what the handset says the mount is, and every check, with
  your location left out, and which release or commit it was run from.
  Nothing is moved to make it.
- **The mount without its handset**, through the SynScan Wi-Fi adapter or an
  EQDIR lead (`direct.py`).
- **A rewritten imaging pipeline**: every raw frame kept, poor frames
  rejected, stars lined up to a fraction of a pixel across a turning field,
  clipped and weighted stacking, a quality pass, calibration frames, and
  several sessions combined into one picture.
- **Focusing by ear**: many stars measured at once, and the result spoken.
- **Making the best of a rough polar alignment**: the drift is measured,
  predicted anywhere in the sky, and a motor is crept against it.
  `polaralign.py` measures the polar axis itself.
- **A horizon survey** that finds what blocks the sky, by night or by day.
- **For programs and AI agents**: `--json` from every script in one shape,
  `--dry-run` for anything that moves, the `ty` command, a read-only web API
  and a read-only MCP server.

**Proven on, and not**

- Under real stars, by the author, on Ubuntu: a Sky-Watcher EQ3 Pro SynScan
  (handset firmware 3.35), an Explorer 150P and an Altair Hypercam 183C.
  The planner, mount moves, plate solving, `goto --solve`, `sync`, camera
  frames and focusing have all run there.
- On Windows 11 the tests and the demo pass and the camera, a Hypercam
  183C, has taken frames indoors. **No mount has been driven from Windows**, and `try-demo.cmd` has
  not yet been run on a real Windows machine.
- The application has been used in the demo only, not with a real mount or
  camera. The stacking pipeline, the drift correction, polar alignment and
  the handset-free link were written or rewritten since they last met real
  equipment; the README says which is which.
- The two questions `--report` asks the handset (its firmware version and
  the mount's model) are from Sky-Watcher's published protocol and are
  tested against the simulated handset; no real handset has been asked yet.
- Nobody but the author has run it. EQ5, HEQ5 and EQ6 owners with a SynScan
  handset: a report from you, working or not, is the most useful thing this
  project could get.

Tests run on every push on Python 3.11 to 3.14, on Ubuntu and on Windows,
with no hardware.

## 0.1.0: first light

The first release: what worked on the first night under real stars. The
night planner, SynScan mount control through the handset, plate-solve
centring, a spoken focus aid, short-exposure stacking, a status page, a demo
mode with a simulated mount, and `doctor.py`.
