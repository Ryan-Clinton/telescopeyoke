# Commands

`./ty` is the single way in. Every line below accepts `--json`; those marked
*demo* accept `--demo`. What each command may do is classed in `policy.py`
(`./policy.py COMMAND`), and the sections here follow it: a test keeps them
in step.

## No hardware: reading, planning and files on this computer (never touches the mount's serial port)

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
| `ty watch-run [--session FOLDER] [--once]` | nothing while the run is well; a line each time frames stop coming, stop being kept, the share kept halves, the stars dim or come back, and when the run ends, which ends the watch (`runwatch.py`) | `schemas/watch-run.schema.json` (with `--once`). Reads the run's files only; meant to be started as a Monitor so an agent is woken only by its lines |
| `ty characterise` | what this rig has had measured about itself and what it has not: frame timing, real exposure, focus response, pointing error on each side, polar error and its repeatability, drift response, skyline, and whether a move has been confirmed by the camera | `schemas/characterise.schema.json`. Reads files only. Each item names the command that measures it |
| `ty candidates` | every field's open candidates in one list, the most nights seen first, each with its field; and the comet hunt's newest tracks heading in towards the Sun (`comets`) | `schemas/candidates.schema.json` (name "every field"). Reads files only |
| `depth.py TARGET [--plant] [--sweep]` | how faint a stack reaches: its zero point against Gaia DR3, the 5-sigma limit on open sky and on each brightness of galaxy glow, and with `--plant` the share of planted stars found at each magnitude; `--sweep` does the same on the first 60 to 600 s of the session's frames | `schemas/depth.schema.json`. Reads the stack and keeps `depth.json` beside a `final.fits` (`NAME-depth.json` beside another stack); fetches Gaia once per field. Not through `ty` |
| `depth.py --model [--predict --fwhm F --sky S --minutes M]` | how depth follows star width, sky and time, fitted to every kept measurement; with `--predict`, how deep a stack under those conditions would reach | `schemas/depth-model.schema.json`. Reads files only |
| `difference.py NEW --reference REF [--plant N]` | what is brighter in NEW than in REF, by proper image subtraction: candidates with a score in units of the local noise and how many fading peaks are as strong; `--plant` adds fake transients and counts those found | `schemas/difference.schema.json`. Reads two stacks, plate-solves both, keeps `candidates.json` and `difference.fits` beside the new one. Candidates are not vetted. Not through `ty` |
| `patrol.py PROGRAMME --plan` | a discovery patrol's readiness (motion lock, reference, focus age, expected depth) and the commands it would run | `schemas/patrol.schema.json`. Moves nothing |
| `patrol.py --analyse SESSION` | depth, subtraction from the reference, vetting, and a short answer with cut-outs of anything unexplained. A stack whose half-found depth is brighter than G 16, or of fewer than 8 frames, is not searched: it could not show an M31 nova, or a cosmic ray would pass for one | Reads the session; keeps `patrol.json` and `patrol-N.png`; asks SkyBoT, VizieR and the Rochester pages |
| `patrol.py --sweep [--all-history]` | `--analyse` on every session not yet searched whose field has a reference it was not made from: the last 3 days, or every one kept | Same as `--analyse`. `shoot.py` and `restack.py` already start `--analyse` in the background (low priority, `patrol.log`) on each new stack of such a field; the sweep catches what that missed |
| `reference.py NAME [--make [--from STACK]] \| --list` | a field's kept references, each a numbered version with where it came from and how deep it reaches; `--make` keeps the deepest measured stack as the next version | `schemas/reference.schema.json`. Writes `reference/NAME/vN.fits` and its record only with `--make`; never replaces a version. `difference.py` uses the newest when not given `--reference` |
| `recover.py NAME RA DEC --before DATE --after DATE [--band zr]` | whether the subtraction finds a known transient in public ZTF images from before and while it was there: how close, how strong, its rank | `schemas/recover.schema.json`. Fetches ZTF cut-outs from IRSA into `cache/ztf/`. Tests the software, not the rig's depth |
| `sungrazer.py fetch\|look\|hunt [--camera c3\|c2\|ccor1] [--hours H] [--until TIME] [--raw] [--plant N] [--install]` | hunt: fetch the last day, look, keep what heads for the Sun in `sungrazer/hunt-CAMERA.json`, delete pictures over 3 days old; `hunt --install` runs it every 6 hours as the user timer `ty-sungrazer` (CCOR-1 only); fetch: SOHO LASCO pictures (with `--raw`, the raw FITS ones, about 2 MB each, for fainter comets), each once, a second apart; look: points that move other than as the stars drift, each with a movie under `sungrazer/DATE/` | `schemas/sungrazer.schema.json`. Needs no sky. Never reports: a person watches the movie and reports through the Sungrazer Project's form |
| `transits.py [tonight] [--deeper PCT]` and `transits.py measure SESSION --planet NAME` | tonight: known transits whole in the dark here, deepest first, each star kept by name for `mount.py goto`; measure: the star's light curve from the night's frames and the fitted depth and timing | `schemas/transits.schema.json`. Planets from NASA's Exoplanet Archive, kept a week. Never moves the mount; an ExoClock submission is a person's |
| `variables.py FIELD [--session NAME ...] [--bin N] [--offline]` | light curves of the field's Gaia stars from batches of each night's kept frames; the ones that scatter more than stars as bright, and every star VSX knows, each with a picture of its curve, kept in `frames/FIELD/variables.json` | `schemas/variables.schema.json`. Stacks every frame again in batches: minutes per night. One not in VSX is a candidate for a person, never reported |
| `brokers.py [--days N] [--brighter MAG] [--unreported] [--demo]` | new transients from the public alert broker ALeRCE that are bright enough for the rig and up in the dark here tonight, each with its height, brightening or not, and whether the Rochester lists have it; with `--unreported`, the last 30 days' bright ones on neither list, up here or not | `schemas/brokers.schema.json`. The Transient Name Server needs a key, so it is not asked: its search link is given. Never moves the mount |
| `report.py CANDIDATE [--quick]` | everything a report of a new transient needs (position and error, UTC time, magnitude and limit, last non-detection, reference, checks, finding chart north up) and what is still wanting before it is sent | `schemas/report.schema.json`. Keeps `reports/ID/`: report.json, report.txt ready to paste, finding.png. **Never sends anything** |
| `candidates.py NAME [--all] [--dismiss ID --reason LABEL [--note TEXT]] [--reopen ID]` | a field's candidates followed from night to night: each night found, and each night measured at its place and not found. `--dismiss` records a person's judgement that one is not real, with one of the labels a classifier will learn from (noise, hot pixel, edge, bad subtraction, satellite, cosmic ray, bright-star halo, cloud or tree, real star, asteroid, variable star); `--reopen` undoes it | `schemas/candidates.schema.json`. Reads `candidates/NAME.json`, which `patrol.py` keeps; only a dismissal or reopening writes it. Dismiss only on the person's word |
| `forced.py NAME RA DEC [--difference]` | one place measured in every measured stack of an object: a magnitude, or how faint it must have been; with `--difference`, the light above the field's reference there | `schemas/forced.schema.json`. Reads files and plate-solves; keeps `forced-RA-DEC.json` |
| `vet.py SESSION [--offline] [--no-halves]` | every candidate `difference.py` left, with the evidence for what it is (in both halves of the night, a known asteroid from SkyBoT, a VSX variable, a nova or supernova on the Rochester lists, a Gaia star, light in the reference) and a verdict; only the "unexplained" are worth a person's eyes | `schemas/vet.schema.json`. Keeps `vetted.json`. Asks SkyBoT, VizieR and the Rochester pages unless `--offline`; not the Transient Name Server (needs an account). Not through `ty` |
| `plant.py NEW --reference REF [--count N]` | fake novae planted in every raw frame of a session and taken through the whole pipeline; the share found at each magnitude is the discovery completeness | `schemas/plant.schema.json`. Writes a planted copy under `frames/NAME-planted/`, deletes its raw frames afterwards, keeps the stack and `plant.json`. A plate solve per frame and a full restack: run it on the desktop. Not through `ty` |
| `ty rigs` | every rig (a telescope with its own settings and files): how its mount is reached, and its newest imaging run | `schemas/rigs.schema.json`. Reads files only. `ty --rig NAME <command>` runs any command for one rig |

