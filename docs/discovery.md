# Looking for something new: a specification

[Back to the README](../README.md)

Not built. This says what telescopeyoke would need to find something nobody
has reported, which hunts are worth it with a 150P, and how a find gets
checked and reported. Written 16 October 2026 from the sources at the end.

## The short answer

A discovery is possible, but only where the big robotic surveys leave gaps.
A 150 mm telescope cannot out-search them across the whole sky. In order of
promise:

1. **Novae in the Andromeda Galaxy (M31).** They peak at about magnitude 16
   to 18, which a stack of a few minutes on the 150P should reach. Amateurs
   still find them: Koichi Itagaki found AT 2025abao in M31 at magnitude
   17.8 on 17 October 2025. M31 is at +41°, outside the Rubin Observatory's
   southern survey, and stands high over Ballymoney from October to
   February. It is a 3° object, so it is a mosaic, which suits this rig.
2. **Comets in SOHO and STEREO spacecraft pictures (the Sungrazer
   Project).** No telescope and no clear sky. Volunteers have found most of
   the project's 5,204 comets. This is the likeliest discovery credit of
   all, and it can run on cloudy nights.
3. **New variable stars** in our own frames. Close to certain over a
   season of the M31 patrol, because the same fields are measured night
   after night. Small news, but a real entry in the AAVSO's catalogue.

Supernovae in other galaxies are possible but a long shot (see below).
Asteroids and comets found with the telescope itself are not realistic now.

The honest headline is "Ballymoney astronomer finds a nova in Andromeda
with an AI-driven telescope". The discovery belongs to the person who
reports it; the software is what made a nightly patrol practical.

## What the rig can reach

| | |
|---|---|
| Telescope | Sky-Watcher 150P, 750 mm, f/5 |
| Camera | 183C, 2.4 µm pixels: 0.66″ a pixel, 1.0° × 0.67° field |
| Mount | EQ3 Pro GoTo, tracking unguided |
| Depth | **Not measured.** Estimated magnitude 17.5 to 18 in 5 minutes of stacked frames. Phase 0 below measures it |
| Sky | Ballymoney, 55° N. M31 passes 14° from the zenith |

The surveys we are up against, and where they stop:

| Survey | Depth | Sky | What it leaves |
|---|---|---|---|
| ASAS-SN | g ≈ 18.5, nightly | whole sky | complete only to about 16.7 at peak; crowded galaxy centres are hard for its 8″ pixels |
| Rubin (LSST), started 30 June 2026 | far deeper | **southern sky only** | M31 and the far north; it saturates near magnitude 16 |
| Professional M31 nova patrols (Ondřejov and others) | deeper than ours | M31 | weather and gaps; a clear Ulster night when Europe is cloudy |

The edge we have is not depth. It is being out on a clear night when
others are not, watching one target every clear night, and checking
candidates fast.

## The hunts, ranked

| Hunt | Odds of a first | Uses the telescope | Effort to build | Report to |
|---|---|---|---|---|
| M31 novae | fair over a winter | yes | medium | TNS; CBAT; BAA |
| Sungrazer comets | good over months | no | small | Sungrazer Project |
| New variable stars | near certain | yes (M31 frames) | small, once M31 works | AAVSO VSX |
| Supernovae in bright galaxies | low | yes | large: many targets a night | TNS |
| Galactic novae | low | needs a camera lens | small | CBAT |
| Asteroids and comets through the telescope | very low | yes | large | MPC |

Why the long shots are long:

- **Supernovae.** ASAS-SN finds most bright ones within a day. Amateurs who
  still win, such as Itagaki, image hundreds of galaxies a night with
  0.35 to 0.6 m telescopes. The EQ3 with its handset slews slowly and has
  caught on the mount before, so a patrol of 100 galaxies a night is the
  wrong job for it. Filipp Romanov's 2025 supernova (AT 2025umq, magnitude
  20) came from a rented 0.51 m telescope.
