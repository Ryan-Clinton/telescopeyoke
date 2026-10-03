#!/usr/bin/env bash
# Set up telescopeyoke on Ubuntu or Debian.
#
#   ./install.sh            everything that can be installed from packages
#   ./install.sh --planner  only what the night planner and demo need
#   ./install.sh --check    install nothing; report what is present and connected
#
# Python libraries come from the distribution's packages (python3-astropy and
# so on), which is the simplest route on Ubuntu and Debian. pyproject.toml
# lists the same libraries with the oldest versions known to work; it is what
# CI and "pip install ." use.
#
# It does not build a camera driver or download the plate solver's star
# database; it prints what is left to do at the end.
set -euo pipefail
cd "$(dirname "$0")"

if [ "${1:-}" = "--check" ]; then
    exec ./doctor.py
fi

planner_only=false
[ "${1:-}" = "--planner" ] && planner_only=true

packages=(python3-astropy python3-scipy python3-numpy python3-pil python3-requests python3-serial)
if ! $planner_only; then
    packages+=(indi-bin astap-cli ffmpeg speech-dispatcher)
fi

echo "Installing: ${packages[*]}"
sudo apt-get update
sudo apt-get install -y "${packages[@]}"

if [ ! -f config.toml ]; then
    cp config.example.toml config.toml
    echo "Created config.toml from the example. Edit it and put in your own location."
fi

if $planner_only; then
    echo
    echo "Done. Try:  ./tonight.py --demo     then, with your location set:  ./tonight.py"
    echo "Check the setup at any time with:  ./doctor.py"
    exit 0
fi

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
