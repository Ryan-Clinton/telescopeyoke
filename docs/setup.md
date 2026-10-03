# Setup

[Back to the README](../README.md)

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

## What it needs from the computer

A 2017 four-core laptop (i7-7700HQ, 22 GB of memory, an SSD) runs all of this
with room to spare while the camera is the slow part. Capture, mount control
and the webcam must stay on the machine the hardware is plugged into. The
quality pass only needs a session's folder of raw frames, so it can be run on
a faster machine later if sessions grow into thousands of frames; the
telescope never depends on a second computer or on Wi-Fi to keep working.