## Asks the handset (opens the serial port; do not run while another command is driving the mount)

| Command | Returns |
|---|---|
| `ty mount status` | `slewing` / `tracking` / `stopped`, position, pier side |
| `doctor.py --report --probe PORT` | the hardware report, plus what answers on that one port: a handset, a motor board, or nothing. Questions that only read; no `--json`. Only for a port a person has named |

## The skyline (nothing moves, except `horizon.py` without `--show`, `--forget` or `--dry-run`)

| Command | Returns |
|---|---|
| `horizon.py --show` | the measured skyline as points (`az`, `alt`), the same with the margin on (`usable`), where it came from and when |
| `horizon.py --forget` | throws the measured skyline away |
| `horizon.py --trace --dry-run` | how many bearings, how many are within the limits now, minutes, and whether it would start from a known skyline |
| `panorama.py use PICTURE` | finds the skyline in a phone panorama; writes `horizon/skyline.jpg` to look at |
| `panorama.py move ACROSS,DOWN ...` | puts points of that line right |
| `panorama.py mark ACROSS DOWN BEARING HEIGHT` | ties a place in the picture to the compass; `--landmark NAME` takes a remembered landmark's, `--telescope` asks the mount where it points (opens the serial port) |
| `panorama.py also PICTURE`, `unmark N`, `show`, `clear` | a panorama from another height; housekeeping |
| `panorama.py save` | the skyline, kept for the planner; warnings for what the picture did not show |

