---
name: Hardware compatibility report
about: Tell us what happened when you tried telescopeyoke on your equipment, working or not
title: "Hardware report: "
labels: hardware-report
---

**Equipment**

- Mount:
- Handset and its firmware version (shown at power-on):
- Connection (which lead or adapter):
- Camera:
- Telescope (focal length):
- Linux distribution and version:
- Python version:

**What worked** (tick what you tried and it worked; leave blank what you did not try)

- [ ] Planner (`./tonight.py`)
- [ ] `./doctor.py` reports ready for mount
- [ ] Mount status (`./mount.py status`)
- [ ] Zenith and home (`./mount.py zenith`, `./mount.py home`)
- [ ] GoTo (`./mount.py goto NAME`)
- [ ] Camera frames (`./snap.py`)
- [ ] Plate solve (`./solve.py`)
- [ ] GoTo with centring (`./mount.py goto NAME --solve`)
- [ ] Stacking (`./shoot.py`)

**Output of `./doctor.py`**

```
paste here
```

**Notes**

Anything that needed changing in `config.toml`, anything that behaved oddly,
and anything that went wrong.
