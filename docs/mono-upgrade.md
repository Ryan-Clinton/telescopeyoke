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
| Filters | Optolong L, R, G, B; SII, Ha, OIII (1.25") | Narrowband brand and bandwidth to be confirmed. Seven filters, seven slots: the wheel is full, with no clear or dark position. |
| Corrector | Sky-Watcher 0.9x coma corrector (part 20233) | For f/4-f/6 Newtonians; makes the 150P **f/4.5, 675 mm**; needs **55 mm** (±2) from the bottom of its 2" thread to the sensor [7]. |

## What changes on the telescope

**Tube mod.** The 150P was not designed to reach focus with a camera, and
the corrector plus 55 mm of camera and wheel need even more inward focus.
The usual fix is to move the primary mirror 20-25 mm up the tube and
recollimate [8]; cutting the drawtube is the other way. Done on 4 November 2026: Gary took the primary mirror out, cut about
10 mm off the bottom of the tube and moved the mirror about 10 mm further
up its cell, so it sits about 20 mm nearer the focuser, at the low end of
the usual 20-25 mm. If the first focus shows it is still short, he says
another 10-15 mm can safely come off the tube; the doughnut of a star
with the drawtube fully in gives the shortfall (about 4.5 times its width
at f/4.5). The mirror came out, so collimation is checked too.

**The 55 mm budget.** The corrector wants 55 mm (±2) from the bottom of its
2" thread to the sensor. The chain has to be written down and measured, not
assumed:

| Piece | Optical length | Source |
|---|---|---|
| 183M PRO TEC, flange to sensor | 17.5 mm (to measure: one forum report says 12.5 mm for a 183M Pro) | Altair's spacer listing for Hypercam TEC cameras [9]; [10] |
| SX wheel, T2 to T2 | about 33 mm (to measure) | [5] |
| Filter glass | adds about a third of its thickness (about 0.7 mm for 2 mm glass) | the usual rule for glass in a converging beam |
| Spacers and adaptors | the rest: about 4.5 mm if the figures above hold | measured on the day |

Write the measured chain into the train's settings. Reaching focus in the
middle is not enough: stars in the corners of a full-resolution frame
decide whether the spacing is right (first night, below).

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

The first focus run is the test. A focuser stall then points first at
power, because on 30 October the same motor stalled from a bare laptop
port and lifted from a powered hub, but it does not prove it: the heavier
train's load, the 28BYJ-48's torque and the Nano's driver can each stall it
too. Tell them apart with what is here, one change at a time: the focuser
on its own lead straight into the laptop instead of through the camera's
hub; the wheel unplugged; the move outward (lifting the train) against
inward; and, if a USB power meter is to hand, the voltage at the Nano while
the motor runs. Record which change cured it. A stall that follows the
load, not the power, is the case for the NEMA17.

**The camera fault and the new camera.** The 183C loses frames because it
has no buffer and an ageing board (docs/camera-fault.md). The 183M PRO has
a 4 GB buffer, so it may not have the fault at all. The readout speed and
the lost-frame refusals become per camera: the 183C keeps Speed 0 and its
refusals; the 183M starts at Speed 0 too and is tried faster only after a
full clean night, with the result recorded against the 183M alone.

**The 183C after the tube mod.** With the mirror moved up, the 183C needs
more outward travel or an extension to reach focus. Behind the corrector it
needs its own spacer chain to 55 mm: same sensor, but its body's flange
distance is its own and has to be measured, not taken from the 183M. Without
the corrector it works at 750 mm with an extension tube. Each is a separate
train (below) with its own measured chain.

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
   camera from the SDK. Leave out `BAYERPAT`. The raw frame is kept at its
   full 5440 x 3648, as the 183C's raw mosaics are kept now, so it can
   always be reprocessed. Processing (stacking, searching, the stream)
   works on 2x2 blocks by default, as now, because stars here measure about
   6.4" across (docs/discovery/results.md), eight native pixels; software
   binning on CMOS adds no read-noise gain, it only matches the sampling.
   The processing scale is a setting, so full resolution can be used where
   it pays (corner checks, centroids for timing work), and the choice is
   tested against the measured seeing and the laptop's speed.
2. **Cooler** (`altair.py`, `config.SETTINGS`). Target temperature as a
   setting; `CCD-TEMP` and `SET-TEMP` in every FITS header; the run waits
   until the sensor is within 1 °C of target before keeping frames.
   Altair's own advice is that cooling below about 10-15 °C gains little on
   this sensor [2]. The target is one fixed value for the season so one
   dark library serves, chosen so the cooler can hold it on the warmest
   night expected with power to spare: -5 °C (the camera's owner's figure,
   below), which on 4 Nov 2026 the cooler held 0 °C with 13% of its power.
   - **From the camera's owner (Gary, 4 Nov 2026, from the forums and his
     own use):** run it at -5 °C: colder gains nothing, so -5 is both the
     target and the floor; and cool it
     slowly, the target stepped down over about 20 minutes, never in one
     jump, or the sensor can frost. The setting's lower limit is -5 °C and
     opening the camera starts that ramp from the sensor's own temperature.
   - **Holding it:** record the cooler's power (the SDK's TEC reading, if it
     gives one) and the sensor temperature with every frame. A frame more
     than 0.5 °C off target is kept but flagged and left out of science
     stacks; a cooler at full power that cannot reach target says so and
     the run uses the nearest dark set or stops, never silent mismatches.
   - **Dew and frost:** a cold sensor window can mist. Watch star brightness
     and flat corners for a sudden fall; if it happens, warm a few degrees
     and say so.
   - **Shutting down:** at the end of a run, step the target up a few
     degrees a minute before turning the cooler off, rather than cutting it
     cold, to spare the sensor thermal shock and the window condensation.
