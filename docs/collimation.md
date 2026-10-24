# Collimation

The 150P is an f/5 Newtonian, and a knock or a big change of temperature
can move its primary mirror out of line. Gary collimates it with a laser.
`collimation.py` says between his visits whether it needs him, from a
defocused star, with no laser and nothing moved:

    ./ty collimation                 three frames of what the camera sees now (stars out of focus)
    ./ty collimation --file F.fits   frames already taken
    ./ty collimation --history       every check so far, from cache/collimation.jsonl

A defocused star in a Newtonian is a doughnut: a bright ring with the
secondary mirror's shadow in it. Lined up, the shadow is in the middle; out
of line, it sits to one side. The check uses the star nearest the middle of
the frame (towards the edge, coma bends the doughnuts at f/5), fits a circle
to the ring's outer edge, finds the shadow's centre, and gives the offset
as a share of the ring's radius, the median over the frames:

| Offset | Means |
|---|---|
| under 5 % | fine |
| 5 to 10 % | slightly off: fine for deep sky, worth a look before a Barlow night |
| over 10 % | off: time to have it collimated |

It also says which way the shadow sits in the frame, for whoever adjusts it.

**It runs by itself.** A walk-in (`./focus.py --walk-in`) starts from the
drawtube set a touch out by hand, where the stars are doughnuts, so it
checks the collimation on its first doughnuts and says the result, then
keeps it in the history. A check every focusing night costs nothing, and
the history shows drift over the weeks.

The doughnut must be wide enough to show its shadow, about 20 pixels or more
across; nearly focused stars give no answer. Seeing moves the shadow about
from frame to frame, which is why it takes the median of several.

Not yet tried on the sky (24 October 2026): tested on made-up doughnuts only.
