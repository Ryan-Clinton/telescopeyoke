# Looking for something new: a specification

[Back to the README](../README.md)

Not built. This says how telescopeyoke would become an always-on
discovery station with a telescope attached. On a clear night it hunts with
the telescope; on a cloudy night or by day it hunts spacecraft pictures and
public data; when a survey sees something, it decides whether this rig can
confirm or report it first; and when its methods improve, it searches its
old pictures again. It looks for change, looks up everything it finds, and
asks for another look when that would settle a question. It hands the
person evidence, not guesses. Written 16 October 2026 from the sources at
the end.

## The short answer

A discovery is possible, but only where the big surveys leave gaps. A
150 mm telescope cannot out-search Rubin, ZTF or ATLAS across the sky.
It can compete on cadence, persistence, crowded-field work, place and
speed of reporting. The first telescope programme, and the test of the
whole system, is a nightly patrol of the Andromeda Galaxy (M31) for novae,
with the Triangulum Galaxy (M33) added once M31 works:

- M31 has about 65 classical novae a year (Darnley and others, 2006: a
  range of 50 to 81). Many peak at magnitude 17 to 19, and amateurs still
  find some. Koichi Itagaki found AT 2025abao there at 17.8 on 17 October
  2025.
- M31 is at +41°, outside Rubin's southern survey, but it is not
  unwatched: ZTF covers the northern sky every two nights with public
  alerts in real time. Our edge is looking several times a night, every
  clear night, and reporting fast. A 200 mm amateur telescope has done it:
  George Carey found a nova in M31 at about magnitude 17 in 2015 with a
  four-position patrol against a reference from an earlier night.
- M31 stands high over Ballymoney from October to February. It is 3°
  across, so it is a mosaic, which suits this rig.
- M33 is a second, independent population within reach: its 2025 novae
  were found at magnitude 17.3 to 18.4, by surveys (ATLAS, XOSS) and by
  named individual observers.

Programmes that need no clear sky run alongside, so something is always
hunting:

- **Comets in SOHO pictures (the Sungrazer Project)** for cloudy nights.
  No telescope is needed, and volunteers have found most of the project's
  5,204 comets.
- **Public alerts** from the surveys, searched for transients nobody has
  reported yet, and checked with the telescope when the rig can reach them.
- **Our own old pictures,** searched again whenever the methods improve.
- **Variable stars** from the measurements the patrols keep anyway. A new
  one is likely over a season, but how likely is unknown until we know how
  precise our photometry is in M31's crowded field. Useful, but not the
  "new object tonight" kind of find.

The rig's depth is now measured, not estimated (phase 0, `depth.py`, 16
October 2026), and it is shallower than first guessed: the best M31 stack
so far, 54 minutes of 16 s frames, finds half of the stars planted in it
at G 17.6 and 90% at 17.0. A first guess of 17.5 to 18 in 5 minutes was
too hopeful. Novae near their peak (16 to 18) are still within reach;
the fainter half of them are not.

The project has an objective finish line. Can telescopeyoke:

1. recover fake transients planted in its own frames?
2. recover known M31 novae from its own data?
3. produce a candidate packet a professional would trust?
4. flag a source nobody has reported, before somebody else does?

When it can do all four, "AI discovery tool" is a description, not
marketing. The discovery still belongs to the person who reports it.

## What the rig can reach

| | |
|---|---|
| Telescope | Sky-Watcher 150P, 750 mm, f/5 |
| Camera | 183C, 2.4 µm pixels: 0.66″ a pixel, 1.0° × 0.67° field |
| Mount | EQ3 Pro GoTo, tracking unguided |
| Depth | **Measured** on the stacks of 6 to 16 October 2026 (below) |
| Sky | Ballymoney, 55° N. M31 passes 14° from the zenith |

The surveys we are up against, and where they stop:

| Survey | Depth | Sky | What it leaves |
|---|---|---|---|
| ASAS-SN | g ≈ 18.5, nightly | whole sky | complete only to about 16.7 at peak; crowded galaxy centres are hard for its 8″ pixels |
| ZTF | deeper than ours | northern sky every 2 nights; real-time public alerts. Its Bright Transient Survey takes spectra of almost every non-Galactic transient brighter than 18.5 | nights between its visits, crowded centres; its current run (ZTF 3) is scheduled to 31 December 2026 |
| Rubin (LSST), started 30 June 2026 | far deeper | **southern sky only** | M31 and the far north; it saturates near magnitude 16 |
| Professional M31 nova patrols (Ondřejov and others) | deeper than ours | M31 | weather and gaps; a clear Ulster night when Europe is cloudy |

## The other hunts, and why they wait

| Hunt | Odds of a first | When |
|---|---|---|
| Novae in M81 | low for this rig: they are found near magnitude 20, one in 2025 at 19.8 in a 3000 s stack on a 0.65 m telescope | not yet |
| Supernovae in bright galaxies | low per field: ASAS-SN finds most bright ones within a day, and amateurs who still win image hundreds of galaxies a night with 0.35 to 0.6 m telescopes. ZTF's Bright Transient Survey covers the northern sky every 2 to 3 nights to 18.5, so bright northern supernovae are a crowded race. They can be bright: Koichi Itagaki found SN 2023ixf in M101 at 14.9 | through every session searched, below; no dedicated patrol |
| Galactic novae | low with the 150P's 1° field; they are found with camera lenses covering the Milky Way (John Seach, Tadashi Kojima, 2025) | no: not a telescope's job |
| Exoplanets in TESS data | open to volunteers: Planet Hunters TESS invites it, and NASA's open-source ExoMiner++ flagged 7,000 TESS candidates on its first run | no: another telescope's data, not this one's |
| Known exoplanet transits, timed with the 150P | a hot Jupiter dims its star by 1 to 3% for 2 to 3 hours; ExoClock collects amateur timings for ESA's Ariel mission, and a transit early or late hints at another body | yes: `transits.py` |
| Asteroids and comets through the telescope | very low for discovery; good for recovering known ones | a later programme, `moving.py`, below |

The EQ3 has caught on the mount before, so a patrol of 100 galaxies a
night is the wrong job for it.

## Making a discovery as likely as possible

The odds come less from any one algorithm than from hunting on many
channels at once and answering faster than a person could alone.

| Channel | When it hunts | Telescope |
|---|---|---|
| M31 and M33 novae | clear nights, October to February | yes |
| Sungrazer comets | all the time | no |
| Public alerts, for unreported transients | all the time; confirmed on clear nights | sometimes |
| Every science picture taken | after every session | yes, already |
| Our old pictures, searched again | whenever a method improves | no |
| Variable stars | from data already held | no |
| Exoplanet transits | a clear night with a transit due | no |