3. **Filter wheel command** (`sxwheel.py`). `status`, `move NAME|NUMBER`,
   the filter names as a setting. Protocol from INDI's driver
   (`indi-3rdparty/indi-sx/sxwheel.cpp`): 2-byte HID write, 2-byte reply
   `[current, total]`; `{0,0}` queries, `{f,0}` moves one way, `{f+0x80,0}`
   moves the shorter way; poll every 250 ms until it arrives. Needs
   `python3-hid` (install.sh). `FILTER` card in every frame.
4. **Focal length from the train** (every user of `focal_length_mm`:
   plate-solve scale hints, field of view, the planner's framing,
   `polaris.py`, `moon.py`, `landmark.py`, `focus.py`, `agent.py`,
   `camera_test.py`). Each reads the active train's effective focal length
   and the active camera's sensor, not a single setting, so 750 mm with the
   183C and 675 mm with the 183M are both right.
5. **Filter in the plan** (`shoot.py`, `schedule.py`, the observing plan's
   goals and windows, docs/observing-plan-spec.md). The filter belongs to
   the step's purpose, through the plan that already chooses steps by goal,
   not a separate filter scheduler: discovery patrols in L against same-band
   references; a transit in one filter for its whole window, never changed
   mid-transit; emission nebulae in narrowband; colour pictures in LRGB
   blocks (for example 10 L, then 5 each of R, G, B). Default L, so a step
   that says nothing behaves like today.
   A filter change is one transaction: finish the exposure, move the wheel,
   read back the position, apply the focus offset, let it settle, then
   expose. A frame is only labelled with a filter the wheel has confirmed;
   a failed move stops the step rather than keeping mislabelled frames.
6. **Focus per filter** (`focus.py`, `focuser.py`). Walk-in in L as now.
   The filters come in two parfocal sets (Gary, 4 Nov 2026): L, R, G and B
   focus together, and SII, Ha and OIII focus together. So the offsets are
   kept by set, not by filter: none within a set, and one offset from the
   LRGB set to the SHO set.
   - **Proving it once:** on the first clear night, a walk-in in each of
     the seven filters. Filters in a set that land within the focus
     tolerance at f/4.5 of each other confirm it; one that doesn't gets
     its own offset, and the result is recorded.
   - **The set-to-set offset:** measured at least three times on different
     nights, approaching from the same side so the motor's slack is taken
     up the same way, kept as mean and spread; a spread bigger than the
     tolerance means a walk-in after every change between sets instead.
     Temperature noted with each, so drift can be fitted later.
   After a wheel move and offset, the first frame's star size is checked
   against the last frame in L; worse than tolerance means refocus, not
   carry on. Reset the stored travel and start position after the tube
   mod.
