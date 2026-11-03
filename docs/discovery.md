# Looking for something new: the discovery station

[README](../README.md) · Guides: [First night](first-night.md) · [Setup](setup.md) · [Imaging](imaging.md) · [Calibration](calibration.md) · [Focus](focus.md) · Science: [Discovery](discovery.md) · [Validation](validation.md) · [Data](data.md) · Developers: [Contributing](../CONTRIBUTING.md) · [Agents](agents/README.md)

The discovery station is operational; what remains unproven is an
original astronomical discovery with this rig:

- the software, on planted fakes and archive data: ✅
- known objects found again: ✅ a known nova in ZTF's archive, known comets
  in archived LASCO pictures, and a known Kreutz sungrazer in live GOES-19
  pictures, found by the hunt itself (19 October 2026)
- an original transient in this rig's own pictures: ❌ not yet

Each programme has its own level of proof (the table below). This says how telescopeyoke
becomes an always-on discovery station with a telescope attached, and
how far it has got (the table below; "Phases" has the detail). The design
and its reasons, what has been measured, and how a find is reported are
on their own pages (the list after the guide). On a clear night it hunts with
the telescope; on a cloudy night or by day it hunts spacecraft pictures and
public data; when a survey sees something, it decides whether this rig can
confirm or report it first; and when its methods improve, it searches its
old pictures again. It looks for change, looks up everything it finds, and
asks for another look when that would settle a question. It hands the
person evidence, not guesses. Written 16 October 2026 from the sources at
the end.

## What the project is for

