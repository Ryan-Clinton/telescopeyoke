# What telescopeyoke just did for you

[Back to the README](../README.md) · [From box to first galaxy](first-night.md)

You followed the first-night guide and have a picture. This page explains
what each step was, in the order you met it, and where to read more. Nothing
here is needed to use the software.

## The mount

**Equatorial mount.** A mount with two axes at right angles, tilted so that
one of them, the **RA axis** or polar axis, can be pointed at the spot the
sky turns about. Turning that one axis at the right speed follows a star all
night. The other, the **Dec axis**, sets how far from that spot the
telescope looks. The counterweight bar is the Dec axis sticking out the far
side.

**RA and Dec.** The sky's own longitude and latitude. Declination runs from
+90° at the north celestial pole to -90° at the south. Right ascension runs
round the sky and is counted in hours, 24 to the circle, because the sky
turns once in about a day. Every object has an RA and a Dec that hardly
change, which is how a catalogue can say where M31 is.

**Hour angle.** How far an object is from the line due south overhead, the
**meridian**, in hours: negative in the east, where it has yet to cross,
positive in the west. An equatorial mount really points by hour angle and
Dec; RA is hour angle plus what time it is.

**The two sides.** A telescope on this kind of mount cannot follow an object
straight through the meridian without the tube meeting the tripod. So for
objects west of the meridian the tube is swung over the top of the mount to
the other side. telescopeyoke tells you before any move that does this. It
matters for measuring too: an error in the Dec axis pushes the aim one way
on the east side and the opposite way on the west.

**Home position.** Where the mount assumes it is when switched on: bar
down, tube along the polar axis. It has no sensor for this on an EQ3; it
counts motor steps from wherever it woke up. [Calibrating a mount](calibration.md)
covers how telescopeyoke measures the real home from the stars so that you
can mark it.

**The handset's clock.** The handset needs the date, time and place to turn
RA into a direction. Its clock is often wrong, so telescopeyoke measures how
wrong and corrects every move for it, and `./mount.py settime` sets it from
the computer.

## Polar alignment

Pointing the RA axis at the celestial pole. The stars near the pole turn in
small circles about it; the Pole Star, Polaris, is about two thirds of a
degree from it. With the axis off the pole the mount follows a slightly
tilted circle, and the target creeps away, mostly in Dec.

`polaralign.py` turns the RA axis to three positions and plate-solves at
each. The three aim points lie on a circle whose centre is wherever the axis
really points. Comparing that with the true pole gives the error as two
numbers, one for each pair of bolts: left-right (azimuth) and up-down
(altitude). [The mount is wonky; measure how wonky](tracking.md) has the rest,
including what telescopeyoke does if you leave the alignment rough.

## Plate solving

Working out where a picture of the sky was taken from the stars in it. The
pattern of distances between stars is unique to each patch of sky.
telescopeyoke uses **ASTAP** for this: it is given the picture and a rough
idea of where to look, and answers with the exact RA and Dec of the
picture's centre, its scale and which way up it is.

Nearly everything clever here is a plate solve put to use:

- **A GoTo that corrects itself** (`goto --solve`): solve, compare with the
  target, move by the difference, repeat until centred.
- **Polar alignment**: three solves on a circle.
- **Finding home**: eight solves, four each side of the meridian.
- **Checking the mount really moved**: if a correction leaves the solve
  where it was, the telescope did not turn.

## Focus

**HFR, half-flux radius.** The radius of the circle that holds half of a
star's light, in pixels. A star is a point, but the air and the optics
spread it into a small blob; the better the focus, the smaller the blob. On
the author's telescope about 2 is good focus.

**Why many stars.** The air shimmers, and any one star swells and shrinks
from moment to moment. Measuring forty at once and taking the middle value
is far steadier.

**Why a ring.** Far out of focus, a star seen through a reflecting telescope
is a ring with a dark middle: the shadow of the small mirror. The aid
measures the ring's size until separate stars appear.

**Why you pass the minimum.** While the stars are still shrinking you cannot
know the smallest has been reached. Only when they start to grow again do
you know where it was. So the aid has you go through it and come back.
[Focusing by ear](focus.md) has the levels, the sounds and the timing.

## Planning

`tonight.py` works out, for your place and date: when the Sun is far enough
below the horizon for the sky to be dark; where the Moon is and how much it
brightens each part of the sky; the forecast for cloud, wind, dew and the
steadiness of the air (**seeing**); and, for every object in its catalogue,
how high it climbs, when, and whether your skyline hides it. It turns those
into one score for each object and a verdict for the night.

**Altitude** is height above the horizon in degrees: 0 at the horizon, 90
overhead. Low objects are seen through more air and more haze, so higher is
better.

## The picture

**Why short exposures.** A long exposure collects more light, but on a
modest mount the stars trail: the gears are not perfect, and a rough polar
alignment makes the target drift. Many short exposures added together
collect the same light, and any that trailed can be left out.

**Stacking.** Adding the exposures after lining them up on their stars, to a
fraction of a pixel, allowing for the picture having turned as well as
shifted. Faint detail is the same in every frame and adds up; the grain of
the sensor is different in each and averages away. Four times the frames
gives twice the clarity.

**Rejection.** Each frame is scored as it arrives: how many stars, how
sharp, how round. Frames through cloud, or taken while the mount shook, are
set aside. When the frames are combined, a pixel that is bright in one frame
only, such as a satellite's trail, is clipped out.

**The quality pass.** The live stack is made in a hurry so that you have
something to watch. Every raw frame is kept, and afterwards `restack.py`
goes back over them all with more care. Keeping the frames means a better
method later can remake an old picture.

**Calibration frames.** Pictures of nothing, used to take the camera's own
marks out of the real ones. **Darks**, with the cap on, record the glow and
hot pixels the sensor adds by itself. **Flats**, of an evenly lit surface,
record the dust shadows and dark corners of the optics. **Bias** frames
record the level the sensor reads with no light at all. `calibrate.py` makes
them and the imaging scripts apply them. [How a picture is made](imaging.md)
has all of this in detail.

## What telescopeyoke is doing differently

Most telescope software assumes each of those things has been set up
carefully by a person who knows how. This assumes it has not, measures what
is actually there, and corrects it or plans round it:

| What a first night gets wrong | What is measured | Where to read |
|---|---|---|
| Home set by eye | Where the telescope really points, by plate solve, at every GoTo; and home itself | [Calibrating a mount](calibration.md) |
| A rough polar alignment | Where the axis points; the drift it causes | [Tracking](tracking.md) |
| No autofocus | Star size, many stars at once, turned into sound | [Focusing by ear](focus.md) |
| A house in the way | Your skyline, from a phone panorama or by the telescope | The README, "What makes it different" |
| A mount that says it moved | Whether the view changed | [Calibrating a mount](calibration.md) |
| A camera that keeps poor time | The real exposure, from star trails | [Checking it under real sky](validation.md) |

`./ty characterise` lists which of these have been measured on your rig.
What has been proven on a real telescope, and what has so far run only on a
simulated one, is in [Checking it under real sky](validation.md).
