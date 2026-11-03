# Searching the Kepler archive for stars like Tabby's

`archive.py` looks for Tabby-like dips in the light curves Kepler took of
about 150,000 stars from 2009 to 2013, read straight from MAST's public
file tree and kept under `cache/kepler/`. Our own telescope watches one
star a night; the archive has four years of a space telescope's
measurements of each, so the search for another star like KIC 8462852 is
done there, and anything it finds is then a target for our own frames.

    ./archive.py dips KIC 8462852       one star's dips, each with its verdict
    ./archive.py search stars.txt       KIC numbers, one a line: the most Tabby-like first

How a dip is found and checked is in the script's own description: each
quarter's cleaned (PDCSAP) flux on its own level, a dip being three points
or more in a row below it by three times the robust scatter and by 1% at
least (`variables.py`'s rules, scaled to Kepler's precision), widened to
where the light comes back. Then the checks for what is not the star: a
dip whose faintest point sits at a quarter's end or a gap (edge), a short
dip on a spacecraft event (momentum dump, attitude tweak, safe mode),
like dips at whole multiples of one interval (an eclipsing binary or a
planet), and dips over much of the curve (the star's own variability).
What is left is a dip; a star with one 5% deep or more is Tabby-like.

## The recovery test, 3 November 2026

On Tabby's star (18 quarters, 56,346 points, scatter 0.029%) it finds the
four dips the discovery paper (Boyajian et al. 2016) is known for, and
nothing else at 1% or deeper:

| Kepler day (BKJD) | Date | Depth | Length | Verdict |
|---|---|---|---|---|
| 792.72 | 5 March 2011 | 14.3% | 78 h | dip (D792, about 15% in the paper) |
| 1519.52 | 1 March 2013 | 20.7% | 13 days with its wings | dip (D1519, about 20%) |
| 1540.38 | 21 March 2013 | 3.0% | 10 days | dip (the 2013 complex) |
| 1568.48 | 18 April 2013 | 7.7% | 69 h | dip (the 2013 complex, D1568) |

The first version called D792 the spacecraft's (Kepler fired its
thrusters every three days, so a dip of days always has a momentum dump
near it) and D1519 an edge (its wings reached a gap). Only a dip shorter
than a day can now be put on the spacecraft, and only one whose faintest
point is at a gap is an edge.

## The first search

The sample: 50 Kepler targets of magnitude 11 to 12.5 within two degrees
of Tabby's star (from NASA's Exoplanet Archive's Kepler stellar table),
Tabby's star itself, KIC 12557548 (KOI-3794, the disintegrating planet
KIC 1255 b: its dips repeat every 0.654 days) and KIC 3542116 (the
exocomets). All 53 were read (about 30 seconds a star to fetch, then a
second from the copy kept).

The first ranking put KIC 8129189 above Tabby's star: 22 dips up to 22%
deep. The Villanova Kepler eclipsing binary catalogue has it as a 53.65
day binary, eclipses 21.6% and 2.1% deep, eccentric (the secondary off
the half period), and the periodic check had wanted every dip alike at
once. It now takes each group of like depth on its own, and finds the
period at 53.64 days. Second was KIC 7988797, one 12.6% dip over 13 days,
not in the binary catalogue, but on a light curve that scatters by 4.2%:
a restless star, not a quiet one with a deep dip (Tabby's scatters by
0.03%). A Tabby-like star must now be steady to 1% between its dips.

After both fixes Tabby's star is the only Tabby-like one of the 53; next
come KIC 7987514 (nine dips, the deepest 2.6%) and KIC 7988797. KIC 1255 b
and KIC 3542116 give nothing: their dips are shallower than the 1% floor.

## Two dips alike, and the catalogues

Two dips alike in depth and length, both symmetric, may be one eclipse
seen twice, the rest of its eclipses just under the floor: they are
marked "possible repeated eclipse", their separation a period or a
multiple of it, and kept in the ranking as a lead. Two are not proof of a
period, so nothing is set aside on the light curve alone: any star with a
dip left or a possible repeat is looked up in the Villanova Kepler
eclipsing binary catalogue (its own table, 2,920 binaries over 59 pages
of keplerebs.villanova.edu, read once and kept in
`cache/kepler/villanova.json`) and in VSX by position (within 10", as
`vet.py` asks it). A star either lists as an eclipsing binary is a "known
eclipsing binary" with the catalogue's period or type, and ranks after
the leads; anything else stays a lead. Which catalogues answered is said:
on 3 November 2026 KIC 9221398 came back as the Villanova catalogue's
13.7875-day binary, and VSX did not answer in its time.

## The benchmark on real light curves

Tabby's dips must be found, known eclipsing binaries must come out
periodic, and quiet stars must give nothing. The binaries are taken from
the Villanova Kepler eclipsing binary catalogue (keplerebs.villanova.edu),
with its periods and eclipse depths; the quiet stars are three that the
first search near Tabby's star found nothing in. `tests/test_archive.py`
runs it on a kept copy of the light curves (`TY_KEPLER_CACHE=.../cache/kepler
pytest -q tests/test_archive.py -k benchmark`) and skips without one.
3 November 2026:

