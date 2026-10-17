---
name: first-night
description: Take someone new from a fresh telescopeyoke checkout to their first picture. Only when the person types /first-night; it installs software and writes their settings.
disable-model-invocation: true
compatibility: a fresh telescopeyoke checkout, Python 3.11 or later, Ubuntu or Windows, the internet; a SynScan mount and a camera
allowed-tools: Bash(./doctor.py *) Bash(./ty capabilities *) Bash(lsusb)
---

# First night

The person's guide is `docs/first-night.md`, the install `docs/setup.md`
(Windows: its "Windows" section). Read both now. They may know nothing
about telescopes yet: say what each step is for, once, in a line, the
first time it comes up.

Indoors, in the daytime:

1. The installer: `./install.sh` on Ubuntu, `install.ps1` on Windows.
2. Their site in `config.toml`: ask for their latitude and longitude, or
   the nearest town, and say it stays on this computer and out of git.
   Never guess it.
3. The ASTAP star database (`docs/setup.md`, step 2).
4. `./doctor.py` until everything it checks is ready, plugging things in
   as it asks; `./doctor.py --offline` needs no mount.
5. A first frame from the camera indoors (`./snap.py`), to see it works.

At night, outside: the `nightly-setup` skill, explaining each step the
first time, then `imaging-run` on something bright and big that the
planner suggests (`./ty tonight`). Finished with their first picture.