### A discovery scheduler, not a target list

`tonight.py` ranks what is nice to look at. Discovery needs a different
score: the chance of a first find per minute of telescope time.

```math
P_{\text{first}} = P_{\text{event}} \times P_{\text{detect}} \times P_{\text{not yet found}} \times P_{\text{first report}}
```

For a patrol field the working form is

```math
\text{priority} \propto \frac{\text{event rate} \times \text{completeness} \times \text{cadence debt}}{\text{minutes needed}}
```

- **Event rate** for each M31 panel comes from where novae have been
  found: the bulge has the higher rate (38 a year against 27 for the disc,
  Darnley and others), so the map of past nova positions is the prior.
- **Completeness** is the injection-and-recovery figure for that panel
  and that night's conditions. The crowded bulge may have the most novae
  and the worst completeness, so multiplying the two gives a map of
  *detectable* novae. The best panel may not be the nucleus, and on a poor
  night four panels may beat eight.
- **Cadence debt** is the time since each field's last good frame. The
  longer a field goes unwatched, the more may have happened in it.
- A public alert that is setting soon, or a candidate needing a second
  look, can outrank the patrol. The scheduler says why: "M31 is due, but
  an unreported 16.8 transient sets in 45 minutes; observe it first."

The plan it makes is a proposal; the person approves it before anything
moves.

### Cadence before depth

The exposure for each panel is not fixed at 5 minutes. Injection and
recovery run at 60, 120, 180, 300 and 600 s, to find where more depth
stops paying for fewer visits. Novae rise fast: M31N 2026-04c was 16.2 when
found and fainter than 18.4 two days before. Looking often may matter more
than going half a magnitude deeper.

### From candidate to report in under five minutes

TNS names as the formal discoverer "the reporter/s whose discovery report
first turns to public", and a report needs discovery photometry (mandatory)
and the last non-detection, or archival information in its place. So
everything a report needs is kept ready before anything is found:

    position and its uncertainty
    UTC time of discovery
    magnitude, uncertainty and passband
    the 5-sigma limit of the frame
    the last non-detection and its limit
    the reference's date
    science, reference and difference FITS
    a finding chart
    the asteroid, VSX, SIMBAD, TNS and Gaia checks
    the number of independent frames it is in

Every figure in the packet says what kind of figure it is:

| Label | Meaning | Example |
|---|---|---|
| measured | from our own frames | magnitude 17.42 ± 0.08 |
| inferred | worked out from measurements | rising 0.7 mag an hour |
| estimated | a model or a guess, not yet measured | the rig's depth before phase 0 measured it |
| simulated | from planted fakes | 90% recovery at 17.8 |
| reported | from someone else | a ZTF detection, a VSX entry |
| not known | asked and not answered | no spectrum yet |

The same labels go on the candidate page and in `ty candidates --json`,
so nobody reading a packet mistakes a guess for a measurement.

The target: from a confirmed candidate to a packet a person can review in
under five minutes, timed on planted fakes. The person still presses send.

### Public alerts, for unreported transients

Fink enriches the public ZTF alerts with TNS, SIMBAD and other catalogues
and offers filtered streams. `brokers.py` would watch for alerts that are
likely real, bright enough for this rig, have no TNS entry, no SIMBAD,
asteroid or variable-star explanation, are observable from here now, and
are brightening. Then:

    Unreported transient candidate
    ZTF detection 17.2; no TNS object within 5"
    58° high now; the rig should reach it in about 3 minutes
    Recommended: confirm now.  [approve]

Credit is honest about where the pixels came from. A TNS discovery
certificate shows a Reporting Group and a Discovery Data Source separately
(for AT 2026acrv both are ZTF). A transient first seen in ZTF data and
reported by us is reported with ZTF as the data source; it is not "my
telescope discovered it". Our own confirmation picture is then follow-up.

### Old pictures, searched again

Every time the subtraction, the star fitting, the classifier, the depth
measurement or the forced photometry improves, every stored frame is
searched again (`./difference.py --all-history`). Professionals do find
things this way: M31N 2022-10c, a possible symbiotic nova, was found in a
search of 2022 archive frames, with earlier detections back to 2020.

### Several rigs together, in the long run

GOTO's many telescopes reported 6,703 transients in 2025 and were first to
find 2,557; volunteers found 48 of those. The principle scales down. If
other people run telescopeyoke, a shared list of fields and when each was
last observed would let a clear site take the next M31 pass when Ulster is
cloudy, and a candidate here could ask another rig to confirm it. This
needs other users first, and an agreed way to share; it is the furthest-off
part of this plan.

## How it is built: seven layers

Professional transient systems are not one clever classifier. They are
layers: ZTF's pipeline for the pictures, Fink for enriching and
classifying alerts, SkyPortal and Fritz for candidate pages and follow-up.
telescopeyoke takes the same shape, much smaller.

| Layer | Job | Where |
|---|---|---|
| Observe | choose and take the night's science frames | `programmes/`, `patrol.py`, existing `shoot.py` and `mosaic.py` |
| Measure | astrometry, photometry, depth, star size, sky for every frame | `depth.py` (built), existing `solve.py` and `stacking.py` |
| Detect | proper image subtraction; moving sources | `reference.py`, `difference.py`, later `moving.py` |
| Vet | drop artefacts and known objects | `vet.py` |
| Enrich | catalogues, TNS, VSX, SkyBoT, our own earlier frames | `vet.py`, `forced.py` |
| Reason | rank what is unusual; propose the observation that would settle it | the agent, through `ty candidates` |
| Act | ask to re-observe, tell the person, draft a report | `report.py`, the status page |

Who does what:

- **Ordinary code** does calibration, astrometry, star-shape fitting,
  photometry, subtraction, significance, track finding, catalogue
  matching and rejecting known objects.
- **A small trained classifier** scores real against bogus, and later
  ranks candidates. It is trained on our own labelled cut-outs.
- **The language model** explains the evidence, checks outside sources,
  proposes which observation would tell the possibilities apart, plans
  the night within the safety rules, and drafts reports. It never decides
  whether a smudge in the pixels is astrophysical.

### Programmes, not special cases

M31 is the first programme, not the architecture. Each programme is a file:

    programmes/m31-novae.toml
    programmes/m33-novae.toml
    programmes/variable-stars.toml
    programmes/sungrazer.toml
    programmes/public-alerts.toml