Places in a picture are shares of it, 0 to 1 across and down, or pixels of
the picture as given. A panorama shows the garden: it is copied to
`horizon/` under the data folder, which git ignores, and never goes in the
repository.

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
`shoot.py --dither N` re-centres every N frames a little off the target (a plate-solved GoTo).
`patrol.py PROGRAMME` points at the field with `mount.py goto` and images it with `shoot.py`, then
analyses the night; a programme with a mosaic (`m31-panels`) does each panel in turn, in order of
priority, as long as the night allows; a `MOTION_LOCKED` file stops it before anything moves, and `--dry-run` runs both
commands with their own `--dry-run`.
`horizon.py` (with `--trace`, `--daylight`, `--fresh`) slews all over the sky for up to an hour,
looking at each bearing; `--dry-run` says what it would do.
`landmark.py check NAME` turns the mount to the axis readings a landmark was
remembered at and photographs it (`--watch N` keeps looking); `landmark.py
remember NAME` and `list` move nothing. `polaris.py check` takes ten frames where the telescope is and says whether Polaris is likely to show
by day (sky, Sun, focus); it moves nothing. `polaris.py find` looks around the home position until Polaris is in
view, the part within 1.2° first: the RA axis crosses from 88° one side of home to 88° the other once for each
part. It refuses on an unchecked focus without `--anyway`, waits at a place while the sky there is not blue, tips
the tube a twentieth of a degree twice to see a candidate move with the sky, and brings the star to the middle;
`--record` keeps every look under `polaris-runs/`. `polaris.py align` then tips the tube a tenth of a degree,
turns the RA axis to five readings and back, and gives the polar axis's error roughly; `--watch N` then looks N
more times without moving while the bolts are turned. All take `--dry-run` and `--json`. `polaralign.py` slews about 25° twice and back to measure the polar axis's
error; it checks all three positions against the limits first, and takes
`--dry-run` and `--json`; `--repeat N` does it N times over to find the scatter; `--cross-check` compares it with the last measurement from the other side of the meridian and withholds advice when they disagree by more than 1°. `ty mount findhome` makes the same
slews as `pointing` and works out where home really is; `ty mount truehome` then goes there, only on a
measurement made in the same session, and holds. `ty mount settime` sets the handset's clock and position and
moves nothing. `ty mount nudge` tips the tube 5° from home and back. `ty mount pointing` slews
to eight hour angles, four each side of the meridian, plate-solving at each, and swings the tube over the pole
once; check it with `--dry-run` first. `ty mount response` slews nothing but creeps the Dec motor at up to
1 arcsecond a second for about 35 minutes. `camera_test.py --trail` stops the mount following the sky for one
frame and starts it again. Any of these, and `goto --solve` and `horizon.py --trace`, can refuse with
`MOUNT_NOT_MOVING`: the camera's view did not change though the mount said it moved. Do not retry; a person must
look at the mount. `ty mount drift` changes the Dec motor's creep. `ty mount stop` halts
everything and is always allowed. `shoot.py` re-centres the target as it
drifts unless given `--no-recentre`. `focus.py --field` first slews to the
best placed of a short list of bright stars with many round them, keeping
to the side of the meridian the tube is on when one there is high enough,
and clear of the directions listed as blocked; `--dry-run` names the star.
`starwatch.py STAR` (`tabby`: KIC 8462852) images a watched star through the
patrol and its checks, measures it against the stars round it, keeps each
night in `frames/NAME/starwatch.json` and calls a night 0.03 mag or more
fainter than usual, beyond its scatter, a dip (`schemas/starwatch.schema.json`);
`--plan` moves nothing, `--measure SESSION` and `--history` only read frames
already taken. Reporting a dip is a person's.

## Uses the camera, not the mount

`snap.py`, `liveview.py`, `focus.py` (without `--field`), `solve.py`, `skywatch.py`,
`calibrate.py`, `camera_test.py`, `shoot.py --no-recentre`.

`focus.py --motor` turns the focuser and takes pictures; with `--dry-run` it only
looks for the focuser's port and says what it would do.

`focuser.py test` and `move` turn the focuser's motor, never the mount; `flash`
loads the Nano's firmware. See `docs/focuser.md`.

`camera_setup.py` gets the camera ready and is safe to run at any time: it
checks the camera is plugged in and has a driver, copies Altair's library
files out of their SDK zip into `vendor/altair/` if they are missing, and
takes one short test frame. `--check` copies nothing and takes no frame.
`--json` gives each step as `{step, status, message}` with `ready` and, when
not ready, `next`: the one thing the person has to do.

## Reaches outside (a person must have asked, or set it up to)

| Command | Returns | Notes |
|---|---|---|
| `notify.py --test` or `notify.py TEXT` | a message to the person's phone by their Telegram bot (`[telegram]` token and chat in config.toml, or TY_TELEGRAM_TOKEN and TY_TELEGRAM_CHAT); the patrol and the comet hunt call it themselves | `schemas/notify.schema.json`. Nothing is sent without a bot set up, from the tests, or in the demo |

## Output rules

- With `--json`, stdout holds exactly one JSON document; anything else is on stderr.
- Exit code 0 means `ok: true`.
- Human-readable output may change freely; the JSON only changes with `schema_version`.