One mission, two instruments. The telescope hunts what changes in the sky
(novae in M31 and M33, supernovae, new transients, the timing of
exoplanet transits, Tabby's star's level); the archives hunt what is
strange in data already taken (Kepler's and TESS's light curves for
Tabby-like dippers, Breakthrough Listen's Green Bank data for radio
technosignatures). The person is drawn to the weird and wonderful
(SETI@home, Tabby's star), so the two are weighed together each night,
in this order:

1. A watch window tonight (Tabby's proposed companion's transit).
2. A research lead still unexplained (or only likely explained) that this
   telescope can watch and is up tonight (`./ty night`'s `research`,
   `observe_tonight`): one look says whether the behaviour goes on.
3. The discovery programmes and transits, as planned.
4. Everything without the sky (the screens, the SETI sweep, the papers,
   the investigations) runs beside it on the desktop, every night and
   every cloudy day.

A fresh session gets this from `./ty context` (the mission, the research
queue, the most intriguing leads and any up tonight) and `./ty night`.

## Recent proofs

- **1-2 November 2026, M31 and M33:** the subtraction fix cut false
  candidates from 23 to 5, and the second looks found none real; `vet.py`
  now sets aside only clusters of 3 or more as residue
  ([results](discovery/results.md#m31-and-m33-patrols-1-and-2-november-2026)).

- **19 October 2026, GOES-19 CCOR-1:** the six-hourly comet hunt found a
  known Kreutz sungrazer by itself in 74 pictures, followed it for seven
  hours across a 45-minute gap, and matched it to the Sungrazer Project's
  report of it to about 2 pixels; SOHO's C3 showed it too. A weak track on
  the occulter's flickering rim was its one false alarm. Within hours the
  hunt joined tracks across gaps, set rim tracks aside, gave positions in
  the project's own frame, checked each find against the planets, bright
  stars and the project's reports, and told the person in two messages
  ([the record](discovery/comet-hunt-2026-10-19/README.md)).
- **20 October 2026, WASP-12 b:** the first exoplanet transit attempt, 973
  frames through ingress and the middle. Dimming of about the right size
  was seen and rejected as a detection: no baseline after the transit, and
  about 14 mmag per 40 s point. Measuring the same frames 288 ways showed
  why (short frames against a noisy background, the comparison stars, a
  slope with the airmass), and the next attempt has a hold on the same
  pixels, the calibration warnings and a recipe
  ([the record](discovery/transit-wasp12b-2026-10-20/README.md)).
- **20 October 2026, M31 panel 4:** a candidate from 18 October seemed to
  be seen again; measured in each night's stack with no reference involved,
  nothing was there, so the striped reference was the cause, and a
  candidate from an earlier night seen again is now sent to the person at
  once with how it was seen.

Where it stands on 20 October 2026, phase by phase:

| Phase | Software | Proved |
|---|---|---|
| 0 Depth and completeness | built | yes, on our own M31 frames; darks, flats and dithering against the noise floor still to try |
| 1 Transient pipeline | built | on archive data (AT2024koe from ZTF images); not yet a transient in our own frames |
| 2 M31 patrol | built | no: a known nova recovered from our own data is still to come |
| 3 M33 | programme and depth only | no: a night with its completeness measured is still to come |
| 4 Sungrazer | built, running every 6 hours | yes: known comets found in archived pictures, and a known Kreutz sungrazer found by the hunt itself in live CCOR-1 pictures (19 October) |
| 5 Report packet | built | the packet, yes (95 s); a claim filled in on the Transient Name Server and stopped before sending, not yet |
| 6 Public alerts | built | the month's search, yes; a public transient observed with the 150P, not yet |
| 7 Search everything again | built | not yet run as a rerun that finds fakes planted in old frames |
| 8 Real-or-bogus classifier | built (`realbogus.py`) | the fall in false candidates, yes, on planted stars: night by night 175 of 452 set aside, 98% of planted stars kept; a candidate leading to a useful repeat, not yet |
| 9 Variables, dippers, transits | built | no: no VSX submission, no transit timed yet; first attempt on WASP-12 b, 20 October 2026: dimming seen but not a detection (no baseline after it, a 20 mmag floor in the photometry; docs/discovery/transit-wasp12b-2026-10-20) |
| 10 Several telescopes | not built | needs other users |

Every result these phases keep says which code made it: the version, the
git commit and whether it had changes not committed, the libraries and a
fingerprint of the settings (records.py; schemas/provenance.schema.json).

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

## Running a discovery night

What a person does; everything else is automatic.

1. Phone alerts, once: put your Telegram bot's token and chat in
   `config.toml` under `[telegram]`, then `./notify.py --test`.
2. On a clear night, after the setup routine: `./patrol.py m31-panels
   --plan` says whether it is ready and what it would do, moving nothing.
   Then `./patrol.py m31-panels` points, images and searches each panel.
   A panel's first good night becomes its reference (`./reference.py
   M31-P3` lists them), whether it was imaged by the patrol or by
   `shoot.py` alone; every night after is searched against it. Each
   panel's final picture and search run in the background while the mount
   goes on to the next panel, and the live picture on the page is drawn in
   the background too, so the camera and the mount never wait for either.
   A subtraction whose stars did not line up with the reference (worse
   than 0.8 px, or as many dark leftovers as bright ones) is not searched:
   the answer says why, and nothing goes to the phone.
3. Anything nothing explains comes to your phone with its pictures and a
   report packet, and the patrol takes a second look: at once for a single
   field, and for a mosaic once its panels are done, going back to the
   panel. The second look dithers before its first frame, so a candidate
   lands on other pixels: a camera defect stays put on the sensor, a real
   object moves with the sky.
   `./ty candidates` lists the open ones; `./candidates.py M31-P3 --dismiss
   ID --reason LABEL` closes one that is not real.
4. To claim one, tell the agent "claim ID": it makes a fresh `./report.py
   ID`, checks the Transient Name Server, fills in the form, and you press
   send ([reporting](discovery/reporting.md)).
5. On cloudy nights: the comet hunt runs by itself every 6 hours
   (`./sungrazer.py hunt --install`, once); `./brokers.py` lists public
   transients worth a look tonight.
6. Old nights are searched again with `./patrol.py --sweep` (the last 3
   days) or `--sweep --all-history` after an improvement.
7. Fresh fields: `./ty night` lists under `other_fields` the big galaxies
   up tonight that no programme watches, and `./patrol.py FIELD` patrols
   any of them. Its first night only makes the reference; later nights
   are searched. A programme "watches" a galaxy when the galaxy's centre
   lies in one of its frames: the camera's rectangle, placed by the
   reference's own plate solve (`./reference.py NAME --locate`; `depth.py`
   keeps the solve of every stack it measures), by a mosaic's plan, or at
   the catalogue centre turned as at the last solve (`footprint.py`). A
   reference counts only when a numbered version is kept with its
   picture, not because a folder exists. The fields are ranked by what
   a watch adds tonight, each with its reasons (`why`): searchable tonight
   (a reference kept) or only giving its reference (half); days since it
   was watched, up to 20, since a supernova stays near its peak about
   three weeks, so a field watched last night adds little; how much of
   the galaxy the frame holds; and how well placed it is. No galaxy
   distances are kept, so the supernova rate is not ranked.

   On 2 November 2026 at 19:50, with the real site and data, the old
   list was M81-M82, NGC 7331, NGC 2683, NGC 147 in the planner's order
   (no reasons). The new one is NGC 2683, NGC 147, NGC 891, M74, all
   never watched. M81-M82 was watched at 02:51 that morning, and NGC
   7331 was being patrolled at 19:48, so each would add the least.
   `best_tonight` was the planner's top five (M39, M45, M81, M82, NGC 869),
   with M82 counted separately and the Double Cluster as one 14' half.
   It is now M39 (0.33 of the frame, never imaged), M45 (a 3x5 mosaic,
   imaged once, 20 days ago), M81 with M82 (one frame, 0.55), NGC 869
   with NGC 884 (the Double Cluster in one frame, never imaged) and M31
   (a 4x6 mosaic, 8 nights). Both lists come from `tonight.py`'s targets,
   which are kept above the measured skyline and its margin in darkness;
   the mount's own limits are checked when a GoTo is asked for
   (`mount.py --dry-run`), not here. Outside M31 and M33 this is a supernova watch, not a nova
   hunt: novae in M81 peak near magnitude 20, beyond this rig's G 17-18
   ([design](discovery/design.md), the table of programmes). A field with a bright supernova in it now (NGC
   7331 with SN 2026aaiv, November 2026) gets a reference holding that
   supernova: the Rochester list explains it on later nights, and the
   subtraction then sees it fade rather than arrive, which takes nothing
   away from a new one elsewhere in the galaxy. A survey picture from
   before it went off would need a different telescope's stars matched to
   ours, which the subtraction does not do.

8. What the outlook gathers besides the programmes (`./ty night`, with
   `./transits.py` and `./brokers.py` beside it, the discovery-night skill):
   - The catalogue (`data/targets.csv`, built by `build_catalogue.py` from
     OpenNGC's v20260501 release) holds what a stack reaches, not what the
     eye sees: galaxies to magnitude 12 and 1.5' or larger (1,050, from
     193 under the old eyepiece cut of 10.5), clusters and nebulae 20' or
     wider however faint, and everything the old cut kept. Each galaxy
     carries its type, and every recommendation says what the object is
     from the catalogue alone (`what`: "spiral galaxy (Sb), seen nearly
     edge-on", the edge-on or face-on from its two axes). Nothing is
     written about an object that the catalogue does not give.
   - The AAVSO Target Tool (`campaigns`): variable stars AAVSO's alerts,
     campaigns and sections ask for, kept to those measured in V or any
     filter whose range reaches between `variables.py`'s BRIGHTEST and
     FAINTEST, up in the dark here; AAVSO's high-priority ones first, then
     the most overdue for their cadence. It needs a free Target Tool
     account's key, kept in `~/.config/telescopeyoke/aavso-key` (or
     `TY_AAVSO_KEY`); without one the list is empty.
   - ExoClock (`./transits.py`): its priority for each planet (the timings
     kept for ESA's Ariel mission), the timings it has had lately, the
     smallest telescope it lists, and how many minutes tonight's predicted
     middle may be out (the ephemeris's epoch and period errors carried to
     tonight). The transits ExoClock wants timed come first.
   - The surveys' new transients (`./brokers.py`, ALeRCE): about a minute,
     so it runs in the background and its line comes when it lands. Each
     one left also carries what Lasair's Sherlock says it sits on (a
     galaxy, a nucleus, a star), the galaxy's distance and so the
     object's absolute magnitude: a supernova near its peak is -17 to
     -19.5. Lasair needs a token, kept in
     `~/.config/telescopeyoke/lasair-token` (or `TY_LASAIR_TOKEN`).
   - Comets to magnitude 12 (was 11), ten at most, each with how fast it
     moves (`motion_arcsec_min`), which sets the longest frame that keeps
     it sharp.
   - How old each outside feed's data is (`sources`): fresh, cached within
     its time, stale (an older copy kept because the source failed) or
     unavailable. A stale feed is said, never given as tonight's.

   On 3 November 2026 at 11:50, for that night with the real site and
   data, the fresh fields went from NGC 2683, NGC 147, NGC 2403, NGC 891
   to NGC 2683, NGC 3079, NGC 147, NGC 2403: NGC 3079, an edge-on barred
   spiral of magnitude 10.7, was outside the old catalogue. The big
   targets were the same (M81 with M82, M45, M39, M34, the Double
   Cluster). ExoClock listed WASP-11 b and HAT-P-16 b at low priority with
   their middles good to 0.3 minutes, and TOI-4153 b not at all.

   - Papers (`./literature.py`, and `papers` in `ty night`): arXiv's
     newest on Tabby's star, novae in M31 and M33, dipping and dimming
     stars, technosignatures and SETI, and transit timing, asked once a
     day. On 3 November 2026 its first run found two Tabby's star papers
     the project had not known: Madurga-Favieres et al. (MNRAS 550,
     stag1273, July 2026), a giant companion at 2.3 sigma with a 1.1%
     deep, ~21 h transit, and Zhu & Liu (arXiv 2610.34806, 26 October
     2026), which reads that transit as a planet with a ring.
   - A programme's dated events (`[[watch]]` in its file, with the paper
     it comes from): `ty night` says when tonight is inside a window and
     when the next one is. Tabby's file holds the companion's windows
     from the paper's Table 1: 18-23 October 2026 (the authors'
     likeliest; the star was measured on 17 October, the evening before
     it opened, and not again until 2 November), 14-16 January 2027 and
     28 February to 2 March 2027. A 1.1% dip needs each night's level to
     about 0.3%; the two nights measured so far differ by 0.22 mag, far
     more than that, so the level between nights has to be made steady
     (`precision.py`) before January's window means anything.

   Accounts held since 3 November 2026: the AAVSO Target Tool and Lasair
   (their keys in `~/.config/telescopeyoke/`, readable by their owner
   only), OccultWatcher Cloud (its predictions are read on its site) and
   the Transient Name Server (approved 3 November; its bot TelescopeYoke_bot,
   number 198068, key in `~/.config/telescopeyoke/tns-key`, lets
   `brokers.py` ask it whether a transient is already reported). Not asked: Fink, which sorts the same ZTF alerts ALeRCE
   does. The Minor Planet Center gives an observatory code only once
   measured asteroid positions from here have been sent, so there is no
   account to make for it yet.
9. Radio SETI on any day, cloudy or not: `./seti.py` searches Breakthrough
   Listen's open radio data for narrowband signals that drift as a
   transmitter on a turning planet would, and keeps only those found in
   every look at the target and none of the looks away from it
   ([seti.md](seti.md)). Tabby's star is among the stars Green Bank
   observed, so the optical watch and the radio search share a target.

What is kept, and what has to be kept to reproduce a find, is in
[data.md](data.md).

## The rest of this specification

- [Design](discovery/design.md): what the rig can reach, the hunts that
  wait, how a discovery is made as likely as possible, the seven layers it
  is built in, what could go wrong, and the sources.
- [Results](discovery/results.md): what phase 0 and phase 1 have measured,
  the comet hunt's planted comets and finds, and the variable-star
  precision.
- [Reporting](discovery/reporting.md): how a find is reported and credited.

## Phases

Ordered by what most raises the chance of a discovery soonest. Each phase
ends with a scientific proof, not just working code.

| Phase | Build | Proof |
|---|---|---|
| 0 | Depth and completeness: `depth.py`, planted fake stars, at 60 to 600 s | a recovery curve for each M31 region and exposure. **Built 16 October 2026;** [results](discovery/results.md#what-phase-0-measured) |
| 1 | References, calibration, proper subtraction, the candidate database, vetting and forced photometry for M31. **Software complete, 16 and 17 October 2026: all of it built and tested. Scientific validation under way: realistic fakes measured, a real nova recovered from archive images (AT2024koe); a find of our own still to come** | planted fakes recovered; a planted rising fake gets the right light curve; a known asteroid and a known variable set aside |
| 2 | The M31 patrol, scheduled by priority. **Built 16 and 17 October 2026: `patrol.py` for one field or M31's 4 x 2 panels, ordered by novae reported x share caught x days unwatched, fitted to the night; each panel's first night becomes its reference. Proof to come: a known nova recovered** | a known nova, past or current, recovered from our data |
| 3 | M33 | a first M33 night with its completeness measured |
| 4 | Sungrazer, running all the time. **`sungrazer.py` built 17 October 2026. A bright comet (C/2024 G3) found in archived pictures; raw LASCO and GOES-19's CCOR-1 added, fakes planted to measure the search; the 15 September 2026 Kreutz comet very likely found; CCOR-1 hunted every 6 hours (`hunt --install`)** | a known comet recovered in archived pictures |
| 5 | The report packet. **`report.py` built 17 October 2026: 95 s for a real candidate. Since then: made at once for every unexplained candidate and sent to the person's phone (`notify.py`, Telegram), a second look at the field taken while the telescope is there, and the form filled in the browser by an agent for the person to send (`docs/agents/claiming.md`)** | under five minutes from a confirmed planted fake to a packet |
| 6 | Public alerts (`brokers.py`). **Built 17 October 2026: ALeRCE's new transients, bright enough and up here tonight; the month's search run (its one real find was AT 2026aexm, already on the Transient Name Server)** | a real public transient observed; an unreported-transient search run over a past month of alerts |
| 7 | Every session searched; old frames searched again on each improvement. **Built 17 October 2026: each new stack of a field with a reference is searched in the background; `patrol.py --sweep [--all-history]` for the rest** | every science picture checked automatically; a rerun finds fakes planted in old frames |
| 8 | Real-or-bogus classifier; proposed follow-up. **Dismissal labels kept from 17 October 2026 (`candidates.py --dismiss`). `realbogus.py` built 17 October 2026: trained on stars planted in five M31 nights and on the peaks the subtraction left, tested night by night; its probability is in each vetted candidate's evidence ([results](discovery/results.md#real-or-bogus)). Since 2 November 2026 an unexplained candidate that is one of three or more within 2 arcminutes is listed as "probably residue" and not alerted (novae do not come in groups; a bad patch of the subtraction does): that night four M31 alerts were one such group. The score itself still decides nothing: its cut keeps 95% of planted stars, and a real nova must never miss its alert. The classifier never trains on "probably residue"** | a measured fall in false candidates; a candidate leads to a useful repeat |
| 9 | Variable stars, dippers like Tabby's star, and known exoplanet transits timed with the 150P. **Built 17 October 2026: `variables.py` (light curves from batches of each night's frames, against VSX, with any dip flagged), `starwatch.py tabby` (a nightly look at KIC 8462852, warning of a dip; since 3 November `archive.py` searches Kepler's light curves for other stars like it: [archive](archive.md)) and `transits.py` (tonight's whole transits from NASA's Exoplanet Archive; the depth and timing fitted from a night's frames)**. Since 20 October: `transits.py measure` gives a verdict before any fitted number, the calibration and timing checks, BJD_TDB and the exposure headroom; `precision.py` finds what limits a night's photometry; `shoot.py --hold PX` keeps the target on the same pixels | a first VSX submission; a transit timed against its prediction |
| 10 | Several telescopes together: other people's telescopeyoke rigs sharing fields and confirming each other's candidates. **Needs other users first** | a candidate confirmed by another telescope |

Phases 0 to 2 run through the 2026 to 2027 M31 season if the weather
allows. Sungrazer needs no sky and can be built any cloudy week.
