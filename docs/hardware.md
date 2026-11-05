# Hardware: what it has run on, and how to add yours

[README](../README.md) · [All docs](README.md) · Guides: [First night](first-night.md) · [Setup](setup.md) · [Imaging](imaging.md) · [Calibration](calibration.md) · [Focus](focus.md) · Science: [Discovery](discovery.md) · [Results](results.md) · [Validation](validation.md) · [Data](data.md) · Developers: [Contributing](../CONTRIBUTING.md) · [Agents](agents/README.md)

**Other mounts are wanted.** It has driven one mount, a Sky-Watcher EQ3
Pro; nothing in it is meant to stay Sky-Watcher-only. [Mounts](mounts.md)
says which mounts can be reached and how, in the order planned: the rest of
Sky-Watcher's family through the motor board's own protocol, Celestron's
NexStar hand controllers, any mount INDI drives on Linux, any ASCOM or Alpaca
driver through Alpaca, and ZWO's AM mounts natively. Ask for yours, or offer
to test one, with a
[Mount support request](https://github.com/Ryan-Clinton/telescopeyoke/issues/new?template=mount-support.yml):
the first step only reads, and nothing moves until you choose it.

## Tried so far

One row for each set of equipment someone has run it on. So far all of them
are the author's. [Validation](validation.md#current-conclusions) has the
evidence behind each tick.

| Mount | Handset | Camera and optics | System | What has worked | Tried by |
|---|---|---|---|---|---|
| Sky-Watcher EQ3 Pro | SynScan, firmware 3.35, FTDI serial lead | Explorer 150P (750 mm f/5); Altair Hypercam 183C, colour (on USB 2 on 3 and 4 October 2026, on a 3 m USB 3 lead since 6 October) | Ubuntu 26.04, Python 3.14 | ✅ Planner, mount moves, camera, focusing (by hand and by motor), plate solving, GoTo with centring, polar alignment, imaging and stacking, under real stars | the author |
| the same EQ3 Pro | the same | the same Hypercam 183C | Windows 11 | ⚠️ The demo, and camera frames indoors. No mount driven, no star seen | the author |
| the same EQ3 Pro | the same | The 150P with a 0.9x coma corrector (675 mm f/4.5); Altair Hypercam 183M PRO TEC, mono and cooled (Altair's library, `[cameras.183m]`, `./cameras.py`); Starlight Xpress 7-position USB filter wheel (`./sxwheel.py`): L, R, G, B, Ha, SII, OIII | Ubuntu 26.04 | ✅ First night 4-5 November 2026: recognised by its profile, every frame at every readout speed, the cooler holding -5 °C with the camera kept open all session, master darks at -5 °C, all seven filter slots, focus by hand (HFR 2.0), plate solving at 1.46"/px in 0.2-0.3 s, polar alignment, and M33 in L (34 minutes of 16 s frames). ❌ No flats yet; the motor focuser cannot lift this train; the first colour picture failed (each filter's stack drifted further off; fixed, not yet rerun). [The record](nights/2026-11-04/183m-first-night.md) | the author |
| EQ5 | SynScan | any | Linux or Windows | ❔ wanted | could be you |
| HEQ5 | SynScan | any | Linux or Windows | ❔ wanted | could be you |
| EQ6, EQ6-R | SynScan | any | Linux or Windows | ❔ wanted | could be you |
| any of them | SynScan | another INDI camera | Linux | ❔ wanted | could be you |
| a mount converted with an EQStar or other EQMOD-style controller | none | any | Linux or Windows | ❔ wanted: whether it answers at all | could be you |

## To add a row

Working or not:

1. Run `./doctor.py --report` (on Windows `python doctor.py --report`), or
   press "Write a hardware report" on the application's Doctor screen. It
   writes out what the computer is, what the handset says the mount is and
   its firmware version, and every check. It only looks: nothing is moved,
   and your location is left out.
2. Paste it into a
   [Hardware compatibility report](https://github.com/Ryan-Clinton/telescopeyoke/issues/new?template=hardware-report.md)
   and tick what you tried. Your GitHub name goes beside your row if you
   want it there.

You can stop there. If you want to go further without the mount turning,
`./mount.py status` reads its position and `./mount.py goto M27 --dry-run`
checks a move against the limits and says what it would do, without making
it. For a question first ("will it work with my HEQ5?"), ask in
[Discussions](https://github.com/Ryan-Clinton/telescopeyoke/discussions).

**A controller that is not a SynScan handset** (an EQDIR lead, an
Astro-Gadget EQStar, anything normally driven through EQMOD): nobody knows
yet whether telescopeyoke can talk to yours, and it does not guess. Name the
port and it will ask:

```bash
./doctor.py --report --probe COM7        # Linux: --probe /dev/ttyUSB0
```

It asks that one port what it is, first as a SynScan handset and then as a
Sky-Watcher motor board (the language EQMOD speaks), at 9600 and at 115200
baud, and writes what answered into the report along with the adapter's
make and USB numbers. Every question only reads; nothing is told to move.
Close EQMOD first, since only one program can have the port.

## Already using EQMOD or ASCOM?

Keep them. telescopeyoke does not use ASCOM and changes nothing about an
ASCOM or EQMOD installation: it talks to the mount's COM port itself. The
one rule is that two programs cannot hold the same port at once, so close
EQMOD (or NINA, or the SynScan app) before starting telescopeyoke on that
mount, and the other way round. On Windows the doctor says so when it sees
ASCOM or EQMOD installed. What it adds to a setup that already works is the
part in between: targets ranked for your own horizon, a GoTo that
plate-solves and centres itself, focusing by ear, and short exposures
checked and stacked as they arrive.

## More than one telescope

A **rig** is one telescope with its own settings and its own files. With two
out on a good night, each runs in a window of its own:

```bash
./app.py --new-rig heq5       # its settings (rigs/heq5.toml) and "TelescopeYoke (heq5)" in the menu
./app.py --rig heq5           # open it; set it up on its Settings screen
./ty --rig heq5 mount status  # any command, for that rig
./ty rigs                     # every rig in one view: what each is and what it is imaging
```

Each rig keeps its own frames, pictures, calibration frames and remembered
measurements under `rigs/heq5/`, so two nights' work never mix. The
application's Rigs screen shows what every rig is doing. With no rig named
everything is as before: `config.toml` and the folders beside it. The motion
lock (`MOTION_LOCKED`) stops every rig at once.

## What to expect of other equipment

| Hardware | Status |
|---|---|
| Sky-Watcher Explorer 150P (150 mm f/5 Newtonian) | ✅ Used by the author, at 750 mm and with a 0.9x coma corrector at 675 mm |
| Altair Hypercam 183C (colour) | ✅ Used by the author through INDI on Ubuntu and through Altair's library on Windows |
| Altair Hypercam 183M PRO TEC (mono, cooled) and a Starlight Xpress USB filter wheel | ✅ Used by the author from 4 November 2026; see the row above for what is still to prove |
| Python 3.11 to 3.14 | ✅ Runs on Ubuntu (no automated tests) |
| Windows 10 and 11 | ⚠️ The demo runs with no hardware. The camera has taken frames on Windows 11, indoors. No mount has been driven from Windows, and camera and mount have not been used together there. |
| SynScan Wi-Fi adapter, or an EQDIR lead (no handset) | ⚠️ The adapter has been found and read on a real EQ3 (firmware, gearing, position). No mount has been moved through it yet; the EQDIR lead is untried. |
| EQ5, HEQ5, EQ6 with a SynScan handset | ⚠️ Untested. Likely: same serial protocol. |
| Other INDI cameras | ⚠️ Untested. Likely for mono or RGGB colour sensors: set the driver and sensor size in `config.toml`. |
| Other telescopes | Set the focal length in `config.toml`. |
| ASCOM, Alpaca | ❌ Not used yet. An ASCOM or EQMOD installation is noticed and left alone; see above. Alpaca is planned as the way to every ASCOM driver ([Mounts](mounts.md)). |
| Celestron, ZWO, iOptron and others | 🗓️ Planned, in order, in [Mounts](mounts.md); testers wanted. |