- **Galactic novae.** These are found by people with DSLRs and 50 to
  300 mm lenses covering the whole Milky Way (John Seach, Tadashi Kojima,
  2025). Possible later with a lens on the mount, not with the 150P.
- **Asteroids.** The surveys go to magnitude 21 and fainter. A new one
  brighter than 18 is very unlikely.

## The recommended programme

**Track A, clear nights: the Andromeda patrol.** Every clear night from
October to February, image M31 as a mosaic of tiles, compare each tile with
a reference, and list anything new.

**Track B, cloudy nights: Sungrazer.** Fetch the newest SOHO LASCO C3 and
C2 pictures, look for faint moving objects heading for the Sun, and list
them for a person to check and report.

**Track C, for free: variable stars.** Every star measured on every M31
night is kept. A star that changes, and is not in VSX, is a candidate.

## What gets built

New commands, each with a test before first use, following AGENTS.md:
files under `config.DATA`, a `--json` mode with its schema in `schemas/`,
and `tests/test_interface.py` updated with it.

### `patrol.py`: the night's tiles

    ./patrol.py M31 --plan          tiles, order, exposures; moves nothing
    ./patrol.py M31                 runs it through shoot.py

- The tiles are `mosaic.py`'s panels, already kept in `mosaics/M31.json`
  as targets M31-P1, M31-P2 and so on. A plan that covers the disc and the
  bulge needs about 2 × 4 panels (`./mosaic.py M31 4x2 --replace`). Keeping
  the panel centres fixed is what lets each night be compared with the last.
- Each tile: about 20 × 15 s frames (stacked to 5 minutes), short enough
  that the bright core does not saturate.
- Moves the mount only through `mount.py`, refuses under `MOTION_LOCKED`,
  and is started by the person, like any imaging run. The order stays on
  one side of the meridian.
- Each panel's frames go where they already go, `frames/M31-P1/` and so on.

### `reference.py`: what each tile should look like

- Builds a deep reference for each tile from our own best nights (the
  first two or three clear nights of the season are spent on this).
- Can also fetch a Pan-STARRS cutout of the same field through the
  CDS hips2fits service, to catch something already bright on our first
  night.
- Kept under `config.DATA/reference/`.

### `difference.py`: what changed

- Registers the new stack onto the reference (the registration in
  `stacking.py`), matches brightness and star size, and subtracts.
- Finds sources in the difference picture above 5 sigma.
- Measures each one's magnitude against Gaia stars in the field (the
  plate solve already knows which stars they are).
- Writes a candidate list and, for each, a cut-out of new, reference and
  difference side by side.

### `vet.py`: throwing out what is not new

Each candidate is checked in this order, and the reason it was dropped is
kept:

1. **In every frame?** It must be present in at least 3 separate frames of
   the stack. Hot pixels (the camera is uncooled), cosmic rays and
   satellites fail here.
2. **Star-shaped?** Its width must match the stars around it.
3. **Not beside a bright star** or at a frame edge.
4. **Not a known asteroid:** the IMCCE SkyBoT cone search for that time
   and place.
5. **Not a known variable:** VSX and Gaia variability, by position.
6. **Not already reported:** the Transient Name Server and the Rochester
   list of M31 novae, by position.
7. **Still there later in the night,** or on the next clear night.

What survives is shown to a person, with the cut-outs and the reasons.
The AI's part is doing all of this every night without tiring; the
decision to call it real is the person's.

### `report.py`: a draft, never a send

- Drafts the report in the form TNS takes (position, time, magnitude,
  limit, the reference used) and the matching note for CBAT and the BAA.
- Prints it and saves it. Nothing is sent by the software. The person
  sends it, under their own name, from their own account.

### `sungrazer.py`: comets in spacecraft pictures

    ./sungrazer.py fetch            the last 24 hours of LASCO C3 and C2
    ./sungrazer.py look             candidates, as a movie and a list

