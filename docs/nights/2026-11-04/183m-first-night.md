# 4 November 2026: the 183M mono rig, bench test and first night

The mono train fitted on the 150P that afternoon (docs/mono-upgrade.md): an
Altair Hypercam 183M PRO TEC, a Starlight Xpress 7-slot USB filter wheel
(1 L, 2 R, 3 G, 4 B, 5 Ha, 6 SII, 7 OIII; LRGB parfocal, SHO parfocal) and a
Sky-Watcher 0.9x coma corrector. Train `183m`: 675 mm, f/4.5.

## The tube mod

Gary took the primary mirror out, cut about 10 mm off the bottom of the tube
and moved the mirror about 10 mm up its cell: about 20 mm nearer the
focuser. Focus was reached with the drawtube racked about 2 cm out from
fully in, so 20 mm was enough, with travel to spare inward. He says another
10-15 mm could safely come off if a longer train ever needs it.

## Camera, cap on, indoors and at the telescope

- Reports `AA183MPROTEC` (USB `16d0:0d8c`), firmware 1.5.1, made August
  2020; mono (raw format `YYYY`), whole-frame buffer, USB 3 at 5000 Mbps.
- **Every frame arrived at every readout speed** (`camera_test.py
  --throughput`, 4 x 1 s at speeds 0-3): speed 3 at 1.43 s per 1 s frame,
  grain the same at every speed. Exposure timing exact from 0.1 to 15 s
  (`--timing`); 30 s and 60 s darks arrived. The 183C loses frames above
  speed 0.
- Row stripes 0.48 ADU in a 60 s dark (183C: 1.4-2.4); no amp glow seen in
  60 s at gain 300 (corners as the middle).
- **Offset** (`camera_test.py --offset-sweep`, 0.1 s bias): the offset is
  the dark background in ADU; grain 1.8 ADU at gain 300 rising to 7.9 at
  1800. Set to **80** for the 183M: at least ten times the grain above zero
  at every gain, for 2% of the range. It was not being applied on the
  Altair route until `altair.py` set it on every open (f0598d7): before,
  darks sat at 17 ADU.
- **Cooler** (`camera_test.py --cooler 0`, twice): ramped from 9 °C at
  1 °C a minute, held 0 °C within 0.4 °C on 11-13% of its power (air
  6.6 °C). 60 s darks: 270 hot pixels at 9.2 °C, 79 at -0.7 °C; 194 at
  6.3 °C, 86 at -0.4 °C. Found and fixed: the warm-up was skipped when the
  camera gave no temperature as it opened (f0598d7) and when a reopen
  mid-run cleared the target (d17cf01); the second fix is still to see
  working on the camera.
- The camera's owner, from his use and the forums: run it at **-5 °C**;
  colder gains nothing. Other reports put the point at -10 to -15 °C, with a
  dew spot on the window below -20 °C (Sky at Night's review). Settled that
  night: -5 °C is the target and the floor, so no dark
  ladder below it is planned.

## Filter wheel

`./sxwheel.py` through the camera's USB hub: all seven slots, every position
confirmed, 1.2 s a move, the short way round. It needed `python3-hid`, the
udev rule for `1278:0920`, and the `hidraw` module rather than `hid`
(Debian's `hid` is libusb and could not open it).

## Focuser

The 28BYJ-48 motor could not move the drawtube with the camera, wheel and
corrector on: 320 half-steps out (five moves of 64) and no movement seen.
Focused by hand with the spoken-numbers aid instead: **HFR 2.0 (3.0")** on
Enif in L, 2 s frames.

## Plate solving and polar alignment

- Plate solve scale **1.46" per pixel** on the 2x2 frame, 0.73" native,
  as predicted for 675 mm with 2.4 um pixels.
- Solves first took about 90-107 s each. Cause, measured on one saved frame
  (same hint, same solver): the 3x3 median filter `where_really` ran over
  the whole frame blurred the 183M's small sharp stars; unfiltered the frame
  solved in 0.3 s, with only hot pixels replaced (990 of them) in 0.2 s
  (e9c741e). A wider search now reuses the picture, and each solve prints
  where its time went (36d2c0b).
- Polar alignment from M31, 12° steps: 4.6° off at first (altitude 4.6°
  low), 1.7° after a raise, **1.6°** on a third run (altitude 1.5° low,
  azimuth 0.7° west), left there. The third run took **60 s end to end**
  (each solve 0.2-0.3 s; most of the rest is the two slews and settles),
  against about 6 minutes before the fixes. Logs kept privately.

## The first imaging session, 4-5 November

From the diary notes kept through the night (times UT).

- **Darks, 22:20-22:44:** cooled from 9.9 °C to -4 °C in about 13 minutes
  on up to 20% of the cooler's power; master darks at 4 s and 16 s (gain
  1500, offset 80, -5 °C, 20 frames each), and a bad-pixel map from the
  16 s one. Readout speed 3 fixed in the settings so lights match darks.
- **NGC 281, 23:08-23:55:** GoTo over the pole 2.8° off, centred to 0.8' in
  three solves. Focus in every filter on the field, nothing turned (HFR, L
  usual best 1.77): L 1.92, R 1.75, G 1.94, B 2.32, Ha 2.25, SII 2.33,
  OIII 2.93. Every dither closed the camera, the cooler stopped, and the
  sensor warmed to about -0.6 °C, then took about 4 minutes to re-cool. 21
  L frames before cloud.
- **M33, 00:12-03:40:** L 126 of 181 frames kept in the first block's
  quality pass (2016 s), aligned to 0.24 px, best FWHM 4.7 px, round about
  0.9; the spiral arms and NGC 604 show, the corners darker for want of
  flats. Then R 57, G 98 and B 99 frames of 16 s. Each block change still
  cost 3-8 minutes of re-cooling until the same-target blocks skipped their
  plate-solved re-centre.
- **The colour picture, 03:45-04:30, failed:** with no re-centre between
  blocks the drift carried through them, and each filter's stack sat
  further off (R 330, G 520, B 1070 px): they shared 41% of the frame.
  Fixed in the code (a plain GoTo back at each block's start, then a
  plate-solved re-centre through the kept-open camera); `colour.py` now
  refuses filters that share under 75% (`FRAMES_APART`).
- **The camera kept open (`camera.lend`), 04:08 on:** a plate-solved
  re-centre through it left the sensor at -4.4 °C, against +2 °C and 8
  minutes of re-cooling before; a block change L to R was ready in about
  30 s. M106 (about 29 L frames) and M81+M82 (11 L frames after centring)
  through thickening cloud.
- **05:10:** night ended, the mount parked at home. No dawn flats: the dim
  frames were wrongly put down to dew; the satellite picture
  (`./clouds.py --at`) showed cloud.
- The warm-up after a reopen worked: 3.9 to 7.4 °C, and 7.6 °C, after the
  fix that keeps the temperature cooling began at across reopens.

## Still to do

- Flats per filter at dusk or dawn, with their flat-darks (the darks at
  -5 °C for 4 s and 16 s and the bad-pixel map are done).
- A colour picture with the drift fix in.
- `./corners.py` on a rich field (written tonight, not yet run) for Gary's
  question about the corners and collimation.
- The focuser: the NEMA17 for this train.