7. **Calibration** (`calibrate.py`, `stacking.py`, docs/calibration.md).
   Darks are filed by camera and matched on everything that changes them:
   temperature, exposure, gain, offset, binning and readout speed. The
   IMX183 has amp glow, so 183M darks are matched, never scaled. The 183C
   keeps its own darks and its "scaled to the night" method for a camera
   with no thermometer. Flats per camera, train and filter, with flat-darks;
   a bad-pixel map per camera. Master frames are versioned and never
   overwritten, and every stack records which masters it used, so a new
   library never changes what an old result meant.
   **It fails closed.** Science work (difference images, photometry,
   transits, depth) refuses a frame whose dark, flat or bad-pixel map is
   missing or does not match, and says which. Uncalibrated frames can still
   be stacked for the stream or a quick look, but that product is labelled
   uncalibrated in its file and on the page and never enters a search. Because the 183M is
   cooled, its darks can be made indoors or on a cloudy night with the cap
   on, never in a clear window.
7a. **Gain and offset** (`camera_test.py`, which already has
   `--gain-sweep`). Before fixing the 183M's defaults, measure read noise
   from bias pairs, full well and dynamic range, and how long a frame can
   be before bright stars saturate, over a few gains and offsets. Altair's
   starting point for the IMX183 (gain 800, offset 50) is where the sweep
   starts, not the answer.
8. **Discovery and photometry** (`difference.py`, `depth.py`, `patrol.py`,
   `transits.py`, `precision.py`). References and zero points are kept per
   camera and band: the 183C's unfiltered colour references stay for nights
   with the 183C, and each patrol field gets a 183M reference in Optolong L
   before its difference images mean anything. A difference image always
   pairs a frame with a reference from the same camera and band.
   Magnitudes are instrumental and say so: the band is named for what took
   it ("L (Optolong), 183M"), the zero point against Gaia G is fitted with a
   colour term measured from comparison stars of different colours, and
   every magnitude carries its uncertainty. Neither L nor the Optolong G is
   Gaia G or Johnson V; a result never calls itself either. Transits in L
   (most light) or R (less scintillation and red-star bias), chosen per
   target, with an ensemble of comparison stars. A candidate nova can be
   checked in Ha, where novae are bright.
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
12. **What every frame records** (`altair.py`, `stacking.py`). Camera and
    serial, train, focal length, filter as confirmed by the wheel, gain,
    offset, readout speed, binning, sensor and set temperature, exposure,
    and the time the exposure really started and ended, in UTC.
    - **Where the time comes from:** the camera's own timestamp if the SDK
      gives one per frame; otherwise the laptop clock read either side of
      the trigger, with the gap between those as the uncertainty. Each
      frame says which (`DATE-OBS`, `DATE-END`, the source and the
      uncertainty in seconds).
    - **The clock:** the laptop's offset from network time is recorded at
      the start of a run; a run for timing work refuses to start if it is
      worse than a set limit.
    - **The shutter:** the IMX183 has a rolling shutter, so rows start at
      slightly different times. The frame says what its time refers to, and
      transit work quotes its timing error from all of the above.
    - **Measured, not assumed:** the delay between trigger and exposure
      start is measured once (`camera_test.py` already has a timing test)
      and written into the camera's profile.
    Calibration masters and software version go into every stack.
13. **Docs.** README hardware table (both cameras), docs/focuser.md,
    docs/calibration.md, docs/camera-fault.md (the fault belongs to the
    183C), docs/validation.md as each item is proven on the sky.

## Later, after the 183M works

In this order, each its own piece of work with its own test:

- **LRGB and narrowband stacking.** Each filter stacked and scored on its
  own, then combined. An incomplete set (cloud during B) keeps what it got,
  and later nights add to the same project. Narrowband composites (SHO)
  are labelled as false colour.
- **Focus that looks after itself.** Refocus on temperature drift and
  after filter changes, notice a focuser stall, and stop rather than keep
  soft frames.
- **The longest useful exposure.** Learned per filter and sky position from
  rejected frames and signal-to-noise, so narrowband exposures are as long
  as the EQ3 can track and no longer.
