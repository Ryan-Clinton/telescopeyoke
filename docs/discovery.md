# Looking for something new: a specification

[Back to the README](../README.md)

Not built. This says how telescopeyoke would become a small discovery
station. Each night it would choose the science worth doing, take the
pictures, look for change, look up everything it finds, and ask for another
look when that would settle a question. It would hand the person evidence,
not guesses. Written 16 October 2026 from the sources at the end.

## The short answer

A discovery is possible, but only where the big surveys leave gaps. A
150 mm telescope cannot out-search Rubin, ZTF or ATLAS across the sky.
It can compete on cadence, persistence, place and speed of follow-up. The
first programme, and the test of the whole system, is a nightly patrol of
the Andromeda Galaxy (M31) for novae:

- M31 has about 65 classical novae a year (Darnley and others, 2006: a
  range of 50 to 81). Many peak at magnitude 17 to 19, and amateurs still
  find some. Koichi Itagaki found AT 2025abao there at 17.8 on 17 October
  2025.
- M31 is at +41°, outside Rubin's survey of the southern sky, and stands
  high over Ballymoney from October to February. It is 3° across, so it is
  a mosaic, which suits this rig.

Two more programmes use the same machinery:

- **Comets in SOHO pictures (the Sungrazer Project)** for cloudy nights.
  No telescope is needed, and volunteers have found most of the project's
  5,204 comets.
- **Variable stars** from the measurements the patrol keeps anyway. A new
  one is likely over a season, but how likely is unknown until we know how
  precise our photometry is in M31's crowded field.

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
| Rubin (LSST), started 30 June 2026 | far deeper | **southern sky only** | M31 and the far north; it saturates near magnitude 16 |
| Professional M31 nova patrols (Ondřejov and others) | deeper than ours | M31 | weather and gaps; a clear Ulster night when Europe is cloudy |

## The other hunts, and why they wait

| Hunt | Odds of a first | When |
|---|---|---|
| Supernovae in bright galaxies | low: ASAS-SN finds most bright ones within a day, and amateurs who still win image hundreds of galaxies a night with 0.35 to 0.6 m telescopes | through serendipitous scanning, below; no dedicated patrol |
| Galactic novae | low: found with DSLRs and 50 to 300 mm lenses covering the Milky Way (John Seach, Tadashi Kojima, 2025) | if a camera lens is ever mounted |
| Asteroids and comets through the telescope | very low for discovery; good for recovering known ones | a later programme, `moving.py`, below |

The EQ3 has caught on the mount before, so a patrol of 100 galaxies a
night is the wrong job for it.

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
    programmes/variable-stars.toml
    programmes/sungrazer.toml

Each names its fields (for M31, `mosaic.py`'s panels), cadence, exposure,
reference, detection settings, catalogues to check, and follow-up policy.
No code says `if target == "M31"`, so M33, M81 and M82 later need only a
new file.

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

### Public alerts

Alert brokers such as Fink and ANTARES sort the surveys' alerts and pick
out ones worth following. `brokers.py` would read a filtered feed and ask,
for each: is it above our skyline tonight, bright enough for this rig,
better value than tonight's planned target, and do we have a reference?
Then: "AT xxxx is 54° high at 22:15 at about 16.7; the rig should reach
it. Take a confirmation picture?" With the person's yes, the patrol pauses,
the transient is imaged, and the patrol resumes. RTS2 shows the
observatory side of this (scheduling, weather, targets of opportunity),
and its complexity is not needed here.

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

Background removed; moving points found; tracklets scored for steady,
near-straight motion; stars and cosmic rays rejected; each candidate
shown as a short movie for a person to watch. The project's guide asks
reporters to view frames in sequence, confirm the object is a comet, and
report its pixel positions and times through the project's form under
their own name. Before fetching automatically, ask the project, and keep
the rate low. This is a good thing for the rig to do when it is cloudy,
but the headline stays "the telescope found a new source in the sky".

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

Each phase ends with a scientific proof, not just working code.

| Phase | Build | Proof |
|---|---|---|
| 0 | Depth and completeness: `measure.py`, planted fake stars | a recovery curve for each region of M31 |
| 1 | References and photometric calibration | the same star measures the same across nights |
| 2 | Proper image subtraction | planted fakes recovered reliably |
| 3 | Candidate database and forced photometry | a planted rising fake gets the right light curve |
| 4 | Vetting and catalogue checks | a known asteroid and a known variable correctly set aside |
| 5 | The M31 patrol | a known nova, past or current, recovered from our data |
| 6 | Real-or-bogus classifier | a measured fall in false candidates |
| 7 | Proposed follow-up | a candidate leads to a useful repeat observation |
| 8 | Public alerts | a real public transient observed |
| 9 | Sungrazer | a known comet recovered in archived pictures |
| 10 | Every session searched | every science picture checked automatically |

Phases 0 to 5 run through the 2026 to 2027 M31 season if the weather
allows. Sungrazer (9) needs no sky and can be built any cloudy week.

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

- [Classical novae from the POINT-AGAPE microlensing survey of M31, II](https://arxiv.org/abs/astro-ph/0509493), Darnley and others: 65 (+16/−15) novae a year
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
