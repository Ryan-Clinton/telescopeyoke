# Daylight skyline survey, 3 November 2026

The morning after the night of 2 November, from ralphie-side, on the
stickered tripod spot. Linked from [validation.md](../../validation.md#3-november-2026).

## What the survey does

`./horizon.py --trace --daylight` measures the skyline (the height of roofs
and walls at each compass bearing) for the night planner. It points the
telescope at a bearing and altitude, takes a short frame and scores it as
sky, wall or an edge between them. The telescope is focused at infinity, so
anything in the garden is a featureless blur; each square of a frame is
scored for brightness next to the high sky (0.4), smoothness (0.4) and
colour next to the high sky's (0.2). It hunts up and down each bearing for
the top. By day nothing checks where the telescope really points: there are
no stars to plate-solve.

## The skyline in use before

The survey of 2 November, 15:59-16:32, was set aside (a repeat look due
north disagreed with the first) and then kept on the person's word after
they looked: house to 75° due north; north-north-east and
south-south-west open but not low; neither due east nor due south open low;
south-west 210-228° open to about 20°. In it due south is blocked to 36° and
195° to 36°.

## This morning

- 08:45-09:42, the Sun about 10-15° up in the south-east, the Sun's side
  left out. 184 looks: 122 read as sky, 38 blocked, 14 edges, 10 unread.
- At the first look the camera sent no frame ("no frame within 10 s of a
  0.011 s exposure"). The schedule started the survey again 30 s later and
  it carried on from what it had measured.
- The result was more than 6° above the checked skyline at 15 bearings, 0-45°
  in the north and 165-210° in the south. Due south (172.5° and 180°) read
  "blocked as far up as it looked" (75°), at 36°, 39°, 45°, 57° and 75°.
- Those frames were **dark**: 1-5% of the high sky's level. They are not
  glare (glare reads brighter than the sky); the saved pictures look pink
  and bright only because each is stretched for viewing.
- It replaced the skyline in use. With the south blocked to about 77° the
  planner would have lost M33 (66° up) and left M31 (76° up) barely clear.

## What the mount's axes show

Every look records the mount's raw axis angles and whether the tube came
over the pole (Dec axis above 90°).

| Bearing | Up | Dec axis | Read |
|---|---|---|---|
| 180° | 36° | 194.66 | blocked (3%) |
| 180° | 39° | 191.66 | blocked (4%) |
| 180° | 45° | 185.66 | blocked (4%) |
| 180° | 57° | 173.66 | blocked (1%) |
| 180° | 75° | 155.66 | blocked (5%) |
| 172.5° | 75° | 155.57 | blocked (4%) |
| 187.5° | 36° | 164.52 | blocked (2%) |
| 187.5° | 39° | 161.53 | blocked (3%) |
| 187.5° | 45° | 155.55 | blocked (10%) |
| 187.5° | 48° | 152.55 | edge (24% sky) |
| 187.5° | 51° | 149.56 | sky |
| 187.5° | 57° | 143.58 | sky |

The 180° and 187.5° series are 30.1° apart in Dec axis at the same height,
though only 7.5° apart in bearing, and every one of these looks was over the
pole. 180° at "75° up" sits at the Dec axis 187.5° used for 45° up, where the
roof is. 187.5° found a top at about 48°, as the person's eye did.

## Why: the pointing correction by side

The survey aims as GoTo does, correcting the mount's coordinates by the
last plate-solved pointing error kept for each side of the meridian
(`cache/pointing.json`), chosen by the target's hour angle
(`mount.load_pointing_error(hour_angle > 0)`). Last night's corrections were
east +15.59° in Dec and west -14.33°. They are that big because the mount's
home position has not been set since 20 October, and a Dec offset reverses
over the pole. The two add up to 29.9°.

172.5° and 180° (hour angle 0 or less) got the east correction and 187.5°
the west one, but the tube came over the same side for all three, so one
set was aimed about 30° wrong; from the heights, 172.5° and 180°. The code
already records which side the tube came over ("on the meridian the mount
may take either side") but does not aim by it.

The due-north disagreement that set the 2 November survey aside may be the
same fault, and so may the Moon time-lapse picture of 2 November 06:02 that
looked blocked at 147-165°, 48-51° up, where the skyline says 36-45°.

## What was changed

1. The checked skyline is back in use; this morning's survey is set aside
   in `cache/horizon-ralphie-side.not-used-20261103-094230.json`.
2. A survey that puts a top more than 6° above a skyline a person checked by
   eye is set aside, never kept (`horizon.above_checked`); it flags 15
   bearings of this one.
3. The survey reopens a jammed camera and asks for the frame again, up to 4
   times in a row (`horizon.Reopening`).
4. The live stream never goes on air for a skyline survey; this one went out
   on YouTube and Twitch.

5. Every corrected slew aims by the side the tube really came over
   (`mount.Mount.aim`, used by GoTo and the survey): after the slew the
   axes are read, and if the tube is on the other side it is sent again
   with that side's correction. A GoTo's plate-solved correction is kept
   for that side too (it was kept for the target's side, which near the
   meridian can be the other).
6. By day a look is not made when its side's correction was never
   plate-solved on that side and is over 2° (`horizon.aim_doubt`), or when
   the tube changed sides again on the second slew.
7. A bearing blocked as far up as the survey looks is warned about: a wall
   to 75° is possible, but so is an aim somewhere else.
8. A skyline replaced by a survey is kept beside it as
   `cache/horizon-SPOT.replaced-TIME.json`.

Corrections from before the handset was last set up are already ignored
(`mount.load_pointing_error`). The home position is still to be set at the
next setup, which needs a person at the handset; the large corrections
come from it. Before another whole survey: a short daylight test at a few
bearings whose tops are known (due north, 187.5°, west), on the person's
go. The 2 November survey's disagreement due north cannot be checked
against the axes: its looks did not record them.

A tube that changes sides again on the second slew is left as it is: GoTo
keeps no correction from it, and the survey makes no look. Still open:
nothing limits how big a saved correction may be, and the second slew's
place is the checked target less a correction, never checked itself; near
the meridian the second slew may swing the tube over the pole again.

## The questions as first asked

1. Choose the correction by the side the tube really came over (read the
   axes after the slew, then slew again with that side's correction), make
   the mount take a known side near the meridian, or refuse corrections
   above about 2° by day?
2. Is setting the home position at the next setup, so the corrections come
   near zero, enough on its own, or should a daylight survey check its own
   pointing (the Sun's or Moon's place, a landmark photographed by the
   person)?
3. Brightness against the high sky carries most of the score. Should a
   bearing that reads dark at every height make the survey doubt its aim,
   rather than record a wall to the top?
4. Should a survey that disagrees with the last one at many bearings always
   be set aside, even when nobody checked the old one by eye?

## Again at midday, home set

At about 11:20 the person set the mount's home again (it had been well off)
and restarted it; `./mount.py settime` retired the old corrections, so the
survey ran with none (both sides zero). 11:23-12:22, the Sun in the south
about 19° up: 136 looks, one camera jam recovered by reopening. Set aside:
back at 30°, 45° up read an edge (28% of the high sky) the first time and
sky (39%) the second, a top that close to the look's height.

Against the skyline checked by eye: the south-west 225-262.5° read open to
20°, as the person's photo showed (the checked skyline says 54°, because
the survey of 2 November avoided the low Sun there). But 270-315° read open
down to 20°, in frames up to five times as bright as the high sky, where
the house stands to 72-75°: the house wall lit by the Sun scored as sky.
Nothing was kept; `cache/horizon-ralphie-side.not-used-20261103-122252.json`.
A sunlit wall reading as sky is not yet caught: brightness cannot tell it
(the sky near the Sun read 440% too), and colour carries only 0.2 of the
score.

Since then a survey is judged bearing by bearing: a recheck that differs
with the mount's axes where they were costs only that bearing; against a
skyline checked by eye, a bearing more than 6° off either way keeps the
checked height and the rest is kept; `--use-aside FILE --bearings FROM-TO
--checked "..."` takes the bearings a person has looked at.

## Trust by point (later the same day)

Each skyline point now carries its `trust`: `eye` inside a span a person
checked (`checked_spans`, set with `./horizon.py --check-span --bearings
FROM-TO --checked "..."`), `telescope` for a top the telescope looked at,
`inferred` for corners, moved or unrechecked points. A survey is weighed
point by point (`horizon.reconcile`): less trust never replaces more, more
replaces less, and two telescope readings more than 6° apart keep the
higher. `--use-aside ... --bearings` marks what it takes as checked, joins
it at the higher top at each end, prints what the planner may use before
and after, and with `--dry-run` keeps nothing. A recheck that differs with
the axes alike is recorded as unrepeatable with no slip seen, not as a
change of light.

The person's words of 2 November 16:46 were marked as spans: house due
north (352.5-7.5°), NNE clear but not low (15-30°), due east not open low
(82.5-97.5°), due south not open low (172.5-187.5°), SSW clear but not low
(195-210°). The south-west photo (210-228° open to about 20°) does not agree
with the skyline in use (36-54°) or with the midday survey at 210-217.5°
(51-54°); they agree only at 225°, too little to take. The west 270-315°
was never checked by eye: the 72-75° in use there is the survey of
2 November, and the midday survey's 20° may be a sunlit wall or may be
right.

**The south-west photo, looked at again.** `horizon/ralphie-side/sightings/PXL_20261102_164757958.jpg`
(2 November 16:47, toward the sunset glow, the telescope in the frame)
shows trees standing high on the left, a low gap over the fence and the
distant houses in the middle, and a white rendered house filling the right
side high up. It agrees with the midday survey: 210-217.5° high (51-54°),
225-262.5° open to 20° in frames 41-56% as bright as the high sky (real low
sky), and 270-315° read "open" in frames 3.5-5.4 times as bright as the
high sky: the white house lit by the Sun. 225-262.5° was taken into the
skyline in use, open to 20°, on that photo
(`--use-aside ... --bearings 225-262.5`, with the change shown first).
The photo faces the sunset glow, about 235°, and a phone's view is about
70° wide: the white house is at its right edge, about 265-275° (an
estimate), and 285-315° is outside it. So the west is **not** settled by
eye: its 72-75° is the survey of 2 November, and the midday 20° there, in
frames 3.5-5.4 times as bright as the high sky, is most likely the same
white house lit by the Sun, but nobody has looked. It is not marked as
checked; under the rules below the planner keeps the higher until two
readings agree. The earlier "210-228°" for the photo was an estimate
from the sky map and is not used. A frame far brighter than the high sky
low down in the day is a lead for telling a lit wall from sky, now with
one photo to check it against.

## Readings, estimate and safe height (round of checks, 3 November)

A point's trust is now what is kept with it (`trust`), never read from its
description; between two points it is the weaker of the two
(`horizon.trust_at`). Each point keeps its last five `readings`, an
`estimate` (the reading most of them agree with) and `alt`, what the
planner uses: when two telescope readings differ by more than 6°, the
higher is used until two readings agree with each other and outnumber the
rest (`horizon.settle`), so a wrong top is overturned by later surveys
instead of kept for good. Each daylight look now records the parts of its
score (`features`: brightness, smoothness, colour, blue, grain), so the
weights can be tried against looks a person has labelled; the looks so far
did not record colour, so no benchmark has been made of them.

## The targeted recheck, 14:06-14:14

`./horizon.py --trace --daylight --only 30,45,52.5,165,270`, 17 looks:

| Bearing | This time | Readings now | Used |
|---|---|---|---|
| 30° | top at 51.3°, then 51.6° | repeatable this time | 54° (checked by eye) |
| 45° | open to 30° | 33°, 30° (two surveys agree) | 30° |
| 52.5° | open to 20° | 20°, 20° (settled) | 20° |
| 165° | top at 32.8° | 42°, 54°, 32.8° (no two agree) | 54°, the higher |
| 270° | top at 35.2° (an edge, not a lone opening) | 33°, 32°, 35.2° | 35.2° |

The west at 315° was not rechecked; 165° needs a fourth reading, best with
the Sun elsewhere.

**165°, 15:15-15:21**, the Sun low in the south-west, 61° away: blocked at
30°, the top at 32.7-32.9° on every look. The first recheck was still
called unrepeatable: the recheck saw the top in view (32.7°) where the
first look had bracketed it (blocked at 30°, sky at 33°), and only a plain
"sky" counted as the same answer. A top in view inside the first look's
bracket is now the same answer (the same fault had flagged 30° twice).
Run again: settled at 32.8°, the readings of 14:14 and 15:19 agreeing.
