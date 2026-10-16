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
  were found at magnitude 17.3 to 18.4, some by amateurs.

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

The rig's depth, estimated at magnitude 17.5 to 18 in 5 minutes, stays an
estimate until planted fake stars measure it (phase 0).

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
| Depth | **Not measured.** Estimated magnitude 17.5 to 18 in 5 minutes of stacked frames |
| Sky | Ballymoney, 55° N. M31 passes 14° from the zenith |

The surveys we are up against, and where they stop:

| Survey | Depth | Sky | What it leaves |
|---|---|---|---|
| ASAS-SN | g ≈ 18.5, nightly | whole sky | complete only to about 16.7 at peak; crowded galaxy centres are hard for its 8″ pixels |
| ZTF | deeper than ours | northern sky every 2 nights; real-time public alerts | nights between its visits, crowded centres; its current run (ZTF 3) is scheduled to 31 December 2026 |
| Rubin (LSST), started 30 June 2026 | far deeper | **southern sky only** | M31 and the far north; it saturates near magnitude 16 |
| Professional M31 nova patrols (Ondřejov and others) | deeper than ours | M31 | weather and gaps; a clear Ulster night when Europe is cloudy |

## The other hunts, and why they wait

| Hunt | Odds of a first | When |
|---|---|---|
| Novae in M81 | low for this rig: they are found near magnitude 20, one in 2025 at 19.8 in a 3000 s stack on a 0.65 m telescope | not yet |
| Supernovae in bright galaxies | low per field: ASAS-SN finds most bright ones within a day, and amateurs who still win image hundreds of galaxies a night with 0.35 to 0.6 m telescopes. But they can be bright: Koichi Itagaki found SN 2023ixf in M101 at 14.9 | through every session searched, below; no dedicated patrol |
| Galactic novae | low with the 150P's 1° field; they are found with DSLRs and 50 to 300 mm lenses covering the Milky Way (John Seach, Tadashi Kojima, 2025) | a wide-field lens node, below |
| Exoplanets in TESS data | open to volunteers: Planet Hunters TESS invites it, and NASA's open-source ExoMiner++ flagged 7,000 TESS candidates on its first run | a later cloudy-night programme |
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
| Galactic novae | clear nights, with a lens | a second camera |
| Variable stars, TESS transits | from data already held | no |

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

Priority on TNS goes to the first report made public, and a report needs
discovery photometry and, where there is one, the last non-detection. So
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

Credit is honest about where the pixels came from. TNS reports carry a
reporting group and a source group, and the discoverer is whoever's report
is made public first. A transient first seen in ZTF data and reported by us
is reported with ZTF as the source; it is not "my telescope discovered
it". Our own confirmation picture is then follow-up.

### Old pictures, searched again

Every time the subtraction, the star fitting, the classifier, the depth
measurement or the forced photometry improves, every stored frame is
searched again (`./difference.py --all-history`). Professionals do find
things this way: M31N 2022-10c, a possible symbiotic nova, was found in a
search of 2022 archive frames, with earlier detections back to 2020.

### A wide-field lens for Galactic novae, later

The 150P sees 1° × 0.67°: too little to patrol the Milky Way. A camera
with a 50 to 135 mm lens covers tens to hundreds of square degrees, and
recent Galactic novae have been found that way. It would be a second rig
(`TY_RIG`, `rigs/NAME.toml`), needing far less pointing accuracy than the
EQ3, running a Milky Way programme while the 150P works on galaxies.

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
| Measure | astrometry, photometry, depth, star size, sky for every frame | `measure.py`, existing `solve.py` and `stacking.py` |
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
| 0 | Depth and completeness: `measure.py`, planted fake stars, at 60 to 600 s | a recovery curve for each M31 region and exposure |
| 1 | References, calibration, proper subtraction, the candidate database, vetting and forced photometry for M31 | planted fakes recovered; a planted rising fake gets the right light curve; a known asteroid and a known variable set aside |
| 2 | The M31 patrol, scheduled by priority | a known nova, past or current, recovered from our data |
| 3 | M33 | a first M33 night with its completeness measured |
| 4 | Sungrazer, running all the time | a known comet recovered in archived pictures |
| 5 | The report packet | under five minutes from a confirmed planted fake to a packet |
| 6 | Public alerts (`brokers.py`) | a real public transient observed; an unreported-transient search run over a past month of alerts |
| 7 | Every session searched; old frames searched again on each improvement | every science picture checked automatically; a rerun finds fakes planted in old frames |
| 8 | Real-or-bogus classifier; proposed follow-up | a measured fall in false candidates; a candidate leads to a useful repeat |
| 9 | Variable stars; TESS transits | a first VSX submission |
| 10 | A wide-field lens rig; several rigs together | a Milky Way field patrolled; a candidate confirmed by a second rig |

Phases 0 to 2 run through the 2026 to 2027 M31 season if the weather
allows. Sungrazer needs no sky and can be built any cloudy week.

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
- **Depth.** If the 150P reaches only 17 in 5 minutes, M31 novae near
  their peak are still within reach, but fewer of them. Phase 0 finds out.

## Sources

- [ZTF public releases](https://www.ztf.caltech.edu/ztf-public-releases.html): the 2-night northern survey, real-time alerts, ZTF 3 to 31 December 2026
- [TNS: getting started](https://www.wis-tns.org/content/tns-getting-started): the discoverer is the first report made public; discovery photometry and the last non-detection
- [Nova in M31 discovered by Bromsgrove amateur](https://britastro.org/journal_contents_ite/nova-in-m31-discovered-by-bromsgrove-amateur), BAA: George Carey, 2015
- [Rochester list of 2025 novae](https://rochesterastronomy.org/sn2025/novae.html): M33 novae at 17.3 to 18.4
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