Each names its fields (for M31, `mosaic.py`'s panels), cadence, exposure,
reference, detection settings, catalogues to check, and follow-up policy.
No code says `if target == "M31"`, so M33 now and others later need only
a new file.

### Observe: `patrol.py`

    ./patrol.py m31-novae --plan    panels, order, exposures, expected depth; moves nothing
    ./patrol.py m31-novae           runs the plan through shoot.py

- M31's fields are `mosaic.py`'s panels, kept in `mosaics/M31.json` as
  targets M31-P1, M31-P2 and so on. About 2 × 4 panels cover the disc
  and the bulge (`./mosaic.py M31 4x2 --replace`). Keeping the centres
  fixed lets each night be compared with the last.
- Each panel: about 20 × 15 s frames, short enough that the core does not
  saturate. Frames go where they already go, `frames/M31-P1/` and so on.
- Moves the mount only through `mount.py`, refuses under `MOTION_LOCKED`,
  and is started by the person, like any run.

### Measure: every frame knows its own depth

One depth for the rig is not enough: tonight may reach 18.3 and tomorrow
17.1. Every stack gets a record like this:

    limiting_mag_5sigma  18.14
    seeing_fwhm          3.1"
    sky_background       ...
    transparency         ...
    stars_used           147
    zeropoint            22.37 ± 0.04

calibrated against Gaia stars in the field. A non-detection then means
something: "absent at 21:12, fainter than 18.2", not "not in the earlier
picture".

**Injection and recovery** measure what the pipeline can find. Fake stars
are planted at 16.0, 16.5 and so on to 19.0, in the bulge, the disc,
blank sky and beside bright stars, and the share recovered is counted.
The result is a curve for each region, for example:

    M31 outer disc   90% recovered at 17.8, 50% at 18.3
    M31 bulge        90% recovered at 16.9, 50% at 17.5

(those figures are invented to show the form). This runs again whenever
the camera, the optics or the subtraction change.

### Detect: proper image subtraction

Subtracting one picture from another leaves residuals around bright
stars, the nucleus, gradients, mismatched star sizes and small
registration errors. M31's bulge has all of these. `difference.py` uses
proper image subtraction (ZOGY: Zackay, Ofek and Gal-Yam), the method
ZTF uses. It takes the new and reference images, a variance map for each,
and each one's star shape. It returns a significance image, the difference
flux, the difference star shape and a mask of candidates. photutils
supplies star-shape fitting that copes with crowded fields.

`reference.py` builds each field's reference by proper coaddition of our
best nights (the first clear nights of the season go on this). It can
fetch a Pan-STARRS cut-out through CDS hips2fits for a first night with no
reference of our own. References are kept, with a version, under
`config.DATA/reference/`.

### Candidates are objects, not nightly blobs

A detection is not an object. Each candidate is kept in a small database
under `config.DATA/candidates/`, and a later detection at the same place
joins the same candidate:

    candidate C20261016-003
    position, first seen, last seen
    detections and non-detections (with each night's limit)
    light curve, motion
    catalogue matches
    reference, new and difference cut-outs
    scores, the person's verdict, follow-up history

How a candidate changes is evidence: rising over three nights then
fading looks like a nova.

**Forced photometry** (`forced.py`). Once something is found, its
position is measured in every earlier frame of that field, including
those where nothing was detected. "Not detected, not detected, detected"
can become a rising light curve with a limit on the last night it was
fainter.

### Vet and enrich: an evidence record, not pass or fail

Each candidate gets a record, and is ranked on it:

    Detection significance     11.4σ
    Independent frames         14 / 16
    Star-shape similarity      0.94
    Edge distance              safe
    Near saturation            no
    Flux in reference          none
    Known asteroid (SkyBoT)    no
    Known variable (VSX)       no
    Already reported (TNS)     no
    Gaia or SIMBAD source      no
    Motion                     < 0.2″ an hour
    Host                       M31 disc
    Earlier night (forced)     18.4 ± 0.3
    Now                        17.1 ± 0.1

The checks are those of the first draft: present in at least 3 separate
frames (hot pixels on the uncooled camera, cosmic rays and satellites fail
here); star-shaped; not beside a bright star or an edge; not a known
asteroid (the IMCCE SkyBoT cone search for that time and place); not a
known variable; not already reported (TNS and the Rochester list of M31
novae); still there later. Each result is kept with the query and its
time.

### A real-or-bogus classifier, learned from our own frames

Every dismissal is labelled (hot pixel, edge, bad subtraction, satellite,
cosmic ray, bright-star halo, cloud or tree, real star) and its cut-outs
kept. After a few hundred labels from this camera and these optics, a
small classifier is trained on the science, reference and difference
cut-outs, the star shape, significance, edge distance and saturation. Its
answer is a probability, "real: 97%", never "nova confirmed". Expert
review stays: automated outlier detection alone throws up mostly bogus
candidates. Its effect is measured as the fall in false candidates it
brings.

### Reason and act: the next observation

Most software stops at "candidate detected". telescopeyoke owns the
telescope, so it can ask which observation would best tell the
possibilities apart:

    Stellar, stationary, unknown, 17.4, on M31's disc.
    Possibilities: nova, variable, subtraction artefact.
    Best next: repeat this panel for 5 minutes now.

then, with 16 independent frames in hand:

    Best next: again in 40 minutes, to see if it is brightening.

and, if filters are ever fitted, a g and r pair for colour. The agent
proposes; **the person approves each move**. A re-observation is a slew,
and the mount moves only when asked (CLAUDE.md), through `mount.py`, never
under `MOTION_LOCKED`.

### Every picture is searched

Discovery is not only for patrol frames. Once a field has a reference,
every ordinary session (M27, M81, M51, NGC 7331 and so on) is subtracted
and checked after `restack.py`. The morning answer is "nothing unusual in
last night's 4 fields" or "one unexplained candidate near NGC 7331". This
is how supernovae in bright galaxies get looked for without a dedicated
patrol.

### Public alerts: `brokers.py`

Alert brokers such as Fink and ANTARES sort the surveys' alerts and pick
out ones worth following. Besides the search for unreported transients
above, `brokers.py` asks of each alert: is it above our skyline tonight,
bright enough for this rig, better value than tonight's planned target,
and do we have a reference? Then: "AT xxxx is 54° high at 22:15 at about
16.7; the rig should reach it. Take a confirmation picture?" With the
person's yes, the patrol pauses, the transient is imaged, and the patrol
resumes. RTS2 shows the observatory side of this (scheduling, weather,
targets of opportunity), and its complexity is not needed here.

**Built 17 October 2026, first part.** `./brokers.py` asks ALeRCE (Fink's
API did not answer that week; both carry the same ZTF alerts) for the
objects first seen in the last few days that its stamp classifier calls a
supernova, keeps those up in the dark here tonight for half an hour or
more and at or brighter than `--brighter` (17.5 by default), and names any
that the Rochester lists already have. The Transient Name Server wants a
key even to be searched, so it is not asked: each answer carries its TNS
search link for a person. Its first run, on 17 October, was given 66
objects from ten days: 35 were not up here and the other 31 fainter than
17.5, so nothing to point at. ALeRCE's newest ZTF detection near M31
was on 27 June 2026 (asked on 17 October), so ZTF says nothing about M31
this autumn, for or against a candidate of ours.

**The month's search, 17 October 2026.** `./brokers.py --unreported`
looks back 30 days, keeps what is bright enough whether it is up here or
not, and lists what is on neither Rochester list. It also leaves out what
ZTF's own deep-learning real-or-bogus score (drb) calls bogus on every
detection, as the stamp classifier calls some ghosts beside bright stars a
supernova. Its first run: 292 objects, 290 fainter than 17.5, 2 left. One
was a ghost 3.8" from a G 12.4 star (drb 0.0; ALeRCE's newer classifier:
bogus, 0.99), which the score now removes. The other, ZTF26acaznbf, was
real: r 16.7 twice, 6.6 minutes apart on 9 October without moving, 12.6"
from the middle of the galaxy NGC 3441, with nothing in Gaia within 36".
The Transient Name Server's page, read by a person's browser, has it as
**AT 2026aexm**, reported by ALeRCE's bot the same day as a possible
supernova and not yet classified. So the search works, and the lesson is
the expected one: the Rochester lists leave out most transients nobody
has classified, and only the Server can say a thing is unreported. From
the garden it is too low before dawn for now (about 18° when full dark
ends at 06:00, behind the eastern skyline), better each week into
November: the first real public transient to point at. Not yet built:
the confirmation picture on a person's yes, and pausing the patrol for it.

### Moving objects, later: `moving.py`

Tycho Tracker shows what amateur software does for moving objects:
synthetic tracking, stacking many short frames along a grid of possible
motions so a faint mover shows up without its motion being known. A later
`moving.py`: 50 short frames, stationary stars removed, a velocity grid,
synthetic stacks, tracklets, and a match against SkyBoT. Recovering known
asteroids first makes it a science programme of its own; discovery is the
long shot.

### Sungrazer: cloudy-night mode

    ./sungrazer.py fetch            the latest LASCO C3 and C2 pictures
    ./sungrazer.py look             candidates, as a movie and a list

It runs all the time, day and night, whatever the weather. Background
removed; moving points found; tracklets scored for steady, near-straight
motion and steady brightness; checked against comets already reported; stars and cosmic rays rejected; each candidate
shown as a short movie for a person to watch. The project's guide asks
reporters to view frames in sequence, confirm the object is a comet, and
report its pixel positions and times through the project's form under
their own name. Before fetching automatically, ask the project, and keep
the rate low. A candidate reaches the person as: "possible unreported
comet, 91% track consistency, in 6 consecutive C3 frames, straight
motion, not in the reported list [watch] [dismiss] [open the report
form]". It may well be the likeliest credited discovery, but the headline
stays "the telescope found a new source in the sky".

**Built 17 October 2026, by hand.** `./sungrazer.py fetch` and `look`
(with `--until` for a day in the past) do the above except the check
against comets already reported, which a person makes from the project's
list. Motion is measured per 12 minutes from each picture's own time, as
the archive has gaps. Two tests on archived C3 pictures: the bright
C/2024 G3 (ATLAS) on 13 and 14 January 2025 was found, its head and tail
the strongest candidates, alongside the bleed line from its saturated
head; the faint Kreutz comet SOHO-5175 on 25 January 2025 was not, on a
day crowded with outward-moving coronal material.

**Raw pictures, GOES-19, and planted comets, 17 October 2026.**
`--raw` takes LASCO's level-0.5 FITS files instead of the JPEGs (the
archive at umbra.nascom.nasa.gov/pub/lasco_level05/, or the last
fortnight's while it catches up), and `--camera ccor1` the Compact
Coronagraph on GOES-19 from NOAA's open archive on Amazon's S3. The
Cambridge list of SOHO comets shows why CCOR-1 matters: in 2026 nearly
every new comet has been found in it (G1), a handful in LASCO. The noise
is now measured in each 64-pixel square, as the inner corona is far
noisier than the edge. `look --plant 120` puts fake comets heading in
towards the Sun into the real pictures, with their real noise and
outflows, and counts them back:

| Pictures | Found at 3, 4, 6, 8 and 12 times the noise (of 20 each) |
|---|---|
| LASCO C3 JPEGs, 15 September 2026, 161 | 8, 17, 20, 20, 20 |
| LASCO C3 raw, the same hours, 161 | 1, 15, 20, 20, 20 |
| CCOR-1, 11 and 12 October 2026, 116 | 3, 8, 15, 18, 20 |

"Times the noise" is each picture's own noise, so the rows say how well
the search works on each kind of picture, not which kind goes fainter:
that needs the same comet measured in both. CCOR-1's first try found its
occulter's arm instead (blanked to 0, its edges flickering), now left
out. The raw pictures of 25 January 2025 give nothing heading for the
Sun either: SOHO-5175 is a Meyer-group comet (Y on the Cambridge list),
small and faint, and without its positions a miss cannot be told from
a comet not moving that way. In CCOR-1, after the arm, nothing heading for the Sun was found in the 30 hours
that held the 12 October CCOR-1 comet, and the project's own pages, with
its positions, would not answer from here to say where it was.

**A real faint comet found, 17 October 2026.** On 15 September 2026, the
day a Kreutz comet was found in C3, both the JPEGs and the raw pictures
give one object moving steadily in towards the Sun, about 2.3 pixels in
12 minutes, from 07:30 to after 20:00 UTC (in the JPEGs from (933, 759)
at 10:30 to (806, 672) at 23:54), the strongest candidate in both. No
planet was in the field that day. It is very likely that comet; until
the project's positions say so, it is not proven. It is not run all the
time for LASCO: the project is to be asked first. CCOR-1's archive is
NOAA's open one, meant for such use, so `./sungrazer.py hunt --install`
runs the CCOR-1 hunt every 6 hours as a systemd user timer: the last
day's pictures, only what heads in towards the Sun kept in
sungrazer/hunt-ccor1.json, pictures over 3 days old deleted.

### The candidate page

On the status page, one page per candidate, a small version of SkyPortal's:

    CANDIDATE C20261207-004
    real (classifier)     96%
    unknown               yes
    stationary            yes
    first detected        22:13:17
    magnitude             17.42 ± 0.08
    limit that night      18.31
    host                  M31

    [reference] [new] [difference]   side by side, or blinked
    light curve, with limits
    checks: 11 frames, star-shaped, no asteroid, no VSX, no TNS,
            not near saturation, still there 43 minutes later
    assessment: a stationary new point source on M31's disc; nova
                plausible, variable or background transient possible
    recommended: observe again now for 5 minutes

    [re-observe]  [dismiss, with a label]  [draft report]

`ty candidates --json` gives the same, read-only, for an agent asking
"anything new last night?". Its schema goes in `schemas/` and its tests
in `tests/test_interface.py`.

### The science ledger

"The AI thought it saw something" is not science. For each candidate the
ledger keeps: the original FITS frames, the calibration masters, the
reference's version, the subtraction's version, the software commit,
every catalogue query with its time, the measurements, the classifier's
version, the person's decisions, follow-up frames and report drafts.
Anyone can then rerun the chain.

### `report.py`: a draft, never a send

Drafts the TNS report (position, time, magnitude, the limit before, the
reference used) and the matching note for CBAT and the BAA. Nothing is
sent by the software. The person sends it, under their own name, from
their own account.

### The evening plan and the morning summary

At dusk, alongside `tonight.py`:

    Clear 21:40 to 01:10.
    M31 not patrolled for 3 nights; well placed until 00:20.
    8 panels, 46 minutes, expected depth about 18.1.
    Public alert AT xxxx observable, likely within reach; time-critical.

    21:45  transient confirmation
    22:00  M31 patrol
    23:05  repeat any M31 candidates
    23:25  variable-star follow-up
    00:10  second transient picture

    The mount moves only when you approve the plan.

In the morning:

    8/8 M31 panels done. Limit 17.9 to 18.3.
    12,481 sources measured, 37 subtraction detections,
    34 artefacts rejected, 2 known variables.
    1 unexplained candidate.  [open]

## Phases

Ordered by what most raises the chance of a discovery soonest. Each phase
ends with a scientific proof, not just working code.

| Phase | Build | Proof |
|---|---|---|
| 0 | Depth and completeness: `depth.py`, planted fake stars, at 60 to 600 s | a recovery curve for each M31 region and exposure. **Built 16 October 2026;** results below |
| 1 | References, calibration, proper subtraction, the candidate database, vetting and forced photometry for M31. **Software complete, 16 and 17 October 2026: all of it built and tested. Scientific validation under way: realistic fakes measured, a real nova recovered from archive images (AT2024koe); a find of our own still to come** | planted fakes recovered; a planted rising fake gets the right light curve; a known asteroid and a known variable set aside |
| 2 | The M31 patrol, scheduled by priority. **Built 16 and 17 October 2026: `patrol.py` for one field or M31's 4 x 2 panels, ordered by novae reported x share caught x days unwatched, fitted to the night; each panel's first night becomes its reference. Proof to come: a known nova recovered** | a known nova, past or current, recovered from our data |
| 3 | M33 | a first M33 night with its completeness measured |
| 4 | Sungrazer, running all the time. **`sungrazer.py` built 17 October 2026. A bright comet (C/2024 G3) found in archived pictures; raw LASCO and GOES-19's CCOR-1 added, fakes planted to measure the search; the 15 September 2026 Kreutz comet very likely found; CCOR-1 hunted every 6 hours (`hunt --install`)** | a known comet recovered in archived pictures |
| 5 | The report packet. **`report.py` built 17 October 2026: 95 s for a real candidate** | under five minutes from a confirmed planted fake to a packet |
| 6 | Public alerts (`brokers.py`). **Built 17 October 2026: ALeRCE's new transients, bright enough and up here tonight; the month's search run (its one real find was AT 2026aexm, already on the Transient Name Server)** | a real public transient observed; an unreported-transient search run over a past month of alerts |
| 7 | Every session searched; old frames searched again on each improvement. **Built 17 October 2026: each new stack of a field with a reference is searched in the background; `patrol.py --sweep [--all-history]` for the rest** | every science picture checked automatically; a rerun finds fakes planted in old frames |
| 8 | Real-or-bogus classifier; proposed follow-up. **Dismissal labels kept from 17 October 2026 (`candidates.py --dismiss`)** | a measured fall in false candidates; a candidate leads to a useful repeat |
| 9 | Variable stars, dippers like Tabby's star, and known exoplanet transits timed with the 150P. **Built 17 October 2026: `variables.py` (light curves from batches of each night's frames, against VSX, with any dip flagged), `starwatch.py tabby` (a nightly look at KIC 8462852, warning of a dip) and `transits.py` (tonight's whole transits from NASA's Exoplanet Archive; the depth and timing fitted from a night's frames)** | a first VSX submission; a transit timed against its prediction |
| 10 | Several telescopes together: other people's telescopeyoke rigs sharing fields and confirming each other's candidates. **Needs other users first** | a candidate confirmed by another telescope |

Phases 0 to 2 run through the 2026 to 2027 M31 season if the weather
allows. Sungrazer needs no sky and can be built any cloudy week.

## What phase 0 measured

`depth.py` plate-solves a stack, matches its stars to Gaia DR3 for the zero
point, works out the 5-sigma limit from apertures dropped on empty sky, and
plants copies of the stack's own stars at G 13 to 19.5 to count how many the
star finder gets back (the brightest in rounds of their own, so their light
does not hide faint ones beside them). The 90% and 50% figures are of the
stars not lost by landing on a real one; that loss, 2 to 5% in these
fields, is crowding, given separately. Magnitudes are **unfiltered,
calibrated approximately to Gaia G**: the camera's colour response is not
G's, so a red or blue star can be off by a few tenths; a colour term from
Gaia's BP-RP is for later, before anything is reported. Measured on 16
October 2026 with the same code throughout:

| Stack | Frames | Stars | Sky (mag/″²) | 5σ on sky | 90% found | 50% found |
|---|---|---|---|---|---|---|
| M31, 13 Oct, 54 min | 202 × 16 s | 6.4″ | 19.1 | 17.91 | 17.02 | 17.59 |
| M31, 13 and 14 Oct, 95 min | 358 × 16 s | 6.4″ | 19.0 | 17.92 | 17.01 | 17.61 |
| M31, 14 Oct, 44 min | 164 × 16 s | 6.6″ | 18.7 | 17.71 | 16.83 | 17.30 |
| M31, 13 Oct, 8 min | 40 × 12 s | 6.2″ | 19.1 | 17.19 | 16.61 | 17.14 |
| M31, 6 Oct, 30 min | 120 × 15 s | 7.9″ | 18.8 | 17.22 | 16.50 | 17.10 |
| M33, 16 Oct, 24 min | 145 × 10 s | 6.1″ | 18.6 | 17.28 | 16.92 | 17.24 |

(The first night's M31 stack, 165 frames of 1 s, would not plate-solve.)

**How much a longer visit buys** (`depth.py --sweep`: the first 60 to 600 s
of the 13 October session, each stacked and measured the same way):

| Stack | 5σ on sky | 90% found | 50% found |
|---|---|---|---|
| 64 s (4 frames) | 16.46 | 16.06 | 16.34 |
| 128 s (8) | 16.77 | 16.40 | 16.72 |
| 176 s (11) | 16.88 | 16.54 | 16.76 |
| 304 s (19) | 17.08 | 16.59 | 16.97 |
| 608 s (38) | 17.29 | 16.80 | 17.20 |
| 3232 s (202) | 17.91 | 17.02 | 17.59 |

**A stack made for faint stars** (`restack.py --discovery`): every frame
that passes the checks, each weighted for a faint star's signal-to-noise,
transparency / (noise² x star width²), the poorest left out wherever they
would lower it (`stacking.point_weights`):

| Frames | Picture's stack, 50% found | Discovery stack, 50% found |
|---|---|---|
| 13 Oct | 17.59 (202 frames) | 17.55 (238) |
| 13 and 14 Oct | 17.61 (358) | 17.59 (421) |

What it says:

- **Within a night, time buys depth**, about 0.2 to 0.3 mag a doubling:
  17.0 in 5 minutes, 17.2 in 10, 17.6 in 54.
- **A second night bought nothing**, and neither weighting nor choosing the
  frames won it back: the 14 October frames had a brighter sky (18.7
  against 19.1) and slightly wider stars, but even the frames chosen and
  weighted for faint stars left the stack at 17.6. The noise in empty sky
  did not fall either (17.91 for 54 minutes, 17.92 for 95), which random
  noise would: something that does not average away sets a floor. The
  likeliest cause is the camera's own pattern. These frames had a bias
  frame only, no darks or flats, the frames drift only a few pixels in a
  session, and the difference images (phase 1) show vertical striping.
  **Dark frames, flats and dithering come before more hours.** That is a
  hypothesis until a session with them is measured the same way.
- **Star size matters as much as time.** `depth.py --model` fits every
  measurement kept to the magnitude half are found at:
  7.91 + 0.59 log10(seconds) − 2.5 log10(FWHM″) + 0.5 x sky, to about 0.3
  mag (the first night's 1 and 3 s frames are the outliers). The width and
  sky terms are fixed by physics; the other two are fitted. It predicts 5
  minutes at 4.5″ under a 19.1 sky reaching about 17.3, against 17.0 at
  today's 6.4″: **sharp focus is worth more than doubling the time.**
  `depth.py --predict --fwhm F --sky S --minutes M` gives the figure before
  a patrol: the check that says "refocus first", or "the sky is too
  bright; wait". It is planning-grade, good to the model's 0.3 mag, not an
  exact limit. The width and sky terms are held at what a perfect detector
  against the sky would give; once there are 20 independent stacks, from
  nights of different focus and sky, `depth.py --model --free` fits them
  too, and this camera and pipeline may well differ from the ideal (a sweep
  counts as one night, since its steps share its stars and sky).
- **The figures agree with each other.** The formula's 5-sigma limit and
  the planted stars' 50% point are within 0.35 mag on every stack.
- **The galaxy's glow costs little away from the core.** On M31's fainter
  and brighter glow the 50% point is within 0.1 to 0.2 mag of open sky,
  and crowding takes only 2 to 5% of planted stars: the discovery map
  (nova rate x completeness per panel) is worth making.

**Not yet a discovery completeness.** The stars are planted into the
finished stack, so this measures the star finder on that picture. It does
not test whether a nova in the raw frames survives calibration, lining up,
frame rejection, stacking, subtraction and vetting. Phase 1 plants
transients into the raw frames and runs the whole pipeline; that figure is
the real one, and may differ.

**How long a patrol visit should be is not settled by this.** Five
minutes a panel (about 17.0) against ten (17.2) trades 0.2 mag for half
the visits. Which wins depends on how many M31 novae spend how long
brighter than each limit: the scheduler should choose the length that
finds the most eruptions an hour, from these completeness curves, the
distribution of M31 novae's peak brightness and their rise and fall, and
the cadence. Five minutes is the starting point, not the answer.

**The next experiment: is the floor the camera's pattern?** Two sessions
on M31, as alike as the sky allows (same exposure, gain and time of
night, similar sky):

| | Session A | Session B |
|---|---|---|
| Calibration | bias only, as now | darks at the session's exposure and gain, and flats |
| Between frames | the mount's own drift | dithered a few pixels every few frames |

Both are measured with `depth.py --plant --sweep` and stacked to 5, 10,
30 and 60 minutes. If B keeps gaining depth past 30 minutes (17.5, 17.8)
where A flattens near 17.6, the floor was the pattern, and darks, flats
and dithering are a free gain. If B flattens too, the floor is elsewhere:
the residual galaxy glow, the stars' own crowding, or the stacking.
What it needs first: darks at 16 s and gain 1500 and a flat
(`calibrate.py`, both possible now), and dithering, which `shoot.py --dither N` now does (built 17 October
2026, proven against the simulator only).

**What to improve, for discovery, in order:** sharp focus from the motor
focuser; tracking and round stars; dark frames, flats and dithering;
then a darker site or less stray light; a filter only if a test shows it
helps the star size or sky more than it costs light; a larger telescope
last.

## What phase 1 has measured so far

**Software complete; scientific validation under way.** Everything phase 1
asked for is built and tested, the end-to-end completeness is measured
with realistic fakes, and the pipeline has rediscovered a real nova it was
not given. What it has not done yet is find something of its own on a
night of this telescope's, which only patrols can do.

Three commands, each measured on the two M31 nights (14 October as the
new night, 13 October as the reference):

- **`difference.py`: proper image subtraction.** The new stack is laid on
  the reference by the two plate solves and lined up on their shared stars
  (1,654 stars, to 0.18 pixel). The subtraction is ZOGY (Zackay, Ofek and
  Gal-Yam), done in 512-pixel squares, each with its own star shapes
  and brightness scale, because the 150P has no coma corrector and its
  stars change shape towards the corners. The score allows for the stars'
  own photon noise, the 0.18-pixel lining-up error and a 3% brightness
  error. A bright peak with a dark partner beside it is a misplaced star
  and is dropped. Each candidate is labelled with how many *fading* peaks
  are as strong: what noise and imperfect subtraction alone produce.
  Getting there took four rounds against the real frames: 335 false
  candidates with one star shape for the whole picture, 169 in squares,
  then 132, 47 and 40 as the photon and lining-up noise, the zero rows at
  a stack's edge, M32's steep glow and the pairs were dealt with.
  On those stacks it left about 40 candidates, none above 7 sigma, each
  matched by 8 or more fading peaks as strong. Most of them came from the
  stack, not the subtraction: the laptop's 14 October stack was made before
  restack.py learned to turn frames from the far side of the meridian
  whenever they line up poorly (`9c4edb2`). **Restacked with today's code,
  the same two nights leave one candidate, at 5.4 sigma: about one false
  candidate a night, before vetting, and nothing new between 13 and 14
  October.**
  Fakes planted in the finished stack are found to G 18.2 (half) and 17.6
  (90%)**, 0.9 mag deeper than phase 0's star finder on the same stack:
  the subtraction's matched filter is a better detector of a single point.
- **`plant.py`: the discovery completeness.** Fakes planted in every raw
  frame, then the whole pipeline. 300 fakes at G 15 to 19.5 were planted
  in the 226 raw frames of 14 October (225 plate-solved; one went in
  unchanged); the copy went through the quality checks (164 frames kept),
  lining up, stacking and subtraction from 13 October:

  | Planted at G | Found |
  |---|---|
  | 15.0 to 16.5 | 117 of 122 (96%) |
  | 17.0 | 22 of 25 |
  | 17.5 | 25 of 30 |
  | 18.0 | 11 of 27 |
  | 18.5 to 19.5 | 0 of 96 |

  That first run said half found at G 17.9 and 90% at 16.9, but its fakes
  were planted with the reference's zero point (13 October, 23.10) into the
  new night's frames (14 October, 22.89): each fake was 0.2 mag brighter
  than its label. Since 17 October the fakes are also realistic: each
  takes its frame's own star shape in its part of the picture (a 3 x 3
  grid, so coma and trailing come with it), its own photon noise (from the
  frame's counts per electron, measured from the sky's grain above the
  bias), and the frame's clearness (a real star dims with haze); and the
  new night's own zero point. **Measured that way, with idealised colour
  (grey) taken out of the question by the colour term below: half found at
  G 17.8, 90% at G 16.9.** Planting into the finished stack had said 18.2
  and 17.6: the whole pipeline costs 0.4 mag at half and 0.7 at 90%.
  The colour term, fitted against Gaia's BP−RP on the same night's stars,
  is −0.34 mag per mag of colour about BP−RP 0.92: the 183C sees a red star
  fainter in G than Gaia does. Planted at three colours through the whole
  pipeline:

  | Fakes' colour (BP−RP) | Half found | 90% found |
  |---|---|---|
  | blue (0.2) | G 18.1 | G 17.55 |
  | grey (0.8) | G 17.8 | G 16.89 |
  | red (1.4) | G 17.73 | G 16.89 |

  A young nova is blue near its peak, so the blue row is the one closest
  to what the patrol hunts; the grey row is the figure quoted.
  For the patrol: a nova at G 17 or brighter is caught nine times in ten
  on a night like 14 October; at 18, about four in ten. It took 10
  minutes on the desktop's 12 workers, and the same run left one
  candidate that was not a fake.
- **`vet.py`: the evidence for each candidate.** On the clean 14 October
  stack the one candidate (5.4 sigma, about G 18.2, 26′ north-east of
  M31's centre along its long axis) passed every check: in both halves of
  the night (4.8 and 4.0 sigma), no known asteroid (SkyBoT), no VSX
  variable, not on the Rochester lists, no Gaia star within 2″. Pan-STARRS
  has nothing there brighter than about 20.8. But **`forced.py`**, which
  measures the place in every stack, does not see it in the 14 October
  stack itself (fainter than G 18.0, while the difference put it at 18.2),
  nor in any other; and noise makes two peaks that strong a night. So it is
  unconfirmed and most likely noise: a clean example of what the pipeline
  hands a person, and of why a real one has to be seen again on another
  night.

  Since 17 October a Gaia star close by is a **clue, not an explanation**:
  a transient can sit beside a catalogued star, and in a crowded field 2″
  is not nothing. Only a match to something catalogued as moving, varying
  or already reported explains a candidate; a Gaia star, light already in
  the reference, or halves not checked are listed with it as clues. Being
  in one half of the night only is said as it is, and whether that sets it
  aside is the programme's rule (`both_halves = true` for the nova
  programmes: a nova lasts the night; another kind of transient might
  not).
- **`reference.py`** keeps each field's reference as a numbered version
  that is never replaced, with the nights it was made from; M31's v1 is the
  13 and 14 October stacks together (half found at G 17.61), and a night in
  it is never compared with it. A stack whose nights include or follow an
  open candidate's first night, with the candidate in its field, is
  **refused as a reference** (`--force` overrides): a real, lasting nova
  baked into the reference would subtract itself away from every night
  after. **`forced.py`** gives a place's brightness or upper limit in
  every stack of a field, and with `--difference` the light above the
  reference there, without the galaxy or the faint stars underneath:
  patrols follow candidates up that way.
- **A real nova, recovered** (`recover.py`). Fakes prove the pipeline finds
  what was put there; the test that matters is something nobody put
  there. AT2024koe (M31N 2024-06a) erupted on 8 June 2024 in M31's outer
  disc, peaked at 16.2 on 12 June and was 19.5 by 3 July. From ZTF's public
  r-band images of 21 May (before) and 27 June (on the way down), cut out
  round it, `difference.py` found it **0.27″ from its published place, at
  10.8 sigma, the strongest of the 4 candidates, at r 19.4**. The first
  try missed it: a fixed 20-pixel mask round bright stars, right on this
  rig's stacks, hid it on ZTF's sharper images; the mask now goes with the
  stars' width (2 and 4 widths), which changed nothing on this rig's
  nights and stops a real nova near a bright star being hidden. These are
  ZTF's images (1.2 m, 1″ pixels), so this proves the software, not this
  telescope's depth.

**`patrol.py` puts it together** for one field: `./patrol.py m31-novae
--plan` says whether it is ready and what it would run, `./patrol.py
m31-novae` points, images and analyses, and `--analyse SESSION` does the
analysis on a night already taken. **`candidates.py`** keeps every
candidate as an object followed from night to night, and each patrol
measures the open ones again at their places whether or not the search
found them, so a real one is seen again. One missed on three nights,
each deep enough to have shown it even had it faded 0.2 mag a day (as
fast as a quick nova near its peak), is closed as most likely noise, with
its evidence kept; a slower miss does not count. The 14 October candidate
is on file as the first.

The Transient Name Server is not asked yet: its search needs an account
(a TNS bot key), which would be the person's own.

## How a find is reported and credited

- **Novae and supernovae:** the Transient Name Server is the IAU's place
  for new transients; the first to report there is normally credited.
  Report there and to CBAT. The BAA's supernova and nova section helps
  with UK and Irish reports and can arrange confirmation.
- **Confirmation** comes from someone else's picture and, for a nova, a
  spectrum from a larger telescope. A candidate we report is an "AT"
  until it is classified.
- **Sungrazer comets:** reported through the project's form; the project
  measures them and the Minor Planet Center gives the designation.
- **Variable stars:** the AAVSO's VSX, with a light curve and, for a
  periodic star, a phase plot. VSX asks new submitters to know their way
  round light curves, and takes one submission a day.

## What could go wrong

- **False alarms.** The uncooled camera makes hot pixels; satellites
  cross the field; M31's core leaves residuals. Reporting one would be the
  opposite of the news we want. Hence the evidence record, the
  classifier's probability, and a person's eyes before anything is sent.
- **Being second.** A professional patrol may report the same nova hours
  earlier. An independent second report is still a confirmation, but not
  a discovery.
- **Weather.** Northern Ireland might give a handful of clear nights a
  month in winter. Sungrazer and the analysis of earlier frames are the
  work for the other nights.
- **Depth.** The 150P reaches about 17.0 in 5 minutes and 17.6 in 54,
  with a floor that more nights did not lower: see "What phase 0
  measured". M31 novae near their peak are within reach, but not the
  fainter half.

## Sources

- [ZTF public releases](https://www.ztf.caltech.edu/ztf-public-releases.html): the 2-night northern survey, real-time alerts, ZTF 3 to 31 December 2026
- [TNS: getting started](https://www.wis-tns.org/content/tns-getting-started): the formal discoverer is the first report made public; discovery photometry and the last non-detection
- [TNS discovery certificate for AT 2026acrv](https://www.wis-tns.org/object/2026acrv/discovery-cert): Reporting Group and Discovery Data Source shown separately
- [ZTF Bright Transient Survey](https://www.ztf.caltech.edu/ztf-bts.html): spectra of almost every non-Galactic transient brighter than 18.5, sky every 2 to 3 nights
- [Nova in M31 discovered by Bromsgrove amateur](https://britastro.org/journal_contents_ite/nova-in-m31-discovered-by-bromsgrove-amateur), BAA: George Carey, 2015
- [Rochester list of 2025 novae](https://rochesterastronomy.org/sn2025/novae.html): M33 novae at 17.3 (ATLAS) to 18.4 (Zhijian Xu and Xing Gao)
- [ATel 17011](https://www.astronomerstelegram.org/?read=17011): a nova in M81 at 19.8
- [ATel 17764](https://www.astronomerstelegram.org/?read=17764): M31N 2026-04c, 16.2, fainter than 18.4 two days before
- [ATel 17810](https://www.astronomerstelegram.org/?read=17810): M31N 2022-10c found in archive frames
- [SN 2023ixf in M101](https://britastro.org/2023/m101-sn2023ixf), BAA: Koichi Itagaki, 14.9
- [GOTO's 2025 transient discoveries](https://goto-observatory.org/2025-summary-of-goto-transient-discoveries/)
- [Planet Hunters TESS](https://science.nasa.gov/citizen-science/planet-hunters-tess/) and [ExoMiner++](https://science.nasa.gov/open-science/deep-learning-exoplanets-tess/), NASA

- [Classical novae from the POINT-AGAPE microlensing survey of M31, II](https://arxiv.org/abs/astro-ph/0509493), Darnley and others: 65 (+16/−15) novae a year, 38 in the bulge and 27 in the disc
- [AT 2025abao in M31, discovered by Koichi Itagaki](https://www.rochesterastronomy.org/sn2025/sn2025abao.html), Rochester list of supernovae and novae
- [Dedicated amateur discovers supernova in remote galaxy](https://www.universetoday.com/articles/dedicated-amateur-discovers-supernova-in-remote-galaxy), Universe Today: Filipp Romanov, AT 2025umq
- [Vera C. Rubin Observatory begins its Legacy Survey of Space and Time](https://www.astronomy.com/science/vera-c-rubin-observatory-begins-its-legacy-survey-of-space-and-time/), Astronomy
- [ASAS-SN Bright Supernova Catalogue](https://par.nsf.gov/biblio/10431061-asas-sn-bright-supernova-catalogue): depth and completeness
- [Proper image subtraction](https://arxiv.org/abs/1601.02655), Zackay, Ofek and Gal-Yam (ZOGY)
- [ZTF Science Data System explanatory supplement](https://irsa.ipac.caltech.edu/data/ZTF/docs/ztf_explanatory_supplement.pdf), IRSA
- [Fink: classification](https://doc.ztf.fink-broker.org/broker/classification/): per-alert labels, "no definitive ground truth"
- [Fritz user guide](https://docs.fritz.science/user_guide.html) and [SkyPortal](https://skyportal.io/docs/): candidate pages and follow-up
- [photutils: PSF matching](https://photutils.readthedocs.io/en/stable/user_guide/psf_matching.html)
- [SkyBoT cone search](https://ssp.imcce.fr/webservices/skybot/howto/conesearch/), IMCCE
- [Anomaly detection and expert review](https://arxiv.org/abs/2012.01419)
- [ANTARES](https://antares.noirlab.edu/faq) alert broker; [RTS2](https://rts2.org/) observatory control
- [Tycho Tracker](https://www.tycho-tracker.com/): synthetic tracking
- [The Sungrazer Project](https://sungrazer.nrl.navy.mil/) and [its tutorial](https://sungrazer.nrl.navy.mil/tutorial)
- [What do I do when I discover a new variable star?](https://aavso.org/node/74808) and [VSX policy changes](https://www.aavso.org/index.php/node/83028), AAVSO