- Takes the public SOHO pictures, removes the steady background, and looks
  for a faint spot that moves steadily over 4 or more pictures.
- Checks the Sungrazer Project's list of comets already reported.
- Shows candidates as a short movie on the status page for a person to
  watch before reporting through the project's form.

### On the status page and in `ty`

- A Candidates screen: each one's cut-outs, magnitude, the checks it
  passed, and "dismiss" or "draft report".
- `ty candidates --json`: read-only, for an agent asking "anything new
  last night?"

## Phases

| Phase | What | When | Done when |
|---|---|---|---|
| 0 | Measure the depth: stack a tile of M31 and find the faintest Gaia stars recovered | first clear night | we know the limiting magnitude |
| 1 | `sungrazer.py` | can start now; needs no sky | it finds a known recent comet in old pictures |
| 2 | `patrol.py` and `reference.py`; references for every M31 tile | October and November 2026 | a full set of references |
| 3 | `difference.py` and `vet.py` | November 2026 | it finds a known nova in our own frames, or a fake star planted in a frame |
| 4 | The nightly patrol | December 2026 to February 2027 | every clear night has a candidate list |
| 5 | Variable stars from the stored measurements | spring 2027 | first VSX submission |

The test for phase 3 matters most. A pipeline that has never found a
planted fake star cannot be trusted to have missed nothing, or to be right
when it says it found something.

## How a find is reported and credited

- **Novae and supernovae:** the Transient Name Server is the IAU's place
  for new transients; the first to report there is normally credited.
  Report there and to CBAT. The BAA's supernova and nova section helps
  with UK and Irish reports and can arrange confirmation.
- **Confirmation** comes from someone else's picture and, for a nova, a
  spectrum from a larger telescope. A candidate we report is an "AT"
  until it is classified.
- **Sungrazer comets:** reported through the project's own form; the
  project measures them and the Minor Planet Center gives the designation.
- **Variable stars:** the AAVSO's VSX, with a light curve and, for a
  periodic star, a phase plot. VSX asks new submitters to know their way
  round light curves, and takes one submission a day.

## What could go wrong

- **False alarms.** The uncooled camera makes hot pixels; satellites
  cross the field; M31's bright core leaves residuals when subtracted.
  Reporting one would be the opposite of the news we want. Hence the
  checks above, and a person's eyes before anything is sent.
- **Being second.** A professional patrol may report the same nova hours
  earlier. Being independent second is still a confirmation, but not a
  discovery.
- **Weather.** Northern Ireland might give a handful of clear nights a
  month in winter. Sungrazer is the work for the other nights.
- **The magnitude estimate is a guess** until phase 0 measures it. If the
  150P only reaches 17 in 5 minutes, M31 novae near their peak are still
  within reach, but fewer of them.

## Sources

- [AT 2025abao in M31, discovered by Koichi Itagaki](https://www.rochesterastronomy.org/sn2025/sn2025abao.html), Rochester list of supernovae and novae
- [Dedicated amateur discovers supernova in remote galaxy](https://www.universetoday.com/articles/dedicated-amateur-discovers-supernova-in-remote-galaxy), Universe Today: Filipp Romanov, AT 2025umq
- [The Sungrazer Project](https://sungrazer.nrl.navy.mil/), US Naval Research Laboratory: 5,204 comets, how to take part
- [Vera C. Rubin Observatory begins its Legacy Survey of Space and Time](https://www.astronomy.com/science/vera-c-rubin-observatory-begins-its-legacy-survey-of-space-and-time/), Astronomy: start date, southern sky
- [ASAS-SN Bright Supernova Catalogue](https://par.nsf.gov/biblio/10431061-asas-sn-bright-supernova-catalogue): depth and completeness
- [What do I do when I discover a new variable star?](https://aavso.org/node/74808), AAVSO
- [VSX policy changes](https://www.aavso.org/index.php/node/83028), AAVSO
