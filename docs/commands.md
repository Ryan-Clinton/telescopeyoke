# Commands, and how they fit together

[README](../README.md) · [All docs](README.md) · Guides: [First night](first-night.md) · [Setup](setup.md) · [Imaging](imaging.md) · [Calibration](calibration.md) · [Focus](focus.md) · Science: [Discovery](discovery.md) · [Results](results.md) · [Validation](validation.md) · [Data](data.md) · Developers: [Contributing](../CONTRIBUTING.md) · [Agents](agents/README.md)

The application (`./app.py`) is the front door. Underneath it is a set of
scripts, each of which can be run by itself from a terminal, and the
planner needs no telescope at all. For programs and AI agents, `./ty` is
one way into all of them: [docs/agents/commands.md](agents/commands.md).

## The scripts, by job

| For | Scripts | Needs |
|---|---|---|
| **Planning the night** | `tonight.py`, `serve.py`, `clouds.py` | Any computer with Python. No telescope. |
| **Setting up** | `doctor.py`, `camera_setup.py`, `polaralign.py`, `polaris.py`, `landmark.py` | The mount and camera. |
| **Measuring the site** | `panorama.py`, `horizon.py` | A phone panorama; for the telescope's own survey, the mount and camera. |
| **Moving the mount** | `mount.py`, `watch.py` | A SynScan mount and its serial lead. |
| **Focusing** | `focus.py` | A supported camera. |
| **Imaging** | `snap.py`, `solve.py`, `shoot.py`, `planet.py`, `mosaic.py`, `liveview.py`, `skywatch.py` | A supported camera and ASTAP. On Linux the camera is read through INDI; on Windows through Altair's own library, which is the only camera route there. |
| **Processing** | `restack.py`, `calibrate.py`, `process.py`, `compare.py` | The raw frames a run kept. |
| **The cooled mono camera** | `keeper.py`, `sxwheel.py`, `colour.py`, `instrument.py`, `cameras.py`, `corners.py` | The 183M (read through Altair's own library, on Linux too) and its filter wheel. |
| **Discovery** | `patrol.py`, `vet.py`, `candidates.py`, `realbogus.py`, `depth.py`, `report.py`, `brokers.py`, `sungrazer.py`, `transits.py`, `precision.py`, `variables.py`, `starwatch.py` | Frames from the telescope; the comet hunt and public alerts need none. |
| **Research without the telescope** | `archive.py`, `investigate.py`, `seti.py` | An internet connection. |

Start with the planner; add hardware when you have it. [The table below](#every-script)
says what each script does.

## Every script

| Script | What it does |
|---|---|
| `tonight.py` | Report for the night: darkness, Moon, weather verdict, ranked targets. `--html` writes the web page. |
| `serve.py` | Serves the status page on port 8080: the night's report rebuilt every 10 minutes, and the imaging run, pictures and system panel refreshed every two seconds. `--install` runs it as a systemd user service (`ty-serve`) that starts at boot and restarts if it stops. |
| `clouds.py` | Fetches the latest infrared satellite image with the site marked on it. |
| `mount.py` | Moves the mount: `status`, `settime` (gives the handset this computer's date, time and the site's position, once you have pressed ENTER through its start-up screens), `nudge` (from home, tips the tube 5° and back, for someone beside it to see that it turns), `home`, `zenith`, `goto NAME [--solve]`, `point AZ ALT`, `sync`, `drift`, `compensate`, `stop`. `response` sets the Dec motor creeping at five rates and measures the drift at each, to see whether the sky answers in proportion; `pointing` plate-solves at eight hour angles, four each side of the meridian, to see whether one correction for each side is enough. `findhome` works out from one run of plate solves where the home position really is, and `truehome` drives there for the joints to be marked. |
| `liveview.py` | Takes a frame every few seconds so the status page shows what the telescope sees now. Steps aside while `shoot.py` runs. |
| `app.py` | TelescopeYoke, the application: one window with everything in it, started from the applications menu. `./app.py --demo` tries it with nothing plugged in. |
| `console.py` | The same observing screens as a page in a browser, without the equipment set-up and tools: the companion to the application. This computer only. |
| `polaralign.py` | Measures how far the polar axis is from the pole by plate solving at three positions, and says which way to turn each adjuster. `--repeat 5` measures five times with the bolts left alone and gives the scatter. After each measurement it says which bolt to turn and about how far, or to turn the whole tripod; `--turned AZ ALT` tells it what you turned since the last one, and it learns what a turn does on this mount. `--cross-check` compares the answer with the last one from the other side of the meridian and gives no advice when they disagree. |
| `polaris.py` | Polar alignment before dark, from Polaris alone, which shows in daylight when nothing else near the pole does. `check` says whether it is worth trying (sky, Sun, focus); `find` looks around the home position until the star is in the picture, proves it by tipping the tube, and can keep every look (`--record`); `align` turns the RA axis with it in view, says roughly which way to move each adjuster, and with `--watch` keeps saying how far is left while the bolts are turned. |
| `landmark.py` | Sets the azimuth by day: remembers a distant fixed thing with the telescope's axis readings, and next time turns back to it and shows how far it has moved. |
| `panorama.py` | The skyline from a phone panorama, with no motors: finds the line between sky and everything else in the picture, lets you put it right where it is wrong, ties the picture to the compass from two marks (something the telescope is pointing at, a remembered landmark, or typed bearings), and keeps the result for the planner. Panoramas from other heights add doubt where things close by sit differently. |
| `horizon.py` | The telescope measuring its own skyline, or checking a panorama's. `--trace` starts 30° apart, adds bearings only where the skyline bends, starts each from the skyline already measured, and checks its own answer; `--daylight` works by day, judging each small square of the frame by brightness, smoothness and colour; a frame that shows the top itself gives the height at once. `--show` prints the skyline in use, `--forget` throws it away. `--move-from SPOT --offset METRES BEARING --distances FROM-TO:METRES ...` works a new spot's skyline out from another spot's, by geometry, with 3° of doubt added, until it is surveyed. Without `--trace` it looks on a fixed grid, as it first did. |
| `snap.py` | Takes one camera frame, saves the FITS in `frames/`, publishes a preview. |
| `shoot.py` | Takes a picture: many short exposures, each checked, lined up and stacked live, with the raw frames kept. `--exposure auto` picks the longest exposure the tracking allows. `--frames 0` carries on until cloud stops it. While it runs, `./ty run stop` ends it cleanly with its final picture; `recentre`, `assist-on` and `assist-off` are also understood. |
| `planet.py` | Photographs a planet: hundreds of frames of a few hundredths of a second, a square round the planet kept from each, the sharpest quarter lined up and stacked, sharpened and given the planet's usual colour. `--restack FOLDER` stacks a saved capture again. Point the telescope first with `mount.py goto Saturn --solve`. |
| `mosaic.py` | Splits an object bigger than the frame into overlapping panels along the camera's sides, and keeps their centres; each panel is then a target, `M31-P1`, for `mount.py goto` and `shoot.py`. With no grid it suggests one from the object's size. |
| `restack.py` | The quality pass: goes back over a session's raw frames, keeps the best, weights and clips them, and writes the finished picture. `shoot.py` runs it at the end. `--all`, or several session folders, stacks sessions from one night or many into one picture. `--on HOST` does the work on a faster computer reached by SSH (a name in `~/.ssh/config`) and brings the picture back (`remote.py`). |
| `calibrate.py` | Makes master dark, bias and flat frames, which `shoot.py` and `restack.py` then apply automatically. |
| `camera_setup.py` | Gets the camera ready: checks it is plugged in and has a driver, takes Altair's library files out of their SDK zip if they are missing, and takes a test frame. `--check` only looks. Also the "Set up the camera" button in the console. |
| `stream.py` | Streams the telescope live to YouTube, Twitch or both at once while a run is imaging, and stops when it is not, in 1080p (720p if the upload falls behind): the stack with one exposure, what the object is, the programme (a transit's light curve once it is steady, a patrol's panel map) and the figures, a card between targets and at the night's end; never the place, the webcam or a candidate's position. Drawn by `streamlook.py` from the words in `stream-targets.toml` ([docs/stream-look.md](stream-look.md)); `./stream.py preview` draws each state. On Twitch it sets the channel's title, category and tags for each target (`twitch.py`, after a one-time `./stream.py twitch-login`). A presenter (`streamstory.py`) turns chapters, explainers and a slow crawl through the night, all curated or measured, and `streamchat.py` answers `!what`, `!next` and the like in the chat. Off unless switched on in Settings; `./stream.py key` puts the stream key in `~/.config/telescopeyoke/stream-key`, and `./stream.py key youtube` or `key twitch` each service's own key for streaming to both (`[stream] service = ["youtube", "twitch"]`: encoded once and sent to each through ffmpeg's tee, so one dropping leaves the other on air). Encoded on the laptop's video hardware where it works. `watch --to FILE` tries it with no account; `watch --install` runs it from boot. Live on Twitch since 20 October 2026; the public pages and what they read are in [docs/live-page.md](live-page.md). |
| `mission.py` | Each programme as a mission for the stream: its goal, its milestones from what was measured, the open question with tonight's figures, a confidence label for a result, the WHAT / WHY / NOW / NEXT line and the RAW → RESULT reveal ([docs/stream-look.md](stream-look.md#the-mission-what-why-how-far-and-what-is-still-unknown)). |
| `narrator.py` | TelescopeYoke's voice on the stream: a curated first-person sentence when something happens, and the mission now and then, spoken by gTTS into the stream's sound ([docs/streaming.md](streaming.md#the-voice)). |
| `clips.py` | Clips of the night's moments cut from a rolling buffer of what was sent, into `clips/` ([docs/streaming.md](streaming.md#clips-of-the-big-moments)). |
| `director.py` | Decides in one place what the observatory is doing and so what the stream shows: the target (what the telescope was last aimed at and how far the aim got: moving, centring, reached by the mount's reading, centred by the camera, or failed; `cache/target.json`, set by every GoTo), the programme, the activity, the scene and the picture, with fresh camera frames over any older run or schedule. Kept in `cache/broadcast.json`; `./stream.py director` says what it decided and what it left out, `./stream.py scenes` draws every scene ([docs/streaming.md](streaming.md#what-is-on-screen-and-why-the-director)). |
| `schedule.py` | Tonight's schedule: the agreed steps of a night (`add LABEL MINUTES [--not-before HH:MM] -- COMMAND`, or `wait LABEL MINUTES PID` for one already running), run in order by `run`, with each step's expected start and finish and its progress, shown on the console's home screen; a step that fails stops the rest and fetches the person (`alert.py call`). |
| `camera_test.py` | `--capabilities` lists what the camera is and offers (model, firmware, FPGA, when it was made, frame buffer, USB link: the camera's part of Altair's Diagnose File); `--throughput` times every way of getting frames off it; `--gain-sweep` tries a range of gains on tonight's sky and suggests one. `--timing` shows whether frames arrive sooner than their exposures could have ended; `--trail` stops the mount following the sky for one frame and reads the real exposure from the stars' trails. `--banding` and `--stripes` measure the row stripes; `--cooldown`, cap on outside, measures them every few minutes as the camera cools, with the air temperature, dew point and USB port (`docs/banding.md`). |
| `compare.py` | Shows the same patch of sky from several stacks side by side at full size, with star measurements for each. |
| `process.py` | Turns a finished stack into a cleaner picture: level sky, white stars, smoothed colour noise. |
| `focus.py` | Hands-free focusing aid: a click and a tone for every frame measured, higher as focus improves, in three levels from quick binned frames to many stars on the full sensor. `--quiet` for no sound, `--numbers` for each reading spoken as a number, `--field` to go first to a bright star with many round it (this moves the telescope), `--scene` for a daytime view. `--report` says how quickly the last run answered a turn of the knob, level by level. |
| `solve.py` | Plate-solves a frame: where is the telescope really pointing? |
| `skywatch.py` | Photographs the sky every minute and stops when stars appear. |
| `doctor.py` | Checks what is installed and connected, and says what is ready: planner, mount, imaging. `--report` writes the same out to post as a hardware report, with the mount's model and the handset's firmware as the handset gives them, and your location left out; `--probe PORT` adds what answers on a serial port you name. |
| `tour.py` | Records the demo being used, pressing the same buttons a person would: the animation at the top of this page, and a still of each screen. Ubuntu only. |
| `replay.py` | Turns a centring run recorded with `mount.py goto --solve --record` into a GIF. |
| `watch.py` | Photographs the telescope itself with the webcam. |
| `release.py` | Makes a release: the zip people download, its notes from `CHANGELOG.md`, and with `--publish` the tag and the release on GitHub. |
| `build_catalogue.py` | Regenerates `data/targets.csv` from OpenNGC. |
| `ty` | One front door for programs and AI agents: `capabilities`, `status`, `context`, `night`, `targets`, `target NAME`, `session`, `observing`, `doctor`, `rigs`, `characterise` (what this rig has had measured about itself). `--rig NAME` first runs any of them for one of several telescopes. Add `--json` for a fixed machine-readable shape. |
| `mcp_server.py` | Read-only MCP server offering the same information to MCP-aware assistants. |

`tonight.py`, `serve.py` and `mount.py` accept `--demo`.

The status page shows two pictures while imaging: **Now**, the newest single
exposure straight from the camera, and **Live stack**, everything added up so
far.

The cooled camera, discovery and research scripts:

| Script | What it does |
|---|---|
| `keeper.py` | Keeps the cooled camera open and cold for the whole night: `start` cools it slowly (1 °C a minute) to its target, every command borrows it from there, and one slow warm-up comes at the night's end. |
| `sxwheel.py` | The Starlight Xpress USB filter wheel: which filter is in the light path, and moves to another with the position confirmed. |
| `colour.py` | One colour picture from a mono camera's L, R, G and B stacks, cropped to the area every filter covers; it refuses one whose filters share under 75% of the frame. |
| `instrument.py` | What the camera in use is ready for and what it still needs (darks, flats, focus offsets, references) before its science counts. |
| `cameras.py` | The camera profiles and light paths (trains). |
| `corners.py` | Star shapes in the corners against the middle: the corrector's spacing, a tilt or the collimation. |
| `guidecam.py` | The guide camera: finds it, takes frames, tests its ST4 lead to the mount (`pulse`), and guides: `star`, `calibrate`, `guide` (not yet proven on the sky; `docs/autoguiding.md`). |
| `patrol.py` | A discovery patrol of one field, from pointing the telescope to the morning's answer: is there anything new? |
| `vet.py`, `candidates.py`, `realbogus.py` | Each candidate checked against catalogues, asteroids and the rig's own history; followed from night to night; scored real or bogus from this rig's own nights. |
| `depth.py` | How faint a stack really reaches, from fake stars planted in it. |
| `report.py` | Everything a report of a new transient needs, gathered for a person to check and send; never sent by the software. |
| `brokers.py` | Public transient alerts bright enough for this rig and up in the dark tonight. |
| `sungrazer.py` | Comets near the Sun in SOHO's and GOES-19's coronagraph pictures, hunted every six hours. |
| `transits.py`, `precision.py` | Tonight's whole exoplanet transits; a night's verdict before any fitted number; what limits the photometry. |
| `variables.py`, `starwatch.py` | Light curves of every star bright enough in the frames already taken; a nightly look at Tabby's star. |
| `archive.py` | Tabby-like dips in Kepler's and TESS's public light curves ([docs/archive.md](archive.md)). |
| `investigate.py` | Looks into a lead from those searches by one fixed procedure and says what it is: explained, an artefact, or unexplained ([docs/research](research/README.md)). |
| `seti.py` | Narrowband radio signals in Breakthrough Listen's open data, with the ON-OFF cadence test ([docs/seti.md](seti.md)). |
| `alert.py`, `notify.py` | The house's lights and speaker, and the phone by Telegram ([docs/alerts.md](alerts.md)). |

### Guiding, in order

Not yet proven on the sky ([Autoguiding](autoguiding.md)). The mount must be tracking. **Moves the mount** marks the ones that send ST4 pulses; each has `--dry-run`, and each checks the motion lock before every pulse.

| Step | Command | Moves the mount |
|---|---|---|
| 1. The camera's frames arrive | `./guidecam.py probe --exposures 2` | no |
| 2. A star found and followed | `./guidecam.py star --count 30` | no |
| 3. The ST4 lead | `./guidecam.py pulse` | **yes**, 5 s each way |
| 4. Calibration | `./guidecam.py calibrate` | **yes**, about 3 minutes of steps |
| 5. Guiding | `./guidecam.py guide --minutes 10` | **yes**, until stopped or a fault |
| 6. A guided imaging run | `./shoot.py TARGET --guide` | **yes**: GoTos as any run, and the guider's pulses |
| 7. The sub-length ladder | `./shoot.py TARGET --guide --ladder`, then `./ladder.py` | **yes**, as a guided run; then `--guide --exposure ladder` uses its answer |

`guide` reuses the kept calibration after a short check move each way, or calibrates first. While it runs, `./guidecam.py status` says how it is, and `./guidecam.py tell pause|resume|relock|stop` orders it, waiting until it is done; nothing else may use the guide camera meanwhile.

## How it works

It is built from plain, focused Python files rather than a framework, each
named for what it does (`mount.py`, `focus.py`, `solve.py`, `shoot.py`,
`patrol.py`). Most things have one obvious file, so a person can follow a
command from the screen to the hardware, and it means to stay that way.

```
plan the night → GoTo → photograph → plate-solve (ASTAP) → correct → photograph … → stack
```

- **`sky.py`** does the astronomy locally with astropy: positions, darkness,
  moonlight (Krisciunas & Schaefer's model), and a score for each target.
- **`feeds.py`** fetches weather, seeing, light pollution and comets, and
  caches them so the report still works when the Wi-Fi drops.
- **`mount.py`** speaks the SynScan handset's serial protocol. It measures how
  wrong the handset's clock is and corrects every GoTo for it, steers by the
  raw axis angles where the handset's own GoTo is unreliable, and stores the
  pointing error found by plate solving.
- **`indi.py`** is a small INDI client written for this project: about 150
  lines that read and set properties and receive image BLOBs over the XML
  protocol, with no dependencies. The stock INDI command-line tools cannot
  address a device whose name contains a dot, which this camera's does.
- **`camera.py`** wraps that into "give me a frame", and recovers when the
  driver stalls.
- **`stacking.py`** is the imaging pipeline's working parts, used live by
  `shoot.py` and again afterwards by `restack.py`.
- **`tracking.py`** predicts the drift a misaligned polar axis causes and
  decides how to trim the Dec motor against it.
- **`moved.py`** judges whether the telescope really turned, from two
  pictures or two plate solves, for anything that makes many moves unattended.
- **`page.py`** lays the report out as the status page. It is plain HTML
  with a little JavaScript reading `status.json`: no framework, no controls.
- **`simulator.py`** is a pretend handset and mount behind `--demo`.

## A night's routine, by hand

The plainest night, step by step. An agent at the telescope follows
[the setup routine](agents/setup-routine.md) instead, which sets the
handset's clock, points at a rich, clear field before focusing, and
polar-aligns. With a cooled camera, `./keeper.py start` comes first, at the handset step,
so the sensor cools slowly while the rest is set up.

1. Set the mount in the home position, power on, and take the handset to its
   main menu.
2. `./mount.py nudge` while you stand beside it: the tube tips 5° and comes
   back (optional: the setting "Motor check at setup", `[mount] nudge_check`). Then `./mount.py zenith` to measure the handset's clock.
3. Focus: `./focus.py --scene` on something distant in daylight, then
   `./focus.py` on stars. Turn the focuser and listen for the tone to rise: go on
   until "Minimum passed", come back, and stop at "Focus good. Hold".
4. `./mount.py sync` on any patch of stars, so later GoTos allow for the home
   position having been set by eye.
5. `./mount.py goto M27 --solve`, then `./shoot.py M27 --frames 48 --recentre 8`.

Commands that move the mount need serial access; until you have logged out
and back in after joining the `dialout` group, prefix them with
`sudo -u $USER -g dialout`.
