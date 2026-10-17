# Looking for something new: the design

[README](../../README.md) · Guides: [First night](../first-night.md) · [Setup](../setup.md) · [Imaging](../imaging.md) · [Calibration](../calibration.md) · [Focus](../focus.md) · Science: [Discovery](../discovery.md) · [Validation](../validation.md) · [Data](../data.md) · Developers: [Contributing](../../CONTRIBUTING.md) · [Agents](../agents/README.md)

[The discovery specification](../discovery.md)

Why each choice was made, layer by layer. Where it stands is in the
[specification](../discovery.md); what has been measured is in
[results](results.md).

## What the rig can reach

| | |
|---|---|
| Telescope | Sky-Watcher 150P, 750 mm, f/5 |
| Camera | 183C, 2.4 µm pixels: 0.66″ a pixel, 1.0° × 0.67° field |
| Mount | EQ3 Pro GoTo, tracking unguided |
| Depth | **Measured** on the stacks of 6 to 16 October 2026 ([results](results.md#what-phase-0-measured)) |
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

What the comet search has found and missed so far, with fake comets
planted to measure it, is in [results](results.md#the-comet-hunt).

### Variable stars, dippers and transits: `variables.py`, `starwatch.py`, `transits.py`

`variables.py` stacks each night's kept frames in batches and puts each
batch on Gaia's scale; what precision that reaches, and what it has
flagged, is in [results](results.md#variable-stars).

`starwatch.py tabby` is a 10-minute look at Tabby's star (KIC 8462852,
G 11.8) in 4 s frames (programmes/tabby.toml), so it does not fill the
wells; each night's level is kept, and once there are three, a night
3% or more fainter, beyond its noise, is called a dip. In October it is
74° up at 21:00, clear of the house until midnight. `transits.py` lists
the known exoplanet transits whole in the dark here tonight, around stars
of V 10.5 to 13, and fits a night's depth and timing; the first to try
is a deep one, such as HAT-P-32 b (2.2%), to prove the rig on a dip of a
known size before any ExoClock timing.

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
  measured" in [results](results.md#what-phase-0-measured). M31 novae near their peak are within reach, but not the
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
