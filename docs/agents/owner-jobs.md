# The owner's rig: jobs owed

[The owner's rig](owner-rig.md) · [The 19-20 November Dec write-up](../nights/2026-11-19/dec-slack.md)

What is owed on the owner's rig and not yet done, so an agent working
there can pick it up. Read it at the start of a daytime conversation and
before setup; strike a job out (delete it) when it is done, with where its
result is recorded.

## Pictures in progress

Minutes in each filter's best stack on the 183M, as of the night of
22 November 2026 (cloud: one 2-minute SII frame of IC 405, not added). Brought up to date at each night's end; the plan for a
night reads it.

| Target | Ha | OIII | SII | Next |
|---|---|---|---|---|
| IC 405, Flaming Star | 178 | none | 58 | SII under a bright Moon, OIII when the Moon is low or down. No more Ha for now |
| NGC 2174, Monkey Head | 39 | 74 | 48 | Ha, its shortest stack, then SII |

OIII suffers most from moonlight. A narrowband filter's first use in a
queue still needs the wheel moved and `./focus.py --auto` run in it (job 33).

## By day, the owner's hands at the mount

1. **Tube clearance on the west side near the meridian.** Every failed GoTo
   of 19-20 November 2026 was on the west side within about an hour of the
   meridian with the tube near vertical; the owner thinks the tube catches
   the tripod leg there and lowered the scope. The 17 November check
   (`docs/nights/2026-11-17/clearance.md`) passed east of the pier only.
   20 November, by hand: after the tube was lowered, only one position
   lets the tube's back end touch a leg: tube straight up on the east side
   of the mount, against the leg carrying the SynScan Wi-Fi box. Not yet
   checked whether the limits keep a GoTo out of it.
2. **The Dec drive**: Dec moves one way only, and the failing way flips
   with the balance ([dec-slack.md](../nights/2026-11-19/dec-slack.md)).
   Gary (20 November): he did not work on Dec at the 16 November service,
   and it is probably the gears not meshing right. For Gary: the worm
   mesh first, then grub screws on the worm gear, worm end-play, the
   clutch. A hand-rock test first. 20 November, on the main camera
   (`./mount.py dectest`): south moves nothing at all, north sticks then
   jumps 20-50"; west of the meridian neither way moved more than about 17" for 403"
   ([dec-one-way.md](../nights/2026-11-20/dec-one-way.md)).
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
   5.5 × 2.1 DC lead, as SVBONY's box list says, only about 10 cm long:
   too short to reach anything. Leads are needed for the mount, the camera
   and the focuser. Two 1.5 m (5 ft) 5.5 × 2.1 male-to-male
   leads (a twin pack) were ordered on 20 November, due 24 November, for
   the mount and the camera; the focuser's (its socket is 5.5 × 2.5) is
   still to make.
7. **The 183M after a power cut**: a procedure that brings it back without
   the cooler running away. Gary: if the cooler ran with the 12 V out, warm
   it to ambient in software before the 12 V goes back in, then the normal
   slow ramp. Untried: TEC off, set point re-sent, TEC on, before failing
   safe; check whether one bad temperature reading can trip the runaway
   check (18 November 20:40 looked like one).
8. **Dew**: the guide scope's USB dew strap fitted when it comes (due
   4 December; from one of the SV241's USB ports; the plain SV241 has no
   dew outputs). The dew shields from
   Gary (20 November) are not a job: they go on each night at setup
   (`owner-rig.md`).
9. **The skyline survey again** (`./horizon.py --trace`): the tube moved up
   its rings on 17 November and was lowered on 20 November.
11. **The guide camera at full resolution**, cap on: an overnight run of
    the 512 x 960 window (`./guidecam.py probe --size 0 --roi 512x960
    --speed 0 --speed-first --exposures 2 --window 28800`), then 480 x 960;
    binned with the speed set first for 5 minutes; a USB trace (usbmon) of
    480 x 240 at speed 4 against speed 0 (`docs/nights/2026-11-19/guide-camera-window.md`).
12. **Python on the desktop** for `./restack.py --on desktop` (astropy,
    scipy, numpy, Pillow, in `~/telescopeyoke/.venv` there).
