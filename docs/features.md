# What makes it different

[README](../README.md) · [All docs](README.md) · Guides: [First night](first-night.md) · [Setup](setup.md) · [Imaging](imaging.md) · [Calibration](calibration.md) · [Focus](focus.md) · Science: [Discovery](discovery.md) · [Results](results.md) · [Validation](validation.md) · [Data](data.md) · Developers: [Contributing](../CONTRIBUTING.md) · [Agents](agents/README.md)

Most telescope software assumes a mount that has been set up carefully.
This assumes it has not, and measures what is actually there. Each section
below says, in italics, how far it has been proven; the evidence is in
[Validation](validation.md).

`./ty characterise` lists what a rig has had measured about itself so far
(the camera's real exposure, the pointing error on each side, the polar
error and how well it repeats, how the drift answers the motor, the skyline)
and the command for each thing it has not; in the application that is the
Rig knowledge screen, with a "Measure this" button on each line. Each of these
says how far it has been proven; [What has been proven](../README.md#what-has-been-proven) has the
table and [docs/validation.md](validation.md) the full account.

**Home position set by eye?** It photographs the sky, plate-solves where the
telescope really ended up, corrects, and repeats until the target is in the
middle. On its first real night an EQ3 that started about ten degrees out
centred M27 in three corrections: 107′ off, then 6′, then 1′
([the run is on the front page](../README.md#see-it-working)). And after a polar alignment it can
measure where home really is, from plate solves either side of the meridian,
drive there, and have you mark the joints, so that home is two marks lined
up from then on ([Calibrating a mount](calibration.md)). *Both are
proven under real stars: finding home took an EQ3 set 10.66° out by eye to
0.19° on the marks (17 October 2026).*

**Manual focuser?** Keep your hand on it and listen. Every frame, once it
has been measured, gives a click: your last turn has been seen. A tone
follows, higher the sharper the stars. It starts on quick binned frames,
moves by itself to many stars and then to the full sensor as focus nears,
tells you when you have passed the minimum, and says "Focus good. Hold" only
when the readings have come back and stayed on it
([Focusing by ear](focus.md)). *The star measurement has brought the
real telescope to focus; the click, tone and levels have run only on made-up
stars.*

**House and trees hiding half the garden?** Teach it your garden. Give it a
phone panorama and it finds the line between sky and everything else, lets
you redraw the line where it is wrong, and ties the picture to the compass
from two known bearings. The planner then stops recommending targets you
cannot see from that spot. Set up in more than one place? Each spot in the
garden keeps its own skyline and blocked directions: `./ty spot NAME` says
where the telescope stands tonight. The telescope can check and refine that skyline
itself, looking only where the line bends. *Proven by day: on 17 October 2026 the
telescope's own survey measured the author's garden in 34 minutes, one look
checked by eye. The skyline has been found in real panoramas too; tying one
to the compass is not yet proven.*

**Setting up before dark?** An experimental mode looks for Polaris by day,
when nothing else near the pole would show. `polaris.py` checks whether the sky, the Sun
and the focus make it worth trying, searches round the home position, proves
a candidate is a star by tipping the tube and seeing it move as the sky
should, then turns the RA axis with the star in view to find where the axis
really points and which way to move each bolt. `landmark.py` remembers a
distant chimney or aerial from a night when the mount was aligned, and by day
turns back to it to recover the azimuth. *Experimental: the search has run
on the real mount three times and has not yet found Polaris, though it did
tell sensor blemishes from stars; the rest has run only on the simulated
mount.*

**Polar alignment still rough?** By night, three plate solves measure how
far the axis is from the pole and say which way to turn each adjuster: on
the real mount, six rounds took it from 3.3° to 0.1° (13 October 2026).
That is with the measurement corrected for the handset moving the Dec axis
during it; the figures from 6 October were wrong for that reason
([validation](validation.md#night-of-13-october-2026)). It says what to do
with your hands, with a drawing of each bolt: which to turn in, about how
far, or to turn the whole tripod and by how many centimetres at the feet;
and it learns what a turn of your mount's bolts does from what you tell it
you turned. Or leave it rough:
telescopeyoke works out the declination drift that error causes, predicts it
for any other part of the sky, and creeps the Dec motor against it as a
guider would, correcting part of the error at a time and never reversing the
motor for a small overshoot ([how](tracking.md)). *The measuring is
proven on the real mount. An earlier, cruder drift correction cancelled most
of the drift there; the model that predicts it across the sky has run only
on the simulated mount.*

**Mount says it moved?** That is not proof. On one real night the motors
stopped with no sound while the handset went on reporting every move as
made, and a survey stared at one tree for half an hour. Now a GoTo whose
correction changes nothing, a polar measurement whose plate solves come back
the same, and a survey whose pictures do not change all stop with "the mount
is not moving" instead of carrying on. *Written because it happened; tried
on made-up frames, and by day it only records what it sees, after its first
real frames nearly fooled it.*

**Tracking not good enough for long exposures?** It works out the longest
exposure the mount can hold, takes many short ones, checks each as it
arrives, re-centres when the target wanders, and stacks the good ones. The
live picture is never the last word: every raw frame is kept, and the quality
pass goes back over them afterwards to choose, weight and clip, so a better
method next month can remake last night's picture
([How a picture is made](imaging.md)). *Real runs of 48 and 207 frames
have been stacked; the newest fixes have not yet been through a real run.*
