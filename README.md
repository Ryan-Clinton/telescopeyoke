# telescopeyoke 🔭

**Turn an ordinary SynScan telescope into a locally controlled smart telescope.**

*Give your old SynScan telescope a brain.*

[![tests](https://github.com/Ryan-Clinton/telescopeyoke/actions/workflows/tests.yml/badge.svg)](https://github.com/Ryan-Clinton/telescopeyoke/actions/workflows/tests.yml)

![A minute and a half of the demo: tonight's report, a target picked, a GoTo shown as a plan and then centred by plate solving, focusing, and an imaging run with cloud coming over](docs/tour.gif)

*The demo, recorded by `./tour.py`: a pretend mount, camera and sky, with
the real centring, focusing and stacking code running on them.*

**[Download the zip](https://github.com/Ryan-Clinton/telescopeyoke/archive/refs/heads/main.zip) ·
[Try the demo, no telescope needed](#quick-start) ·
[What it has been tried on](#hardware) ·
[Ask a question](https://github.com/Ryan-Clinton/telescopeyoke/discussions)**

telescopeyoke is a lightweight telescope automation system for Linux. It
also runs natively on Windows, where the tests and the demo pass and the
camera has taken frames, but no mount has been driven yet. It runs
on a laptop left beside a modest SynScan telescope and camera, and you watch
from indoors. It plans the night, checks the weather and moonlight, ranks
targets for your own sky, slews the mount, plate-solves where the telescope is
really pointing, re-centres the target, helps you focus, and stacks short
exposures into a picture.

It is built for the inexpensive gear many amateur astronomers already own,
and for the things that gear gets wrong: a handset with the wrong time, a home
position set by eye, a rough polar alignment.

> **Looking for testers.** So far it has run on one telescope: the author's
> EQ3 Pro. If you have an EQ3, EQ5, HEQ5 or EQ6 with a SynScan handset, on
> Linux or Windows, a report from you is worth more than any new feature.
> You do not have to let it move your mount: `./doctor.py --report` only
> looks at what is connected, and what it writes is useful by itself. See
> [Hardware](#hardware).

## What it does

- 🌙 **Plans tonight's observing**: darkness, Moon, and a GO / MARGINAL / NO-GO verdict
- ☁️ **Checks cloud, rain, wind, dew and seeing**, plus a live satellite cloud picture
- 🎯 **Ranks targets for your actual sky**: altitude, moonlight, light pollution, blocked horizons
- 🔭 **Controls SynScan mounts** through the handset, with the handset's clock errors corrected
- 🧭 **Plate-solves and centres GoTos automatically** (`goto M27 --solve`)
- 🔊 **Talks you through focusing**, eyes on the focuser not the screen: "Improving. 4.8" … "Minimum passed. Reverse slightly" … "Best focus. Hold"
- 📐 **Makes the best of a rough polar alignment**: measures how far out the mount is, predicts the drift that causes anywhere in the sky, and creeps a motor against it
- 📷 **Captures and stacks images**: every raw frame kept, poor frames rejected, stars lined up to a fraction of a pixel, satellite trails clipped out
- 🏠 **Shows it all on a status page** you can watch from indoors: the verdict, the run's progress and star quality frame by frame, the live stack, what to point at now, and the state of the kit
- 🛑 **Keeps the mount inside physical limits**, with a motion lock and a webcam watching every slew

## See it working

**Planned.** This is what `./serve.py` shows, to watch from indoors:
tonight's verdict and the targets worth pointing at, ranked for your sky.

![The status page: tonight's verdict, a live imaging run with its quality readings, the stacked picture, the best targets, the night's timeline and the state of the kit](docs/dashboard.jpg)

**Found.** A real run from the first night. The mount's home position had
been set by eye and was about ten degrees out; the telescope photographed the
sky, worked out where it really was, and corrected itself:

```
$ ./mount.py goto M27 --solve
M27 Dumbbell Nebula: altitude 57°, hour angle +0.36 h (west: the tube will swing over the pole)
  off by -107.0' in hour angle, +94.4' in Dec
  off by -6.2' in hour angle, -11.4' in Dec
  off by +1.0' in hour angle, -1.8' in Dec
  centred
```

**Captured.** The Dumbbell Nebula (M27) from that night: 48 two-second
exposures through a 150 mm Newtonian on an EQ3 mount that was polar aligned
by eye.

![The Dumbbell Nebula, stacked by shoot.py](docs/m27-result.jpg)

## Quick start

**Try the demo: no telescope, nothing to set up, nothing that can move.**

On Ubuntu or Debian:

```bash
git clone https://github.com/Ryan-Clinton/telescopeyoke
cd telescopeyoke
./install.sh --demo           # the Python libraries, then TelescopeYoke (demo) opens
```

On Windows 10 or 11: install 64-bit Python 3.11 or newer from python.org
(tick "Add python.exe to PATH"),
[download the zip](https://github.com/Ryan-Clinton/telescopeyoke/archive/refs/heads/main.zip),
unpack it, and double-click **`try-demo.cmd`**. No git needed; the same zip
works on Ubuntu if you would sooner not clone.

Either way a window opens on a pretend mount, camera and sky. It is in the
applications menu (or Start Menu) from then on as **TelescopeYoke (demo)**.

The same from a terminal, a piece at a time:

```bash
./doctor.py                   # what is installed and connected
./tonight.py --demo           # tonight's report with made-up weather
./serve.py --demo             # the web page, on http://localhost:8080
./mount.py --demo goto M27    # drive a simulated mount
```

On Windows these are written `python doctor.py`, `python tonight.py --demo`
and so on, and `.\ty.cmd` (or `python ty`) for `./ty`. See
[Setup](docs/setup.md#windows).

**The application.** `./install.sh` puts **TelescopeYoke** and **TelescopeYoke
(demo)** in the applications menu (on Windows, `install.ps1` puts them in the
Start Menu). It opens in a window of its own, with no terminal and no
browser: Tonight, Targets, Imaging, Focus and Mount for observing; Camera,
Telescope, Plate solver and Webcam for setting the equipment up; the tools;
and the doctor, settings and logs. The first time, it opens on what is ready
and what still needs doing. With a real mount, every move is checked with a
dry run and shown as a plan, and nothing moves until you confirm it. From a
terminal it is `./app.py`, or `./app.py --demo`. It has not yet been used
with a real mount or camera.

**The demo is the whole thing on a pretend telescope.** TelescopeYoke (demo)
has a pretend mount, camera and sky: a GoTo is centred by plate solving,
the focusing aid follows a focuser you turn with a button, and an imaging
run stacks frames and rejects the ones taken after you bring the cloud
over. It runs the same commands as a real night and keeps its files in a
folder of its own (`demo/`), apart from anything real.

**Use the planner for real** (still no telescope needed): put your location
in `config.toml`, then `./tonight.py`.

**Run a telescope:** `./install.sh`, then follow [Setup](docs/setup.md).

## Three parts, usable separately

| Part | Commands | Needs |
|---|---|---|
| **Planner** | `tonight.py`, `serve.py`, `clouds.py` | Any computer with Python. No telescope. |
| **Control** | `mount.py`, `polaralign.py`, `watch.py` | A SynScan mount and its serial lead. |
| **Imaging** | `snap.py`, `focus.py`, `solve.py`, `shoot.py`, `skywatch.py` | A supported camera and ASTAP. On Linux the camera is read through INDI; on Windows through Altair's own library, which is the only camera route there. |

Start with the planner; add hardware when you have it.

## Hardware

**Tried so far.** One row for each set of equipment someone has run it on.
There is one, and it is the author's:

| Mount | Handset | Camera | System | What has worked | Tried by |
|---|---|---|---|---|---|
| Sky-Watcher EQ3 Pro | SynScan, firmware 3.35, FTDI serial lead | Altair Hypercam 183C on USB 2 | Ubuntu 26.04, Python 3.14 | ✅ Planner, mount moves, camera, focusing, plate solving, GoTo with centring, under real stars | the author |
| the same EQ3 Pro | the same | the same Hypercam 183C | Windows 11 | ⚠️ The demo, and camera frames indoors. No mount driven, no star seen | the author |
| EQ5 | SynScan | any | Linux or Windows | ❔ wanted | could be you |
| HEQ5 | SynScan | any | Linux or Windows | ❔ wanted | could be you |
| EQ6, EQ6-R | SynScan | any | Linux or Windows | ❔ wanted | could be you |
| any of them | SynScan | another INDI camera | Linux | ❔ wanted | could be you |

**To add a row**, working or not:

1. Run `./doctor.py --report` (on Windows `python doctor.py --report`), or
   press "Write a hardware report" on the application's Doctor screen. It
   writes out what the computer is, what the handset says the mount is and
   its firmware version, and every check. It only looks: nothing is moved,
   and your location is left out.
2. Paste it into a
   [Hardware compatibility report](https://github.com/Ryan-Clinton/telescopeyoke/issues/new?template=hardware-report.md)
   and tick what you tried. Your GitHub name goes beside your row if you
   want it there.

You can stop there. If you want to go further without the mount turning,
`./mount.py status` reads its position and `./mount.py goto M27 --dry-run`
checks a move against the limits and says what it would do, without making
it. For a question first ("will it work with my HEQ5?"), ask in
[Discussions](https://github.com/Ryan-Clinton/telescopeyoke/discussions).

**What to expect of other equipment:**

| Hardware | Status |
|---|---|
| Sky-Watcher Explorer 150P (150 mm f/5 Newtonian) | ✅ Tested by the author |
| Python 3.11, 3.12, 3.13, 3.14 | ✅ Tests pass in CI on Ubuntu and Windows (no hardware) |
| Windows 10 and 11 | ⚠️ Tests and the demo pass with no hardware. The camera has taken frames on Windows 11, indoors. No mount has been driven from Windows, and camera and mount have not been used together there. |
| SynScan Wi-Fi adapter, or an EQDIR lead (no handset) | ⚠️ The adapter has been found and read on a real EQ3 (firmware, gearing, position). No mount has been moved through it yet; the EQDIR lead is untried. |
| EQ5, HEQ5, EQ6 with a SynScan handset | ⚠️ Untested. Likely: same serial protocol. |
| Other INDI cameras | ⚠️ Untested. Likely for mono or RGGB colour sensors: set the driver and sensor size in `config.toml`. |
| Other telescopes | Set the focal length in `config.toml`. |
| ASCOM, Alpaca | ❌ Not supported. |

## Commands

| Script | What it does |
|---|---|
| `tonight.py` | Report for the night: darkness, Moon, weather verdict, ranked targets. `--html` writes the web page. |
| `serve.py` | Serves the status page on port 8080: the night's report rebuilt every 10 minutes, and the imaging run, pictures and system panel refreshed every two seconds. |
| `clouds.py` | Fetches the latest infrared satellite image with the site marked on it. |
| `mount.py` | Moves the mount: `status`, `home`, `zenith`, `goto NAME [--solve]`, `point AZ ALT`, `sync`, `drift`, `compensate`, `stop`. |
| `liveview.py` | Takes a frame every few seconds so the status page shows what the telescope sees now. Steps aside while `shoot.py` runs. |
| `app.py` | TelescopeYoke, the application: one window with everything in it, started from the applications menu. `./app.py --demo` tries it with nothing plugged in. |
| `console.py` | The same observing screens as a page in a browser, without the equipment set-up and tools: the companion to the application. This computer only. |
| `horizon.py` | Sweeps the sky and reports which directions are blocked by houses, hedges and trees, as lines for `config.toml`. `--trace` follows the top of whatever is in the way right round and checks its own answer; `--daylight` works by day, going by brightness instead of stars. |
| `snap.py` | Takes one camera frame, saves the FITS in `frames/`, publishes a preview. |
| `shoot.py` | Takes a picture: many short exposures, each checked, lined up and stacked live, with the raw frames kept. `--exposure auto` picks the longest exposure the tracking allows. `--frames 0` carries on until cloud stops it. While it runs, `./ty run stop` ends it cleanly with its final picture; `recentre`, `assist-on` and `assist-off` are also understood. |
| `restack.py` | The quality pass: goes back over a session's raw frames, keeps the best, weights and clips them, and writes the finished picture. `shoot.py` runs it at the end. `--all`, or several session folders, stacks sessions from one night or many into one picture. |
| `calibrate.py` | Makes master dark, bias and flat frames, which `shoot.py` and `restack.py` then apply automatically. |
| `camera_setup.py` | Gets the camera ready: checks it is plugged in and has a driver, takes Altair's library files out of their SDK zip if they are missing, and takes a test frame. `--check` only looks. Also the "Set up the camera" button in the console. |
| `camera_test.py` | `--capabilities` lists what the camera offers; `--throughput` times every way of getting frames off it; `--gain-sweep` tries a range of gains on tonight's sky and suggests one. |
| `compare.py` | Shows the same patch of sky from several stacks side by side at full size, with star measurements for each. |
| `process.py` | Turns a finished stack into a cleaner picture: level sky, white stars, smoothed colour noise. |
| `focus.py` | Hands-free focusing aid: measures many stars at once and speaks the result. `--tones` for a rising pitch instead of speech, `--scene` for a daytime view. |
| `solve.py` | Plate-solves a frame: where is the telescope really pointing? |
| `polaralign.py` | Measures how far the polar axis is from the pole, from three plate solves. |
| `skywatch.py` | Photographs the sky every minute and stops when stars appear. |
| `doctor.py` | Checks what is installed and connected, and says what is ready: planner, mount, imaging. `--report` writes the same out to post as a hardware report, with the mount's model and the handset's firmware as the handset gives them, and your location left out. |
| `tour.py` | Records the demo being used, pressing the same buttons a person would: the animation at the top of this page, and a still of each screen. Ubuntu only. |
| `replay.py` | Turns a centring run recorded with `mount.py goto --solve --record` into a GIF. |
| `watch.py` | Photographs the telescope itself with the webcam. |
| `build_catalogue.py` | Regenerates `data/targets.csv` from OpenNGC. |
| `ty` | One front door for programs and AI agents: `capabilities`, `status`, `context`, `night`, `targets`, `target NAME`, `session`, `observing`, `doctor`. Add `--json` for a fixed machine-readable shape. |
| `mcp_server.py` | Read-only MCP server offering the same information to MCP-aware assistants. |

`tonight.py`, `serve.py` and `mount.py` accept `--demo`.

The status page shows two pictures while imaging: **Now**, the newest single
exposure straight from the camera, and **Live stack**, everything added up so
far.

## How it works

It is deliberately small: a dozen short scripts with plain names
(`mount.py`, `focus.py`, `solve.py`, `shoot.py`, `tonight.py`). One person
can read it and understand how the whole telescope works, and it means to
stay that way.

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
- **`page.py`** lays the report out as the status page. It is plain HTML
  with a little JavaScript reading `status.json`: no framework, no controls.
- **`simulator.py`** is a pretend handset and mount behind `--demo` and the
  tests.

## Going deeper

| Page | What is in it |
|---|---|
| [How a picture is made](docs/imaging.md) | Calibration, frame checks, lining up, stacking, the quality pass. |
| [Focusing by ear](docs/focus.md) | Turn the knob and the laptop talks you onto focus. |
| [The mount is wonky; measure how wonky](docs/tracking.md) | Drift from a rough polar alignment, and how it is cancelled. |
| [Setup](docs/setup.md) | Installing, the camera driver, the plate solver, what the computer needs. |
| [For programs and AI agents](docs/agents/README.md) | `--json`, `--dry-run`, the `ty` command, the web API and the MCP server. |
| [Checking it under real sky](docs/validation.md) | The five experiments that will show whether the clever parts work. |

**Focus without looking at the laptop.** `./focus.py` measures up to 40 stars
at once and speaks: "Improving", "Best focus. Hold", "Minimum passed. Reverse
slightly". It ignores the shimmer of the air, so it does not send you chasing it.

**For programs and AI agents**, every command answers in one JSON shape with
`--json`, anything that moves the mount can be checked first with `--dry-run`,
and a read-only web API and MCP server offer the same information. Start with
[AGENTS.md](AGENTS.md).

## A night's routine

1. Set the mount in the home position, power on, and take the handset to its
   main menu.
2. `./mount.py zenith` to measure the handset's clock and check the mount
   moves correctly.
3. Focus: `./focus.py --scene` on something distant in daylight, then
   `./focus.py` on stars. Turn the focuser slowly and listen: stop at "Best focus. Hold".
4. `./mount.py sync` on any patch of stars, so later GoTos allow for the home
   position having been set by eye.
5. `./mount.py goto M27 --solve`, then `./shoot.py M27 --frames 48 --recentre 8`.

Commands that move the mount need serial access; until you have logged out
and back in after joining the `dialout` group, prefix them with
`sudo -u $USER -g dialout`.

## Safety

The laptop cannot see what the telescope is about to hit.

- **Start the handset properly.** After every power-on, press ENTER through
  the handset's start-up screens to its main menu, entering today's date. A
  handset still on its version screen accepts commands but moves the mount by
  the wrong amounts. `mount.py` refuses to run if the handset's date is still
  its default.
- **Power on in the home position**: counterweight bar at the lowest point of
  its swing, tube on top, pointing at the pole.
- **Keep the tripod legs clear** and leave slack in the cables. Targets west
  of the meridian swing the tube over the pole.
- **Never point near the Sun.** `mount.py point` refuses within 40° of it
  while it is up; `goto` only knows night-sky objects.
- Creating a file called `MOTION_LOCKED` in this folder blocks all movement.
- `mount.py` will not go below 20° altitude or more than 5.75 hours from the
  meridian.
- **The status page (`serve.py`) is read-only on purpose.** It is served to
  the whole home network with no login, which is fine for pictures and
  reports. Nothing that moves the mount will be added to it.
- **The control console (`console.py`) answers this computer only.** It
  needs a key made each time it starts, shows every move as a plan first,
  and moves the mount only when that plan is confirmed.

## Current status

Working on real hardware and real stars: the night report and web page,
mount moves through the handset, camera frames, focusing, plate solving,
`goto --solve` (centres a target to a fraction of an arcminute) and `sync`.
The pictures on this page came from an earlier, simpler version of
`shoot.py`.

Rewritten since those pictures, tested on simulated star fields, and being
proven on real sky: the stacking pipeline (frame scoring and rejection,
sub-pixel and rotation alignment, clipped and weighted stacking, saved raw
frames, the quality pass).

Windows: the tests and every `--demo` command pass with nothing plugged in,
and the camera has taken frames there: a Hypercam 183C on Windows 11, read
through Altair's own library (`altair.py`) instead of INDI, set up from
nothing by `camera_setup.py`. That was indoors with no telescope, so no star
has been through that route, and its picture has not been compared with the
INDI route's for which way up it is. The mount has not been driven from
Windows: the handset's lead has been found by name among the COM ports and
nothing more. The plate solver's Windows paths, the DirectShow webcam and the
spoken focusing aid are untried on real equipment. Camera and mount have not
been used together on Windows.

Written but not yet run for real: `calibrate.py` (no dark or flat frames have
been taken yet) and `camera_test.py --gain-sweep`.

Rewritten since they were last used on real hardware, and so far proven only
against the simulator and made-up data: `focus.py` (multi-star HFR and the
new spoken guidance), `mount.py drift` (line-fitted, with the drift model),
`mount.py compensate` and `shoot.py --assist`. An earlier, cruder
`mount.py drift` did cancel most of the drift on the real mount.

Written but never run on the real mount: `polaralign.py`, also offered in
the application under Tools. Its geometry is checked by the tests, and in the
demo it finds the pretend mount's polar error (1.4° east, 0.8° high) through
the real plate-solve path. It checks its three positions against the
altitude and meridian limits, and the motion lock, before anything moves.

Written but never moved a real mount: control without the handset, through
the SynScan Wi-Fi adapter or an EQDIR lead (`direct.py`). The adapter has
been found on the network and asked for its firmware, gearing, position and
status, on a real EQ3. Every movement is tested only against a simulated
motor board, and which way the Dec motor turns has to be checked on each
mount, with someone watching, before a GoTo is allowed.

Written but never used with a real mount or camera: the application
(`app.py`) and its companion page (`console.py`). The server, its refusals,
the plan-then-confirm step and Stop are tested against the simulated mount
and stand-in jobs; the screens have been looked at in demo mode only. The
window itself has been opened on Ubuntu (GTK with WebKit). On Windows the
window (WebView2 through pywebview, or Edge's application mode) and the Start
Menu shortcuts have not been tried on a real machine. How long Stop takes during a real slew, on
Linux and on Windows, has not been measured.

Written but not yet tried where they are meant for: `./doctor.py --report`
asks the handset two things it has not been asked before, its firmware
version and the mount's model. Both are in Sky-Watcher's published protocol
and both only read, but they are tested against the simulated handset alone.
`try-demo.cmd` and `install.ps1 -Demo` have not been run on a real Windows
machine; `./install.sh --demo` and `./tour.py` have been, on Ubuntu.

Written but never run on the real mount or camera: `horizon.py --trace` and
`horizon.py --daylight`. The following and its checks are tested against the
simulated mount; the brightness levels that tell daytime sky from a wall are
first guesses and have not seen a real frame.

Covered by automated tests (`pytest`, run on every push on Python 3.11 to 3.14): the astronomy, the
mount logic against the simulated handset, frame alignment and hot-pixel
removal, star measurement and frame rejection, sub-pixel and rotation
registration, clipped stacking, calibration arithmetic, a whole simulated
imaging run, the focus measurement, the polar alignment geometry, the INDI
message handling, the drift formula against a mount modelled from first
principles, drift cancelling on both sides of the simulated mount, and the
demo report end to end. The tests cannot cover the
real mount, camera or sky.

Known limits:

- Camera frames are slow with this driver on USB 2: about 4 s plus five times
  the exposure, so light is collected only about a seventh of the time.
- After a slew the stars streak for up to half a minute while the gears
  settle; the scripts wait before photographing.
- With a rough polar alignment the aim drifts by an arcsecond or more per
  second, which limits exposures to a couple of seconds.
- The handset's GoTo overshoots right next to the pole, so `home` steers by
  the axis readout instead.
- The target ranking in `tonight.py` uses weights chosen by judgement.

## Roadmap

Near term:

- Someone other than the author running it. Reports from other SynScan
  mounts come before any new feature.
- Recordings from real nights for this page: a GoTo-and-centre run
  (`--record` and `replay.py` are ready for it) and a focusing session. The
  animation at the top is the demo.
- More of the camera's quirks moved into `config.toml` as other cameras are tried.
- Faster frames: a newer camera driver, or USB 3. The camera currently
  collects light for about a seventh of the time, so this is the largest
  single gain available.
- Dark and flat frames taken and in use, and the gain chosen from a sweep
  instead of by guesswork.

Later, for image quality, in this order: colour calibration from catalogue
stars (the plate solve already identifies them); gentle deconvolution, once
calibration and alignment are proven; sky-gradient removal frame by frame;
drizzle on the raw Bayer frames. None of these before a controlled
comparison has shown what the current pipeline gains on real data.

Later, if people ask for them:

- Raspberry Pi or other small computer strapped to the telescope.
- Controls on the web page, behind a login.
- Letting an agent request a move over MCP, carried out only after a person
  approves that exact move (designed in `docs/agents/safety.md`, not built).
- The agent scenarios in `evals/` run with a real model in the loop.
- The MCP server moved onto the official MCP Python SDK, once MCP is a feature people
  rely on. Today's hand-written one speaks the protocol directly to avoid a dependency;
  the telescope logic stays in `agent.py` either way.
- Guiding and focuser support.

Not planned: ASCOM, mobile apps, a React front end, cloud services, AI target
selection, Docker images, plugin systems, a sequencing language. Bigger
projects (NINA, KStars/Ekos) do those well; this one stays small, readable,
and aimed at ordinary SynScan gear.

## Contributing

Reports from other hardware are the most useful contribution: run
`./doctor.py --report` and paste it into a **Hardware compatibility report**
issue, as [Hardware](#hardware) describes. Questions, ideas and pictures you
have taken go in
[Discussions](https://github.com/Ryan-Clinton/telescopeyoke/discussions).
What each release added is in [CHANGELOG.md](CHANGELOG.md). For code, see
[CONTRIBUTING.md](CONTRIBUTING.md):
run `pytest`, and anything that changes how the mount moves comes with a test
against `simulator.py`.

## Data sources

Weather: [Open-Meteo](https://open-meteo.com). Seeing: [7Timer](https://www.7timer.info).
Light pollution: [D. Lorenz's atlas](https://djlorenz.github.io/astronomy/lp/).
Comets: [COBS](https://cobs.si) and [JPL Horizons](https://ssd.jpl.nasa.gov/horizons/).
Cloud imagery: [EUMETSAT](https://view.eumetsat.int).

## Licence

MIT; see `LICENSE`. `data/targets.csv` is derived from
[OpenNGC](https://github.com/mattiaverga/OpenNGC) and is licensed
CC-BY-SA-4.0.