40. **Slew in and around the place the motor board garbled its answers**,
    to see whether it repeats there. The first two faults of 22 November 2026
    were west of the meridian with the RA axis at about 309°:
    - 17:43 UT, `'03'`, in findhome, leaving +1 h for the east side: the
      mount stopped at RA axis 308.63°, Dec axis 105.59° (RA 18.83 h,
      Dec +74.41°). Read on the old home, which was 1.04° out in RA and
      8.00° in Dec.
    - About 19:00 UT, `'85=101'`, at the GoTo to Tabby for its R frames:
      hour angle +2.58 h, altitude 63°, about RA axis 309°, Dec axis 134°,
      on the true home. The check that followed erased home and the Dec
      direction.
    - 19:57 UT, an empty answer, in findhome --check: stopped at RA axis
      43.78°, Dec axis 40.42°, east of the meridian. So not only near 309°.
      Garbled answers to read-only questions are now asked again, so a
      repeat no longer ends a run: note how often they come.
    - 20:00 UT, the likelier cause: the laptop's Wi-Fi (2.4 GHz, -71 dBm,
      29 Mb/s) was carrying about 8 Mb/s of upload, and pings to the router
      took up to 1.7 s (2 ms at 17:44). The mount's commands share that radio.
      Of the upload the stream was 3.7 Mb/s (already 720p) and remote desktop
      0.9; the other 4 or so is not identified. Moving the router at 20:21
      gave -63 dBm, channel 1 and about 10 ms. Test by day with the stream on
      and off as well as by place.

    By day, with nothing else asking the mount anything: GoTos into and
    through RA axis 300-318°, at Dec axis 105° and 134° and between, from
    both directions, and the same number elsewhere to compare. Three faults
    do not show that the place is the cause.
41. **The guide camera at switch-on.** On 20, 21 and 22 November it timed out
    on laptop port 1-4 (error -110) until replugged; twice it failed as the
    hub came up with it, and it worked with the hub up first. Try it last in
    the plugging order, then on the SV241.
42. **Is -5 °C enough for the 183M?** `./darktest.py`, cap on, camera and 12 V
    plugged in, about 90 minutes on a rainy night: darks at +5, 0, -2.5 and
    -5 °C. Built 23 November, not yet run on the camera. Only if the noise is
    still falling at -5 does a colder test go to Gary and the owner.

## In code, no hands needed

43. **Leftovers from the ryanclinton.uk session** (24 November, unchecked here;
    after the Tabby freeze work):
    - Repost with `[[images]]` records, as these break a site test:
      `2026-11-20-the-flaming-star-and-a-mount-that-only-goes-one-way.md`
      (`monkey-head-2026-11-20.jpg`), `2026-11-20-the-monkey-head-in-colour.md`
      (`monkey-head-hoo-2026-11-20.jpg`, `monkey-head-sho-2026-11-20.jpg`),
      `2026-11-21-a-pleasant-surprise.md` (`flaming-star-ha-2026-11-21.jpg`),
      `2026-11-22-the-night-the-mount-forgot.md` (`moon-2026-11-22.jpg`),
      `2026-11-23-testing-the-free-tools.md` (topics, and
      `free-tools-ngc2174-graxpert.jpg`, `free-tools-star-removal.jpg`). The
      12 entries from 21 October to 18 November are tagged on the server:
      start from its copy if reposting one.
    - `clouds.py`: `cover` turns NCD into CLR, so take the code from `rawOb`.
    - `compendium.merge()`: NGC 4889 rated 4 (likely the Coma Cluster's), about
      41 galaxies given a group's rating, and LMC added beside ESO 056-115.
    - `data/targets.csv`: the names of IC 434, NGC 253 (and its magnitude) and
      NGC 2070; `build_catalogue.py` takes OpenNGC's first common name.
    - `docs/validation.md`: settle "parked and told" from the 3-4 November run
      records.
    - README: a line linking https://ryanclinton.uk/projects/telescopeyoke/ and
      the diary. Forecasts: Meanwhile is now https://meanwhileinspace.com.

16. **The demo drives the real focuser**: on 20 November `TY_DEMO=1
    ./focus.py --auto` opened the real Nano while `--measure-backlash` was
    using it, broke that measurement and lost the focuser's kept position.
    The demo needs a pretend focuser, or to refuse the real one; until
    then, never run the demo's focus while the focuser is in use.

13. **Automatic recovery from mount faults**: (done 22 November, not yet seen
    working on a real fault: a garbled answer to a read-only question is asked
    again, and one cannot erase home.) Still owed: a command that leaves the mount stopped
    mid-job restarts tracking or says so; trailed stars all the same way
    reported as "not tracking", never "cloud"; a run that loses the mount
    resumes. In the demo first (`TY_DEMO_BOARD`).

20. **An L reference for M31-P8**: P8 has none in L, and the deepest stack
    is the withdrawn v2. `./reference.py M31-P8 --trial` (20 November)
    would keep the 18 Oct 21:43 stack: `./reference.py M31-P8 --make`.

21. **M33's 19 October candidate** (G~15.4, both halves, 1.8" from a
    Cepheid VSX gives as never brighter than 18.57): closed as a known
    variable until 20 November, now unexplained by the new rule. Look at
    its stamps before anything else; its kept vetted.json still says the
    old verdict.

22. **The real/bogus model is stale** (trained on uncommitted code):
    `./realbogus.py train`, minutes of computing, not while imaging.

## In the next clear gap

19. **Collimation** for Gary: 14% off centre, towards the left of the
    frame (20 November).

14. **The guide camera window on a star**: `./guidecam.py star --count 30
    --compare-window`, binned against the full-resolution window, then the
    ST4-pulse comparison before any guider change.