| Star | Catalogue | Found |
|---|---|---|
| KIC 8462852 (Tabby's) | dips D792 about 15%, D1519 about 20% | 14.3%, 20.7%, and 3.0% and 7.7% in the 2013 complex; the only Tabby-like star |
| KIC 8129189 | binary, 53.647 d, eclipses 21.6% and 2.1%, eccentric | periodic, 53.637 d; no dip left |
| KIC 10274244 | binary, 13.684 d, eclipse 19.2% | periodic, 13.649 d |
| KIC 5795648 | binary, 4.553 d, eclipse 2.3% | periodic, 4.536 d |
| KIC 9221398 | binary, 13.788 d, eclipse 1.19% | two 1.32% dips 827.25 days apart (60 periods): a possible repeated eclipse, and the catalogue check names it a known binary |
| KIC 4035675 | binary, 2.874 d, eclipse 3.8% | no dip left: its 2.1% scatter |
| KIC 7684873, 5990753 | binaries, eclipses 0.04% and 0.00% | nothing: under the 1% floor, as they should be |
| KIC 7849605, 7850078, 7917803 | quiet | nothing |

The periods found are 0.1 to 0.4% short of the catalogue's: the period
here is the shortest gap between eclipses, not a fit, which is enough to
tell a binary from a dipper and not a measurement.

## Screening every star Kepler watched

    ./archive.py screen --batch 500
    ssh desktop 'cd ~/telescopeyoke-laptop && ./archive.py screen --batch 5000'   # big batches

`screen` takes the stars Kepler watched (199,959 rows in NASA's Exoplanet
Archive's Kepler stellar table, brightest first), skips those already
screened, and keeps each answer in `cache/kepler/screened.json` every ten
stars, so a run stopped part way, or the next one, carries on from there.
Each star's light curves are deleted once screened unless it is
Tabby-like (`--keep` keeps them all): the whole archive at about 7 MB a
star would not fit. Its answer ranks everything screened so far.

Each star ends in one state: done; failed (the fetch or the file went
wrong: tried again at the start of later runs, oldest first, up to three
times in all); unavailable (MAST has no light curve of it); or excluded,
with why (fewer than 1,000 usable points). Every run, and `screen
--report` alone, gives the coverage: how many of each of the 199,959,
how many not yet, the Tabby-like, the leads, the known binaries, and the
reasons with their counts. A record kept by an earlier version (a
summary, or `missed`) is read as done or failed, and left as it is on
disk until the next screen writes it.

The first run, 3 November 2026: the 40 brightest (Kepler magnitude 5.0
upward), all read, none Tabby-like; the most dip-like was KIC 7940959,
one 1.4% dip on 0.18% scatter.

## The cleaned flux and the raw

PDCSAP is Kepler's cleaned light curve. The Kepler Archive Manual
(section 2.3.1.2) says the cleaning removes what correlates with the
spacecraft (pointing drift, focus changes, thermal transients) by fitting
basis vectors made from quiet stars, corrects sudden drops in a pixel's
sensitivity, and corrects for crowding, and that "in most cases" it keeps
planet transits and other astrophysical signals. So every dip is measured
in the raw SAP flux too: Tabby's four are in both, at like depths (D792
14.3% in PDCSAP, 14.8% in SAP; D1519 20.7% and 20.6%, SAP measured
against the light either side of each dip). A dip in one only
is the pipeline's doing until shown otherwise.

The cleaning, and putting each quarter on its own level, take out slow
change. With the quarters joined at their edges instead (each scaled to
meet the last day of the one before: the star is on another CCD after
each roll), Tabby's SAP flux falls 2.6% over the four years (-1.1% a
year), against the about 3% Montet & Simon (2016) measured; the PDCSAP
flux joined the same way shows +0.6%: the cleaning took the fading out.

## TESS

    ./archive.py tess TIC 185336364      or: tess Tabby, tess KIC 8462852 (by the TIC's own cross-match)

TESS has watched nearly the whole sky in 27-day sectors since 2018, so it
reaches the stars Kepler never saw. `tess` reads a star's SPOC 2-minute
light curves from MAST (through astroquery, installed with the
distribution's `python3-astroquery`), keeps them under `cache/tess/TIC/`,
bins them to Kepler's 30 minutes, and runs the same search and checks;
times are BTJD (BJD minus 2457000). The long-term trend is not measured:
sectors years apart cannot be joined at their edges.

On Tabby's star (TIC 185336364; sectors 14, 15, 41, 54 and 55; 5,959
binned points, scatter 0.086%) it finds one dip, on 3 September 2019
(BTJD 1730.21): 1.28% deep in PDCSAP and in SAP, 16.5 hours, nearly
symmetric (asymmetry -0.15). That is the single symmetric transit in
sector 15 that Madurga-Favieres et al. (MNRAS 550, stag1273, published 6
July 2026) put down to a giant companion, about 1.1% deep and 21 hours
long by their fit. SAP's depth is measured against the light either
side of the dip: TESS's raw flux drifts with scattered light within a
sector, and against the sector's median the same dip read 0.35%.

## What it cannot see

Dips shallower than 1%: the exocomets Rappaport et al. (2018) found round
KIC 3542116 are about 0.1% deep, and a search for those needs a lower
floor and a model of the comet's shape. A dip longer than a TESS sector,
or falling in its mid-sector gap.
An odd light curve here is a reason to look, not a discovery: VSX, SIMBAD
and the papers on the star come before any claim.
