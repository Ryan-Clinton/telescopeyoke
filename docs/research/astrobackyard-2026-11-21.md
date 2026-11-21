# AstroBackyard: what is useful to TelescopeYoke

Read 21 November 2026, from Trevor Jones's
[beginner guide](https://astrobackyard.com/beginner-astrophotography/),
[resources](https://astrobackyard.com/resources/) and
[tutorials](https://astrobackyard.com/tutorials/), and 22 of the pages they
link to on capture, calibration, focus, alignment, guiding, filters and
planning. Image processing is left out: another session has it.

These are notes in our own words, with links; the site's text and pictures
are its own and are not copied here. Its figures are one imager's practice,
much of it with a DSLR, and nothing here has been tried on this telescope.
Three pages were read only in part (the beginner guide, the deep-sky how-to
and the 7 tips): what they say past about 40,000 characters came through a
summary and is marked *(summary)*.

## Worth doing

In the order they would help this rig.

1. **Refocus during a run when the stars widen or the tube cools.** The site
   refocuses about an hour in, sooner when the temperature drops, and at
   filter changes *(deep-sky how-to, partly summary; the hourly figure on the
   focus page is from commenters)*. We refocus after a filter change
   (`filters.size_check`) and keep every focus with the focuser's temperature
   (`focus.py` `FOCUS_LOG`). On 19 November focus crept outward about 6
   half-steps a minute. **Built 21 November 2026** (`refocus.py`,
   `docs/focus.md`), not yet tried on the sky.
2. **Choose the filter by the Moon.** The site's consistent advice: broadband
   for galaxies, reflection nebulae and clusters on dark nights; Ha and OIII
   for emission nebulae, planetary nebulae and supernova remnants when the
   Moon is up. It gives no numeric threshold. **Built 21 November 2026** as
   advice in the planner (`filters.for_moon`, the Filter column). It changes
   at the point the Moon doubles the sky, a first estimate: our frames have
   only one moonlit L run to measure it from.
3. **Bias the RA balance slightly east-heavy** so the RA gears stay loaded
   against the worm ([autoguiding](https://astrobackyard.com/autoguiding/)).
   Costs nothing, needs hands at the mount, and matters while guiding is
   RA-only. The heavy side changes across the meridian, so it needs redoing
   after a flip. Nothing in the repo mentions it.
4. **Rebalance when the top dovetail goes on.** The site balances with the
   whole train fitted and the focuser at its imaging position
   ([5 ways](https://astrobackyard.com/5-ways-improve-astrophotography/)). The
   guide scope, SV241 and focuser box moving to the top dovetail will change
   both axes.
5. **Watch the guide scope's focal length if guiding stays poor.** The site's
   rule is at least a third of the imaging focal length: 250 mm for the 150P's
   750 mm. Our guide scope is 162 mm, at 9.55" a pixel as the guider bins it.
   This is a rule of thumb and centroiding works well below one pixel, so it
   is a suspect to check against the imaging frames' stars. The owner's
   Barlow is the way to try it: `docs/autoguiding.md`.

## Useful reference figures

| Topic | The site's figure | Ours |
|---|---|---|
| Flat level | about 25,000 of 65,000 ADU | 0.4 of full scale (`calibrate.flat_exposure`), the same |
| Flats | 15 to 20 or more, focus untouched | Kept valid until the camera is turned or removed |
| Darks | 15 to 20, matched on exposure, temperature, gain, offset, binning, readout | Matched on all of these |
| Bias | 20 to 40, median; unreliable on some CMOS cameras | Handled per camera (`docs/calibration.md`) |
| Stacking | Noise falls as the square root of the frames | Same |
| Integration | 30 min good, 2 h better, 6 h great; typical projects 4 to 10 h | Set by `goals.py` from measured depth |
| Guiding RMS | About 0.3" in 2" seeing, 0.5" in 2-3", 1.0" in worse than 3" (attributed to Jerry Lodriguss; the site says not to chase them) | Measured per frame (`GUIDERMS`) |
| Guide exposure | 2 to 5 s | Our guider's own setting |
| Mount load | Rated for twice the gear, about 75% of rated payload at most | The EQ3 Pro is what it is |
| Narrowband subs | 10 to 20 min, up to 10 times RGB | Limited to 120 s while the Dec drive is broken |

The site's polar alignment goal of "under 1 arcsec" *(deep-sky how-to)* reads
as a slip for arcminutes. Do not adopt it as written.

**Bortle by SQM.** The site's bands differ from `feeds.BORTLE`, for example
the faint end of class 4 is 21.29 there and 21.69 in ours. Both are
approximate and Bortle is a visual scale, so there is no case for changing
ours.

| Class | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8-9 |
|---|---|---|---|---|---|---|---|---|
| SQM from | 21.76 | 21.60 | 21.30 | 20.40 | 19.10 | 18.50 | 18.00 | below 18.00 |

**Targets by Bortle class:** 1-2 dark nebulae and faint broadband; 3-4 nearly
anything; 5-6 emission nebulae, clusters, Moon, planets, brighter galaxies
with more time; 7-9 Moon, planets, bright clusters, and emission nebulae
through narrowband.

**Symptoms** ([autoguiding](https://astrobackyard.com/autoguiding/)): star lost
means cloud, seeing or focus; calibration failing means the mount did not move
or a setting or lead is wrong; oscillation means too aggressive or too short
an exposure; elongated stars mean polar error, periodic error, wind or a
snagging cable. Check polar alignment, balance and cables before the guider.

## Seasonal targets for a mid to long focal length

From [targets by season](https://astrobackyard.com/astrophotography-targets-by-season/),
those it rates mid, mid-to-long or long, which suit 750 mm best. Its wide
targets are mosaics here (`mosaic.py`).

- **Winter:** Horsehead and Flame, Christmas Tree and Cone, Crab (M1).
- **Spring:** Leo Triplet, M51, M3, M104, Needle, M64, Markarian's Chain,
  Antennae, M13.
- **Summer:** M16, Veil, Propeller.
- **Autumn:** Helix, Pacman, Crescent, Ghost (Sh2-136), M76, M74.

## Services we do not use yet

- [Clear Outside](https://clearoutside.com/): free; cloud by layer, darkness.
  Covers the UK. A human cross-check; our forecast centres and satellite
  already cover what it would add, and `./clouds.py --scores` would have to
  show it earning a place.
- [Zoom Earth](https://zoom.earth/): satellite and radar to look at by eye.
- [Globe at Night](https://globeatnight.org/) and
  [Unihedron's SQM](https://unihedron.com/projects/darksky/): a measured sky
  brightness to compare with the `[site] sqm` setting.
- Astrospheric and Clear Sky Chart are mainly North American: no use here.

## Nothing to take

Bahtinov masks (the motor focus measures the stars), polar scope reticles and
SharpCap's polar routine (`polaralign.py` does this by plate solving), the 500
rule and fixed-tripod settings, DSLR ISO advice, t-shirt flats (we take dawn
sky flats), star trackers, smart telescopes, buying guides. Dithering: the
site says to dither every frame but gives no size or settle time, and
`shoot.py` already has both. Its planetary and Moon pages give no frame rate,
region or share of frames to keep, and `lucky.py` is well past them.
