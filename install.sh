#!/usr/bin/env bash
# Set up telescopeyoke on Ubuntu or Debian.
#
#   ./install.sh            everything that can be installed from packages
#   ./install.sh --planner  only what the night planner and demo need
#   ./install.sh --demo     the same as --planner, then opens TelescopeYoke (demo)
#   ./install.sh --check    install nothing; report what is present and connected
#
# Python libraries come from the distribution's packages (python3-astropy and
# so on), which is the simplest route on Ubuntu and Debian. pyproject.toml
# lists the same libraries with the oldest versions known to work; it is what
# "pip install ." uses (the Windows installer).
#
# It does not build a camera driver or download the plate solver's star
# database; it prints what is left to do at the end.
set -euo pipefail
cd "$(dirname "$0")"

if [ "${1:-}" = "--check" ]; then
    exec ./doctor.py
fi

# Python 3.11 or newer (tomllib): Ubuntu 22.04's 3.10 and Debian 11's 3.9
# would install everything and then fail on the first command.
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
    echo "TelescopeYoke needs Python 3.11 or newer; this python3 is $(python3 -V 2>&1 || echo missing)." >&2
    echo "Ubuntu 24.04 or Debian 12 (or newer) have it." >&2
    exit 1
fi

planner_only=false
open_demo=false
case "${1:-}" in
    --planner) planner_only=true ;;
    --demo) planner_only=true; open_demo=true ;;
esac

packages=(python3-astropy python3-scipy python3-numpy python3-pil python3-requests python3-serial python3-jsonschema python3-sgp4)
# archive.py tess: TESS's light curves from MAST.
packages+=(python3-astroquery)
# The application's own window: GTK with a WebKit view.
packages+=(python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1)
if ! $planner_only; then
    # uhubctl: ./camera_test.py --power-cycle cuts the camera's power at the hub's port
    packages+=(indi-bin astap-cli ffmpeg speech-dispatcher uhubctl)
    # sxwheel.py: the Starlight Xpress filter wheel, a USB HID device
    packages+=(python3-hid)
fi

echo "Installing: ${packages[*]}"
sudo apt-get update
sudo apt-get install -y "${packages[@]}"

# Settings: an install that has them in this folder keeps them here, as
# before. A fresh one keeps them, and every file made from them, in a folder
# of their own, so moving to a newer release copies nothing (config.py).
data="${XDG_DATA_HOME:-$HOME/.local/share}/telescopeyoke/data"
if [ -f config.toml ]; then
    echo "Settings: config.toml in this folder, left alone"
elif [ -f "$data/config.toml" ]; then
    echo "Settings: $data/config.toml, left alone"
else
    mkdir -p "$data"
    cp config.example.toml "$data/config.toml"
    echo "Created $data/config.toml from the example. Edit it and put in your own location."
    echo "Your frames, pictures and records will be kept beside it, apart from the program."
fi

# TelescopeYoke and its demo in the applications menu.
./app.py --install-launcher

if $planner_only; then
    echo
    echo "Done. Start TelescopeYoke (demo) from the applications menu, or try:  ./tonight.py --demo"
    echo "Then, with your location set:  ./tonight.py"
    echo "Check the setup at any time with:  ./doctor.py"
    if $open_demo; then
        echo
        echo "Opening TelescopeYoke (demo): a pretend mount, camera and sky. Nothing real is connected or moved."
        exec ./app.py --demo
    fi
    exit 0
fi

# The filter wheel's /dev/hidraw is root's alone unless a rule opens it.
echo 'SUBSYSTEM=="hidraw", ATTRS{idVendor}=="1278", ATTRS{idProduct}=="0920", MODE="0666"' |
    sudo tee /etc/udev/rules.d/99-sxwheel.rules >/dev/null
# ModemManager probes every new serial port as a possible modem, and holds
# the handset's lead (FTDI 0403:6015) while it does (15 November 2026: it
# had ttyUSB0 each time the lead came back): told to leave it alone.
echo 'ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6015", ENV{ID_MM_DEVICE_IGNORE}="1"' |
    sudo tee /etc/udev/rules.d/99-ty-handset.rules >/dev/null
sudo udevadm control --reload-rules

# Serial access to the mount's handset.
if ! id -nG "$USER" | grep -qw dialout; then
    sudo usermod -aG dialout "$USER"
    echo "Added $USER to the dialout group. Log out and back in for it to take effect."
fi

cat <<'NEXT'

Done. Still to do by hand:

  1. Edit config.toml: your location, and your camera's driver and sensor.
  2. Star database for plate solving (about 400 MB): install the D20 database
     from https://sourceforge.net/projects/astap-program/files/star_databases/
     so that it sits in /opt/astap.
  3. Camera driver: if your camera's INDI driver is not packaged for your
     system, build it; the README has the steps used for the Altair driver.

Then try, with nothing plugged in:
    ./tonight.py --demo
    ./mount.py --demo goto M27

and check what is ready with:
    ./doctor.py
NEXT
