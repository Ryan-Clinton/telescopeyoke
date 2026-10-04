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

## The mount without its handset

The tested way to reach the mount is a serial lead to the SynScan handset.
It can also be reached with the handset unplugged, through the SynScan Wi-Fi
adapter or an EQDIR lead. **No real mount has been moved this way yet**; the
adapter has only been found and read.

1. In `config.toml` under `[mount]`, set `link = "wifi"` (or `"eqdir"`).
   The Wi-Fi adapter is found by asking the network. It makes its own
   network, `SynScan_WiFi_xxxx`; it is simpler to use the SynScan app once to
   have it join yours, so the computer keeps its internet connection.
2. `./doctor.py` says what answered and what is still to do.
3. Put the mount at its home position (counterweight bar down, tube pointing
   at the pole) and run `./mount.py sethome`. It moves nothing. Do it again
   whenever the mount has been switched off and moved, or its clutches
   loosened: unlike the handset, the motor board cannot be told by buttons.
4. Once for each mount, with someone standing by it: `./mount.py directions`.
   It tips the tube 5° from home, asks which way it went, and puts it back.
   Until then a GoTo is refused, because the Dec motor turning the other way
   would send the tube to the wrong side of the pole.
5. Then everything is as with the handset: `./mount.py goto M27 --dry-run`
   first, and stand by the mount for the first real moves.

Close the SynScan app and anything else talking to the mount first.

## The application

`./install.sh` puts **TelescopeYoke** in the applications menu, with
**TelescopeYoke (demo)** beside it for trying everything with nothing plugged
in. On Windows, `install.ps1` puts the same two in the Start Menu. From a
terminal it is `./app.py` (or `python app.py` on Windows).

It opens in a window of its own. The first time, or whenever something the
telescope needs is missing, it opens on a Welcome screen that lists what is
ready and what is not, with a button to the screen that deals with each:
Camera, Telescope, Plate solver, Webcam, Settings. After that it opens on
Tonight.

Every move is shown as a plan first and happens only when you confirm it.
Stop is always at the top right. Closing the window ends whatever is running
and tells the mount to stop; if something is running it asks first.

`./console.py` gives the observing screens alone as a page in a browser on
the same computer, without the equipment and tools. The status page
(`serve.py`) is separate and stays read-only for watching from elsewhere in
the house.

## Windows

telescopeyoke runs natively on Windows 10 and 11: no WSL and no ASCOM. What
has and has not been proven there is in the README's "Current status".

Commands in these documents are written for Linux. On Windows `./mount.py
goto M27` is typed `python mount.py goto M27`, and `./ty status` is
`.\ty status`.

1. Install 64-bit Python 3.11 or newer from python.org, ticking "Add
   python.exe to PATH". Then, in PowerShell in the project folder:

       .\install.ps1

   If Windows answers that running scripts is disabled, run it this once as
   `powershell -ExecutionPolicy Bypass -File .\install.ps1`. It installs the
   Python libraries and creates `config.toml`; it needs no administrator
   rights and changes no system setting. `python doctor.py` then says what
   is still missing, and how to fix each thing.
2. **Paths in `config.toml`** are written with forward slashes:
   `"C:/Program Files/astap"`. Inside double quotes a backslash starts an
   escape, so `"C:\Program Files\astap"` is an error. Single quotes also
   work: `'C:\Program Files\astap'`.
3. **Camera.** INDI does not run on Windows, so the camera is read through
   Altair's own library.
   - Download "Altair Camera SDK" from <https://www.altairastro.help>
     (Software downloads). Their site gives it only to a logged-in visitor,
     so register there first; this is the one step nothing can do for you.
     Leave the zip in your Downloads folder.
   - Plug the camera in and run `python camera_setup.py`, or press "Set up
     the camera" under Tools in the console. It checks the camera is there
     and has a driver, takes `altaircam.py` and the 64-bit `altaircam.dll`
     out of the zip into `vendor\altair\`, loads the library and takes a
     test frame, saying at each step what it found. Those files are
     Altair's and are not part of this repository. `--check` only looks.
   - The driver: on the Windows 11 machine this was tried on, Windows gave
     the camera its own built-in driver (WinUSB) as soon as it was plugged
     in. If the setup says there is no working driver, install AltairCapture
     from the same site, which brings one; check the camera shows a picture
     in it, then close it, because only one program can hold the camera.
   - If frames are slow or cut off, open the camera and the USB hub it hangs
     from in Device Manager and, on the Power Management tab, untick "Allow
     the computer to turn off this device to save power".
4. **Mount.** The handset's lead shows up as a COM port, found by its
   adapter's name: `serial_match = "FTDI"` under `[mount]` suits the tested
   lead. A handset plugged in by its own USB socket is a Prolific PL2303
   port: install Prolific's driver and set `serial_match = "Prolific"`.
   `--port COM5` overrides the search. If nothing matches, the command
   refuses and lists the ports it saw; it never guesses one. Close EQMod,
   SharpCap, NINA or anything else holding the port.
5. **Plate solver.** Install ASTAP's command-line program, `astap_cli.exe`,
   and the D20 star database, both into `C:\Program Files\astap`. To keep
   them elsewhere, name them under `[solver]` in `config.toml`.
6. **Webcam and sound.** Install ffmpeg, including `ffplay`, and put it on
   PATH. List the cameras with `ffmpeg -list_devices true -f dshow -i dummy`
   and put the one that watches the telescope under `[webcam] device` in
   `config.toml`. Without `ffplay` the focusing aid speaks but has no tones.
7. **Sending `--json` to a file.** The output is UTF-8. Windows PowerShell
   5.1 re-encodes what a program prints before `>` writes it; to keep it
   exact use `cmd /c "python doctor.py --json > result.json"`, or PowerShell
   7.

## What it needs from the computer

A 2017 four-core laptop (i7-7700HQ, 22 GB of memory, an SSD) runs all of this
with room to spare while the camera is the slow part. Capture, mount control
and the webcam must stay on the machine the hardware is plugged into. The
quality pass only needs a session's folder of raw frames, so it can be run on
a faster machine later if sessions grow into thousands of frames; the
telescope never depends on a second computer or on Wi-Fi to keep working.
