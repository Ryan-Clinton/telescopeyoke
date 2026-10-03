# telescopeyoke

Scripts for driving a small telescope from a Linux laptop left outside with
it: planning the night, moving the mount, taking and checking camera frames,
and watching it all from indoors on a web page.

Built for, and only tested with:

- Sky-Watcher Explorer 150P (150 mm f/5 Newtonian) on an EQ3 Pro SynScan mount
- SynScan handset, firmware 3.35, connected by its serial lead through an FTDI
  USB adapter
- Altair Hypercam 183C camera on USB 2
- a USB webcam pointed at the telescope
- Ubuntu 26.04, Python 3.14

This is a first-night project. Some parts are well exercised, others have
never seen a star; see "State of things" below.

## Scripts

| Script | What it does |
|---|---|
| `tonight.py` | Report for the night: darkness, Moon, weather verdict, ranked targets. `--html` writes the web page. |
| `serve.py` | Serves `web/` on port 8080 and rebuilds the page every 10 minutes. |
| `clouds.py` | Fetches the latest infrared satellite image with the site marked on it. |
| `mount.py` | Moves the mount: `status`, `home`, `zenith`, `goto NAME [--solve]`, `point AZ ALT`, `sync`, `drift`, `stop`. |
| `snap.py` | Takes one camera frame, saves the FITS in `frames/`, publishes a preview. |
| `shoot.py` | Takes a picture: many short exposures lined up and averaged, re-centring as it goes. |
| `focus.py` | Focusing aid that speaks "better" or "worse" and the star size. `--scene` for a daytime view. |
| `solve.py` | Plate-solves a frame: where is the telescope really pointing? |
| `polaralign.py` | Measures how far the polar axis is from the pole, from three plate solves. |
| `skywatch.py` | Photographs the sky every minute and stops when stars appear. |
| `watch.py` | Photographs the telescope itself with the webcam. |
| `build_catalogue.py` | Regenerates `data/targets.csv` from OpenNGC. |

Supporting modules: `sky.py` (astronomy), `feeds.py` (weather, seeing, light
pollution, comets), `camera.py` and `indi.py` (the camera), `config.py`.

## Setup

1. Copy `config.example.toml` to `config.toml` and enter your location.
2. Install the packaged software:

       sudo apt install indi-bin astap-cli ffmpeg python3-astropy python3-scipy \
            python3-serial python3-pil python3-requests
       sudo usermod -aG dialout $USER      # then log out and back in

3. Install the ASTAP D20 star database (about 400 MB) from
   <https://sourceforge.net/projects/astap-program/files/star_databases/>;
   it installs into `/opt/astap`.
4. Build the Altair camera driver. Ubuntu does not package it. From the
   [indi-3rdparty](https://github.com/indilib/indi-3rdparty) repository at
   the tag matching the installed INDI (`v1.9.9` on Ubuntu 26.04):

       sudo apt install cmake libindi-dev libcfitsio-dev libnova-dev libusb-1.0-0-dev zlib1g-dev
       cd libaltaircam && cmake -DCMAKE_INSTALL_PREFIX=/usr -DCMAKE_POLICY_VERSION_MINIMUM=3.5 . \
           && make && sudo make install
       cd ../indi-toupbase     # first trim CMakeLists.txt to the indi_altair_ccd target only
       cmake -DCMAKE_INSTALL_PREFIX=/usr -DCMAKE_POLICY_VERSION_MINIMUM=3.5 . \
           && make && sudo make install

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

## State of things

Working on real hardware and real stars: the night report and web page,
mount moves through the handset, camera frames, focusing, plate solving,
`goto --solve` (centres a target to a fraction of an arcminute), `sync`, and
stacking with `shoot.py`.

Working but only lightly tested: `mount.py drift` (cancels declination drift
by creeping the Dec motor; the gears' slack makes it slow to settle).

Written but never run on the real mount: `polaralign.py` (its geometry is
checked against a simulated misaligned mount).

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

## Data sources

Weather: [Open-Meteo](https://open-meteo.com). Seeing: [7Timer](https://www.7timer.info).
Light pollution: [D. Lorenz's atlas](https://djlorenz.github.io/astronomy/lp/).
Comets: [COBS](https://cobs.si) and [JPL Horizons](https://ssd.jpl.nasa.gov/horizons/).
Cloud imagery: [EUMETSAT](https://view.eumetsat.int).

`data/targets.csv` is derived from [OpenNGC](https://github.com/mattiaverga/OpenNGC)
and is licensed CC-BY-SA-4.0.
