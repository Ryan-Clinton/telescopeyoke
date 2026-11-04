# More than one camera: adding the 183M PRO TEC, filter wheel and corrector

Spec for adding Gary's mono imaging train to the 150P, bought 4 November
2026 and fitted that day. It says what the hardware is, what changes on the
telescope, what every part of the software has to do differently, and how
the first night proves it. Figures from vendors are marked with their
source; figures not yet measured on this rig say so.

## The rule: an addition, not a replacement

The project gains a second imaging camera; it does not swap one for the
other. The colour 183C stays fully supported: its code path, settings,
calibration, focus positions and records keep working unchanged, and on any
night either camera can be the one on the telescope. The software finds out
which camera is plugged in and uses that camera's profile; nothing assumes
there is only one. Each camera keeps its own darks, flats, focus positions,
reference images and fault history, so a night with one never spoils the
other's records. The guide camera (`guidecam.py`) is a third camera already
and stays separate.

Done means: with the 183C plugged in, every command behaves as it did
before this work, and its tests pass untouched; with the 183M plugged in,
the same commands work in mono with the filter wheel.

## What is arriving

| Part | What it is | Facts that matter here |
|---|---|---|
| Camera | Altair Hypercam 183M PRO TEC | Sony IMX183 mono, 5440 x 3648 at 2.4 um, 12-bit; TEC up to 45 °C below ambient; **4 GB DDR3 frame buffer** (the 183C has none); 12 V supply for the cooler; 580 g; two USB 2 sockets on the back fed by an internal hub [1][2][3]. Same Altair SDK as the 183C. Fan and TEC run only while a computer has the camera open [1]. |
| Filter wheel | Starlight Xpress USB wheel, 7 x 1.25" (to be confirmed: the Mini is 5-position, so 7 x 1.25" is the standard SXUFW-1) | USB HID, `1278:0920`, powered from USB; about 33 mm thick T2-T2 [4][5]. Selects filter 1 after power-up; reports 0 filters until that turn ends [6]. |
| Filters | Optolong L, R, G, B; SII, Ha, OIII (1.25") | Narrowband brand and bandwidth to be confirmed. One slot spare. |
| Corrector | Sky-Watcher 0.9x coma corrector (part 20233) | For f/4-f/6 Newtonians; makes the 150P **f/4.5, 675 mm**; needs **55 mm** (±2) from the bottom of its 2" thread to the sensor [7]. |

## What changes on the telescope

**Tube mod.** The 150P was not designed to reach focus with a camera, and
the corrector plus 55 mm of camera and wheel need even more inward focus.
The usual fix is to move the primary mirror 20-25 mm up the tube and
recollimate [8]; cutting the drawtube is the other way. Gary does it on
4 November with the user's Dremel. Record how far the mirror moved (mm) and
which way was chosen here when it is done.

**Image scale and field.** At 675 mm instead of 750 mm:

| | 183C at 750 mm (now) | 183M at 675 mm (new) |
|---|---|---|
| Native scale | 0.66"/px | 0.73"/px |
| Scale after the pipeline's 2x2 | 1.32"/px | 1.47"/px |
| Field | 1.00° x 0.67° | 1.11° x 0.74° |
| Focal ratio | f/5 | f/4.5 |

The field gets about 11 % wider each way and the stars stay sharp to the
corners. That suits the big targets the user prefers.

**Weight.** Camera, wheel, corrector and filters weigh roughly 1-1.2 kg at
the focuser (580 g measured for the camera; the rest estimated). The 183C
weighs less. The EQ3 Pro was already carrying the 150P near its limit, so
rebalance both axes with the new train on, and watch the guiding-free
tracking (trailed-frame share) on the first night against the 183C nights.

**Focuser.** The motor now lifts the heavier train. On 30 October the
28BYJ-48 stalled when it was powered from the laptop's own port and lifted
from the powered hub, which has gone back. The NEMA17 upgrade becomes needed
rather than optional if the first walk-in stalls outward. The Sharpie mark
and every stored focus position are void after the tube mod.

**USB and power.** One lead goes to the laptop: the camera's USB 3. The
camera's own USB 2 hub feeds the wheel and the focuser. One of its two
sockets broke in Gary's mount collision. Until Mark solders in a
replacement double socket (£3.59), a Trust Halyx 4-port USB 2 hub
(unpowered) sits in the working socket. Two things are unknown and decide
whether the focuser gets enough power:

- whether the camera's hub ports are powered from its 12 V supply or from
  the laptop's USB;
- how much the wheel and the Nano draw together through one unpowered hub.

The first focus run is the test. A focuser stall then is a power problem,
not the camera.

**The camera fault and the new camera.** The 183C loses frames because it
has no buffer and an ageing board (docs/camera-fault.md). The 183M PRO has
a 4 GB buffer, so it may not have the fault at all. The readout speed and
the lost-frame refusals become per camera: the 183C keeps Speed 0 and its
refusals; the 183M starts at Speed 0 too and is tried faster only after a
full clean night, with the result recorded against the 183M alone.

**The 183C after the tube mod.** With the mirror moved up, the 183C reaches
focus with spacers behind the corrector at the same 55 mm (it is the same
sensor and needs the same spacing), or with an extension tube without the
corrector at 750 mm. Which one is used is part of its train (below).

## Software work

Each item is a change to an existing command or a new one, with its test,
before its first use on the sky. Item 0 comes first, because every other
item files its settings and records by camera.

0. **Camera profiles** (`config.py`, `config.example.toml`,
   `config.SETTINGS`). Today `[camera]` describes one camera and `[scope]`
   one focal length. They become:
   - `[cameras.NAME]`, one table per camera (`183c`, `183m`): how to
     recognise it (the SDK's model name, or a serial), colour or mono,
     cooled or not, sensor size and pixels, bit depth, readout speed, gain
     and offset, and the 183C's existing options (power cycle on jam).
   - `[trains.NAME]`, one per light path: which camera, corrector factor
     (0.9 or none), filter wheel or none, and the `setup` name flats are
     filed under today. The effective focal length is 750 x the factor.
   - The camera in use is the one the SDK finds plugged in, matched to a
     profile; a setting or `--camera NAME` overrides when both are
     plugged in. An unknown camera is refused with what was found, not
     guessed. The old single `[camera]` table still loads as the `183c`
     profile, so the existing `config.toml` keeps working unchanged.
   - Everything kept per camera lives under the camera's name in the data
     folder: darks, flats, focus positions and filter offsets, readout and
     lost-frame records, patrol references and zero points. The 183C's
     existing files move under `183c` once, by a tested step.
   - Every frame carries `INSTRUME` (the camera) and `TELESCOP`/`FOCALLEN`
     (the train), so a stack or a difference image never mixes cameras by
     accident; stacking refuses a mixed set.

1. **Mono frames** (`altair.py`, `camera.py`, `stacking.py`). Detect a mono
   camera from the SDK. Leave out `BAYERPAT`. Treat each 2x2 block as one
   pixel the way the colour mosaic is treated now, so the 1.47"/px scale
   and everything downstream keep working; `colour()` gives a grey image.
   Native 0.73"/px is oversampled for this sky's seeing, so keep the 2x2.
   *Built 4 Nov; not yet tried on the 183M.*
2. **Cooler** (`altair.py`, `config.SETTINGS`). Target temperature as a
   setting; `CCD-TEMP` and `SET-TEMP` in every FITS header; the run waits
   until the sensor is within 1 °C of target before keeping frames.
   Altair's own advice is that cooling below about 10-15 °C gains little on
   this sensor [2], so start with a fixed 0 °C in winter and the same value
   all season, so one dark library serves. *Built 4 Nov; not yet tried on the 183M.*
3. **Filter wheel command** (`sxwheel.py`). `status`, `move NAME|NUMBER`,
   the filter names as a setting. Protocol from INDI's driver
   (`indi-3rdparty/indi-sx/sxwheel.cpp`): 2-byte HID write, 2-byte reply
   `[current, total]`; `{0,0}` queries, `{f,0}` moves one way, `{f+0x80,0}`
   moves the shorter way; poll every 250 ms until it arrives. Needs
   `python3-hid` (install.sh). `FILTER` card in every frame. *Built 4 Nov (`./sxwheel.py status`,
   `move NAME|NUMBER`); needs the udev rule install.sh writes.*
4. **Focal length from the train** (every user of `focal_length_mm`:
   plate-solve scale hints, field of view, the planner's framing,
   `polaris.py`, `moon.py`, `landmark.py`, `focus.py`, `agent.py`,
   `camera_test.py`). Each reads the active train's effective focal length
   and the active camera's sensor, not a single setting, so 750 mm with the
   183C and 675 mm with the 183M are both right.
5. **Filter in the plan** (`shoot.py`, `schedule.py`). A run step names its
   filter. An LRGB step cycles filters in blocks (for example 10 L, then 5
   each of R, G, B), moving the wheel and the focus offset between blocks.
   Default L, so a step that says nothing behaves like today.
6. **Focus per filter** (`focus.py`, `focuser.py`). Walk-in in L as now.
   Measure the offset of every other filter from L once (walk-in in each),
   keep it, and apply it when the wheel moves. Reset the stored travel and
   start position after the tube mod.
7. **Calibration** (`calibrate.py`, `stacking.py`, docs/calibration.md).
   Darks are filed by camera, and for a cooled camera matched by
   temperature as well as exposure and gain, so a 183M library made once
   at the set temperature is reused. The 183C keeps its own darks and its
   "scaled to the night" method for a camera with no thermometer. Flats
   per camera, train and filter.
8. **Discovery and photometry** (`difference.py`, `depth.py`, `patrol.py`,
   `transits.py`, `precision.py`). References and zero points are kept per
   camera and band: the 183C's unfiltered colour references stay for nights
   with the 183C, and each patrol field gets a 183M reference in Optolong L
   before its difference images mean anything, with its own Gaia G zero
   point. A difference image always pairs a frame with a reference from
   the same camera and band. Transits in L (most light) or R (less scintillation
   and red-star bias), chosen per target. A candidate nova can be checked
   in Ha, where novae are bright. There is no photometric V filter in the
   set; G stands in, and results say "G (Optolong)", never "V".
9. **Stream and page** (`stream.py`, `streamlook.py`, `page.py`). Name the
   camera in use. With the 183M the live picture is grey; show the filter
   and the sensor temperature beside it. With the 183C, as now.
   Colour stacks come later from LRGB runs.
10. **Checks** (`doctor.py`, `agent.py`). Say which camera and train are in
    use and which profile matched; see the wheel (`1278:0920`) when the
    train has one, and the camera's temperature when it is cooled.
11. **Focus per camera** (`focus.py`). Focus positions, travel and filter
    offsets are kept per camera and train, so swapping back to the 183C
    starts from its own last focus, not the 183M's.
12. **Docs.** README hardware table (both cameras), docs/focuser.md,
    docs/calibration.md, docs/camera-fault.md (the fault belongs to the
    183C), docs/validation.md as each item is proven on the sky.

The first three items were built on 4 November so the 183M can be
used that night; they detect mono and the cooler from the camera itself and
leave the 183C's behaviour as it is. Item 0 follows before anything else is
filed by camera.

## First night, in order

Daylight, indoors or out, before the sky is dark:

1. Everything plugged in through the camera: `lsusb` shows the camera, the
   wheel and the Nano. `./doctor.py --offline`.
2. Wheel: status, then each slot in turn. Write down which filter sits in
   which slot and set the names.
3. Camera opens, the cooler reaches its target, one frame is kept with
   `CCD-TEMP`, `SET-TEMP` and `FILTER`.
4. Focuser moves the whole train out and back without stalling.
5. Focus reaches a far-off object (a mast or hill more than a kilometre
   away): proves the tube mod gives enough inward travel.

Dark:

6. Collimation checked after the mirror moved (Gary).
7. Walk-in focus in L on a rich field; record the position and HFR.
8. Plate solve at 675 mm; check the solved scale is 0.73"/px (1.47 after
   2x2) and set the focal length from the solve.
9. The usual polar alignment and GoTo.
10. Focus offsets for R, G, B, Ha, OIII, SII.
11. A short run in L: frames kept against frames lost, trailed share.
12. Darks at the set temperature for the night's exposures and gains.
13. Flats per filter at dusk or dawn.

Each result goes in `docs/nights/2026-11-04/` and, when it proves a line
above, in docs/validation.md.

## To ask Gary

- The filter slot order, and the narrowband filters' make and bandwidth.
- Which SX wheel it is (7 x 1.25" standard?) and what spacers make the
  55 mm.
- How far the mirror moved, or how much drawtube came off.
- Whether the camera's USB 2 ports are powered from its 12 V supply.

## Sources

1. [Sky at Night review, Hypercam 183M PRO TEC](https://www.skyatnightmagazine.com/reviews/altair-astro-hypercam-183m-pro-tec-4gb-mono-cmos-camera-review)
2. [Altair: Hypercam 183M PRO TEC](https://altairastro.com/altair-hypercam-183m-pro-tec-cooled-mono-20mp-astronomy-imaging-camera-49-p.asp)
3. [APM Telescopes: Hypercam 183M PRO TEC with 4 GB DDR3](https://www.apm-telescopes.net/en/altair-hypercam-183m-pro-tec-monochrome-20mp-astronomy-imaging-camera-mit-4gb-ddr3-ram)
4. [Adorama: SX USB filter wheel, 7 x 1.25" (SXUFW-1)](https://www.adorama.com/sxufw1t.html)
5. [Astroshop: SX USB filter wheel 7 x 1.25" T2-T2](https://www.astroshop.eu/filter-wheels/starlight-xpress-filter-wheel-usb-7x-1-25-t2-t2/p,23748)
6. [SX Mini filter wheel handbook](https://www.sxccd.com/wp-content/files/Mini-Filter-Wheel.pdf); INDI driver `indilib/indi-3rdparty/indi-sx/sxwheel.cpp`
7. [First Light Optics: Sky-Watcher 0.9x coma corrector](https://www.firstlightoptics.com/coma-correctors/skywatcher-coma-corrector.html)
8. [Stargazers Lounge: coma corrector on the 150PDS](https://stargazerslounge.com/topic/276993-coma-corrector-skywatcher-150pds/); [the 150P and prime focus](https://stargazerslounge.com/topic/283434-achieving-focus-with-skywatcher-star-discovery-150p-and-dslr/)
