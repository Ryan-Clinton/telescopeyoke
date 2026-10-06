---
name: Hardware compatibility report
about: Tell us what happened when you tried telescopeyoke on your equipment, working or not
title: "Hardware report: "
labels: hardware-report
---

A report is useful even if you moved nothing: what the doctor found on your
equipment is worth having by itself.

**The report**

Run `./doctor.py --report` (on Windows, `python doctor.py --report`), or
press "Write a hardware report" on the application's Doctor screen, and paste
what it writes here. It says what the computer is, what the handset says the
mount is, and every check. It leaves out your location and moves nothing.

```
paste here
```

**Equipment it cannot see for itself**

- Mount (as sold, for example "HEQ5 Pro"):
- Connection (which lead or adapter):
- Camera:
- Telescope (focal length):

**What worked** (tick what you tried and it worked; leave blank what you did not try)

- [ ] The demo (`./app.py --demo`)
- [ ] Planner (`./tonight.py`)
- [ ] `./doctor.py` reports ready for mount
- [ ] Mount status (`./mount.py status`): reads the position, moves nothing
- [ ] A move checked without making it (`./mount.py goto NAME --dry-run`)
- [ ] Zenith and home (`./mount.py zenith`, `./mount.py home`)
- [ ] GoTo (`./mount.py goto NAME`)
- [ ] Camera frames (`./snap.py`)
- [ ] Plate solve (`./solve.py`)
- [ ] GoTo with centring (`./mount.py goto NAME --solve`)
- [ ] Stacking (`./shoot.py`)

**Notes**

Anything that needed changing in `config.toml`, anything that behaved oddly,
and anything that went wrong.

**Credit**

If your equipment goes into the README's table, may your GitHub name go
beside it? (yes / no)
