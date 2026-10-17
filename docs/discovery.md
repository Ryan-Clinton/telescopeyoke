# Looking for something new: a specification

[README](../README.md) · Guides: [First night](first-night.md) · [Setup](setup.md) · [Imaging](imaging.md) · [Calibration](calibration.md) · [Focus](focus.md) · Science: [Discovery](discovery.md) · [Validation](validation.md) · [Data](data.md) · Developers: [Contributing](../CONTRIBUTING.md) · [Agents](agents/README.md)

Mostly built, not yet proved on the sky. This says how telescopeyoke
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

Where it stands on 17 October 2026, phase by phase:

| Phase | Software | Proved |
|---|---|---|
| 0 Depth and completeness | built | yes, on our own M31 frames; darks, flats and dithering against the noise floor still to try |
| 1 Transient pipeline | built | on archive data (AT2024koe from ZTF images); not yet a transient in our own frames |
| 2 M31 patrol | built | no: a known nova recovered from our own data is still to come |
| 3 M33 | programme and depth only | no: a night with its completeness measured is still to come |
| 4 Sungrazer | built, running every 6 hours | yes: known comets found in archived pictures |
| 5 Report packet | built | the packet, yes (95 s); a claim filled in on the Transient Name Server and stopped before sending, not yet |
| 6 Public alerts | built | the month's search, yes; a public transient observed with the 150P, not yet |
| 7 Search everything again | built | not yet run as a rerun that finds fakes planted in old frames |
| 8 Real-or-bogus classifier | labels kept only | no: too few labelled candidates to train on |
| 9 Variables, dippers, transits | built | no: no VSX submission, no transit timed yet |
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
   M31-P3` lists them); every night after is searched against it.
3. Anything nothing explains comes to your phone with its pictures and a
   report packet, and the patrol takes a second look at once.
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
| 8 | Real-or-bogus classifier; proposed follow-up. **Dismissal labels kept from 17 October 2026 (`candidates.py --dismiss`)** | a measured fall in false candidates; a candidate leads to a useful repeat |
| 9 | Variable stars, dippers like Tabby's star, and known exoplanet transits timed with the 150P. **Built 17 October 2026: `variables.py` (light curves from batches of each night's frames, against VSX, with any dip flagged), `starwatch.py tabby` (a nightly look at KIC 8462852, warning of a dip) and `transits.py` (tonight's whole transits from NASA's Exoplanet Archive; the depth and timing fitted from a night's frames)** | a first VSX submission; a transit timed against its prediction |
| 10 | Several telescopes together: other people's telescopeyoke rigs sharing fields and confirming each other's candidates. **Needs other users first** | a candidate confirmed by another telescope |

Phases 0 to 2 run through the 2026 to 2027 M31 season if the weather
allows. Sungrazer needs no sky and can be built any cloudy week.
