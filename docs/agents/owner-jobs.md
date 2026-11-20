# The owner's rig: jobs owed

[The owner's rig](owner-rig.md) · [The 19-20 November Dec write-up](../nights/2026-11-19/dec-slack.md)

What is owed on the owner's rig and not yet done, so an agent working
there can pick it up. Read it at the start of a daytime conversation and
before setup; strike a job out (delete it) when it is done, with where its
result is recorded.

## By day, the owner's hands at the mount

1. **Tube clearance on the west side near the meridian.** Every failed GoTo
   of 19-20 November 2026 was on the west side within about an hour of the
   meridian with the tube near vertical; the owner thinks the tube catches
   the tripod leg there and lowered the scope. The 17 November check
   (`docs/nights/2026-11-17/clearance.md`) passed east of the pier only.
2. **The Dec drive**: Dec moves one way only, and the failing way flips
   with the balance ([dec-slack.md](../nights/2026-11-19/dec-slack.md)).
   Gary (20 November): he did not work on Dec at the 16 November service,
   and it is probably the gears not meshing right. For Gary: the worm
   mesh first, then grub screws on the worm gear, worm end-play, the
   clutch. A hand-rock test first.
3. **The balance**, checked and recorded both ways before the next Dec
   test: on 20 November the 700 g of sand at the back came off and the tube
   was rebalanced (the change not recorded).
4. **The Dec drive-response test**: tube on a distant landmark, clutch
   tight: a tape flag on the Dec motor shaft or worm end, a chalk line
   across the Dec axis, `./guidecam.py pulse --seconds 5` one way then the
   other while the owner watches, the main camera on the landmark before
   and after (`moved.py`). Then, only if the drive is sound,
   `./guidecam.py dectest --engage` and `--native` back to back.
5. **The new rear latitude bolt** fitted. The old one rises for a quarter
   to half a turn, then jerks lower. Then start the altitude record in
   `cache/polar_bolts.json` again: its entries disagree with the 13 October
   notes (rear bolt in lowers the axis, front bolt in raises it).
6. **The SV241 power box** (arrived 20 November 2026), tested indoors
   before any night depends on it (`docs/usb-hub.md`, "Bought: the Svbony
   SV241"). Its 12 V outputs are always on, with no software switching
   (only the Pro has it), so the 183M's 12 V still goes in by hand, after
   the camera is warmed in software, never with the cooler running (19
   November 16:31: it ran away to -7.3 °C that way). It came with one
   5.5 × 2.1 DC lead, as SVBONY's box list says: a second is needed for
   the mount and the camera both. A 1.5 m (5 ft) 5.5 × 2.1 male-to-male
   lead was ordered on 20 November, due 24 November.
7. **The 183M after a power cut**: a procedure that brings it back without
   the cooler running away. Gary: if the cooler ran with the 12 V out, warm
   it to ambient in software before the 12 V goes back in, then the normal
   slow ramp. Untried: TEC off, set point re-sent, TEC on, before failing
   safe; check whether one bad temperature reading can trip the runaway
   check (18 November 20:40 looked like one).
8. **Dew**: the guide scope's USB dew strap fitted (from one of the SV241's
   USB ports; the plain SV241 has no dew outputs). The dew shields from
   Gary (20 November) are not a job: they go on each night at setup
   (`owner-rig.md`).
9. **The skyline survey again** (`./horizon.py --trace`): the tube moved up
   its rings on 17 November and was lowered on 20 November.
10. **Darks for the 183M**, cap on, -5 °C: 60 s, then 180 s and 240 s (20
    each).
11. **The guide camera at full resolution**, cap on: an overnight run of
    the 512 x 960 window (`./guidecam.py probe --size 0 --roi 512x960
    --speed 0 --speed-first --exposures 2 --window 28800`), then 480 x 960;
    binned with the speed set first for 5 minutes; a USB trace (usbmon) of
    480 x 240 at speed 4 against speed 0 (`docs/nights/2026-11-19/guide-camera-window.md`).
12. **Python on the desktop** for `./restack.py --on desktop` (astropy,
    scipy, numpy, Pillow, in `~/telescopeyoke/.venv` there).

## In code, no hands needed

13. **Automatic recovery from mount faults**: one garbled motor-board answer
    asked again before giving up; a command that leaves the mount stopped
    mid-job restarts tracking or says so; trailed stars all the same way
    reported as "not tracking", never "cloud"; a run that loses the mount
    resumes. In the demo first (`TY_DEMO_BOARD`).

## In the next clear gap

14. **The guide camera window on a star**: `./guidecam.py star --count 30
    --compare-window`, binned against the full-resolution window, then the
    ST4-pulse comparison before any guider change.
15. **The Dec pile-up cap A/B** (`./guidecam.py guide --minutes 10
    --dec-one-way WAY`, then the same with `--dec-stuck 3`): on hold until
    the Dec drive moves both ways (job 2).
