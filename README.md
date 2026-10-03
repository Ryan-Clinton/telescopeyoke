# telescopeyoke 🔭

**Turn an ordinary SynScan telescope into a locally controlled smart telescope.**

*Give your old SynScan telescope a brain.*

[![tests](https://github.com/Ryan-Clinton/telescopeyoke/actions/workflows/tests.yml/badge.svg)](https://github.com/Ryan-Clinton/telescopeyoke/actions/workflows/tests.yml)

![The status page: tonight's verdict, a live imaging run with its quality readings, the stacked picture, the best targets, the night's timeline and the state of the kit](docs/dashboard.jpg)

telescopeyoke is a lightweight telescope automation system for Linux. It runs
on a laptop left beside a modest SynScan telescope and camera, and you watch
from indoors. It plans the night, checks the weather and moonlight, ranks
targets for your own sky, slews the mount, plate-solves where the telescope is
really pointing, re-centres the target, helps you focus, and stacks short
exposures into a picture.

It is built for the inexpensive gear many amateur astronomers already own,
and for the things that gear gets wrong: a handset with the wrong time, a home
position set by eye, a rough polar alignment.

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

**Planned.** The page at the top is what `./serve.py` shows: tonight's
verdict and the targets worth pointing at, ranked for your sky.

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

**Try it with no telescope and no setup:**

```bash
git clone https://github.com/Ryan-Clinton/telescopeyoke
cd telescopeyoke
./install.sh --planner        # Python libraries only (Ubuntu/Debian)
./doctor.py                   # what is installed and connected
./tonight.py --demo           # tonight's report with made-up weather
./serve.py --demo             # the web page, on http://localhost:8080
./mount.py --demo goto M27    # drive a simulated mount
```

**Use the planner for real** (still no telescope needed): put your location
in `config.toml`, then `./tonight.py`.

**Run a telescope:** `./install.sh`, then follow [Setup](#setup).

## Three parts, usable separately

| Part | Commands | Needs |
|---|---|---|
| **Planner** | `tonight.py`, `serve.py`, `clouds.py` | Any computer with Python. No telescope. |
| **Control** | `mount.py`, `polaralign.py`, `watch.py` | A SynScan mount and its serial lead. |
| **Imaging** | `snap.py`, `focus.py`, `solve.py`, `shoot.py`, `skywatch.py` | An INDI camera and ASTAP. |

Start with the planner; add hardware when you have it.

## Hardware

| Hardware | Status |
|---|---|
| Sky-Watcher EQ3 Pro SynScan, handset firmware 3.35, FTDI serial lead | ✅ Tested by the author |
| Sky-Watcher Explorer 150P (150 mm f/5 Newtonian) | ✅ Tested by the author |
| Altair Hypercam 183C on USB 2 | ✅ Tested by the author |
| Ubuntu 26.04, Python 3.14 | ✅ Tested by the author |
| Python 3.11, 3.12, 3.13 | ✅ Tests pass in CI (no hardware) |
| EQ5, HEQ5, EQ6 with a SynScan handset | ⚠️ Untested. Likely: same serial protocol. |
| Other INDI cameras | ⚠️ Untested. Likely for mono or RGGB colour sensors: set the driver and sensor size in `config.toml`. |
| Other telescopes | Set the focal length in `config.toml`. |
| Mounts driven without a handset (EQDIR), ASCOM, Alpaca | ❌ Not supported. |

Tested on one setup so far, and nobody but the author has run it yet. If you
try it on anything, working or not, please open a **Hardware compatibility
report** issue; rows marked "community tested" will be added from those.

## Commands

| Script | What it does |
|---|---|
| `tonight.py` | Report for the night: darkness, Moon, weather verdict, ranked targets. `--html` writes the web page. |
| `serve.py` | Serves the status page on port 8080: the night's report rebuilt every 10 minutes, and the imaging run, pictures and system panel refreshed every two seconds. |
| `clouds.py` | Fetches the latest infrared satellite image with the site marked on it. |
| `mount.py` | Moves the mount: `status`, `home`, `zenith`, `goto NAME [--solve]`, `point AZ ALT`, `sync`, `drift`, `compensate`, `stop`. |
| `liveview.py` | Takes a frame every few seconds so the status page shows what the telescope sees now. Steps aside while `shoot.py` runs. |
| `snap.py` | Takes one camera frame, saves the FITS in `frames/`, publishes a preview. |
| `shoot.py` | Takes a picture: many short exposures, each checked, lined up and stacked live, with the raw frames kept. `--exposure auto` picks the longest exposure the tracking allows. |
| `restack.py` | The quality pass: goes back over a session's raw frames, keeps the best, weights and clips them, and writes the finished picture. `shoot.py` runs it at the end. |
| `calibrate.py` | Makes master dark, bias and flat frames, which `shoot.py` and `restack.py` then apply automatically. |
| `camera_test.py` | `--gain-sweep` tries a range of gains on tonight's sky and suggests one. |
| `compare.py` | Shows the same patch of sky from several stacks side by side at full size, with star measurements for each. |
| `process.py` | Turns a finished stack into a cleaner picture: level sky, white stars, smoothed colour noise. |
| `focus.py` | Hands-free focusing aid: measures many stars at once and speaks the result. `--tones` for a rising pitch instead of speech, `--scene` for a daytime view. |
| `solve.py` | Plate-solves a frame: where is the telescope really pointing? |
| `polaralign.py` | Measures how far the polar axis is from the pole, from three plate solves. |
| `skywatch.py` | Photographs the sky every minute and stops when stars appear. |
| `doctor.py` | Checks what is installed and connected, and says what is ready: planner, mount, imaging. |
| `replay.py` | Turns a centring run recorded with `mount.py goto --solve --record` into a GIF. |
| `watch.py` | Photographs the telescope itself with the webcam. |
| `build_catalogue.py` | Regenerates `data/targets.csv` from OpenNGC. |
| `ty` | One front door for programs and AI agents: `capabilities`, `status`, `context`, `night`, `targets`, `target NAME`, `session`, `doctor`. Always answers in JSON. |
| `mcp_server.py` | Read-only MCP server offering the same information to MCP-aware assistants. |

`tonight.py`, `serve.py` and `mount.py` accept `--demo`.

The status page shows two pictures while imaging: **Now**, the newest single
exposure straight from the camera, and **Live stack**, everything added up so
far.

## For programs and AI agents

Everything a person can read, a program can read too, in one stable shape.
Start with [AGENTS.md](AGENTS.md); the details are in [docs/agents/](docs/agents/).

```
./ty capabilities                         # what is connected, allowed and locked
./ty status                               # mount, camera, imaging run, system
./ty context                              # a short plain-text briefing for an agent
./mount.py goto M27 --dry-run --json      # what a move would do, without moving
```

- **`--json`** on `mount.py`, `doctor.py` and `tonight.py`, and always from
  `ty`. Every answer is the same envelope: `schema_version`, `ok`, `command`,
  `timestamp`, `data`, `warnings`, `errors`. The shapes are JSON Schemas in
  [`schemas/`](schemas/).
- **Error codes that stay put**, such as `MOTION_LOCKED`,
  `TARGET_BELOW_ALTITUDE_LIMIT` and `HANDSET_NOT_SET_UP`, each saying whether
  retrying can help and what to do instead.
- **`--dry-run`** on every command that moves the mount: the same checks, the
  planned move and any warning (such as the tube swinging over the pole), and
  the hardware is never opened.
- **Web API**: `GET /api/v1/status`, `/capabilities`, `/night`, `/targets`,
  `/target/NAME`, `/session/current` and `/context` on the status page's port.
- **MCP**: `./mcp_server.py` over stdio; setup in
  [docs/agents/mcp.md](docs/agents/mcp.md).

The web API and the MCP server are read-only: they can report, plan and
simulate, and cannot move the mount or start the camera. Moving the telescope
from an agent means running `mount.py`, with the same limits as a person and
only when a person has asked for that move.
[`evals/`](evals/) holds the situations an agent should handle well; the test
suite checks the interface gives the right answer in each. They have not yet
been run with a model in the loop.

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

## How a picture is made

`shoot.py` works on many short exposures, because a modest mount cannot hold
a star still for long. Each frame goes through:

```
raw frame → saved to disk → dark and flat applied → 2x2 Bayer cells to RGB
→ stars measured (sharpness, roundness, brightness, count)
→ rejected if cloud, wind or a knock spoiled it
→ lined up on the first frame: shift and rotation, to a fraction of a pixel
→ added to a running stack that leaves out satellite trails
→ web page updated
```

It prints a line per frame, such as `032 ACCEPT  FWHM 3.4  round 0.93  stars
74` or `033 REJECT  star brightness down 41% (cloud)`.

When the run ends, `restack.py` does the same job again with hindsight: it
measures every saved frame, judges each against the better half of the
session (so a half-cloudy night does not set a cloudy standard), keeps the
best 85% of those that pass, lines them up on the sharpest, weights each by
sharpness, roundness, transparency and noise, clips
outliers against the whole session's average, removes the sky gradient, and
writes `final.fits` and `final.jpg` in the session folder
(`frames/NAME/<date-time>/`).

Things worth knowing:

- **It uses the whole processor, and the camera never waits for it.** The
  per-frame work is shared between worker processes, one per physical core.
  If frames ever arrive faster than they can be stacked live, the extra ones
  are saved raw and marked `LATER`, and the quality pass picks them up.
  `--profile` on `shoot.py` or `restack.py` reports where the time went.
- **Frames are checked cheaply before the expensive work.** Quality is judged
  on a quarter-size image first; only frames that pass are calibrated in
  full, cleaned and lined up.
- **The 2x2 Bayer reduction is deliberate.** It halves the resolution to
  about 1.3 arcseconds per pixel on this telescope, which suits ordinary
  seeing; the sensor's native 0.66 would only record blur more finely.
- **Drift is used, not fought.** The mount is only sent back to the target
  once it has drifted a fifth of the frame. Until then the stars wander over
  different pixels, so the sensor's fixed pattern averages away.
- **Calibration frames make a visible difference** and are picked up
  automatically once made:

      ./calibrate.py dark --exposure 2 --gain 1500    # cap on; match your exposure and gain
      ./calibrate.py bias --gain 1500                 # cap on
      ./calibrate.py flat                             # cap off, evenly lit: twilight sky through a white T-shirt

  Masters are averaged with outliers left out. A flat is filed under the
  `setup` name in `config.toml`, because it only suits the arrangement it was
  taken with: change the name and take a new flat whenever the camera is
  rotated or refitted. This camera cannot report its temperature, so with a
  bias and a dark at the same gain the dark is scaled to each frame's own hot
  pixels instead of being matched by temperature.
- **Alignment is shift and rotation only**, no scale or lens distortion,
  which is enough for one session through one set of optics. `restack.py`
  reports how closely the stars matched; if that ever nears a pixel, it is
  time for more.

- **Raw frames are large**: about 20 MB each, so a 300-frame session is 6 GB.
  Delete a session's `light-*.fits` once you are happy with `final.fits`, or
  use `--no-save`.

## The mount is wonky; measure how wonky

telescopeyoke does not assume a careful polar alignment, and it does not
trust the handset's own alignment model. It measures what the stars actually
do.

A polar axis that misses the pole makes the aim slide slowly in declination,
at a rate that depends only on the hour angle. So:

- `./mount.py compensate` photographs the sky at three RA positions, works
  out where the axis really points, and tells you how to fix it mechanically
  ("swing the north end 1.4° west, raise the axis 0.6°"). Or leave it: it
  then predicts the drift where the telescope is aimed, sets the Dec motor
  creeping against it, measures what is left, and says what exposure that
  allows.
- After that, every GoTo starts with the creep its part of the sky needs.
- `./mount.py drift` measures and trims the drift on its own: several plate
  solves with a line fitted through them, an uncertainty on the answer, part
  of the error corrected at a time, and the Dec motor never reversed for a
  small overshoot, because its gears have slack.
- `./shoot.py --assist` lets the pictures themselves report the drift, and
  trims the creep as the run goes.

What this cannot do: with the axis off the pole, the field still turns slowly
about the target, and the gears' own periodic wobble is untouched. The
stacker's rotation alignment deals with the first; short exposures deal with
the second. It is drift assist, not guiding.

## Focusing by ear

`./focus.py` is built for a manual focuser in the dark: turn the knob, listen.
It measures the half-flux radius (HFR) of up to forty stars at once, steadies
the readings over three frames, and ignores changes smaller than the air's
own shimmer. It says "Improving. 4.8", "No change", "Worse. Go back", and,
when the numbers bottom out and rise again, "Minimum passed. Reverse
slightly", then "Best focus. Hold" when you are back on it. `--tones` swaps
the speech for a tone whose pitch rises as focus improves.

## Setup

1. `./install.sh` installs the packaged software and creates `config.toml`
   from the example. Put in your location, and your camera's INDI driver and
   sensor details if they differ. Run `./doctor.py` (or `./install.sh
   --check`) at any point to see what is still missing.
2. Install the ASTAP D20 star database (about 400 MB) from
   <https://sourceforge.net/projects/astap-program/files/star_databases/>;
   it installs into `/opt/astap`.
3. If your camera's INDI driver is not packaged, build it. For the Altair
   driver on Ubuntu 26.04, from the
   [indi-3rdparty](https://github.com/indilib/indi-3rdparty) repository at
   the tag matching the installed INDI (`v1.9.9`):

       sudo apt install cmake libindi-dev libcfitsio-dev libnova-dev libusb-1.0-0-dev zlib1g-dev
       cd libaltaircam && cmake -DCMAKE_INSTALL_PREFIX=/usr -DCMAKE_POLICY_VERSION_MINIMUM=3.5 . \
           && make && sudo make install
       cd ../indi-toupbase     # first trim CMakeLists.txt to the indi_altair_ccd target only
       cmake -DCMAKE_INSTALL_PREFIX=/usr -DCMAKE_POLICY_VERSION_MINIMUM=3.5 . \
           && make && sudo make install

4. INDI server: by default the scripts connect to one you have started
   (`indiserver indi_altair_ccd`). If nothing else uses INDI on the machine,
   set `manage_server = true` under `[indi]` in `config.toml` and they will
   start and restart it themselves. Leave it off if a guider, focuser or
   filter wheel shares the server, because a restart cuts them all off.

On Ubuntu and Debian, `install.sh` takes the Python libraries from the
distribution's own packages. `pyproject.toml` lists the same libraries with
the oldest versions known to work, and is what CI and `pip install .` use.

## A night's routine

1. Set the mount in the home position, power on, and take the handset to its
   main menu.
2. `./mount.py zenith` to measure the handset's clock and check the mount
   moves correctly.
3. Focus: `./focus.py --scene` on something distant in daylight, then
   `./focus.py` on stars. Aim for a star size under 10.
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
- **The web page is read-only on purpose.** It is served to the whole home
  network with no login, which is fine for pictures and reports. Nothing that
  moves the mount will be added to it without authentication designed first.

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

Written but not yet run for real: `calibrate.py` (no dark or flat frames have
been taken yet) and `camera_test.py --gain-sweep`.

Rewritten since they were last used on real hardware, and so far proven only
against the simulator and made-up data: `focus.py` (multi-star HFR and the
new spoken guidance), `mount.py drift` (line-fitted, with the drift model),
`mount.py compensate` and `shoot.py --assist`. An earlier, cruder
`mount.py drift` did cancel most of the drift on the real mount.

Written but never run on the real mount: `polaralign.py` (its geometry is
checked by the tests against a simulated misaligned mount).

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

## What it needs from the computer

A 2017 four-core laptop (i7-7700HQ, 22 GB of memory, an SSD) runs all of this
with room to spare while the camera is the slow part. Capture, mount control
and the webcam must stay on the machine the hardware is plugged into. The
quality pass only needs a session's folder of raw frames, so it can be run on
a faster machine later if sessions grow into thousands of frames; the
telescope never depends on a second computer or on Wi-Fi to keep working.

## Roadmap

Near term:

- Someone other than the author running it. Reports from other SynScan
  mounts come before any new feature.
- Recordings for this page: a GoTo-and-centre run (`--record` and `replay.py`
  are ready for it) and a focusing session.
- Splitting this README into shorter pages under `docs/` once it grows further.
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
- Guiding and focuser support.

Not planned: ASCOM, mobile apps, a React front end, cloud services, AI target
selection, Docker images, plugin systems, a sequencing language. Bigger
projects (NINA, KStars/Ekos) do those well; this one stays small, readable,
and aimed at ordinary SynScan gear.

## Contributing

Reports from other hardware are the most useful contribution: open a
**Hardware compatibility report** issue with your mount, handset firmware and
camera, and what happened. For code, see [CONTRIBUTING.md](CONTRIBUTING.md):
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
