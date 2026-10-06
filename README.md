# telescopeyoke 🔭

**Turn an ordinary SynScan telescope into a locally controlled smart telescope.**

*Give your old SynScan telescope a brain.*

[![tests](https://github.com/Ryan-Clinton/telescopeyoke/actions/workflows/tests.yml/badge.svg)](https://github.com/Ryan-Clinton/telescopeyoke/actions/workflows/tests.yml)

![A minute and a half of the demo: tonight's report, a target picked, a GoTo shown as a plan and then centred by plate solving, focusing, and an imaging run with cloud coming over](docs/tour.gif)

*The demo, recorded by `./tour.py`: a pretend mount, camera and sky, with
the real centring, focusing and stacking code running on them.*

**[Home page](https://ryan-clinton.github.io/telescopeyoke/) ·
[Download 0.2.1](https://github.com/Ryan-Clinton/telescopeyoke/releases/download/v0.2.1/TelescopeYoke-v0.2.1.zip) ·
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
- 🎯 **Ranks targets for your actual sky**: altitude, moonlight, light pollution, and your own skyline, measured from a phone panorama or by the telescope
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
wget https://github.com/Ryan-Clinton/telescopeyoke/releases/download/v0.2.1/TelescopeYoke-v0.2.1.zip
unzip TelescopeYoke-v0.2.1.zip
cd TelescopeYoke-v0.2.1
./install.sh --demo           # the Python libraries, then TelescopeYoke (demo) opens
```

On Windows 10 or 11: install 64-bit Python 3.11 or newer from python.org
(tick "Add python.exe to PATH"),
[download TelescopeYoke-v0.2.1.zip](https://github.com/Ryan-Clinton/telescopeyoke/releases/download/v0.2.1/TelescopeYoke-v0.2.1.zip),
unpack it, and double-click **`try-demo.cmd`**.

That zip is release 0.2.1, which stays as it is; a hardware report says
which release made it. `git clone https://github.com/Ryan-Clinton/telescopeyoke`
gets the newest code instead, which changes from day to day.

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
| Sky-Watcher EQ3 Pro | SynScan, firmware 3.35, FTDI serial lead | Altair Hypercam 183C (on USB 2 for every night so far; USB 3 timed indoors) | Ubuntu 26.04, Python 3.14 | ✅ Planner, mount moves, camera, focusing, plate solving, GoTo with centring, under real stars | the author |
| the same EQ3 Pro | the same | the same Hypercam 183C | Windows 11 | ⚠️ The demo, and camera frames indoors. No mount driven, no star seen | the author |
| EQ5 | SynScan | any | Linux or Windows | ❔ wanted | could be you |
| HEQ5 | SynScan | any | Linux or Windows | ❔ wanted | could be you |
| EQ6, EQ6-R | SynScan | any | Linux or Windows | ❔ wanted | could be you |
| any of them | SynScan | another INDI camera | Linux | ❔ wanted | could be you |
| a mount converted with an EQStar or other EQMOD-style controller | none | any | Linux or Windows | ❔ wanted: whether it answers at all | could be you |

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

**A controller that is not a SynScan handset** (an EQDIR lead, an
Astro-Gadget EQStar, anything normally driven through EQMOD): nobody knows
yet whether telescopeyoke can talk to yours, and it does not guess. Name the
port and it will ask:

```bash
./doctor.py --report --probe COM7        # Linux: --probe /dev/ttyUSB0
```

It asks that one port what it is, first as a SynScan handset and then as a
Sky-Watcher motor board (the language EQMOD speaks), at 9600 and at 115200
baud, and writes what answered into the report along with the adapter's
make and USB numbers. Every question only reads; nothing is told to move.
Close EQMOD first, since only one program can have the port.

### Already using EQMOD or ASCOM?

Keep them. telescopeyoke does not use ASCOM and changes nothing about an
ASCOM or EQMOD installation: it talks to the mount's COM port itself. The
one rule is that two programs cannot hold the same port at once, so close
EQMOD (or NINA, or the SynScan app) before starting telescopeyoke on that
mount, and the other way round. On Windows the doctor says so when it sees
ASCOM or EQMOD installed. What it adds to a setup that already works is the
part in between: targets ranked for your own horizon, a GoTo that
plate-solves and centres itself, focusing by ear, and short exposures
checked and stacked as they arrive.

### More than one telescope

A **rig** is one telescope with its own settings and its own files. With two
out on a good night, each runs in a window of its own:

```bash
./app.py --new-rig heq5       # its settings (rigs/heq5.toml) and "TelescopeYoke (heq5)" in the menu
./app.py --rig heq5           # open it; set it up on its Settings screen
./ty --rig heq5 mount status  # any command, for that rig
./ty rigs                     # every rig in one view: what each is and what it is imaging
```

Each rig keeps its own frames, pictures, calibration frames and remembered
measurements under `rigs/heq5/`, so two nights' work never mix. The
application's Rigs screen shows what every rig is doing. With no rig named
everything is as before: `config.toml` and the folders beside it. The motion
lock (`MOTION_LOCKED`) stops every rig at once.

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
| ASCOM, Alpaca | ❌ Not used. An ASCOM or EQMOD installation is noticed and left alone; see below. |

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
| `polaralign.py` | Measures how far the polar axis is from the pole by plate solving at three positions, and says which way to turn each adjuster. |
| `polaris.py` | Polar alignment before dark, from Polaris alone, which shows in daylight when nothing else near the pole does. `check` says whether it is worth trying (sky, Sun, focus); `find` looks around the home position until the star is in the picture, proves it by tipping the tube, and can keep every look (`--record`); `align` turns the RA axis with it in view, says roughly which way to move each adjuster, and with `--watch` keeps saying how far is left while the bolts are turned. |
| `landmark.py` | Sets the azimuth by day: remembers a distant fixed thing with the telescope's axis readings, and next time turns back to it and shows how far it has moved. |
| `panorama.py` | The skyline from a phone panorama, with no motors: finds the line between sky and everything else in the picture, lets you put it right where it is wrong, ties the picture to the compass from two marks (something the telescope is pointing at, a remembered landmark, or typed bearings), and keeps the result for the planner. Panoramas from other heights add doubt where things close by sit differently. |
| `horizon.py` | The telescope measuring its own skyline, or checking a panorama's. `--trace` starts 30° apart, adds bearings only where the skyline bends, starts each from the skyline already measured, and checks its own answer; `--daylight` works by day, judging each small square of the frame by brightness, smoothness and colour; a frame that shows the top itself gives the height at once. `--show` prints the skyline in use, `--forget` throws it away. Without `--trace` it looks on a fixed grid, as it first did. |
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
| `doctor.py` | Checks what is installed and connected, and says what is ready: planner, mount, imaging. `--report` writes the same out to post as a hardware report, with the mount's model and the handset's firmware as the handset gives them, and your location left out; `--probe PORT` adds what answers on a serial port you name. |
| `tour.py` | Records the demo being used, pressing the same buttons a person would: the animation at the top of this page, and a still of each screen. Ubuntu only. |
| `replay.py` | Turns a centring run recorded with `mount.py goto --solve --record` into a GIF. |
| `watch.py` | Photographs the telescope itself with the webcam. |
| `release.py` | Makes a release: the zip people download, its notes from `CHANGELOG.md`, and with `--publish` the tag and the release on GitHub. |
| `build_catalogue.py` | Regenerates `data/targets.csv` from OpenNGC. |
| `ty` | One front door for programs and AI agents: `capabilities`, `status`, `context`, `night`, `targets`, `target NAME`, `session`, `observing`, `doctor`, `rigs`. `--rig NAME` first runs any of them for one of several telescopes. Add `--json` for a fixed machine-readable shape. |
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

Written for a second person's equipment and not yet tried on it: rigs have
been run only as tests, never with two real telescopes at once. `--probe`
has never met a real controller: the handset's part and the motor board's
part are each tested against stand-ins, and whether an EQStar answers either
is exactly what it is there to find out. The notice about ASCOM and EQMOD
reads the Windows registry where ASCOM is documented to keep its list, and
has not been run on a computer that has them. The report also now asks the
handset whether it gives a position (it keeps only yes or no, because the
answer would say roughly where the mount is); that too is from the published
protocol and tested on the simulated handset.

Not yet proven on the real sky: `polaris.py`. Its geometry is tested in
three dimensions on the simulated mount with a made-up daytime sky. On the
real mount (6 October 2026) the first version of the search turned as
intended for 23 minutes, out to 1.6° from home, and found nothing: there was
some cloud, the focus had been disturbed and not checked, and no frames were
kept, so there is no telling which it was. That is why the search now asks
for a focus check and can record every look. Daytime frames from the real
camera expose at about 16 ms with the Sun 14° up, take about a second each,
and show no false stars in blank sky. The reordered search then ran on the
real mount from 18:22 to 19:06 the same evening, across sunset: 266 looks in
35 minutes, about 8 seconds each, the tube stopping within 0.05° of where it
was sent, out to 3.3° from home, every look kept. It did not find Polaris,
and nothing stood out further than 8.8 until faint stars began to show at
dusk and it stopped itself. The likeliest reason is that the mount's axis
was more than 3° from the pole (it had been set by a phone compass); that
was not confirmed. Still untried on real hardware: the tipping of the tube
to prove a candidate, the bringing to the middle, `align`, and the watching
while the bolts are turned. Guesses still to be set from real
runs: the level of blue that counts as clear sky (from three frames), the
steps from "poor" to "very good" by the Sun's height, and how far a point
must stand out to count.

Written but never run on the real mount or camera: `landmark.py`. Finding
how far a view has moved is tested on made-up rooftops, and the turning back
on the simulated mount. Daytime frames have never been taken with the real
camera, so its choice of exposure is untried.

Written but never run on the real mount or camera: `horizon.py --trace` and
`horizon.py --daylight`. The following, the adding of bearings and the checks
are tested against the simulated mount and made-up skylines. The scores that
tell daytime sky from a wall, the wait for the tube to steady by day and the
reading of a top from where the stars stop are first guesses and have not
seen a real frame; every look keeps its picture in `horizon/looks/` so that
the first real run can be checked. A frame is about two thirds of a degree
tall, so "the top is in this frame" only saves looks when the start is
already close: from a panorama or an earlier survey, not from nothing. The
camera is read at full size: a smaller or binned mode is not used because
nobody has yet recorded which of this camera's modes keeps its colour
pattern (`./camera_test.py --throughput` shows it).

`panorama.py` has found the skyline in three real phone panoramas of one
garden, two of them well and one (taken low, mostly walls and ground) badly;
a pale rendered wall is what it most often takes for sky, which is why the
line can be redrawn. No panorama has yet been tied to the compass with real
marks and compared with what the telescope sees, so how true the bearings
and heights come out is not known. The Horizon screen's drawing and marking
have been run through the console's own interface in the demo but not yet
used with a mouse.

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

- Camera frames are slow with this driver on a USB 2 lead: about 4 s plus
  five times the exposure, so light is collected only about a seventh of the
  time. On a USB 3 lead, timed indoors on 6 October 2026, a 1 s frame takes
  1.5 s instead of 9.3 s. No night has been run on USB 3 yet.
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
- A night on the USB 3 lead. Indoors it brings the shutter from open about
  a seventh of the time to about two thirds; under the stars it is untried.
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
What each release added is in [CHANGELOG.md](CHANGELOG.md); `./release.py`
makes one. For code, see
[CONTRIBUTING.md](CONTRIBUTING.md):
run `pytest`, and anything that changes how the mount moves comes with a test
against `simulator.py`.

## Data sources

Weather: [Open-Meteo](https://open-meteo.com). Seeing: [7Timer](https://www.7timer.info).
Light pollution: [D. Lorenz's atlas](https://djlorenz.github.io/astronomy/lp/).
Comets: [COBS](https://cobs.si) and [JPL Horizons](https://ssd.jpl.nasa.gov/horizons/).
Cloud imagery: [EUMETSAT](https://view.eumetsat.int).

## Licence

MIT; see [`LICENSE`](LICENSE). The one exception is `data/targets.csv`,
which is derived from [OpenNGC](https://github.com/mattiaverga/OpenNGC) and
is licensed CC-BY-SA-4.0; see [`data/LICENSE`](data/LICENSE).