- **Stream.** Grey live view in L, a colour picture that builds as R, G
  and B arrive, the filter and why it was chosen.
- **Guiding** is its own spec: the guide camera (docs: guide camera,
  29 Oct) is a step towards it, not closed-loop guiding.

## Is it better? Measured, not assumed

The same tests the 183C has already been through, repeated with the 183M,
so the upgrade is judged on numbers. The 183C's baselines, from
docs/discovery/results.md (`depth.py`, planted fake stars, M31):

| Measure | 183C | 183M |
|---|---|---|
| 50% of planted stars found, 8 min (40 x 12 s) | G 17.14 | to measure |
| 50% found, 54 min (202 x 16 s) | G 17.59 | to measure |
| 5-sigma on sky, 54 min | 17.91 | to measure |
| Frames kept, of frames taken | in the night records | to measure |
| False candidates per searched field | in the patrol records | to measure |
| Scatter on a transit's flat part | in the transit records | to measure |

Depth alone doesn't make a better discovery system: a deeper image that
throws up more false candidates can be worse. So the two cameras are
compared at the same false-alarm rate: planted stars found, at a fixed
number of false candidates per field, both measured on the same fields.

The optics change too (675 mm, corrector), so this compares the whole
system, not the camera alone; where a fair camera-only comparison is
possible (the 183C behind the same corrector), it is done too.


## First night, in order

Done on 4 November 2026: [what it showed](nights/2026-11-04/183m-first-night.md).

Daylight, indoors or out, before the sky is dark:

1. Everything plugged in through the camera: `lsusb` shows the camera, the
   wheel and the Nano. `./doctor.py --offline`.
2. Wheel: status, then each slot in turn. Write down which filter sits in
   which slot and set the names.
3. Camera opens, the cooler reaches its target, one frame is kept with
   `CCD-TEMP`, `SET-TEMP` and `FILTER`.
4. Focuser moves the whole train out and back without stalling.
5. Focus reaches a far-off object (a mast or hill more than a kilometre
   away) with travel to spare both ways: record how far inside and outside
   focus the drawtube can still go, not just that focus is reached.

Dark:

6. Collimation checked after the mirror moved (Gary).
7. Walk-in focus in L on a rich field; record the position and HFR.
8. Plate solve at 675 mm; check the solved scale is 0.73"/px (1.47 after
   2x2) and set the focal length from the solve.
9. The usual polar alignment and GoTo.
10. Corners: star size and shape in the four corners of a full-resolution
    frame against the middle. The pattern says which fault it is:
    - all four corners stretched the same way round the centre (pointing
      out from it, or across it): the 55 mm spacing is wrong; which way
      says too long or too short;
    - corners different from each other, one side soft or stretched and
      the opposite side sharp: tilt in the camera, wheel or focuser;
    - stars soft or flared off-centre even in the middle, with a skewed
      pattern across the field: collimation, which Gary checks.
    Fix them in that order of evidence, one change at a time.
11. Focus offsets for R, G, B, Ha, OIII, SII.
12. A short run in L: frames kept against frames lost, trailed share, star
    roundness, and the longest exposure that stays round, against the 183C
    nights.
13. Flats per filter at dusk or dawn; their corners show whether the
    1.25" filters vignette the sensor at f/4.5.

Darks at the set temperature are made on a cloudy night or indoors with
the cap on, not in this clear window.

Each result goes in `docs/nights/2026-11-04/` and, when it proves a line
above, in docs/validation.md.

## To ask Gary

- The narrowband filters' make and bandwidth. (Slot order, from Gary on 4 Nov: 1 L, 2 R, 3 G, 4 B, 5 Ha, 6 SII, 7 OIII; in [filterwheel] filters.)
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
9. [Altair spacer for Hypercam TEC cameras, 17.5 mm sensor-to-flange](https://astroworldtelescopes.com/products/altair-nikon-lens-adapter-spacer-17-5-mm-for-hypercam-tec)
10. [Stargazers Lounge: backfocus for a 55 mm corrector (12.5 mm report for the 183M Pro)](https://stargazerslounge.com/topic/356556-what-else-do-i-need-for-my-55mm-backfocus)