15. **The Dec pile-up cap A/B**: run 20 November with Dec north only
    ([dec-one-way.md](../nights/2026-11-20/dec-one-way.md)): `--dec-stuck
    3` did not stop the jumps. Again only once job 2 is done.

## The filter science: built on 21 November, still to prove on the sky

Each result goes in `docs/validation.md` when it has run on real data, and
its job comes off this list.

26. **Tabby's baseline.** 21 November gave the 183M's first night in L
    (11.879 ± 0.011), B (11.832 ± 0.040), R (11.804 ± 0.019) and G
    (11.880 ± 0.014). 22 November gave the second: L 11.849 ± 0.018, B
    11.802 ± 0.013, R 11.858 ± 0.028, G 11.835 ± 0.039, each within 2 sigma
    of the first. Each band needs three nights before a dip or colour
    change can be judged: `./starwatch.py tabby`, then `--colour`.
27. **`./starwatch.py tabby --colour` from start to finish.** On 21 November
    B and R were finished by hand after the fix that takes both bands before
    stacking, so the command as it now stands has only had a dry run.
28. **Tabby's proposed 1.1% transit.** Next windows from 14 and 16 January
    2027. Before them, `./starwatch.py tabby --transit-reach` must say the L
    nights are steady enough. It compares nights; it has not recovered a
    real 21-hour transit in a time series.
29. **The 183M's L references for M31 and M33.** The patrols' first good
    dark visits make them. Dark, Moon-down evenings with both well up:
    28 November 18:20-20:20, 29 November to 22:00, 30 November to 23:30.
30. **Nova follow-up in R and Ha**, `./patrol.py M31-P4 --characterise
    M31-P4-20261018-225844-001,M31-P4-20261018-233620-003`, on a dark night
    after job 29. Not yet run on the sky. Those candidates were last seen at
    G 17.4 and 18.0, too faint under a bright Moon.
31. **The filters compared fairly.** Every filter has a first depth from
    21 November (half of planted stars: B 15.62, G 15.75, R 15.05, Ha 15.32,
    OIII 16.22, SII 15.81), but from different fields, exposures and sky.
    Ranking them needs the same field on the same night.
32. **L or R for transits**: a whole transit in each on shared nights, then
    `./precision.py SESSION --planet NAME` and `--compare FIELD`. One shared
    night is provisional, two wins are firm. `precision.py`'s mono path has
    not yet run on a real 183M transit.
34. **Mono Moon video.** `./ty moon` and `./ty lucky` failed under the keeper
    on 22 November (`TypeError: cannot pickle 'generator' object`). From
    23 November the keeper streams the frames one at a time, its cooler checks
    going on between them. 23 November, cap on, through the SV241 at USB 3:
    120 and 300 frames (512 x 512, 10 ms, 50 a second) came through the
    keeper, and a normal frame worked after. **Longer videos stall**: "no video
    frame within 5 s" after 1 to 284 frames in all six 600-frame runs with the
    keeper stopped, and once through it, with no USB error in the kernel log.
    Straight into the laptop, six of six finished, and three of three through
    the keeper. With the owner's shorter lead to the SV241, six of six, then
    three 2,400-frame videos (82-88 a second, none dropped) while the guide
    camera took 12 frames each and the wheel turned, with no USB error. So the
    longer lead was the fault. The guide frames (0.5 s) came 1 to 5 s apart:
    look at that with the new lead. **Still owed: video with the sensor held
    at -5 °C**, then this job comes off and goes in `docs/validation.md`.
    **`./ty moon`'s centring** also lost the Moon that night, probably on the
    test moves in Dec (job 2): the disc had to be centred by `--aim-off`.
35. **Mineral Moon from B, G and R** (`./ty lucky capture --filter`, stack
    each, `./ty lucky mineral --mono B G R`), and **a supernova's colour**
    (`./patrol.py TARGET --colour-at RA,DEC`): both built, neither run on
    the sky. The owner chose not to run them on 21 November.
36. **Focus during a run** (`refocus.py`, `docs/focus.md`): built 21 November.
    First triggered on 22 November at 20:40 (the focuser 1 °C cooler), when
    cloud took the stars part way and it went back where it started, so it
    has not yet been seen to improve focus. The next clear run will: read its `focusing again` and `focus:` lines, check the stars
    after it, and record the result in `docs/validation.md`. Its 1.25 width
    and 1 °C triggers are first estimates.
37. **The Moon's filter advice** (`filters.for_moon`): it changes where the
    Moon doubles the sky, from one moonlit L run. Measure it by band as
    moonlit runs come in.
38. **The Omni 1.25" Barlow**, for another night: on the guide scope
    (`docs/autoguiding.md`) and on the 183C for the Moon and planets
    (`docs/lucky-imaging.md`). Check its marking says 2×, and try focus by
    day first. The owner was thinking of sending it back: keep it until then.
