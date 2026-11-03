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

## The cleaned flux and the raw

PDCSAP is Kepler's cleaned light curve. The Kepler Archive Manual
(section 2.3.1.2) says the cleaning removes what correlates with the
spacecraft (pointing drift, focus changes, thermal transients) by fitting
basis vectors made from quiet stars, corrects sudden drops in a pixel's
sensitivity, and corrects for crowding, and that "in most cases" it keeps
planet transits and other astrophysical signals. So every dip is measured
in the raw SAP flux too: Tabby's four are in both, at like depths (D792
14.3% in PDCSAP, 15.1% in SAP; D1519 20.7% and 20.5%). A dip in one only
is the pipeline's doing until shown otherwise.

The cleaning, and putting each quarter on its own level, take out slow
change. With the quarters joined at their edges instead (each scaled to
meet the last day of the one before: the star is on another CCD after
each roll), Tabby's SAP flux falls 2.6% over the four years (-1.1% a
year), against the about 3% Montet & Simon (2016) measured; the PDCSAP
flux joined the same way shows +0.6%: the cleaning took the fading out.

## What it cannot see

Dips shallower than 1%: the exocomets Rappaport et al. (2018) found round
KIC 3542116 are about 0.1% deep, and a search for those needs a lower
floor and a model of the comet's shape. Stars Kepler did not watch: TESS
covers the whole sky in 27-day sectors, and is the next archive to add.
An odd light curve here is a reason to look, not a discovery: VSX, SIMBAD
and the papers on the star come before any claim.
