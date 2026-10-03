# telescopeyoke 🔭

**Turn an ordinary SynScan telescope into a locally controlled smart telescope.**

*Give your old SynScan telescope a brain.*

[![tests](https://github.com/Ryan-Clinton/telescopeyoke/actions/workflows/tests.yml/badge.svg)](https://github.com/Ryan-Clinton/telescopeyoke/actions/workflows/tests.yml)

![The web page: tonight's verdict, the latest frame through the telescope, and ranked targets](docs/dashboard.jpg)

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
- 🔊 **Speaks focus feedback**: "better, 66" … "worse, 80" while you turn the focuser
- 📷 **Captures and stacks images**, re-centring as the sky drifts
- 🏠 **Shows it all on a web page** you can watch from indoors
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
| `serve.py` | Serves `web/` on port 8080 and rebuilds the page every 10 minutes. |
| `clouds.py` | Fetches the latest infrared satellite image with the site marked on it. |
| `mount.py` | Moves the mount: `status`, `home`, `zenith`, `goto NAME [--solve]`, `point AZ ALT`, `sync`, `drift`, `stop`. |
| `snap.py` | Takes one camera frame, saves the FITS in `frames/`, publishes a preview. |
| `shoot.py` | Takes a picture: many short exposures lined up and averaged, re-centring as it goes. |
| `process.py` | Turns a finished stack into a cleaner picture: level sky, white stars, smoothed colour noise. |
| `focus.py` | Focusing aid that speaks "better" or "worse" and the star size. `--scene` for a daytime view. |
| `solve.py` | Plate-solves a frame: where is the telescope really pointing? |
| `polaralign.py` | Measures how far the polar axis is from the pole, from three plate solves. |
| `skywatch.py` | Photographs the sky every minute and stops when stars appear. |
| `doctor.py` | Checks what is installed and connected, and says what is ready: planner, mount, imaging. |
| `replay.py` | Turns a centring run recorded with `mount.py goto --solve --record` into a GIF. |
| `watch.py` | Photographs the telescope itself with the webcam. |
| `build_catalogue.py` | Regenerates `data/targets.csv` from OpenNGC. |

`tonight.py`, `serve.py` and `mount.py` accept `--demo`.

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
- **`simulator.py`** is a pretend handset and mount behind `--demo` and the
  tests.

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
`goto --solve` (centres a target to a fraction of an arcminute), `sync`, and
stacking with `shoot.py`.

Working but only lightly tested: `mount.py drift` (cancels declination drift
by creeping the Dec motor; the gears' slack makes it slow to settle).

Written but never run on the real mount: `polaralign.py` (its geometry is
checked by the tests against a simulated misaligned mount).

Covered by automated tests (`pytest`, run on every push on Python 3.11 to 3.14): the astronomy, the
mount logic against the simulated handset, frame alignment and hot-pixel
removal, the focus measurement, the polar alignment geometry, the INDI
message handling, and the demo report end to end. The tests cannot cover the
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
- Recordings for this page: a GoTo-and-centre run (`--record` and `replay.py`
  are ready for it) and a focusing session.
- Splitting this README into shorter pages under `docs/` once it grows further.
- More of the camera's quirks moved into `config.toml` as other cameras are tried.
- Faster frames: a newer camera driver, or USB 3.

Later, if people ask for them:

- Raspberry Pi or other small computer strapped to the telescope.
- Controls on the web page, behind a login.
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
